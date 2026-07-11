import sqlite3
import smtplib
import imaplib
import email
import re
import time
import logging
import sys
from datetime import datetime, timedelta
from email.mime.text import MIMEText

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger("leadflow.bounce_checker")

DB_PATH = "/Users/chandan/leadflow/leadflow.db"
CHECKER_EMAIL = "chqn.films2@gmail.com"
CHECKER_PASS = "dfqm fvqq posf bdhi"

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def _spintax(text: str) -> str:
    import random as _random_mod
    def _pick(m):
        opts = m.group(1).split("|")
        return _random_mod.choice(opts).strip()
    return re.sub(r"\{([^{}]+)\}", _pick, text)

def send_ping_email(recipient_email):
    """Send a link-free, low-friction text ping email to test deliverability."""
    subject_raw = "{Quick question|Quick chat|Hi there|Hello|Checking in}"
    body_raw = "{Hi|Hello|Hey},\n\n{Just wanted to check if this is the correct inbox to reach you.|Is this the best email address to contact you directly?|Wanted to verify if this inbox is active.|Hope you're doing well. Is this the right email address to reach you?}\n\n{Best|Regards|Thanks},\nChandan"
    
    subject = _spintax(subject_raw)
    body = _spintax(body_raw)
    
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = CHECKER_EMAIL
    msg["To"] = recipient_email
    
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as server:
            server.login(CHECKER_EMAIL, CHECKER_PASS)
            server.sendmail(CHECKER_EMAIL, [recipient_email], msg.as_string())
        log.info(f"Ping email sent successfully to {recipient_email}")
        return True
    except Exception as e:
        log.error(f"Failed to send ping email to {recipient_email}: {e}")
        return False

