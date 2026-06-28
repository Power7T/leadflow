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


def get_all_sender_accounts() -> list[tuple[str, str]]:
    emails_str = os.getenv("SENDER_EMAIL", "")
    pwds_str = os.getenv("SENDER_APP_PASSWORD", "")
    
    emails = [e.strip() for e in emails_str.split(",") if e.strip()]
    pwds = [p.strip() for p in pwds_str.split(",") if p.strip()]
    
    accounts = []
    for i, email in enumerate(emails):
        pwd = pwds[i] if i < len(pwds) else (pwds[0] if pwds else "")
        accounts.append((email, pwd))
    return accounts


def get_sender_credentials(assigned_email: str = None) -> tuple[str, str]:
    accounts = get_all_sender_accounts()
    if not accounts:
        return "", ""
    if assigned_email:
        for email, pwd in accounts:
            if email.lower() == assigned_email.lower():
                return email, pwd
    return accounts[0]


def send_email(to_email: str, subject: str, body: str,
               tracking_id: str = "", demo_url: str = "",
               business_id: int = None, smtp_server=None,
               reply_to_message_id: str = None) -> bool:
    from database import get_or_assign_sender_email, get_conn

    # Prevent contractors (roofer, hvac, solar, plumbers) from sending/receiving demo links to boost reply rates
    if business_id:
        conn = get_conn()
        try:
            row = conn.execute("SELECT category, name FROM businesses WHERE id=?", (business_id,)).fetchone()
            if row:
                category = (row["category"] or "").lower()
                name_lower = (row["name"] or "").lower()
                contractor_kws = ["remodeler", "remodeling", "renovation", "detail", "detailing", "ceramic", "tree", "arborist", "roof", "hvac", "solar", "plumb", "landscap", "moving", "handyman"]
                is_contractor = any(kw in category or kw in name_lower for kw in contractor_kws)
                if is_contractor:
                    demo_url = ""
        except Exception:
            pass
        finally:
            conn.close()


    assigned_email = None
    if business_id:
        assigned_email = get_or_assign_sender_email(business_id)

    sender_email, sender_password = get_sender_credentials(assigned_email)
    sender_name     = os.getenv("AGENCY_NAME", "")
    if not sender_email or not sender_password:
        raise ValueError("SENDER_EMAIL and SENDER_APP_PASSWORD must be set in .env")

    # Never email someone who has opted out.
    if is_suppressed(to_email):
        return False

    msg = MIMEMultipart("alternative")
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

    # ── Email Threading for Follow-ups ──
    parent_message_id = reply_to_message_id
    if not parent_message_id and business_id:
        conn = get_conn()
        try:
            row = conn.execute(
                "SELECT message_id FROM outreach WHERE business_id=? AND channel='email' AND status='sent' LIMIT 1",
                (business_id,)
            ).fetchone()
            if row and row["message_id"]:
                parent_message_id = row["message_id"]
        except Exception:
            pass
        finally:
            conn.close()

    if parent_message_id:
        msg["In-Reply-To"] = parent_message_id
        msg["References"] = parent_message_id
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

    msg["Subject"] = subject

    # Generate unique RFC-compliant Message-ID
    from email.utils import make_msgid
    msg_id = make_msgid(domain=sender_email.split('@')[-1])
    msg['Message-ID'] = msg_id

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
        if smtp_server is not None:
            smtp_server.sendmail(sender_email, to_email, msg.as_string())
        else:
            smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
            try:
                smtp_port = int(os.getenv("SMTP_PORT", "465"))
            except ValueError:
                smtp_port = 465
            
            if smtp_port == 465:
                with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
                    server.login(sender_email, sender_password)
                    server.sendmail(sender_email, to_email, msg.as_string())
            else:
                with smtplib.SMTP(smtp_host, smtp_port) as server:
                    server.starttls()
                    server.login(sender_email, sender_password)
                    server.sendmail(sender_email, to_email, msg.as_string())

        # Update database with generated message_id
        if business_id:
            conn = get_conn()
            try:
                if parent_message_id:
                    # Update message_id for the most recent pending/sending follow-up
                    conn.execute("""
                        UPDATE follow_ups 
                        SET message_id=? 
                        WHERE id = (
                            SELECT id FROM follow_ups 
                            WHERE business_id=? AND status='pending' 
                            ORDER BY sequence_num ASC LIMIT 1
                        )
                    """, (msg_id, business_id))
                else:
                    # Update message_id for the initial email
                    conn.execute("""
                        UPDATE outreach 
                        SET message_id=? 
                        WHERE business_id=? AND channel='email'
                    """, (msg_id, business_id))
                conn.commit()
            except Exception:
                pass
            finally:
                conn.close()

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
