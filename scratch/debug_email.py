import imaplib, email, os, sys
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

from sender import get_all_sender_accounts

accounts = get_all_sender_accounts()
IMAP_SERVER = os.getenv("IMAP_SERVER", "imap.gmail.com")

for email_addr, pwd in accounts:
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(email_addr, pwd)
        mail.select("inbox")
        status, messages = mail.search(None, '(FROM "info@rock-fitness.com")')
        if status == "OK" and messages[0]:
            email_ids = messages[0].split()
            res, msg_data = mail.fetch(email_ids[-1], "(RFC822)")
            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    msg = email.message_from_bytes(response_part[1])
                    print("SUBJECT:", msg.get("Subject"))
                    if msg.is_multipart():
                        for part in msg.walk():
                            print("PART TYPE:", part.get_content_type())
                            if part.get_content_type() in ["text/plain", "text/html"]:
                                payload = part.get_payload(decode=True)
                                print("CONTENT LEN:", len(payload) if payload else 0)
                                print(payload.decode(errors="ignore")[:200])
                                print("---")
                    else:
                        print("NON-MULTIPART:", msg.get_content_type())
        mail.logout()
    except Exception as e:
        print("Error:", e)
