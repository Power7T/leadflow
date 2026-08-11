"""
whatsapp_sender.py — WhatsApp sender for LeadFlow.

Supports two backends (configure in .env):
  1. Twilio WhatsApp Business API  (TWILIO_ACCOUNT_SID + TWILIO_AUTH_TOKEN + TWILIO_WHATSAPP_FROM)
     Cost: ~$0.005/message. Recommended for reliability.

  2. Free (no-API) fallback — generates a daily digest of WhatsApp messages
     to copy-paste into WhatsApp Business on your phone. Zero cost.

The system auto-detects which backend to use based on what's in .env.
"""

import os
import json
import logging
from datetime import date
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("leadflow.whatsapp")

import tempfile
TEMP_DIR = Path(tempfile.gettempdir())

# ── Config ───────────────────────────────────────────────────────────────────
TWILIO_SID      = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_TOKEN    = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM     = os.getenv("TWILIO_WHATSAPP_FROM", "")   # e.g. "whatsapp:+14155238886"

DAILY_LOG_FILE  = TEMP_DIR / "wa_daily_sends.json"
DAILY_LIMIT     = 100   # Twilio has no hard limit — this is our safety cap


# ── Daily count tracking ──────────────────────────────────────────────────────

def _load_daily_log() -> dict:
    try:
        if DAILY_LOG_FILE.exists():
            return json.loads(DAILY_LOG_FILE.read_text())
    except Exception:
        pass
    return {}


def get_whatsapp_daily_sent_count() -> int:
    return _load_daily_log().get(str(date.today()), 0)


def _increment_daily_count():
    today = str(date.today())
    data = _load_daily_log()
    data[today] = data.get(today, 0) + 1
    DAILY_LOG_FILE.write_text(json.dumps(data))


def has_twilio() -> bool:
    return bool(TWILIO_SID and TWILIO_TOKEN and TWILIO_FROM)


# ── Twilio sender ─────────────────────────────────────────────────────────────

def _send_via_twilio(phone: str, message: str) -> bool:
    """Send WhatsApp message via Twilio API. Phone in E.164 format: +12125551234"""
    try:
        from twilio.rest import Client
    except ImportError:
        log.error("[WhatsApp] Twilio not installed. Run: pip3 install twilio")
        return False

    # Normalize phone number
    phone = phone.strip().replace(" ", "").replace("-", "")
    if not phone.startswith("+"):
        phone = "+" + phone
    to = f"whatsapp:{phone}"

    try:
        client = Client(TWILIO_SID, TWILIO_TOKEN)
        msg = client.messages.create(
            from_=TWILIO_FROM,
            to=to,
            body=message
        )
        _increment_daily_count()
        count = get_whatsapp_daily_sent_count()
        log.info(f"[WhatsApp/Twilio] Sent to {phone} (SID: {msg.sid}) [{count}/{DAILY_LIMIT} today]")
        return True
    except Exception as e:
        log.error(f"[WhatsApp/Twilio] Send failed to {phone}: {e}")
        return False


# ── Digest fallback (no Twilio) ───────────────────────────────────────────────

DIGEST_FILE = TEMP_DIR / "wa_digest_today.json"

def _queue_for_digest(phone: str, business_name: str, message: str):
    """
    When no Twilio configured, queue the message in a daily digest file.
    The LeadFlow dashboard shows this digest so you can send manually.
    """
    today = str(date.today())
    try:
        existing = json.loads(DIGEST_FILE.read_text()) if DIGEST_FILE.exists() else {}
    except Exception:
        existing = {}

    if today not in existing:
        existing[today] = []

    existing[today].append({
        "phone": phone,
        "name": business_name,
        "message": message,
        "sent": False,
    })
    DIGEST_FILE.write_text(json.dumps(existing, indent=2))
    log.info(f"[WhatsApp/Digest] Queued message for {business_name} ({phone})")


def get_whatsapp_digest() -> list:
    """Return today's pending digest entries for dashboard display."""
    today = str(date.today())
    try:
        data = json.loads(DIGEST_FILE.read_text()) if DIGEST_FILE.exists() else {}
        return [e for e in data.get(today, []) if not e.get("sent")]
    except Exception:
        return []


# ── Main send function ────────────────────────────────────────────────────────

def send_whatsapp(phone: str, message: str, business_name: str = "") -> bool:
    """
    Send a WhatsApp message. Auto-selects Twilio or digest mode.

    Args:
        phone:         Phone number in E.164 format (+12125551234) or raw digits
        message:       Message text
        business_name: Human-readable name for digest display
    """
    if not phone or not message:
        return False

    if get_whatsapp_daily_sent_count() >= DAILY_LIMIT:
        log.info(f"[WhatsApp] Daily cap reached ({DAILY_LIMIT}). Skipping.")
        return False

    if has_twilio():
        return _send_via_twilio(phone, message)
    else:
        _queue_for_digest(phone, business_name, message)
        return True   # "sent" to digest


def whatsapp_backend() -> str:
    """Return 'twilio' or 'digest' so the UI can show which mode is active."""
    return "twilio" if has_twilio() else "digest"
