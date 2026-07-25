import os
import imaplib
import email
from email.header import decode_header
import sqlite3
import logging
import time
import socket
from dotenv import load_dotenv

load_dotenv(override=True)  # override=True ensures updated .env values are picked up after restart

# Set socket timeout to 30 seconds to prevent hanging on network calls
socket.setdefaulttimeout(30.0)

# Configure logging if not already configured
if not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    )

log = logging.getLogger('imap_sync')

def notify_chandan(title, message, tags="bell", priority="default"):
    # 1. Send push alert via ntfy.sh
    try:
        import requests
        _ntfy_topic = os.getenv("NTFY_TOPIC")
        # ntfy headers must be latin-1 safe — strip anything outside ASCII
        safe_title = title.encode("ascii", errors="ignore").decode("ascii")
        safe_tags = tags.encode("ascii", errors="ignore").decode("ascii")
        requests.post(
            f"https://ntfy.sh/{_ntfy_topic}",
            data=message.encode("utf-8"),
            headers={"Title": safe_title, "Tags": safe_tags, "Priority": priority},
            timeout=5
        )
    except Exception:
        pass

    # 2. Send instant alert via Telegram Bot
    bot_token = os.getenv("TELEGRAM_CONTROL_BOT_TOKEN")
    user_id = os.getenv("TELEGRAM_CONTROL_USER_ID")
    if bot_token and user_id:
        try:
            import urllib.request
            import urllib.parse
            import ssl
            context = ssl._create_unverified_context()
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            formatted_text = f"{title}\n{message}"
            data = urllib.parse.urlencode({
                "chat_id": user_id,
                "text": formatted_text,
            }).encode("utf-8")
            req = urllib.request.Request(url, data=data)
            with urllib.request.urlopen(req, context=context, timeout=5) as resp:
                pass
        except Exception as e:
            log.warning(f"Failed to send Telegram alert: {e}")

import re


def classify_reply(body_text: str) -> str:
    """Classify an email reply using AI, with keyword fallback.
    
    Returns one of: 'interested', 'question', 'not_interested', 'unsubscribe'
    """
    # Use a list ordered by length so 'not_interested' is checked before 'interested'
    valid_categories = ['unsubscribe', 'not_interested', 'interested', 'question', 'autoreply']

    # 1. Obvious keyword checks first (to save API credits)
    text_lower = body_text.lower()
    
    # Very obvious autoreplies
    autoreply_keywords = ['out of office', 'automated response', 'auto-reply', 'is not monitored', 'vacation', 'message was blocked']
    if any(kw in text_lower for kw in autoreply_keywords):
        return 'autoreply'

    # Very obvious opt-outs
    unsubscribe_keywords = ['unsubscribe', 'remove me', 'stop emailing', 'take me off']
    if any(kw in text_lower for kw in unsubscribe_keywords):
        return 'unsubscribe'

    # 2. If it's a real human response, use AI to classify intent accurately
    try:
        from ai_writer import _run
        prompt = (
            'Classify this email reply into EXACTLY one category: '
            'interested, question, not_interested, unsubscribe, autoreply. '
            'Reply with ONLY the category name, nothing else.\n\n'
            f'Email: {body_text[:500]}'
        )
        ai_response = _run(prompt)
        if ai_response:
            response_lower = ai_response.strip().lower()
            for category in valid_categories:
                if category in response_lower:
                    return category
    except Exception as e:
        log.warning(f"AI classification failed, falling back to keywords: {e}")

    # 3. Fallback to basic keywords if AI fails
    interested_keywords = ['interested', 'tell me more', 'schedule', 'sounds good', 'how much',
                           'pricing', "let's talk", 'call me', 'send me', 'demo']
    question_keywords = ['how', 'what', 'when', 'cost', 'price', '?']
    not_interested_keywords = ['not interested', 'we are good', 'we have', 'no thanks']

    if any(kw in text_lower for kw in interested_keywords):
        return 'interested'
    if any(kw in text_lower for kw in not_interested_keywords):
        return 'not_interested'
    if any(kw in text_lower for kw in question_keywords):
        return 'question'

    return 'question'


