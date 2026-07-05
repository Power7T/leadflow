import sqlite3
conn = sqlite3.connect('/Users/chandan/leadflow/leadflow.db')
conn.row_factory = sqlite3.Row
row = conn.execute("SELECT o.draft FROM outreach o JOIN contacts c ON c.business_id = o.business_id WHERE c.instagram = '@crystal.sells.homes' OR c.instagram = 'crystal.sells.homes'").fetchone()
if row:
    print(row['draft'])
else:
    print("Not found on Mac, checking Firestick...")
