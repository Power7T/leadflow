import sqlite3
import ai_writer
import time
from demo_generator import _scrape_site

def generate_drafts():
    from database import get_conn
    conn = get_conn()
    c = conn.cursor()
    # Fetch high ticket leads with IG handles that DON'T already have an IG draft
    c.execute("""
        SELECT b.id, b.name, b.category, b.website, b.website_score, b.gap, b.competitor_deficit, b.pitch_type, b.lead_score, con.instagram, b.google_rating, b.google_reviews, b.demo_tunnel_url, b.city, b.tier 
        FROM businesses b
        JOIN contacts con ON con.business_id = b.id
        WHERE b.category IN ('medspa', 'solar', 'roofing', 'remodeler', 'lawyer', 'hvac', 'plumbing', 'tree service', 'landscaping', 'chiropractor', 'dentist', 'real estate', 'gym', 'fitness', 'accountant', 'cpa', 'electrician', 'pool', 'detailing', 'auto detailing', 'flooring', 'moving', 'painter', 'painting', 'barber', 'barbershop', 'restaurant', 'cleaning')
        AND con.instagram IS NOT NULL AND con.instagram != ''
        AND b.status IN ('new', 'approved', 'sent')
        AND b.id NOT IN (SELECT business_id FROM outreach WHERE channel = 'instagram')
        LIMIT 200
    """)
    rows = c.fetchall()
    conn.close()
    
    for r in rows:
        biz_dict = {
            "id": r[0], "name": r[1], "category": r[2], "website": r[3],
            "website_score": r[4], "gap": r[5], "competitor_deficit": r[6],
            "pitch_type": r[7], "lead_score": r[8], "instagram": r[9],
            "google_rating": r[10], "google_reviews": r[11],
            "demo_tunnel_url": r[12], "city": r[13], "tier": r[14]
        }

        # ── Get demo URL ──────────────────────────────────────────────────────
        demo_url = biz_dict.get("demo_tunnel_url") or ""

        # ── Scrape website for personalisation context ────────────────────────
        scraped = {}
        website = biz_dict.get("website") or ""
        if website:
            try:
                scraped = _scrape_site(website) or {}
            except Exception as e:
                print(f"  [scrape error] {e}")

        # Fetch top competitor
        from demo_generator import get_competitor_name
        comp = get_competitor_name(biz_dict.get("category", ""), biz_dict.get("city", ""), biz_dict.get("name", ""))
        if comp:
            scraped["top_competitor"] = comp

        print(f"Generating IG draft for {biz_dict['name']} (demo={bool(demo_url)}, scraped={bool(scraped)})...")
        try:
            draft = ai_writer.write_instagram_dm(biz_dict, demo_url=demo_url, scraped=scraped or None)
        except Exception as e:
            print(f"  [AI draft error] Failed to generate for {biz_dict['name']}: {e}")
            draft = None

        if draft:
            # Open a fast, short-lived connection just for the insert to prevent SQLite locking
            insert_conn = get_conn()
            insert_c = insert_conn.cursor()
            try:
                insert_c.execute("""
                    INSERT INTO outreach (business_id, channel, draft, status)
                    VALUES (?, 'instagram', ?, 'draft')
                """, (biz_dict['id'], draft))
                insert_conn.commit()
                print(f"Draft saved: {draft}\n")
            except Exception as e:
                print(f"Error saving draft: {e}")
            finally:
                insert_conn.close()
            
        time.sleep(2)  # brief pause to avoid hitting rate limits too fast
    print("Done!")

if __name__ == '__main__':
    generate_drafts()
