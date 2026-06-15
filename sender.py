"""
Email sender — sends via Gmail SMTP with HTML body + open tracking pixel.

Deliverability guards (cold sending will land in spam without these):
- List-Unsubscribe + one-click header (Gmail/Yahoo bulk-sender requirement)
- physical postal address + opt-out in the footer (CAN-SPAM)
- a suppression list so we never re-email someone who opted out
"""
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from dotenv import load_dotenv
from tracker import inject_tracking_into_email

load_dotenv()

SUPPRESS_FILE = os.path.join(os.path.dirname(__file__), "suppressed.txt")


def is_suppressed(email: str) -> bool:
    try:
        with open(SUPPRESS_FILE) as f:
            return (email or "").strip().lower() in {l.strip().lower() for l in f if l.strip()}
    except FileNotFoundError:
        return False


def suppress(email: str):
    if email and not is_suppressed(email):
        with open(SUPPRESS_FILE, "a") as f:
            f.write(email.strip().lower() + "\n")


def _public_base() -> str:
    try:
        from deploy import public_base
        return public_base()
    except Exception:
        return ""


def send_email(to_email: str, subject: str, body: str,
               tracking_id: str = "", demo_url: str = "") -> bool:
    sender_email    = os.getenv("SENDER_EMAIL", "")
    sender_password = os.getenv("SENDER_APP_PASSWORD", "")
    sender_name     = os.getenv("AGENCY_NAME", "")
    if not sender_email or not sender_password:
        raise ValueError("SENDER_EMAIL and SENDER_APP_PASSWORD must be set in .env")

    # Never email someone who has opted out.
    if is_suppressed(to_email):
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = formataddr((sender_name, sender_email)) if sender_name else sender_email
    msg["To"]      = to_email

    # One-click unsubscribe headers (mailto always; https one-click if reachable).
    base = _public_base()
    unsub_https = f"{base}/unsubscribe?e={to_email}" if base else ""
    unsub_parts = []
    if unsub_https:
        unsub_parts.append(f"<{unsub_https}>")
        msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    unsub_parts.append(f"<mailto:{sender_email}?subject=unsubscribe>")
    msg["List-Unsubscribe"] = ", ".join(unsub_parts)

    # CAN-SPAM footer: postal address + clear opt-out.
    address = os.getenv("AGENCY_ADDRESS", "")
    plain_body = body
    if "unsubscribe" not in plain_body.lower() and "reply with 'stop'" not in plain_body.lower():
        footer = "\n\n---\n"
        if address:
            footer += address + "\n"
        if unsub_https:
            footer += f"Prefer not to hear from me? Unsubscribe: {unsub_https}"
        else:
            footer += "Prefer not to hear from me? Just reply 'stop' and I'll remove you."
        plain_body += footer

    msg.attach(MIMEText(plain_body, "plain"))

    # HTML version with tracking and opt-out
    if tracking_id:
        html = inject_tracking_into_email(plain_body, tracking_id, demo_url)
    else:
        html = f"<html><body>{plain_body.replace(chr(10), '<br>')}</body></html>"
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, to_email, msg.as_string())
        return True
    except Exception as e:
        raise RuntimeError(f"Failed to send email: {e}")


def parse_subject_body(draft: str) -> tuple[str, str]:
    """Split an AI draft into (subject, body), tolerant of format drift.

    Handles: an explicit 'Subject:' line anywhere in the first few lines, a
    missing blank line between subject and body, and stray markdown (** / #)."""
    text = (draft or "").strip()
    if not text:
        return "", ""
    lines = text.split("\n")

    subject, body_start = "", 0
    for i, line in enumerate(lines[:4]):
        s = line.strip().lstrip("*# ").strip()      # tolerate **Subject:** etc.
        if s.lower().startswith("subject:"):
            subject = s.split(":", 1)[1].strip()
            body_start = i + 1
            break
    if not subject:
        for i, line in enumerate(lines):
            if line.strip():
                subject = line.strip()
                body_start = i + 1
                break

    # Skip blank lines between subject and body.
    while body_start < len(lines) and not lines[body_start].strip():
        body_start += 1

    body = "\n".join(lines[body_start:]).strip()
    if not body:                       # subject-only draft — don't lose the text
        body = text
    subject = subject.strip("*# ").strip()
    return subject, body
