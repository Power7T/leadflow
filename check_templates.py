import sqlite3
import random
import asyncio
import os
import re
from playwright.async_api import async_playwright

TARGET_TEMPLATES = [
    "gym.html", "dentist.html", "restaurant.html", "chiropractor.html", 
    "medspa.html", "barbershop.html", "realestate.html", "hvac.html", "lawyer.html"
]

def slugify(text: str) -> str:
    t = " ".join(text.split()[:3]).lower()
    return re.sub(r'[^a-z0-9]+', '-', t).strip('-')

def get_demo_url(bid, name):
    slug = f"{slugify(name)}-{bid}"
    return f"https://leadflow-relay.chandango12.workers.dev/demo/{slug}"

async def main():
    conn = sqlite3.connect('/Users/chandan/leadflow/leadflow.db')
    cur = conn.cursor()
    
    urls_to_test = {}
    
    cur.execute("SELECT id, name, category, template_id FROM businesses WHERE tier IN (1, 2)")
    rows = cur.fetchall()
    
    for tpl in TARGET_TEMPLATES:
        matches = [r for r in rows if r[3] == tpl or (r[2] and tpl.replace('.html', '') in r[2].lower())]
        if matches:
            lead = random.choice(matches)
            urls_to_test[tpl] = (lead[0], lead[1], get_demo_url(lead[0], lead[1]))
    
    conn.close()

    print(f"Testing {len(urls_to_test)} templates...")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        for tpl, (bid, name, url) in urls_to_test.items():
            page = await browser.new_page()
            print(f"Loading {tpl} ({name}) -> {url}")
            try:
                response = await page.goto(url, wait_until="networkidle", timeout=15000)
                await page.screenshot(path=f'/Users/chandan/leadflow/preview_{tpl.replace(".html", "")}.png')
                print(f"✅ {tpl} loaded successfully (Status: {response.status if response else 'Unknown'})")
            except Exception as e:
                print(f"❌ Error loading {tpl}: {e}")
            finally:
                await page.close()
        await browser.close()

asyncio.run(main())
