
import sqlite3, uuid, json

from pathlib import Path
DB = Path(__file__).parents[2] / "leadflow.db"
conn = sqlite3.connect(DB, timeout=30)
conn.row_factory = sqlite3.Row

# 1. Backfill tracking_ids
rows = conn.execute("SELECT id FROM outreach WHERE status='sent' AND (tracking_id IS NULL OR tracking_id='')").fetchall()
for r in rows:
    conn.execute("UPDATE outreach SET tracking_id=? WHERE id=?", (str(uuid.uuid4()), r["id"]))
print(f"tracking_id backfill: {len(rows)} rows")

# 2. Backfill subject_used
rows2 = conn.execute("SELECT id, subject_options FROM outreach WHERE status='sent' AND (subject_used IS NULL OR subject_used='')").fetchall()
for r in rows2:
    subj = "Cold Outreach"
    try:
        opts = json.loads(r["subject_options"] or "[]")
        if isinstance(opts, list) and opts: subj = opts[0]
        elif isinstance(opts, str) and opts: subj = opts
    except: pass
    conn.execute("UPDATE outreach SET subject_used=? WHERE id=?", (subj, r["id"]))
print(f"subject_used backfill: {len(rows2)} rows")

# 3. Deal for replied leads
replied = conn.execute("SELECT b.id, b.name FROM businesses b WHERE b.status='replied' AND NOT EXISTS (SELECT 1 FROM deals d WHERE d.business_id=b.id)").fetchall()
for r in replied:
    conn.execute("INSERT INTO deals (business_id, value_usd, service, notes, created_at) VALUES (?, 0, 'Web Design', 'Auto-created on reply', datetime('now'))", (r["id"],))
    print(f"Deal created: {r['name']}")

conn.commit()
conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
conn.close()
print("DB startup fixes done")
