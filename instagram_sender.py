"""
instagram_sender.py — Safe, rate-limited Instagram DM sender for LeadFlow.

Safety rules (to NEVER get the account banned or deleted):
  - Max 20 DMs per calendar day (Instagram unofficial limit ~50, we use 20)
  - 45-120 second random delay between each DM (human-like pacing)
  - Session saved to disk — no fresh login every time (fresh logins = suspicious)
  - All errors caught and logged — never crashes the scheduler

Setup:
  Add to .env:
    INSTAGRAM_USERNAME=your_username
    INSTAGRAM_PASSWORD=your_password
"""

import os
import json
import time
import random
import logging
from datetime import date
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("leadflow.instagram")

# ── Config ──────────────────────────────────────────────────────────────────
DAILY_LIMIT       = 20           # Max DMs per calendar day — conservative for safety
MIN_DELAY_SECONDS = 45           # Min wait between DMs
MAX_DELAY_SECONDS = 120          # Max wait between DMs
SESSION_FILE      = Path("/tmp/ig_session.json")
DAILY_LOG_FILE    = Path("/tmp/ig_daily_sends.json")

IG_USERNAME = os.getenv("INSTAGRAM_USERNAME", "")
IG_PASSWORD = os.getenv("INSTAGRAM_PASSWORD", "")


# ── Daily count tracking ─────────────────────────────────────────────────────

def _load_daily_log() -> dict:
    try:
        if DAILY_LOG_FILE.exists():
            return json.loads(DAILY_LOG_FILE.read_text())
    except Exception:
        pass
    return {}


def _save_daily_log(data: dict):
    try:
        DAILY_LOG_FILE.write_text(json.dumps(data))
    except Exception as e:
        log.warning(f"[Instagram] Could not save daily log: {e}")


def get_instagram_daily_sent_count() -> int:
    today = str(date.today())
    return _load_daily_log().get(today, 0)


def _increment_daily_count():
    today = str(date.today())
    data = _load_daily_log()
    data[today] = data.get(today, 0) + 1
    _save_daily_log(data)


def can_send_instagram() -> bool:
    if not IG_USERNAME or not IG_PASSWORD:
        log.info("[Instagram] No credentials configured — set INSTAGRAM_USERNAME and INSTAGRAM_PASSWORD in .env")
        return False
    count = get_instagram_daily_sent_count()
    if count >= DAILY_LIMIT:
        log.info(f"[Instagram] Daily limit reached ({count}/{DAILY_LIMIT}). No more DMs today.")
        return False
    return True


# ── Instagram client ─────────────────────────────────────────────────────────

_ig_client = None


def _get_client():
    global _ig_client

    try:
        from instagrapi import Client
    except ImportError:
        log.error("[Instagram] instagrapi not installed. Run: pip3 install instagrapi")
        return None

    if _ig_client is not None:
        return _ig_client

    cl = Client()
    cl.delay_range = [MIN_DELAY_SECONDS, MAX_DELAY_SECONDS]

    # Try restored session first (avoids suspicious fresh logins)
    if SESSION_FILE.exists():
        try:
            cl.load_settings(SESSION_FILE)
            cl.login(IG_USERNAME, IG_PASSWORD)
            log.info(f"[Instagram] Restored session for @{IG_USERNAME}")
            _ig_client = cl
            return cl
        except Exception as e:
            log.warning(f"[Instagram] Session restore failed ({e}), doing fresh login")
            SESSION_FILE.unlink(missing_ok=True)

    # Fresh login
    try:
        cl.login(IG_USERNAME, IG_PASSWORD)
        cl.dump_settings(SESSION_FILE)
        log.info(f"[Instagram] Fresh login successful for @{IG_USERNAME}")
        _ig_client = cl
        return cl
    except Exception as e:
        log.error(f"[Instagram] Login failed: {e}")
        return None


# ── Main send function ───────────────────────────────────────────────────────

def send_instagram_dm(username: str, message: str) -> bool:
    """
    Send a DM to an Instagram username. Returns True on success.
    Enforces daily limit + human-like delay between sends.
    """
    if not username or not message:
        return False

    username = username.lstrip("@").strip()
    if not username:
        return False

    if not can_send_instagram():
        return False

    cl = _get_client()
    if cl is None:
        return False

    try:
        user_id = cl.user_id_from_username(username)
        cl.direct_send(message, [user_id])
        _increment_daily_count()
        count = get_instagram_daily_sent_count()
        log.info(f"[Instagram] DM sent to @{username} ({count}/{DAILY_LIMIT} today)")

        # Human-like delay AFTER send
        delay = random.randint(MIN_DELAY_SECONDS, MAX_DELAY_SECONDS)
        log.info(f"[Instagram] Waiting {delay}s before next send...")
        time.sleep(delay)
        return True

    except Exception as e:
        err = str(e).lower()
        global _ig_client
        if "not found" in err or "usernamenotavailable" in err:
            log.warning(f"[Instagram] @{username} not found")
        elif "challenge" in err or "checkpoint" in err:
            log.error("[Instagram] Account checkpoint! Login to Instagram manually to clear it.")
            _ig_client = None
        elif "ratelimit" in err or "feedback_required" in err:
            log.warning("[Instagram] Rate limited — pausing all DMs for today")
            data = _load_daily_log()
            data[str(date.today())] = DAILY_LIMIT  # force-fill daily cap
            _save_daily_log(data)
        else:
            log.error(f"[Instagram] DM failed for @{username}: {e}")
        return False


def get_all_instagram_sender_accounts() -> list:
    if IG_USERNAME:
        return [IG_USERNAME]
    return []
