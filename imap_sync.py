import os
import imaplib
import email
from email.header import decode_header
import sqlite3
from dotenv import load_dotenv

load_dotenv()

IMAP_SERVER = os.getenv("IMAP_SERVER", "imap.gmail.com")
IMAP_EMAIL = os.getenv("IMAP_EMAIL") or os.getenv("SENDER_EMAIL") or ""
IMAP_PASSWORD = os.getenv("IMAP_PASSWORD") or os.getenv("SENDER_APP_PASSWORD") or ""


def get_email_body(msg) -> str:
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition"))
            if content_type == "text/plain" and "attachment" not in content_disposition:
                payload = part.get_payload(decode=True)
                if payload:
                    body += payload.decode(errors="ignore")
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            body = payload.decode(errors="ignore")
    return body

def check_replies():
    from sender import get_all_sender_accounts
    accounts = get_all_sender_accounts()
    if not accounts:
        print("No sender accounts configured. Skipping reply detection.")
        return

    from database import DB_PATH
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10.0)
        conn.row_factory = sqlite3.Row
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
            print(f"Checking replies for account: {email_addr}")
            mail = None
            try:
                mail = imaplib.IMAP4_SSL(IMAP_SERVER)
                mail.login(email_addr, pwd)
                mail.select("inbox")

                # Search for unseen emails
                status, messages = mail.search(None, "UNSEEN")
                if status != "OK" or not messages[0]:
                    print(f"No new emails for {email_addr}.")
                    continue

                email_ids = messages[0].split()
                for eid in email_ids:
                    res, msg_data = mail.fetch(eid, "(RFC822)")
                    for response_part in msg_data:
                        if isinstance(response_part, tuple):
                            msg = email.message_from_bytes(response_part[1])
                            sender = msg.get("From")
                            if not sender: continue
                            
                            # Extract email from "Name <email@domain.com>"
                            if "<" in sender and ">" in sender:
                                sender_email = sender.split("<")[1].split(">")[0].strip().lower()
                            else:
                                sender_email = sender.strip().lower()

                            if sender_email in email_to_bid:
                                bid = email_to_bid[sender_email]
                                
                                # Check body for opt-out/unsubscribe intent
                                body_text = get_email_body(msg).lower()
                                opt_out_words = {"unsubscribe", "remove", "stop", "don't email", "dont email", "not interested", "please stop", "leave us out"}
                                is_opt_out = any(word in body_text for word in opt_out_words)
                                
                                if is_opt_out:
                                    print(f"Opt-out request detected from {sender_email} for business {bid}!")
                                    cursor.execute("UPDATE businesses SET status='opted_out' WHERE id=?", (bid,))
                                    cursor.execute("DELETE FROM follow_ups WHERE business_id=? AND status='pending'", (bid,))
                                else:
                                    print(f"Reply detected from {sender_email} for business {bid}!")
                                    cursor.execute("UPDATE businesses SET status='replied' WHERE id=?", (bid,))
                                    cursor.execute("DELETE FROM follow_ups WHERE business_id=? AND status='pending'", (bid,))
                                conn.commit()
            except Exception as e:
                print(f"IMAP Error for account {email_addr}: {e}")
            finally:
                if mail:
                    try:
                        mail.close()
                    except Exception:
                        pass
                    try:
                        mail.logout()
                    except Exception:
                        pass

        print("Finished checking replies across all accounts.")

    except Exception as e:
        print(f"Database/IMAP outer Error: {e}")
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

if __name__ == "__main__":
    check_replies()
