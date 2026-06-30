import sqlite3
import ai_writer
from database import get_conn
from deploy import demo_url_for

def generate_drafts():
    conn = get_conn()
    c = conn.cursor()
    # Fetch high ticket leads with phone numbers that don't have IG handles and don't already have a WA draft
    c.execute("""
        SELECT b.id, b.name, b.category, b.website, b.website_score, b.gap, b.competitor_deficit, b.pitch_type, b.lead_score, b.phone, b.google_rating, b.google_reviews 
        FROM businesses b
        JOIN contacts con ON con.business_id = b.id
        WHERE b.category IN ('medspa', 'solar', 'roofing', 'remodeler', 'lawyer', 'hvac', 'plumbing', 'tree service', 'landscaping', 'chiropractor', 'dentist', 'real estate')
        AND b.phone IS NOT NULL AND b.phone != ''
        AND (con.instagram IS NULL OR con.instagram = '')
        AND b.status IN ('new', 'approved', 'sent')
        AND b.id NOT IN (SELECT business_id FROM outreach WHERE channel = 'whatsapp')
        LIMIT 200
    """)
    rows = c.fetchall()
    for r in rows:
        biz_dict = {
            "id": r[0], "name": r[1], "category": r[2], "website": r[3],
            "website_score": r[4], "gap": r[5], "competitor_deficit": r[6],
            "pitch_type": r[7], "lead_score": r[8], "phone": r[9],
            "google_rating": r[10], "google_reviews": r[11]
        }
        print(f"Generating WA draft for {biz_dict['name']}...")
        draft = ai_writer.write_whatsapp_dm(biz_dict)
        demo_url = demo_url_for(r[0], r[1])
        if demo_url and demo_url not in draft:
            draft += f"\n\nDemo: {demo_url}?utm=wa"
        c.execute("""
            INSERT INTO outreach (business_id, channel, status, draft, sent_at)
            VALUES (?, 'whatsapp', 'draft', ?, NULL)
        """, (r[0], draft))
    conn.commit()
    conn.close()
    print("Done generating WA drafts.")

if __name__ == "__main__":
    generate_drafts()
