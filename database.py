import sqlite3
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent / "leadflow.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
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
            found_at TEXT DEFAULT CURRENT_TIMESTAMP
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
            replied INTEGER DEFAULT 0,
            opened INTEGER DEFAULT 0,
            clicked INTEGER DEFAULT 0,
            open_count INTEGER DEFAULT 0,
            tracking_id TEXT
        );

        CREATE TABLE IF NOT EXISTS follow_ups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER REFERENCES businesses(id),
            sequence_num INTEGER,
            channel TEXT,
            draft TEXT,
            status TEXT DEFAULT 'pending',
            scheduled_for TEXT,
            sent_at TEXT
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
    ]:
        try:
            conn.execute(f"ALTER TABLE businesses ADD COLUMN {col} {definition}")
        except Exception:
            pass

    for col, definition in [
        ("replied_at", "TEXT"),
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
    ]:
        try:
            conn.execute(f"ALTER TABLE outreach ADD COLUMN {col} {definition}")
        except Exception:
            pass

    for col, definition in [
        ("source",    "TEXT DEFAULT 'google_maps'"),
        ("max_score", "INTEGER DEFAULT 70"),
    ]:
        try:
            conn.execute(f"ALTER TABLE scheduler_config ADD COLUMN {col} {definition}")
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
        existing = conn.execute("SELECT id FROM businesses WHERE LOWER(website) = ?", (website.lower(),)).fetchone()
        if existing:
            conn.close()
            return existing["id"]
            
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
            existing = conn.execute("SELECT id FROM businesses WHERE LOWER(name) = ? AND LOWER(city) = ?", (name.lower(), city.lower())).fetchone()
            if existing:
                conn.close()
                return existing["id"]

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
    }

    cur = conn.execute("""
        INSERT INTO businesses (name, category, address, city, country, phone,
            website, website_score, google_rating, google_reviews, gap, pitch_type,
            lead_score, domain_available, source, maps_url)
        VALUES (:name, :category, :address, :city, :country, :phone,
            :website, :website_score, :google_rating, :google_reviews, :gap, :pitch_type,
            :lead_score, :domain_available, :source, :maps_url)
    """, bind_data)
    conn.commit()
    bid = cur.lastrowid
    conn.close()
    return bid


def insert_contacts(business_id: int, contacts: dict):
    conn = get_conn()
    conn.execute('''
        INSERT OR REPLACE INTO contacts 
        (business_id, email, instagram, facebook, linkedin_url, linkedin_name, whatsapp, hunter_email, apollo_email, apollo_person_name)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        contacts.get("apollo_person_name")
    ))
    conn.commit()
    conn.close()


def get_leads(status: str = "new") -> list:
    conn = get_conn()
    rows = conn.execute("""
        SELECT b.*, c.email, c.instagram, c.linkedin_name, c.linkedin_url, c.whatsapp
        FROM businesses b
        LEFT JOIN contacts c ON c.business_id = b.id
        WHERE b.status = ?
        ORDER BY b.lead_score DESC, b.found_at DESC
    """, (status,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_active_leads() -> list:
    """All leads except skipped — used for review page (show everything always)."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT b.*, c.email, c.instagram, c.linkedin_name, c.linkedin_url, c.whatsapp
        FROM businesses b
        LEFT JOIN contacts c ON c.business_id = b.id
        WHERE b.status NOT IN ('skipped')
        ORDER BY b.lead_score DESC, b.found_at DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_leads_for_kanban() -> list:
    conn = get_conn()
    rows = conn.execute("""
        SELECT b.*, c.email, c.instagram
        FROM businesses b
        LEFT JOIN contacts c ON c.business_id = b.id
        WHERE b.status NOT IN ('skipped', 'opted_out')
        ORDER BY b.lead_score DESC, b.found_at DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_business_status(bid: int, status: str):
    conn = get_conn()
    conn.execute("UPDATE businesses SET status=? WHERE id=?", (status, bid))
    conn.commit()
    conn.close()


def insert_outreach(business_id: int, channel: str, draft: str, subject_options: str = ""):
    conn = get_conn()
    import uuid
    tracking_id = str(uuid.uuid4())
    conn.execute("""
        INSERT INTO outreach (business_id, channel, draft, final_message, subject_options, status, tracking_id)
        VALUES (?, ?, ?, ?, ?, 'draft', ?)
    """, (business_id, channel, draft, draft, subject_options, tracking_id))
    conn.commit()
    conn.close()
    return tracking_id


def mark_sent(business_id: int, channel: str):
    conn = get_conn()
    conn.execute("""
        UPDATE outreach SET status='sent', sent_at=?
        WHERE business_id=? AND channel=?
    """, (datetime.now().isoformat(), business_id, channel))
    conn.commit()
    conn.close()


def record_tracking_event(tracking_id: str, business_id: int, event_type: str, metadata: str = ""):
    conn = get_conn()
    conn.execute("""
        INSERT INTO tracking_events (tracking_id, business_id, event_type, metadata)
        VALUES (?, ?, ?, ?)
    """, (tracking_id, business_id, event_type, metadata))
    if event_type == "open":
        conn.execute("""
            UPDATE outreach SET opened=1, open_count=open_count+1
            WHERE tracking_id=?
        """, (tracking_id,))
    elif event_type == "click":
        conn.execute("UPDATE outreach SET clicked=1 WHERE tracking_id=?", (tracking_id,))
    conn.commit()
    conn.close()


def insert_follow_ups(business_id: int, sequences: list[dict]):
    conn = get_conn()
    for seq in sequences:
        conn.execute("""
            INSERT INTO follow_ups (business_id, sequence_num, channel, draft, scheduled_for)
            VALUES (?, ?, ?, ?, ?)
        """, (business_id, seq["num"], seq["channel"], seq["draft"], seq["scheduled_for"]))
    conn.commit()
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
          AND f.scheduled_for <= datetime('now')
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


def mark_follow_up_sent(fid: int):
    conn = get_conn()
    conn.execute("UPDATE follow_ups SET status='sent', sent_at=? WHERE id=?",
                 (datetime.now().isoformat(), fid))
    conn.commit()
    conn.close()


def insert_deal(business_id: int, value: float, service: str, notes: str = ""):
    conn = get_conn()
    conn.execute("""
        INSERT INTO deals (business_id, value_usd, service, status, notes, closed_at)
        VALUES (?, ?, ?, 'closed', ?, CURRENT_TIMESTAMP)
    """, (business_id, value, service, notes))
    conn.execute("UPDATE businesses SET status='closed' WHERE id=?", (business_id,))
    conn.commit()
    conn.close()


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
        row = conn.execute("SELECT COUNT(*) as c FROM businesses WHERE status=?", (status,)).fetchone()
        stats[status] = row["c"]
    
    # Check if autopilot scheduler is enabled
    cfg_row = conn.execute("SELECT enabled FROM scheduler_config LIMIT 1").fetchone()
    stats["autopilot_active"] = bool(cfg_row["enabled"]) if cfg_row else False
    
    conn.close()
    return stats


def get_emails_sent_today() -> int:
    conn = get_conn()
    count1 = conn.execute("""
        SELECT COUNT(*) as c FROM outreach 
        WHERE status='sent' AND channel='email' AND date(sent_at) = date('now')
    """).fetchone()["c"]
    count2 = conn.execute("""
        SELECT COUNT(*) as c FROM follow_ups 
        WHERE status='sent' AND channel='email' AND date(sent_at) = date('now')
    """).fetchone()["c"]
    conn.close()
    return count1 + count2
