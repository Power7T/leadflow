"""
Assigns a scheduled_at UTC timestamp to every draft outreach record.

Logic:
  - Uses business.timezone (already stored on most leads)
  - Picks a random slot in the optimal window: 9:00–11:30 AM local time,
    Mon–Fri. If today's slot is already past, schedules for tomorrow.
  - Spreads sends: adds 0–90 min jitter so not all go at exactly 9:00.
  - Skips records that already have a scheduled_at.
"""
import sqlite3
import random
from datetime import datetime, timedelta
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

DB = Path(__file__).parents[2] / "leadflow.db"

# Optimal local send window
WINDOW_START_H = 9    # 9 AM
WINDOW_END_H   = 11   # up to 11:30 AM (30-min jitter added)
WINDOW_JITTER_MINUTES = 90  # random offset within window

def next_send_slot(tz_str: str) -> datetime:
    """
    Returns next UTC datetime that falls in the 9–11:30 AM Mon–Fri window
    for the given timezone. Adds random minute jitter so sends are spread.
    """
    try:
        tz = ZoneInfo(tz_str)
    except Exception:
        tz = ZoneInfo("America/New_York")  # safe fallback

    jitter = random.randint(0, WINDOW_JITTER_MINUTES)
    now_local = datetime.now(tz)

    # Build candidate: today at 9 AM + jitter
    candidate = now_local.replace(
        hour=WINDOW_START_H,
        minute=jitter % 60,
        second=random.randint(0, 59),
        microsecond=0
    )

    # If we've already passed today's window end (11:30), push to next day
    window_end_today = now_local.replace(hour=WINDOW_END_H, minute=30, second=0, microsecond=0)
    if now_local >= window_end_today:
        candidate += timedelta(days=1)

    # Skip weekends
    days_tried = 0
    while candidate.weekday() >= 5 and days_tried < 7:  # 5=Sat, 6=Sun
        candidate += timedelta(days=1)
        days_tried += 1

    # Convert to UTC
    return candidate.astimezone(ZoneInfo("UTC"))


conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

# Step 1: Add scheduled_at column if missing
existing_cols = [r[1] for r in conn.execute("PRAGMA table_info(outreach)").fetchall()]
if "scheduled_at" not in existing_cols:
    conn.execute("ALTER TABLE outreach ADD COLUMN scheduled_at TEXT DEFAULT NULL")
    conn.commit()
    print("✅ Added scheduled_at column to outreach table")
else:
    print("ℹ️  scheduled_at column already exists")

# Step 2: Fetch all draft outreach that don't have a scheduled_at yet
rows = conn.execute("""
    SELECT o.id, o.business_id, o.channel,
           b.timezone, b.city, b.country, b.name
    FROM outreach o
    JOIN businesses b ON b.id = o.business_id
    WHERE o.status = 'draft'
      AND (o.scheduled_at IS NULL OR o.scheduled_at = '')
""").fetchall()

print(f"\nAssigning scheduled_at to {len(rows)} draft outreach records...\n")

tz_slot_cache = {}  # tz_str -> list of slots (to spread across the hour)
updated = 0
errors = 0

for row in rows:
    tz_str = row["timezone"] or "America/New_York"

    # Generate slot (with randomness per record)
    try:
        slot_utc = next_send_slot(tz_str)
        slot_str = slot_utc.strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "UPDATE outreach SET scheduled_at=? WHERE id=?",
            (slot_str, row["id"])
        )
        updated += 1
        if updated <= 15 or updated % 50 == 0:
            # Show local time for human readability
            try:
                tz = ZoneInfo(tz_str)
                local = slot_utc.astimezone(tz)
                local_str = local.strftime("%Y-%m-%d %H:%M %Z")
            except Exception:
                local_str = slot_str
            print(f"  [{updated}] out:{row['id']} | {row['name'][:30]:30s} | "
                  f"tz={tz_str:25s} | send @ {local_str} local ({slot_str} UTC)")
    except Exception as e:
        print(f"  ❌ out:{row['id']} {row['name']}: {e}")
        errors += 1

conn.commit()
conn.close()
print(f"\n✅ Done. Assigned scheduled_at to {updated} outreach records. Errors: {errors}")
