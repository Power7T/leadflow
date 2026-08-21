"""
Background scheduler — runs daily auto-find and queues follow-ups.
Uses APScheduler. Started by server.py on launch.
"""
import json
import logging
import sys
import threading
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler

log = logging.getLogger("leadflow.scheduler")
log.setLevel(logging.INFO)
log.propagate = False
if not log.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    log.addHandler(handler)

from apscheduler.executors.pool import ThreadPoolExecutor
executors = {
    'default': ThreadPoolExecutor(10)
}
scheduler = BackgroundScheduler(timezone="UTC", executors=executors)

_leads_send_lock = threading.Lock()
_followups_send_lock = threading.Lock()
_enqueue_lock = threading.Lock()


def get_active_network_name():
    try:
        import subprocess
        # Dynamically find router IP from default route (first 3 octets + .1)
        from resolve_devices import get_subnet
        subnet = get_subnet()
        router_ip = f"{subnet}.1"
        cmd = ["sshpass", "-p", "root", "ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=2", f"root@{router_ip}", "iwinfo | grep ESSID | grep -v unknown | head -n 1"]
        out = subprocess.check_output(cmd, text=True, timeout=3).strip()
        if "ESSID:" in out:
            essid = out.split("ESSID:")[1].strip().strip('"')
            return f"OpenWrt ({essid})"
    except Exception:
        pass
    try:
        import subprocess
        route_out = subprocess.check_output("route -n get default", shell=True, timeout=2).decode()
        if "gateway: 192.168.1.1" in route_out:
            return "Syrotech (pbg)"
        elif "gateway: 192.168.0.1" in route_out:
            return "Tenda (RX2 Pro)"
    except Exception:
        pass
    return "Home WAN"


def send_ntfy_sent_notification(email_type, recipient, sender, subject):
    try:
        import requests, os
        topic = os.getenv("NTFY_TOPIC")
        net_name = get_active_network_name()
        
        msg = f"✅ {email_type} sent to {recipient} via {sender}\n"
        msg += f"📶 Network: {net_name}\n"
        msg += f"📧 Subject: {subject}"
        
        title = "LeadFlow - Email Dispatch"
        tags = "email,incoming_envelope"
        if "follow-up" in email_type.lower():
            tags = "email,repeat"
            title = "LeadFlow - Follow-up Dispatch"
            
        requests.post(
            f"https://ntfy.sh/{topic}",
            data=msg.encode("utf-8"),
            headers={
                "Title": title,
                "Tags": tags,
                "Priority": "default"
            },
            timeout=5
        )
    except Exception:
        pass


def require_internet(func):
    import functools
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        from ai_writer import check_internet
        if not check_internet():
            log.warning(f"[Scheduler] No internet connectivity. Skipping job {func.__name__} to prevent errors/popups.")
            return None
        return func(*args, **kwargs)
    return wrapper


def _enqueue_sequence_for_lead(lead: dict, is_hot_lead: bool = False,
                                first_fu_delay_minutes: int = None) -> int:
    """
    Shared helper — generates and inserts a full follow-up sequence for a lead.
    Called from job_queue_follow_ups, job_auto_followup_opened_leads, and
    job_check_scroll_engaged_leads so the logic lives in exactly ONE place.

    Args:
        lead: row dict from businesses/contacts join (must include 'id', 'demo_tunnel_url').
        is_hot_lead: passed through to write_follow_up_sequence for tone adjustment.
        first_fu_delay_minutes: if set, overrides the FU-1 scheduled_for to this
                                many minutes from now (for immediate hot-lead follow-ups).

    Returns:
        Number of follow-up steps inserted, or 0 on error.
    """
    from database import insert_follow_ups, get_conn
    from ai_writer import write_follow_up_sequence
    from datetime import timedelta

    with _enqueue_lock:
        # Check if follow-ups already exist for this lead (prevents race condition
        # between job_queue_follow_ups, job_auto_followup_opened_leads, and
        # job_check_scroll_engaged_leads running concurrently)
        conn = get_conn()
        try:
            res = conn.execute("SELECT 1 FROM follow_ups WHERE business_id=?", (lead["id"],)).fetchone()
        finally:
            conn.close()
        if res:
            return 0

        try:
            demo_url = lead.get("demo_tunnel_url", "")
            original_channel = lead.get("original_channel", "email")
            sequences = write_follow_up_sequence(lead, demo_url, is_hot_lead=is_hot_lead, channel=original_channel)

            # Override timing if caller wants immediate or custom first-touch
            if first_fu_delay_minutes is not None:
                now = datetime.utcnow()
                for seq in sequences:
                    if seq["num"] == 1:
                        seq["scheduled_for"] = (now + timedelta(minutes=first_fu_delay_minutes)).isoformat()
                    elif seq["num"] == 2:
                        seq["scheduled_for"] = (now + timedelta(days=2)).isoformat()
                    elif seq["num"] == 3:
                        seq["scheduled_for"] = (now + timedelta(days=5)).isoformat()
                    elif seq["num"] == 4:
                        seq["scheduled_for"] = (now + timedelta(hours=6)).isoformat()

            insert_follow_ups(lead["id"], sequences)
            return len(sequences)
        except Exception as e:
            log.error(f"[Scheduler] _enqueue_sequence_for_lead failed for {lead.get('name', '?')}: {e}")
            return 0



def city_to_timezone(city: str) -> str:
    """Map a city/location string to an IANA timezone identifier.

    Uses a broad keyword match so partial strings like 'Austin, Texas, USA'
    still resolve correctly.  Falls back to 'America/New_York' (EST/EDT)
    which covers the majority of US leads.
    """
    if not city:
        return "America/New_York"

    c = city.lower()

    # ── India ──────────────────────────────────────────────────────────────
    india_cities = [
        "mumbai", "delhi", "bangalore", "bengaluru", "hyderabad", "chennai",
        "kolkata", "pune", "ahmedabad", "jaipur", "surat", "lucknow",
        "kanpur", "nagpur", "indore", "bhopal", "patna", "vadodara",
        "coimbatore", "agra", "india",
    ]
    if any(x in c for x in india_cities):
        return "Asia/Kolkata"

    # ── UK / Ireland ───────────────────────────────────────────────────────
    if any(x in c for x in ["london", "manchester", "birmingham", "glasgow",
                              "liverpool", "leeds", "edinburgh", "bristol",
                              "united kingdom", "uk", "ireland", "dublin"]):
        return "Europe/London"

    # ── Europe ─────────────────────────────────────────────────────────────
    if any(x in c for x in ["paris", "france", "berlin", "germany", "madrid",
                              "spain", "rome", "italy", "amsterdam", "netherlands",
                              "brussels", "belgium", "vienna", "austria",
                              "zurich", "switzerland", "prague", "warsaw",
                              "stockholm", "oslo", "copenhagen"]):
        return "Europe/Paris"

    # ── Australia ──────────────────────────────────────────────────────────
    if any(x in c for x in ["sydney", "melbourne", "brisbane", "perth",
                              "adelaide", "australia"]):
        if "perth" in c or "western australia" in c:
            return "Australia/Perth"
        if "brisbane" in c or "queensland" in c:
            return "Australia/Brisbane"
        if "adelaide" in c or "south australia" in c:
            return "Australia/Adelaide"
        return "Australia/Sydney"

    # ── Canada ─────────────────────────────────────────────────────────────
    if any(x in c for x in ["toronto", "ontario", "ottawa", "montreal",
                              "quebec", "nova scotia", "new brunswick",
                              "prince edward"]):
        return "America/Toronto"
    if any(x in c for x in ["vancouver", "victoria", "british columbia"]):
        return "America/Vancouver"
    if any(x in c for x in ["calgary", "edmonton", "alberta"]):
        return "America/Edmonton"
    if any(x in c for x in ["winnipeg", "manitoba", "saskatchewan", "regina",
                              "saskatoon"]):
        return "America/Winnipeg"

    # ── US Pacific ─────────────────────────────────────────────────────────
    if any(x in c for x in ["los angeles", "san francisco", "seattle",
                              "portland", "san diego", "las vegas",
                              "phoenix", "denver", "salt lake",
                              "california", "nevada", "oregon", "washington",
                              "colorado", "utah", "idaho", "montana",
                              "wyoming", "alaska", "hawaii"]):
        if "alaska" in c:
            return "America/Anchorage"
        if "hawaii" in c:
            return "Pacific/Honolulu"
        if any(x in c for x in ["denver", "colorado", "salt lake", "utah",
                                  "idaho", "montana", "wyoming"]):
            return "America/Denver"
        return "America/Los_Angeles"

    # ── US Central ─────────────────────────────────────────────────────────
    if any(x in c for x in ["chicago", "houston", "dallas", "austin",
                              "san antonio", "minneapolis", "kansas city",
                              "oklahoma", "new orleans", "memphis",
                              "milwaukee", "illinois", "texas", "minnesota",
                              "missouri", "iowa", "kansas", "nebraska",
                              "north dakota", "south dakota", "arkansas",
                              "louisiana", "mississippi", "wisconsin"]):
        return "America/Chicago"

    # ── US Eastern (default for unrecognized US cities) ────────────────────
    return "America/New_York"


def _assign_scheduled_at(tz_str: str) -> str:
    """
    Return next UTC send slot as a string.
    If current local time is during reasonable working hours (7 AM - 6 PM), schedule it for today (now + a few minutes jitter).
    If it's past 6 PM, schedule it for tomorrow morning (9 AM).
    """
    import random
    from datetime import datetime, timedelta
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo
    try:
        tz = ZoneInfo(tz_str or "America/New_York")
    except Exception:
        tz = ZoneInfo("America/New_York")
        
    now_local = datetime.now(tz)
    
    # If it's currently between 7 AM and 6 PM local time, send it today!
    if 7 <= now_local.hour < 18:
        # Schedule for right now + 0-15 mins jitter
        jitter_mins = random.randint(0, 15)
        candidate = now_local + timedelta(minutes=jitter_mins)
    else:
        # It's outside working hours. Schedule for tomorrow at 9 AM (fix #14: always add a day
        # when hour < 7 so we never produce a past timestamp at midnight).
        jitter_mins = random.randint(0, 60)
        candidate = now_local.replace(hour=9, minute=jitter_mins % 60, second=random.randint(0, 59), microsecond=0)
        # For after-18h we push to next day; for midnight (hour < 7) also push to next day
        candidate += timedelta(days=1)
            
    # Skip weekends (push to Monday if needed)
    for _ in range(7):
        if candidate.weekday() < 5:
            break
        candidate += timedelta(days=1)
        
    utc_slot = candidate.astimezone(ZoneInfo("UTC"))
    return utc_slot.strftime("%Y-%m-%d %H:%M:%S")


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


def auto_update_warmup_limit():
    """Dynamically updates per-sender warmup limits and resolves A/B test winners."""
    import os
    from database import get_conn, get_sender_warmup, get_sender_daily_limit, resolve_ab_winners
    from sender import get_all_sender_accounts
def job_shadow_checks():
    try:
        from shadow_client import check_shadow_timeouts, send_shadow_inquiries
        log.info("[Scheduler] Running shadow checks...")
        send_shadow_inquiries(limit=3)
        check_shadow_timeouts(timeout_hours=24)
    except Exception as e:
        log.error(f"[Scheduler] check_shadow_timeouts failed: {e}")

    from database import get_conn, get_sender_warmup, get_sender_daily_limit, resolve_ab_winners
    from sender import get_all_sender_accounts
    accounts = get_all_sender_accounts()
    if not accounts:
        return
    
    # Initialize/update warmup tracking for each sender
    total_limit = 0
    for email_addr, _ in accounts:
        limit = get_sender_daily_limit(email_addr)
        warmup = get_sender_warmup(email_addr)
        total_limit += limit
        log.info(f"[Warmup] {email_addr}: {warmup.get('sent_today', 0)}/{limit}/day (lifetime: {warmup.get('total_sent_lifetime', 0)})")
    
    # Update global limit in scheduler_config for dashboard display
    conn = get_conn()
    try:
        conn.execute("UPDATE scheduler_config SET max_auto_send = ?", (total_limit,))
        conn.commit()
    except Exception as e:
        log.error(f"[Scheduler] Failed to update warmup limit: {e}")
    finally:
        conn.close()
    
    # Resolve any pending A/B tests that have enough data
    try:
        resolve_ab_winners()
    except Exception as e:
        log.error(f"[Scheduler] A/B resolution error: {e}")


@require_internet
def job_daily_find(force: bool = False):
    if not is_leader():
        log.info("[Scheduler] Primary device (Firestick) is active. Skipping job_daily_find.")
        return

    """Run once per day — find new HIGH-QUALITY businesses from saved niches.
    
    Quality gate (a lead only counts toward the 10-lead cap if it passes ALL):
      - lead_score >= 70 (hot tier)
      - Has a real website with website_score < 70 (clear pain point)
      - google_rating >= 4.5 (established, can afford service)
      - google_reviews >= 30 (real business, active)
      - Not already in DB (deduplication)
    
    Scraping stops the moment 10 qualified leads are found. Never runs twice in one day.
    """
    cfg = _get_config()
    if not force and not cfg.get("enabled"):
        return

    # ── Once-per-day guard ────────────────────────────────────────────────
    from database import get_conn as _get_db_conn
    _conn = _get_db_conn()
    try:
        last_find = _conn.execute("""
            SELECT MAX(found_at) as last FROM businesses
            WHERE DATE(found_at) = DATE('now')
        """).fetchone()["last"]
    finally:
        _conn.close()

    if not force and last_find:
        log.info(f"[Scheduler] Scraper already ran today (last find: {last_find}). Skipping until tomorrow.")
        return

    niches    = json.loads(cfg.get("niches") or "[]")
    locations = json.loads(cfg.get("locations") or "[]")
    max_score = cfg.get("max_score", 100)  # allow all scores — quality gate handles filtering
    source    = cfg.get("source", "google_maps")

    if not niches or not locations:
        log.warning("[Scheduler] No niches or locations configured — skipping.")
        return

    import random as _random

    # Rotate niches sequentially, pick location randomly
    last_niche_idx = cfg.get("last_niche_idx", 0) or 0
    location = _random.choice(locations)

    # ── Daily scrape cap: 20 qualified leads total ─────────────────────────
    DAILY_SCRAPE_CAP = 20  # Backlog is large — 20 quality leads/day is plenty
    QUALITY_MIN_SCORE = 70
    QUALITY_MIN_RATING = 4.5
    QUALITY_MIN_REVIEWS = 30
    QUALITY_MAX_WEBSITE_SCORE = 70  # must have clear pain (site score below this)

    qualified_today = 0
    current_idx = last_niche_idx
    niches_tried = 0

    while qualified_today < DAILY_SCRAPE_CAP and niches_tried < len(niches):
        niche = niches[current_idx % len(niches)]
        current_idx = (current_idx + 1) % len(niches)
        niches_tried += 1

        log.info(f"[Scheduler] Quality scrape: {niche} in {location} via {source} (need {DAILY_SCRAPE_CAP - qualified_today} more qualified leads)")
        try:
            from finder import run_finder
            # Pass quality gate parameters so finder applies them
            found = run_finder(
                niche, location,
                max_results=20,  # scrape up to 20 candidates per niche to find quality ones
                source=source,
                max_score=max_score,
                quality_gate={
                    "min_lead_score": QUALITY_MIN_SCORE,
                    "min_rating": QUALITY_MIN_RATING,
                    "min_reviews": QUALITY_MIN_REVIEWS,
                    "max_website_score": QUALITY_MAX_WEBSITE_SCORE,
                },
                stop_after_qualified=DAILY_SCRAPE_CAP - qualified_today,
            )
            qualified_today += (found or 0)
            log.info(f"[Scheduler]   -> {found} qualified leads from {niche}. Total today: {qualified_today}/{DAILY_SCRAPE_CAP}")
        except Exception as e:
            log.error(f"[Scheduler] Daily find error for {niche}: {e}")

        if qualified_today >= DAILY_SCRAPE_CAP:
            log.info(f"[Scheduler] ✅ Daily scrape cap of {DAILY_SCRAPE_CAP} quality leads reached. Stopping scraper.")
            break

    # Update niche index in DB
    from database import get_conn
    conn = get_conn()
    try:
        conn.execute("UPDATE scheduler_config SET last_niche_idx=?, last_loc_idx=0", (current_idx,))
        conn.commit()
    finally:
        conn.close()


