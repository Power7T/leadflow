import sqlite3
import urllib.parse
from pathlib import Path

db_path = Path(__file__).parents[2] / "leadflow.db"
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

# Find all emails in contacts table
rows = conn.execute("SELECT business_id, email, hunter_email, apollo_email FROM contacts").fetchall()

print(f"Total contacts: {len(rows)}")
updated_count = 0
for row in rows:
    bid = row["business_id"]
    email = row["email"]
    hunter = row["hunter_email"]
    apollo = row["apollo_email"]
    
    needs_update = False
    new_email = email
    new_hunter = hunter
    new_apollo = apollo
    
    if email and ("%20" in email or " " in email):
        new_email = urllib.parse.unquote(email).strip()
        needs_update = True
        print(f"Bid {bid}: email '{email}' -> '{new_email}'")
        
    if hunter and ("%20" in hunter or " " in hunter):
        new_hunter = urllib.parse.unquote(hunter).strip()
        needs_update = True
        print(f"Bid {bid}: hunter '{hunter}' -> '{new_hunter}'")
        
    if apollo and ("%20" in apollo or " " in apollo):
        new_apollo = urllib.parse.unquote(apollo).strip()
        needs_update = True
        print(f"Bid {bid}: apollo '{apollo}' -> '{new_apollo}'")
        
    if needs_update:
        conn.execute(
            "UPDATE contacts SET email=?, hunter_email=?, apollo_email=? WHERE business_id=?",
            (new_email, new_hunter, new_apollo, bid)
        )
        updated_count += 1

if updated_count > 0:
    conn.commit()
    print(f"Updated {updated_count} rows in database.")
else:
    print("No matching rows found to update.")

conn.close()
