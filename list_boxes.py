import os, imaplib
from dotenv import load_dotenv
load_dotenv()
mail = imaplib.IMAP4_SSL("imap.gmail.com")
mail.login("chandango12@gmail.com", os.getenv("SENDER_APP_PASSWORD").split(",")[0].strip())
print(mail.list())