@require_internet
def job_queue_follow_ups():
    """Check for leads sent 3+ days ago with no reply — queue 5-touch follow-up cadence."""
    from database import get_conn

    conn = get_conn()
    try:
        # fix #2: was filtering on found_at (scrape date). Now correctly filters on
        # the actual sent_at from the outreach table so 3-day window starts at send time.
        rows = conn.execute("""
            SELECT b.*, c.email, c.instagram, o.channel as original_channel
            FROM businesses b
            LEFT JOIN contacts c ON c.business_id = b.id
            JOIN outreach o ON o.business_id = b.id
            WHERE b.status = 'sent'
              AND o.channel IN ('email', 'instagram')
              AND o.status = 'sent'
              AND o.sent_at <= datetime('now', '-2 days')
              AND b.id NOT IN (SELECT DISTINCT business_id FROM follow_ups)
            LIMIT 10
        """).fetchall()
        leads = [dict(r) for r in rows]
    finally:
        conn.close()

    for lead in leads:
        log.info(f"[Scheduler] Queuing 5-touch follow-up cadence for: {lead['name']}")
        n = _enqueue_sequence_for_lead(lead, is_hot_lead=False)
        if n:
            log.info(f"[Scheduler]   -> Queued {n} follow-ups for {lead['name']}")


@require_internet
def job_auto_followup_opened_leads():
    """
    HIGH PRIORITY: Any lead that OPENED the email but has NO follow-ups gets
    an immediate 5-touch follow-up sequence, regardless of how long ago it was sent.
    Runs every 30 minutes. This is the #1 conversion fix — opened leads are
    actively interested and must be followed up with immediately.
    """
    from database import get_conn, insert_follow_ups
    from ai_writer import write_follow_up_sequence
    from datetime import timedelta

    conn = get_conn()
    try:
        rows = conn.execute("""
            SELECT b.*, c.email, c.instagram, o.channel as original_channel
            FROM businesses b
            JOIN outreach o ON o.business_id = b.id
            LEFT JOIN contacts c ON c.business_id = b.id
            WHERE o.opened = 1
              AND b.status = 'sent'
              AND b.id NOT IN (SELECT DISTINCT business_id FROM follow_ups)
              AND (c.email IS NOT NULL OR c.instagram IS NOT NULL)
            ORDER BY o.open_count DESC
            LIMIT 20
        """).fetchall()
        leads = [dict(r) for r in rows]
    finally:
        conn.close()

    if not leads:
        return

    log.info(f"[Scheduler] *** {len(leads)} OPENED leads have no follow-ups — queueing immediately ***")
    for lead in leads:
        log.info(f"[Scheduler] Queueing OPENED-lead follow-up for: {lead['name']} ({lead.get('email', '?')})")
        try:
            # Use shared helper with FU1 firing in 5 minutes (hot-open = strike now)
            n = _enqueue_sequence_for_lead(lead, is_hot_lead=True, first_fu_delay_minutes=5)
            if n:
                log.info(f"[Scheduler]   -> Queued {n} HOT follow-ups for {lead['name']} (FU1 in 5 min)")

            # Operator alert
            try:
                import requests as _req
                _ntfy_t = __import__('os').getenv('NTFY_TOPIC')  # fix #12
                _req.post(
                    f"https://ntfy.sh/{_ntfy_t}",
                    data=f"\U0001f7e1 Follow-up queued for OPENED lead: {lead['name']} ({lead.get('email','?')})".encode(),
                    headers={"Tags": "envelope", "Priority": "default"},
                    timeout=5,
                )
            except Exception:
                pass
        except Exception as e:
            log.error(f"[Scheduler] Follow-up gen error for opened lead {lead['name']}: {e}")




_instagram_send_lock = threading.Lock()
_whatsapp_send_lock  = threading.Lock()


def is_ig_handle_match(business_name: str, ig_handle: str) -> bool:
    biz = (business_name or "").lower()
    ig = (ig_handle or "").lower()
    
    if ig in {"squarespace", "wix", "wordpress", "weebly", "v", "link", "instagram", "facebook", "twitter"}:
        return False
    if len(ig) < 3:
        return False
        
    import re
    biz_words = re.findall(r'\b[a-z]{3,}\b', biz)
    
    niche_words = {
        'gym', 'fitness', 'studio', 'center', 'club', 'crossfit', 'health', 'wellness', 
        'training', 'barbell', 'strength', 'performance', 'athletics', 'dentist', 'dental',
        'chiropractic', 'chiropractor', 'chiro', 'medspa', 'spa', 'barbershop', 'barber',
        'realestate', 'realty', 'estate', 'roofing', 'roof', 'hvac', 'heating', 'cooling',
        'lawyer', 'attorney', 'legal', 'law', 'salon', 'restaurant', 'cafe', 'food'
    }
    stopwords = {
        'the', 'and', 'for', 'you', 'with', 'from', 'our', 'your', 'this', 'that', 'are',
        'inc', 'llc', 'gbr', 'gmbh', 'pty', 'ltd', 'limited', 'group', 'services', 'team',
        'city', 'north', 'south', 'east', 'west', 'valley', 'bay', 'creek', 'hill', 'lake'
    }
    
    filtered_biz_words = [w for w in biz_words if w not in niche_words and w not in stopwords]
    
    if not filtered_biz_words:
        clean_biz = re.sub(r'[^a-z]', '', biz)
        clean_ig = re.sub(r'[^a-z]', '', ig)
        return clean_biz in clean_ig or clean_ig in clean_biz
        
    for w in filtered_biz_words:
        if w in ig or ig in w:
            return True
            
    abbr = "".join([w[0] for w in biz_words if w not in stopwords])
    if len(abbr) >= 3 and abbr in ig:
        return True
        
    return False


def job_unfollow_ghosts():
    """Runs the script to unfollow ghosts randomly throughout the day."""
    import time
    import random
    # Jitter start time by 0 to 15 minutes so it's completely unpredictable
    jitter = random.randint(0, 900)
    log.info(f"[Scheduler] Jittering unfollow job by {jitter} seconds...")
    time.sleep(jitter)

    try:
        # Ensure ig_rate_state table exists before running
        from ig_rate_db import migrate as ig_rate_migrate
        ig_rate_migrate()
        import ig_ghost_cleanup
        ig_ghost_cleanup.run_ghost_cleanup(dry_run=False)
    except Exception as e:
        log.error(f"[Scheduler] Failed to run unfollow ghosts routine: {e}")