def check_for_bounces():
    """Check CHECKER_EMAIL inbox via IMAP for bounces AND real lead replies.

    Bounces: detected and marked in DB.
    Real replies: classified via AI, auto-replied with demo/booking link, CC'd to chandango12.
    """
    log.info("Checking for bounces via IMAP...")

    # 1. Fetch email addresses currently in 'bounce_checking' status
    conn = get_conn()
    checking_rows = conn.execute("""
        SELECT b.id, c.email
        FROM businesses b
        JOIN contacts c ON c.business_id = b.id
        WHERE b.status = 'bounce_checking'
    """).fetchall()

    checking_emails = {row["email"].lower().strip(): row["id"] for row in checking_rows}

    # 2. Build broader email_to_bid map from contacts table (for replies from any lead)
    all_contacts = conn.execute("SELECT business_id, email, hunter_email, apollo_email FROM contacts").fetchall()
    email_to_bid = {}
    for row in all_contacts:
        bid = row["business_id"]
        for col in ("email", "hunter_email", "apollo_email"):
            em = row[col]
            if em:
                email_to_bid[em.lower().strip()] = bid
    conn.close()

    if not checking_emails and not email_to_bid:
        log.info("No leads to monitor. Skipping IMAP checks.")
        return

    log.info(f"Monitoring bounces for {len(checking_emails)} addresses, reply detection for {len(email_to_bid)} leads...")

    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(CHECKER_EMAIL, CHECKER_PASS)

        # Check both Inbox and Spam just in case Google routes the bounces weirdly
        for folder in ["INBOX", "[Gmail]/Spam"]:
            status, select_data = mail.select(folder, readonly=True)
            if status != "OK":
                if folder == "[Gmail]/Spam":
                    mail.select("Spam", readonly=True)
                else:
                    continue

            num_messages = int(select_data[0])
            if num_messages == 0:
                continue

            # Scan last 100 emails
            start_idx = max(1, num_messages - 99)
            for i in range(num_messages, start_idx - 1, -1):
                status, data = mail.fetch(str(i), "(BODY.PEEK[])")
                if status != "OK" or not data or not data[0] or not isinstance(data[0], tuple):
                    continue

                raw_bytes = data[0][1]
                parsed_msg = email.message_from_bytes(raw_bytes)

                header_part = str(raw_bytes[:4096], "utf-8", errors="ignore")

                # Extract sender email from headers
                from_header = parsed_msg.get("From", "")
                from_match = re.search(r'([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)', from_header)
                sender_email_addr = from_match.group(1).lower().strip() if from_match else ""

                # Extract Message-ID for dedup
                message_id = (parsed_msg.get("Message-ID") or "").strip()

                # Extract subject
                raw_subject = (parsed_msg.get("Subject") or "").strip()

                # Check if it is a bounce notification
                from_lower = from_header.lower()
                is_bounce = False
                if "mailer-daemon" in from_lower or "postmaster@" in from_lower:
                    is_bounce = True
                elif "delivery status" in header_part.lower() or "undeliverable" in header_part.lower() or "returned mail" in header_part.lower():
                    is_bounce = True

                if is_bounce:
                    # Search for any of our bounce_checking emails in the full raw message
                    combined_text = str(raw_bytes, "utf-8", errors="ignore").lower()
                    for target_email, biz_id in checking_emails.items():
                        if target_email in combined_text:
                            log.warning(f"⚠️ Bounce detected for lead {target_email} (Business ID: {biz_id})!")
                            conn = get_conn()
                            conn.execute("UPDATE businesses SET status='bounced' WHERE id=?", (biz_id,))
                            conn.commit()
                            conn.close()
                    continue

                # ── Real reply handling ────────────────────────────────────
                # Skip emails from ourselves or system addresses
                if not sender_email_addr or sender_email_addr == CHECKER_EMAIL.lower():
                    continue

                bid = email_to_bid.get(sender_email_addr)
                if not bid:
                    # Unknown sender replied to our ping — auto-create them as a lead
                    name_match = re.search(r'"?([^<"\n]+)"?\s*<', from_header)
                    sender_name = name_match.group(1).strip() if name_match else sender_email_addr.split("@")[0]
                    domain = sender_email_addr.split("@")[-1] if "@" in sender_email_addr else ""
                    try:
                        conn = get_conn()
                        conn.execute(
                            "INSERT INTO businesses (name, status, category, notes) VALUES (?, 'replied', 'unknown', ?)",
                            (sender_name, f"[Auto-created] Replied to bounce ping. Domain: {domain}")
                        )
                        bid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                        conn.execute(
                            "INSERT INTO contacts (business_id, email) VALUES (?, ?)",
                            (bid, sender_email_addr)
                        )
                        conn.commit()
                        conn.close()
                        email_to_bid[sender_email_addr] = bid
                        log.info(f"Auto-created lead for unknown replier {sender_email_addr} → business {bid}")
                    except Exception as create_err:
                        log.warning(f"Failed to auto-create lead for {sender_email_addr}: {create_err}")
                        continue

                # Dedup: skip if we already processed this message_id
                if message_id:
                    conn = get_conn()
                    existing = conn.execute("SELECT id FROM inbound_messages WHERE message_id=?", (message_id,)).fetchone()
                    conn.close()
                    if existing:
                        continue

                log.info(f"Real reply detected from {sender_email_addr} (business {bid}) in bounce inbox!")

                # Extract body from the already-fetched parsed_msg
                from imap_sync import get_email_body, classify_reply, notify_chandan
                body_text = get_email_body(parsed_msg)

                if not body_text.strip():
                    continue

                classification = classify_reply(body_text)
                log.info(f"Classified reply from {sender_email_addr} as: {classification}")

                # Save classification
                try:
                    from database import save_reply_classification
                    save_reply_classification(bid, classification, body_text)
                except Exception as e:
                    log.warning(f"Failed to save reply classification: {e}")

                if classification == "autoreply":
                    continue

                # Save to inbound_messages
                conn = get_conn()
                conn.execute(
                    "INSERT INTO inbound_messages (business_id, message_id, subject, body) VALUES (?, ?, ?, ?)",
                    (bid, message_id, raw_subject, body_text)
                )
                conn.commit()

                if classification in ("unsubscribe", "not_interested"):
                    conn.execute("UPDATE businesses SET status='opted_out' WHERE id=?", (bid,))
                    conn.execute("DELETE FROM follow_ups WHERE business_id=? AND status='pending'", (bid,))
                    conn.commit()
                    conn.close()
                    notify_chandan(
                        "Bounce Reply — Opt Out",
                        f"Lead {sender_email_addr} (biz {bid}) opted out from bounce inbox.\n\n\"{body_text[:200]}\"",
                        tags="no_entry", priority="default"
                    )
                    continue

                # interested or question — generate AI reply and send
                conn.execute("UPDATE businesses SET status='replied' WHERE id=?", (bid,))
                conn.execute("UPDATE contacts SET reply_text = CASE WHEN reply_text IS NULL OR reply_text = '' THEN ? ELSE reply_text || '\n\n━━━━━━━━━━━━━━━━━━━━\n\n' || ? END WHERE business_id=?",
                             (body_text, body_text, bid))
                conn.execute("UPDATE outreach SET replied=1 WHERE business_id=?", (bid,))
                conn.execute("DELETE FROM follow_ups WHERE business_id=? AND status='pending'", (bid,))
                conn.commit()
                conn.close()

                try:
                    from ai_writer import generate_bounce_reply
                    from sender import send_email
                    import uuid as _uuid

                    # Load business row for context
                    conn = get_conn()
                    biz_row = conn.execute("SELECT * FROM businesses WHERE id=?", (bid,)).fetchone()
                    conn.close()
                    biz_dict = dict(biz_row) if biz_row else {"name": "there", "category": "", "city": ""}

                    ai_body = generate_bounce_reply(biz_dict, body_text)
                    if not ai_body:
                        log.warning(f"AI generation failed for bounce reply to {sender_email_addr}, skipping auto-reply")
                        notify_chandan(
                            "Bounce Reply — AI Failed",
                            f"Got reply from {sender_email_addr} but AI failed. Manual reply needed.\n\n\"{body_text[:300]}\"",
                            tags="warning", priority="high"
                        )
                        continue

                    # Build reply subject
                    reply_subject = raw_subject
                    if reply_subject and not reply_subject.lower().startswith("re:"):
                        reply_subject = f"Re: {reply_subject}"
                    elif not reply_subject:
                        reply_subject = f"Re: Quick question about {biz_dict.get('name', 'your business')}"

                    tracking_id = str(_uuid.uuid4())

                    send_email(
                        sender_email_addr, reply_subject, ai_body,
                        tracking_id=tracking_id,
                        business_id=bid,
                        reply_to_message_id=message_id,
                        cc_email="chandango12@gmail.com",
                        auth_email=CHECKER_EMAIL,
                        auth_password=CHECKER_PASS,
                    )
                    log.info(f"Sent AI auto-reply to {sender_email_addr} (CC: chandango12), business {bid}")

                    # Record in outreach for CRM visibility
                    conn = get_conn()
                    conn.execute("""
                        INSERT INTO outreach
                            (business_id, channel, final_message, status, sent_at, is_autopilot, tracking_id)
                        VALUES (?, 'email', ?, 'sent', datetime('now'), 1, ?)
                    """, (bid, ai_body, tracking_id))
                    conn.commit()
                    conn.close()

                    biz_name = biz_dict.get("name", sender_email_addr)
                    notify_chandan(
                        "🔥 Bounce Reply — HOT LEAD!",
                        f"{biz_name} ({sender_email_addr}) replied to bounce ping!\nAI auto-reply sent with demo.\n\n\"{body_text[:400]}\"",
                        tags="moneybag,fire", priority="high"
                    )
                except Exception as reply_err:
                    log.error(f"Failed to process bounce reply from {sender_email_addr}: {reply_err}")
                    try:
                        notify_chandan(
                            "Bounce Reply — Error",
                            f"Reply from {sender_email_addr} but auto-reply failed: {reply_err}",
                            tags="warning", priority="high"
                        )
                    except Exception:
                        pass

        mail.close()
        mail.logout()
    except Exception as e:
        log.error(f"Error checking bounces via IMAP: {e}")

