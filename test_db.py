import sqlite3, json, base64
conn = sqlite3.connect("/data/data/com.termux/files/home/leadflow/leadflow.db")
conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT o.draft as ai_draft, c.instagram as instagram_handle FROM outreach o JOIN businesses b ON b.id = o.business_id JOIN contacts c ON c.business_id = o.business_id WHERE o.channel = 'instagram' AND o.status = 'draft' LIMIT 1").fetchall()
print(json.dumps([dict(r) for r in rows]))