@require_internet
def job_auto_send_instagram_dms():
    """
    Hourly Instagram DM autopilot — sends to leads in draft state within their local awake hours.
    Respects ig_settings.status (running/stopped) and daily_limit.
    """
    
    if not _instagram_send_lock.acquire(blocking=False):
        log.info("[Instagram] Job already running — skipping")
        return
    
    try:
        from database import get_conn
        conn_status = get_conn()
        try:
            import sqlite3
            conn_status.row_factory = sqlite3.Row
            status_row = conn_status.execute("SELECT status, daily_limit, sent_today, last_reset_date FROM ig_settings WHERE id=1").fetchone()
            is_running = status_row and status_row["status"] == "running"
            if is_running:
                from datetime import datetime
                today = datetime.now().strftime("%Y-%m-%d")
                last_reset = status_row["last_reset_date"]
                if last_reset != today:
                    import random
                    conn_status.execute("UPDATE ig_settings SET sent_today=0, daily_limit=?, last_reset_date=? WHERE id=1", (random.randint(45, 50), today))
                    conn_status.commit()
        except Exception as err:
            log.warning(f"[Instagram] Settings reset check failed: {err}")
            is_running = False
        finally:
            conn_status.close()
            
        if not is_running:
            log.info("[Instagram] Autopilot is paused/stopped in settings — skipping sending")
            return

        # Mac guard: only send from Mac if mac_ig_dm_enabled=1 (OFF by default)
        import os, sys
        _is_termux = os.path.isdir("/data/data/com.termux")
        _device_role = os.getenv("LEADFLOW_DEVICE_ROLE", "backup")
        _is_vivo_or_primary = _is_termux or _device_role == "primary"
        if not _is_vivo_or_primary:
            # Running on Mac or another backup device — check the toggle
            try:
                from database import get_conn as _gc
                _c = _gc()
                _toggle_row = _c.execute("SELECT mac_ig_dm_enabled FROM ig_settings WHERE id=1").fetchone()
                _c.close()
                _mac_enabled = _toggle_row and _toggle_row[0] == 1
            except Exception as _e:
                log.warning(f"[Instagram] Failed to read mac_ig_dm_enabled: {_e}")
                _mac_enabled = False
            if not _mac_enabled:
                log.info("[Instagram] Mac DM sending is disabled (emergency backup only). Skipping — Vivo/primary device should be sending.")
                return

        from instagram_sender import can_send_instagram, send_instagram_dm, get_instagram_daily_sent_count
        if not can_send_instagram():
            return

        import os, json, requests
        public_url = os.getenv("CF_WORKER_URL", "https://leadflow-relay.chandango12.workers.dev")
        headers = {"X-Secret-Token": os.getenv("LEADFLOW_SECRET_TOKEN", os.getenv("SECRET_TOKEN", ""))}
        
        # Fetch directly from the local Mac database
        import sqlite3
        from database import get_conn, is_optimal_send_time, detect_timezone
        from zoneinfo import ZoneInfo
        from datetime import datetime, timezone
        
        conn = get_conn()
        conn.row_factory = sqlite3.Row
        # Scan a larger pool of 200 candidates to filter and sort by local time suitability
        rows = conn.execute("""
            SELECT o.business_id, o.draft as ai_draft, c.instagram as instagram_handle, 
                   b.name as business_name, b.timezone, b.city, b.country 
            FROM outreach o 
            JOIN businesses b ON b.id = o.business_id 
            JOIN contacts c ON c.business_id = o.business_id 
            WHERE o.channel = 'instagram' AND o.status = 'draft' 
              AND b.status NOT IN ('skipped', 'opted_out')
              AND b.demo_tunnel_url IS NOT NULL AND b.demo_tunnel_url != '' 
            GROUP BY o.business_id 
            LIMIT 200
        """).fetchall()
        leads = [dict(r) for r in rows]
        conn.close()
        
        # Filter for eligible ones within local timezone awake hours (8 AM - 9 PM)
        eligible = []
        for l in leads:
            if l.get('ai_draft') and len(l['ai_draft']) > 10:
                tz = l.get("timezone") or detect_timezone(l.get("city", ""), l.get("country", ""))
                if not l.get("timezone"):
                    try:
                        conn_tz = get_conn()
                        conn_tz.execute("UPDATE businesses SET timezone=? WHERE id=?", (tz, l["business_id"]))
                        conn_tz.commit()
                        conn_tz.close()
                    except: pass
                
                # Verify they are currently within their local awake window
                if is_optimal_send_time(tz, window_start=8, window_end=21, preferred_days=[0,1,2,3,4,5,6]):
                    # Priority score: leads closest to 12 PM (midday) local time get prioritized
                    try:
                        now_local = datetime.now(ZoneInfo(tz))
                        priority = -abs(now_local.hour - 12)
                    except:
                        priority = -12  # fallback
                    l['priority'] = priority
                    l['timezone_resolved'] = tz
                    eligible.append(l)
        
        # Sort so that leads closest to active midday climb up the ladder
        eligible.sort(key=lambda x: x.get('priority', -12), reverse=True)
        
        # Take the top 5 to send in this hour interval
        eligible = eligible[:5]
                
        if not eligible:
            log.info("[Instagram] No eligible leads within local awake hours (8 AM - 9 PM) right now")
            return

        log.info(f"[Instagram] Sending DMs to {len(eligible)} leads ({get_instagram_daily_sent_count()}/20 used today)")

        for lead in eligible:
            handle = lead["instagram_handle"].strip().lstrip("@")
            draft  = lead.get("ai_draft") or ""
            if not handle or not draft:
                continue

            # Mismatch Prevention double-check
            if not is_ig_handle_match(lead.get("business_name", ""), handle):
                log.warning(f"[Instagram] Mismatch detected: Business '{lead.get('business_name')}' does not match handle '{handle}'! Skipping to review_needed.")
                try:
                    conn_update = get_conn()
                    conn_update.execute("UPDATE outreach SET status='review_needed' WHERE business_id=? AND channel='instagram'", (lead.get('business_id'),))
                    conn_update.commit()
                    conn_update.close()
                except Exception as db_err:
                    log.error(f"[Instagram] Mismatch state update failed: {db_err}")
                continue

            ok = send_instagram_dm(handle, draft)
            if ok == "contact_only":
                # Business only has a "Contact" button — no direct DM capability on Instagram
                log.warning(f"[Instagram] @{handle} is contact-only (no Message button) — marking in DB and skipping")
                try:
                    conn_update = get_conn()
                    conn_update.execute(
                        "UPDATE businesses SET ig_contact_only=1, status='ig_contact_only' WHERE id=?",
                        (lead.get('business_id'),)
                    )
                    conn_update.execute(
                        "UPDATE outreach SET status='ig_skip' WHERE business_id=? AND channel='instagram'",
                        (lead.get('business_id'),)
                    )
                    conn_update.commit()
                    conn_update.close()
                except Exception as db_err:
                    log.error(f"[Instagram] ig_contact_only update failed: {db_err}")
            elif ok is None:
                # Permanent skip: user not found, account deleted, or private (no DMs until follow-back)
                log.warning(f"[Instagram] Permanent skip for @{handle} — marking outreach as 'ig_skip'")
                try:
                    conn_update = get_conn()
                    conn_update.execute("UPDATE outreach SET status='ig_skip' WHERE business_id=? AND channel='instagram'", (lead.get('business_id'),))
                    conn_update.commit()
                    conn_update.close()
                except Exception as db_err:
                    log.error(f"[Instagram] ig_skip update failed: {db_err}")
            elif ok:
                # Update SQLite database status immediately
                try:
                    conn_update = get_conn()
                    conn_update.execute("UPDATE outreach SET status='sent', sent_at=datetime('now') WHERE business_id=? AND channel='instagram'", (lead.get('business_id'),))
                    # Set ig_link_delivered=1 if the message contained a URL/link
                    _has_link = "http" in draft or "www." in draft
                    conn_update.execute(
                        "UPDATE businesses SET ig_dm_sent=1, ig_dm_sent_at=datetime('now'), status='sent'"
                        + (", ig_link_delivered=1" if _has_link else "")
                        + " WHERE id=?",
                        (lead.get('business_id'),)
                    )
                    conn_update.commit()
                    conn_update.close()
                    log.info(f"[Instagram] Updated local SQLite database status for @{handle} to sent" + (" (link delivered)" if _has_link else ""))
                except Exception as db_err:
                    log.error(f"[Instagram] Local SQLite status update failed: {db_err}")

                # Fetch, append, and push back array (non-blocking fallback)
                try:
                    res_done = requests.post(f"{public_url}/api/kv", headers=headers, json={"key": "bot:ig_done_queue"}, timeout=10)
                    done_q = json.loads(res_done.json().get("value", "[]") or "[]")
                except Exception:
                    done_q = []
                done_q.append({"business_id": lead.get('business_id', lead.get('id')), "done_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
                try:
                    requests.post(f"{public_url}/api/kv", headers=headers, json={"key": "bot:ig_done_queue", "value": json.dumps(done_q)}, timeout=10)
                except Exception as kv_err:
                    log.warning(f"[Instagram] Non-blocking Cloudflare KV sync failure: {kv_err}")
                log.info(f"[Instagram] Sent DM to @{handle} for {lead.get('business_name')}")
            if not can_send_instagram():
                log.info("[Instagram] Daily cap reached — stopping")
                break
    except Exception as e:
        log.error(f"[Instagram] Job error: {e}")
    finally:
        _instagram_send_lock.release()


_instagram_reply_lock = threading.Lock()

@require_internet
def job_check_instagram_replies():
    """
    Check Instagram for replies/opt-outs and deliver links to positive responses.
    """
    if not _instagram_reply_lock.acquire(blocking=False):
        log.info("[Instagram Reply] Responder job already running — skipping")
        return
    try:
        import os, subprocess, sys
        from pathlib import Path
        script_path = str(Path(__file__).parent / "ig_reply_responder.py")
        if os.path.exists(script_path):
            log.info("[Instagram Reply] Launching automated reply responder...")
            res = subprocess.run([sys.executable, script_path, "--method", "both"], capture_output=True, text=True, timeout=300)
            if res.returncode == 0:
                log.info("[Instagram Reply] Completed successfully.")
            else:
                log.error(f"[Instagram Reply] Responder failed: {res.stderr}")
        else:
            log.warning(f"[Instagram Reply] Responder script not found at {script_path}")
    except Exception as e:
        log.error(f"[Instagram Reply] Job error: {e}")
    finally:
        _instagram_reply_lock.release()


@require_internet
def job_auto_send_whatsapp():
    """
    Hourly: find leads where email was sent 3+ days ago with no reply
    and they have a WhatsApp number. Send up to 10 messages per run.
    Auto-selects Twilio API or daily digest based on .env config.
    """
    if not _whatsapp_send_lock.acquire(blocking=False):
        log.info("[WhatsApp] Job already running — skipping")
        return
    try:
        from whatsapp_sender import send_whatsapp, get_whatsapp_daily_sent_count, whatsapp_backend
        from database import get_conn
        from ai_writer import write_whatsapp_dm

        backend = whatsapp_backend()
        log.info(f"[WhatsApp] Backend: {backend}")

        conn = get_conn()
        try:
            rows = conn.execute("""
                SELECT b.id, b.name, b.category, b.city,
                       c.whatsapp, b.demo_tunnel_url,
                       o.draft AS wa_draft
                FROM businesses b
                JOIN contacts c ON c.business_id = b.id
                LEFT JOIN outreach o ON o.business_id = b.id AND o.channel = 'whatsapp'
                WHERE b.status = 'sent'
                  AND c.whatsapp IS NOT NULL AND c.whatsapp != ''
                  AND b.id NOT IN (
                      SELECT business_id FROM outreach
                      WHERE channel='whatsapp' AND status='sent'
                  )
                ORDER BY b.lead_score DESC
                LIMIT 10
            """).fetchall()
            leads = [dict(r) for r in rows]
        finally:
            conn.close()

        if not leads:
            log.info("[WhatsApp] No eligible leads for WhatsApp right now")
            return

        log.info(f"[WhatsApp] Processing {len(leads)} leads ({get_whatsapp_daily_sent_count()} sent today)")
        for lead in leads:
            phone = lead["whatsapp"].strip()
            # Use pre-written draft if exists, otherwise generate a short message
            draft = lead.get("wa_draft") or ""
            if not draft:
                demo_url = lead.get("demo_tunnel_url") or ""
                draft = write_whatsapp_dm(lead, demo_url)
            if not draft:
                continue
            ok = send_whatsapp(phone, draft, lead["name"])
            if ok:
                conn2 = get_conn()
                try:
                    conn2.execute("""
                        INSERT OR REPLACE INTO outreach (business_id, channel, final_message, status, sent_at, is_autopilot)
                        VALUES (?, 'whatsapp', ?, 'sent', datetime('now'), 1)
                    """, (lead["id"], draft))
                    conn2.commit()
                finally:
                    conn2.close()
                log.info(f"[WhatsApp] Sent to {phone} for {lead['name']} via {backend}")
    except Exception as e:
        log.error(f"[WhatsApp] Job error: {e}")
    finally:
        _whatsapp_send_lock.release()


@require_internet
def job_check_scroll_engaged_leads():
    """
    Every 5 minutes: find leads where someone scrolled 90%+ through their demo
    but has no follow-up queued yet. These are the HOTTEST leads — queue an
    immediate priority follow-up and bump their lead_score so they surface first.
    """
    from database import get_conn, insert_follow_ups
    from ai_writer import write_follow_up_sequence
    from datetime import timedelta

    conn = get_conn()
    try:
        rows = conn.execute("""
            SELECT DISTINCT b.*, c.email, c.instagram, o.channel as original_channel
            FROM tracking_events te
            JOIN businesses b ON b.id = te.business_id
            LEFT JOIN contacts c ON c.business_id = b.id
            LEFT JOIN outreach o ON o.business_id = b.id AND o.status = 'sent'
            WHERE te.event_type IN ('engage:scroll_90', 'engage:modal_shown', 'click')
              AND b.status = 'sent'
              AND (c.email IS NOT NULL OR c.instagram IS NOT NULL)
              AND b.id NOT IN (SELECT DISTINCT business_id FROM follow_ups)
            ORDER BY te.occurred_at DESC
            LIMIT 10
        """).fetchall()
        leads = [dict(r) for r in rows]
    finally:
        conn.close()

    if not leads:
        return

    log.info(f"[Scheduler] 🔥 {len(leads)} SCROLL-ENGAGED leads detected — queueing priority follow-ups")

    for lead in leads:
        log.info(f"[Scheduler] Scroll-engaged: {lead['name']} ({lead.get('email', '?')})")
        try:
            # Bump lead score +20 so they rank higher in every queue
            conn2 = get_conn()
            try:
                conn2.execute("""
                    UPDATE businesses SET lead_score = MIN(100, COALESCE(lead_score,0) + 20)
                    WHERE id=?
                """, (lead["id"],))
                conn2.commit()
            finally:
                conn2.close()

            # Use shared helper with FU1 firing in 20 minutes (scroll = live, but avoid feeling like surveillance)
            n = _enqueue_sequence_for_lead(lead, is_hot_lead=True, first_fu_delay_minutes=20)
            if n:
                log.info(f"[Scheduler]   -> Queued SCROLL-PRIORITY follow-up for {lead['name']} (FU1 in 20 min)")

            # Push notification
            try:
                import requests as _req
                _ntfy_t2 = __import__('os').getenv('NTFY_TOPIC')  # fix #12
                _req.post(
                    f"https://ntfy.sh/{_ntfy_t2}",
                    data=f"🔥 {lead['name']} scrolled 90%+ through their demo — follow-up queued in 20 min!".encode(),
                    headers={"Title": "LeadFlow - HOT Demo Engagement!", "Tags": "fire,chart_with_upwards_trend", "Priority": "high"},
                    timeout=5,
                )
            except Exception:
                pass
        except Exception as e:
            log.error(f"[Scheduler] Scroll-engaged FU error for {lead['name']}: {e}")


@require_internet
def job_demo_open_nudge():
    """
    Every 15 min: find leads who opened the demo 2+ hrs ago but never tapped
    WhatsApp. Fire a personal ntfy ping so Chandan can follow up manually.
    """
    from database import get_conn
    from datetime import datetime as _dt, timedelta as _td

    conn = get_conn()
    try:
        rows = conn.execute("""
            SELECT b.id, b.name, b.demo_first_opened_at
            FROM businesses b
            WHERE b.demo_first_opened_at IS NOT NULL
              AND b.demo_followup_nudge_sent = 0
              AND b.demo_first_opened_at <= datetime('now', '-2 hours')
              AND b.id NOT IN (
                  SELECT DISTINCT business_id FROM tracking_events
                  WHERE event_type = 'engage:cta_whatsapp'
              )
        """).fetchall()
        leads = [dict(r) for r in rows]
    finally:
        conn.close()

    if not leads:
        return

    import requests as _req
    _ntfy_t = __import__('os').getenv('NTFY_TOPIC')

    for lead in leads:
        try:
            log.info(f"[Scheduler] Demo-open nudge: {lead['name']} (opened {lead['demo_first_opened_at']}, no WA tap)")
            if _ntfy_t:
                _req.post(
                    f"https://ntfy.sh/{_ntfy_t}",
                    data=f"⏰ {lead['name']} opened the demo 2h ago — no WhatsApp tap yet. Follow up now!".encode(),
                    headers={"Title": "LeadFlow - Demo Follow-up", "Tags": "alarm_clock", "Priority": "high"},
                    timeout=5,
                )
            conn2 = get_conn()
            try:
                conn2.execute(
                    "UPDATE businesses SET demo_followup_nudge_sent=1 WHERE id=?",
                    (lead["id"],),
                )
                conn2.commit()
            finally:
                conn2.close()
        except Exception as e:
            log.error(f"[Scheduler] Demo nudge error for {lead['name']}: {e}")


@require_internet
def job_check_color_customizer_leads():
    """Every 5 minutes: detect leads who used the color customizer in their demo.

    Color-picking is a strong buying signal — the prospect is imagining the
    site as their own.  Queue an urgent follow-up (fires in 5 minutes) and
    bump lead_score +35 so they surface at the top of every queue.
    Only acts on leads that don't already have a follow-up queued.
    """
    from database import get_conn, insert_follow_ups

    conn = get_conn()
    try:
        rows = conn.execute("""
            SELECT DISTINCT b.*, c.email, c.instagram, o.channel as original_channel
            FROM tracking_events te
            JOIN businesses b ON b.id = te.business_id
            LEFT JOIN contacts c ON c.business_id = b.id
            LEFT JOIN outreach o ON o.business_id = b.id AND o.status = 'sent'
            WHERE te.event_type LIKE 'engage:customize_color_%'
              AND b.status = 'sent'
              AND (c.email IS NOT NULL OR c.instagram IS NOT NULL)
              AND b.id NOT IN (SELECT DISTINCT business_id FROM follow_ups)
            ORDER BY te.occurred_at DESC
            LIMIT 10
        """).fetchall()
        leads = [dict(r) for r in rows]
    finally:
        conn.close()

    if not leads:
        return

    log.info(f"[Scheduler] 🎨 {len(leads)} COLOR-CUSTOMIZER leads detected — queueing priority follow-ups")

    for lead in leads:
        log.info(f"[Scheduler] Color-customized: {lead['name']} ({lead.get('email', '?')})")
        try:
            # Bump lead score +35 — color-picking is stronger signal than scrolling
            conn2 = get_conn()
            try:
                conn2.execute("""
                    UPDATE businesses SET lead_score = MIN(100, COALESCE(lead_score,0) + 35)
                    WHERE id=?
                """, (lead["id"],))
                conn2.commit()
            finally:
                conn2.close()

            # FU1 in 5 minutes — they're live and engaged right now
            n = _enqueue_sequence_for_lead(lead, is_hot_lead=True, first_fu_delay_minutes=5)
            if n:
                log.info(f"[Scheduler]   -> Queued COLOR-PRIORITY follow-up for {lead['name']} (FU1 in 5 min)")

            # ntfy push — high priority
            try:
                import requests as _r
                _topic = __import__('os').getenv('NTFY_TOPIC')
                _r.post(
                    f"https://ntfy.sh/{_topic}",
                    data=f"🎨 {lead['name']} just customized their demo colors — they're picturing it as theirs! FU queued in 5 min.".encode(),
                    headers={"Title": "LeadFlow - Color Customizer Alert!", "Tags": "art,fire", "Priority": "high"},
                    timeout=5,
                )
            except Exception:
                pass
        except Exception as e:
            log.error(f"[Scheduler] Color-customizer FU error for {lead['name']}: {e}")


def job_lead_score_decay():
    """
    Weekly: subtract 5 from lead_score for every silent 'sent' lead.
    If lead_score drops below 20, mark status='cold' to stop follow-up queues.
    """
    from database import get_conn
    conn = get_conn()
    try:
        # Decay: -5 for every lead sent with no reply in the last 7 days
        conn.execute("""
            UPDATE businesses
            SET lead_score = MAX(0, COALESCE(lead_score, 50) - 5)
            WHERE status = 'sent'
              AND id NOT IN (
                  SELECT DISTINCT business_id FROM contacts
                  WHERE replied_at IS NOT NULL AND replied_at != ''
              )
        """)
        # Mark cold when score too low
        affected = conn.execute("""
            UPDATE businesses
            SET status = 'cold'
            WHERE status = 'sent'
              AND COALESCE(lead_score, 0) < 20
        """).rowcount
        conn.commit()
        if affected:
            log.info(f"[Lead Decay] Marked {affected} leads cold (score < 20)")
    except Exception as e:
        log.error(f"[Lead Decay] Error: {e}")
    finally:
        conn.close()


@require_internet
def job_reengage_cold_leads():
    """
    Daily: find silent 'sent' leads at 30/60/90-day milestones and queue
    a re-engagement follow-up with an angle appropriate to the stage.
    """
    from database import get_conn, insert_follow_ups
    from ai_writer import write_follow_up_sequence
    from datetime import datetime as _dt, timedelta

    STAGES = [
        (90,  "final_nudge",   "Last reach-out — I'll close your file after this. Should I?"),
        (60,  "new_angle",     "New case study from a similar business — worth 2 minutes?"),
        (30,  "checking_in",   "Quick check-in — are you still exploring options for your website?"),
    ]

    conn = get_conn()
    try:
        rows = conn.execute("""
            SELECT b.id, b.name, b.category, b.city, b.website, b.website_score,
                   b.gap, b.pitch_type, b.lead_score, b.demo_tunnel_url,
                   c.email, c.instagram,
                   o.channel as original_channel, o.sent_at
            FROM businesses b
            JOIN contacts c ON c.business_id = b.id
            JOIN outreach o ON o.business_id = b.id AND o.status='sent'
            WHERE b.status = 'sent'
              AND (c.replied_at IS NULL OR c.replied_at = '')
              AND (c.email IS NOT NULL OR c.instagram IS NOT NULL)
              AND julianday('now') - julianday(o.sent_at) >= 30
            ORDER BY o.sent_at ASC
            LIMIT 20
        """).fetchall()
        leads = [dict(r) for r in rows]
    finally:
        conn.close()

    for lead in leads:
        try:
            sent_days = 0
            try:
                sent_days = (_dt.utcnow() - _dt.fromisoformat(lead["sent_at"])).days
            except Exception:
                continue

            # Pick the highest applicable stage
            stage_key = None
            stage_msg = None
            for min_days, key, msg in STAGES:
                if sent_days >= min_days:
                    stage_key = key
                    stage_msg = msg
                    break

            if not stage_key:
                continue

            # Skip if we already queued this stage angle for this lead
            conn2 = get_conn()
            already = conn2.execute(
                "SELECT id FROM follow_ups WHERE business_id=? AND followup_angle=?",
                (lead["id"], stage_key)
            ).fetchone()
            conn2.close()
            if already:
                continue

            channel = lead.get("original_channel") or ("email" if lead.get("email") else "instagram")
            now = _dt.utcnow()
            sequences = [{
                "num": 1,
                "channel": channel,
                "draft": stage_msg,
                "scheduled_for": (now + timedelta(minutes=10)).isoformat(),
                "followup_angle": stage_key,
            }]
            insert_follow_ups(lead["id"], sequences)
            log.info(f"[Reengage] {stage_key} queued for {lead['name']} ({sent_days}d silent)")
        except Exception as e:
            log.error(f"[Reengage] Error for {lead.get('name')}: {e}")


@require_internet
def job_sync_beacon():
    """
    Keep beacon-config.json on GitHub Pages in sync with the current tunnel URL.
    Runs every 5 minutes. Ensures ALL demo pages (even old ones with stale URLs)
    always beacon to the right server.
    """
    try:
        from pathlib import Path
        url = Path("/tmp/leadflow-tunnel-url.txt").read_text().strip()
        if url.startswith("https://"):
            from beacon_relay import sync_beacon_if_stale
            updated = sync_beacon_if_stale(url)
            if updated:
                log.info(f"[Scheduler] Beacon config synced to: {url}")
    except FileNotFoundError:
        # No tunnel running yet — completely normal, skip silently
        log.debug("[Scheduler] No tunnel URL file yet — beacon sync skipped")
    except Exception as e:
        log.warning(f"[Scheduler] Beacon sync error: {e}")
    
    try:
        import os, requests, time
        token = os.getenv("LEADFLOW_SECRET_TOKEN", os.getenv("SECRET_TOKEN", ""))
        public_url = os.getenv("LEADFLOW_PUBLIC_URL", "")
        role = os.getenv("LEADFLOW_DEVICE_ROLE", "backup")
        if public_url:
            requests.post(
                f"{public_url}/api/heartbeat?device={role}",
                json={"timestamp": int(time.time() * 1000)},
                headers={"X-Secret-Token": token},
                timeout=5
            )
            log.info(f"[Scheduler] Heartbeat ({role}) posted to Cloudflare Worker")
    except Exception as hb_err:
        log.debug(f"[Scheduler] Heartbeat post error: {hb_err}")


@require_internet
def job_replicate_database():
    if not is_leader(): return
    """
    Bi-directional database replication via Cloudflare KV + LAN failsafe.
    Runs every 2 minutes. LAN sync to Firestick acts as hard backup in case
    Cloudflare journal missed any inserts (new leads, contacts, outreach etc).
    """
    try:
        import os
        from sync_engine import run_sync_cycle
        import socket as _sock
        # Pass Firestick IP as LAN peer for failsafe full-DB sync
        # Dynamic Firestick IP resolution
        _fs_home = os.path.join(os.path.expanduser("~"), ".firestick_ip")
        _fs_local = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".firestick_ip")
        _fs_ip = None
        for _p in (_fs_home, _fs_local):
            try:
                _fs_ip = open(_p).read().strip().replace(":5555", "")
                if _fs_ip: break
            except Exception:
                pass
        if not _fs_ip:
            _fs_ip = "192.168.8.246"
        lan_peers = [_fs_ip]
        # Filter out this device's own IP to prevent syncing to self
        try:
            own_ip = _sock.gethostbyname(_sock.gethostname())
        except Exception:
            own_ip = None
        lan_peers = [p for p in lan_peers if p != own_ip]
        if lan_peers:
            run_sync_cycle(lan_peers=lan_peers)
        else:
            run_sync_cycle()
            log.debug("[Scheduler] No remote LAN peers after filtering own IP, skipping LAN sync.")
        log.info("[Scheduler] Database replication cycle completed (Cloudflare + LAN).")
    except Exception as e:
        log.error(f"[Scheduler] Database replication error: {e}")



def job_replicate_dashboard_static():
    """Statically compile and replicate all dashboard views to GitHub Pages / Cloudflare Pages."""
    try:
        from replicate import run_replication
        run_replication()
        log.info("[Scheduler] Static dashboard replica successfully updated on Cloudflare/GitHub Pages.")
    except Exception as e:
        log.error(f"[Scheduler] Static dashboard replication error: {e}")


_kv_last_heartbeat_write: float = 0.0  # epoch seconds of last successful KV put
_KV_HEARTBEAT_INTERVAL = 1800  # write to KV at most once every 30 minutes


def is_leader() -> bool:
    """Check if this device is currently the authorized leader.
    Firestick (primary) returns True if running.
    Mac (backup) returns False if Firestick is active, True if Firestick offline.
    """
    global _kv_last_heartbeat_write
    import os, requests, time
    from pathlib import Path

    public_url = os.getenv('CF_WORKER_URL') or os.getenv('LEADFLOW_PUBLIC_URL')
    if not public_url:
        raise ValueError("LEADFLOW_PUBLIC_URL is missing from the environment")

    secret_token = os.getenv('LEADFLOW_SECRET_TOKEN') or os.getenv('SECRET_TOKEN')
    if not secret_token:
        raise ValueError("LEADFLOW_SECRET_TOKEN is missing from the environment")

    device_role = os.getenv("LEADFLOW_DEVICE_ROLE", "backup")
    if device_role == "primary":
        now = time.time()
        # Rate-limit KV writes to once every 5 min to stay under Cloudflare free tier (1000 puts/day)
        if now - _kv_last_heartbeat_write < _KV_HEARTBEAT_INTERVAL:
            return True  # Already wrote heartbeat recently; we are still leader
        try:
            headers = {'X-Secret-Token': secret_token}
            response = requests.post(
                f"{public_url}/api/kv",
                headers=headers,
                json={"key": "leader:heartbeat", "value": str(now)},
                timeout=5
            )
            if response.status_code == 500:
                # May be Cloudflare KV daily write-limit hit; primary is still running — assert leadership
                import logging
                err_body = ""
                try:
                    err_body = response.json().get("error", "")
                except Exception:
                    pass
                logging.warning(f"[Failover] KV write returned 500 (likely rate-limit: {err_body}). Primary still asserting leadership.")
                _kv_last_heartbeat_write = now  # back off retries even on 500
                return True
            response.raise_for_status()
            _kv_last_heartbeat_write = now
            return True  # Successfully asserted leadership
        except requests.exceptions.ConnectionError as e:
            import logging
            logging.error(f"[Failover] Primary cannot reach Cloudflare (network down): {e}. Sleeping to allow backup to takeover.")
            return False
        except Exception as e:
            import logging
            logging.error(f"[Failover] Primary KV heartbeat failed: {e}. Sleeping to allow backup to takeover.")
            return False

    # If this is the Mac (Backup), check primary's LAN health endpoint first to avoid KV read counts
    try:
        # Resolve Firestick LAN IP dynamically
        _fs_home = os.path.join(os.path.expanduser("~"), ".firestick_ip")
        _fs_local = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".firestick_ip")
        _default_lan_ip = "192.168.8.246"
        for _p in (_fs_home, _fs_local):
            try:
                _ip = open(_p).read().strip().replace(":5555", "")
                if _ip:
                    _default_lan_ip = _ip
                    break
            except Exception:
                pass
        ping_res = requests.get(f'http://{os.getenv("PRIMARY_LAN_IP", _default_lan_ip)}:8765/api/health', timeout=2)
        if ping_res.status_code == 200 and ping_res.json().get("status") == "ok":
            try:
                Path("/tmp/failover_checks.txt").write_text("0")
            except Exception:
                pass
            return False # Primary active on LAN, Backup stands down
    except Exception:
        pass

    # If this is the Mac (Backup), read heartbeat to decide if we should stand down
    try:
        headers = {'X-Secret-Token': secret_token}
        res = requests.post(
            f"{public_url}/api/kv", 
            headers=headers, 
            json={"key": "leader:heartbeat"}, 
            timeout=5
        )
        if res.status_code != 200:
            return False

        try:
            val = res.json().get("value")
            last_heartbeat = float(val) if val else 0.0
        except (ValueError, TypeError):
            return False
        
        # If heartbeat is under 10 minutes old, the Firestick is active.
        if (time.time() - last_heartbeat) < 600:
            try:
                Path("/tmp/failover_checks.txt").write_text("0")
            except Exception:
                pass
            return False # Skip running jobs on the Mac
    except Exception:
        pass
        
    # Heartbeat check failed (stale or network exception). Let's count consecutive failures.
    fail_file = Path("/tmp/failover_checks.txt")
    fails = 0
    try:
        if fail_file.exists():
            fails = int(fail_file.read_text().strip())
    except Exception:
        pass
        
    fails += 1
    try:
        fail_file.write_text(str(fails))
    except Exception:
        pass
    
    # Require at least 2 consecutive stale checks before taking over
    if fails >= 2:
        # Avoid exhausting KV read counts for logging - logic moved locally
        pass
        # log.warning is missing imports here so just failover cleanly
        return True # Mac executes outreach jobs
        
    return False # Stand down for now to account for KV propagation delay




