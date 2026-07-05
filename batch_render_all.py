import os
import sqlite3
import server

# Get the local Mac tunnel URL
tunnel_url = server._start_leadflow_tunnel()
print(f"Using Mac Tunnel: {tunnel_url}")

db_path = "/Users/chandan/leadflow/leadflow.db"
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# Get ALL businesses missing a demo link or using the old edge link
cur.execute("""
    SELECT id, name
    FROM businesses 
    WHERE status IN ('new', 'approved', 'sent')
""")
businesses = cur.fetchall()

print(f"Routing {len(businesses)} demos to local Mac server...")

updated = 0
for r in businesses:
    bid = r["id"]
    demo_url = f"{tunnel_url}/demo/{bid}"
    cur.execute("UPDATE businesses SET demo_tunnel_url = ? WHERE id = ?", (demo_url, bid))
    updated += 1

conn.commit()
print(f"Successfully routed {updated} demos to the Mac local tunnel!")
