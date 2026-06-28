import os
import sys
import imaplib
import email
sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv

load_dotenv(str(Path(__file__).parent.parent / '.env'))

body = """Hi Wicker Park Fitness Team,

Apologies for the delay! I wanted to take the time to really look under the hood of your current Squarespace site and ClubReady system to give you an accurate quote.

As the only 24/7 gym in Wicker Park, you have a massive advantage, but your current site is holding you back. Beyond fixing the slow 45/100 mobile speed, I found three low-hanging opportunities to drastically increase your online sign-ups:
* Highlighting Checkouts: Your ClubReady links are currently tucked away. We need to bring them front-and-center.
* The $150 PT Promo: Instead of forcing clients to email you to claim this, we can add a frictionless "click-to-buy" button.
* Free Workout Capture: We can add a simple pop-up for the free workout offer to automatically capture leads, even if they don't show up.

I keep my pricing simple with two one-time flat fees:

Option 1: The Core Redesign ($1,500)
We completely visually remake your website (like the demo I sent) and optimize it for Chicago SEO. We keep your existing ClubReady links but integrate them cleanly so they convert better on mobile.

Option 2: The Automation Setup ($2,000)
Everything in Option 1, plus we build a fully custom, branded checkout directly on your website so users don't have to leave the page. We also set up the lead-capture forms and the digital checkout for the PT promo.

Optional: Hands-Free Site Management ($100/mo)
If you'd prefer to be completely hands-off, I offer an unlimited site management retainer. Whenever you want to swap out gym photos, change class schedules, or put up a new holiday promo, you just shoot me an email and I will personally build and update the site for you so you never have to touch the code.

Which route aligns best with your vision right now?

Best,
Chandan"""

IMAP_SERVER = os.getenv("IMAP_SERVER", "imap.gmail.com")
IMAP_EMAIL = "chandango12@gmail.com"  # The account that emailed them
IMAP_PASSWORD = os.getenv("SENDER_APP_PASSWORD", "").split(",")[0].strip()

mail = imaplib.IMAP4_SSL(IMAP_SERVER)
mail.login(IMAP_EMAIL, IMAP_PASSWORD)
mail.select("inbox")

status, messages = mail.search(None, 'FROM "info@wickerparkfitness.com"')
if status != "OK" or not messages[0]:
    print("Email not found!")
    sys.exit(1)

email_ids = messages[0].split()
# Find the email with "Cost?" subject
client_msg_id = None
client_subject = None

for eid in email_ids[::-1]:
    res, msg_data = mail.fetch(eid, "(RFC822)")
    for response_part in msg_data:
        if isinstance(response_part, tuple):
            msg = email.message_from_bytes(response_part[1])
            sub = msg.get("Subject", "")
            if "cost" in sub.lower():
                client_msg_id = msg.get("Message-ID")
                client_subject = sub
                break
    if client_msg_id:
        break

if not client_msg_id:
    # fallback to latest
    res, msg_data = mail.fetch(email_ids[-1], "(RFC822)")
    for response_part in msg_data:
        if isinstance(response_part, tuple):
            msg = email.message_from_bytes(response_part[1])
            client_msg_id = msg.get("Message-ID")
            client_subject = msg.get("Subject", "Cost?")
            break

print(f"Replying to: {client_subject}")
print(f"Message-ID: {client_msg_id}")

from sender import send_email
send_email(
    to_email="info@wickerparkfitness.com",
    subject=client_subject,
    body=body,
    business_id=97,
    reply_to_message_id=client_msg_id
)
print("Successfully sent exact reply to thread!")
