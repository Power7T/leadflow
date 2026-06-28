import os
import sqlite3
import requests
import json
import logging

log = logging.getLogger("leadflow.sync")
log.setLevel(logging.INFO)

DB_PATH = os.path.join(os.path.dirname(__file__), "leadflow.db")

def get_conn():
    return sqlite3.connect(DB_PATH, timeout=30.0)

def log_sync_action(action, payload):
    """Log a DB change to the local sync journal to be pushed to Cloudflare."""
    try:
        conn = get_conn()
        payload_str = json.dumps(payload)
        conn.execute(
            "INSERT INTO sync_journal (action, payload) VALUES (?, ?)",
            (action, payload_str)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        log.error(f"Failed to log sync action: {e}")

def get_last_sync_seq():
    conn = get_conn()
    row = conn.execute("SELECT val FROM sync_state WHERE key='last_sync_seq'").fetchone()
    conn.close()
    return row[0] if row else "0"

def set_last_sync_seq(seq):
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO sync_state (key, val) VALUES ('last_sync_seq', ?)", (seq,))
    conn.commit()
    conn.close()

def push_local_changes():
    """Push unsynced journal entries to Cloudflare."""
    conn = get_conn()
    rows = conn.execute("SELECT id, action, payload FROM sync_journal WHERE synced=0 ORDER BY id ASC").fetchall()
    conn.close()
    
    if not rows:
        return
        
    transactions = []
    for r_id, action, payload in rows:
        try:
            transactions.append({
                "action": action,
                "payload": json.loads(payload),
                "local_id": r_id
            })
        except: pass
        
    if not transactions:
        return
        
    public_url = os.getenv("LEADFLOW_PUBLIC_URL", "")
    token = os.getenv("LEADFLOW_SECRET_TOKEN", os.getenv("SECRET_TOKEN", ""))
    
    if not public_url or not token:
        return
        
    try:
        r = requests.post(
            f"{public_url}/api/sync",
            json={"transactions": transactions},
            headers={"X-Secret-Token": token},
            timeout=10
        )
        if r.status_code == 200:
            # Mark as synced
            synced_ids = [t["local_id"] for t in transactions]
            conn = get_conn()
            placeholders = ",".join("?" for _ in synced_ids)
            conn.execute(f"UPDATE sync_journal SET synced=1 WHERE id IN ({placeholders})", synced_ids)
            conn.commit()
            conn.close()
            log.info(f"Successfully pushed {len(transactions)} local changes to Cloudflare.")
    except Exception as e:
        log.error(f"Failed to push changes to Cloudflare: {e}")

def apply_sync_transaction(conn, action, payload):
    """Execute the change locally on the SQLite database using the provided connection."""
    if action == "update_business_status":
        conn.execute(
            "UPDATE businesses SET status=? WHERE id=?",
            (payload["status"], payload["business_id"])
        )
    elif action == "update_followup_status":
        conn.execute(
            "UPDATE follow_ups SET status=?, sent_at=?, tracking_id=? WHERE id=?",
            (payload["status"], payload.get("sent_at"), payload.get("tracking_id"), payload["followup_id"])
        )
    elif action == "insert_business":
        b = payload.get("business")
        if b:
            # Check for existing before inserting
            exist = conn.execute("SELECT id FROM businesses WHERE name=?", (b.get("name"),)).fetchone()
            if not exist:
                cols = ", ".join(b.keys())
                placeholders = ", ".join("?" for _ in b)
                vals = list(b.values())
                conn.execute(f"INSERT INTO businesses ({cols}) VALUES ({placeholders})", vals)
    elif action == "increment_demo_viewed":
        conn.execute(
            "UPDATE businesses SET demo_viewed = COALESCE(demo_viewed, 0) + 1 WHERE id=?",
            (payload["business_id"],)
        )
    elif action == "insert_deal":
        d = payload.get("deal")
        if d:
            cols = ", ".join(d.keys())
            placeholders = ", ".join("?" for _ in d)
            vals = list(d.values())
            conn.execute(f"INSERT OR REPLACE INTO deals ({cols}) VALUES ({placeholders})", vals)

def pull_remote_changes():
    """Pull new changes from Cloudflare and apply them locally in a single transaction."""
    public_url = os.getenv("LEADFLOW_PUBLIC_URL", "")
    token = os.getenv("LEADFLOW_SECRET_TOKEN", os.getenv("SECRET_TOKEN", ""))
    
    if not public_url or not token:
        return
        
    last_seq = get_last_sync_seq()
    try:
        r = requests.get(
            f"{public_url}/api/sync",
            params={"since": last_seq, "token": token},
            timeout=10
        )
        if r.status_code == 200:
            data = r.json()
            transactions = data.get("transactions", [])
            
            if transactions:
                conn = get_conn()
                try:
                    conn.execute("BEGIN TRANSACTION;")
                    for tx in transactions:
                        action = tx.get("action")
                        payload = tx.get("payload", {})
                        apply_sync_transaction(conn, action, payload)
                        last_seq = tx.get("seq")
                    
                    conn.execute("INSERT OR REPLACE INTO sync_state (key, val) VALUES ('last_sync_seq', ?)", (last_seq,))
                    conn.commit()
                    log.info(f"Successfully pulled and applied {len(transactions)} changes from Cloudflare.")
                except Exception as db_err:
                    conn.rollback()
                    log.error(f"Database sync commit failed, changes rolled back: {db_err}")
                finally:
                    conn.close()
    except Exception as e:
        log.error(f"Failed to pull changes from Cloudflare: {e}")

def run_sync_cycle():
    """Run full push/pull sync cycle."""
    push_local_changes()
    pull_remote_changes()
