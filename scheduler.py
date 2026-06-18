"""
Background scheduler — runs daily auto-find and queues follow-ups.
Uses APScheduler. Started by server.py on launch.
"""
import json
import logging
import sys
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler

log = logging.getLogger("leadflow.scheduler")
log.setLevel(logging.INFO)
if not log.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    log.addHandler(handler)

scheduler = BackgroundScheduler(timezone="UTC")


def _get_config() -> dict:
    from database import get_conn
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM scheduler_config LIMIT 1").fetchone()
        if not row:
            return {"enabled": False}
        return dict(row)
    finally:
        conn.close()


def job_daily_find():
    """Run at configured hour — find new businesses from saved niches."""
    cfg = _get_config()
    if not cfg.get("enabled"):
        return

    niches    = json.loads(cfg.get("niches") or "[]")
    locations = json.loads(cfg.get("locations") or "[]")
    max_per   = cfg.get("max_per_run", 20)
    max_score = cfg.get("max_score", 70)
    source    = cfg.get("source", "google_maps")

    if not niches or not locations:
        log.warning("[Scheduler] No niches or locations configured — skipping.")
        return

    import random as _random

    # Rotate niches sequentially, pick location randomly
    last_niche_idx = cfg.get("last_niche_idx", 0) or 0
    next_niche_idx = (last_niche_idx + 1) % len(niches)
    niche    = niches[last_niche_idx % len(niches)]
    location = _random.choice(locations)   # ← random, not sequential

    # Update niche index in DB
    from database import get_conn
    conn = get_conn()
    try:
        conn.execute("UPDATE scheduler_config SET last_niche_idx=?, last_loc_idx=0", (next_niche_idx,))
        conn.commit()
    finally:
        conn.close()

    log.info(f"[Scheduler] Daily find: {niche} in {location} via {source}")
    try:
        from finder import run_finder
        run_finder(niche, location, max_per, source, max_score)
    except Exception as e:
        log.error(f"[Scheduler] Daily find error: {e}")


def job_queue_follow_ups():
    """Check for leads sent 4+ days ago with no reply — queue follow-up."""
    from database import get_conn, insert_follow_ups
    from ai_writer import write_follow_up_sequence

    conn = get_conn()
    try:
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
        leads = [dict(r) for r in rows]
    finally:
        conn.close()

    for lead in leads:
        log.info(f"[Scheduler] Queuing follow-up for: {lead['name']}")
        try:
            demo_url = lead.get("demo_tunnel_url", "")
            sequences = write_follow_up_sequence(lead, demo_url)
            insert_follow_ups(lead["id"], sequences)
        except Exception as e:
            log.error(f"[Scheduler] Follow-up gen error for {lead['name']}: {e}")


def _is_gym(category: str, name: str) -> bool:
    cat = (category or "").lower()
    nm = (name or "").lower()
    gym_keywords = {"gym", "fit", "fitness", "crossfit", "yoga", "pilates", "studio", "boxing", "martial arts", "mma", "workout", "athletic", "ymca"}
    return any(kw in cat or kw in nm for kw in gym_keywords)


