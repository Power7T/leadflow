"""
Email sender — sends via Gmail SMTP with HTML body + open tracking pixel.
"""
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
from tracker import inject_tracking_into_email

load_dotenv()

SENDER_EMAIL    = os.getenv("SENDER_EMAIL", "")
SENDER_PASSWORD = os.getenv("SENDER_APP_PASSWORD", "")


def send_email(to_email: str, subject: str, body: str,
               tracking_id: str = "", demo_url: str = "") -> bool:
    if not SENDER_EMAIL or not SENDER_PASSWORD:
        raise ValueError("SENDER_EMAIL and SENDER_APP_PASSWORD must be set in .env")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SENDER_EMAIL
    msg["To"]      = to_email

    # Plain text fallback
    msg.attach(MIMEText(body, "plain"))

    # HTML version with tracking
    if tracking_id:
        html = inject_tracking_into_email(body, tracking_id, demo_url)
    else:
        html = f"<html><body>{body.replace(chr(10), '<br>')}</body></html>"
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.sendmail(SENDER_EMAIL, to_email, msg.as_string())
        return True
    except Exception as e:
        raise RuntimeError(f"Failed to send email: {e}")


def parse_subject_body(draft: str) -> tuple[str, str]:
    """Split AI draft into subject + body (subject is first line)."""
    lines = draft.strip().split("\n")
    subject = lines[0].strip()
    if subject.lower().startswith("subject:"):
        subject = subject[8:].strip()
    body = "\n".join(lines[2:]).strip() if len(lines) > 2 else "\n".join(lines[1:]).strip()
    return subject, body
