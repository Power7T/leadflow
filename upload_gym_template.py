import os
import requests
from dotenv import load_dotenv

load_dotenv("/Users/chandan/leadflow/.env")

PUBLIC_URL = os.getenv("LEADFLOW_PUBLIC_URL", "https://leadflow-relay.chandango12.workers.dev")
SECRET_TOKEN = os.getenv("LEADFLOW_SECRET_TOKEN")

with open("/Users/chandan/leadflow/demo_templates/gym.html", "r") as f:
    html_content = f.read()

r = requests.post(
    f"{PUBLIC_URL}/api/template?id=gym.html",
    headers={"X-Secret-Token": SECRET_TOKEN, "Content-Type": "text/html"},
    data=html_content.encode('utf-8')
)

print(r.status_code, r.text)
