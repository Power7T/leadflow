import sqlite3, json, base64, os
db_path = "/data/data/com.termux/files/home/leadflow/leadflow.db"
if not os.path.exists(db_path):
    db_path = os.path.join(os.path.dirname(__file__), "leadflow.db")
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT o.draft as ai_draft, c.instagram as instagram_handle FROM outreach o JOIN businesses b ON b.id = o.business_id JOIN contacts c ON c.business_id = o.business_id WHERE o.channel = 'instagram' AND o.status = 'draft' LIMIT 1").fetchall()
print(json.dumps([dict(r) for r in rows]))