def job_auto_send_leads():
    """Find untouched leads with score > 80, auto-generate demo/draft, and send email."""
    cfg = _get_config()
    if not cfg.get("enabled") or not cfg.get("auto_send_enabled"):
        log.info("[Scheduler] Autopilot or Auto-send is disabled. Skipping auto-sending leads.")
        return

    from database import get_conn, mark_sent, get_emails_sent_today, update_business_status
    from sender import parse_subject_body, send_email
    from ai_writer import write_audit_pitch, write_no_website_pitch, BOOKING_URL
    import uuid, requests, time

    max_auto_send = cfg.get("max_auto_send", 10)
    # Enforce safe daily cold email limit to prevent spam blocking
    sent_today = get_emails_sent_today()
    if sent_today >= max_auto_send:
        log.info(f"[Scheduler] Daily auto-send limit ({max_auto_send}) reached. Skipping initial auto-sending today (already sent: {sent_today}).")
        return

    conn = get_conn()
    try:
        # Find leads > 80 score that have email
        rows = conn.execute("""
            SELECT b.*, c.email FROM businesses b
            LEFT JOIN contacts c ON c.business_id = b.id
            WHERE b.status IN ('new', 'approved') AND b.lead_score >= 25 AND c.email IS NOT NULL
            LIMIT 3
        """).fetchall()
        leads = [dict(r) for r in rows]
    finally:
        conn.close()

    if not leads:
        log.info("[Scheduler] No unsent leads in queue. Proactively triggering daily lead finder to gather new leads.")
        job_daily_find()
        return

    for lead in leads:
        log.info(f"[Scheduler] Auto-sending initial outreach to {lead['name']}")
        try:
            # Validate email address before attempting to email
            from extractor import _clean_email
            if not _clean_email(lead["email"]):
                log.info(f"  -> Skipping lead {lead['name']} because email {lead['email']} is invalid/placeholder.")
                from database import update_business_status
                update_business_status(lead["id"], "skipped")
                continue

            pitch_type = lead.get("pitch_type", "")
            is_saas_lead = (pitch_type == "leadflow_saas") or _is_gym(lead.get("category", ""), lead.get("name", ""))
            draft_text = ""
            demo_url = ""

            if is_saas_lead:
                # 1. SaaS CRM Lead: Generate custom demo page and pitch draft if not exists
                if not lead.get("demo_tunnel_url"):
                    log.info(f"  -> Building demo and draft for SaaS prospect: {lead['name']}...")
                    res = requests.post(f"http://127.0.0.1:8765/leads/{lead['id']}/generate", json={"channels": ["email"]}, timeout=180)
                    if res.status_code != 200:
                        log.error(f"  -> Failed to generate: {res.text}")
                        continue
                    # Refresh lead data to get the new demo_tunnel_url
                    conn2 = get_conn()
                    try:
                        lead = dict(conn2.execute("""
                            SELECT b.*, c.email FROM businesses b
                            LEFT JOIN contacts c ON c.business_id = b.id
                            WHERE b.id=?
                        """, (lead["id"],)).fetchone())
                    finally:
                        conn2.close()

                # Never email a dead link: confirm the demo is actually live on Pages.
                from deploy import is_live
                demo_url = lead.get("demo_tunnel_url", "")
                if demo_url and not is_live(demo_url, wait=150):
                    log.error(f"  -> Demo not live yet for {lead['name']} — skipping send this round")
                    continue

                # Get the draft
                conn2 = get_conn()
                try:
                    draft_row = conn2.execute("SELECT draft FROM outreach WHERE business_id=? AND channel='email'", (lead["id"],)).fetchone()
                    draft_text = draft_row["draft"] if draft_row else ""
                finally:
                    conn2.close()

            else:
                # 2. Web Design Lead: Send audit report (if has site) or benefits (if no site)
                has_site = bool(lead.get("website"))
                if has_site:
                    log.info(f"  -> Writing website audit pitch for {lead['name']}...")
                    draft_text = write_audit_pitch(lead, BOOKING_URL)
                else:
                    log.info(f"  -> Writing no-website benefit pitch for {lead['name']}...")
                    draft_text = write_no_website_pitch(lead, BOOKING_URL)

                # Save draft to outreach table
                conn2 = get_conn()
                try:
                    conn2.execute("DELETE FROM outreach WHERE business_id=? AND channel='email'", (lead["id"],))
                    conn2.execute("""
                        INSERT INTO outreach (business_id, channel, draft, status)
                        VALUES (?, 'email', ?, 'draft')
                    """, (lead["id"], draft_text))
                    conn2.commit()
                finally:
                    conn2.close()

            if not draft_text:
                continue

            subject, body = parse_subject_body(draft_text)
            if subject and body:
                tracking_id = str(uuid.uuid4())
                send_email(lead["email"], subject, body, tracking_id, demo_url, business_id=lead["id"])
                mark_sent(lead["id"], "email", is_autopilot=True)
                update_business_status(lead["id"], "sent")
                log.info(f"[Scheduler] Successfully sent to {lead['email']}")
                
                # Anti-spam: Add randomized human-like delay between sends
                import random
                jitter = random.randint(35, 85)
                log.info(f"  -> Sleeping for {jitter}s to avoid spam filters...")
                time.sleep(jitter)
        except Exception as e:
            log.error(f"[Scheduler] Failed to auto-send to {lead['name']}: {e}")


