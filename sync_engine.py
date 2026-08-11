import os
import sqlite3
import requests
import json
import logging

log = logging.getLogger("leadflow.sync")
log.setLevel(logging.INFO)

DB_PATH = os.path.join(os.path.dirname(__file__), "leadflow.db")

def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.execute("PRAGMA busy_timeout = 30000;")
    return conn

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
    """Push unsynced journal entries to Cloudflare in batches of 100."""
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

    # Deduplicate idempotent actions — keep only the latest entry per (action, business_id).
    # Collapses repeated demo URL updates for the same lead into one KV write.
    DEDUP_ACTIONS = {"update_demo_url", "update_business_status", "update_ig_settings"}
    seen = {}
    deduped = []
    for tx in reversed(transactions):
        if tx["action"] in DEDUP_ACTIONS:
            key = (tx["action"], tx["payload"].get("business_id"))
            if key not in seen:
                seen[key] = True
                deduped.append(tx)
        else:
            deduped.append(tx)
    transactions = list(reversed(deduped))

    public_url = os.getenv("LEADFLOW_PUBLIC_URL", "")
    token = os.getenv("LEADFLOW_SECRET_TOKEN", os.getenv("SECRET_TOKEN", ""))

    if not public_url or not token:
        return

    # Mark deduplicated (dropped) rows synced now — they'll never be sent but are superseded.
    sent_ids = {t["local_id"] for t in transactions}
    all_ids = [r_id for r_id, _, _ in rows]
    dropped_ids = [r_id for r_id in all_ids if r_id not in sent_ids]
    if dropped_ids:
        conn = get_conn()
        placeholders = ",".join("?" for _ in dropped_ids)
        conn.execute(f"UPDATE sync_journal SET synced=1 WHERE id IN ({placeholders})", dropped_ids)
        conn.commit()
        conn.close()
        log.info(f"Deduped {len(dropped_ids)} redundant journal entries (skipped push).")

    BATCH_SIZE = 100
    total_pushed = 0
    for i in range(0, len(transactions), BATCH_SIZE):
        batch = transactions[i:i + BATCH_SIZE]
        try:
            r = requests.post(
                f"{public_url}/api/sync",
                json={"transactions": batch},
                headers={"X-Secret-Token": token},
                timeout=35
            )
            if r.status_code == 200:
                synced_ids = [t["local_id"] for t in batch]
                conn = get_conn()
                placeholders = ",".join("?" for _ in synced_ids)
                conn.execute(f"UPDATE sync_journal SET synced=1 WHERE id IN ({placeholders})", synced_ids)
                conn.commit()
                conn.close()
                total_pushed += len(batch)
            else:
                log.error(f"Push batch {i//BATCH_SIZE + 1} failed: HTTP {r.status_code} — {r.text[:200]}")
                break
        except Exception as e:
            log.error(f"Failed to push batch {i//BATCH_SIZE + 1}: {e}")
            break

    if total_pushed:
        log.info(f"Successfully pushed {total_pushed} local changes to Cloudflare.")

def resolve_global_fk(conn, table, global_id):
    """Helper to map a global_id back to a local integer id"""
    if not global_id: return None
    row = conn.execute(f"SELECT id FROM {table} WHERE global_id=?", (global_id,)).fetchone()
    return row[0] if row else None

