import requests, os
from dotenv import load_dotenv

load_dotenv("/Users/chandan/leadflow/.env")
PUBLIC_URL = os.getenv("LEADFLOW_PUBLIC_URL", "https://leadflow-relay.chandango12.workers.dev")
SECRET_TOKEN = os.getenv("LEADFLOW_SECRET_TOKEN")

payload = {
    "business": {"id": 100060, "name": "Health & Fitness", "city": "NYC", "category": "gym"},
    "website_data": {"title": "Test", "description": "Test", "about_text": "Test", "services": []},
    "template_id": "gym.html",
    "hero_img": "https://images.unsplash.com/photo-1517838277536-f5f99be501cd?w=1400",
    "about_img": "https://images.unsplash.com/photo-1534438327276-14e5300c3a48?w=600"
}
r = requests.post(f"{PUBLIC_URL}/api/demo?slug=100060", headers={"X-Secret-Token": SECRET_TOKEN, "Content-Type": "application/json"}, json=payload)
print(r.status_code)
