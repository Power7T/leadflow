import sqlite3
conn = sqlite3.connect("/data/data/com.termux/files/home/leadflow/leadflow.db")
conn.execute("DELETE FROM outreach WHERE channel = 'instagram' AND status = 'draft'")
conn.commit()