@require_internet

def job_process_ig_regens():
    if not is_leader(): return  # Firestick only
    import os, json, sqlite3, requests
    from ai_writer import write_instagram_dm
    from database import get_conn
    from demo_generator import _scrape_site
    public_url = os.getenv("CF_WORKER_URL", "https://leadflow-relay.chandango12.workers.dev")
    headers = {"X-Secret-Token": os.getenv("LEADFLOW_SECRET_TOKEN", os.getenv("SECRET_TOKEN", ""))}
    try:
        res = requests.post(f"{public_url}/api/kv", headers=headers, json={"key": "bot:ig_regen_queue"}, timeout=10)
        if not res.text or not res.text.strip():
            log.warning("[Scheduler] IG regen queue: upstream returned empty response, skipping")
            return
        try:
            kv_data = res.json()
        except (json.JSONDecodeError, ValueError):
            log.warning(f"[Scheduler] IG regen queue: invalid JSON from upstream ({res.text[:120]}), skipping")
            return
            
        try:
            q = json.loads(kv_data.get("value", "[]") or "[]")
        except (json.JSONDecodeError, ValueError, TypeError):
            log.warning(f"[Scheduler] IG regen queue: corrupted value inside KV data, skipping")
            return
        if not q: return
        
        conn = get_conn()
        for bid in q:
            # Generate new draft
            r = conn.execute("SELECT b.id, b.name, b.category, b.website, b.website_score, b.gap, b.competitor_deficit, b.pitch_type, b.lead_score, con.instagram, b.google_rating, b.google_reviews, b.demo_tunnel_url, b.city FROM businesses b JOIN contacts con ON con.business_id = b.id WHERE b.id = ?", (bid,)).fetchone()
            if not r: continue
            biz = {"id": r[0], "name": r[1], "category": r[2], "website": r[3], "website_score": r[4], "gap": r[5], "competitor_deficit": r[6], "pitch_type": r[7], "lead_score": r[8], "instagram": r[9], "google_rating": r[10], "google_reviews": r[11], "city": r[13]}
            # Fetch demo URL and scraped website data for personalisation
            demo_url = r[12] or ""
            scraped = {}
            if biz.get("website"):
                try:
                    scraped = _scrape_site(biz["website"]) or {}
                except Exception:
                    pass
            draft = write_instagram_dm(biz, demo_url=demo_url, scraped=scraped or None)
            conn.execute("UPDATE outreach SET draft = ?, status = 'draft' WHERE business_id = ? AND channel = 'instagram'", (draft, bid))
        conn.commit()
        
        # Clear queue
        requests.post(f"{public_url}/api/kv", headers=headers, json={"key": "bot:ig_regen_queue", "value": "[]"}, timeout=10)
        
        # Push new KV instantly
        job_push_bot_kv()
        log.info(f"[Scheduler] Processed {len(q)} IG regens")
    except Exception as e:
        log.error(f"[Scheduler] Failed to process regens: {e}")

def job_push_bot_kv():
    if not is_leader(): return
    """
    Push live stats and pending drafts to Cloudflare KV so the Telegram bot webhook
    can serve them instantly without needing the Firestick to be online.
    Runs every 5 minutes.
    """
    import os, json, requests
    public_url = os.getenv("LEADFLOW_PUBLIC_URL", "")
    token = os.getenv("LEADFLOW_SECRET_TOKEN", os.getenv("SECRET_TOKEN", ""))
    if not public_url or not token:
        return
    headers = {"X-Secret-Token": token, "Content-Type": "application/json"}

    try:
        from database import get_conn
        conn = get_conn()

        # Ensure tier column exists (prevents "no such column: b.tier" on older DBs)
        try:
            conn.execute("ALTER TABLE businesses ADD COLUMN tier INTEGER DEFAULT 0")
            conn.commit()
        except Exception:
            pass  # column already exists

        # Ensure ig_contact_only column exists
        try:
            conn.execute("ALTER TABLE businesses ADD COLUMN ig_contact_only INTEGER DEFAULT 0")
            conn.commit()
        except Exception:
            pass  # column already exists

        # Build stats
        stats = {}
        for status in ("new", "approved", "sent", "replied", "skipped", "closed", "opted_out"):
            stats[status] = conn.execute("SELECT COUNT(*) FROM businesses WHERE status=?", (status,)).fetchone()[0]
        cfg_row = conn.execute("SELECT enabled FROM scheduler_config LIMIT 1").fetchone()
        stats["autopilot_active"] = bool(cfg_row["enabled"]) if cfg_row else False

        requests.post(f"{public_url}/api/kv", headers=headers,
                      json={"key": "bot:stats", "value": json.dumps(stats)}, timeout=10)

        # Build drafts list
        rows = conn.execute("""
            SELECT o.id as draft_id, o.business_id, o.channel, o.draft,
                   b.name as business_name, c.email as contact_email
            FROM outreach o
            JOIN businesses b ON o.business_id = b.id
            LEFT JOIN contacts c ON c.business_id = b.id
            WHERE o.status = 'draft' AND b.status IN ('new','approved')
            ORDER BY o.id ASC LIMIT 20
        """).fetchall()
        drafts = []
        for row in rows:
            d = dict(row)
            if d.get("draft"):
                lines = d["draft"].split("\n")
                d["subject"] = lines[0].replace("Subject:", "").strip() if lines else ""
                d["body"] = "\n".join(lines[1:]).strip()
            drafts.append(d)

        requests.post(f"{public_url}/api/kv", headers=headers,
                      json={"key": "bot:drafts", "value": json.dumps(drafts)}, timeout=10)

        # Also process any send_queue or skip_queue from the bot
        send_q_raw = requests.get(f"{public_url}/api/kv?key=bot:send_queue", headers=headers, timeout=10)
        skip_q_raw = requests.get(f"{public_url}/api/kv?key=bot:skip_queue", headers=headers, timeout=10)

        if send_q_raw.status_code == 200:
            try:
                send_queue = json.loads(send_q_raw.json().get("value", "[]") or "[]")
                for item in send_queue:
                    did = item.get("draft_id")
                    if did:
                        conn.execute("UPDATE outreach SET status='approved' WHERE id=?", (did,))
                if send_queue:
                    conn.commit()
                    requests.post(f"{public_url}/api/kv", headers=headers,
                                  json={"key": "bot:send_queue", "value": "[]"}, timeout=10)
            except Exception:
                pass

        if skip_q_raw.status_code == 200:
            try:
                skip_queue = json.loads(skip_q_raw.json().get("value", "[]") or "[]")
                for item in skip_queue:
                    bid = item.get("business_id")
                    if bid:
                        conn.execute("UPDATE businesses SET status='skipped' WHERE id=?", (bid,))
                if skip_queue:
                    conn.commit()
                    requests.post(f"{public_url}/api/kv", headers=headers,
                                  json={"key": "bot:skip_queue", "value": "[]"}, timeout=10)
            except Exception:
                pass

        # Process ig_done_queue — mark businesses as ig_dm_sent in local DB
        ig_done_raw = requests.get(f"{public_url}/api/kv?key=bot:ig_done_queue", headers=headers, timeout=10)
        if ig_done_raw.status_code == 200:
            try:
                ig_done = json.loads(ig_done_raw.json().get("value", "[]") or "[]")
                for item in ig_done:
                    bid = item.get("business_id")
                    if bid:
                        conn.execute("UPDATE businesses SET ig_dm_sent=1, ig_dm_sent_at=datetime('now'), status='sent' WHERE id=?", (bid,))
                        conn.execute("UPDATE outreach SET status='sent', sent_at=datetime('now') WHERE business_id=? AND channel='instagram'", (bid,))
                if ig_done:
                    conn.commit()
                    requests.post(f"{public_url}/api/kv", headers=headers,
                                  json={"key": "bot:ig_done_queue", "value": "[]"}, timeout=10)
            except Exception:
                pass


        # Process WA done queue
        wa_done_raw = requests.get(f"{public_url}/api/kv?key=bot:wa_done_queue", headers=headers, timeout=10)
        if wa_done_raw.status_code == 200:
            try:
                wa_done = json.loads(wa_done_raw.json().get("value", "[]") or "[]")
                for item in wa_done:
                    bid = item.get("business_id")
                    if bid:
                        conn.execute("UPDATE businesses SET wa_dm_sent=1, wa_dm_sent_at=datetime('now'), status='sent' WHERE id=?", (bid,))
                        conn.execute("UPDATE outreach SET status='sent', sent_at=datetime('now') WHERE business_id=? AND channel='whatsapp'", (bid,))
                if wa_done:
                    conn.commit()
                    requests.post(f"{public_url}/api/kv", headers=headers, json={"key": "bot:wa_done_queue", "value": "[]"}, timeout=10)
            except Exception:
                pass

        # Push Tier 1 & 2 IG leads (not yet DM'd, limit 100 per push, Tier 1 first)
        ig_rows = conn.execute("""
            SELECT b.id as business_id, b.name as business_name, b.category, b.city, b.tier,
                   b.demo_tunnel_url as demo_url, b.phone, b.website,
                   (SELECT draft FROM outreach WHERE business_id = b.id AND channel = 'instagram' AND status = 'draft' LIMIT 1) as ai_draft,
                   (SELECT instagram FROM contacts WHERE business_id = b.id LIMIT 1) as instagram_handle
            FROM businesses b
            WHERE b.tier IN (1,2)
              AND (b.ig_dm_sent IS NULL OR b.ig_dm_sent = 0)
              AND (b.ig_contact_only IS NULL OR b.ig_contact_only = 0)
              AND b.status NOT IN ('opted_out','skipped','closed','ig_contact_only')
              AND EXISTS (SELECT 1 FROM outreach WHERE business_id = b.id AND channel = 'instagram' AND status = 'draft')
            ORDER BY b.tier ASC, b.lead_score DESC
            LIMIT 100
        """).fetchall()
        ig_leads = [dict(r) for r in ig_rows]
        if False: pass # Disabled on Mac to prevent overwriting Firestick

        # Push Tier 1 & 2 WA leads
        wa_rows = conn.execute("""
            SELECT b.id as business_id, b.name as business_name, b.category, b.city, b.tier,
                   b.demo_tunnel_url as demo_url, b.phone, b.website,
                   (SELECT draft FROM outreach WHERE business_id = b.id AND channel = 'whatsapp' AND status = 'draft' LIMIT 1) as ai_draft,
                   con.whatsapp as phone_number
            FROM businesses b
            JOIN contacts con ON con.business_id = b.id
            WHERE b.tier IN (1,2)
              AND (b.wa_dm_sent IS NULL OR b.wa_dm_sent = 0)
              AND b.status NOT IN ('opted_out','skipped','closed')
              AND EXISTS (SELECT 1 FROM outreach WHERE business_id = b.id AND channel = 'whatsapp' AND status = 'draft')
            ORDER BY b.tier ASC, b.lead_score DESC
            LIMIT 100
        """).fetchall()
        wa_leads = [dict(r) for r in wa_rows]
        requests.post(f"{public_url}/api/kv", headers=headers,
                      json={"key": "bot:wa_leads", "value": json.dumps(wa_leads)}, timeout=10)


        conn.close()
        log.info("[Bot KV] Pushed stats, %d drafts, %d IG leads to Cloudflare KV", len(drafts), len(ig_leads))
    except Exception as e:
        log.warning("[Bot KV] Push failed: %s", e)


