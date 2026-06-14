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
            found_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER REFERENCES businesses(id),
            email TEXT,
            instagram TEXT,
            linkedin_name TEXT,
            linkedin_url TEXT,
            whatsapp TEXT
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
            max_per_run INTEGER DEFAULT 20
        );
    """)

    # Migrate existing DB — add new columns if missing
    for col, definition in [
        ("lead_score",       "INTEGER DEFAULT 0"),
        ("domain_available", "TEXT"),
        ("source",           "TEXT DEFAULT 'google_maps'"),
        ("maps_url",         "TEXT"),
        ("demo_tunnel_url",  "TEXT"),
    ]:
        try:
            conn.execute(f"ALTER TABLE businesses ADD COLUMN {col} {definition}")
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

    conn.commit()
    conn.close()


def insert_business(data: dict) -> int:
    conn = get_conn()
    cur = conn.execute("""
        INSERT INTO businesses (name, category, address, city, country, phone,
            website, website_score, google_rating, google_reviews, gap, pitch_type,
            lead_score, domain_available, source, maps_url)
        VALUES (:name, :category, :address, :city, :country, :phone,
            :website, :website_score, :google_rating, :google_reviews, :gap, :pitch_type,
            :lead_score, :domain_available, :source, :maps_url)
    """, {
        "lead_score": data.get("lead_score", 0),
        "domain_available": data.get("domain_available"),
        "source": data.get("source", "google_maps"),
        "maps_url": data.get("maps_url"),
        **data,
    })
    conn.commit()
    bid = cur.lastrowid
    conn.close()
    return bid


def insert_contacts(business_id: int, contacts: dict):
    conn = get_conn()
    conn.execute("""
        INSERT INTO contacts (business_id, email, instagram, linkedin_name, linkedin_url, whatsapp)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        business_id,
        contacts.get("email"),
        contacts.get("instagram"),
        contacts.get("linkedin_name"),
        contacts.get("linkedin_url"),
        contacts.get("whatsapp"),
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
        WHERE b.status NOT IN ('skipped')
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
        INSERT INTO deals (business_id, value_usd, service, notes)
        VALUES (?, ?, ?, ?)
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
    for status in ("new", "approved", "sent", "replied", "skipped", "closed"):
        row = conn.execute("SELECT COUNT(*) as c FROM businesses WHERE status=?", (status,)).fetchone()
        stats[status] = row["c"]
    conn.close()
    return stats
