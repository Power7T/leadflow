import sqlite3
import json
from pathlib import Path
from datetime import datetime, timedelta

DB_PATH = Path(__file__).parent / "leadflow.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.execute("PRAGMA busy_timeout = 30000;")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS businesses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT,
            address TEXT,
            city TEXT,
            country TEXT,
            phone TEXT,
            website TEXT,
            website_score INTEGER,
            google_rating REAL,
            google_reviews INTEGER,
            gap TEXT,
            pitch_type TEXT,
            status TEXT DEFAULT 'new',
            lead_score INTEGER DEFAULT 0,
            domain_available TEXT,
            source TEXT DEFAULT 'google_maps',
            maps_url TEXT,
            demo_tunnel_url TEXT,
            template_id TEXT,
            demo_viewed INTEGER DEFAULT 0,
            found_at TEXT DEFAULT CURRENT_TIMESTAMP,
            assigned_sender_email TEXT
        );

        CREATE TABLE IF NOT EXISTS contacts (
            business_id INTEGER PRIMARY KEY,
            email TEXT,
            instagram TEXT,
            facebook TEXT,
            linkedin_url TEXT,
            linkedin_name TEXT,
            whatsapp TEXT,
            hunter_email TEXT,
            apollo_email TEXT,
            apollo_person_name TEXT,
            replied_at TEXT,
            FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE
        );
        
        CREATE TABLE IF NOT EXISTS outreach (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER REFERENCES businesses(id),
            channel TEXT,
            draft TEXT,
            final_message TEXT,
            subject_options TEXT,
            status TEXT DEFAULT 'draft',
            sent_at TEXT,
            scheduled_at TEXT,
            replied INTEGER DEFAULT 0,
            opened INTEGER DEFAULT 0,
            clicked INTEGER DEFAULT 0,
            open_count INTEGER DEFAULT 0,
            tracking_id TEXT,
            is_autopilot INTEGER DEFAULT 0,
            subject_used TEXT,
            message_id TEXT
        );

        CREATE TABLE IF NOT EXISTS follow_ups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER REFERENCES businesses(id),
            sequence_num INTEGER,
            channel TEXT,
            draft TEXT,
            status TEXT DEFAULT 'pending',
            scheduled_for TEXT,
            sent_at TEXT,
            tracking_id TEXT,
            message_id TEXT,
            followup_angle TEXT
        );

        CREATE TABLE IF NOT EXISTS tracking_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tracking_id TEXT,
            business_id INTEGER,
            event_type TEXT,
            occurred_at TEXT DEFAULT CURRENT_TIMESTAMP,
            metadata TEXT
        );

        CREATE TABLE IF NOT EXISTS deals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER REFERENCES businesses(id),
            value_usd REAL,
            service TEXT,
            status TEXT DEFAULT 'open',
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            closed_at TEXT
        );

        CREATE TABLE IF NOT EXISTS scheduler_config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            niches TEXT,
            locations TEXT,
            enabled INTEGER DEFAULT 0,
            run_hour INTEGER DEFAULT 6,
            max_per_run INTEGER DEFAULT 20,
            source TEXT DEFAULT 'google_maps',
            max_score INTEGER DEFAULT 70
        );

        CREATE TABLE IF NOT EXISTS sender_warmup (
            sender_email TEXT PRIMARY KEY,
            start_date TEXT DEFAULT CURRENT_TIMESTAMP,
            current_daily_limit INTEGER DEFAULT 5,
            total_sent_lifetime INTEGER DEFAULT 0,
            sent_today INTEGER DEFAULT 0,
            last_send_date TEXT,
            reputation_score INTEGER DEFAULT 50,
            is_warmed_up INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS ab_tests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER,
            subject_a TEXT,
            subject_b TEXT,
            sent_a INTEGER DEFAULT 0,
            sent_b INTEGER DEFAULT 0,
            opens_a INTEGER DEFAULT 0,
            opens_b INTEGER DEFAULT 0,
            winner TEXT,
            experiment TEXT DEFAULT 'old_vs_new',
            label_a TEXT DEFAULT 'Old Formula',
            label_b TEXT DEFAULT 'New Formula',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            resolved_at TEXT
        );
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS inbound_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER,
            message_id TEXT,
            subject TEXT,
            body TEXT,
            received_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS sync_journal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT,
            payload TEXT,
            synced INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS sync_state (
            key TEXT PRIMARY KEY,
            val TEXT
        );
    """)

    # Migrate existing DB — add new columns if missing
    for col, definition in [
        ("lead_score",       "INTEGER DEFAULT 0"),
        ("domain_available", "TEXT"),
        ("source",           "TEXT DEFAULT 'google_maps'"),
        ("maps_url",         "TEXT"),
        ("demo_tunnel_url",  "TEXT"),
        ("template_id",      "TEXT"),
        ("demo_viewed",      "INTEGER DEFAULT 0"),
        ("assigned_sender_email", "TEXT"),
        ("timezone", "TEXT"),
        ("has_google_ads", "INTEGER DEFAULT 0"),
        ("social_active", "INTEGER DEFAULT 0"),
        ("intent_score", "INTEGER DEFAULT 0"),
        ("maps_rank", "INTEGER DEFAULT 0"),
        ("competitor_deficit", "TEXT"),
        ("visual_preview_url", "TEXT"),
        ("ig_dm_sent",         "INTEGER DEFAULT 0"),
        ("ig_dm_sent_at",      "TEXT"),
    ]:
        try:
            conn.execute(f"ALTER TABLE businesses ADD COLUMN {col} {definition}")
        except Exception:
            pass

    for col, definition in [
        ("replied_at", "TEXT"),
        ("owner_name", "TEXT"),
        ("reply_text", "TEXT"),
        ("reply_classification", "TEXT"),
    ]:
        try:
            conn.execute(f"ALTER TABLE contacts ADD COLUMN {col} {definition}")
        except Exception:
            pass

    for col, definition in [
        ("subject_options", "TEXT"),
        ("opened",          "INTEGER DEFAULT 0"),
        ("clicked",         "INTEGER DEFAULT 0"),
        ("open_count",      "INTEGER DEFAULT 0"),
        ("tracking_id",     "TEXT"),
        ("is_autopilot",    "INTEGER DEFAULT 0"),
        ("subject_used",    "TEXT"),
        ("message_id",      "TEXT"),
        ("scheduled_at",    "TEXT"),  # send-time optimization slot (fix #1)
    ]:
        try:
            conn.execute(f"ALTER TABLE outreach ADD COLUMN {col} {definition}")
        except Exception:
            pass

    for col, definition in [
        ("source",    "TEXT DEFAULT 'google_maps'"),
        ("max_score", "INTEGER DEFAULT 70"),
        ("last_niche_idx", "INTEGER DEFAULT 0"),
        ("last_loc_idx",   "INTEGER DEFAULT 0"),
        ("auto_send_enabled", "INTEGER DEFAULT 0"),
        ("max_auto_send", "INTEGER DEFAULT 10"),
        ("send_window_start", "INTEGER DEFAULT 9"),
        ("send_window_end", "INTEGER DEFAULT 11"),
        ("preferred_days", "TEXT DEFAULT '[1,2,3]'"),
        ("ab_testing_enabled", "INTEGER DEFAULT 1"),
    ]:
        try:
            conn.execute(f"ALTER TABLE scheduler_config ADD COLUMN {col} {definition}")
        except Exception:
            pass

    for col, definition in [
        ("followup_angle", "TEXT"),
        ("tracking_id", "TEXT"),
        ("message_id", "TEXT"),
    ]:
        try:
            conn.execute(f"ALTER TABLE follow_ups ADD COLUMN {col} {definition}")
        except Exception:
            pass
    # ── Performance indexes (idempotent) ───────────────────────────────────
    for _idx in [
        "CREATE INDEX IF NOT EXISTS idx_outreach_tracking_id    ON outreach(tracking_id)",
        "CREATE INDEX IF NOT EXISTS idx_outreach_business_opened ON outreach(business_id, opened, status)",
        "CREATE INDEX IF NOT EXISTS idx_outreach_status          ON outreach(status)",
        "CREATE INDEX IF NOT EXISTS idx_businesses_status_score  ON businesses(status, lead_score)",
        "CREATE INDEX IF NOT EXISTS idx_businesses_found_at      ON businesses(found_at)",
        "CREATE INDEX IF NOT EXISTS idx_follow_ups_bid_status    ON follow_ups(business_id, status)",
        "CREATE INDEX IF NOT EXISTS idx_follow_ups_scheduled     ON follow_ups(status, scheduled_for)",
        "CREATE INDEX IF NOT EXISTS idx_tracking_tid             ON tracking_events(tracking_id)",
        "CREATE INDEX IF NOT EXISTS idx_tracking_bid             ON tracking_events(business_id, event_type)",
        "CREATE INDEX IF NOT EXISTS idx_contacts_bid             ON contacts(business_id)",
    ]:
        try:
            conn.execute(_idx)
        except Exception:
            pass
    conn.commit()
    conn.close()


def insert_business(data: dict) -> int:
    conn = get_conn()
    
    # Check for duplicate business before inserting
    website = data.get("website", "")
    if isinstance(website, str):
        website = website.strip()
    else:
        website = ""
        
    name = data.get("name", "")
    if isinstance(name, str):
        name = name.strip()
    else:
        name = ""

    if website:
        # Simple exact check first
        existing = conn.execute("SELECT id FROM businesses WHERE LOWER(website) = ?", (website.lower(),)).fetchone()
        if existing:
            conn.close()
            return existing["id"]
            
        # Domain similarity check
        from urllib.parse import urlparse
        parsed = urlparse(website)
        domain = parsed.netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        if domain:
            existing_by_domain = conn.execute("SELECT id FROM businesses WHERE website LIKE ?", (f"%{domain}%",)).fetchone()
            if existing_by_domain:
                conn.close()
                return existing_by_domain["id"]
            
    if name:
        phone = data.get("phone", "")
        if isinstance(phone, str):
            phone = phone.strip()
        else:
            phone = ""
            
        if phone:
            existing = conn.execute("SELECT id FROM businesses WHERE LOWER(name) = ? AND phone = ?", (name.lower(), phone)).fetchone()
            if existing:
                conn.close()
                return existing["id"]
                
        city = data.get("city", "")
        if isinstance(city, str):
            city = city.strip()
        else:
            city = ""
            
        if city:
            # Direct name/city duplicate check
            existing = conn.execute("SELECT id FROM businesses WHERE LOWER(name) = ? AND LOWER(city) = ?", (name.lower(), city.lower())).fetchone()
            if existing:
                conn.close()
                return existing["id"]
                
            # Fuzzy name match check in the same city
            from difflib import SequenceMatcher
            candidates = conn.execute("SELECT id, name FROM businesses WHERE LOWER(city) = ?", (city.lower(),)).fetchall()
            for cand in candidates:
                ratio = SequenceMatcher(None, name.lower(), cand["name"].lower()).ratio()
                if ratio > 0.85:
                    conn.close()
                    return cand["id"]

    bind_data = {
        "name": name,
        "category": data.get("category", ""),
        "address": data.get("address", ""),
        "city": data.get("city", ""),
        "country": data.get("country", ""),
        "phone": data.get("phone", ""),
        "website": website,
        "website_score": data.get("website_score", 0),
        "google_rating": data.get("google_rating"),
        "google_reviews": data.get("google_reviews"),
        "gap": data.get("gap", ""),
        "pitch_type": data.get("pitch_type", ""),
        "lead_score": data.get("lead_score", 0),
        "domain_available": data.get("domain_available"),
        "source": data.get("source", "google_maps"),
        "maps_url": data.get("maps_url"),
        "has_google_ads": data.get("has_google_ads", 0),
        "social_active": data.get("social_active", 0),
        "intent_score": data.get("intent_score", 0),
        "maps_rank": data.get("maps_rank", 0),
        "competitor_deficit": data.get("competitor_deficit"),
        "visual_preview_url": data.get("visual_preview_url"),
    }

    cur = conn.execute("""
        INSERT INTO businesses (name, category, address, city, country, phone,
            website, website_score, google_rating, google_reviews, gap, pitch_type,
            lead_score, domain_available, source, maps_url, has_google_ads, social_active, intent_score,
            maps_rank, competitor_deficit, visual_preview_url)
        VALUES (:name, :category, :address, :city, :country, :phone,
            :website, :website_score, :google_rating, :google_reviews, :gap, :pitch_type,
            :lead_score, :domain_available, :source, :maps_url, :has_google_ads, :social_active, :intent_score,
            :maps_rank, :competitor_deficit, :visual_preview_url)
    """, bind_data)
    conn.commit()
    bid = cur.lastrowid
    conn.close()
    # Sync new business to all nodes
    try:
        from sync_engine import log_sync_action
        sync_payload = dict(bind_data)
        sync_payload["id"] = bid
        log_sync_action("insert_business", {"business": sync_payload})
    except Exception:
        pass
    return bid


def insert_contacts(business_id: int, contacts: dict):
    conn = get_conn()
    conn.execute('''
        INSERT OR REPLACE INTO contacts 
        (business_id, email, instagram, facebook, linkedin_url, linkedin_name, whatsapp, hunter_email, apollo_email, apollo_person_name, owner_name)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        business_id,
        contacts.get("email"),
        contacts.get("instagram"),
        contacts.get("facebook"),
        contacts.get("linkedin_url"),
        contacts.get("linkedin_name"),
        contacts.get("whatsapp"),
        contacts.get("hunter_email"),
        contacts.get("apollo_email"),
        contacts.get("apollo_person_name"),
        contacts.get("owner_name")
    ))
    conn.commit()
    conn.close()
    # Sync contacts to all nodes
    try:
        from sync_engine import log_sync_action
        log_sync_action("insert_contact", {"business_id": business_id, "contacts": contacts})
    except Exception:
        pass


def get_leads(status: str = "new") -> list:
    conn = get_conn()
    rows = conn.execute("""
        SELECT b.*, c.email, c.instagram, c.linkedin_name, c.linkedin_url, c.whatsapp, c.owner_name
        FROM businesses b
        LEFT JOIN contacts c ON c.business_id = b.id
        WHERE b.status = ? AND (b.source IS NULL OR b.source != 'test_leads')
        ORDER BY b.lead_score DESC, b.found_at DESC
    """, (status,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_active_leads() -> list:
    """All leads except skipped — used for review page (show everything always)."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT b.*, c.email, c.instagram, c.linkedin_name, c.linkedin_url, c.whatsapp, c.owner_name, c.replied_at, c.reply_text,
               (SELECT json_group_array(json_object('is_inbound', is_inbound, 'content', content, 'timestamp', timestamp))
                FROM (
                    SELECT 0 as is_inbound, final_message as content, sent_at as timestamp
                    FROM outreach
                    WHERE business_id = b.id AND final_message IS NOT NULL AND status = 'sent' AND sent_at IS NOT NULL
                    GROUP BY channel, sent_at
                    UNION ALL
                    SELECT 1 as is_inbound, body as content, received_at as timestamp FROM inbound_messages WHERE business_id = b.id
                    ORDER BY timestamp ASC
                )
               ) as interactions_json,
               (SELECT sent_at FROM outreach WHERE business_id = b.id AND sent_at IS NOT NULL ORDER BY id DESC LIMIT 1) as email_sent_at,
               (SELECT MAX(opened) FROM outreach WHERE business_id = b.id) as email_opened,
               (SELECT MAX(clicked) FROM outreach WHERE business_id = b.id) as email_clicked
        FROM businesses b
        LEFT JOIN contacts c ON c.business_id = b.id
        WHERE b.status NOT IN ('skipped') AND (b.source IS NULL OR b.source != 'test_leads')
        ORDER BY b.lead_score DESC, b.found_at DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_facebook_leads() -> list:
    """Fetch only manually added Facebook Miami group leads."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT b.*, c.email, c.instagram, c.linkedin_name, c.linkedin_url, c.whatsapp, c.owner_name, c.replied_at, c.reply_text,
               (SELECT json_group_array(json_object('is_inbound', is_inbound, 'content', content, 'timestamp', timestamp))
                FROM (
                    SELECT 0 as is_inbound, final_message as content, sent_at as timestamp
                    FROM outreach
                    WHERE business_id = b.id AND final_message IS NOT NULL AND status = 'sent' AND sent_at IS NOT NULL
                    GROUP BY channel, sent_at
                    UNION ALL
                    SELECT 1 as is_inbound, body as content, received_at as timestamp FROM inbound_messages WHERE business_id = b.id
                    ORDER BY timestamp ASC
                )
               ) as interactions_json,
               (SELECT sent_at FROM outreach WHERE business_id = b.id AND sent_at IS NOT NULL ORDER BY id DESC LIMIT 1) as email_sent_at,
               (SELECT MAX(opened) FROM outreach WHERE business_id = b.id) as email_opened,
               (SELECT MAX(clicked) FROM outreach WHERE business_id = b.id) as email_clicked
        FROM businesses b
        LEFT JOIN contacts c ON c.business_id = b.id
        WHERE b.source = 'facebook_miami' AND b.status NOT IN ('skipped')
        ORDER BY b.found_at DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_test_leads() -> list:
    """Fetch only high-intent conversion test leads."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT b.*, c.email, c.instagram, c.linkedin_name, c.linkedin_url, c.whatsapp, c.owner_name, c.replied_at, c.reply_text,
               (SELECT json_group_array(json_object('is_inbound', is_inbound, 'content', content, 'timestamp', timestamp))
                FROM (
                    SELECT 0 as is_inbound, final_message as content, sent_at as timestamp
                    FROM outreach
                    WHERE business_id = b.id AND final_message IS NOT NULL AND status = 'sent' AND sent_at IS NOT NULL
                    GROUP BY channel, sent_at
                    UNION ALL
                    SELECT 1 as is_inbound, body as content, received_at as timestamp FROM inbound_messages WHERE business_id = b.id
                    ORDER BY timestamp ASC
                )
               ) as interactions_json,
               (SELECT sent_at FROM outreach WHERE business_id = b.id AND sent_at IS NOT NULL ORDER BY id DESC LIMIT 1) as email_sent_at,
               (SELECT MAX(opened) FROM outreach WHERE business_id = b.id) as email_opened,
               (SELECT MAX(clicked) FROM outreach WHERE business_id = b.id) as email_clicked
        FROM businesses b
        LEFT JOIN contacts c ON c.business_id = b.id
        WHERE b.source = 'test_leads' AND b.status NOT IN ('skipped')
        ORDER BY b.found_at DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_lead_by_id(bid: int) -> dict | None:
    """Get a single lead by ID directly (avoids loading all active leads)."""
    conn = get_conn()
    row = conn.execute("""
        SELECT b.*, c.email, c.instagram, c.linkedin_name, c.linkedin_url, c.whatsapp, c.owner_name, c.replied_at, c.reply_text,
               (SELECT json_group_array(json_object('is_inbound', is_inbound, 'content', content, 'timestamp', timestamp))
                FROM (
                    SELECT 0 as is_inbound, final_message as content, sent_at as timestamp
                    FROM outreach
                    WHERE business_id = b.id AND final_message IS NOT NULL AND status = 'sent' AND sent_at IS NOT NULL
                    GROUP BY channel, sent_at
                    UNION ALL
                    SELECT 1 as is_inbound, body as content, received_at as timestamp FROM inbound_messages WHERE business_id = b.id
                    ORDER BY timestamp ASC
                )
               ) as interactions_json,
               (SELECT sent_at FROM outreach WHERE business_id = b.id AND sent_at IS NOT NULL ORDER BY id DESC LIMIT 1) as email_sent_at,
               (SELECT MAX(opened) FROM outreach WHERE business_id = b.id) as email_opened,
               (SELECT MAX(clicked) FROM outreach WHERE business_id = b.id) as email_clicked
        FROM businesses b
        LEFT JOIN contacts c ON c.business_id = b.id
        WHERE b.id = ?
    """, (bid,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_leads_for_kanban() -> list:
    conn = get_conn()
    rows = conn.execute("""
        SELECT b.*, c.email, c.instagram, c.whatsapp, c.linkedin_name, c.linkedin_url, c.owner_name,
               MAX(o.opened) as email_opened, MAX(o.clicked) as email_clicked
        FROM businesses b
        LEFT JOIN contacts c ON c.business_id = b.id
        LEFT JOIN outreach o ON o.business_id = b.id
        WHERE b.status NOT IN ('skipped', 'opted_out')
        GROUP BY b.id
        ORDER BY b.lead_score DESC, b.found_at DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_business_status(bid: int, status: str):
    conn = get_conn()
    conn.execute("UPDATE businesses SET status=? WHERE id=?", (status, bid))
    if status == 'replied':
        conn.execute("UPDATE outreach SET replied=1 WHERE business_id=?", (bid,))
    conn.commit()
    conn.close()
    try:
        from sync_engine import log_sync_action
        log_sync_action("update_business_status", {"business_id": bid, "status": status})
    except: pass


def insert_outreach(business_id: int, channel: str, draft: str, subject_options: str = ""):
    """Upsert: update existing draft row if one exists for this business+channel,
    otherwise insert a new one. This prevents duplicate rows from accumulating
    every time a draft is (re)generated."""
    conn = get_conn()
    import uuid
    # Check for an existing unsent draft row
    existing = conn.execute(
        "SELECT id, tracking_id FROM outreach WHERE business_id=? AND channel=? AND status='draft' LIMIT 1",
        (business_id, channel)
    ).fetchone()
    if existing:
        tracking_id = existing["tracking_id"]
        conn.execute(
            "UPDATE outreach SET draft=?, final_message=?, subject_options=? WHERE id=?",
            (draft, draft, subject_options, existing["id"])
        )
    else:
        tracking_id = str(uuid.uuid4())
        conn.execute("""
            INSERT INTO outreach (business_id, channel, draft, final_message, subject_options, status, tracking_id)
            VALUES (?, ?, ?, ?, ?, 'draft', ?)
        """, (business_id, channel, draft, draft, subject_options, tracking_id))
    conn.commit()
    conn.close()
    # Sync outreach draft to all nodes
    try:
        from sync_engine import log_sync_action
        log_sync_action("insert_outreach", {
            "business_id": business_id, "channel": channel,
            "draft": draft, "subject_options": subject_options, "tracking_id": tracking_id
        })
    except Exception:
        pass
    return tracking_id


def mark_sent(business_id: int, channel: str, is_autopilot: bool = False, subject_used: str = None, tracking_id: str = None):
    """Mark a single outreach row as sent. Always targets a specific row to avoid
    updating all duplicate rows for the same business+channel."""
    conn = get_conn()
    cursor = conn.cursor()
    updated = False
    
    if tracking_id:
        # 1. Try to update by tracking_id in case it already exists in the table
        res = cursor.execute("""
            UPDATE outreach SET status='sent', sent_at=datetime('now'), is_autopilot=?, subject_used=?
            WHERE tracking_id=?
        """, (int(is_autopilot), subject_used, tracking_id))
        if res.rowcount > 0:
            updated = True
            
    if not updated:
        # 2. If it wasn't updated (e.g. tracking_id is new), update the most recent 'draft' row
        # for this business+channel and update its tracking_id to the new one so tracking works!
        if tracking_id:
            res = cursor.execute("""
                UPDATE outreach SET status='sent', sent_at=datetime('now'), is_autopilot=?, subject_used=?, tracking_id=?
                WHERE id = (
                    SELECT id FROM outreach
                    WHERE business_id=? AND channel=? AND status='draft'
                    ORDER BY id DESC LIMIT 1
                )
            """, (int(is_autopilot), subject_used, tracking_id, business_id, channel))
        else:
            res = cursor.execute("""
                UPDATE outreach SET status='sent', sent_at=datetime('now'), is_autopilot=?, subject_used=?
                WHERE id = (
                    SELECT id FROM outreach
                    WHERE business_id=? AND channel=? AND status='draft'
                    ORDER BY id DESC LIMIT 1
                )
            """, (int(is_autopilot), subject_used, business_id, channel))
        if res.rowcount > 0:
            updated = True
            
    if not updated:
        # 3. Fallback: if no draft row exists at all, insert a new sent row
        cursor.execute("""
            INSERT INTO outreach (business_id, channel, final_message, status, sent_at, is_autopilot, subject_used, tracking_id)
            VALUES (?, ?, ?, 'sent', datetime('now'), ?, ?, ?)
        """, (business_id, channel, subject_used or "", int(is_autopilot), subject_used, tracking_id))
        
    conn.commit()
    conn.close()


def record_tracking_event(tracking_id: str, business_id: int, event_type: str, metadata: str = ""):
    conn = get_conn()
    
    # If business_id is 0 or not provided, resolve it from the tracking_id
    if (not business_id or business_id == 0) and tracking_id:
        try:
            # Check outreach table
            row = conn.execute("SELECT business_id FROM outreach WHERE tracking_id=?", (tracking_id,)).fetchone()
            if row:
                business_id = row["business_id"]
            else:
                # Check follow_ups table
                row = conn.execute("SELECT business_id FROM follow_ups WHERE tracking_id=?", (tracking_id,)).fetchone()
                if row:
                    business_id = row["business_id"]
        except Exception:
            pass

    conn.execute("""
        INSERT INTO tracking_events (tracking_id, business_id, event_type, metadata)
        VALUES (?, ?, ?, ?)
    """, (tracking_id, business_id or 0, event_type, metadata))
    
    if event_type == "open":
        # Update by tracking_id (most precise — one outreach row)
        updated = 0
        if tracking_id:
            cursor = conn.execute("""
                UPDATE outreach SET opened=1, open_count=open_count+1
                WHERE tracking_id=?
            """, (tracking_id,))
            updated = cursor.rowcount
        
        # If tracking_id wasn't in outreach (e.g. it was in follow_ups) or tracking_id is empty, update by business_id
        if not updated and business_id:
            conn.execute("""
                UPDATE outreach SET opened=1, open_count=open_count+1
                WHERE business_id=? AND channel='email'
            """, (business_id,))
    elif event_type == "click":
        updated = 0
        if tracking_id:
            cursor = conn.execute("UPDATE outreach SET clicked=1 WHERE tracking_id=?", (tracking_id,))
            updated = cursor.rowcount
        if not updated and business_id:
            conn.execute("UPDATE outreach SET clicked=1 WHERE business_id=? AND channel='email'", (business_id,))

    # Update demo viewed status in businesses table for click/engage events
    if event_type == "click" or event_type.startswith("engage") or (event_type == "open" and not tracking_id):
        if business_id:
            conn.execute("UPDATE businesses SET demo_viewed=1 WHERE id=?", (business_id,))
            
    conn.commit()
    conn.close()


def insert_follow_ups(business_id: int, sequences: list[dict]):
    conn = get_conn()
    for seq in sequences:
        conn.execute("""
            INSERT INTO follow_ups (business_id, sequence_num, channel, draft, scheduled_for)
            VALUES (?, ?, ?, ?, ?)
        """, (business_id, seq["num"], seq["channel"], seq["draft"], seq["scheduled_for"]))
        # Store followup_angle if column exists (added in later schema version)
        try:
            conn.execute(
                "UPDATE follow_ups SET followup_angle=? WHERE rowid=last_insert_rowid()",
                (seq.get("followup_angle", ""),)
            )
        except Exception:
            pass
    conn.commit()
    # Sync follow-ups to all nodes
    try:
        from sync_engine import log_sync_action
        log_sync_action("insert_followups", {"business_id": business_id, "sequences": sequences})
    except Exception:
        pass
    conn.close()


def get_pending_follow_ups() -> list:
    conn = get_conn()
    rows = conn.execute("""
        SELECT f.*, b.name, b.status as biz_status,
               c.email, c.instagram
        FROM follow_ups f
        JOIN businesses b ON b.id = f.business_id
        LEFT JOIN contacts c ON c.business_id = f.business_id
        WHERE f.status = 'pending'
          AND datetime(f.scheduled_for) <= datetime('now')
          AND b.status = 'sent'
        ORDER BY f.scheduled_for ASC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_follow_ups() -> list:
    conn = get_conn()
    rows = conn.execute("""
        SELECT f.*, b.name, c.email, c.instagram
        FROM follow_ups f
        JOIN businesses b ON b.id = f.business_id
        LEFT JOIN contacts c ON c.business_id = f.business_id
        ORDER BY f.scheduled_for ASC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_follow_up_sent(fid: int, tracking_id: str = None):
    conn = get_conn()
    import datetime
    now_str = datetime.datetime.utcnow().isoformat()
    if tracking_id:
        conn.execute("UPDATE follow_ups SET status='sent', sent_at=?, tracking_id=? WHERE id=?",
                     (now_str, tracking_id, fid))
    else:
        conn.execute("UPDATE follow_ups SET status='sent', sent_at=? WHERE id=?",
                     (now_str, fid))
    conn.commit()
    conn.close()
    try:
        from sync_engine import log_sync_action
        log_sync_action("update_followup_status", {
            "followup_id": fid,
            "status": "sent",
            "tracking_id": tracking_id,
            "sent_at": now_str
        })
    except: pass


def insert_deal(business_id: int, value: float, service: str, notes: str = ""):
    conn = get_conn()
    conn.execute("""
        INSERT INTO deals (business_id, value_usd, service, status, notes, closed_at)
        VALUES (?, ?, ?, 'closed', ?, CURRENT_TIMESTAMP)
    """, (business_id, value, service, notes))
    conn.execute("UPDATE businesses SET status='closed' WHERE id=?", (business_id,))
    conn.commit()
    conn.close()
    try:
        from sync_engine import log_sync_action
        log_sync_action("insert_deal", {
            "deal": {
                "business_id": business_id,
                "value_usd": value,
                "service": service,
                "status": "closed",
                "notes": notes
            }
        })
    except: pass


def get_analytics() -> dict:
    conn = get_conn()

    total     = conn.execute("SELECT COUNT(*) as c FROM businesses WHERE status!='skipped'").fetchone()["c"]
    sent      = conn.execute("SELECT COUNT(*) as c FROM businesses WHERE status IN ('sent','replied','closed')").fetchone()["c"]
    replied   = conn.execute("SELECT COUNT(*) as c FROM businesses WHERE status IN ('replied','closed')").fetchone()["c"]
    closed    = conn.execute("SELECT COUNT(*) as c FROM businesses WHERE status='closed'").fetchone()["c"]
    revenue   = conn.execute("SELECT COALESCE(SUM(value_usd),0) as s FROM deals WHERE status='closed'").fetchone()["s"]
    opens     = conn.execute("SELECT COUNT(*) as c FROM outreach WHERE opened=1").fetchone()["c"]
    clicks    = conn.execute("SELECT COUNT(*) as c FROM outreach WHERE clicked=1").fetchone()["c"]
    emails_sent = conn.execute("SELECT COUNT(*) as c FROM outreach WHERE status='sent' AND channel='email'").fetchone()["c"]

    # Best niches
    niches = conn.execute("""
        SELECT category, COUNT(*) as total,
               SUM(CASE WHEN status IN ('replied','closed') THEN 1 ELSE 0 END) as replied
        FROM businesses WHERE status NOT IN ('skipped','new')
        GROUP BY category ORDER BY replied DESC LIMIT 5
    """).fetchall()

    # Recent deals
    deals = conn.execute("""
        SELECT d.*, b.name FROM deals d
        JOIN businesses b ON b.id = d.business_id
        ORDER BY d.created_at DESC LIMIT 10
    """).fetchall()

    conn.close()
    return {
        "total": total, "sent": sent, "replied": replied, "closed": closed,
        "revenue": revenue, "opens": opens, "clicks": clicks,
        "emails_sent": emails_sent,
        "reply_rate": round(replied / sent * 100, 1) if sent else 0,
        "close_rate": round(closed / replied * 100, 1) if replied else 0,
        "open_rate":  round(opens / emails_sent * 100, 1) if emails_sent else 0,
        "niches": [dict(n) for n in niches],
        "deals":  [dict(d) for d in deals],
    }


def get_stats() -> dict:
    conn = get_conn()
    stats = {}
    for status in ("new", "approved", "sent", "replied", "skipped", "closed", "opted_out"):
        row = conn.execute("SELECT COUNT(*) as c FROM businesses WHERE status=? AND (source IS NULL OR (source NOT IN ('facebook_miami', 'instagram_reach', 'test_leads')))", (status,)).fetchone()
        stats[status] = row["c"]
        
    # FB Miami leads count
    row_miami = conn.execute("SELECT COUNT(*) as c FROM businesses WHERE source='facebook_miami' AND status='new'").fetchone()
    stats["miami_new"] = row_miami["c"]
    
    # Instagram Reach leads count
    row_ig = conn.execute("SELECT COUNT(*) as c FROM businesses WHERE source='instagram_reach' AND status='new'").fetchone()
    stats["instagram_reach_new"] = row_ig["c"]

    # Test Leads count
    row_test = conn.execute("SELECT COUNT(*) as c FROM businesses WHERE source='test_leads' AND status='new'").fetchone()
    stats["test_leads_new"] = row_test["c"]
    
    # Check if autopilot scheduler is enabled
    cfg_row = conn.execute("SELECT enabled FROM scheduler_config LIMIT 1").fetchone()
    stats["autopilot_active"] = bool(cfg_row["enabled"]) if cfg_row else False
    
    conn.close()
    return stats


def get_emails_sent_today() -> int:
    """
    Returns the total number of emails sent today by summing the sent_today
    counters from all active sender accounts. This ensures the dashboard UI
    matches the actual SMTP limits exactly.
    """
    conn = get_conn()
    try:
        # We must only count today's sends, so we check last_send_date = today
        from datetime import datetime
        today = datetime.utcnow().strftime("%Y-%m-%d")
        
        row = conn.execute("""
            SELECT SUM(sent_today) as total 
            FROM sender_warmup 
            WHERE last_send_date = ?
        """, (today,)).fetchone()
        
        return row["total"] or 0
    finally:
        conn.close()


def get_dynamic_send_limit() -> int:
    """
    Daily send limit = 25 per active sender email.
    Automatically increases when a new email account is added.
    Also syncs the scheduler_config.max_auto_send so the UI shows the right number.
    """
    import os
    sender_emails_str = os.getenv("SENDER_EMAIL", "")
    active_senders = [e.strip() for e in sender_emails_str.split(",") if e.strip()]
    # Also count any senders in sender_warmup that aren't in env (manually added)
    conn = get_conn()
    try:
        db_senders = conn.execute("SELECT sender_email FROM sender_warmup").fetchall()
        db_set = {r["sender_email"].strip().lower() for r in db_senders}
        env_set = {e.lower() for e in active_senders}
        total_senders = max(len(db_set | env_set), len(active_senders), 1)
        dynamic_limit = total_senders * 25
        # Sync to config so UI is accurate
        conn.execute("UPDATE scheduler_config SET max_auto_send=? WHERE max_auto_send != ?",
                     (dynamic_limit, dynamic_limit))
        conn.commit()
    finally:
        conn.close()
    return dynamic_limit


def get_or_assign_sender_email(business_id: int) -> str:
    """
    Dynamically assign the best available sender email that has NOT hit its daily limit.
    Balances load by picking the sender with the lowest 'sent_today' count.
    Updates the 'assigned_sender_email' on the business so we know who sent it.
    """
    import os
    sender_emails_str = os.getenv("SENDER_EMAIL", "")
    active_emails = [e.strip() for e in sender_emails_str.split(",") if e.strip()]
    if not active_emails:
        return ""

    conn = get_conn()
    try:
        # Check if already assigned and STILL has capacity today
        row = conn.execute("SELECT assigned_sender_email FROM businesses WHERE id = ?", (business_id,)).fetchone()
        if row and row["assigned_sender_email"] in active_emails:
            current_assigned = row["assigned_sender_email"]
            if can_sender_send(current_assigned):
                return current_assigned

        # Otherwise, find a new sender from the pool with remaining capacity
        best_sender = None
        lowest_sent = 999999

        for email in active_emails:
            if can_sender_send(email):
                w_row = conn.execute("SELECT sent_today, last_send_date FROM sender_warmup WHERE sender_email=?", (email,)).fetchone()
                
                today = datetime.utcnow().strftime("%Y-%m-%d")
                sent_today = w_row["sent_today"] if w_row and w_row["last_send_date"] == today else 0
                
                if sent_today < lowest_sent:
                    lowest_sent = sent_today
                    best_sender = email

        if best_sender:
            conn.execute("UPDATE businesses SET assigned_sender_email = ? WHERE id = ?", (best_sender, business_id))
            conn.commit()
            return best_sender

        return "" # All senders have hit their daily limit
    finally:
        conn.close()




# ── Sender Warmup Tracking ────────────────────────────────────────────────

def get_sender_warmup(sender_email: str) -> dict:
    """Get warmup stats for a sender account. Creates entry if missing."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM sender_warmup WHERE sender_email=?", (sender_email,)).fetchone()
    if not row:
        conn.execute("""
            INSERT INTO sender_warmup (sender_email, start_date, current_daily_limit, sent_today, last_send_date)
            VALUES (?, datetime('now'), 5, 0, date('now'))
        """, (sender_email,))
        conn.commit()
        row = conn.execute("SELECT * FROM sender_warmup WHERE sender_email=?", (sender_email,)).fetchone()
    conn.close()
    return dict(row)


def increment_sender_send(sender_email: str):
    """Record a send for a sender account. Resets daily count if new day."""
    conn = get_conn()
    row = conn.execute("SELECT last_send_date FROM sender_warmup WHERE sender_email=?", (sender_email,)).fetchone()
    today = datetime.utcnow().strftime("%Y-%m-%d")
    
    if row and row["last_send_date"] != today:
        # New day — reset daily counter
        conn.execute("""
            UPDATE sender_warmup 
            SET sent_today=1, last_send_date=?, total_sent_lifetime=total_sent_lifetime+1
            WHERE sender_email=?
        """, (today, sender_email))
    elif row:
        conn.execute("""
            UPDATE sender_warmup
            SET sent_today=sent_today+1, total_sent_lifetime=total_sent_lifetime+1
            WHERE sender_email=?
        """, (sender_email,))
    else:
        conn.execute("""
            INSERT INTO sender_warmup (sender_email, start_date, current_daily_limit, sent_today, last_send_date, total_sent_lifetime)
            VALUES (?, datetime('now'), 5, 1, ?, 1)
        """, (sender_email, today))
    conn.commit()
    conn.close()


def get_sender_daily_limit(sender_email: str) -> int:
    """Calculate dynamic daily limit based on warmup age. Gradual ramp: 5 → 10 → 15 → 20 → 25 → 30."""
    import os
    if os.getenv("BYPASS_WARMUP", "false").lower() == "true":
        try:
            limit = int(os.getenv("CUSTOM_SENDER_LIMIT", "50"))
        except:
            limit = 50
        
        # Update the stored limit
        conn2 = get_conn()
        conn2.execute("INSERT OR IGNORE INTO sender_warmup (sender_email, start_date, current_daily_limit, sent_today) VALUES (?, datetime('now'), ?, 0)", (sender_email, limit))
        conn2.execute("UPDATE sender_warmup SET current_daily_limit=? WHERE sender_email=?", (limit, sender_email))
        conn2.commit()
        conn2.close()
        return limit

    conn = get_conn()
    row = conn.execute("SELECT * FROM sender_warmup WHERE sender_email=?", (sender_email,)).fetchone()
    conn.close()
    
    if not row:
        return 5
    
    start = datetime.fromisoformat(row["start_date"].replace("Z", "+00:00")) if row["start_date"] else datetime.utcnow()
    days_active = max(0, (datetime.utcnow() - start.replace(tzinfo=None)).days)
    
    # Warmup curve: 5/day for first 3 days, then +3/day every 3 days, cap at 30
    limit = min(30, 5 + (days_active // 3) * 3)
    
    # Update the stored limit
    conn2 = get_conn()
    conn2.execute("UPDATE sender_warmup SET current_daily_limit=? WHERE sender_email=?", (limit, sender_email))
    conn2.commit()
    conn2.close()
    return limit


def can_sender_send(sender_email: str) -> bool:
    """Check if a specific sender is under their daily limit."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM sender_warmup WHERE sender_email=?", (sender_email,)).fetchone()
    conn.close()
    
    if not row:
        return True  # New sender, will be initialized on first send
    
    today = datetime.utcnow().strftime("%Y-%m-%d")
    sent_today = row["sent_today"] if row["last_send_date"] == today else 0
    limit = get_sender_daily_limit(sender_email)
    return sent_today < limit


def get_all_sender_warmup_stats() -> list:
    """Get warmup stats for all sender accounts."""
    conn = get_conn()
    rows = conn.execute("SELECT * FROM sender_warmup ORDER BY sender_email").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Intelligent Conversion Score (ICS) ───────────────────────────────────────

# Niche conversion weights (0–25 pts) — based on digital maturity + pain + decision speed
_NICHE_WEIGHTS = {
    "gym": 25, "fitness": 25, "yoga": 25,
    "roofing": 25, "roofer": 25,
    "plumbing": 24, "plumber": 24,
    "landscaping": 23, "landscape": 23,
    "tree service": 22, "arborist": 22,
    "detailing": 21, "auto detailing": 21,
    "chiropractor": 20, "chiropractic": 20,
    "medspa": 20, "med spa": 20, "aesthetics": 20,
    "moving": 19, "mover": 19,
    "cleaning": 18, "cleaner": 18,
    "remodeler": 18, "remodeling": 18,
    "barbershop": 17, "barber": 17, "salon": 17,
    "restaurant": 15, "cafe": 15, "bistro": 15,
    "real estate": 14, "realtor": 14,
    "solar": 14,
    "hvac": 12,
    "accountant": 11, "cpa": 11,
    "lawyer": 10, "attorney": 10,
    "dentist": 9, "dental": 9,
}


def compute_ics(lead: dict, contact: dict = None) -> int:
    """
    Compute Intelligent Conversion Score (0–100) for a lead.
    Higher = more likely to convert. Used to rank the daily send queue.

    Breakdown:
      Website Pain Score      0–30  (low site quality = high urgency)
      Niche Conversion Weight 0–25  (category-based likelihood)
      Business Maturity       0–20  (rating + review signals)
      Personalization Bonus   0–15  (owner name, whatsapp, instagram)
      Pitch Match Score       0–10  (right pitch for their pain)
    """
    score = 0
    contact = contact or {}

    # ── 1. Website Pain Score (30 pts) ────────────────────────────────────
    ws = lead.get("website_score") or 0
    has_website = bool(lead.get("website"))
    if not has_website:
        score += 25  # Invisible online — massive pain
    elif ws < 30:
        score += 30  # Terrible site
    elif ws < 50:
        score += 22  # Clearly broken/outdated
    elif ws < 70:
        score += 12  # Mediocre, noticeable pain
    else:
        score += 3   # Decent site, hard sell

    # ── 2. Niche Conversion Weight (25 pts) ───────────────────────────────
    category = (lead.get("category") or "").lower()
    niche_pts = 8  # default for unknown niches
    for keyword, pts in _NICHE_WEIGHTS.items():
        if keyword in category:
            niche_pts = pts
            break
    score += niche_pts

    # ── 3. Business Maturity (20 pts) ─────────────────────────────────────
    rating = lead.get("google_rating") or 0
    reviews = lead.get("google_reviews") or 0
    if reviews >= 200:
        score += 10
    elif reviews >= 100:
        score += 7
    elif reviews >= 30:
        score += 4
    if rating >= 4.8:
        score += 10
    elif rating >= 4.5:
        score += 7
    elif rating >= 4.0:
        score += 4

    # ── 4. Personalization Bonus (15 pts) ─────────────────────────────────
    owner_name = contact.get("owner_name") or lead.get("owner_name") or ""
    whatsapp = contact.get("whatsapp") or lead.get("whatsapp") or ""
    instagram = contact.get("instagram") or lead.get("instagram") or ""
    if owner_name.strip():
        score += 8
    if whatsapp.strip():
        score += 4
    if instagram.strip():
        score += 3

    # ── 5. Pitch Match Score (10 pts) ─────────────────────────────────────
    pitch = (lead.get("pitch_type") or "").lower()
    if pitch == "website_redesign" and ws < 70:
        score += 10  # Perfect match: bad site + redesign pitch
    elif pitch == "leadflow_saas":
        score += 6
    elif pitch == "automation":
        score += 5
    else:
        score += 2

    # ── 6. Send-Time Bonus (0–20 pts) ─────────────────────────────────────
    # Leads whose LOCAL time is currently peak business hours jump to the
    # top of the queue. This ensures the scheduler always prioritises the
    # leads most likely to see the email right away.
    tz = lead.get("timezone") or ""
    if tz:
        st_score = compute_send_time_score(tz)  # 0-100
        # Scale to 0-20 pt bonus
        score += int(st_score * 0.20)

    return min(100, score)


def get_niche_sent_today(category: str) -> int:
    """Count emails sent today for a specific niche/category."""
    conn = get_conn()
    try:
        cat = (category or "").lower()
        count = conn.execute("""
            SELECT COUNT(*) as c
            FROM outreach o
            JOIN businesses b ON b.id = o.business_id
            WHERE o.status = 'sent'
              AND o.channel = 'email'
              AND date(o.sent_at) = date('now')
              AND lower(b.category) = ?
        """, (cat,)).fetchone()["c"]
        return count
    finally:
        conn.close()


def get_unsent_lead_count() -> int:
    """Count leads in queue that are ready to send (have email, status=new/approved)."""
    conn = get_conn()
    try:
        row = conn.execute("""
            SELECT COUNT(*) as c
            FROM businesses b
            LEFT JOIN contacts c ON c.business_id = b.id
            WHERE b.status IN ('new', 'approved')
              AND c.email IS NOT NULL AND c.email != ''
        """).fetchone()
        return row["c"]
    finally:
        conn.close()


def compute_niche_daily_budget(daily_total: int = 45) -> dict:
    """
    Compute per-niche daily email slot allocation using conversion-weighted ICS model.

    Strategy:
      - Calculates the average ICS score across all ready-to-send leads per niche
      - Allocates daily slots proportionally: niches with higher avg ICS get more slots
      - Enforces MIN=1 and MAX=9 per niche (anti-spam + guaranteed coverage)
      - Scales to exactly fill the daily_total quota

    Returns: dict of {category_lower: daily_slot_cap}

    Why avg ICS and not lead count?
      - A niche with 200 leads but low ICS (e.g. Solar avg=41.9) should get FEWER
        slots than a niche with 32 leads but high ICS (e.g. Tree Service avg=63.5)
      - This ensures we spend our daily send budget where conversion is most likely
    """
    conn = get_conn()
    try:
        rows = conn.execute("""
            SELECT b.category, b.website_score, b.website, b.google_rating,
                   b.google_reviews, b.pitch_type,
                   c.owner_name, c.whatsapp, c.instagram
            FROM businesses b
            LEFT JOIN contacts c ON c.business_id = b.id
            WHERE b.status IN ('new', 'approved')
              AND c.email IS NOT NULL AND c.email != ''
        """).fetchall()
    finally:
        conn.close()

    # Aggregate ICS scores per niche
    from collections import defaultdict
    niche_scores: dict = defaultdict(list)
    for r in rows:
        lead = dict(r)
        cat = (lead.get("category") or "unknown").lower()
        ics = compute_ics(lead, lead)
        niche_scores[cat].append(ics)

    if not niche_scores:
        return {}

    # Compute avg ICS per niche (the weight)
    niche_avg = {cat: sum(scores) / len(scores) for cat, scores in niche_scores.items()}
    total_weight = sum(niche_avg.values())

    MIN_SLOTS = 1
    MAX_SLOTS = 20   # raised from 9 — allows high-volume niches to absorb spillover

    # Raw proportional allocation
    raw_alloc = {cat: (avg / total_weight) * daily_total for cat, avg in niche_avg.items()}

    # Apply min/max and round
    alloc = {cat: max(MIN_SLOTS, min(MAX_SLOTS, round(slots)))
             for cat, slots in raw_alloc.items()}

    # Adjust total to exactly hit daily_total by scaling the largest buckets
    current_total = sum(alloc.values())
    diff = daily_total - current_total
    if diff != 0:
        sorted_cats = sorted(alloc.keys(), key=lambda c: raw_alloc[c], reverse=(diff > 0))
        for cat in sorted_cats:
            if diff == 0:
                break
            if diff > 0 and alloc[cat] < MAX_SLOTS:
                alloc[cat] += 1
                diff -= 1
            elif diff < 0 and alloc[cat] > MIN_SLOTS:
                alloc[cat] -= 1
                diff += 1

    # ── Spillover pass ─────────────────────────────────────────────────────
    # Check how many each niche has ALREADY sent today. If a niche is at or
    # over its cap, redistribute its remaining budget to niches that still
    # have capacity — so daily quota never goes to waste.
    conn2 = get_conn()
    try:
        sent_rows = conn2.execute("""
            SELECT LOWER(b.category) as cat, COUNT(*) as n
            FROM outreach o
            JOIN businesses b ON b.id = o.business_id
            WHERE o.status = 'sent'
              AND DATE(o.sent_at) = DATE('now')
            GROUP BY LOWER(b.category)
        """).fetchall()
    finally:
        conn2.close()

    sent_today_by_niche = {r["cat"]: r["n"] for r in sent_rows}

    # ── Spillover: raise all niche caps to absorb freed daily quota ───────────
    # If some niches hit their cap early, redistribute their freed slots across
    # ALL niches (including exhausted ones) so the daily total is actually used.
    sent_today_by_niche = {r["cat"]: r["n"] for r in sent_rows}

    freed = sum(
        alloc[cat]
        for cat in alloc
        if sent_today_by_niche.get(cat, 0) >= alloc[cat]
    )

    if freed > 0:
        # Spread freed slots evenly across ALL niches (exhausted or not)
        bonus_each = max(1, freed // max(1, len(alloc)))
        for cat in alloc:
            alloc[cat] += min(bonus_each, MAX_SLOTS - alloc[cat])


    import logging
    _log = logging.getLogger("leadflow.scheduler")
    log_lines = sorted(alloc.items(), key=lambda x: -x[1])
    _log.info(f"[NicheBudget] Daily allocation ({sum(alloc.values())} slots): "
              + ", ".join(f"{c}={s}" for c, s in log_lines[:10]))

    return alloc


# ── A/B Testing ───────────────────────────────────────────────────────────

def create_ab_test(business_id: int, subject_a: str, subject_b: str) -> int:
    """Create an A/B test for two subject lines."""
    conn = get_conn()
    cur = conn.execute("""
        INSERT INTO ab_tests (business_id, subject_a, subject_b)
        VALUES (?, ?, ?)
    """, (business_id, subject_a, subject_b))
    conn.commit()
    test_id = cur.lastrowid
    conn.close()
    return test_id


def _make_old_subject(business_id: int, name: str) -> str:
    """Generate the OLD generic subject formula for A/B control group.
    NOTE: 'Quick question for' and 'Idea for' are banned per copy rules — use
    compliant alternatives that preserve the A/B control-group spirit.
    """
    # Shorten to first 3 meaningful words to match old behaviour
    short = " ".join(name.split()[:3]) if len(name.split()) > 3 else name
    # Alternate between two compliant generic templates (fix #4)
    if business_id % 4 < 2:
        return f"Improvement for {short}"
    return f"Quick thought on {short}"


def pick_ab_subject(business_id: int, subject_options: list, business_name: str = "") -> tuple:
    """Pick which subject line to use for A/B testing.

    Experiment: OLD formula (control) vs NEW formula (treatment).
    - Even business_id  → Variant A = OLD generic subject
    - Odd  business_id  → Variant B = NEW specific subject (from subject_options[0])

    Returns (chosen_subject, variant_label).
    """
    new_subject = subject_options[0] if subject_options else "Quick question"
    old_subject = _make_old_subject(business_id, business_name or new_subject)

    # 50/50 split by ID parity
    if business_id % 2 == 0:
        variant  = "A"
        subject  = old_subject
        label_a  = "Old Formula"
        label_b  = "New Formula"
    else:
        variant  = "B"
        subject  = new_subject
        label_a  = "Old Formula"
        label_b  = "New Formula"

    # Log in database for tracking
    conn = get_conn()
    try:
        test = conn.execute(
            "SELECT * FROM ab_tests WHERE business_id = ?", (business_id,)
        ).fetchone()
        if not test:
            conn.execute("""
                INSERT INTO ab_tests
                  (business_id, subject_a, subject_b, sent_a, sent_b,
                   experiment, label_a, label_b)
                VALUES (?, ?, ?, ?, ?, 'old_vs_new', ?, ?)
            """, (
                business_id, old_subject, new_subject,
                1 if variant == "A" else 0,
                0 if variant == "A" else 1,
                label_a, label_b,
            ))
        else:
            if variant == "A":
                conn.execute("UPDATE ab_tests SET sent_a = sent_a + 1 WHERE id = ?", (test["id"],))
            else:
                conn.execute("UPDATE ab_tests SET sent_b = sent_b + 1 WHERE id = ?", (test["id"],))
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()

    return (subject, variant)


def record_ab_open(tracking_id: str):
    """Record an open event for A/B testing — called from tracking event handler."""
    conn = get_conn()
    # Find which outreach this tracking_id belongs to
    outreach = conn.execute("""
        SELECT business_id, subject_used FROM outreach WHERE tracking_id=?
    """, (tracking_id,)).fetchone()
    
    if not outreach:
        conn.close()
        return
    
    # Find matching A/B test
    test = conn.execute("""
        SELECT * FROM ab_tests WHERE business_id=? AND winner IS NULL
    """, (outreach["business_id"],)).fetchone()
    
    if test:
        subject = outreach["subject_used"] or ""
        if subject == test["subject_a"]:
            conn.execute("UPDATE ab_tests SET opens_a=opens_a+1 WHERE id=?", (test["id"],))
        elif subject == test["subject_b"]:
            conn.execute("UPDATE ab_tests SET opens_b=opens_b+1 WHERE id=?", (test["id"],))
        conn.commit()
    conn.close()


def resolve_ab_winners():
    """Check all unresolved A/B tests and declare winners based on open rates.
    
    Rules:
    - Minimum 10 sends per variant required before declaring a winner
    - Minimum 20 total sends across both variants
    - After 7 days with insufficient data, declare the leading variant winner anyway
      (avoids tests running forever with no resolution)
    - Tie goes to A (default/control variant)
    """
    conn = get_conn()
    try:
        tests = conn.execute("""
            SELECT * FROM ab_tests 
            WHERE winner IS NULL 
            AND created_at <= datetime('now', '-24 hours')
        """).fetchall()
        
        MIN_SENDS_PER_VARIANT = 10
        MIN_TOTAL_SENDS = 20
        MAX_WAIT_DAYS = 7  # After 7 days, force resolution with whatever data exists

        for test in tests:
            sent_a   = test["sent_a"] or 0
            sent_b   = test["sent_b"] or 0
            opens_a  = test["opens_a"] or 0
            opens_b  = test["opens_b"] or 0
            total    = sent_a + sent_b

            # Check if we've waited long enough to force-resolve
            from datetime import datetime as _dt
            created = _dt.fromisoformat(test["created_at"])
            days_old = (_dt.utcnow() - created).days
            force_resolve = days_old >= MAX_WAIT_DAYS

            # If not enough data and not yet force-resolving, skip
            if not force_resolve:
                if sent_a < MIN_SENDS_PER_VARIANT or sent_b < MIN_SENDS_PER_VARIANT:
                    continue
                if total < MIN_TOTAL_SENDS:
                    continue

            # Compute open rates (avoid div by zero)
            rate_a = opens_a / sent_a if sent_a > 0 else 0.0
            rate_b = opens_b / sent_b if sent_b > 0 else 0.0

            if rate_b > rate_a:
                winner = "B"
            else:
                winner = "A"  # Tie or A leads -> A wins (control stays if equal)

            reason = "force-resolved (7 days, insufficient data)" if force_resolve else f"A={rate_a:.1%} vs B={rate_b:.1%}"
            conn.execute("""
                UPDATE ab_tests SET winner=?, resolved_at=datetime('now') WHERE id=?
            """, (winner, test["id"]))
            import logging as _log
            _log.getLogger("leadflow").info(f"[A/B] Test #{test['id']} resolved: winner={winner} ({reason})")

        conn.commit()
    except Exception as e:
        import logging as _log
        _log.getLogger("leadflow").error(f"[A/B] resolve_ab_winners error: {e}")
    finally:
        conn.close()


def get_ab_winner_subject(subject_options: list) -> str:
    """Look up historical outreach data to pick the best performing subject style."""
    if not subject_options:
        return "Quick question"
    if len(subject_options) < 2:
        return subject_options[0]
        
    conn = get_conn()
    try:
        # Query the overall outreach table to find which option has a higher open rate
        row_a = conn.execute("""
            SELECT COUNT(*) as sends, SUM(opened) as opens
            FROM outreach
            WHERE subject_used = ?
        """, (subject_options[0],)).fetchone()
        
        row_b = conn.execute("""
            SELECT COUNT(*) as sends, SUM(opened) as opens
            FROM outreach
            WHERE subject_used = ?
        """, (subject_options[1],)).fetchone()
        
        sends_a = row_a["sends"] if row_a else 0
        opens_a = row_a["opens"] if row_a and row_a["opens"] else 0
        sends_b = row_b["sends"] if row_b else 0
        opens_b = row_b["opens"] if row_b and row_b["opens"] else 0
        
        if sends_a >= 3 and sends_b >= 3:
            rate_a = opens_a / sends_a
            rate_b = opens_b / sends_b
            if rate_a > rate_b:
                return subject_options[0]
            elif rate_b > rate_a:
                return subject_options[1]
    except Exception:
        pass
    finally:
        conn.close()
        
    return subject_options[0]


# ── Send-Time Optimization ────────────────────────────────────────────────

def detect_timezone(city: str, country: str) -> str:
    """Detect timezone from city/country. Returns IANA timezone string."""
    city_lower = (city or "").lower().strip()
    country_lower = (country or "").lower().strip()
    
    # Common timezone mappings for major cities/regions
    tz_map = {
        # US Eastern
        "new york": "America/New_York", "boston": "America/New_York", "miami": "America/New_York",
        "philadelphia": "America/New_York", "atlanta": "America/New_York", "washington": "America/New_York",
        "jacksonville": "America/New_York", "charlotte": "America/New_York", "columbus": "America/New_York",
        "indianapolis": "America/Indiana/Indianapolis", "detroit": "America/Detroit",
        "nashville": "America/Chicago", "louisville": "America/Kentucky/Louisville",
        "baltimore": "America/New_York", "virginia beach": "America/New_York",
        "newark": "America/New_York", "jersey city": "America/New_York",
        "pittsburgh": "America/New_York", "buffalo": "America/New_York",
        "raleigh": "America/New_York", "durham": "America/New_York",
        "richmond": "America/New_York", "norfolk": "America/New_York",
        "greensboro": "America/New_York", "winston-salem": "America/New_York",
        "providence": "America/New_York", "worcester": "America/New_York",
        "fort lauderdale": "America/New_York", "tampa": "America/New_York",
        "st. petersburg": "America/New_York", "orlando": "America/New_York",
        "tallahassee": "America/New_York", "pembroke pines": "America/New_York",
        "port st. lucie": "America/New_York", "cape coral": "America/New_York",
        "hialeah": "America/New_York", "cleveland": "America/New_York",
        "cincinnati": "America/New_York",
        # US Central
        "chicago": "America/Chicago", "houston": "America/Chicago", "dallas": "America/Chicago",
        "austin": "America/Chicago", "san antonio": "America/Chicago", "milwaukee": "America/Chicago",
        "minneapolis": "America/Chicago", "st. paul": "America/Chicago", "st. louis": "America/Chicago",
        "kansas city": "America/Chicago", "omaha": "America/Chicago", "tulsa": "America/Chicago",
        "oklahoma city": "America/Chicago", "memphis": "America/Chicago",
        "new orleans": "America/Chicago", "wichita": "America/Chicago",
        "fort worth": "America/Chicago", "plano": "America/Chicago",
        "garland": "America/Chicago", "irving": "America/Chicago", "laredo": "America/Chicago",
        "lubbock": "America/Chicago", "corpus christi": "America/Chicago",
        "brownsville": "America/Chicago", "des moines": "America/Chicago",
        "grand rapids": "America/Chicago", "madison": "America/Chicago",
        "lincoln": "America/Chicago", "sioux falls": "America/Chicago",
        "jackson": "America/Chicago", "baton rouge": "America/Chicago",
        "little rock": "America/Chicago", "birmingham": "America/Chicago",
        "montgomery": "America/Chicago", "huntsville": "America/Chicago",
        "knoxville": "America/Chicago", "chattanooga": "America/Chicago",
        # US Mountain
        "denver": "America/Denver", "salt lake": "America/Denver",
        "albuquerque": "America/Denver", "el paso": "America/Denver",
        "colorado springs": "America/Denver", "aurora": "America/Denver",
        "tucson": "America/Phoenix", "phoenix": "America/Phoenix",
        "mesa": "America/Phoenix", "chandler": "America/Phoenix",
        "scottsdale": "America/Phoenix", "tempe": "America/Phoenix",
        "peoria": "America/Phoenix", "glendale": "America/Phoenix",
        # US Pacific
        "los angeles": "America/Los_Angeles", "san francisco": "America/Los_Angeles",
        "seattle": "America/Los_Angeles", "portland": "America/Los_Angeles", "san diego": "America/Los_Angeles",
        "las vegas": "America/Los_Angeles", "sacramento": "America/Los_Angeles",
        "san jose": "America/Los_Angeles", "fresno": "America/Los_Angeles",
        "long beach": "America/Los_Angeles", "bakersfield": "America/Los_Angeles",
        "anaheim": "America/Los_Angeles", "santa ana": "America/Los_Angeles",
        "irvine": "America/Los_Angeles", "riverside": "America/Los_Angeles",
        "stockton": "America/Los_Angeles", "oakland": "America/Los_Angeles",
        "fremont": "America/Los_Angeles", "modesto": "America/Los_Angeles",
        "fontana": "America/Los_Angeles", "moreno valley": "America/Los_Angeles",
        "lancaster": "America/Los_Angeles", "elk grove": "America/Los_Angeles",
        "corona": "America/Los_Angeles", "santa clarita": "America/Los_Angeles",
        "garden grove": "America/Los_Angeles", "oceanside": "America/Los_Angeles",
        "rancho cucamonga": "America/Los_Angeles", "ontario": "America/Los_Angeles",
        "santa rosa": "America/Los_Angeles", "huntington beach": "America/Los_Angeles",
        "oxnard": "America/Los_Angeles", "fayetteville": "America/Los_Angeles",
        "reno": "America/Los_Angeles", "henderson": "America/Los_Angeles",
        "north las vegas": "America/Los_Angeles", "van couver": "America/Los_Angeles",
        "spokane": "America/Los_Angeles", "tacoma": "America/Los_Angeles",
        "eugene": "America/Los_Angeles", "salem": "America/Los_Angeles",
        "boise": "America/Boise",
        # US non-contiguous
        "honolulu": "Pacific/Honolulu", "anchorage": "America/Anchorage",
        # Canada
        "toronto": "America/Toronto", "montreal": "America/Toronto",
        "ottawa": "America/Toronto", "hamilton": "America/Toronto",
        "vancouver": "America/Vancouver", "calgary": "America/Edmonton",
        "edmonton": "America/Edmonton", "winnipeg": "America/Winnipeg",
        "halifax": "America/Halifax",
        # UK & Ireland
        "london": "Europe/London", "manchester": "Europe/London",
        "birmingham uk": "Europe/London", "leeds": "Europe/London",
        "glasgow": "Europe/London", "edinburgh": "Europe/London",
        "dublin": "Europe/Dublin",
        # Europe
        "paris": "Europe/Paris", "berlin": "Europe/Berlin", "munich": "Europe/Berlin",
        "frankfurt": "Europe/Berlin", "hamburg": "Europe/Berlin",
        "madrid": "Europe/Madrid", "barcelona": "Europe/Madrid", "rome": "Europe/Rome",
        "amsterdam": "Europe/Amsterdam", "rotterdam": "Europe/Amsterdam",
        "brussels": "Europe/Brussels", "zurich": "Europe/Zurich", "geneva": "Europe/Zurich",
        # Australia & NZ
        "sydney": "Australia/Sydney", "melbourne": "Australia/Melbourne",
        "brisbane": "Australia/Brisbane", "perth": "Australia/Perth",
        "adelaide": "Australia/Adelaide", "canberra": "Australia/Sydney",
        "auckland": "Pacific/Auckland", "wellington": "Pacific/Auckland",
        # Middle East
        "dubai": "Asia/Dubai", "abu dhabi": "Asia/Dubai",
        # Asia
        "mumbai": "Asia/Kolkata", "delhi": "Asia/Kolkata", "bangalore": "Asia/Kolkata",
        "singapore": "Asia/Singapore", "tokyo": "Asia/Tokyo",
        "hong kong": "Asia/Hong_Kong", "shanghai": "Asia/Shanghai",
        # Latin America
        "sao paulo": "America/Sao_Paulo", "mexico city": "America/Mexico_City",
        "buenos aires": "America/Argentina/Buenos_Aires",
    }
    
    for city_key, tz in tz_map.items():
        if city_key in city_lower:
            return tz
    
    # Country-level fallbacks
    country_tz = {
        "united states": "America/New_York", "usa": "America/New_York", "us": "America/New_York",
        "canada": "America/Toronto", "united kingdom": "Europe/London", "uk": "Europe/London",
        "australia": "Australia/Sydney", "new zealand": "Pacific/Auckland",
        "india": "Asia/Kolkata", "germany": "Europe/Berlin",
        "france": "Europe/Paris", "spain": "Europe/Madrid", "italy": "Europe/Rome",
        "netherlands": "Europe/Amsterdam", "ireland": "Europe/Dublin",
        "switzerland": "Europe/Zurich",
        "uae": "Asia/Dubai", "united arab emirates": "Asia/Dubai",
        "singapore": "Asia/Singapore", "japan": "Asia/Tokyo",
        "brazil": "America/Sao_Paulo", "mexico": "America/Mexico_City",
        "south africa": "Africa/Johannesburg",
    }
    
    for country_key, tz in country_tz.items():
        if country_key in country_lower:
            return tz
    
    return "America/New_York"  # Default fallback


def compute_send_time_score(timezone_str: str) -> int:
    """
    Returns a 0-100 score for how good RIGHT NOW is to email this lead.

    0   = outside working hours entirely (do NOT send)
    1-49 = acceptable window (Mon/Fri, or afternoon 2-5pm)
    50-79 = good window (Tue-Thu, 8-9am or 11am-2pm)
    80-100 = peak window (Tue-Thu, 9-11am — highest open rates)

    This score is used as a tiebreaker in the ICS queue so leads in
    prime local morning slots are always sent before afternoon leads.
    """
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo(timezone_str))
    except Exception:
        return 50  # Unknown timezone — allow send with neutral score

    weekday = now.weekday()  # 0=Mon, 6=Sun
    hour    = now.hour

    # Weekends — don't send
    if weekday >= 5:
        return 0

    # Outside 7am-6pm local — don't send
    if hour < 7 or hour >= 18:
        return 0

    # Score the day: Tue/Wed/Thu best, Mon/Fri lower
    day_score = 100 if weekday in (1, 2, 3) else 60

    # Score the hour: 9-11am peak, 8-9am and 11am-2pm good, rest ok
    if 9 <= hour < 11:
        hour_score = 100
    elif hour == 8 or (11 <= hour < 14):
        hour_score = 70
    elif 14 <= hour < 17:
        hour_score = 45
    else:  # 7am or 5-6pm
        hour_score = 25

    return int((day_score + hour_score) / 2)


def is_optimal_send_time(timezone_str: str, window_start: int = 8, window_end: int = 18,
                         preferred_days: list = None) -> bool:
    """Returns True if it's an acceptable time to send to this lead.

    Respects the caller-supplied window_start/window_end/preferred_days values
    (which come from the DB scheduler_config so the user's UI settings are
    honoured).  When the user sets 0-24h / all-7-days the function always
    returns True so the autopilot runs 24/7 as configured.

    Falls back to compute_send_time_score() only when the caller did NOT supply
    explicit window params (i.e. both still at their defaults: start=8, end=18).
    """
    # If the user configured a fully-open window (0-24h, all days) → always send
    if window_start == 0 and window_end >= 24 and preferred_days and set(preferred_days) >= {0,1,2,3,4,5,6}:
        return True

    # Non-default window supplied by caller — apply it directly
    try:
        from zoneinfo import ZoneInfo
        now_local = datetime.now(ZoneInfo(timezone_str or "America/New_York"))
    except Exception:
        return True  # Unknown timezone — allow send

    hour    = now_local.hour
    weekday = now_local.weekday()  # 0=Mon … 6=Sun

    # Check day restriction
    if preferred_days and weekday not in preferred_days:
        return False

    # Check hour window (window_end==24 means midnight, treat as inclusive of hour 23)
    effective_end = 24 if window_end >= 24 else window_end
    if not (window_start <= hour < effective_end):
        return False

    return True


def update_business_timezone(business_id: int, timezone_str: str):
    """Store detected timezone for a business."""
    conn = get_conn()
    conn.execute("UPDATE businesses SET timezone=? WHERE id=?", (timezone_str, business_id))
    conn.commit()
    conn.close()


# ── Reply Classification ──────────────────────────────────────────────────

def save_reply_classification(business_id: int, classification: str, reply_text: str = ""):
    """Save AI-classified reply type: interested, question, not_interested, unsubscribe."""
    conn = get_conn()
    conn.execute("UPDATE contacts SET reply_classification=? WHERE business_id=?", (classification, business_id))
    if reply_text:
        conn.execute("UPDATE contacts SET reply_text=? WHERE business_id=?", (reply_text, business_id))
    conn.commit()
    conn.close()


def get_reply_classifications() -> dict:
    """Get count of each reply classification type."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT reply_classification, COUNT(*) as c 
        FROM contacts 
        WHERE reply_classification IS NOT NULL 
        GROUP BY reply_classification
    """).fetchall()
    conn.close()
    return {r["reply_classification"]: r["c"] for r in rows}


# ── Enhanced Analytics ────────────────────────────────────────────────────

def get_emails_sent_by_sender() -> dict:
    """Get today's send count per sender email for warmup tracking."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT b.assigned_sender_email, COUNT(*) as c 
        FROM outreach o
        JOIN businesses b ON b.id = o.business_id
        WHERE o.status='sent' AND o.channel='email' 
        AND date(o.sent_at) = date('now')
        AND b.assigned_sender_email IS NOT NULL
        GROUP BY b.assigned_sender_email
    """).fetchall()
    conn.close()
    return {r["assigned_sender_email"]: r["c"] for r in rows}

