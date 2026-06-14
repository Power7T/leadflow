import os
import imaplib
import email
from email.header import decode_header
import sqlite3
from dotenv import load_dotenv

load_dotenv()

IMAP_SERVER = os.getenv("IMAP_SERVER", "imap.gmail.com")
IMAP_EMAIL = os.getenv("IMAP_EMAIL", "")
IMAP_PASSWORD = os.getenv("IMAP_PASSWORD", "")

def check_replies():
    if not IMAP_EMAIL or not IMAP_PASSWORD:
        print("IMAP credentials missing in .env. Skipping reply detection.")
        return

    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(IMAP_EMAIL, IMAP_PASSWORD)
        mail.select("inbox")

        # Search for unseen emails
        status, messages = mail.search(None, "UNSEEN")
        if status != "OK" or not messages[0]:
            print("No new emails.")
            mail.close()
            mail.logout()
            return

        email_ids = messages[0].split()
        conn = sqlite3.connect("leadflow.db")
        cursor = conn.cursor()

        # Fetch all known lead emails
        cursor.execute("SELECT business_id, email, hunter_email, apollo_email FROM contacts")
        lead_contacts = cursor.fetchall()

        # Create a mapping of email_address -> business_id
        email_to_bid = {}
        for bid, em, hem, aem in lead_contacts:
            if em: email_to_bid[em.lower()] = bid
            if hem: email_to_bid[hem.lower()] = bid
            if aem: email_to_bid[aem.lower()] = bid

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
                        print(f"Reply detected from {sender_email} for business {bid}!")
                        cursor.execute("UPDATE businesses SET status='replied' WHERE id=?", (bid,))
                        conn.commit()

        conn.close()
        mail.close()
        mail.logout()
        print("Finished checking replies.")

    except Exception as e:
        print(f"IMAP Error: {e}")

if __name__ == "__main__":
    check_replies()
