"""
Background scheduler — runs daily auto-find and queues follow-ups.
Uses APScheduler. Started by server.py on launch.
"""
import json
import logging
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler

log = logging.getLogger("leadflow.scheduler")
scheduler = BackgroundScheduler(timezone="UTC")


def _get_config() -> dict:
    from database import get_conn
    conn = get_conn()
    row = conn.execute("SELECT * FROM scheduler_config LIMIT 1").fetchone()
    conn.close()
    if not row:
        return {"enabled": False}
    return dict(row)


def job_daily_find():
    """Run at configured hour — find new businesses from saved niches."""
    cfg = _get_config()
    if not cfg.get("enabled"):
        return

    niches    = json.loads(cfg.get("niches") or "[]")
    locations = json.loads(cfg.get("locations") or "[]")
    max_per   = cfg.get("max_per_run", 20)

    if not niches or not locations:
        return

    from finder import run_finder
    import itertools

    # Rotate: today's pair based on day of year
    day = datetime.now().timetuple().tm_yday
    niche    = niches[day % len(niches)]
    location = locations[day % len(locations)]

    log.info(f"[Scheduler] Daily find: {niche} in {location}")
    try:
        run_finder(niche, location, max_per)
    except Exception as e:
        log.error(f"[Scheduler] Daily find error: {e}")


def job_queue_follow_ups():
    """Check for leads sent 4+ days ago with no reply — queue follow-up."""
    from database import get_conn, insert_follow_ups
    from ai_writer import write_follow_up_sequence

    conn = get_conn()
    # Leads sent 4+ days ago, still status='sent'
    rows = conn.execute("""
        SELECT b.*, c.email, c.instagram
        FROM businesses b
        LEFT JOIN contacts c ON c.business_id = b.id
        WHERE b.status = 'sent'
          AND b.found_at <= datetime('now', '-4 days')
          AND b.id NOT IN (SELECT DISTINCT business_id FROM follow_ups)
        LIMIT 10
    """).fetchall()
    conn.close()

    for row in rows:
        lead = dict(row)
        log.info(f"[Scheduler] Queuing follow-up for: {lead['name']}")
        try:
            sequences = write_follow_up_sequence(lead)
            insert_follow_ups(lead["id"], sequences)
        except Exception as e:
            log.error(f"[Scheduler] Follow-up gen error for {lead['name']}: {e}")


def start_scheduler():
    """Start background scheduler. Called once on server startup."""
    cfg = _get_config()
    hour = cfg.get("run_hour", 6)

    scheduler.add_job(job_daily_find,      "cron", hour=hour, minute=0,  id="daily_find",    replace_existing=True)
    scheduler.add_job(job_queue_follow_ups, "cron", hour=hour, minute=30, id="queue_followups", replace_existing=True)

    if not scheduler.running:
        scheduler.start()
        log.info(f"[Scheduler] Started — daily find at {hour}:00 UTC")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)


def save_scheduler_config(niches: list, locations: list, enabled: bool, hour: int, max_per: int):
    from database import get_conn
    conn = get_conn()
    conn.execute("DELETE FROM scheduler_config")
    conn.execute("""
        INSERT INTO scheduler_config (niches, locations, enabled, run_hour, max_per_run)
        VALUES (?, ?, ?, ?, ?)
    """, (json.dumps(niches), json.dumps(locations), int(enabled), hour, max_per))
    conn.commit()
    conn.close()

    # Reschedule with new config
    scheduler.reschedule_job("daily_find", trigger="cron", hour=hour, minute=0)