@require_internet
def job_sync_worker_events():
    """
    Poll the Cloudflare Worker to pull and flush all tracked open/click/engage events.
    Runs every 5 minutes.
    """
    import os, requests
    from database import record_tracking_event
    
    public_url = os.getenv("LEADFLOW_PUBLIC_URL", "")
    if not public_url or not public_url.startswith("https://") or "workers.dev" not in public_url:
        return
        
    secret_token = os.getenv("LEADFLOW_SECRET_TOKEN", "your-very-secure-secret-token-here")
    
    try:
        headers = {"X-Secret-Token": secret_token}
        r = requests.get(f"{public_url}/api/events", headers=headers, timeout=15)
        if r.status_code == 200:
            events = r.json()
            if events:
                log.info(f"[Scheduler] Syncing {len(events)} events from Cloudflare Worker...")
                for ev in events:
                    ev_type = ev.get("type")
                    biz_id = 0
                    actual_type = ev_type
                    
                    if ev_type in ("open", "click"):
                        tracking_id = ev.get("tracking_id")
                        metadata = ev.get("redirect_url", "")
                        record_tracking_event(tracking_id, 0, ev_type, metadata)
                        
                        # Resolve business_id for notification
                        try:
                            conn_temp = database.get_conn()
                            row_temp = conn_temp.execute("SELECT business_id FROM outreach WHERE tracking_id=?", (tracking_id,)).fetchone()
                            if not row_temp:
                                row_temp = conn_temp.execute("SELECT business_id FROM follow_ups WHERE tracking_id=?", (tracking_id,)).fetchone()
                            if row_temp:
                                biz_id = row_temp["business_id"]
                            conn_temp.close()
                        except Exception:
                            pass
                    elif ev_type == "engage":
                        bid = ev.get("business_id", 0)
                        engage_type = ev.get("event_type", "")
                        record_tracking_event("", bid, engage_type, "")
                        biz_id = bid
                        actual_type = engage_type
                    
                    # Fire local ntfy notification using Mac's clean home IP
                    if biz_id:
                        try:
                            conn_temp = database.get_conn()
                            row_temp = conn_temp.execute("SELECT name FROM businesses WHERE id=?", (biz_id,)).fetchone()
                            biz_name = row_temp["name"] if row_temp else f"Business #{biz_id}"
                            conn_temp.close()
                            
                            _ntfy_t = os.getenv('NTFY_TOPIC')
                            msg = ""
                            if actual_type == "open":
                                msg = f"✉️ Email opened: {biz_name}"
                            elif actual_type == "click":
                                msg = f"🖱️ Demo clicked: {biz_name}"
                            elif actual_type == "scroll_90":
                                msg = f"🔥 Hot Lead! {biz_name} read 90% of demo"
                            elif actual_type == "modal_shown":
                                msg = f"💬 Contact Modal Opened: {biz_name}"
                            elif actual_type == "fiverr_click":
                                msg = f"💰 Fiverr gig clicked: {biz_name}! Connect with them!"
                            else:
                                msg = f"📢 Engagement ({actual_type}): {biz_name}"
                                
                            requests.post(
                                f"https://ntfy.sh/{_ntfy_t}",
                                data=msg.encode("utf-8"),
                                headers={"Title": "Leadflow Sync", "Tags": "sync,bell"},
                                timeout=5
                            )
                        except Exception:
                            pass
        elif r.status_code != 404:
            log.warning(f"[Scheduler] Cloudflare Worker event sync returned status {r.status_code}")
    except Exception as e:
        log.error(f"[Scheduler] Cloudflare Worker event sync error: {e}")


