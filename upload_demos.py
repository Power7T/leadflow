import os
import sqlite3
import json
import requests
import time
from pathlib import Path
from dotenv import load_dotenv

# Load main env configurations
load_dotenv("/Users/chandan/leadflow/.env")

PUBLIC_URL = os.getenv("LEADFLOW_PUBLIC_URL", "https://leadflow-relay.chandango12.workers.dev")
SECRET_TOKEN = os.getenv("LEADFLOW_SECRET_TOKEN", "lf_sec_9e21808ccce4d37")
DEMO_TEMPLATES_DIR = Path("/Users/chandan/leadflow/demo_templates")

# 1. Load config.json template rules
config_path = DEMO_TEMPLATES_DIR / "config.json"
templates_list = []
if config_path.exists():
    try:
        config_data = json.loads(config_path.read_text(encoding="utf-8"))
        templates_list = config_data.get("templates", [])
    except Exception as e:
        print(f"Error loading template config: {e}")

def get_template_for(category, name, assigned_template):
    if assigned_template and assigned_template.endswith(".html"):
        return assigned_template
        
    category_lower = (category or "").lower()
    name_lower = (name or "").lower()
    
    for tpl in templates_list:
        if not tpl.get("enabled", True):
            continue
        tpl_file = tpl.get("file")
        if not tpl_file:
            continue
        niches = tpl.get("niches", [])
        if any(n in category_lower or n in name_lower for n in niches):
            return tpl_file
            
    return "dentist.html" # fallback

# Connect to database
db_path = "/Users/chandan/leadflow/leadflow.db"
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# Get all Tier 1 & Tier 2 businesses for IG
cur.execute("""
    SELECT id, name, category, address, city, phone, website, website_score, google_rating, google_reviews, template_id, pitch_type 
    FROM businesses 
    WHERE tier IN (1, 2)
""")
rows = cur.fetchall()

print(f"Found {len(rows)} businesses to upload demo data for.")

success_count = 0
for row in rows:
    biz = dict(row)
    bid = biz["id"]
    name = biz["name"] or "Your Business"
    category = biz["category"] or "services"
    
    tpl = get_template_for(category, name, biz.get("template_id"))
    
    hero_img = "https://images.unsplash.com/photo-1522071820081-009f0129c71c?w=1400"
    about_img = "https://images.unsplash.com/photo-1521737711867-e3b904737c88?w=600"
    
    if tpl == "gym.html":
        hero_img = "https://images.unsplash.com/photo-1517838277536-f5f99be501cd?w=1400"
        about_img = "https://images.unsplash.com/photo-1534438327276-14e5300c3a48?w=600"
    elif tpl == "restaurant.html":
        hero_img = "https://images.unsplash.com/photo-1414235077428-338989a2e8c0?w=1400"
        about_img = "https://images.unsplash.com/photo-1550966871-3ed3cdb5ed0c?w=600"
    elif tpl == "chiropractor.html":
        hero_img = "https://power7t.github.io/leadflow-demos/chiro-hero.jpg"
        about_img = "https://power7t.github.io/leadflow-demos/chiro-about.jpg"
    elif tpl == "medspa.html":
        hero_img = "https://images.unsplash.com/photo-1522335789203-aabd1fc54bc9?w=1400"
        about_img = "https://images.unsplash.com/photo-1512290923902-8a9f81dc236c?w=600"
    elif tpl == "barbershop.html":
        hero_img = "https://images.unsplash.com/photo-1503951914875-452162b0f3f1?w=1400"
        about_img = "https://images.unsplash.com/photo-1593702295094-aec22597af65?w=600"
    elif tpl == "realestate.html":
        hero_img = "https://images.unsplash.com/photo-1600596542815-ffad4c1539a9?w=1400"
        about_img = "https://images.unsplash.com/photo-1600607687939-ce8a6c25118c?w=600"
    elif tpl == "hvac.html" or tpl == "roofing.html":
        hero_img = "https://images.unsplash.com/photo-1621905251189-08b45d6a269e?w=1400"
        about_img = "https://images.unsplash.com/photo-1581094288338-2314dddb7ecc?w=600"
    elif tpl == "lawyer.html":
        hero_img = "https://images.unsplash.com/photo-1589829545856-d10d557cf95f?w=1400"
        about_img = "https://images.unsplash.com/photo-1450133064473-71024230f91b?w=600"

    payload = {
        "business": biz,
        "website_data": {
            "title": f"{name} Web presentation",
            "description": f"Expert {category} services in {biz['city'] or 'your area'}.",
            "about_text": f"Welcome to {name}. We are dedicated to providing the highest quality {category} services in {biz['city'] or 'our city'}. Contact us today to learn more.",
            "services": ["Professional Diagnostics", "Custom Consultation", "Quality Verification", "24/7 Support"]
        },
        "template_id": tpl,
        "hero_img": hero_img,
        "about_img": about_img
    }

    try:
        r = requests.post(
            f"{PUBLIC_URL}/api/demo?slug={bid}",
            headers={"X-Secret-Token": SECRET_TOKEN, "Content-Type": "application/json"},
            json=payload,
            timeout=5
        )
        if r.status_code == 200:
            success_count += 1
            print(f"✅ Synced {bid} ({name})")
        else:
            print(f"❌ Failed to sync {bid}: {r.status_code}")
    except Exception as e:
        print(f"❌ Error syncing {bid}: {e}")

print(f"\nDone! Successfully synced {success_count} demos to KV.")
