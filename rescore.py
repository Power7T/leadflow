import sqlite3
from pathlib import Path
from scorer import score_lead

conn = sqlite3.connect(str(Path(__file__).parent / 'leadflow.db'))
c = conn.cursor()
c.execute('SELECT id, website_score, google_reviews, google_rating, website, category, pitch_type, name FROM businesses')
rows = c.fetchall()
updates = []

for r in rows:
    biz = {
        'website_score': r[1],
        'google_reviews': r[2],
        'google_rating': r[3],
        'website': r[4],
        'category': r[5],
        'pitch_type': r[6],
        'name': r[7]
    }
    c.execute('SELECT email, instagram, linkedin_url, whatsapp FROM contacts WHERE business_id=?', (r[0],))
    ct = c.fetchone()
    contacts = {}
    if ct:
        contacts = {
            'email': ct[0],
            'instagram': ct[1],
            'linkedin_url': ct[2],
            'whatsapp': ct[3]
        }
    ns = score_lead(biz, contacts)
    updates.append((ns, r[0]))

c.executemany('UPDATE businesses SET lead_score=? WHERE id=?', updates)
conn.commit()
print(f'Updated {len(updates)} leads.')
