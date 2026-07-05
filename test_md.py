import asyncio
from telethon.extensions.markdown import parse

text = "[Click to DM @user_name_123](https://instagram.com/user_name_123)"
try:
    res = parse(text)
    print("Parsed OK:", res)
except Exception as e:
    print("Error:", e)