def run_pipeline():
    """Main pipeline loop: send pings for new leads, check bounces, and approve clean leads."""
    log.info("--- Starting Lead Verification Run ---")
    
    # Step 1: Query new leads that have emails and need verification
    conn = get_conn()
    new_leads = conn.execute("""
        SELECT b.id, c.email 
        FROM businesses b
        JOIN contacts c ON c.business_id = b.id
        WHERE b.status = 'new'
          AND c.email IS NOT NULL AND c.email != ''
          AND b.id NOT IN (
              SELECT DISTINCT business_id FROM outreach
          )
        ORDER BY b.lead_score DESC
        LIMIT 10
    """).fetchall()
    conn.close()
    
    log.info(f"Found {len(new_leads)} new leads needing verification.")
    
    # Step 2: Send ping email and update status to 'bounce_checking'
    for lead in new_leads:
        biz_id = lead["id"]
        email_addr = lead["email"].strip()
        
        # Update timestamp and status
        conn = get_conn()
        conn.execute("""
            UPDATE businesses 
            SET status='bounce_checking', 
                notes=COALESCE(notes, '') || '\n[Bounce Check] Ping email sent: ' || datetime('now')
            WHERE id=?
        """, (biz_id,))
        conn.commit()
        conn.close()
        
        # Send email
        success = send_ping_email(email_addr)
        if not success:
            # If SMTP fail, revert to new so it can be retried
            conn = get_conn()
            conn.execute("UPDATE businesses SET status='new' WHERE id=?", (biz_id,))
            conn.commit()
            conn.close()
            
    # Step 3: Run the bounce verification checker
    check_for_bounces()
    
    # Step 4: Approve leads that have been in 'bounce_checking' for > 15 minutes without bouncing
    log.info("Approving verified leads...")
    conn = get_conn()
    # Parse notes to extract timestamp and see if 15 minutes have passed
    checking_leads = conn.execute("""
        SELECT id, notes 
        FROM businesses 
        WHERE status='bounce_checking'
    """).fetchall()
    
    approved_count = 0
    for lead in checking_leads:
        biz_id = lead["id"]
        notes = lead["notes"] or ""
        
        # Extract timestamp from notes
        match = re.search(r"\[Bounce Check\] Ping email sent: (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", notes)
        if match:
            sent_time_str = match.group(1)
            sent_time = datetime.strptime(sent_time_str, "%Y-%m-%d %H:%M:%S")
            # If 15 minutes have passed since ping, we assume it's deliverable
            if datetime.now() - sent_time > timedelta(minutes=15):
                conn.execute("""
                    UPDATE businesses 
                    SET status='approved',
                        notes=COALESCE(notes, '') || '\n[Bounce Check] Verified clean: ' || datetime('now')
                    WHERE id=?
                """, (biz_id,))
                approved_count += 1
                
    conn.commit()
    conn.close()
    log.info(f"Approved {approved_count} verified leads for outreach.")
    log.info("--- Lead Verification Run Finished ---")

if __name__ == "__main__":
    run_pipeline()
