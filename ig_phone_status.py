"""
ig_phone_status.py — Phone Status Tracker + Overlay Module

Tracks WHO is controlling the Vivo phone and WHAT it's doing right now.
Visible in three places:
  1. Vivo phone itself — via ntfy notification (phone subscribes to topic)
  2. Mac dashboard (localhost:8765) — via /api/phone-status endpoint
  3. Firestick dashboard (same server via Silk browser) — same endpoint

Uses SQLite for session tracking + activity log.
Uses ntfy.sh for push notifications to the phone.
"""

import os
import time
import sqlite3
import logging
import requests
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

log = logging.getLogger("ig_phone_status")

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "leadflow.db")
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "leadflow-chandan-secret")
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"

# Phone-specific ntfy topic — phone subscribes to this for overlay-style alerts
PHONE_STATUS_TOPIC = f"{NTFY_TOPIC}-phone-status"
PHONE_STATUS_URL = f"https://ntfy.sh/{PHONE_STATUS_TOPIC}"


# ── Database ────────────────────────────────────────────────────────────────

def migrate():
    """Create phone status tables if they don't exist."""
    conn = sqlite3.connect(DB_PATH, timeout=15)
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS ig_phone_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                controller TEXT NOT NULL,
                started_at TEXT NOT NULL DEFAULT (datetime('now')),
                ended_at TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                summary TEXT
            );

            CREATE TABLE IF NOT EXISTS ig_phone_activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER,
                action TEXT NOT NULL,
                detail TEXT,
                target_username TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (session_id) REFERENCES ig_phone_sessions(id)
            );

            CREATE INDEX IF NOT EXISTS idx_phone_sessions_status
                ON ig_phone_sessions(status);
            CREATE INDEX IF NOT EXISTS idx_phone_activity_session
                ON ig_phone_activity(session_id);
            CREATE INDEX IF NOT EXISTS idx_phone_activity_created
                ON ig_phone_activity(created_at DESC);
        """)
        conn.commit()
    finally:
        conn.close()


def _get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


# ── Session management ──────────────────────────────────────────────────────

def start_session(controller: str) -> int:
    """Start a new phone control session.

    Args:
        controller: Who is controlling the phone, e.g.
                    'ig_session_runner', 'ig_ghost_cleanup', 'manual'

    Returns:
        Session ID
    """
    migrate()

    # End any stale sessions first
    _end_stale_sessions()

    conn = _get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO ig_phone_sessions (controller, status) VALUES (?, 'active')",
            (controller,)
        )
        session_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    log.info(f"📱 Phone session started: {controller} (session #{session_id})")

    # Notify phone + dashboard
    _notify_phone(f"📱 {_friendly_name(controller)} started", "Phone is now being automated")
    _notify_main(f"📱 Phone control: {_friendly_name(controller)}", "Session started")

    return session_id


def end_session(session_id: int, summary: str = None):
    """End a phone control session."""
    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE ig_phone_sessions SET ended_at=datetime('now'), status='ended', summary=? WHERE id=?",
            (summary, session_id)
        )
        conn.commit()
    finally:
        conn.close()

    log.info(f"📱 Phone session ended: #{session_id} — {summary or 'done'}")

    _notify_phone("📱 Phone released", summary or "Automation finished")
    _notify_main("📱 Phone released", summary or "Session ended")


def _end_stale_sessions():
    """Close any sessions that have been active for more than 2 hours (likely crashed)."""
    conn = _get_conn()
    try:
        stale = conn.execute("""
            UPDATE ig_phone_sessions
            SET ended_at=datetime('now'), status='stale', summary='Auto-closed (stale > 2h)'
            WHERE status='active'
              AND started_at < datetime('now', '-2 hours')
        """)
        if stale.rowcount > 0:
            log.warning(f"Closed {stale.rowcount} stale phone session(s)")
        conn.commit()
    finally:
        conn.close()


# ── Activity logging ────────────────────────────────────────────────────────

def update_activity(action: str, detail: str = None, target_username: str = None,
                    session_id: int = None, notify_phone: bool = True):
    """Log a phone activity and optionally push to phone overlay.

    Args:
        action: What's happening — 'follow', 'dm', 'unfollow', 'check_follower',
                'open_profile', 'typing', 'block_detected', 'error', 'idle'
        detail: Human-readable detail (e.g. "Sending DM to @shopname")
        target_username: The IG handle being interacted with
        session_id: Link to active session (auto-detected if None)
        notify_phone: Push ntfy notification to phone (default True)
    """
    if session_id is None:
        session_id = get_active_session_id()

    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO ig_phone_activity (session_id, action, detail, target_username) VALUES (?, ?, ?, ?)",
            (session_id, action, detail, target_username)
        )
        conn.commit()
    finally:
        conn.close()

    # Build notification message
    emoji = _action_emoji(action)
    msg = f"{emoji} {detail or action}"
    if target_username:
        msg = f"{emoji} @{target_username.lstrip('@')}: {detail or action}"

    log.debug(f"Phone activity: {msg}")

    if notify_phone and action not in ('idle',):
        _notify_phone(msg, priority="low")


# ── Query helpers (for dashboard API) ───────────────────────────────────────

def get_active_session() -> dict | None:
    """Get the current active phone session, if any."""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM ig_phone_sessions WHERE status='active' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_active_session_id() -> int | None:
    """Get just the session ID of the active session."""
    session = get_active_session()
    return session["id"] if session else None


def get_recent_activity(limit: int = 20) -> list[dict]:
    """Get recent phone activity log entries."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM ig_phone_activity ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_phone_status() -> dict:
    """Full phone status payload for the dashboard API."""
    session = get_active_session()
    activity = get_recent_activity(limit=15)

    # Get today's stats
    conn = _get_conn()
    try:
        today_stats = conn.execute("""
            SELECT
                COUNT(CASE WHEN action='follow' THEN 1 END) as follows_today,
                COUNT(CASE WHEN action='dm' THEN 1 END) as dms_today,
                COUNT(CASE WHEN action='unfollow' THEN 1 END) as unfollows_today,
                COUNT(CASE WHEN action='block_detected' THEN 1 END) as blocks_today
            FROM ig_phone_activity
            WHERE created_at >= date('now')
        """).fetchone()

        # Last activity timestamp
        last_activity = conn.execute(
            "SELECT created_at FROM ig_phone_activity ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()

    # Resolve current Vivo phone IP
    vivo_ip = _get_vivo_ip()

    return {
        "is_active": session is not None,
        "controller": session["controller"] if session else None,
        "controller_friendly": _friendly_name(session["controller"]) if session else None,
        "session_started": session["started_at"] if session else None,
        "last_activity": last_activity["created_at"] if last_activity else None,
        "activity_log": activity,
        "vivo_ip": vivo_ip,
        "today": {
            "follows": today_stats["follows_today"] if today_stats else 0,
            "dms": today_stats["dms_today"] if today_stats else 0,
            "unfollows": today_stats["unfollows_today"] if today_stats else 0,
            "blocks": today_stats["blocks_today"] if today_stats else 0,
        }
    }


# ── ntfy notification helpers ───────────────────────────────────────────────

def _notify_phone(message: str, detail: str = None, priority: str = "default"):
    """Send ntfy notification to the PHONE-specific topic.

    The Vivo phone subscribes to this topic via the ntfy app,
    which shows as a persistent notification / overlay.
    """
    try:
        headers = {
            "Title": message[:120],
            "Priority": priority,
            "Tags": "iphone",
        }
        body = detail or message
        requests.post(PHONE_STATUS_URL, data=body.encode("utf-8"),
                      headers=headers, timeout=5)
    except Exception as e:
        log.debug(f"Phone ntfy notification failed: {e}")


def _notify_main(title: str, message: str):
    """Send ntfy notification to the main LeadFlow topic (Mac/Firestick)."""
    try:
        headers = {
            "Title": title[:120],
            "Priority": "low",
            "Tags": "robot_face",
        }
        requests.post(NTFY_URL, data=message.encode("utf-8"),
                      headers=headers, timeout=5)
    except Exception as e:
        log.debug(f"Main ntfy notification failed: {e}")


# ── Helpers ─────────────────────────────────────────────────────────────────

def _get_vivo_ip() -> str:
    """Resolve current Vivo phone IP from ~/.vivo_ip → local fallback."""
    ip_file = Path(os.path.expanduser("~/.vivo_ip"))
    if ip_file.exists():
        ip = ip_file.read_text().strip()
        if ip:
            return ip
    local_file = Path(__file__).parent / ".vivo_ip"
    if local_file.exists():
        ip = local_file.read_text().strip()
        if ip:
            return ip
    return "192.168.8.157:5555"


def _friendly_name(controller: str) -> str:
    """Convert controller ID to human-readable name."""
    names = {
        "ig_session_runner": "Follow+DM Bot",
        "ig_ghost_cleanup": "Ghost Cleanup",
        "ig_reply_responder": "Reply Checker",
        "manual": "Manual Control",
        "scheduler": "Scheduler",
    }
    return names.get(controller, controller or "Unknown")


def _action_emoji(action: str) -> str:
    """Emoji prefix for each action type."""
    emojis = {
        "follow": "👤",
        "dm": "💬",
        "unfollow": "👋",
        "check_follower": "🔍",
        "open_profile": "📱",
        "typing": "⌨️",
        "send": "📤",
        "block_detected": "🚫",
        "error": "❌",
        "idle": "💤",
        "unlock_screen": "🔓",
        "acquire_lock": "🔒",
        "release_lock": "🔓",
        "start": "▶️",
        "complete": "✅",
        "skip": "⏭️",
    }
    return emojis.get(action, "📍")


# ── CLI entry point ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    migrate()

    if len(sys.argv) > 1 and sys.argv[1] == "--status":
        status = get_phone_status()
        if status["is_active"]:
            print(f"📱 Phone controlled by: {status['controller_friendly']}")
            print(f"   Session started: {status['session_started']}")
        else:
            print("📱 Phone is idle (no active session)")
        print(f"\nToday: {status['today']['follows']} follows, "
              f"{status['today']['dms']} DMs, "
              f"{status['today']['unfollows']} unfollows, "
              f"{status['today']['blocks']} blocks")
        if status["activity_log"]:
            print(f"\nRecent activity:")
            for a in status["activity_log"][:10]:
                emoji = _action_emoji(a["action"])
                target = f"@{a['target_username']}" if a.get("target_username") else ""
                print(f"  {a['created_at']} {emoji} {a['action']} {target} — {a.get('detail', '')}")
    elif len(sys.argv) > 1 and sys.argv[1] == "--test":
        print("Testing phone status notifications...")
        sid = start_session("manual")
        update_activity("open_profile", "Testing phone overlay", target_username="testuser", session_id=sid)
        time.sleep(2)
        update_activity("follow", "Followed test user", target_username="testuser", session_id=sid)
        time.sleep(2)
        end_session(sid, "Test complete — 1 follow, 0 DMs")
        print("Done! Check ntfy notifications on phone.")
    else:
        print("Usage:")
        print("  python3 ig_phone_status.py --status   # Show current phone status")
        print("  python3 ig_phone_status.py --test     # Send test notifications")