def apply_sync_transaction(conn, action, payload):
    """Execute the change locally on the SQLite database using the provided connection."""
    
    # Map foreign keys if global_id is provided in the payload payload
    b_gid = payload.get("business_global_id")
    if b_gid:
        local_b_id = resolve_global_fk(conn, "businesses", b_gid)
        if local_b_id: payload["business_id"] = local_b_id
        
    c_gid = payload.get("contact_global_id")
    if c_gid:
        local_c_id = resolve_global_fk(conn, "contacts", c_gid)
        if local_c_id: payload["contact_id"] = local_c_id

    f_gid = payload.get("followup_global_id")
    if f_gid:
        local_f_id = resolve_global_fk(conn, "follow_ups", f_gid)
        if local_f_id: payload["followup_id"] = local_f_id

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
            exist = conn.execute("SELECT id FROM businesses WHERE name=?", (b.get("name"),)).fetchone()
            if not exist:
                # Strip id so the DB auto-assigns one to avoid PK conflicts between nodes
                b_insert = {k: v for k, v in b.items() if k != "id"}
                if all(isinstance(k, str) and k.isidentifier() for k in b_insert.keys()):
                    cols = ", ".join(b_insert.keys())
                    placeholders = ", ".join("?" for _ in b_insert)
                    vals = list(b_insert.values())
                    conn.execute(f"INSERT INTO businesses ({cols}) VALUES ({placeholders})", vals)
                else:
                    log.error("SQL Injection attempt or invalid column name detected in insert_business keys.")

    elif action == "insert_contact":
        business_id = payload.get("business_id")
        c = payload.get("contacts", {})
        if business_id and c:
            conn.execute("""
                INSERT OR REPLACE INTO contacts
                (business_id, email, instagram, facebook, linkedin_url, linkedin_name, whatsapp,
                 hunter_email, apollo_email, apollo_person_name, owner_name)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                business_id,
                c.get("email"), c.get("instagram"), c.get("facebook"),
                c.get("linkedin_url"), c.get("linkedin_name"), c.get("whatsapp"),
                c.get("hunter_email"), c.get("apollo_email"),
                c.get("apollo_person_name"), c.get("owner_name")
            ))

    elif action == "insert_outreach":
        business_id = payload.get("business_id")
        channel = payload.get("channel")
        draft = payload.get("draft", "")
        subject_options = payload.get("subject_options", "")
        tracking_id = payload.get("tracking_id")
        if business_id and channel and tracking_id:
            exist = conn.execute("SELECT id FROM outreach WHERE tracking_id=?", (tracking_id,)).fetchone()
            if not exist:
                conn.execute("""
                    INSERT INTO outreach
                    (business_id, channel, draft, final_message, subject_options, status, tracking_id)
                    VALUES (?, ?, ?, ?, ?, 'draft', ?)
                """, (business_id, channel, draft, draft, subject_options, tracking_id))

    elif action == "insert_followups":
        business_id = payload.get("business_id")
        sequences = payload.get("sequences", [])
        if business_id and sequences:
            for seq in sequences:
                conn.execute("""
                    INSERT OR IGNORE INTO follow_ups
                    (business_id, sequence_num, channel, draft, scheduled_for)
                    VALUES (?, ?, ?, ?, ?)
                """, (business_id, seq.get("num"), seq.get("channel"),
                      seq.get("draft"), seq.get("scheduled_for")))

    elif action == "increment_demo_viewed":
        conn.execute(
            "UPDATE businesses SET demo_viewed = COALESCE(demo_viewed, 0) + 1 WHERE id=?",
            (payload["business_id"],)
        )
    elif action == "update_ig_settings":
        status = payload.get("status")
        daily_limit = payload.get("daily_limit")
        if status is not None and daily_limit is not None:
            exist = conn.execute("SELECT id FROM ig_settings WHERE id=1").fetchone()
            if not exist:
                from datetime import datetime
                today = datetime.now().strftime("%Y-%m-%d")
                conn.execute(
                    "INSERT INTO ig_settings (id, status, daily_limit, sent_today, last_reset_date) VALUES (1, ?, ?, 0, ?)",
                    (status, daily_limit, today)
                )
            else:
                conn.execute("UPDATE ig_settings SET status=?, daily_limit=? WHERE id=1", (status, daily_limit))
    elif action == "insert_deal":
        d = payload.get("deal")
        if d:
            if all(isinstance(k, str) and k.isidentifier() for k in d.keys()):
                cols = ", ".join(d.keys())
                placeholders = ", ".join("?" for _ in d)
                vals = list(d.values())
                conn.execute(f"INSERT OR REPLACE INTO deals ({cols}) VALUES ({placeholders})", vals)
            else:
                log.error("SQL Injection attempt or invalid column name detected in insert_deal keys.")
    elif action == "update_demo_url":
        bid = payload.get("business_id")
        url = payload.get("demo_tunnel_url")
        if bid and url:
            conn.execute(
                "UPDATE businesses SET demo_tunnel_url=? WHERE id=? AND (demo_tunnel_url IS NULL OR demo_tunnel_url='' OR demo_tunnel_url LIKE '%/demo/%' OR ? NOT LIKE '%/demo/%')",
                (url, bid, url)
            )

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
            timeout=35
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

                    conn.execute(
                        "INSERT OR REPLACE INTO sync_state (key, val) VALUES ('last_sync_seq', ?)",
                        (last_seq,)
                    )
                    conn.commit()
                    log.info(f"Successfully pulled and applied {len(transactions)} changes from Cloudflare.")
                except Exception as db_err:
                    conn.rollback()
                    log.error(f"Database sync commit failed, changes rolled back: {db_err}")
                finally:
                    conn.close()
    except Exception as e:
        log.error(f"Failed to pull changes from Cloudflare: {e}")

def get_adb_binary() -> str:
    """Helper to detect and return raw/original adb binary path to bypass custom shell wrapper.
    Wrapper redirects generic adb commands. Bypassing it prevents routing collisions.
    """
    for path in ("/opt/homebrew/bin/adb.orig", "/usr/local/bin/adb.orig"):
        if os.path.exists(path):
            return path
    return "adb"

def lan_sync_to_peer(peer_ip: str, peer_adb_port: int = 5555, mac_ip: str = None, http_port: int = 9997):
    """
    DEPRECATED/DISABLED (Failover Fix 2026-07-22): 
    The old destructive full-DB COUNT(*) override was removed.
    LAN synchronisation relies purely on the Cloudflare KV sync journals now, which guarantees append-only structural integrity via UUIDs.
    """
    import logging
    logging.info(f"lan_sync_to_peer disabled for safe bidirectional failover. Relying on KV journal.")

def run_sync_cycle(lan_peers: list = None):
    """Run full push/pull Cloudflare sync, then LAN failsafe sync to any local peers."""
    push_local_changes()
    pull_remote_changes()
    if lan_peers:
        for peer_ip in lan_peers:
            lan_sync_to_peer(peer_ip)
