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

DB_PATH = "leadflow.db"
CHECKER_EMAIL = "chqn.films2@gmail.com"
CHECKER_PASS = "dfqm fvqq posf bdhi"

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def send_ping_email(recipient_email):
    """Send a link-free, low-friction text ping email to test deliverability."""
    subject = "Quick question"
    body = "Hi,\n\nI hope you're doing well. Just wanted to check if this is the correct inbox to reach you.\n\nBest,\nChandan"
    
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
    """Check CHECKER_EMAIL inbox via IMAP for bounces, extract recipient addresses, and mark them in the DB."""
    log.info("Checking for bounces via IMAP...")
    
    # 1. Fetch email addresses currently in 'bounce_checking' status
    conn = get_conn()
    checking_rows = conn.execute("""
        SELECT b.id, c.email 
        FROM businesses b 
        JOIN contacts c ON c.business_id = b.id 
        WHERE b.status = 'bounce_checking'
    """).fetchall()
    conn.close()
    
    if not checking_rows:
        log.info("No leads currently in 'bounce_checking' status. Skipping IMAP checks.")
        return
        
    checking_emails = {row["email"].lower().strip(): row["id"] for row in checking_rows}
    log.info(f"Monitoring bounces for {len(checking_emails)} email addresses...")
    
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
                
            # Scan last 50 emails
            start_idx = max(1, num_messages - 49)
            for i in range(num_messages, start_idx - 1, -1):
                status, data = mail.fetch(str(i), "(BODY[HEADER.FIELDS (SUBJECT FROM)] BODY[TEXT])")
                if status != "OK" or not data[0]:
                    continue
                    
                header_part = data[0][1].decode("utf-8", errors="ignore")
                body_part = data[1][1].decode("utf-8", errors="ignore") if len(data) > 1 and data[1] else ""
                
                # Check if it is a bounce notification
                is_bounce = False
                if "mailer-daemon@googlemail.com" in header_part.lower() or "postmaster@" in header_part.lower():
                    is_bounce = True
                elif "delivery status" in header_part.lower() or "undeliverable" in header_part.lower() or "returned mail" in header_part.lower():
                    is_bounce = True
                    
                if not is_bounce:
                    continue
                    
                # Search for any of our bounce_checking emails inside the headers or body text
                combined_text = (header_part + "\n" + body_part).lower()
                for target_email, biz_id in checking_emails.items():
                    if target_email in combined_text:
                        log.warning(f"⚠️ Bounce detected for lead {target_email} (Business ID: {biz_id})!")
                        # Mark as bounced in database
                        conn = get_conn()
                        conn.execute("UPDATE businesses SET status='bounced' WHERE id=?", (biz_id,))
                        conn.commit()
                        conn.close()
                        
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