def job_auto_send_followups():
    """Send follow-ups that are scheduled and pending."""
    cfg = _get_config()
    if not cfg.get("enabled") or not cfg.get("auto_send_enabled"):
        log.info("[Scheduler] Autopilot or Auto-send is disabled. Skipping auto-sending followups.")
        return

    from database import get_conn, get_emails_sent_today
    from sender import parse_subject_body, send_email
    import uuid

    max_auto_send = cfg.get("max_auto_send", 10)
    # Enforce safe daily cold email limit to prevent spam blocking
    sent_today = get_emails_sent_today()
    if sent_today >= max_auto_send:
        log.info(f"[Scheduler] Daily auto-send limit ({max_auto_send}) reached. Skipping auto follow-ups today (already sent: {sent_today}).")
        return

    conn = get_conn()
    try:
        rows = conn.execute("""
            SELECT f.*, c.email, b.demo_tunnel_url FROM follow_ups f
            JOIN businesses b ON b.id = f.business_id
            LEFT JOIN contacts c ON c.business_id = b.id
            WHERE f.status = 'pending' AND f.scheduled_for <= datetime('now')
              AND b.status = 'sent'
        """).fetchall()
        follow_ups = [dict(r) for r in rows]
    finally:
        conn.close()

    for row in follow_ups:
        if not row["email"] or not row["draft"]:
            continue
        try:
            # Validate email address before sending followup
            from extractor import _clean_email
            if not _clean_email(row["email"]):
                log.info(f"  -> Skipping followup {row['id']} because email {row['email']} is invalid.")
                conn2 = get_conn()
                try:
                    conn2.execute("UPDATE follow_ups SET status='skipped' WHERE id=?", (row["id"],))
                    conn2.execute("UPDATE businesses SET status='skipped' WHERE id=?", (row["business_id"],))
                    conn2.commit()
                finally:
                    conn2.close()
                continue

            subject, body = parse_subject_body(row["draft"])
            if not subject: subject = "Quick follow-up"
            tracking_id = str(uuid.uuid4())
            send_email(row["email"], subject, body, tracking_id, row.get("demo_tunnel_url", ""), business_id=row["business_id"])
            
            conn2 = get_conn()
            try:
                conn2.execute("UPDATE follow_ups SET status='sent', sent_at=datetime('now') WHERE id=?", (row["id"],))
                conn2.commit()
            finally:
                conn2.close()
            log.info(f"[Scheduler] Auto-sent follow-up {row['sequence_num']} to {row['email']}")

            # Anti-spam: Add randomized human-like delay between sends
            import random
            jitter = random.randint(20, 60)
            log.info(f"  -> Sleeping for {jitter}s to avoid spam filters...")
            import time
            time.sleep(jitter)
        except Exception as e:
            log.error(f"[Scheduler] Failed to send followup {row['id']}: {e}")


def job_check_replies():
    """Check inbox for replies/unsubscribes and update database/cancel follow-ups."""
    from imap_sync import check_replies
    log.info("[Scheduler] Checking inbox for replies/opt-outs...")
    try:
        check_replies()
    except Exception as e:
        log.error(f"[Scheduler] IMAP reply check error: {e}")


def start_scheduler():
    """Start background scheduler. Called once on server startup."""
    cfg = _get_config()
    hour = cfg.get("run_hour", 6)

    from datetime import timezone
    now_utc = datetime.now(timezone.utc)

    # Set lead finder as a fast 10-minute interval job (runs immediately on startup)
    scheduler.add_job(job_daily_find,      "interval", minutes=10, id="daily_find",    next_run_time=now_utc, replace_existing=True)
    scheduler.add_job(job_queue_follow_ups, "cron", hour=hour, minute=30, id="queue_followups", replace_existing=True)
    scheduler.add_job(job_auto_send_leads, "interval", minutes=5, id="auto_send_leads", next_run_time=now_utc, replace_existing=True)
    scheduler.add_job(job_auto_send_followups, "interval", minutes=5, id="auto_send_followups", next_run_time=now_utc, replace_existing=True)
    scheduler.add_job(job_check_replies, "interval", minutes=5, id="check_replies", next_run_time=now_utc, replace_existing=True)

    if not scheduler.running:
        scheduler.start()
        log.info(f"[Scheduler] Started — lead finder running every 10 minutes")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)


def save_scheduler_config(niches: list, locations: list, enabled: bool, hour: int, max_per: int, source: str = "google_maps", max_score: int = 70, auto_send_enabled: bool = False, max_auto_send: int = 10):
    from database import get_conn
    conn = get_conn()
    try:
        conn.execute("DELETE FROM scheduler_config")
        conn.execute("""
            INSERT INTO scheduler_config (niches, locations, enabled, run_hour, max_per_run, source, max_score, auto_send_enabled, max_auto_send)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (json.dumps(niches), json.dumps(locations), int(enabled), hour, max_per, source, max_score, int(auto_send_enabled), max_auto_send))
        conn.commit()
    finally:
        conn.close()

    # Reschedule with new config
    scheduler.reschedule_job("daily_find", trigger="interval", minutes=10)
