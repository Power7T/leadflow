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
if not log.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    log.addHandler(handler)

scheduler = BackgroundScheduler(timezone="UTC")

_leads_send_lock = threading.Lock()
_followups_send_lock = threading.Lock()


def get_active_network_name():
    try:
        import subprocess
        cmd = ["sshpass", "-p", "root", "ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=2", "root@192.168.1.10", "iwinfo | grep ESSID | grep -v unknown | head -n 1"]
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
        topic = os.getenv("NTFY_TOPIC", "leadflow-chandan-secret")
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
    except Exception as e:
        log.error(f"[Scheduler] Failed to send ntfy sent notification: {e}")


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
    if is_primary_active():
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

    # ── Daily scrape cap: 10 qualified leads total ─────────────────────────
    DAILY_SCRAPE_CAP = 10  # Backlog is large — 10 quality leads/day is plenty
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
    from database import get_conn, insert_follow_ups
    from ai_writer import write_follow_up_sequence

    conn = get_conn()
    try:
        # fix #2: was filtering on found_at (scrape date). Now correctly filters on
        # the actual sent_at from the outreach table so 3-day window starts at send time.
        rows = conn.execute("""
            SELECT b.*, c.email, c.instagram
            FROM businesses b
            LEFT JOIN contacts c ON c.business_id = b.id
            JOIN outreach o ON o.business_id = b.id
            WHERE b.status = 'sent'
              AND o.channel = 'email'
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
        try:
            demo_url = lead.get("demo_tunnel_url", "")
            sequences = write_follow_up_sequence(lead, demo_url)
            insert_follow_ups(lead["id"], sequences)
            log.info(f"[Scheduler]   -> Queued {len(sequences)} follow-ups for {lead['name']}")
        except Exception as e:
            log.error(f"[Scheduler] Follow-up gen error for {lead['name']}: {e}")


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
            SELECT b.*, c.email, c.instagram
            FROM businesses b
            JOIN outreach o ON o.business_id = b.id
            LEFT JOIN contacts c ON c.business_id = b.id
            WHERE o.opened = 1
              AND b.status = 'sent'
              AND b.id NOT IN (SELECT DISTINCT business_id FROM follow_ups)
              AND c.email IS NOT NULL
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
            demo_url = lead.get("demo_tunnel_url", "")
            sequences = write_follow_up_sequence(lead, demo_url, is_hot_lead=True)

            # Schedule opened-lead follow-ups IMMEDIATELY — they just opened, strike now:
            now = datetime.utcnow()
            for seq in sequences:
                if seq["channel"] == "email":
                    if seq["num"] == 1:
                        seq["scheduled_for"] = (now + timedelta(minutes=5)).isoformat()
                        # Override subject to signal this is a hot-open reply
                        if seq.get("draft"):
                            draft = seq["draft"]
                            lines = draft.strip().splitlines()
                            if lines and not lines[0].lower().startswith("subject:"):
                                seq["draft"] = f"Subject: Re: {lead.get('name', 'your site')}\n\n" + draft
                    elif seq["num"] == 2:
                        seq["scheduled_for"] = (now + timedelta(days=2)).isoformat()
                    elif seq["num"] == 3:
                        seq["scheduled_for"] = (now + timedelta(days=5)).isoformat()
                elif seq["channel"] == "instagram":
                    seq["scheduled_for"] = (now + timedelta(hours=6)).isoformat()
            insert_follow_ups(lead["id"], sequences)
            log.info(f"[Scheduler]   -> Queued {len(sequences)} HOT follow-ups for {lead['name']} (FU1 in 5 min)")


            # Send ntfy alert so operator knows
            try:
                import requests as _req
                _ntfy_t = __import__('os').getenv('NTFY_TOPIC', 'leadflow-chandan-secret')  # fix #12
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


@require_internet
def job_auto_send_instagram_dms():
    """
    Hourly: find leads where email was sent 5+ days ago with no reply
    and they have an Instagram handle. Send up to 5 DMs per run.
    Respects the 20/day safety cap in instagram_sender.py.
    """
    if not _instagram_send_lock.acquire(blocking=False):
        log.info("[Instagram] Job already running — skipping")
        return
    try:
        from instagram_sender import can_send_instagram, send_instagram_dm, get_instagram_daily_sent_count
        if not can_send_instagram():
            return

        from database import get_conn
        conn = get_conn()
        try:
            rows = conn.execute("""
                SELECT b.id, b.name, c.instagram,
                       o.draft AS email_draft
                FROM businesses b
                JOIN contacts c ON c.business_id = b.id
                JOIN outreach o ON o.business_id = b.id
                WHERE b.status = 'sent'
                  AND o.channel = 'instagram'
                  AND o.status = 'draft'
                  AND c.instagram IS NOT NULL AND c.instagram != ''
                  AND o.sent_at <= datetime('now', '-5 days')
                ORDER BY b.lead_score DESC
                LIMIT 5
            """).fetchall()
            leads = [dict(r) for r in rows]
        finally:
            conn.close()

        if not leads:
            log.info("[Instagram] No eligible leads for DMs right now")
            return

        log.info(f"[Instagram] Sending DMs to {len(leads)} leads ({get_instagram_daily_sent_count()}/20 used today)")
        for lead in leads:
            handle = lead["instagram"].strip().lstrip("@")
            draft  = lead.get("email_draft") or ""
            if not handle or not draft:
                continue
            ok = send_instagram_dm(handle, draft)
            if ok:
                conn2 = get_conn()
                try:
                    conn2.execute("""
                        UPDATE outreach SET status='sent', sent_at=datetime('now'), is_autopilot=1
                        WHERE business_id=? AND channel='instagram'
                    """, (lead["id"],))
                    conn2.commit()
                finally:
                    conn2.close()
                log.info(f"[Instagram] Sent DM to @{handle} for {lead['name']}")
            if not can_send_instagram():
                log.info("[Instagram] Daily cap reached — stopping")
                break
    except Exception as e:
        log.error(f"[Instagram] Job error: {e}")
    finally:
        _instagram_send_lock.release()


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
            SELECT DISTINCT b.*, c.email
            FROM tracking_events te
            JOIN businesses b ON b.id = te.business_id
            LEFT JOIN contacts c ON c.business_id = b.id
            WHERE te.event_type IN ('engage:scroll_90', 'engage:modal_shown', 'click')
              AND b.status = 'sent'
              AND c.email IS NOT NULL
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

            demo_url = lead.get("demo_tunnel_url", "")
            sequences = write_follow_up_sequence(lead, demo_url, is_hot_lead=True)
            # Immediate schedule: FU1 in 3 minutes (scroll = live interest RIGHT NOW)
            now = datetime.utcnow()
            for seq in sequences:
                if seq["channel"] == "email":
                    if seq["num"] == 1:
                        seq["scheduled_for"] = (now + timedelta(minutes=3)).isoformat()
                    elif seq["num"] == 2:
                        seq["scheduled_for"] = (now + timedelta(days=2)).isoformat()
                    elif seq["num"] == 3:
                        seq["scheduled_for"] = (now + timedelta(days=5)).isoformat()
                elif seq["channel"] == "instagram":
                    seq["scheduled_for"] = (now + timedelta(hours=6)).isoformat()
            insert_follow_ups(lead["id"], sequences)
            log.info(f"[Scheduler]   -> Queued SCROLL-PRIORITY follow-up for {lead['name']} (FU1 in 3 min)")


            # Push notification
            try:
                import requests as _req
                _ntfy_t2 = __import__('os').getenv('NTFY_TOPIC', 'leadflow-chandan-secret')  # fix #12
                _req.post(
                    f"https://ntfy.sh/{_ntfy_t2}",
                    data=f"🔥 {lead['name']} scrolled 90%+ through their demo — follow-up queued in 3 min!".encode(),

                    headers={"Title": "LeadFlow - HOT Demo Engagement!", "Tags": "fire,chart_with_upwards_trend", "Priority": "high"},
                    timeout=5,
                )
            except Exception:
                pass
        except Exception as e:
            log.error(f"[Scheduler] Scroll-engaged FU error for {lead['name']}: {e}")



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
        token = os.getenv("SECRET_TOKEN", "lf_sec_9e21808ccce4d37")
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
    """
    Bi-directional database replication via Cloudflare KV.
    Runs every 2 minutes.
    """
    try:
        from sync_engine import run_sync_cycle
        run_sync_cycle()
        log.info("[Scheduler] Database replication cycle completed.")
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


def is_primary_active() -> bool:
    """Check if we are NOT the active leader.
    
    If this device claims leadership successfully, it is the leader, so we return False (execute the job).
    If another active device holds leadership, we return True (skip).
    """
    import os, requests, time
    
    device_name = os.getenv("LEADFLOW_DEVICE_NAME", "")
    if not device_name:
        import sys
        if sys.platform == "darwin":
            device_name = "mac"
        else:
            device_name = "firestick"

    public_url = os.getenv("LEADFLOW_PUBLIC_URL", "")
    token = os.getenv("LEADFLOW_SECRET_TOKEN", os.getenv("SECRET_TOKEN", "lf_sec_9e21808ccce4d37"))
    
    if not public_url:
        # If offline/isolated, default to executing on firestick, skipping on mac
        return device_name != "firestick"

    try:
        r = requests.post(
            f"{public_url}/api/leadership/claim?device={device_name}",
            headers={"X-Secret-Token": token},
            timeout=5
        )
        if r.status_code == 200:
            data = r.json()
            is_leader = data.get("success", False)
            if is_leader:
                # We successfully claimed/renewed leadership
                return False
            else:
                # Another active device holds leadership
                return True
    except Exception as e:
        log.warning(f"[Scheduler] Failed to claim leadership: {e}")
        # On connection failure:
        # - Firestick is always the primary hardware, so default to executing (return False)
        # - Mac should default to skipping (return True)
        return device_name != "firestick"

    return True


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
                            
                            _ntfy_t = os.getenv('NTFY_TOPIC', 'leadflow-chandan-secret')
                            msg = ""
                            if actual_type == "open":
                                msg = f"✉️ Email opened: {biz_name}"
                            elif actual_type == "click":
                                msg = f"🖱️ Demo clicked: {biz_name}"
                            elif actual_type == "scroll_90":
                                msg = f"🔥 Hot Lead! {biz_name} read 90% of demo"
                            elif actual_type == "modal_shown":
                                msg = f"💬 Contact Modal Opened: {biz_name}"
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
    if is_primary_active():
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
        send_window_end = cfg.get("send_window_end", 11)
        preferred_days = _json.loads(cfg.get("preferred_days", "[1,2,3]")) if cfg.get("preferred_days") else [1, 2, 3]

        
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
                ORDER BY b.lead_score DESC
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
                ORDER BY b.lead_score DESC
                LIMIT 300
            """).fetchall()
            backlog_leads = [dict(r) for r in backlog_rows]

        finally:
            conn.close()

        # Score both pools with ICS
        for c in fresh_leads:
            c["_ics"] = compute_ics(c, c)
            c["_is_fresh"] = True
        for c in backlog_leads:
            c["_ics"] = compute_ics(c, c)
            c["_is_fresh"] = False

        # Sort each pool by ICS, then merge: fresh leads ALWAYS go first
        fresh_leads.sort(key=lambda x: x["_ics"], reverse=True)
        backlog_leads.sort(key=lambda x: x["_ics"], reverse=True)
        candidates = fresh_leads + backlog_leads

        if fresh_leads:
            log.info(f"[Scheduler] \U0001f195 {len(fresh_leads)} fresh leads scraped today — they get FIRST pick of today's slots")
        log.info(f"[Scheduler] Candidate pool: {len(fresh_leads)} fresh + {len(backlog_leads)} backlog = {len(candidates)} total")

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
                        server = smtplib.SMTP_SSL("smtp.gmail.com", 465)
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
                    from deploy import is_live
                    demo_url = lead.get("demo_tunnel_url", "")
                    if demo_url and not is_live(demo_url, wait=10):
                        log.error(f"  -> Demo not live yet for {lead['name']} — skipping send this round")
                        continue

                    # Get the draft and subject options
                    conn2 = get_conn()
                    try:
                        draft_row = conn2.execute("SELECT draft, subject_options FROM outreach WHERE business_id=? AND channel='email'", (lead["id"],)).fetchone()
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
                    if has_site:
                        log.info(f"  -> Writing website audit pitch for {lead['name']}...")
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
                        conn2.commit()
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
    if is_primary_active():
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
        send_window_end = cfg.get("send_window_end", 11)
        preferred_days = _json.loads(cfg.get("preferred_days", "[1,2,3]")) if cfg.get("preferred_days") else [1, 2, 3]
        
        # Enforce safe daily cold email limit to prevent spam blocking
        sent_today = get_emails_sent_today()
        if sent_today >= max_auto_send:
            log.info(f"[Scheduler] Daily auto-send limit ({max_auto_send}) reached. Skipping auto follow-ups today (already sent: {sent_today}).")
            return

        conn = get_conn()
        try:
            rows = conn.execute("""
                SELECT f.*, c.email, b.demo_tunnel_url, b.city, b.country, b.timezone,
                       b.assigned_sender_email
                FROM follow_ups f
                JOIN businesses b ON b.id = f.business_id
                LEFT JOIN contacts c ON c.business_id = b.id
                WHERE f.status = 'pending' AND datetime(f.scheduled_for) <= datetime('now')
                  AND b.status IN ('sent', 'replied', 'interested')
                ORDER BY f.scheduled_for ASC
                LIMIT 20
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

                # ── Send-Time Check for Follow-ups (relaxed) ──
                # Follow-ups go to leads who already showed interest — we send
                # them regardless of send window so they are never left overdue.
                # Only enforce time window for sequence #1 to avoid early-morning
                # interruptions; subsequent follow-ups send any time.
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
                        server = smtplib.SMTP_SSL("smtp.gmail.com", 465)
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
    scheduler.add_job(job_sync_worker_events,   "interval", minutes=5,  id="sync_worker_events",   next_run_time=now_utc, replace_existing=True)
    # Database replication: sync SQLite changes bi-directionally via Cloudflare KV
    scheduler.add_job(job_replicate_database,   "interval", minutes=2,  id="replicate_database",   next_run_time=now_utc, replace_existing=True)
    # Opened-lead follow-ups: highest priority, fires every 5 min (was 30 min)
    scheduler.add_job(job_auto_followup_opened_leads, "interval", minutes=5, id="followup_opened_leads", next_run_time=now_utc, replace_existing=True)
    # Scroll-engaged leads: detect demo scroll-90 events and queue instant follow-up
    scheduler.add_job(job_check_scroll_engaged_leads, "interval", minutes=5, id="scroll_engaged_leads", next_run_time=now_utc, replace_existing=True)
    # Demo buffer: maintain 10 pre-generated demos ahead of send queue — runs every 15 min
    scheduler.add_job(job_pregen_demo_buffer, "interval", minutes=15, id="pregen_demo_buffer", next_run_time=now_utc, replace_existing=True)
    # Instagram DMs: safe rate-limited sends (20/day max) — check every 60 min
    scheduler.add_job(job_auto_send_instagram_dms, "interval", minutes=60, id="auto_send_instagram", next_run_time=now_utc, replace_existing=True)
    # WhatsApp: Twilio or digest — check every 60 min
    scheduler.add_job(job_auto_send_whatsapp, "interval", minutes=60, id="auto_send_whatsapp", next_run_time=now_utc, replace_existing=True)
    # Dashboard Replication: Static compiler replica on GitHub/Cloudflare Pages — runs every 15 min
    # Delay first run by 5 minutes so server is ready before wrangler blocks the process
    from datetime import timedelta
    replicate_first_run = now_utc + timedelta(minutes=5)
    scheduler.add_job(job_replicate_dashboard_static, "interval", minutes=15, id="replicate_dashboard_static", next_run_time=replicate_first_run, replace_existing=True)
    # Bounce verification pipeline: checks new leads using burner account every 10 min
    scheduler.add_job(job_check_bounces, "interval", minutes=10, id="bounce_verification", next_run_time=now_utc, replace_existing=True)
    # Daily performance recap alert: runs every day at 6 PM (18:00) local time
    scheduler.add_job(job_daily_recap, "cron", hour=18, minute=0, id="daily_recap", replace_existing=True)

    if not scheduler.running:
        scheduler.start()
        log.info(f"[Scheduler] Started — lead finder every 10 min | bounce verification every 10 min | daily recap at 6 PM")


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