def get_email_body(msg) -> str:
    body_plain = ""
    body_html = ""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition"))
            if "attachment" not in content_disposition:
                payload = part.get_payload(decode=True)
                if payload:
                    text = payload.decode(errors="ignore")
                    if content_type == "text/plain":
                        body_plain += text
                    elif content_type == "text/html":
                        body_html += text
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            text = payload.decode(errors="ignore")
            if msg.get_content_type() == "text/html":
                body_html = text
            else:
                body_plain = text
                
    if body_plain:
        return body_plain
    elif body_html:
        # Strip HTML tags nicely and collapse whitespace
        text = re.sub(r'<style.*?>.*?</style>', '', body_html, flags=re.DOTALL|re.IGNORECASE)
        text = re.sub(r'<script.*?>.*?</script>', '', text, flags=re.DOTALL|re.IGNORECASE)
        text = re.sub(r'<[^>]+>', ' ', text)
        return ' '.join(text.split())
    return ""

def check_replies():
    from sender import get_all_sender_accounts
    accounts = get_all_sender_accounts()
    if not accounts:
        log.warning("No sender accounts configured. Skipping reply detection.")
        return

    from database import DB_PATH
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH, timeout=30.0)
        conn.execute("PRAGMA busy_timeout = 5000;")
        conn.row_factory = sqlite3.Row

        # Ensure inbound_messages table exists (Fix B: prevent 'no such table' crash)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS inbound_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                business_id INTEGER,
                message_id TEXT,
                subject TEXT,
                body TEXT,
                received_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()

        cursor = conn.cursor()

        # Fetch all known lead emails
        cursor.execute("SELECT business_id, email, hunter_email, apollo_email FROM contacts")
        lead_contacts = cursor.fetchall()

        # Create a mapping of email_address -> business_id
        email_to_bid = {}
        for row in lead_contacts:
            bid = row["business_id"]
            em = row["email"]
            hem = row["hunter_email"]
            aem = row["apollo_email"]
            if em: email_to_bid[em.lower()] = bid
            if hem: email_to_bid[hem.lower()] = bid
            if aem: email_to_bid[aem.lower()] = bid

        for email_addr, pwd in accounts:
            log.info(f"Checking replies for account: {email_addr}")
            mail = None
            try:
                for _attempt in range(3):
                    try:
                        mail = imaplib.IMAP4_SSL(os.getenv("IMAP_SERVER", "imap.gmail.com"))
                        mail.login(email_addr, pwd)
                        mail.select("inbox")
                        break
                    except Exception as _conn_err:
                        log.warning(f"IMAP connect attempt {_attempt+1}/3 failed for {email_addr}: {_conn_err}")
                        mail = None
                        if _attempt < 2:
                            time.sleep(5)
                        else:
                            log.error(f"All IMAP connect attempts failed for {email_addr}, skipping account")
                if mail is None:
                    continue

                # Limit live search to past 2 days (catches everything since script runs every 5 mins)
                import datetime
                cutoff_date = datetime.datetime.now() - datetime.timedelta(days=2)
                since_date = cutoff_date.strftime("%d-%b-%Y")
                status, messages = mail.search(None, f'(SINCE "{since_date}")')
                
                if status != "OK" or not messages[0]:
                    log.info(f"No emails found for {email_addr}.")
                    continue

                email_ids = messages[0].split()
                for eid in email_ids:
                    # Fetch ONLY the basic headers first (super fast)
                    res, header_data = mail.fetch(eid, "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID FROM)])")
                    if res != "OK":
                        continue
                        
                    header_str = header_data[0][1].decode(errors="ignore")
                    msg_headers = email.message_from_string(header_str)
                    
                    sender = msg_headers.get("From", "")
                    message_id = msg_headers.get("Message-ID", "")
                    
                    if not sender:
                        continue
                        
                    if "<" in sender and ">" in sender:
                        sender_email = sender.split("<")[1].split(">")[0].strip().lower()
                    else:
                        sender_email = sender.strip().lower()

                    # Avoid re-processing the same reply
                    if message_id:
                        existing_msg = cursor.execute("SELECT id FROM inbound_messages WHERE message_id=?", (message_id,)).fetchone()
                        if existing_msg:
                            continue

                    # Does this email matter to us?
                    is_bounce = sender_email.startswith("mailer-daemon") or sender_email.startswith("postmaster") or sender_email.startswith("bounce")
                    is_lead = sender_email in email_to_bid

                    if not is_bounce and not is_lead:
                        continue  # Skip unrelated emails entirely without downloading the body

                    # If it matters, NOW fetch the full email body to process it
                    res, full_msg_data = mail.fetch(eid, "(RFC822)")
                    if res != "OK":
                        continue
                        
                    msg = None
                    for response_part in full_msg_data:
                        if isinstance(response_part, tuple):
                            msg = email.message_from_bytes(response_part[1])
                            break
                            
                    if not msg:
                        continue

                    # Detect Bounces / Undeliverable emails
                    if is_bounce:
                        body_text = get_email_body(msg).lower()
                        for known_email, bid in email_to_bid.items():
                            if known_email in body_text:
                                log.info(f"Bounce detected for {known_email} (business {bid})! Marking as bounced.")
                                cursor.execute("UPDATE businesses SET status='bounced' WHERE id=?", (bid,))
                                cursor.execute("DELETE FROM follow_ups WHERE business_id=? AND status='pending'", (bid,))
                                conn.commit()
                                break
                        continue

                    if is_lead:
                        bid = email_to_bid[sender_email]
                        
                        # Allow subsequent replies to be processed so we don't miss follow-up questions/opt-outs,
                        # while still preventing duplicate processing of the same email via message_id check.
                        body_text = get_email_body(msg)

                        # AI-powered reply classification
                        classification = classify_reply(body_text)
                        from database import save_reply_classification
                        save_reply_classification(bid, classification, body_text)
                        
                        if classification == 'autoreply':
                            log.info(f"Skipping autoreply from {sender_email} for business {bid}")
                            conn.commit()
                            continue
                            
                        cursor.execute("INSERT INTO inbound_messages (business_id, message_id, subject, body) VALUES (?, ?, ?, ?)",
                                      (bid, message_id, msg.get("Subject", ""), body_text))

                        if classification in ('unsubscribe', 'not_interested'):
                            log.info(f"Opt-out ({classification}) detected from {sender_email} for business {bid}!")
                            cursor.execute("UPDATE businesses SET status='opted_out' WHERE id=?", (bid,))
                            cursor.execute("UPDATE contacts SET reply_text = CASE WHEN reply_text IS NULL OR reply_text = '' THEN ? ELSE reply_text || '\n\n━━━━━━━━━━━━━━━━━━━━\n\n' || ? END WHERE business_id=?", (body_text, body_text, bid))
                            cursor.execute("DELETE FROM follow_ups WHERE business_id=? AND status='pending'", (bid,))
                            try:
                                biz_name = "there"
                                biz_row = cursor.execute("SELECT name FROM businesses WHERE id=?", (bid,)).fetchone()
                                if biz_row:
                                    biz_name = biz_row["name"]
                                notify_chandan(
                                    "LeadFlow - Opt-out Received",
                                    f"Opt-out ({classification}) detected from {biz_name} ({sender_email}).\n\nReply:\n\"{body_text[:200]}\"",
                                    tags="no_entry",
                                    priority="default"
                                )
                            except Exception as opt_err:
                                log.warning(f"Failed to send opt-out notification: {opt_err}")
                        elif classification == 'interested':
                            log.info(f"Interested reply from {sender_email} for business {bid}!")
                            cursor.execute("UPDATE businesses SET status='replied' WHERE id=?", (bid,))
                            cursor.execute("UPDATE contacts SET reply_text = CASE WHEN reply_text IS NULL OR reply_text = '' THEN ? ELSE reply_text || '\n\n━━━━━━━━━━━━━━━━━━━━\n\n' || ? END WHERE business_id=?", (body_text, body_text, bid))
                            cursor.execute("UPDATE outreach SET replied=1 WHERE business_id=?", (bid,))
                            cursor.execute("DELETE FROM follow_ups WHERE business_id=? AND status='pending'", (bid,))
                            
                            conn.commit()  # <-- commit before send_email to prevent DB deadlock
                            try:
                                from sender import send_email
                                import uuid as _uuid
                                booking_url = os.getenv("CALENDLY_URL") or os.getenv("BOOKING_URL") or "https://calendly.com"
                                agency_name = os.getenv("AGENCY_NAME", "LeadFlow Agency")
                                
                                # Get business name
                                biz_name = "there"
                                biz_row = cursor.execute("SELECT name FROM businesses WHERE id=?", (bid,)).fetchone()
                                if biz_row:
                                    biz_name = biz_row["name"]
                                    
                                client_subject = msg.get("Subject", "your custom demo website")
                                if not client_subject.lower().startswith("re:"):
                                    auto_subject = f"Re: {client_subject}"
                                else:
                                    auto_subject = client_subject
                                    
                                client_msg_id = msg.get("Message-ID")
                                auto_tracking_id = str(_uuid.uuid4())
                                
                                auto_body = (
                                    f"Hi,\n\n"
                                    f"Thanks for your interest! I'd love to chat and show you how we can customize this "
                                    f"specifically for your business to help drive more customers.\n\n"
                                    f"Could you pick a quick time on my calendar here to connect?\n"
                                    f"{booking_url}\n\n"
                                    f"Talk soon,\n"
                                    f"{agency_name}"
                                )
                                send_email(sender_email, auto_subject, auto_body, business_id=bid,
                                           reply_to_message_id=client_msg_id)
                                log.info(f"Sent auto-reply with booking link to {sender_email}")

                                # fix #8: record the auto-reply in outreach so it's visible in CRM
                                cursor.execute("""
                                    INSERT INTO outreach
                                        (business_id, channel, final_message, status, sent_at, is_autopilot, tracking_id)
                                    VALUES (?, 'email', ?, 'sent', datetime('now'), 1, ?)
                                """, (bid, auto_body, auto_tracking_id))
                                conn.commit()
                                
                                notify_chandan(
                                    "LeadFlow - HOT INTEREST!",
                                    f"Interested reply from {biz_name} ({sender_email})! Auto-reply sent.\n\nReply:\n\"{body_text[:400]}\"",
                                    tags="moneybag,fire",
                                    priority="high"
                                )
                            except Exception as reply_err:
                                log.warning(f"Failed to process auto-reply/notification: {reply_err}")
                        else:
                            # question reply path
                            log.info(f"Question reply from {sender_email} for business {bid}!")
                            cursor.execute("UPDATE businesses SET status='replied' WHERE id=?", (bid,))
                            cursor.execute("UPDATE contacts SET reply_text = CASE WHEN reply_text IS NULL OR reply_text = '' THEN ? ELSE reply_text || '\n\n━━━━━━━━━━━━━━━━━━━━\n\n' || ? END WHERE business_id=?", (body_text, body_text, bid))
                            cursor.execute("UPDATE outreach SET replied=1 WHERE business_id=?", (bid,))
                            cursor.execute("DELETE FROM follow_ups WHERE business_id=? AND status='pending'", (bid,))

                            conn.commit()  # commit before sending email
                            try:
                                biz_name = "there"
                                biz_row = cursor.execute("SELECT name, demo_tunnel_url FROM businesses WHERE id=?", (bid,)).fetchone()
                                if biz_row:
                                    biz_name = biz_row["name"]
                                    demo_url = biz_row["demo_tunnel_url"] or ""

                                # Re-send the original personalised outreach as the reply
                                orig = cursor.execute(
                                    "SELECT final_message, draft, subject_used FROM outreach "
                                    "WHERE business_id=? AND channel='email' AND status='sent' "
                                    "ORDER BY sent_at ASC LIMIT 1",
                                    (bid,)
                                ).fetchone()

                                if orig:
                                    original_body = orig["final_message"] or orig["draft"] or ""
                                    original_subject = orig["subject_used"] or f"Re: your question about {biz_name}"
                                    if original_body:
                                        client_msg_id = msg.get("Message-ID")
                                        re_subject = original_subject if original_subject.lower().startswith("re:") else f"Re: {original_subject}"

                                        # AI-generated intro that acknowledges their specific question
                                        ai_intro = ""
                                        try:
                                            from ai_writer import _run as _ai_run
                                            agency = os.getenv("AGENCY_NAME", "us")
                                            ai_prompt = (
                                                f"A prospect named '{biz_name}' replied to our cold email with this message:\n\n"
                                                f"\"{body_text[:600]}\"\n\n"
                                                f"Write a SHORT 2-3 sentence reply that:\n"
                                                f"1. Briefly answers their question (we build custom demo websites for local businesses so they can see exactly what their site could look like — no commitment needed)\n"
                                                f"2. Naturally leads into showing them the demo we already built for them\n"
                                                f"3. Ends with something like 'I actually already put together a quick demo for you — take a look:'\n\n"
                                                f"Write ONLY the reply text, no subject line, no sign-off. Keep it warm, natural, and under 60 words."
                                            )
                                            ai_intro = _ai_run(ai_prompt) or ""
                                            if ai_intro:
                                                ai_intro = ai_intro.strip() + "\n\n"
                                        except Exception as _ai_err:
                                            log.warning(f"AI intro generation failed: {_ai_err}")

                                        combined_body = ai_intro + original_body if ai_intro else original_body

                                        from sender import send_email
                                        send_email(
                                            sender_email, re_subject, combined_body,
                                            demo_url=demo_url,
                                            business_id=bid,
                                            reply_to_message_id=client_msg_id
                                        )
                                        log.info(f"Re-sent original outreach to {sender_email} as reply to question")

                                notify_chandan(
                                    "LeadFlow - Lead Question (original outreach re-sent)",
                                    f"Question from {biz_name} ({sender_email}).\n\nReply:\n\"{body_text[:400]}\"",
                                    tags="speech_balloon",
                                    priority="default"
                                )
                            except Exception as _e:
                                log.warning(f'Question reply handler error: {_e}')
                        conn.commit()
                # -- SCAN SENT MAIL FOR MANUAL REPLIES --
                try:
                    mail.select('"[Gmail]/Sent Mail"')
                    status, messages = mail.search(None, f'(SINCE "{since_date}")')
                    if status == "OK" and messages[0]:
                        email_ids = messages[0].split()
                        for eid in email_ids:
                            # Fetch ONLY headers first (super fast)
                            res, header_data = mail.fetch(eid, "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID TO)])")
                            if res != "OK":
                                continue
                                
                            header_str = header_data[0][1].decode(errors="ignore")
                            msg_headers = email.message_from_string(header_str)
                            
                            recipient = msg_headers.get("To", "")
                            message_id = msg_headers.get("Message-ID", "")
                            
                            if not recipient:
                                continue
                                
                            if "<" in recipient and ">" in recipient:
                                recipient_email = recipient.split("<")[1].split(">")[0].strip().lower()
                            else:
                                recipient_email = recipient.strip().lower()

                            # Only fetch full body if recipient is a known lead
                            if recipient_email in email_to_bid:
                                bid = email_to_bid[recipient_email]
                                
                                # Skip if already logged in outreach
                                if message_id:
                                    existing_outreach = cursor.execute("SELECT id FROM outreach WHERE message_id=?", (message_id,)).fetchone()
                                    if existing_outreach:
                                        continue
                                        
                                # Now fetch full body
                                res, full_msg_data = mail.fetch(eid, "(RFC822)")
                                if res != "OK":
                                    continue
                                    
                                msg = None
                                for response_part in full_msg_data:
                                    if isinstance(response_part, tuple):
                                        msg = email.message_from_bytes(response_part[1])
                                        break
                                        
                                if not msg:
                                    continue
                                
                                body_text = get_email_body(msg)
                                # Add to outreach as a manually sent message
                                cursor.execute("""
                                    INSERT INTO outreach (business_id, channel, final_message, status, message_id)
                                    VALUES (?, 'email', ?, 'sent', ?)
                                """, (bid, body_text, message_id))
                                log.info(f"Synced manual sent email to {recipient_email} for business {bid}")
                                conn.commit()
                except Exception as e:
                    log.warning(f"Could not scan Sent Mail for {email_addr}: {e}")

            except Exception as e:
                log.warning(f"IMAP Error for account {email_addr}: {e}")
            finally:
                if mail:
                    try:
                        mail.close()
                    except Exception as _e:
                        log.warning(f'IMAP close error: {_e}')
                    try:
                        mail.logout()
                    except Exception as _e:
                        log.warning(f'IMAP close error: {_e}')

        log.info("Finished checking replies across all accounts.")

    except Exception as e:
        log.warning(f"Database/IMAP outer Error: {e}")
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

if __name__ == "__main__":
    check_replies()
