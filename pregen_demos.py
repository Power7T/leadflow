"""
Pre-generate GitHub Pages demos for the top 100 backlog leads that don't have
a demo URL yet. This prevents the scheduler from timing out at send time
waiting for GitHub Pages to propagate.
"""
import sys
import os
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parents[2]))

import sqlite3
import requests
import time

DB_PATH = str(pathlib.Path(__file__).parents[2] / "leadflow.db")
GENERATE_URL = 'http://127.0.0.1:8765/leads/{id}/generate'

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
c = conn.cursor()

# Find top leads by score that have email but no demo yet
rows = c.execute("""
    SELECT b.id, b.name, b.category, b.lead_score
    FROM businesses b
    JOIN contacts ct ON ct.business_id = b.id
    WHERE b.status IN ('new', 'approved')
      AND (b.demo_tunnel_url IS NULL OR b.demo_tunnel_url = '')
      AND ct.email IS NOT NULL AND ct.email != ''
      AND b.lead_score >= 25
    ORDER BY b.lead_score DESC
    LIMIT 100
""").fetchall()

leads = [dict(r) for r in rows]
conn.close()

print(f"Found {len(leads)} leads needing demos pre-generated.")

success = 0
failed = 0
for i, lead in enumerate(leads):
    print(f"[{i+1}/{len(leads)}] Generating demo for: {lead['name']} ({lead['category']}, score={lead['lead_score']})")
    try:
        resp = requests.post(
            GENERATE_URL.format(id=lead['id']),
            json={"channels": ["email"]},
            timeout=200
        )
        if resp.status_code == 200:
            print(f"  ✅ Done")
            success += 1
        else:
            print(f"  ❌ Failed: {resp.status_code} - {resp.text[:100]}")
            failed += 1
    except Exception as e:
        print(f"  ❌ Error: {e}")
        failed += 1
    
    # Small delay to avoid hammering the API
    time.sleep(2)

print(f"\nCompleted: {success} demos generated, {failed} failed.")
