import sqlite3
import ai_writer

def generate_drafts():
    conn = sqlite3.connect('leadflow.db')
    c = conn.cursor()
    # Fetch 5 high ticket leads with IG handles that DON'T already have an IG draft
    c.execute("""
        SELECT b.id, b.name, b.category, b.website, b.website_score, b.gap, b.competitor_deficit, b.pitch_type, b.lead_score, con.instagram, b.google_rating, b.google_reviews 
        FROM businesses b
        JOIN contacts con ON con.business_id = b.id
        WHERE b.category IN ('medspa', 'solar', 'roofing', 'remodeler', 'lawyer', 'hvac', 'plumbing', 'tree service', 'landscaping', 'chiropractor', 'dentist', 'real estate')
        AND con.instagram IS NOT NULL AND con.instagram != ''
        AND b.status IN ('new', 'approved', 'sent')
        AND b.id NOT IN (SELECT business_id FROM outreach WHERE channel = 'instagram')
        LIMIT 200
    """)
    rows = c.fetchall()
    for r in rows:
        biz_dict = {
            "id": r[0], "name": r[1], "category": r[2], "website": r[3],
            "website_score": r[4], "gap": r[5], "competitor_deficit": r[6],
            "pitch_type": r[7], "lead_score": r[8], "instagram": r[9],
            "google_rating": r[10], "google_reviews": r[11]
        }
        print(f"Generating IG draft for {biz_dict['name']}...")
        draft = ai_writer.write_instagram_dm(biz_dict)
        
        # Insert into outreach
        c.execute("""
            INSERT INTO outreach (business_id, channel, draft, status)
            VALUES (?, 'instagram', ?, 'draft')
        """, (biz_dict['id'], draft))
        print(f"Draft saved: {draft}\n")
    
    conn.commit()
    print("Done!")

if __name__ == '__main__':
    generate_drafts()
