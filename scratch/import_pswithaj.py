import sys
import os
sys.path.append(str(Path(__file__).parents[2]))

import asyncio
from extractor import scrape_instagram_profile
from database import insert_business, insert_contacts, get_conn
from demo_generator import generate_instagram_custom_demo_html
from pathlib import Path

async def main():
    conn = get_conn()
    conn.execute("DELETE FROM contacts WHERE instagram = 'pswithaj'")
    conn.execute("DELETE FROM businesses WHERE website LIKE '%pswithaj%' OR name = 'Pswithaj'")
    conn.commit()
    conn.close()
    print("Deleted any existing pswithaj record for a clean re-import.")

    url = "https://www.instagram.com/pswithaj?igsh=dzV0czQwNnd4ZGpi"
    print(f"Scraping {url}...")
    profile = scrape_instagram_profile(url)
    print("Scraped profile details:")
    print(profile)
    
    if not profile or not profile.get("instagram"):
        print("Failed to scrape.")
        return
        
    followers_str = profile.get("followers", "0").replace(",", "").replace(".", "").strip()
    followers_val = 0
    try:
        if "k" in followers_str.lower():
            followers_val = int(float(followers_str.lower().replace("k", "")) * 1000)
        elif "m" in followers_str.lower():
            followers_val = int(float(followers_str.lower().replace("m", "")) * 1000000)
        else:
            followers_val = int(followers_str)
    except Exception:
        pass
        
    lead_score = 50
    if followers_val > 100000:
        lead_score = 95
    elif followers_val > 10000:
        lead_score = 80
    elif followers_val > 5000:
        lead_score = 70
    elif followers_val > 1000:
        lead_score = 60
        
    bus_id = insert_business({
        "name": profile["name"],
        "category": profile["category"],
        "website": f"https://www.instagram.com/{profile['instagram']}/",
        "gap": profile["bio"],
        "maps_url": profile["profile_pic"],
        "google_reviews": followers_val,
        "google_rating": 5.0,
        "source": "instagram_reach",
        "pitch_type": "instagram_reach",
        "status": "new",
        "lead_score": lead_score,
        "city": "Instagram",
        "country": "Online"
    })
    
    insert_contacts(bus_id, {
        "instagram": profile["instagram"],
        "email": ""
    })
    
    from extractor import EMAIL_RE
    bio_emails = EMAIL_RE.findall(profile["bio"])
    if bio_emails:
        conn = get_conn()
        conn.execute("UPDATE contacts SET email=? WHERE business_id=?", (bio_emails[0], bus_id))
        conn.commit()
        conn.close()
        print(f"Extracted email from bio: {bio_emails[0]}")
        
    print(f"Added business to DB with ID: {bus_id}")
    
    # Get the lead from database to make sure dict has all fields
    from database import get_lead_by_id
    lead = get_lead_by_id(bus_id)
    
    print("Generating custom website for lead using Gemini...")
    html = generate_instagram_custom_demo_html(lead)
    
    # Save the demo html to DEMOS_DIR
    demos_dir = Path(__file__).parents[3] / "demos"
    demos_dir.mkdir(exist_ok=True)
    
    (demos_dir / f"{bus_id}.html").write_text(html, encoding="utf-8")
    print(f"Successfully generated and saved demo site to {demos_dir}/{bus_id}.html")

if __name__ == '__main__':
    asyncio.run(main())
