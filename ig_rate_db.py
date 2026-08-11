"""
ig_rate_db.py — Database layer for Instagram automation rate limiting & follow tracking.

Tables managed:
  ig_rate_state   — persists the rate limiter state machine (state, block count, timestamps)
  ig_follow_log   — tracks every follow/DM/unfollow action for ghost cleanup + analytics

Also runs migrations on the `businesses` table to add:
  ig_followed_at        — when we followed them
  ig_follows_us_back    — 1 if verified they follow us, 0 if not, NULL if unchecked
  ig_followback_checked — last time we checked their followers list for our username
"""

import sqlite3
import logging
from datetime import datetime
from pathlib import Path

log = logging.getLogger("ig_rate_db")

DB_PATH = str(Path(__file__).parent / "leadflow.db")

# ── Schema migration ────────────────────────────────────────────────────────

_MIGRATIONS = [
    # ig_rate_state: persists rate limiter state across sessions
    """
    CREATE TABLE IF NOT EXISTS ig_rate_state (
        id          INTEGER PRIMARY KEY DEFAULT 1,
        state       TEXT    NOT NULL DEFAULT 'WARMING_UP',
        block_count INTEGER NOT NULL DEFAULT 0,
        last_block_at   TEXT,
        last_action_at  TEXT,
        pairs_today     INTEGER NOT NULL DEFAULT 0,
        today_date      TEXT,
        warmup_day      INTEGER NOT NULL DEFAULT 1,
        cooldown_until  TEXT,
        frozen_until    TEXT,
        updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,

    # ig_follow_log: tracks individual follow/DM/unfollow events
    """
    CREATE TABLE IF NOT EXISTS ig_follow_log (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        business_id INTEGER,
        username    TEXT NOT NULL,
        action      TEXT NOT NULL,  -- 'follow', 'dm', 'unfollow', 'skip_no_msg_btn', 'skip_blocked'
        detail      TEXT,
        created_at  TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (business_id) REFERENCES businesses(id)
    )
    """,
]

# Columns to add to existing `businesses` table
_BUSINESS_COLUMNS = [
    ("ig_followed_at",        "TEXT"),
    ("ig_follows_us_back",    "INTEGER"),        # 1=yes, 0=no, NULL=unchecked
    ("ig_followback_checked", "TEXT"),            # last check timestamp
]


def _column_exists(conn, table, column):
    """Check if a column already exists in a table."""
    cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    return column in cols


def migrate():
    """Run all migrations idempotently."""
    conn = sqlite3.connect(DB_PATH, timeout=15)
    try:
        for sql in _MIGRATIONS:
            conn.execute(sql)

        for col_name, col_type in _BUSINESS_COLUMNS:
            if not _column_exists(conn, "businesses", col_name):
                conn.execute(f"ALTER TABLE businesses ADD COLUMN {col_name} {col_type}")
                log.info(f"Added column businesses.{col_name} ({col_type})")

        # Ensure at least one row exists in ig_rate_state
        row = conn.execute("SELECT id FROM ig_rate_state WHERE id=1").fetchone()
        if not row:
            conn.execute("""
                INSERT INTO ig_rate_state (id, state, block_count, pairs_today, today_date, warmup_day)
                VALUES (1, 'WARMING_UP', 0, 0, date('now'), 1)
            """)

        conn.commit()
        log.info("ig_rate_db: migrations complete.")
    finally:
        conn.close()


# ── Rate State helpers ──────────────────────────────────────────────────────

def get_rate_state() -> dict:
    """Load the current rate limiter state from DB."""
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM ig_rate_state WHERE id=1").fetchone()
        return dict(row) if row else {}
    finally:
        conn.close()


def update_rate_state(**kwargs):
    """Update rate limiter state. Pass column=value pairs."""
    if not kwargs:
        return
    kwargs["updated_at"] = datetime.now().isoformat()
    cols = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values())
    conn = sqlite3.connect(DB_PATH, timeout=15)
    try:
        conn.execute(f"UPDATE ig_rate_state SET {cols} WHERE id=1", vals)
        conn.commit()
    finally:
        conn.close()


# ── Follow log helpers ──────────────────────────────────────────────────────

def log_action(username: str, action: str, business_id: int = None, detail: str = None):
    """Record a follow/DM/unfollow/skip event."""
    conn = sqlite3.connect(DB_PATH, timeout=15)
    try:
        conn.execute(
            "INSERT INTO ig_follow_log (business_id, username, action, detail) VALUES (?,?,?,?)",
            (business_id, username, action, detail)
        )
        conn.commit()
    finally:
        conn.close()


def get_todays_pair_count() -> int:
    """How many follow+DM pairs have we completed today?"""
    conn = sqlite3.connect(DB_PATH, timeout=15)
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM ig_follow_log WHERE action='dm' AND date(created_at)=date('now')"
        ).fetchone()
        return row[0] if row else 0
    finally:
        conn.close()


def get_pending_ghosts(min_days: int = 7):
    """Find businesses we followed 7+ days ago that haven't replied and aren't unfollowed."""
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        # Uses ig_followed_at if set, otherwise falls back to ig_dm_sent_at
        query = """
            SELECT b.id, c.instagram,
                   COALESCE(b.ig_followed_at, b.ig_dm_sent_at) as followed_at,
                   b.ig_follows_us_back,
                   b.replied_at
            FROM businesses b
            JOIN contacts c ON c.business_id = b.id
            WHERE b.ig_dm_sent = 1
              AND b.ig_unfollowed = 0
              AND c.instagram IS NOT NULL
              AND c.instagram != ''
              AND COALESCE(b.ig_followed_at, b.ig_dm_sent_at) < datetime('now', ? || ' days')
        """
        rows = conn.execute(query, (f"-{min_days}",)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_silent_followbacks(min_days: int = 14):
    """Find businesses that follow us back but never replied after 14+ days."""
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        query = """
            SELECT b.id, c.instagram,
                   COALESCE(b.ig_followed_at, b.ig_dm_sent_at) as followed_at
            FROM businesses b
            JOIN contacts c ON c.business_id = b.id
            WHERE b.ig_dm_sent = 1
              AND b.ig_unfollowed = 0
              AND b.ig_follows_us_back = 1
              AND b.replied_at IS NULL
              AND c.instagram IS NOT NULL
              AND COALESCE(b.ig_followed_at, b.ig_dm_sent_at) < datetime('now', ? || ' days')
        """
        rows = conn.execute(query, (f"-{min_days}",)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def mark_followed(business_id: int, username: str):
    """Record that we just followed this business."""
    conn = sqlite3.connect(DB_PATH, timeout=15)
    try:
        conn.execute(
            "UPDATE businesses SET ig_followed_at=datetime('now') WHERE id=?",
            (business_id,)
        )
        conn.commit()
    finally:
        conn.close()
    log_action(username, "follow", business_id)


def mark_followback(business_id: int, follows_us: bool):
    """Record the result of checking if someone follows us back."""
    conn = sqlite3.connect(DB_PATH, timeout=15)
    try:
        conn.execute(
            "UPDATE businesses SET ig_follows_us_back=?, ig_followback_checked=datetime('now') WHERE id=?",
            (1 if follows_us else 0, business_id)
        )
        conn.commit()
    finally:
        conn.close()


def mark_unfollowed(business_id: int, username: str, reason: str = "ghost"):
    """Mark business as unfollowed."""
    conn = sqlite3.connect(DB_PATH, timeout=15)
    try:
        conn.execute(
            "UPDATE businesses SET ig_unfollowed=1 WHERE id=?",
            (business_id,)
        )
        conn.commit()
    finally:
        conn.close()
    log_action(username, "unfollow", business_id, detail=reason)


def get_dm_candidates(limit: int = 20):
    """Get businesses eligible for follow+DM (not yet DMed, have IG handle)."""
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        query = """
            SELECT b.id, b.name, b.city, b.category, c.instagram,
                   b.gap, b.pitch_type, b.ig_dm_variant
            FROM businesses b
            JOIN contacts c ON c.business_id = b.id
            WHERE b.ig_dm_sent = 0
              AND c.instagram IS NOT NULL
              AND c.instagram != ''
            ORDER BY b.lead_score DESC
            LIMIT ?
        """
        rows = conn.execute(query, (limit,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    migrate()
    state = get_rate_state()
    print(f"Rate state: {state}")
    print(f"Today's pairs: {get_todays_pair_count()}")
    ghosts = get_pending_ghosts()
    print(f"Pending ghosts (7+ days): {len(ghosts)}")
    silent = get_silent_followbacks()
    print(f"Silent followbacks (14+ days): {len(silent)}")
    candidates = get_dm_candidates(5)
    print(f"DM candidates (next 5): {[c['instagram'] for c in candidates]}")