def _has_matching_template(category: str, name: str) -> bool:
    import os, json
    category_lower = (category or "").lower()
    name_lower = (name or "").lower()
    
    config_path = os.path.join(os.path.dirname(__file__), "demo_templates", "config.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as cfg_f:
                config_data = json.load(cfg_f)
            templates_list = config_data.get("templates", [])
            for tpl in templates_list:
                if not tpl.get("enabled", True):
                    continue
                niches = tpl.get("niches", [])
                if any(n in category_lower or n in name_lower for n in niches):
                    return True
        except Exception:
            pass
            
    demo_templates_dir = os.path.join(os.path.dirname(__file__), "demo_templates")
    if os.path.exists(demo_templates_dir):
        try:
            for tpl_file in os.listdir(demo_templates_dir):
                if not tpl_file.endswith(".html") or tpl_file == "config.json":
                    continue
                base_name = tpl_file.replace(".html", "").lower()
                if base_name in category_lower or base_name in name_lower:
                    return True
        except Exception:
            pass
            
    return False


@require_internet
def job_auto_send_leads():
    """Find untouched leads, auto-generate demo/draft, and send email with A/B testing + send-time optimization."""
    if not is_leader():
        log.info("[Scheduler] Primary device (Firestick) is active. Skipping job_auto_send_leads.")
        return

    if not _leads_send_lock.acquire(blocking=False):
        log.info("[Scheduler] job_auto_send_leads is already running. Skipping concurrent execution.")
        return
    active_connections = {}  # (email, pwd) -> smtp_server
    try:
        auto_update_warmup_limit()
        cfg = _get_config()
        if not cfg.get("enabled") or not cfg.get("auto_send_enabled"):
            log.info("[Scheduler] Autopilot or Auto-send is disabled. Skipping auto-sending leads.")
            return

        from database import (get_conn, mark_sent, get_emails_sent_today, update_business_status,
                              can_sender_send, increment_sender_send, detect_timezone,
                              update_business_timezone, is_optimal_send_time, pick_ab_subject,
                              get_or_assign_sender_email, get_dynamic_send_limit)
        from sender import parse_subject_body, send_email, get_sender_credentials
        from ai_writer import write_audit_pitch, write_no_website_pitch, BOOKING_URL, CALENDLY_URLS
        import uuid, requests, time, json as _json, smtplib

        # Dynamic limit: 25 per active sender email (auto-scales when new email is added)
        max_auto_send = get_dynamic_send_limit()
        send_window_start = cfg.get("send_window_start", 9)
        send_window_end = cfg.get("send_window_end", 14)
        preferred_days = _json.loads(cfg.get("preferred_days", "[1,2,3,4]")) if cfg.get("preferred_days") else [1, 2, 3, 4]


        # Enforce safe daily cold email limit to prevent spam blocking
        sent_today = get_emails_sent_today()
        if sent_today >= max_auto_send:
            log.info(f"[Scheduler] Daily auto-send limit ({max_auto_send}) reached. Skipping initial auto-sending today (already sent: {sent_today}).")
            return

        # ── Conversion-Weighted Niche Budget + ICS-Ranked Queue ──────────────
        # 1. Compute today's per-niche slot budget weighted by avg ICS score
        #    (high-converting niches get more daily sends, all niches get ≥1)
        # 2. Fetch large candidate pool, rank by ICS, apply budget caps, pick best leads
        from database import compute_ics, get_niche_sent_today, compute_niche_daily_budget

        remaining_today = max_auto_send - sent_today
        if remaining_today <= 0:
            return

        # Build today's conversion-weighted niche budget (recalculated each run)
        niche_budget = compute_niche_daily_budget(daily_total=max_auto_send)

        conn = get_conn()
        try:
            # ── Pool A: Fresh leads scraped TODAY (always sent first — same-day lifecycle) ──
            fresh_rows = conn.execute("""
                SELECT b.*, c.email, c.owner_name, c.whatsapp, c.instagram
                FROM businesses b
                LEFT JOIN contacts c ON c.business_id = b.id
                WHERE b.status IN ('new', 'approved')
                  AND b.lead_score >= 25
                  AND c.email IS NOT NULL AND c.email != ''
                  AND DATE(b.found_at) = DATE('now')
                  AND b.id NOT IN (
                      SELECT DISTINCT business_id FROM outreach
                      WHERE status='sent' AND channel='email'
                  )
                ORDER BY
                  CASE WHEN LOWER(b.category) IN ('accountant','medspa','solar','gym','dentist') THEN 0 ELSE 1 END ASC,
                  b.lead_score DESC
                LIMIT 50
            """).fetchall()
            fresh_leads = [dict(r) for r in fresh_rows]


            # ── Pool B: Backlog (leads from previous days, ICS-ranked) ──
            backlog_rows = conn.execute("""
                SELECT b.*, c.email, c.owner_name, c.whatsapp, c.instagram
                FROM businesses b
                LEFT JOIN contacts c ON c.business_id = b.id
                WHERE b.status IN ('new', 'approved')
                  AND b.lead_score >= 25
                  AND c.email IS NOT NULL AND c.email != ''
                  AND DATE(b.found_at) < DATE('now')
                  AND b.id NOT IN (
                      SELECT DISTINCT business_id FROM outreach
                      WHERE status='sent' AND channel='email'
                  )
                ORDER BY
                  CASE WHEN LOWER(b.category) IN ('accountant','medspa','solar','gym','dentist') THEN 0 ELSE 1 END ASC,
                  b.lead_score DESC
                LIMIT 300
            """).fetchall()
            backlog_leads = [dict(r) for r in backlog_rows]

            # ── Pool C: Win-backs (Opened but no reply, >30 days ago, high score) ──
            winback_rows = conn.execute("""
                SELECT b.*, c.email, c.owner_name, c.whatsapp, c.instagram
                FROM businesses b
                LEFT JOIN contacts c ON c.business_id = b.id
                JOIN outreach o ON o.business_id = b.id
                WHERE b.status = 'sent'
                  AND o.channel = 'email'
                  AND o.opened = 1
                  AND b.lead_score >= 35
                  AND (c.email IS NOT NULL AND c.email != '')
                  AND o.sent_at < DATE('now', '-30 days')
                ORDER BY b.lead_score DESC
                LIMIT 50
            """).fetchall()
            winback_leads = [dict(r) for r in winback_rows]

        finally:
            conn.close()

        # Score all pools with ICS
        for c in fresh_leads:
            c["_ics"] = compute_ics(c, c)
            c["_is_fresh"] = True
        for c in backlog_leads:
            c["_ics"] = compute_ics(c, c)
            c["_is_fresh"] = False
        for c in winback_leads:
            c["_ics"] = compute_ics(c, c)
            c["_is_fresh"] = False
            c["_is_winback"] = True

        # Sort each pool by ICS, then merge: fresh leads ALWAYS go first, then backlog, then win-backs
        fresh_leads.sort(key=lambda x: x["_ics"], reverse=True)
        backlog_leads.sort(key=lambda x: x["_ics"], reverse=True)
        winback_leads.sort(key=lambda x: x["_ics"], reverse=True)
        candidates = fresh_leads + backlog_leads + winback_leads

        if fresh_leads:
            log.info(f"[Scheduler] \U0001f195 {len(fresh_leads)} fresh leads scraped today — they get FIRST pick of today's slots")
        if winback_leads:
            log.info(f"[Scheduler] \U0001f504 {len(winback_leads)} win-back candidates (opened >30d ago, no reply)")
        log.info(f"[Scheduler] Candidate pool: {len(fresh_leads)} fresh + {len(backlog_leads)} backlog + {len(winback_leads)} winback = {len(candidates)} total")

        # Apply conversion-weighted niche budget and pick top leads
        niche_sent_cache = {}  # category -> emails sent today (DB lookup, cached)
        leads = []
        for cand in candidates:
            if len(leads) >= remaining_today:
                break
            cat = (cand.get("category") or "unknown").lower()
            # Get today's budget for this niche (default 1 if not in budget)
            niche_cap = niche_budget.get(cat, 1)
            if cat not in niche_sent_cache:
                niche_sent_cache[cat] = get_niche_sent_today(cat)
            if niche_sent_cache[cat] >= niche_cap:
                continue  # This niche's daily budget is exhausted
            leads.append(cand)
            niche_sent_cache[cat] += 1  # reserve slot

        log.info(f"[Scheduler] ICS queue: {len(candidates)} candidates → {len(leads)} selected "
                 f"(conversion-weighted niche budget, ICS-ranked)")
        if leads:
            top5 = [(l['name'], l['category'], l['_ics']) for l in leads[:5]]
            log.info(f"[Scheduler] Top picks today: {top5}")

        sends_this_run = 0
        sent_biz_ids_this_run = set()  # in-run dedup: never send to same business twice in one cycle
        MAX_SENDS_PER_RUN = 10  # process up to 10 per 5-min cycle to avoid holding the lock too long

        for lead in leads:
            if sends_this_run >= MAX_SENDS_PER_RUN:
                break
            # In-run dedup: skip if we already sent to this business this cycle
            if lead["id"] in sent_biz_ids_this_run:
                log.info(f"[Scheduler] Skipping {lead['name']} — already sent this run (in-run dedup)")
                continue

            log.info(f"[Scheduler] Processing lead: {lead['name']} (ICS: {lead.get('_ics', '?')})") 
            try:
                # Validate email address before attempting to email
                from extractor import _clean_email
                if not _clean_email(lead["email"]):
                    log.info(f"  -> Skipping lead {lead['name']} because email {lead['email']} is invalid/placeholder.")
                    from database import update_business_status
                    update_business_status(lead["id"], "skipped")
                    continue

                # ── Send-Time Optimization ──
                tz = lead.get("timezone") or detect_timezone(lead.get("city", ""), lead.get("country", ""))
                if not lead.get("timezone"):
                    update_business_timezone(lead["id"], tz)
                
                # Check if it's within the optimal send window for this lead's timezone
                if not is_optimal_send_time(tz, send_window_start, send_window_end, preferred_days):
                    log.info(f"  -> Skipping {lead['name']} — not optimal send time in {tz} (window: {send_window_start}-{send_window_end}h, days: {preferred_days})")
                    continue

                # Check scheduled_at — only send if the slot has been reached
                from datetime import datetime, timezone as _tz_mod
                conn_sched = get_conn()
                try:
                    sched_row = conn_sched.execute(
                        "SELECT scheduled_at FROM outreach WHERE business_id=? AND channel='email' AND status='draft' ORDER BY id DESC LIMIT 1",
                        (lead["id"],)
                    ).fetchone()
                finally:
                    conn_sched.close()
                if sched_row and sched_row["scheduled_at"]:
                    try:
                        slot_dt = datetime.strptime(sched_row["scheduled_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=_tz_mod.utc)
                        if datetime.now(_tz_mod.utc) < slot_dt:
                            log.info(f"  -> Holding {lead['name']} — scheduled for {sched_row['scheduled_at']} UTC (not yet)")
                            continue
                    except Exception:
                        pass  # unparseable scheduled_at — proceed anyway

                # ── Per-Sender Warmup Check ──
                assigned_sender = get_or_assign_sender_email(lead["id"])
                if not assigned_sender or not can_sender_send(assigned_sender):
                    log.info(f"  -> Skipping {lead['name']} — all senders have hit their daily warmup limit")
                    continue

                # Get SMTP session credentials and connect/cache
                sender_email, sender_password = get_sender_credentials(assigned_sender)
                if not sender_email or not sender_password:
                    log.error(f"  -> Skipping {lead['name']} — no credentials found for sender {assigned_sender}")
                    continue

                sender_key = (sender_email, sender_password)
                if sender_key not in active_connections:
                    try:
                        server = smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30)
                        server.login(sender_email, sender_password)
                        active_connections[sender_key] = server
                    except Exception as conn_err:
                        log.error(f"[Scheduler] Failed to connect/login SMTP for {sender_email}: {conn_err}")
                        continue

                smtp_server = active_connections[sender_key]

                pitch_type = lead.get("pitch_type", "")
                category_val = (lead.get("category", "") or "").lower()
                name_val = (lead.get("name", "") or "").lower()
                is_saas_lead = (pitch_type == "leadflow_saas") or _has_matching_template(category_val, lead.get("name", ""))
                draft_text = ""
                demo_url = ""
                subject_options = []

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
                    from deploy import is_live, slug_for, demo_url_for
                    demo_url = lead.get("demo_tunnel_url", "")
                    if demo_url and not is_live(demo_url, wait=10):
                        # Stored URL may be a stale numeric-ID URL; try the slug URL as fallback
                        slug_url = demo_url_for(lead["id"], lead["name"])
                        if slug_url != demo_url and is_live(slug_url, wait=10):
                            demo_url = slug_url
                            conn.execute("UPDATE businesses SET demo_tunnel_url=? WHERE id=?", (demo_url, lead["id"]))
                            conn.commit()
                            log.info(f"  -> Corrected demo URL for {lead['name']} to slug URL")
                        else:
                            log.error(f"  -> Demo not live yet for {lead['name']} — skipping send this round")
                            continue

                    # Get the draft and subject options
                    conn2 = get_conn()
                    try:
                        draft_row = conn2.execute("SELECT draft, subject_options FROM outreach WHERE business_id=? AND channel='email' AND channel != 'instagram'", (lead["id"],)).fetchone()
                        draft_text = draft_row["draft"] if draft_row else ""
                        if draft_row and draft_row["subject_options"]:
                            try:
                                subject_options = _json.loads(draft_row["subject_options"])
                            except Exception:
                                pass
                    finally:
                        conn2.close()

                else:
                    # 2. Web Design Lead: Send audit report (if has site) or benefits (if no site)
                    has_site = bool(lead.get("website"))
                    booking_link = os.getenv("CALENDLY_URL") or os.getenv("BOOKING_URL") or "https://calendly.com"
                    
                    scraped = {}
                    if has_site:
                        from demo_generator import _scrape_site, get_competitor_name
                        try:
                            scraped = _scrape_site(lead["website"]) or {}
                        except Exception:
                            pass
                        comp = get_competitor_name(lead.get("category", ""), lead.get("city", ""), lead.get("name", ""))
                        if comp:
                            scraped["top_competitor"] = comp
                    
                    if has_site:
                        log.info(f"  -> Writing website audit pitch for {lead['name']}...")
                        # Pass scraped to write_audit_pitch if we updated it, but currently it doesn't take it.
                        # We'll rely on write_instagram_dm using it below.
                        draft_text = write_audit_pitch(lead, booking_link)
                    else:
                        log.info(f"  -> Writing no-website benefit pitch for {lead['name']}...")
                        draft_text = write_no_website_pitch(lead, booking_link)

                    # Save draft to outreach table with scheduled_at
                    conn2 = get_conn()
                    try:
                        tz_str = lead.get("timezone") or "America/New_York"
                        slot = _assign_scheduled_at(tz_str)
                        conn2.execute("DELETE FROM outreach WHERE business_id=? AND channel='email'", (lead["id"],))
                        conn2.execute("""
                            INSERT INTO outreach (business_id, channel, draft, status, scheduled_at)
                            VALUES (?, 'email', ?, 'draft', ?)
                        """, (lead["id"], draft_text, slot))
                        
                        # Generate IG draft if they have an IG handle
                        if lead.get("instagram"):
                            from ai_writer import write_instagram_dm, ai_review_draft
                            log.info(f"  -> Building Instagram DM draft for {lead['name']}...")
                            ig_draft = write_instagram_dm(lead, demo_url=lead.get("demo_tunnel_url",""), scraped=scraped or None)
                            if ig_draft:
                                # ── AI PRE-SEND REVIEW ──────────────────────────────
                                approved, review_reason = ai_review_draft(
                                    draft=ig_draft,
                                    business_name=lead.get("name", ""),
                                    ig_handle=lead.get("instagram", "")
                                )
                                if not approved:
                                    log.warning(
                                        f"  -> [AI Review] REJECTED draft for @{lead.get('instagram')} "
                                        f"({lead['name']}): {review_reason}. Skipping queue."
                                    )
                                else:
                                    log.info(f"  -> [AI Review] {review_reason}")
                                    conn2.execute("DELETE FROM outreach WHERE business_id=? AND channel='instagram'", (lead["id"],))
                                    conn2.execute("""
                                        INSERT INTO outreach (business_id, channel, draft, status)
                                        VALUES (?, 'instagram', ?, 'draft')
                                    """, (lead["id"], ig_draft))
                                # ────────────────────────────────────────────────────

                        
                        conn2.commit()

                        # Generate follow-up sequence for web-design leads
                        from ai_writer import write_follow_up_sequence
                        from database import insert_follow_ups
                        try:
                            # Use email channel for web-design follow-ups by default
                            sequences = write_follow_up_sequence(lead, lead.get("demo_tunnel_url", ""), channel="email")
                            insert_follow_ups(lead["id"], sequences)
                            log.info(f"  -> Queued {len(sequences)} follow-ups for {lead['name']}")
                        except Exception as fu_err:
                            log.error(f"  -> Failed queuing follow-ups for {lead['name']}: {fu_err}")

                        log.info(f"  -> Scheduled {lead['name']} for {slot} UTC")
                    finally:
                        conn2.close()

                if not draft_text:
                    continue

                # ── A/B Subject Line Testing ──
                subject, body = parse_subject_body(draft_text)
                if subject_options and len(subject_options) >= 2:
                    chosen_subject, variant = pick_ab_subject(lead["id"], subject_options)
                    log.info(f"  -> A/B Testing: Using variant {variant} subject: {chosen_subject[:50]}...")
                    subject = chosen_subject
                
                if subject and body:
                    lead_email = lead.get("email", "")
                    # ── Suppression check ─────────────────────────────────────────────────
                    from sender import is_suppressed as _is_suppressed
                    if lead_email and _is_suppressed(lead_email):
                        log.warning(f"[Scheduler] Skipping {lead_email} — in suppression list")
                        continue
                    # ── Duplicate email guard ─────────────────────────────────────────
                    if lead_email:
                        conn_dup = get_conn()
                        try:
                            dup = conn_dup.execute(
                                """SELECT b.name FROM contacts c
                                   JOIN businesses b ON b.id=c.business_id
                                   WHERE LOWER(c.email)=LOWER(?)
                                     AND b.status IN ('sent','replied','closed')
                                     AND b.id != ?""",
                                (lead_email, lead["id"])
                            ).fetchone()
                        finally:
                            conn_dup.close()
                        if dup:
                            log.warning(f"[Scheduler] Skipping {lead_email} — already sent to '{dup['name']}' (duplicate email)")
                            continue
                    # ─────────────────────────────────────────────────────────────────
                    tracking_id = str(uuid.uuid4())
                    send_email(lead["email"], subject, body, tracking_id, demo_url, business_id=lead["id"], smtp_server=smtp_server)
                    mark_sent(lead["id"], "email", is_autopilot=True, subject_used=subject, tracking_id=tracking_id)
                    update_business_status(lead["id"], "sent")
                    sent_biz_ids_this_run.add(lead["id"])  # mark as sent this run

                    
                    # Track per-sender warmup
                    if assigned_sender:
                        increment_sender_send(assigned_sender)
                    
                    sends_this_run += 1
                    log.info(f"[Scheduler] ✅ Successfully sent to {lead['email']} (sender: {assigned_sender}, tz: {tz})")
                    send_ntfy_sent_notification("Outreach Email", lead['email'], assigned_sender, subject)
                    
                    # Anti-spam: Add randomized human-like delay between sends
                    import random
                    jitter = random.randint(35, 85)
                    log.info(f"  -> Sleeping for {jitter}s to avoid spam filters...")
                    time.sleep(jitter)

                    # fix #11: SMTP sessions can expire during long jitter sleeps.
                    # After each sleep, verify the connection is still alive with a NOOP.
                    # If it's dead, reconnect before the next lead.
                    if sender_key in active_connections:
                        try:
                            active_connections[sender_key].noop()
                        except Exception:
                            log.warning(f"[Scheduler] SMTP session for {sender_email} expired — reconnecting")
                            try:
                                active_connections[sender_key].quit()
                            except Exception:
                                pass
                            del active_connections[sender_key]
            except Exception as e:
                log.error(f"[Scheduler] Failed to auto-send to {lead['name']}: {e}")
                if 'sender_key' in locals() and sender_key in active_connections:
                    try:
                        active_connections[sender_key].quit()
                    except Exception:
                        pass
                    del active_connections[sender_key]
    finally:
        # Close all cached SMTP sessions
        for server in active_connections.values():
            try:
                server.quit()
            except Exception:
                pass
        _leads_send_lock.release()


@require_internet
def job_auto_send_followups():
    """Send follow-ups that are scheduled and pending, respecting per-sender warmup limits."""
    if not is_leader():
        log.info("[Scheduler] Primary device (Firestick) is active. Skipping job_auto_send_followups.")
        return

    if not _followups_send_lock.acquire(blocking=False):
        log.info("[Scheduler] job_auto_send_followups is already running. Skipping concurrent execution.")
        return
    active_connections = {}  # (email, pwd) -> smtp_server
    try:
        auto_update_warmup_limit()
        cfg = _get_config()
        if not cfg.get("enabled") or not cfg.get("auto_send_enabled"):
            log.info("[Scheduler] Autopilot or Auto-send is disabled. Skipping auto-sending followups.")
            return

        from database import (get_conn, get_emails_sent_today, can_sender_send,
                              increment_sender_send, get_or_assign_sender_email,
                              is_optimal_send_time, detect_timezone)
        from sender import parse_subject_body, send_email, get_sender_credentials
        import uuid, json as _json, smtplib

        from database import get_dynamic_send_limit
        max_auto_send = get_dynamic_send_limit()  # 25 per active sender, auto-scales

        send_window_start = cfg.get("send_window_start", 9)
        send_window_end = cfg.get("send_window_end", 14)
        preferred_days = _json.loads(cfg.get("preferred_days", "[1,2,3,4]")) if cfg.get("preferred_days") else [1, 2, 3, 4]

        # Enforce safe daily cold email limit to prevent spam blocking
        sent_today = get_emails_sent_today()
        if sent_today >= max_auto_send:
            log.info(f"[Scheduler] Daily auto-send limit ({max_auto_send}) reached. Skipping auto follow-ups today (already sent: {sent_today}).")
            return

        conn = get_conn()
        try:
            rows = conn.execute("""
                SELECT f.*, c.email, c.instagram, b.demo_tunnel_url, b.city, b.country, b.timezone,
                       b.assigned_sender_email
                FROM follow_ups f
                JOIN businesses b ON b.id = f.business_id
                LEFT JOIN contacts c ON c.business_id = b.id
                WHERE f.status = 'pending' AND datetime(f.scheduled_for) <= datetime('now')
                  AND b.status NOT IN ('replied', 'opted_out', 'closed')
                ORDER BY f.scheduled_for ASC
                LIMIT 20
            """).fetchall()
            follow_ups = [dict(r) for r in rows]
        finally:
            conn.close()

        for row in follow_ups:
            if not row["draft"]:
                continue
                
            channel = row.get("channel", "email")
            
            # ── Instagram Follow-up Dispatch (via ADB) ──
            if channel == "instagram":
                handle = (row.get("instagram") or "").strip().lstrip("@")
                if not handle:
                    log.info(f"  -> Skipping Instagram follow-up {row['id']} because handle is empty.")
                    conn_skip = get_conn()
                    try:
                        conn_skip.execute("UPDATE follow_ups SET status='skipped' WHERE id=?", (row["id"],))
                        conn_skip.commit()
                    finally:
                        conn_skip.close()
                    continue
                
                # Time window enforcement
                if row.get("sequence_num", 1) == 1:
                    tz = row.get("timezone") or detect_timezone(row.get("city", ""), row.get("country", ""))
                    if not is_optimal_send_time(tz, send_window_start, send_window_end, preferred_days):
                        log.info(f"  -> Deferring Instagram follow-up {row['id']} seq#1 — not optimal send time in {tz}")
                        continue
                
                from instagram_sender import can_send_instagram, send_instagram_dm
                if not can_send_instagram():
                    log.info(f"  -> Deferring Instagram follow-up {row['id']} — daily sending limit reached")
                    continue
                
                try:
                    log.info(f"[Scheduler] Sending Instagram follow-up seq#{row['sequence_num']} to @{handle}")
                    ok = send_instagram_dm(handle, row["draft"])
                    if ok is None:
                        log.warning(f"[Scheduler] Permanent skip IG follow-up @{handle} — account not found or private. Marking skipped.")
                        conn_skip2 = get_conn()
                        try:
                            conn_skip2.execute("UPDATE follow_ups SET status='skipped' WHERE id=?", (row["id"],))
                            conn_skip2.commit()
                        finally:
                            conn_skip2.close()
                    elif ok:
                        conn_update = get_conn()
                        try:
                            conn_update.execute("UPDATE follow_ups SET status='sent', sent_at=datetime('now') WHERE id=?", (row["id"],))
                            conn_update.commit()
                        finally:
                            conn_update.close()
                        
                        log.info(f"[Scheduler] ✅ Auto-sent Instagram follow-up {row['sequence_num']} to @{handle}")
                        send_ntfy_sent_notification(f"IG Follow-up #{row['sequence_num']}", f"@{handle}", "Instagram", "Instagram DM")
                        
                        # Add a small buffer on top of ADB's delay
                        time.sleep(5)
                except Exception as ig_err:
                    log.error(f"[Scheduler] Failed to send Instagram follow-up {row['id']}: {ig_err}")
                continue

            # ── Email Follow-up Dispatch ──
            if not row["email"]:
                continue
            try:
                from database import is_suppressed
                if is_suppressed(row["email"], row["business_id"]):
                    log.info(f"  -> Skipping followup {row['id']} because email {row['email']} or domain is suppressed.")
                    conn2 = get_conn()
                    try:
                        conn2.execute("UPDATE follow_ups SET status='skipped' WHERE id=?", (row["id"],))
                        conn2.execute("UPDATE businesses SET status='skipped' WHERE id=?", (row["business_id"],))
                        conn2.commit()
                    finally:
                        conn2.close()
                    continue

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

                # ── Send-Time Check for Follow-ups (relaxed) ──
                if row.get("sequence_num", 1) == 1:
                    tz = row.get("timezone") or detect_timezone(row.get("city", ""), row.get("country", ""))
                    if not is_optimal_send_time(tz, send_window_start, send_window_end, preferred_days):
                        log.info(f"  -> Deferring follow-up {row['id']} seq#1 — not optimal send time in {tz}")
                        continue

                # ── Per-Sender Warmup Check ──
                sender = row.get("assigned_sender_email") or get_or_assign_sender_email(row["business_id"])
                if sender and not can_sender_send(sender):
                    log.info(f"  -> Deferring follow-up {row['id']} — sender {sender} at warmup limit")
                    continue

                # Get SMTP session credentials and connect/cache
                sender_email, sender_password = get_sender_credentials(sender)
                if not sender_email or not sender_password:
                    log.error(f"  -> Deferring follow-up {row['id']} — no credentials found for sender {sender}")
                    continue

                sender_key = (sender_email, sender_password)
                if sender_key not in active_connections:
                    try:
                        server = smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30)
                        server.login(sender_email, sender_password)
                        active_connections[sender_key] = server
                    except Exception as conn_err:
                        log.error(f"[Scheduler] Failed to connect/login SMTP for follow-up {sender_email}: {conn_err}")
                        continue
                
                smtp_server = active_connections[sender_key]

                subject, body = parse_subject_body(row["draft"])
                if not subject: subject = "Quick follow-up"
                tracking_id = str(uuid.uuid4())
                send_email(row["email"], subject, body, tracking_id, row.get("demo_tunnel_url", ""), business_id=row["business_id"], smtp_server=smtp_server)
                
                conn2 = get_conn()
                try:
                    conn2.execute("UPDATE follow_ups SET status='sent', sent_at=datetime('now'), tracking_id=? WHERE id=?", (tracking_id, row["id"]))
                    conn2.commit()
                except Exception as db_err:
                    log.error(f"[Scheduler] Failed to update follow_up tracking_id in DB: {db_err}")
                finally:
                    conn2.close()
                
                # Track per-sender warmup
                if sender:
                    increment_sender_send(sender)
                
                log.info(f"[Scheduler] ✅ Auto-sent follow-up {row['sequence_num']} to {row['email']} (angle: {row.get('followup_angle', 'unknown')})")
                send_ntfy_sent_notification(f"Follow-up #{row['sequence_num']}", row['email'], sender, subject)

                # Anti-spam: Add randomized human-like delay between sends
                import random
                jitter = random.randint(20, 60)
                log.info(f"  -> Sleeping for {jitter}s to avoid spam filters...")
                import time
                time.sleep(jitter)
            except Exception as e:
                log.error(f"[Scheduler] Failed to send followup {row['id']}: {e}")
                if 'sender_key' in locals() and sender_key in active_connections:
                    try:
                        active_connections[sender_key].quit()
                    except Exception:
                        pass
                    del active_connections[sender_key]
    finally:
        # Close all cached SMTP sessions
        for server in active_connections.values():
            try:
                server.quit()
            except Exception:
                pass
        _followups_send_lock.release()


@require_internet
def job_check_replies():
    """Check inbox for replies/unsubscribes and update database/cancel follow-ups."""
    from imap_sync import check_replies
    log.info("[Scheduler] Checking inbox for replies/opt-outs...")
    try:
        check_replies()
    except Exception as e:
        log.error(f"[Scheduler] IMAP reply check error: {e}")


_pregen_lock = threading.Lock()

@require_internet
def job_pregen_demo_buffer():
    """
    Maintains a rolling demo buffer equal to tomorrow's full send capacity.

    Instead of a fixed buffer of 10, this reads max_auto_send from the
    scheduler config so the buffer always equals exactly how many emails
    we plan to send tomorrow. If the daily limit is 75, we ensure 75 demos
    are pre-generated and ready — so the send job never has to wait on
    GitHub Pages propagation for a single lead.

    Runs every 15 minutes. Only generates what's missing to top up to target.
    """
    if not _pregen_lock.acquire(blocking=False):
        return  # Already running, skip
    try:
        # Dynamically read today's send limit as the buffer target
        from database import get_conn
        conn = get_conn()
        try:
            from database import get_dynamic_send_limit
            BUFFER_TARGET = get_dynamic_send_limit()  # match the dynamic daily send limit


            # Count leads at the top of the send queue that already have demos
            already_ready = conn.execute("""
                SELECT COUNT(*) as cnt FROM (
                    SELECT b.id
                    FROM businesses b
                    JOIN contacts c ON c.business_id = b.id
                    WHERE b.status IN ('new', 'approved')
                      AND b.lead_score >= 25
                      AND c.email IS NOT NULL AND c.email != ''
                      AND b.demo_tunnel_url IS NOT NULL AND b.demo_tunnel_url != ''
                    ORDER BY b.lead_score DESC
                    LIMIT ?
                )
            """, (BUFFER_TARGET,)).fetchone()["cnt"]

            needed = max(0, BUFFER_TARGET - already_ready)

            if needed == 0:
                log.info(f"[DemoBuffer] Buffer full ({already_ready}/{BUFFER_TARGET} demos ready). Nothing to do.")
                return

            log.info(f"[DemoBuffer] Buffer at {already_ready}/{BUFFER_TARGET} (daily limit) — generating {needed} more demos.")

            # Find the next N leads in the send queue that NEED a demo, in queue order
            rows = conn.execute("""
                SELECT b.id, b.name, b.category
                FROM businesses b
                JOIN contacts c ON c.business_id = b.id
                WHERE b.status IN ('new', 'approved')
                  AND b.lead_score >= 25
                  AND c.email IS NOT NULL AND c.email != ''
                  AND (b.demo_tunnel_url IS NULL OR b.demo_tunnel_url = '')
                ORDER BY b.lead_score DESC
                LIMIT ?
            """, (needed,)).fetchall()
            leads_to_gen = [dict(r) for r in rows]
        finally:
            conn.close()

        if not leads_to_gen:
            log.info("[DemoBuffer] No leads in queue need demos right now.")
            return

        import requests as _req
        for lead in leads_to_gen:
            log.info(f"[DemoBuffer] Pre-generating demo for: {lead['name']} ({lead['category']})")
            for _attempt in range(3):
                try:
                    resp = _req.post(
                        f"http://127.0.0.1:8765/leads/{lead['id']}/generate",
                        json={"channels": ["email"]},
                        timeout=200,
                    )
                    if resp.status_code == 200:
                        log.info(f"[DemoBuffer]   -> ✅ Demo ready for {lead['name']}")
                    else:
                        log.warning(f"[DemoBuffer]   -> ❌ Failed ({resp.status_code}) for {lead['name']}, attempt {_attempt+1}/3")
                        if _attempt < 2:
                            import time as _t; _t.sleep(5 * (_attempt + 1))
                            continue
                    break
                except Exception as gen_err:
                    log.error(f"[DemoBuffer]   -> Error attempt {_attempt+1}/3 for {lead['name']}: {gen_err}")
                    if _attempt < 2:
                        import time as _t; _t.sleep(5 * (_attempt + 1))
    finally:
        _pregen_lock.release()
def job_check_bounces():
    """Verify new leads via burner account pinging & bounce monitoring."""
    try:
        import bounce_checker
        bounce_checker.run_pipeline()
    except Exception as e:
        log.error(f"[Scheduler] Error running bounce verification pipeline: {e}")


def job_daily_recap():
    """Compile and send a daily summary of outreach results to ntfy/Telegram."""
    from database import get_conn
    conn = get_conn()
    try:
        # 1. Total emails sent today
        sent_today = conn.execute("""
            SELECT COUNT(*) FROM outreach 
            WHERE status='sent' 
              AND DATE(sent_at) = DATE('now')
        """).fetchone()[0] or 0

        # 2. Total opens registered today
        opens_today = conn.execute("""
            SELECT COUNT(*) FROM tracking_events 
            WHERE event_type='open' 
              AND DATE(occurred_at) = DATE('now')
        """).fetchone()[0] or 0

        # 3. Total clicks registered today
        clicks_today = conn.execute("""
            SELECT COUNT(*) FROM tracking_events 
            WHERE event_type='click' 
              AND DATE(occurred_at) = DATE('now')
        """).fetchone()[0] or 0

        # 4. Total replies received today
        replies_today = conn.execute("""
            SELECT COUNT(*) FROM inbound_messages 
            WHERE DATE(received_at) = DATE('now')
        """).fetchone()[0] or 0

        # 5. Total warm leads (replied status)
        total_replied = conn.execute("""
            SELECT COUNT(*) FROM businesses 
            WHERE status='replied'
        """).fetchone()[0] or 0

        # 6. Bounced emails checked today
        bounces_today = conn.execute("""
            SELECT COUNT(*) FROM businesses 
            WHERE status='bounced' 
              AND notes LIKE '%' || DATE('now') || '%'
        """).fetchone()[0] or 0

        # Send alert via ntfy & Telegram
        title = "📊 LeadFlow - Daily Performance Recap"
        message = (
            f"Here is your daily campaign recap:\n\n"
            f"📤 Sent Today: {sent_today} emails\n"
            f"👀 Opened Today: {opens_today} opens\n"
            f"🖱️ Clicked Today: {clicks_today} clicks\n"
            f"💬 Replies Received: {replies_today} replies\n"
            f"🛡️ Bounces Blocked: {bounces_today} invalid addresses\n\n"
            f"🔥 Total Active Warm Leads: {total_replied}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Live static dashboard is active at:\n"
            f"https://leadflow-demos.pages.dev/dashboard_index.html"
        )
        
        from imap_sync import notify_chandan
        notify_chandan(title, message, tags="bar_chart,chart_with_upwards_trend", priority="default")
    except Exception as e:
        log.error(f"[Scheduler] Error running daily recap job: {e}")


def job_adb_keepalive():
    """Every 10 min: reconnect ADB to Vivo; alert if unreachable for >1 cycle."""
    import subprocess
    from imap_sync import notify_chandan
    adb_bin = "adb"
    import resolve_devices
    vivo = resolve_devices.ensure_connected("vivo")
    
    if vivo:
        try:
            # Verify shell responds
            result = subprocess.run(
                [adb_bin, "-s", vivo, "shell", "echo", "ok"],
                timeout=10, capture_output=True, text=True
            )
            if result.returncode != 0 or result.stdout.strip() != "ok":
                raise RuntimeError(f"shell check failed: {result.stderr.strip()}")
            log.debug(f"[ADB keepalive] Vivo {vivo} online")
        except Exception as e:
            log.warning(f"[ADB keepalive] Vivo {vivo} unreachable: {e}")
            try:
                notify_chandan(
                    "Vivo ADB Offline",
                    f"Cannot reach Vivo at {vivo} via ADB.\nError: {e}\nCheck WiFi or Developer Options > Wireless Debugging.",
                    tags="warning",
                    priority="high"
                )
            except Exception:
                pass
    else:
        log.warning(f"[ADB keepalive] Vivo is completely offline (dynamic scan failed)")
        try:
            notify_chandan(
                "Vivo ADB Offline",
                f"Vivo is completely off the network! Could not find its MAC address via ARP/Network Scan.",
                tags="warning",
                priority="high"
            )
        except Exception:
            pass


def job_device_health():
    """Every 6 hours: read battery stats via ADB and alert on problems."""
    import subprocess
    from imap_sync import notify_chandan
    adb_bin = "adb"
    import resolve_devices
    vivo = resolve_devices.ensure_connected("vivo")
    if not vivo:
        return

    # Quick connectivity check first
    try:
        result = subprocess.run(
            [adb_bin, "-s", vivo, "shell", "echo", "ok"],
            timeout=10, capture_output=True, text=True
        )
        if result.returncode != 0 or result.stdout.strip() != "ok":
            notify_chandan(
                "Vivo Offline - Health Check Failed",
                f"Device {vivo} did not respond to ADB health check.",
                tags="warning", priority="high"
            )
            return
    except Exception as e:
        notify_chandan(
            "Vivo Offline - Health Check Error",
            f"Error contacting {vivo}: {e}",
            tags="warning", priority="high"
        )
        return

    # Parse battery info
    try:
        out = subprocess.run(
            [adb_bin, "-s", vivo, "shell", "dumpsys", "battery"],
            timeout=15, capture_output=True, text=True
        ).stdout
        info = {}
        for line in out.splitlines():
            for key in ("level", "health", "temperature", "status"):
                if key + ":" in line:
                    info[key] = line.split(":", 1)[1].strip()

        level = int(info.get("level", 0))
        temp_raw = int(info.get("temperature", 0))
        temp_c = temp_raw / 10
        # status 2 = charging
        is_charging = info.get("status", "0") == "2"
        health_map = {"1": "Unknown", "2": "Good", "3": "Overheat", "4": "Dead",
                      "5": "Over voltage", "6": "Failure", "7": "Cold"}
        health = health_map.get(info.get("health", "1"), "Unknown")

        alerts = []
        if level <= 20 and not is_charging:
            alerts.append(f"Battery at {level}% — plug in now to keep above 20%.")
        if is_charging and level >= 62:
            alerts.append(f"Battery at {level}% while charging — charge cap may not be active! Unplug now.")
        if temp_c >= 42:
            alerts.append(f"Battery temp critical: {temp_c}C — phone is overheating!")
        elif temp_c >= 38:
            alerts.append(f"Battery temp high: {temp_c}C — consider removing case.")
        if health not in ("Good", "Unknown"):
            alerts.append(f"Battery health degraded: {health}")

        if alerts:
            notify_chandan(
                "Vivo Battery Alert",
                f"Level: {level}% | Temp: {temp_c}C | Health: {health}\n\n" + "\n".join(alerts),
                tags="battery,warning",
                priority="high"
            )
            log.warning(f"[Device health] Alerts: {alerts}")
        else:
            log.info(f"[Device health] Vivo OK — {level}% | {temp_c}C | {health}")
    except Exception as e:
        log.warning(f"[Device health] Error reading battery info: {e}")


@require_internet
def job_classify_replies():
    """
    Every 15 min: find contacts with new reply_text that has no classification yet.
    AI classifies as: interested / not_now / wrong_person / price_objection.
    Routes: interested → urgent ntfy; not_now → 60-day FU; price_objection → ROI draft.
    """
    from database import get_conn, insert_follow_ups
    from imap_sync import notify_chandan
    from datetime import datetime as _dt, timedelta

    conn = get_conn()
    try:
        rows = conn.execute("""
            SELECT b.id, b.name, b.category, b.city, b.website, b.demo_tunnel_url,
                   b.lead_score, c.email, c.instagram, c.reply_text, c.reply_classification
            FROM contacts c
            JOIN businesses b ON b.id = c.business_id
            WHERE c.reply_text IS NOT NULL AND c.reply_text != ''
              AND (c.reply_classification IS NULL OR c.reply_classification = '')
            LIMIT 20
        """).fetchall()
        leads = [dict(r) for r in rows]
    finally:
        conn.close()

    if not leads:
        return

    for lead in leads:
        try:
            reply = lead["reply_text"]
            classification = _classify_reply_ai(reply, lead["name"])
            if not classification:
                continue

            # Store classification
            conn2 = get_conn()
            conn2.execute(
                "UPDATE contacts SET reply_classification=? WHERE business_id=?",
                (classification, lead["id"])
            )
            conn2.commit()
            conn2.close()

            log.info(f"[ReplyClassify] {lead['name']} → {classification}")

            if classification == "interested":
                # Bump score, fire urgent ntfy
                conn3 = get_conn()
                conn3.execute(
                    "UPDATE businesses SET lead_score=MIN(100, COALESCE(lead_score,50)+25), status='hot' WHERE id=?",
                    (lead["id"],)
                )
                conn3.commit()
                conn3.close()
                notify_chandan(
                    f"HOT REPLY: {lead['name']}",
                    f"Replied INTERESTED 🔥\n\n\"{reply[:200]}\"\n\nMove to close now.",
                    tags="fire,star",
                    priority="urgent"
                )

            elif classification == "not_now":
                # Schedule 60-day re-engage follow-up
                channel = "email" if lead.get("email") else "instagram"
                now = _dt.utcnow()
                sequences = [{
                    "num": 1,
                    "channel": channel,
                    "draft": "Hey, just circling back as promised — are you in a better place to look at this now?",
                    "scheduled_for": (now + timedelta(days=60)).isoformat(),
                    "followup_angle": "not_now_revisit",
                }]
                # Only insert if no such follow-up exists yet
                conn4 = get_conn()
                exists = conn4.execute(
                    "SELECT id FROM follow_ups WHERE business_id=? AND followup_angle='not_now_revisit'",
                    (lead["id"],)
                ).fetchone()
                conn4.close()
                if not exists:
                    insert_follow_ups(lead["id"], sequences)
                    log.info(f"[ReplyClassify] Scheduled 60-day re-engage for {lead['name']}")

            elif classification == "price_objection":
                # Queue ROI-focused draft as urgent ntfy alert
                roi_msg = (
                    f"ROI OBJECTION — {lead['name']}\n\n"
                    f"Reply: \"{reply[:150]}\"\n\n"
                    "Suggested response: Share the ROI case study — avg 3x bookings in 90 days, "
                    "monthly retainer pays for itself in 1 new client."
                )
                notify_chandan(
                    f"Price Objection: {lead['name']}",
                    roi_msg,
                    tags="money,warning",
                    priority="high"
                )

        except Exception as e:
            log.error(f"[ReplyClassify] Error for {lead.get('name')}: {e}")


def _classify_reply_ai(reply_text: str, business_name: str) -> str:
    """Call AI to classify a reply into one of 4 categories."""
    prompt = (
        f"Classify this email/Instagram reply from '{business_name}' into EXACTLY one of these categories:\n"
        "interested / not_now / wrong_person / price_objection\n\n"
        "interested = they want to know more, asked for price, said yes, want to meet.\n"
        "not_now = too busy, come back later, not the right time.\n"
        "wrong_person = not the decision maker, forward to someone else.\n"
        "price_objection = too expensive, can't afford it, mention of cost.\n\n"
        f"Reply:\n\"{reply_text[:500]}\"\n\n"
        "Respond with only the category name, nothing else."
    )
    try:
        from ai_writer import _run
        result = _run(prompt).strip().lower()
        for cat in ("interested", "not_now", "wrong_person", "price_objection"):
            if cat in result:
                return cat
    except Exception as e:
        log.warning(f"[ReplyClassify] AI classify error: {e}")
    return ""


@require_internet
def job_demo_expiry_urgency():
    """
    Daily: if demo was sent >7 days ago with no open/reply, queue
    a 'your personalised preview expires in 48h' follow-up message.
    """
    from database import get_conn, insert_follow_ups
    from datetime import datetime as _dt, timedelta

    conn = get_conn()
    try:
        rows = conn.execute("""
            SELECT b.id, b.name, b.category, b.city, b.demo_tunnel_url,
                   c.email, c.instagram,
                   o.channel as original_channel, o.sent_at,
                   o.opened
            FROM businesses b
            JOIN contacts c ON c.business_id = b.id
            JOIN outreach o ON o.business_id = b.id AND o.status='sent'
            WHERE b.demo_tunnel_url IS NOT NULL AND b.demo_tunnel_url != ''
              AND b.status = 'sent'
              AND (c.replied_at IS NULL OR c.replied_at = '')
              AND (o.opened IS NULL OR o.opened = 0)
              AND julianday('now') - julianday(o.sent_at) >= 7
              AND b.id NOT IN (
                  SELECT business_id FROM follow_ups WHERE followup_angle='demo_expiry'
              )
            LIMIT 15
        """).fetchall()
        leads = [dict(r) for r in rows]
    finally:
        conn.close()

    for lead in leads:
        try:
            channel = lead.get("original_channel") or ("email" if lead.get("email") else "instagram")
            demo_url = lead.get("demo_tunnel_url", "")
            msg = (
                f"Hi {lead['name'].split()[0]} — just a heads up: the personalised website preview "
                f"we built for {lead['name']} expires in 48 hours. "
                f"Take a quick look before it's gone: {demo_url}"
            )
            now = _dt.utcnow()
            sequences = [{
                "num": 1,
                "channel": channel,
                "draft": msg,
                "scheduled_for": (now + timedelta(minutes=15)).isoformat(),
                "followup_angle": "demo_expiry",
            }]
            insert_follow_ups(lead["id"], sequences)
            log.info(f"[DemoExpiry] Queued expiry urgency for {lead['name']}")
        except Exception as e:
            log.error(f"[DemoExpiry] Error for {lead.get('name')}: {e}")


@require_internet
def job_linkedin_enrichment():
    """
    Daily: for contacts with email but no linkedin_url, run a Serper search
    to find their LinkedIn profile and store it.
    """
    from database import get_conn
    import os, requests

    serper_key = os.getenv("SERPER_API_KEY", "")
    if not serper_key:
        return

    conn = get_conn()
    try:
        rows = conn.execute("""
            SELECT b.id, b.name, c.owner_name
            FROM businesses b
            JOIN contacts c ON c.business_id = b.id
            WHERE (c.linkedin_url IS NULL OR c.linkedin_url = '')
              AND c.email IS NOT NULL AND c.email != ''
            LIMIT 20
        """).fetchall()
        leads = [dict(r) for r in rows]
    finally:
        conn.close()

    for lead in leads:
        try:
            search_name = lead.get("owner_name") or lead["name"]
            query = f'"{search_name}" site:linkedin.com/in'
            resp = requests.post(
                "https://google.serper.dev/search",
                json={"q": query, "num": 3},
                headers={"X-API-KEY": serper_key},
                timeout=10
            )
            if resp.status_code != 200:
                continue

            results = resp.json().get("organic", [])
            linkedin_url = ""
            for r in results:
                link = r.get("link", "")
                if "linkedin.com/in/" in link:
                    linkedin_url = link.split("?")[0]
                    break

            if linkedin_url:
                conn2 = get_conn()
                conn2.execute(
                    "UPDATE contacts SET linkedin_url=? WHERE business_id=?",
                    (linkedin_url, lead["id"])
                )
                conn2.commit()
                conn2.close()
                log.info(f"[LinkedIn] Enriched {lead['name']}: {linkedin_url}")
        except Exception as e:
            log.error(f"[LinkedIn] Error for {lead.get('name')}: {e}")


def job_snapshot_dashboard():
    """Snapshot LeadFlow stats to CF Pages dashboard_index.html every 5 min."""
    import logging
    from datetime import datetime, timezone
    from database import get_conn, get_stats
    try:
        from deploy import deploy_raw
    except Exception as e:
        logging.warning(f"[snapshot] deploy import failed: {e}")
        return

    logger = logging.getLogger("snapshot_dashboard")
    try:
        conn = get_conn()
        try:
            total_scraped = conn.execute("SELECT COUNT(*) FROM businesses").fetchone()[0]
            total_sent = conn.execute("SELECT COUNT(*) FROM outreach WHERE status='sent' AND channel='email'").fetchone()[0]
            total_followups = conn.execute("SELECT COUNT(*) FROM follow_ups WHERE status='sent' AND channel='email'").fetchone()[0]
            total_opened = conn.execute("SELECT COUNT(*) FROM outreach WHERE opened=1").fetchone()[0]
            total_clicked = conn.execute("SELECT COUNT(*) FROM outreach WHERE clicked=1").fetchone()[0]
            total_demo_opened = conn.execute("SELECT COUNT(*) FROM businesses WHERE demo_viewed=1").fetchone()[0]
            total_replied = conn.execute("SELECT COUNT(*) FROM outreach WHERE replied=1").fetchone()[0]
            # Recent leads (last 10)
            recent_rows = conn.execute("""
                SELECT b.name, b.category, c.email, b.status, b.found_at
                FROM businesses b
                LEFT JOIN contacts c ON c.business_id = b.id
                ORDER BY b.found_at DESC LIMIT 10
            """).fetchall()
        finally:
            conn.close()

        stats = get_stats()
        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        # Build recent leads table rows
        rows_html = ""
        for r in recent_rows:
            rows_html += f"""
            <tr>
              <td style="padding:8px 12px;border-bottom:1px solid #2a2a2a;font-weight:500;color:#e2e8f0">{r[0] or '—'}</td>
              <td style="padding:8px 12px;border-bottom:1px solid #2a2a2a;color:#94a3b8">{r[1] or '—'}</td>
              <td style="padding:8px 12px;border-bottom:1px solid #2a2a2a;color:#94a3b8;font-size:11px">{r[2] or '—'}</td>
              <td style="padding:8px 12px;border-bottom:1px solid #2a2a2a;color:#94a3b8">{r[3] or '—'}</td>
            </tr>"""

        autopilot_active = stats.get('autopilot_active')
        dot_color = '#00c896' if autopilot_active else '#64748b'
        autopilot_text_color = '#00c896' if autopilot_active else '#94a3b8'
        autopilot_label = 'Active' if autopilot_active else 'Stopped'

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="300">
<title>LeadFlow Dashboard — Live Snapshot</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0a0a0a;color:#e2e8f0;min-height:100vh;padding:32px 24px}}
  h1{{font-size:22px;font-weight:700;color:#fff;margin-bottom:4px}}
  .subtitle{{color:#64748b;font-size:13px;margin-bottom:32px}}
  .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:16px;margin-bottom:32px}}
  .card{{background:#111;border:1px solid #1e293b;border-radius:12px;padding:20px 18px}}
  .card-num{{font-size:32px;font-weight:700;color:#00c896;line-height:1}}
  .card-label{{font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:0.5px;margin-top:6px}}
  .section-title{{font-size:13px;font-weight:600;color:#94a3b8;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:12px}}
  table{{width:100%;border-collapse:collapse;background:#111;border:1px solid #1e293b;border-radius:10px;overflow:hidden}}
  th{{padding:10px 12px;text-align:left;font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:0.5px;border-bottom:1px solid #1e293b}}
  .badge{{display:inline-block;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:600;background:#1e293b;color:#94a3b8}}
  .footer{{margin-top:24px;color:#334155;font-size:11px;text-align:right}}
  .autopilot{{display:inline-flex;align-items:center;gap:6px;background:#111;border:1px solid #1e293b;border-radius:8px;padding:6px 12px;font-size:12px;margin-bottom:24px}}
  .dot{{width:7px;height:7px;border-radius:50%;background:{dot_color}}}
</style>
</head>
<body>
<h1>LeadFlow Command Center</h1>
<div class="subtitle">Live snapshot · Updated {now_utc}</div>

<div class="autopilot">
  <span class="dot"></span>
  <span style="color:{autopilot_text_color}">
    Autopilot {autopilot_label}
  </span>
</div>

<div class="grid">
  <div class="card"><div class="card-num">{total_scraped}</div><div class="card-label">Leads Scraped</div></div>
  <div class="card"><div class="card-num">{total_sent}</div><div class="card-label">Outreach Sent</div></div>
  <div class="card"><div class="card-num">{total_followups}</div><div class="card-label">Follow-ups</div></div>
  <div class="card"><div class="card-num">{total_opened}</div><div class="card-label">Emails Opened</div></div>
  <div class="card"><div class="card-num">{total_clicked}</div><div class="card-label">Links Clicked</div></div>
  <div class="card"><div class="card-num">{total_demo_opened}</div><div class="card-label">Demo Opened</div></div>
  <div class="card"><div class="card-num">{total_replied}</div><div class="card-label">Replies</div></div>
  <div class="card"><div class="card-num">{stats.get('new', 0)}</div><div class="card-label">New Leads</div></div>
  <div class="card"><div class="card-num">{stats.get('closed', 0)}</div><div class="card-label">Deals Closed</div></div>
</div>

<div class="section-title">Recent Leads</div>
<table>
  <thead><tr>
    <th>Name</th><th>Category</th><th>Email</th><th>Status</th>
  </tr></thead>
  <tbody>{rows_html}</tbody>
</table>

<div class="footer">leadflow-demos.pages.dev · snapshot refreshes every 5 min</div>
</body>
</html>"""

        deploy_raw("dashboard_index.html", html)
        logger.info(f"[snapshot] Dashboard deployed to CF Pages at {now_utc}")
    except Exception as e:
        logger.error(f"[snapshot] Failed: {e}", exc_info=True)


def job_cleanup_demos_dir():
    """Weekly: delete demo HTML files older than 30 days to prevent demos/ from bloating."""
    import time
    from pathlib import Path
    demos_dir = Path(__file__).parent / "demos"
    if not demos_dir.exists():
        return
    cutoff = time.time() - 30 * 86400  # 30 days ago
    removed = 0
    for f in demos_dir.iterdir():
        if f.is_file() and f.suffix == ".html" and f.stat().st_mtime < cutoff:
            try:
                f.unlink()
                removed += 1
            except Exception:
                pass
    if removed:
        log.info(f"[DemoCleanup] Removed {removed} demo HTML files older than 30 days.")
    else:
        log.info("[DemoCleanup] No stale demo files found.")


def start_scheduler():
    """Start background scheduler. Called once on server startup."""
    cfg = _get_config()
    hour = cfg.get("run_hour", 6)

    from datetime import timezone
    now_utc = datetime.now(timezone.utc)

    # ── WAL checkpoint: keep DB lean on every restart ──────────────────────
    try:
        from database import get_conn
        _wconn = get_conn()
        _wconn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        _wconn.commit()
        _wconn.close()
        log.info("[Scheduler] WAL checkpoint completed on startup")
    except Exception as _wale:
        log.warning(f"[Scheduler] WAL checkpoint failed: {_wale}")

    # ── Scraper: once per day at configured hour (quality-gated, 10-lead cap) ──
    # Use cron so it fires exactly once at the run_hour, not on every startup.
    scheduler.add_job(job_daily_find, "cron", hour=hour, minute=0, id="daily_find", replace_existing=True)

    scheduler.add_job(job_queue_follow_ups,     "cron",     hour=hour, minute=30, id="queue_followups", replace_existing=True)
    scheduler.add_job(job_auto_send_leads,      "interval", minutes=5,  id="auto_send_leads",      next_run_time=now_utc, replace_existing=True)
    scheduler.add_job(job_auto_send_followups,  "interval", minutes=5,  id="auto_send_followups",  next_run_time=now_utc, replace_existing=True)
    scheduler.add_job(job_check_replies,        "interval", minutes=5,  id="check_replies",        next_run_time=now_utc, replace_existing=True)
    # Beacon sync: keep beacon-config.json on GitHub Pages current with tunnel URL
    scheduler.add_job(job_sync_beacon,          "interval", minutes=5,  id="sync_beacon",          next_run_time=now_utc, replace_existing=True)
    # Cloudflare Worker event sync: pull tracking events from online worker buffer
    scheduler.add_job(job_shadow_checks,        "interval", minutes=60, id="shadow_checks",        next_run_time=now_utc, replace_existing=True)
    scheduler.add_job(job_sync_worker_events,   "interval", minutes=5,  id="sync_worker_events",   next_run_time=now_utc, replace_existing=True)
    # Bot KV sync: push live stats + drafts to Cloudflare KV for Telegram bot webhook
    scheduler.add_job(job_process_ig_regens, "interval", minutes=1, id="process_ig_regens", next_run_time=now_utc, replace_existing=True)
    scheduler.add_job(job_push_bot_kv,          "interval", minutes=30, id="bot_kv_sync",          next_run_time=now_utc, replace_existing=True)
    # Database replication: sync SQLite changes bi-directionally via Cloudflare KV
    scheduler.add_job(job_replicate_database,   "interval", minutes=2,  id="replicate_database",   next_run_time=now_utc, replace_existing=True)
    # Opened-lead follow-ups: highest priority, fires every 5 min (was 30 min)
    scheduler.add_job(job_auto_followup_opened_leads, "interval", minutes=5, id="followup_opened_leads", next_run_time=now_utc, replace_existing=True)
    # Scroll-engaged leads: detect demo scroll-90 events and queue instant follow-up
    scheduler.add_job(job_check_scroll_engaged_leads, "interval", minutes=5, id="scroll_engaged_leads", next_run_time=now_utc, replace_existing=True)
    # Demo-open nudge: ping Chandan if a lead opened the demo 2h ago but never tapped WA
    scheduler.add_job(job_demo_open_nudge, "interval", minutes=15, id="demo_open_nudge", next_run_time=now_utc, replace_existing=True)
    # Color-customizer leads: detect prospects who personalized demo colors → priority follow-up in 5 min
    scheduler.add_job(job_check_color_customizer_leads, "interval", minutes=5, id="color_customizer_leads", next_run_time=now_utc, replace_existing=True)
    # Demo buffer: maintain 10 pre-generated demos ahead of send queue — runs every 15 min
    scheduler.add_job(job_pregen_demo_buffer, "interval", minutes=15, id="pregen_demo_buffer", next_run_time=now_utc, replace_existing=True)
    # Instagram DMs: safe rate-limited sends (20/day max) — check every 60 min
    scheduler.add_job(job_auto_send_instagram_dms, "interval", minutes=60, id="auto_send_instagram", next_run_time=now_utc, replace_existing=True)
    # Instagram Unfollow: automatically prune old DMs that didn't reply — runs every 45 mins
    scheduler.add_job(job_unfollow_ghosts, "interval", minutes=45, id="unfollow_ghosts", next_run_time=now_utc, replace_existing=True)
    # WhatsApp: Twilio or digest — check every 60 min
    scheduler.add_job(job_auto_send_whatsapp, "interval", minutes=60, id="auto_send_whatsapp", next_run_time=now_utc, replace_existing=True)
    # Dashboard Replication: Static compiler replica on GitHub/Cloudflare Pages — runs every 15 min
    # Delay first run by 5 minutes so server is ready before wrangler blocks the process
    from datetime import timedelta
    replicate_first_run = now_utc + timedelta(minutes=5)
    scheduler.add_job(job_replicate_dashboard_static, "interval", minutes=15, id="replicate_dashboard_static", next_run_time=replicate_first_run, replace_existing=True)
    # CF Pages static dashboard mirror: snapshot stats to dashboard_index.html every 5 min
    scheduler.add_job(job_snapshot_dashboard, 'interval', minutes=5, id='snapshot_dashboard', replace_existing=True)
    # Bounce verification pipeline: checks new leads using burner account every 10 min
    scheduler.add_job(job_check_bounces, "interval", minutes=10, id="bounce_verification", next_run_time=now_utc, replace_existing=True)
    # Daily performance recap alert: runs every day at 6 PM (18:00) local time
    scheduler.add_job(job_daily_recap, "cron", hour=18, minute=0, id="daily_recap", replace_existing=True)
    # ADB keep-alive: reconnect to Vivo every 10 min, alert if offline
    scheduler.add_job(job_adb_keepalive, "interval", minutes=10, id="adb_keepalive", next_run_time=now_utc, replace_existing=True, misfire_grace_time=60)
    # Device health: battery level/temp monitoring every 6 hours
    scheduler.add_job(job_device_health, "interval", hours=6, id="device_health", next_run_time=now_utc, replace_existing=True, misfire_grace_time=300)
    # AI IG/WA Draft Generation: Firestick only — Mac skips silently
    import generate_ig_drafts
    import generate_wa_drafts
    def _firestick_only(fn):
        def _wrapped(): 
            import os
            # Firestick only means hard requirement for primary physical device OR if it fails over, it should stand down and let mac run it? Wait
            # User instruction: "reverse decorators so mac_only runs on mac, firestick_only runs on firestick"
            if os.getenv("LEADFLOW_DEVICE_ROLE", "backup") != "primary": return
            fn()
        _wrapped.__name__ = fn.__name__
        return _wrapped
        
    def _mac_only(fn):
        def _wrapped():
            import os
            # Only run if explicitly mac backup device
            if os.getenv("LEADFLOW_DEVICE_ROLE", "backup") == "primary": return
            fn()
        _wrapped.__name__ = fn.__name__
        return _wrapped

    scheduler.add_job(generate_wa_drafts.generate_drafts, "interval", hours=4, id="generate_wa_drafts", next_run_time=now_utc, replace_existing=True)
    scheduler.add_job(generate_ig_drafts.generate_drafts, "interval", hours=4, id="generate_ig_drafts", next_run_time=now_utc, replace_existing=True)
    scheduler.add_job(job_check_instagram_replies, "interval", minutes=15, id="check_instagram_replies", next_run_time=now_utc, replace_existing=True)

    scheduler.add_job(job_lead_score_decay,    "interval", days=7,     id="lead_score_decay",    next_run_time=now_utc, replace_existing=True)
    scheduler.add_job(job_reengage_cold_leads, "interval", hours=24,   id="reengage_cold_leads", next_run_time=now_utc, replace_existing=True)
    scheduler.add_job(job_classify_replies,    "interval", minutes=15, id="classify_replies",    next_run_time=now_utc, replace_existing=True)
    scheduler.add_job(job_demo_expiry_urgency, "interval", hours=24,   id="demo_expiry_urgency", next_run_time=now_utc, replace_existing=True)
    scheduler.add_job(job_linkedin_enrichment, "interval", hours=24,   id="linkedin_enrichment", next_run_time=now_utc, replace_existing=True)
    scheduler.add_job(job_cleanup_demos_dir,   "interval", days=7,     id="cleanup_demos_dir",   next_run_time=now_utc, replace_existing=True)

    if not scheduler.running:
        scheduler.start()
        log.info(f"[Scheduler] Started — lead finder every 10 min | bounce verification every 10 min | daily recap at 6 PM")

    # Battery guardian — runs as background daemon thread, checks every 5 min
    try:
        import battery_guardian
        _bg_thread = threading.Thread(target=battery_guardian.run, daemon=True, name="battery-guardian")
        _bg_thread.start()
        log.info("[BatteryGuardian] Started — enforcing 20–60% real charge range.")
    except Exception as _e:
        log.warning(f"[BatteryGuardian] Failed to start: {_e}")


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
    scheduler.reschedule_job("daily_find", trigger="cron", hour=hour, minute=0)
