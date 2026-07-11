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
            timeout=35
        )
        if r.status_code == 200:
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
    Hard failsafe: sync the full DB to a peer device over LAN.
    Uses SQL dump served over HTTP + Python urllib on the peer (corruption-free).
    Only syncs if local DB has more data than the peer.
    """
    import subprocess, threading, http.server, tempfile, os

    adb_bin = get_adb_binary()

    try:
        # Check peer DB size via ADB
        result = subprocess.run(
            [adb_bin, "-s", f"{peer_ip}:{peer_adb_port}", "shell",
             "run-as com.termux python3 -c \"import sqlite3; c=sqlite3.connect('/data/data/com.termux/files/home/leadflow/leadflow.db'); c.execute('PRAGMA busy_timeout=30000'); print(c.execute('SELECT COUNT(*) FROM businesses').fetchone()[0]); c.close()\""],
            capture_output=True, text=True, timeout=15
        )
        peer_count = int(result.stdout.strip()) if result.stdout.strip().isdigit() else 0
        local_conn = sqlite3.connect(DB_PATH, timeout=30.0)
        local_conn.execute("PRAGMA busy_timeout = 5000;")
        local_count = local_conn.execute("SELECT COUNT(*) FROM businesses").fetchone()[0]
        local_conn.close()

        if local_count <= peer_count:
            log.info(f"LAN sync: peer is up to date ({peer_count} businesses >= {local_count}), skipping.")
            return

        log.info(f"LAN sync: local has {local_count} businesses vs peer {peer_count}, syncing...")

        # Dump local DB as SQL into a temp directory
        dump_dir = tempfile.mkdtemp()
        dump_path = os.path.join(dump_dir, "leadflow_dump.sql")
        conn = sqlite3.connect(DB_PATH, timeout=30.0)
        conn.execute("PRAGMA busy_timeout = 5000;")
        with open(dump_path, "w") as f:
            for line in conn.iterdump():
                f.write(line + "\n")
        conn.close()

        # Auto-detect Mac IP if not provided
        if not mac_ip:
            import socket
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                mac_ip = s.getsockname()[0]
                s.close()
            except Exception:
                mac_ip = "192.168.1.17"

        # Serve the SQL dump via a temporary HTTP server
        handler = http.server.SimpleHTTPRequestHandler
        handler.log_message = lambda *a: None  # silence logs
        import socketserver
        httpd = socketserver.TCPServer(("", http_port), lambda *a, **kw: handler(*a, directory=dump_dir, **kw))
        t = threading.Thread(target=httpd.handle_request)
        t.start()

        # Have the peer download and restore it
        restore_cmd = (
            f"import urllib.request, sqlite3, os; "
            f"db=\\\"/data/data/com.termux/files/home/leadflow/leadflow.db\\\"; "
            f"sql=\\\"/data/data/com.termux/files/home/leadflow/restore.sql\\\"; "
            f"urllib.request.urlretrieve(\\\"http://{mac_ip}:{http_port}/leadflow_dump.sql\\\", sql); "
            f"os.remove(db) if os.path.exists(db) else None; "
            f"c=sqlite3.connect(db); c.executescript(open(sql).read()); c.close(); "
            f"os.remove(sql); print('LAN sync restore done')"
        )
        subprocess.run(
            [adb_bin, "-s", f"{peer_ip}:{peer_adb_port}", "shell",
             f"run-as com.termux /data/data/com.termux/files/usr/bin/python3 -c \"{restore_cmd}\""],
            capture_output=True, timeout=120
        )
        httpd.server_close()
        os.remove(dump_path)
        os.rmdir(dump_dir)
        log.info(f"LAN sync to {peer_ip} complete.")

    except Exception as e:
        log.warning(f"LAN sync to {peer_ip} failed (non-critical): {e}")


def run_sync_cycle(lan_peers: list = None):
    """Run full push/pull Cloudflare sync, then LAN failsafe sync to any local peers."""
    push_local_changes()
    pull_remote_changes()
    if lan_peers:
        for peer_ip in lan_peers:
            lan_sync_to_peer(peer_ip)
