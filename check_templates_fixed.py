import sqlite3
import random
import asyncio
import os
import requests
import re
from pathlib import Path
from dotenv import load_dotenv
from playwright.async_api import async_playwright

load_dotenv("/Users/chandan/leadflow/.env")
PUBLIC_URL = os.getenv("LEADFLOW_PUBLIC_URL", "https://leadflow-relay.chandango12.workers.dev")
SECRET_TOKEN = os.getenv("LEADFLOW_SECRET_TOKEN")

TARGET_TEMPLATES = [
    "gym.html", "dentist.html", "restaurant.html", "chiropractor.html", 
    "medspa.html", "barbershop.html", "realestate.html", "hvac.html", "lawyer.html"
]

def slugify(text: str) -> str:
    t = " ".join(text.split()[:3]).lower()
    return re.sub(r'[^a-z0-9]+', '-', t).strip('-')

def get_demo_url(bid, name):
    slug = f"{slugify(name)}-{bid}"
    return f"{PUBLIC_URL}/demo/{slug}"

async def main():
    conn = sqlite3.connect('/Users/chandan/leadflow/leadflow.db')
    cur = conn.cursor()
    
    urls_to_test = {}
    
    cur.execute("SELECT id, name, category, template_id, city FROM businesses WHERE tier IN (1, 2) LIMIT 1000")
    rows = cur.fetchall()
    
    for tpl in TARGET_TEMPLATES:
        matches = [r for r in rows if str(r[3]) == tpl or (r[2] and tpl.replace('.html', '') in r[2].lower())]
        if matches:
            lead = random.choice(matches)
            bid, name, category, _tpl, city = lead
            
            # Manually sync this specific lead to KV just to be 100% sure it's fresh
            payload = {
                "business": {"id": bid, "name": name, "city": city, "category": category},
                "website_data": {"title": f"{name} Web presentation", "description": "Test", "about_text": "Test"},
                "template_id": tpl,
                "hero_img": f"https://images.unsplash.com/photo-1517838277536-f5f99be501cd?w=1400",
                "about_img": f"https://images.unsplash.com/photo-1534438327276-14e5300c3a48?w=600"
            }
            # Add overrides for specific templates if needed, but not strictly necessary for visual check
            if tpl == "chiropractor.html":
                payload["hero_img"] = "https://power7t.github.io/leadflow-demos/chiro-hero.jpg"
                payload["about_img"] = "https://power7t.github.io/leadflow-demos/chiro-about.jpg"
            
            r = requests.post(f"{PUBLIC_URL}/api/demo?slug={bid}", 
                headers={"X-Secret-Token": SECRET_TOKEN, "Content-Type": "application/json"}, json=payload)
            print(f"Synced {tpl} ({name} - {bid}) -> {r.status_code}")
            
            urls_to_test[tpl] = (bid, name, get_demo_url(bid, name))
    
    conn.close()

    print(f"Testing {len(urls_to_test)} templates...")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        for tpl, (bid, name, url) in urls_to_test.items():
            page = await browser.new_page()
            # Intercept images specifically so screenshots load perfectly
            print(f"Loading {tpl} -> {url}")
            try:
                response = await page.goto(url, wait_until="networkidle", timeout=15000)
                await page.screenshot(path=f'/Users/chandan/leadflow/preview_final_{tpl.replace(".html", "")}.png')
                print(f"✅ {tpl} loaded successfully (Status: {response.status if response else 'Unknown'})")
            except Exception as e:
                print(f"❌ Error loading {tpl}: {e}")
            finally:
                await page.close()
        await browser.close()

asyncio.run(main())
