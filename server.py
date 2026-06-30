#!/usr/bin/env python3.12
import sys
import shutil as _shutil
import logging
import logging.handlers  # needed for RotatingFileHandler
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

# ── Structured logging (writes to server.log + stderr) ──────────────────────
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        # fix #16: use RotatingFileHandler so server.log never grows unbounded
        logging.handlers.RotatingFileHandler(
            "server.log", maxBytes=10 * 1024 * 1024, backupCount=3, encoding="utf-8"
        ),
        logging.StreamHandler(sys.stderr),
    ],
)
log = logging.getLogger("leadflow")

import json
import asyncio
import uuid
import functools
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn

from database import (
    init_db, get_leads, get_all_leads_for_kanban, get_all_active_leads, get_stats,
    update_business_status, insert_outreach, mark_sent,
    record_tracking_event, insert_follow_ups, get_all_follow_ups,
    mark_follow_up_sent, insert_deal, get_analytics, get_pending_follow_ups,
    get_conn, get_lead_by_id, get_facebook_leads,
)
from finder import search_places, get_place_details, clean_website_url, is_chain_or_too_big, search_places_async, get_place_details_async
from extractor import extract_contacts
from analyzer import score_website, detect_gap, full_audit
from database import insert_business, insert_contacts
from ai_writer import generate_all, write_follow_up_sequence, rewrite_message
from sender import send_email, parse_subject_body, suppress
from demo_generator import generate_demo_html, generate_demo_html_stream
from scorer import score_lead
from multi_finder import check_domain_available, scrape_yelp
from tracker import PIXEL_GIF
from scheduler import start_scheduler, stop_scheduler, save_scheduler_config
from deploy import deploy_demo, deploy_raw, demo_url_for, is_live, slug_for
def ctx(request: Request, page: str, **kwargs) -> dict:
    """
    Helper to build template context for Jinja2 rendering.
    Includes the request object, current page identifier, and any extra data.
    """
    context = {"request": request, "page": page}
    context.update(kwargs)
    return context


BASE      = Path(__file__).parent
DEMOS_DIR = BASE / "demos"
DEMOS_DIR.mkdir(exist_ok=True)
DEMO_CACHE: dict[int, str] = {}

# Per-demo tunnel registry: bid → {port, server, proc, url}
DEMO_TUNNELS: dict[int, dict] = {}

import re as _re
import socket as _socket
import threading as _threading
import http.server as _http_server
import socketserver as _socketserver
import subprocess as _subprocess

_demo_proc = None
_leadflow_tunnel_proc = None


def _free_port() -> int:
    with _socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _start_demo_tunnel(bid: int, html: str) -> str:
    """Publish the demo to GitHub Pages via the single deploy pipeline.
    Returns the public URL, or "" if the push failed."""
    from database import get_conn
    conn = get_conn()
    row = conn.execute("SELECT name FROM businesses WHERE id=?", (bid,)).fetchone()
    name = row["name"] if row else str(bid)
    result = deploy_demo(bid, name, html)
    if not result["ok"]:
        print(f"[deploy] demo {bid} push failed: {result['error']}")
        conn.close()
        return ""
    conn.execute("UPDATE businesses SET demo_tunnel_url=? WHERE id=?", (result["url"], bid))
    conn.commit()
    conn.close()
    return result["url"]


def _kill_all_cloudflared():
    """Kill every cloudflared process on the system to prevent zombie tunnel buildup."""
    import subprocess
    try:
        subprocess.run(["pkill", "-f", "cloudflared"], capture_output=True)
    except Exception:
        pass
    # Clear stale URL cache files so we don't reuse dead tunnel URLs
    for f in ["/tmp/leadflow-tunnel-url.txt", "/tmp/leadflow-demo-tunnel-url.txt"]:
        try:
            Path(f).unlink(missing_ok=True)
        except Exception:
            pass


def _start_leadflow_tunnel() -> str:
    """Start cloudflared tunnel for the main LeadFlow app on port 8765. Returns URL."""
    global _leadflow_tunnel_proc

    # If our own tracked process is still alive, reuse it
    if _leadflow_tunnel_proc and _leadflow_tunnel_proc.poll() is None:
        try:
            url = Path("/tmp/leadflow-tunnel-url.txt").read_text().strip()
            if url.startswith("https://"):
                return url
        except Exception:
            pass

    _cf_bin = _shutil.which("cloudflared") or "/opt/homebrew/bin/cloudflared"
    if not _shutil.which("cloudflared"):
        return ""
    proc = _subprocess.Popen(
        [_cf_bin, "tunnel", "--url", "http://127.0.0.1:8765"],
        stderr=_subprocess.PIPE, stdout=_subprocess.DEVNULL, text=True,
    )
    _leadflow_tunnel_proc = proc

    url = ""
    import time
    deadline = time.time() + 35
    while time.time() < deadline:
        line = proc.stderr.readline()
        if not line:
            break
        m = _re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
        if m:
            url = m.group(0)
            break

    if url:
        Path("/tmp/leadflow-tunnel-url.txt").write_text(url)
    return url


def _restore_demo_tunnels():
    """On startup, flush any demos that were built locally but never pushed
    (the old silent-push bug stranded several), so no prospect hits a 404."""
    from deploy import _publish
    try:
        result = _publish(".gitkeep", "")   # commits & pushes everything pending
        if result["ok"]:
            print("[deploy] startup sync OK — stranded demos flushed to GitHub Pages")
        else:
            print(f"[deploy] startup sync failed: {result['error']}")
    except Exception as e:
        print(f"[deploy] startup sync error: {e}")


async def update_tunnel_urls():
    import re
    from database import get_conn
    
    tunnel_url = ""
    for _ in range(30):
        try:
            with open("/tmp/leadflow-demo-tunnel-url.txt") as f:
                tunnel_url = f.read().strip()
                if tunnel_url.startswith("http"):
                    break
        except Exception:
            pass
        await asyncio.sleep(1)
        
    if not tunnel_url:
        return
        
    print(f"Updating drafts to new tunnel URL: {tunnel_url}")
    conn = get_conn()
    
    rows = conn.execute("SELECT id, draft FROM outreach WHERE status != 'sent'").fetchall()
    for row in rows:
        if row["draft"]:
            new_draft = re.sub(r'https://[a-zA-Z0-9\-]+\.trycloudflare\.com', tunnel_url, row["draft"])
            if new_draft != row["draft"]:
                conn.execute("UPDATE outreach SET draft = ?, final_message = ? WHERE id = ?", (new_draft, new_draft, row["id"]))
                
    rows = conn.execute("SELECT id, draft FROM follow_ups WHERE status = 'pending'").fetchall()
    for row in rows:
        if row["draft"]:
            new_draft = re.sub(r'https://[a-zA-Z0-9\-]+\.trycloudflare\.com', tunnel_url, row["draft"])
            if new_draft != row["draft"]:
                conn.execute("UPDATE follow_ups SET draft = ? WHERE id = ?", (new_draft, row["id"]))
                
    conn.commit()
    conn.close()

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _demo_proc
    # ── Kill ALL stale cloudflared processes before starting fresh ones ──
    # This prevents zombie tunnel buildup which causes hundreds of browser
    # login windows to open when the internet drops and reconnects.
    _kill_all_cloudflared()

    init_db()
    start_scheduler()
    asyncio.create_task(update_tunnel_urls())

    # Start demo server on 8766 if not already running
    try:
        s = _socket.create_connection(("127.0.0.1", 8766), timeout=0.5)
        s.close()
    except OSError:
        _demo_proc = _subprocess.Popen(
            [sys.executable, str(BASE / "demo_server.py")],
            stdout=_subprocess.DEVNULL, stderr=_subprocess.DEVNULL,
        )

    # Start cloudflared tunnels in background threads
    _threading.Thread(target=_start_leadflow_tunnel, daemon=True, name="cf-leadflow").start()
    _threading.Thread(target=_restore_demo_tunnels, daemon=True, name="cf-demos").start()

    yield
    stop_scheduler()
    # Clean shutdown — kill all tunnels
    _kill_all_cloudflared()
    if _demo_proc:
        _demo_proc.terminate()


app = FastAPI(lifespan=lifespan)
from fastapi.middleware.cors import CORSMiddleware

# fix #6: restrict CORS to localhost and the live tunnel URL.
# allow_origins=["*"] + allow_credentials=True is rejected by browsers and is a security hole.
_ALLOWED_ORIGINS = [
    "http://localhost:8765",
    "http://127.0.0.1:8765",
    "http://localhost:3000",
]
# If a tunnel URL is set in .env (e.g. LEADFLOW_PUBLIC_URL=https://xxx.trycloudflare.com) add it
import os as _os
_pub = _os.getenv("LEADFLOW_PUBLIC_URL", "")
if _pub:
    _ALLOWED_ORIGINS.append(_pub.rstrip("/"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")


def ctx(request: Request, page: str, **extra):
    return {"request": request, "page": page, "stats": get_stats(), **extra}


# ── Find businesses ────────────────────────────────────────────────────────

@app.get("/find", response_class=HTMLResponse)
def find_page(request: Request):
    cfg = _get_scheduler_cfg()
    return templates.TemplateResponse(request, "find.html", ctx(request, "find", sched=cfg))


# ── Dashboard & Autopilot ──────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
@app.get("/autopilot", response_class=HTMLResponse)
def home(request: Request):
    from database import get_conn, get_emails_sent_today
    conn = get_conn()
    try:
        cfg = conn.execute("SELECT * FROM scheduler_config LIMIT 1").fetchone()
        cfg = dict(cfg) if cfg else {}
        
        # 1. Recent cold outreach emails sent by autopilot
        sent_rows = conn.execute("""
            SELECT b.id, b.name, b.category, b.website, b.demo_tunnel_url,
                   c.email, o.channel, o.sent_at, o.opened, o.clicked, o.replied
            FROM outreach o
            JOIN businesses b ON b.id = o.business_id
            LEFT JOIN contacts c ON c.business_id = b.id
            WHERE o.status = 'sent' AND o.channel = 'email' AND o.is_autopilot = 1
            ORDER BY o.sent_at DESC LIMIT 15
        """).fetchall()
        recent_sent = [dict(r) for r in sent_rows]
        
        # 2. Recent leads found by autopilot (status is new or approved)
        found_rows = conn.execute("""
            SELECT b.id, b.name, b.category, b.website, b.lead_score, b.found_at, b.status,
                   c.email, c.instagram
            FROM businesses b
            LEFT JOIN contacts c ON c.business_id = b.id
            WHERE b.status IN ('new', 'approved')
            ORDER BY b.found_at DESC LIMIT 15
        """).fetchall()
        recent_found = [dict(r) for r in found_rows]
        
        # 3. Autopilot statistics
        stats_data = {
            "total_scraped": conn.execute("SELECT COUNT(*) FROM businesses").fetchone()[0],
            "total_sent": conn.execute("SELECT COUNT(*) FROM outreach WHERE status='sent' AND channel='email'").fetchone()[0],
            "total_followups": conn.execute("SELECT COUNT(*) FROM follow_ups WHERE status='sent' AND channel='email'").fetchone()[0],
            "total_replied": conn.execute("SELECT COUNT(*) FROM outreach WHERE replied=1").fetchone()[0],
            "total_opened": conn.execute("SELECT COUNT(*) FROM outreach WHERE opened=1").fetchone()[0],
            "total_clicked": conn.execute("SELECT COUNT(*) FROM outreach WHERE clicked=1").fetchone()[0],
            "total_demo_opened": conn.execute("SELECT COUNT(*) FROM businesses WHERE demo_viewed=1").fetchone()[0],
        }
        
        # 4. Pending Initials (Top 5)
        # First try to get leads that already have a draft scheduled
        pending_init_rows = conn.execute("""
            SELECT b.name, c.email, b.assigned_sender_email, o.scheduled_at
            FROM businesses b
            JOIN contacts c ON c.business_id = b.id
            JOIN outreach o ON o.business_id = b.id
            WHERE o.status = 'draft' AND o.channel = 'email' AND o.scheduled_at IS NOT NULL
            ORDER BY o.scheduled_at ASC
            LIMIT 5
        """).fetchall()
        
        # If we need more, backfill from the general backlog (new/approved)
        if len(pending_init_rows) < 5:
            backfill_limit = 5 - len(pending_init_rows)
            backfill_rows = conn.execute("""
                SELECT b.name, c.email, b.assigned_sender_email, 'Pending AI drafting' as scheduled_at
                FROM businesses b
                LEFT JOIN contacts c ON c.business_id = b.id
                WHERE b.status IN ('new', 'approved') AND b.lead_score >= 25 AND c.email IS NOT NULL AND c.email != ''
                AND b.id NOT IN (SELECT business_id FROM outreach WHERE status = 'draft')
                ORDER BY b.lead_score DESC
                LIMIT ?
            """, (backfill_limit,)).fetchall()
            pending_init_rows.extend(backfill_rows)
            
        pending_initials = [dict(r) for r in pending_init_rows]
        
        # 5. Pending Follow-ups
        pending_fup_rows = conn.execute("""
            SELECT b.name, c.email, b.assigned_sender_email, f.scheduled_for
            FROM follow_ups f
            JOIN businesses b ON b.id = f.business_id
            LEFT JOIN contacts c ON c.business_id = b.id
            WHERE f.status = 'pending' AND b.status = 'sent' AND c.email IS NOT NULL
            ORDER BY f.scheduled_for ASC LIMIT 5
        """).fetchall()
        pending_followups = []
        for r in pending_fup_rows:
            d = dict(r)
            # Format ISO datetime (2026-06-25T06:31:31.854912) to YYYY-MM-DD HH:MM:SS
            if d["scheduled_for"]:
                d["scheduled_for"] = d["scheduled_for"].replace("T", " ").split(".")[0]
            pending_followups.append(d)
        # 6. Stuck/Pending counts for warnings
        stuck_approved_count = conn.execute("SELECT COUNT(*) FROM businesses b LEFT JOIN contacts c ON c.business_id=b.id WHERE b.status='approved' AND (c.email IS NULL OR c.email='')").fetchone()[0]
        total_pending_followups = conn.execute("SELECT COUNT(*) FROM follow_ups WHERE status='pending'").fetchone()[0]
    finally:
        conn.close()
    
    sent_today = get_emails_sent_today()
    html = templates.get_template("index.html").render(**ctx(
        request=request,
        page="home",
        cfg=cfg,
        sent_today=sent_today,
        recent_sent=recent_sent,
        recent_found=recent_found,
        stats=stats_data,
        pending_initials=pending_initials,
        pending_followups=pending_followups,
        stuck_approved_count=stuck_approved_count,
        total_pending_followups=total_pending_followups,
    ))
    return HTMLResponse(content=html)

@app.get("/autopilot/logs")
def get_autopilot_logs():
    try:
        import re
        BASE_DIR = Path(__file__).parent
        # Check multiple possible log locations (Mac: server.log, Firestick: server_run.log)
        candidates = [
            BASE_DIR / "server.log",
            BASE_DIR / "server_run.log",
            Path("/tmp/leadflow_server.log"),
        ]
        for log_path in candidates:
            if log_path.exists() and log_path.stat().st_size > 0:
                lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
                clean_lines = []
                seen = set()
                for line in lines[-300:]:
                    line = re.sub(r'\s{10,}', ' ', line).strip()
                    # Deduplicate lines (Firestick logs each line twice due to dual scheduler)
                    if line and line not in seen:
                        seen.add(line)
                        clean_lines.append(line)
                if clean_lines:
                    return {"logs": "\n".join(clean_lines[-80:])}
    except Exception as e:
        return {"logs": f"Error reading logs: {e}"}
    return {"logs": "No logs available yet — scheduler may still be starting up."}

@app.post("/autopilot/toggle")
async def autopilot_toggle(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()
    enabled = bool(data.get("enabled", False))
    from database import get_conn
    conn = get_conn()
    try:
        conn.execute("UPDATE scheduler_config SET enabled = ?", (int(enabled),))
        conn.commit()
    finally:
        conn.close()
    
    # AUTO IG DM DISABLED — using manual DM queue (/ig-manual) to avoid ban risk
    # scheduler.add_job(job_auto_send_instagram_dms, "interval", minutes=60, id="auto_send_instagram", next_run_time=now_utc, replace_existing=True)
    # Reload/start scheduler if enabled
    try:
        import scheduler
        if enabled:
            if not scheduler.scheduler.running:
                scheduler.start_scheduler()
            # Trigger immediate background execution when enabled
            background_tasks.add_task(scheduler.job_auto_send_leads)
            background_tasks.add_task(scheduler.job_auto_send_followups)
        else:
            # Note: We keep scheduler running for reply check intervals,
            # but setting enabled=0 in database stops daily_find from executing.
            pass
    except Exception:
        pass
        
    return JSONResponse({"ok": True, "enabled": enabled})

@app.post("/autopilot/trigger/{job_id}")
async def autopilot_trigger(job_id: str, background_tasks: BackgroundTasks):
    import scheduler
    if job_id == "find":
        background_tasks.add_task(scheduler.job_daily_find, force=True)
        return JSONResponse({"ok": True, "message": "Daily Lead Finder triggered successfully in the background."})
        
    jobs = {
        "send_leads": (scheduler.job_auto_send_leads, "Auto-Send Outreach"),
        "send_followups": (scheduler.job_auto_send_followups, "Auto-Send Followups"),
        "check_replies": (scheduler.job_check_replies, "Check Replies/Opt-Outs")
    }
    if job_id not in jobs:
        return JSONResponse({"ok": False, "error": "Invalid job ID"}, status_code=400)
    
    func, label = jobs[job_id]
    background_tasks.add_task(func)
    return JSONResponse({"ok": True, "message": f"{label} triggered successfully in the background."})


# ── Settings ───────────────────────────────────────────────────────────────

@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    from dotenv import dotenv_values
    env = dotenv_values(".env")
    return templates.TemplateResponse(request, "settings.html", ctx(request, "settings", env=env))

@app.post("/settings/save")
async def settings_save(request: Request):
    data = await request.json()
    try:
        from dotenv import set_key
        env_file = BASE / ".env"
        for k, v in data.items():
            if v is not None:
                set_key(str(env_file), k, v)
        # Reload environment into python
        from dotenv import load_dotenv
        load_dotenv(override=True)
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

@app.post("/settings/test-gmail")
def settings_test_gmail():
    import os, smtplib, imaplib
    from sender import get_all_sender_accounts
    accounts = get_all_sender_accounts()
    if not accounts:
        return JSONResponse({"ok": False, "error": "Email or Password not set."})
    
    imap_server = os.getenv("IMAP_SERVER", "imap.gmail.com")
    errors = []
    successes = []
    
    for email, pwd in accounts:
        try:
            # Test SMTP
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(email, pwd)
            
            # Test IMAP
            with imaplib.IMAP4_SSL(imap_server) as mail:
                mail.login(email, pwd)
                
            successes.append(email)
        except Exception as e:
            errors.append(f"{email}: {e}")
            
    if errors:
        err_msg = "; ".join(errors)
        if successes:
            return JSONResponse({"ok": False, "error": f"Connected: {', '.join(successes)}. Failed: {err_msg}"})
        else:
            return JSONResponse({"ok": False, "error": f"Failed: {err_msg}"})
            
    return JSONResponse({"ok": True})


@app.post("/settings/test-gemini")
async def settings_test_gemini(request: Request):
    body = await request.json()
    keys_str = body.get("keys", "")
    keys = [k.strip() for k in keys_str.split(",") if k.strip()]
    if not keys:
        return JSONResponse({"ok": False, "error": "No keys provided"}, status_code=400)

    import urllib.request, json, time, ssl
    results = []
    # fix #7: use verified SSL context
    try:
        import certifi
        context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        context = ssl.create_default_context()

    payload = json.dumps({
        "contents": [{"parts": [{"text": "say hello"}]}]
    }).encode()

    for idx, key in enumerate(keys):
        masked = key[:6] + "..." + key[-4:] if len(key) > 10 else "Invalid format"
        success = False

        # Try this key up to 2 times before marking it failed
        for attempt in range(2):
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={key}"
                req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=10, context=context) as resp:
                    data = json.loads(resp.read().decode('utf-8'))

                if "candidates" in data and len(data["candidates"]) > 0:
                    results.append({"index": idx + 1, "key": masked, "status": "active", "error": None})
                    success = True
                    break
                else:
                    results.append({"index": idx + 1, "key": masked, "status": "invalid", "error": "Unexpected response"})
                    success = True
                    break
            except Exception as e:
                err_str = str(e)
                if attempt == 0:
                    # First failure — wait 1s and retry the same key
                    time.sleep(1.0)
                else:
                    # Second failure — classify and record
                    status = "invalid"
                    if "503" in err_str or "unavailable" in err_str.lower():
                        status = "exhausted"
                        error_msg = "Temporarily Unavailable (transient)"
                    elif "429" in err_str or "quota" in err_str.lower() or "limit" in err_str.lower():
                        status = "exhausted"
                        error_msg = "Quota exhausted / Rate limit hit"
                    elif "400" in err_str or "403" in err_str or "404" in err_str or "invalid" in err_str.lower():
                        error_msg = "Invalid API Key"
                    else:
                        error_msg = err_str[:80]
                    results.append({"index": idx + 1, "key": masked, "status": status, "error": error_msg})

    return {"ok": True, "results": results}


def _get_scheduler_cfg():
    try:
        from database import get_conn
        conn = get_conn()
        row = conn.execute("SELECT * FROM scheduler_config LIMIT 1").fetchone()
        conn.close()
        return dict(row) if row else {}
    except Exception:
        return {}


@app.get("/find/stream")
async def find_stream(niche: str, location: str, max_results: int = 20, source: str = "google", max_score: int = 70,
                      require_contact: bool = True, no_website_only: bool = False, max_rating: float = 5.0):
    async def generator():
        def send(msg: str, cls: str = ""):
            return f"data: {json.dumps({'type':'log','msg':msg,'cls':cls})}\n\n"

        try:
            yield send(f"Searching '{niche}' in {location} via {source}...", "dim")
            await asyncio.sleep(0.05)

            if source == "yelp":
                loop = asyncio.get_event_loop()
                places_data = await loop.run_in_executor(None, scrape_yelp, niche, location, max_results)
                saved = 0
                for biz in places_data:
                    name = biz.get("name", "Unknown")
                    yield send(f"Processing: {name}...", "dim")
                    website = clean_website_url(biz.get("website", ""))
                    if no_website_only and website:
                        yield send(f"  skipped (has website)", "dim")
                        continue
                    rating = biz.get("google_rating")
                    if rating and rating > max_rating:
                        yield send(f"  skipped (rating {rating} > {max_rating})", "dim")
                        continue
                    score = score_website(website) if website else 0
                    
                    # Detect if this is a high-ticket SaaS campaign target
                    cat_lower = niche.lower()
                    saas_niches = {"roof", "hvac", "solar", "plumb", "dent", "ortho", "gym", "fitness", "contractor", "electrician", "painter", "landscap"}
                    is_saas_campaign = any(kw in cat_lower for kw in saas_niches)

                    if not is_saas_campaign and score >= max_score:
                        yield send(f"  skipped (score >= {max_score})", "dim")
                        continue

                    if is_saas_campaign:
                        pitch_type = "leadflow_saas"
                        gap = "Opportunity for SaaS CRM, automated follow-ups, and lead-gen landing page"
                    else:
                        gap, pitch_type = detect_gap(website, score)

                    reviews = biz.get("google_reviews")
                    if is_chain_or_too_big(name, reviews):
                        yield send(f"  skipped (chain)", "dim")
                        continue
                    domain_info = check_domain_available(name) if not website else {}
                    contacts = extract_contacts(website, name, location)
                    if require_contact and not any([contacts.get("email"), contacts.get("instagram"),
                                 contacts.get("linkedin_url"), contacts.get("whatsapp")]):
                        yield send(f"  skipped (no contacts)", "dim")
                        continue

                    # Prepare and score business data
                    biz_payload = {**biz, "website": website, "website_score": score,
                                   "gap": gap, "pitch_type": pitch_type, "category": niche}
                    lead_score = score_lead(biz_payload, contacts)

                    business_data = {**biz_payload, "lead_score": lead_score,
                                     "domain_available": domain_info.get("domain") if domain_info.get("available") else None,
                                     "source": "yelp"}
                    bid = insert_business(business_data)
                    insert_contacts(bid, contacts)
                    yield send(f"  ✓ {name} | score={score}", "ok")
                    saved += 1
                    await asyncio.sleep(0.02)
                yield f"data: {json.dumps({'type':'done','count':saved})}\n\n"
                return

            # Google Maps or LinkedIn path
            search_query = niche
            if source == "linkedin":
                search_query = f"B2B {niche} companies"
                
            places = await search_places_async(search_query, location, max_results)
            if not places:
                yield f"data: {json.dumps({'type':'error','msg':'No results. Check niche/location or API key.'})}\n\n"
                return

            yield send(f"Found {len(places)} places. Fetching details...", "dim")
            saved = 0

            for place in places:
                name = place.get("name", "Unknown")
                yield send(f"Processing: {name}...", "dim")
                await asyncio.sleep(0.05)

                # Use details already fetched via new Places API, fallback if missing
                raw_url   = place.get("website") or ""
                phone     = place.get("phone") or place.get("international_phone_number") or place.get("formatted_phone_number", "")
                address   = place.get("address") or place.get("formatted_address", "")
                rating    = place.get("rating")
                reviews   = place.get("reviews") or place.get("user_ratings_total") or 0

                if raw_url == "" and phone == "" and address == "":
                    details   = await get_place_details_async(place["place_id"])
                    raw_url   = details.get("website", "")
                    phone     = details.get("international_phone_number") or details.get("formatted_phone_number", "")
                    address   = details.get("formatted_address", "")
                    rating    = details.get("rating")
                    reviews   = details.get("user_ratings_total") or 0

                website   = clean_website_url(raw_url)

                if no_website_only and website:
                    yield send(f"  skipped (has website)", "dim")
                    continue

                if rating and rating > max_rating:
                    yield send(f"  skipped (rating {rating} > {max_rating})", "dim")
                    continue

                if is_chain_or_too_big(name, reviews):
                    yield send(f"  skipped ({reviews} reviews — chain)", "dim")
                    continue

                loop = asyncio.get_event_loop()
                score = await loop.run_in_executor(None, score_website, website) if website else 0
                
                # Detect if this is a high-ticket SaaS campaign target
                cat_lower = niche.lower()
                saas_niches = {"roof", "hvac", "solar", "plumb", "dent", "ortho", "gym", "fitness", "contractor", "electrician", "painter", "landscap"}
                is_saas_campaign = any(kw in cat_lower for kw in saas_niches)

                if not is_saas_campaign and score >= max_score:
                    yield send(f"  skipped (score >= {max_score})", "dim")
                    continue

                if is_saas_campaign:
                    pitch_type = "leadflow_saas"
                    gap = "Opportunity for SaaS CRM, automated follow-ups, and lead-gen landing page"
                else:
                    gap, pitch_type = detect_gap(website, score)

                parts   = address.split(",")
                city    = parts[-3].strip() if len(parts) >= 3 else ""
                country = parts[-1].strip() if parts else ""

                domain_info = check_domain_available(name) if not website else {}
                contacts    = extract_contacts(website, name, location)

                if source == "linkedin":
                    if not contacts.get("linkedin_url"):
                        contacts["linkedin_url"] = f"https://linkedin.com/company/{name.lower().replace(' ', '-')}"
                        yield send(f"  generated linkedin profile: {contacts['linkedin_url']}", "dim")

                if require_contact and not any([contacts.get("email"), contacts.get("instagram"),
                            contacts.get("linkedin_url"), contacts.get("whatsapp"), phone]):
                    yield send(f"  skipped (no contacts)", "dim")
                    continue

                # Prepare and score business data
                biz_payload = {
                    "name": name, "category": niche, "address": address,
                    "city": city, "country": country, "phone": phone,
                    "website": website, "website_score": score,
                    "google_rating": rating, "google_reviews": reviews,
                    "gap": gap, "pitch_type": pitch_type
                }
                lead_score = score_lead(biz_payload, contacts)

                business_data = {
                    **biz_payload,
                    "lead_score": lead_score,
                    "domain_available": domain_info.get("domain") if domain_info.get("available") else None,
                    "source": source,
                    "maps_url": f"https://www.google.com/maps/place/?q=place_id:{place['place_id']}",
                }
                bid = insert_business(business_data)
                insert_contacts(bid, contacts)

                has_email = "✓" if contacts.get("email") else "✗"
                has_ig    = "✓" if contacts.get("instagram") else "✗"
                yield send(f"  ✓ {name} | id={bid} | score={lead_score} | web_score={score} | email={has_email} ig={has_ig}", "ok")
                saved += 1
                await asyncio.sleep(0.02)

            yield f"data: {json.dumps({'type':'done','count':saved})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type':'error','msg':str(e)})}\n\n"

    return StreamingResponse(generator(), media_type="text/event-stream")


# ── Scheduler config ───────────────────────────────────────────────────────

@app.post("/scheduler/save")
async def scheduler_save(request: Request):
    data = await request.json()
    niches    = [n.strip() for n in data.get("niches", "").split(",") if n.strip()]
    locations = [l.strip() for l in data.get("locations", "").split(",") if l.strip()]
    save_scheduler_config(niches, locations, data.get("enabled", False),
                          int(data.get("hour", 6)), int(data.get("max_per", 20)),
                          data.get("source", "google_maps"), int(data.get("max_score", 70)),
                          bool(data.get("auto_send_enabled", False)), int(data.get("max_auto_send", 10)))
    return JSONResponse({"ok": True})


# ── Miami Facebook Group Manual Leads ──────────────────────────────────────

@app.get("/miami-group", response_class=HTMLResponse)
def miami_group_page(request: Request):
    leads = get_facebook_leads()
    import json
    for l in leads:
        try:
            l["interactions"] = json.loads(l.get("interactions_json") or "[]")
        except:
            l["interactions"] = []
    return templates.TemplateResponse(request, "miami_group.html", ctx(request, "miami", leads=leads))


@app.post("/saas-leads/add")
async def add_miami_lead(request: Request):
    form_data = await request.form()
    website = form_data.get("website", "").strip()
    fb_link = form_data.get("fb_link", "").strip()
    campaign_mode = form_data.get("campaign_mode", "auto")
    
    if not website:
        return RedirectResponse("/miami-group?error=Website is required", status_code=303)
        
    if not website.startswith("http"):
        website = "https://" + website
        
    # Scrape website details
    import urllib.parse
    domain = urllib.parse.urlparse(website).netloc.replace("www.", "")
    
    # 1. Fetch website HTML
    from extractor import _fetch, extract_contacts
    from bs4 import BeautifulSoup
    import re
    
    try:
        html = _fetch(website, timeout=10)
    except Exception as e:
        html = ""
        
    # 2. Extract Business Name from title or domain
    business_name = ""
    if html:
        try:
            soup = BeautifulSoup(html, "lxml")
            title = soup.title.string if soup.title else ""
            if title:
                title = title.strip()
                for sep in ("|", "-", "—", "·"):
                    if sep in title:
                        parts = title.split(sep)
                        candidate = parts[0].strip()
                        if len(candidate) > 2 and len(candidate) < 50:
                            business_name = candidate
                            break
                if not business_name and len(title) < 50:
                    business_name = title
        except Exception:
            pass
            
    if not business_name:
        business_name = domain.split(".")[0].capitalize()
        
    # 3. Detect Niche/Category from title and content
    category = "Local Business"
    if html:
        try:
            visible_text = BeautifulSoup(html, "lxml").get_text(separator=' ').lower()
        except Exception:
            visible_text = html.lower()
            
        combined = (business_name + " " + visible_text).lower()
        niches = {
            "Cleaning": ["clean", "janitorial", "maid", "housekeeping", "laundry"],
            "Gym & Fitness": ["gym", "fitness", "crossfit", "yoga", "workout", "trainer"],
            "Dentist & Dental": ["dentist", "dental", "orthodontist"],
            "Medical & Clinic": ["clinic", "medical", "physio", "chiro", "spine", "doctor", "health"],
            "Restaurant & Cafe": ["restaurant", "food", "cafe", "coffee", "bakery", "dining"],
            "Plumber": ["plumber", "plumbing"],
            "Electrician": ["electrician", "electrical"],
            "Roofing": ["roofing", "roofer"],
            "HVAC": ["hvac", "air conditioning", "heating"],
            "Salon & Beauty": ["salon", "hair", "barber", "grooming", "beauty", "spa"],
            "Landscaping & Tree": ["landscaping", "tree service", "arborist"],
            "Real Estate": ["real estate", "realtor", "property management", "airbnb", "realty"],
            "Valet Laundry": ["laundry", "valet", "dry clean", "linens"],
            "Art & Decor": ["decor", "art", "interior design", "staging", "gallery", "artist", "painting"],
            "Trash & Waste": ["trash", "waste", "garbage", "junk", "dumpster"],
            "Handyman": ["handyman", "repair", "locksmith", "maintenance"]
        }
        for niche, keywords in niches.items():
            if any(re.search(r'\b' + re.escape(kw) + r'\b', combined) for kw in keywords):
                category = niche
                break
                
    # 4. Audit Website
    from analyzer import score_website, detect_gap
    web_score = score_website(website)
    gap, suggested_pitch = detect_gap(website, web_score)
    
    # 5. Extract Contacts (email, phone, instagram, linkedin, whatsapp, owner_name)
    contacts = {}
    try:
        contacts = extract_contacts(website, business_name, "Miami, FL")
    except Exception:
        pass
        
    # 6. Determine campaign path
    pitch_type = suggested_pitch
    if campaign_mode == "manual":
        pitch_types = form_data.getlist("pitch_types")
        if "leadflow_saas" in pitch_types and "website_new" in pitch_types:
            pitch_type = "both"
        elif "leadflow_saas" in pitch_types:
            pitch_type = "leadflow_saas"
        elif "website_new" in pitch_types:
            pitch_type = "website_new"
            
    elif campaign_mode == "auto":
        # Auto suggest based on website score:
        # Good website (>=70) -> promote SaaS CRM
        # Poor website (<40) -> promote website redesign
        # In-between (40-70) -> suggest BOTH (they have an ok site but could benefit from a redesign AND CRM)
        if web_score >= 70:
            pitch_type = "leadflow_saas"
        elif web_score < 40:
            pitch_type = "website_new"
        else:
            pitch_type = "both"
            
    if not gap or gap == "No website — losing customers who search online" and website:
        gap = f"Website scores {web_score}/100. Miami FB Group lead looking for clients."
        
    business_data = {
        "name": business_name,
        "category": category,
        "address": "Miami, FL, USA",
        "city": "Miami",
        "country": "USA",
        "phone": contacts.get("phone", contacts.get("whatsapp", "")),
        "website": website,
        "website_score": web_score,
        "google_rating": 0.0,
        "google_reviews": 0,
        "gap": gap,
        "pitch_type": pitch_type,
        "source": "facebook_miami",
        "maps_url": fb_link,
        "lead_score": 60 if pitch_type == "both" else 50,
    }
    
    bid = insert_business(business_data)
    
    contact_data = {
        "email": contacts.get("email"),
        "owner_name": contacts.get("owner_name"),
        "instagram": contacts.get("instagram"),
        "facebook": contacts.get("facebook"),
        "linkedin_url": contacts.get("linkedin_url"),
        "linkedin_name": contacts.get("linkedin_name"),
        "whatsapp": contacts.get("whatsapp", contacts.get("phone")),
    }
    insert_contacts(bid, contact_data)
    
    return RedirectResponse("/saas-leads?success=Manual lead scraped and added successfully", status_code=303)


# ── Leads review ───────────────────────────────────────────────────────────

@app.get("/leads", response_class=HTMLResponse)
def leads_page(request: Request):
    leads = get_all_active_leads()
    import json
    for l in leads:
        try:
            l["interactions"] = json.loads(l.get("interactions_json") or "[]")
        except:
            l["interactions"] = []
    return templates.TemplateResponse(request, "leads.html", ctx(request, "leads", leads=leads))
    
@app.get("/saas-leads", response_class=HTMLResponse)
def saas_leads_page(request: Request):
    all_leads = get_all_active_leads()
    saas_leads = [l for l in all_leads if l.get("pitch_type") in ("leadflow_saas", "both")]
    import json
    for l in saas_leads:
        try:
            l["interactions"] = json.loads(l.get("interactions_json") or "[]")
        except:
            l["interactions"] = []
    return templates.TemplateResponse(request, "saas_leads.html", ctx(request, "saas_leads", leads=saas_leads))


@app.get("/instagram-reach", response_class=HTMLResponse)
def instagram_reach_page(request: Request):
    all_leads = get_all_active_leads()
    ig_leads = [l for l in all_leads if l.get("pitch_type") == "instagram_reach" or l.get("source") == "instagram_reach"]
    import json
    for l in ig_leads:
        try:
            l["interactions"] = json.loads(l.get("interactions_json") or "[]")
        except:
            l["interactions"] = []
    return templates.TemplateResponse(request, "instagram_reach.html", ctx(request, "instagram_reach", leads=ig_leads))


# ── Instagram Manual DM Queue ──────────────────────────────────────────────

@app.get("/ig-manual", response_class=HTMLResponse)
def ig_manual_page(request: Request):
    conn = get_conn()
    try:
        rows = conn.execute("""
            SELECT b.id, b.name, b.category, b.lead_score, b.status,
                   b.demo_tunnel_url, b.ig_dm_sent, b.ig_dm_sent_at,
                   c.instagram
            FROM businesses b
            JOIN contacts c ON c.business_id = b.id
            WHERE c.instagram IS NOT NULL AND c.instagram != ''
            ORDER BY b.ig_dm_sent ASC, b.lead_score DESC
        """).fetchall()
    finally:
        conn.close()

    leads = []
    for r in rows:
        lead = dict(r)
        handle = (lead.get("instagram") or "").strip().lstrip("@")
        name   = lead.get("name", "")
        demo   = lead.get("demo_tunnel_url") or ""

        # Build demo link — use tunnel URL if available, else GitHub Pages demo
        if not demo or not demo.startswith("http"):
            safe_slug = "".join(c if c.isalnum() or c in "-_" else "-" for c in name.lower()).strip("-")
            demo = f"https://power7t.github.io/leadflow-demos/{safe_slug}.html"

        # Build DM message
        lead["dm_message"] = (
            f"Hey {name.split()[0]} 👋\n\n"
            f"I built a free custom website preview for {name} — thought you'd find it useful!\n\n"
            f"Check it out here: {demo}\n\n"
            f"No strings attached, just wanted to show you what's possible. Let me know what you think! 🚀"
        )
        lead["ig_dm_sent"] = lead.get("ig_dm_sent") or 0
        leads.append(lead)

    return templates.TemplateResponse(request, "ig_manual.html", ctx(request, "ig_manual", leads=leads))


@app.post("/ig-manual/mark-dm")
async def ig_mark_dm(request: Request):
    data = await request.json()
    bid  = int(data.get("business_id", 0))
    sent = int(data.get("sent", 1))
    if not bid:
        return JSONResponse({"ok": False, "error": "Missing business_id"})
    conn = get_conn()
    try:
        if sent:
            conn.execute(
                "UPDATE businesses SET ig_dm_sent=1, ig_dm_sent_at=datetime('now','localtime') WHERE id=?",
                (bid,)
            )
        else:
            conn.execute(
                "UPDATE businesses SET ig_dm_sent=0, ig_dm_sent_at=NULL WHERE id=?",
                (bid,)
            )
        conn.commit()
    finally:
        conn.close()
    return JSONResponse({"ok": True})


@app.get("/test-leads", response_class=HTMLResponse)
def test_leads_page(request: Request):
    from database import get_test_leads
    leads = get_test_leads()
    import json
    for l in leads:
        try:
            l["interactions"] = json.loads(l.get("interactions_json") or "[]")
        except:
            l["interactions"] = []
    return templates.TemplateResponse(request, "test_leads.html", ctx(request, "test_leads", leads=leads))


@app.post("/test-leads/run")
async def run_test_leads_triggers(request: Request):
    form_data = await request.form()
    niche = form_data.get("niche", "").strip()
    city  = form_data.get("city",  "").strip()

    if not niche or not city:
        return RedirectResponse("/test-leads?error=Please specify both Niche and City", status_code=303)

    # ── Niche-specific average ticket prices ─────────────────────────────────
    NICHE_TICKET = {
        "dentist": 320, "dental": 320, "orthodontist": 2800,
        "hvac": 275, "air conditioning": 275, "heating": 275,
        "roofing": 9500, "roofer": 9500,
        "plumbing": 220, "plumber": 220,
        "landscaping": 180, "lawn": 180, "landscaper": 180,
        "solar": 28000, "solar panel": 28000,
        "chiropractor": 120, "chiropractic": 120,
        "gym": 65, "fitness": 65, "personal trainer": 65,
        "lawyer": 1800, "attorney": 1800, "law": 1800,
        "remodeling": 14000, "remodel": 14000, "contractor": 5000,
        "electrician": 190, "electrical": 190,
        "financial": 600, "accountant": 400, "cpa": 400,
        "insurance": 900, "real estate": 6000, "realtor": 6000,
        "restaurant": 45, "cafe": 35,
    }
    niche_lower = niche.lower()
    avg_ticket = 200
    for key, price in NICHE_TICKET.items():
        if key in niche_lower:
            avg_ticket = price
            break

    # ── Google Maps click-share model ────────────────────────────────────────
    MONTHLY_SEARCHES = 1000          # conservative baseline for a local niche keyword
    CLICK_SHARE = {1: 0.29, 2: 0.17, 3: 0.11}  # 3-Pack rank → click share
    OUTSIDE_SHARE = 0.03             # rank 4+ combined
    CALL_CVR  = 0.28                 # click → phone call
    CLOSE_CVR = 0.40                 # call → booked customer

    try:
        loop = asyncio.get_event_loop()
        places = await loop.run_in_executor(None, search_places, niche, city, 5)

        if not places:
            return RedirectResponse(f"/test-leads?error=No businesses found in {city} for {niche}", status_code=303)

        # Top competitor = first place with a website (used for review/name comparison)
        top_name     = places[0].get("name", "top competitor")
        top_reviews  = int(places[0].get("reviews") or places[0].get("user_ratings_total") or 0)
        for p in places:
            if p.get("website"):
                top_name    = p.get("name")
                top_reviews = int(p.get("reviews") or p.get("user_ratings_total") or 0)
                break

        added = 0
        for idx, place in enumerate(places):
            name       = place.get("name", "Unknown")
            raw_web    = place.get("website") or ""
            phone      = (place.get("phone") or place.get("international_phone_number")
                          or place.get("formatted_phone_number") or "")
            address    = place.get("address") or place.get("formatted_address") or ""
            rating     = place.get("rating")
            reviews    = int(place.get("reviews") or place.get("user_ratings_total") or 0)
            place_id   = place.get("place_id") or ""
            maps_url   = (f"https://www.google.com/maps/place/?q=place_id:{place_id}" if place_id
                          else f"https://maps.google.com/?q={name.replace(' ', '+')}+{city.replace(' ', '+')}")
            rank       = idx + 1

            # ── Missed revenue math ───────────────────────────────────────────
            cur_share     = CLICK_SHARE.get(rank, OUTSIDE_SHARE)
            pack_avg      = sum(CLICK_SHARE.values()) / 3
            cur_customers = MONTHLY_SEARCHES * cur_share    * CALL_CVR * CLOSE_CVR
            pack_customers= MONTHLY_SEARCHES * pack_avg     * CALL_CVR * CLOSE_CVR
            if rank <= 3:
                # Show what they'd LOSE by dropping out of the 3-Pack
                outside_customers = MONTHLY_SEARCHES * OUTSIDE_SHARE * CALL_CVR * CLOSE_CVR
                missed_leads  = max(0, cur_customers - outside_customers)
            else:
                missed_leads  = max(0, pack_customers - cur_customers)
            missed_rev    = int(missed_leads * avg_ticket)


            # ── Review gap vs top competitor ──────────────────────────────────
            comp_reviews  = top_reviews if idx != 0 else int(
                places[1].get("reviews") or places[1].get("user_ratings_total") or 0
                if len(places) > 1 else 0)
            comp_name     = top_name if idx != 0 else (
                places[1].get("name", "2nd ranked") if len(places) > 1 else "competitors")
            review_gap    = max(0, comp_reviews - reviews)

            # ── Competitor Deficit — dollar-framed ────────────────────────────
            parts = []
            if rank > 3:
                parts.append(
                    f"At rank #{rank} you're missing ~{int(missed_leads)} new "
                    f"{niche_lower} inquiries/month worth ~${missed_rev:,} in lost revenue "
                    f"(${avg_ticket:,} avg ticket) — all going to your 3-Pack competitors."
                )
            else:
                parts.append(
                    f"Ranked #{rank} — one ranking slip drops you out of the 3-Pack entirely. "
                    f"The gap between rank #3 and #4 is ~${missed_rev:,}/month in booked "
                    f"{niche_lower} jobs at your avg ticket (${avg_ticket:,})."
                )
            if review_gap > 10:
                parts.append(
                    f"Review gap: {comp_name} has {comp_reviews} reviews vs your {reviews} "
                    f"({review_gap} more) — Google treats review count as a direct 3-Pack ranking signal."
                )
            if not raw_web:
                parts.append(
                    f"No website detected — {top_name} captures 100% of pre-call research "
                    f"traffic while customers searching online before calling will never find you."
                )
            deficit = " | ".join(parts)

            # ── Gap string (stored in lead 'gap' column) ──────────────────────
            if rank > 3:
                gap_str = (f"Ranked #{rank} on Google Maps "
                           f"(❌ Outside 3-Pack — est. ${missed_rev:,}/mo in lost {niche_lower} revenue).")
            else:
                gap_str = (f"Ranked #{rank} on Google Maps "
                           f"(⚠️ At risk of dropping from 3-Pack — ${missed_rev:,}/mo at stake).")

            # ── Website / score ───────────────────────────────────────────────
            website = clean_website_url(raw_web)
            score   = score_website(website) if website else 0

            # ── Contact extraction ────────────────────────────────────────────
            contacts = await loop.run_in_executor(None, extract_contacts, website, name, city)

            # ── Persist lead ──────────────────────────────────────────────────
            business_data = {
                "name": name, "category": niche, "address": address,
                "city": city, "country": "", "phone": phone,
                "website": website, "website_score": score,
                "google_rating": rating, "google_reviews": reviews,
                "gap": gap_str, "pitch_type": "both",
                "lead_score": score_lead({"website_score": score, "google_reviews": reviews}, contacts),
                "source": "test_leads", "maps_rank": rank,
                "competitor_deficit": deficit,
                "visual_preview_url": "Ready (Personalized visual transformation mockup generated)",
                "maps_url": maps_url,
                "intent_score": missed_rev,   # $/month at risk — used by pitch generator
            }
            bid = insert_business(business_data)
            insert_contacts(bid, contacts)

            # ── Deploy demo to GitHub Pages ───────────────────────────────────
            try:
                from database import get_lead_by_id
                full_lead = get_lead_by_id(bid)
                if full_lead:
                    demo_html = generate_demo_html(full_lead)
                    if demo_html:
                        deploy_res = deploy_demo(bid, name, demo_html)
                        if deploy_res.get("ok"):
                            real_url = deploy_res.get("url")
                            _c = get_conn()
                            _c.execute(
                                "UPDATE businesses SET visual_preview_url=?, demo_tunnel_url=? WHERE id=?",
                                (real_url, real_url, bid)
                            )
                            _c.commit()
                            _c.close()
            except Exception as deploy_err:
                print(f"[test-leads] deploy failed for {name}: {deploy_err}")

            added += 1

        return RedirectResponse(
            f"/test-leads?success=Successfully analyzed and added {added} high-intent leads in {city} for {niche}",
            status_code=303
        )

    except Exception as e:
        return RedirectResponse(f"/test-leads?error=Failed to execute conversion triggers: {str(e)}", status_code=303)


@app.post("/instagram-reach/add")
async def add_instagram_leads(request: Request):
    form_data = await request.form()
    leads_text = form_data.get("instagram_leads", "").strip()
    if not leads_text:
        return RedirectResponse("/instagram-reach?error=No Instagram leads provided", status_code=303)

    # Split by newlines/commas and strip whitespace
    import re
    lines = [line.strip() for line in re.split(r'[\n,]', leads_text) if line.strip()]

    import asyncio
    from database import insert_business, insert_contacts
    from extractor import scrape_instagram_profile

    added_count = 0
    errors = []

    loop = asyncio.get_event_loop()


    for line in lines:
        try:
            # Scrape Instagram profile details
            profile = await loop.run_in_executor(None, scrape_instagram_profile, line)
            if not profile or not profile.get("instagram"):
                errors.append(f"Could not parse or fetch profile for: {line}")
                continue
                
            # Parse followers size
            followers_str = profile.get("followers", "0").replace(",", "").replace(".", "").strip()
            followers_val = 0
            try:
                if "k" in followers_str.lower():
                    followers_val = int(float(followers_str.lower().replace("k", "")) * 1000)
                elif "m" in followers_str.lower():
                    followers_val = int(float(followers_str.lower().replace("m", "")) * 1000000)
                else:
                    followers_val = int(followers_str)
            except Exception:
                pass
                
            # Assign priority score
            lead_score = 50
            if followers_val > 100000:
                lead_score = 95
            elif followers_val > 10000:
                lead_score = 80
            elif followers_val > 5000:
                lead_score = 70
            elif followers_val > 1000:
                lead_score = 60
                
            # Store bio in gap, profile pic in maps_url, followers in google_reviews
            bus_id = insert_business({
                "name": profile["name"],
                "category": profile["category"],
                "website": f"https://www.instagram.com/{profile['instagram']}/",
                "gap": profile["bio"],
                "maps_url": profile["profile_pic"],
                "google_reviews": followers_val,
                "google_rating": 5.0,
                "source": "instagram_reach",
                "pitch_type": "instagram_reach",
                "status": "new",
                "lead_score": lead_score,
                "city": "Instagram",
                "country": "Online"
            })
            
            # Insert contacts details
            insert_contacts(bus_id, {
                "instagram": profile["instagram"],
                "email": ""
            })
            
            # Search for email in bio and update
            from extractor import EMAIL_RE
            bio_emails = EMAIL_RE.findall(profile["bio"])
            if bio_emails:
                from database import get_conn
                conn = get_conn()
                conn.execute("UPDATE contacts SET email=? WHERE business_id=?", (bio_emails[0], bus_id))
                conn.commit()
                conn.close()
                
            added_count += 1
        except Exception as e:
            errors.append(f"Error processing {line}: {str(e)}")
            
    success_msg = f"Successfully added {added_count} Instagram lead(s)."
    if errors:
        success_msg += f" Note: {len(errors)} error(s) occurred."
        
    return RedirectResponse(f"/instagram-reach?success={success_msg}", status_code=303)



@app.post("/leads/{bid}/generate")
async def generate_messages(bid: int, request: Request):
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    channels = body.get("channels") or None  # None = all channels

    lead = get_lead_by_id(bid)
    if not lead:
        return JSONResponse({"error": "Lead not found"}, status_code=404)

    # Scrape the business website once — used for both demo build and AI context
    from demo_generator import _scrape_site, _is_gym, generate_gym_demo_html, generate_saas_crm_demo_html
    loop = asyncio.get_event_loop()
    website = lead.get("website", "")

    scraped = {}
    if website:
        try:
            scraped = await loop.run_in_executor(None, _scrape_site, website)
        except Exception:
            pass

    # Build demo site always so the URL is available for all DMs
    demo_url = ""
    try:
        pitch_type = lead.get("pitch_type", "")
        if pitch_type == "instagram_reach" or lead.get("source") == "instagram_reach":
            from demo_generator import generate_instagram_custom_demo_html
            html = await loop.run_in_executor(
                None, generate_instagram_custom_demo_html, lead
            )
        elif pitch_type in ("leadflow_saas", "both"):
            html = await loop.run_in_executor(
                None, functools.partial(generate_saas_crm_demo_html, lead)
            )
        elif _is_gym(lead.get("category", ""), lead.get("name", "")):
            html = await loop.run_in_executor(
                None, functools.partial(generate_gym_demo_html, lead, scraped)
            )
        else:
            html = await loop.run_in_executor(
                None, functools.partial(generate_demo_html, lead, scraped)
            )
        DEMO_CACHE[bid] = html
        result = await loop.run_in_executor(
            None, functools.partial(deploy_demo, bid, lead.get("name", ""), html)
        )
        demo_url = result["url"]
        if not result["ok"]:
            print(f"[deploy] demo {bid} push failed: {result['error']}")
        # Persist URL to DB so the UI + outreach use the GitHub Pages link
        from database import get_conn
        conn = get_conn()
        conn.execute("UPDATE businesses SET demo_tunnel_url=? WHERE id=?", (demo_url, bid))
        conn.commit()
        conn.close()
    except Exception:
        pass

    try:
        drafts = await loop.run_in_executor(
            None, functools.partial(generate_all, lead, demo_url, channels=channels, scraped=scraped)
        )
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

    # Store outreach drafts
    subjects_str = json.dumps(drafts.get("subject_options", []))
    for channel in ("email", "instagram", "whatsapp", "linkedin"):
        if drafts.get(channel):
            insert_outreach(bid, channel, drafts[channel], subjects_str if channel == "email" else "")

    # Generate follow-up sequence in background (only on full generate)
    if not channels:
        try:
            sequences = await loop.run_in_executor(None, lambda: write_follow_up_sequence(lead, demo_url))
            insert_follow_ups(bid, sequences)
        except Exception:
            pass

    update_business_status(bid, "approved")

    return JSONResponse({
        "name":             lead["name"],
        "to_email":         lead.get("email", ""),
        "instagram_handle": lead.get("instagram", ""),
        "linkedin_url":     lead.get("linkedin_url", ""),
        "whatsapp":         lead.get("whatsapp", "") or lead.get("phone", ""),
        "email":            drafts.get("email", ""),
        "instagram":        drafts.get("instagram", ""),
        "whatsapp_msg":     drafts.get("whatsapp", ""),
        "linkedin":         drafts.get("linkedin", ""),
        "subject_options":  drafts.get("subject_options", []),
        "demo_url":         demo_url,
    })




@app.post("/leads/{bid}/chat")
async def chat_with_lead(bid: int, request: Request):
    try:
        body = await request.json()
        message = body.get("message", "")
        history = body.get("history", [])
        if not message:
            return JSONResponse({"error": "Empty message"}, status_code=400)

        lead = get_lead_by_id(bid)
        if not lead:
            return JSONResponse({"error": "Lead not found"}, status_code=404)

        loop = asyncio.get_event_loop()
        scraped = None
        if lead.get("website"):
            scraped = await loop.run_in_executor(None, full_audit, lead["website"])

        from ai_writer import _business_context, _run
        biz_ctx = _business_context(lead, scraped)
        
        prompt = (
            f"You are a friendly, helpful AI Business Assistant for {lead.get('name', 'this business')}, "
            f"a {lead.get('category', 'service provider')} located in {lead.get('city', '')}.\n"
            f"Here is the context about the business:\n"
            f"{biz_ctx}\n\n"
            "Guidelines:\n"
            "1. Answer questions about the business (services, location, etc.) politely using only the provided context.\n"
            "2. If the user asks about the website design, booking a call, claiming this website, editing colors, "
            "or pricing/sales for the site, explain that this is a premium concept demo built by LeadFlow Agency. "
            "Instruct them to click the 'Claim Website' button at the bottom/top of the screen to lock in this design "
            "or book a calendar call.\n"
            "3. Keep your answers brief, professional, and conversational (under 3 sentences).\n\n"
            "Previous conversation:\n"
        )
        for h in history[-5:]: # only last 5 turns to save tokens
            role = "User" if h["role"] == "user" else "AI"
            prompt += f"{role}: {h['content']}\n"
        
        prompt += f"\nUser: {message}\n\nAI:"
        
        reply = await loop.run_in_executor(None, _run, prompt)
        return {"reply": reply}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post("/leads/{bid}/rewrite")
async def rewrite_draft(bid: int, request: Request):
    body = await request.json()
    channel      = body.get("channel", "email")
    current_text = body.get("current_text", "")
    instruction  = body.get("instruction", "")
    if not instruction:
        return JSONResponse({"error": "No instruction provided"}, status_code=400)

    lead = get_lead_by_id(bid)
    if not lead:
        return JSONResponse({"error": "Lead not found"}, status_code=404)

    from demo_generator import _scrape_site
    loop = asyncio.get_event_loop()
    scraped = {}
    if lead.get("website"):
        try:
            scraped = await loop.run_in_executor(None, _scrape_site, lead["website"])
        except Exception:
            pass

    demo_url = demo_url_for(bid, lead.get("name", ""))

    try:
        result = await loop.run_in_executor(
            None, functools.partial(rewrite_message, lead, channel, current_text, instruction, demo_url, scraped)
        )
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

    # Update stored draft
    insert_outreach(bid, channel, result, "")
    return JSONResponse({"draft": result})


@app.post("/leads/{bid}/send")
async def send_lead(bid: int, request: Request):
    data      = await request.json()
    email_msg = data.get("email_msg", "")
    to_email  = data.get("to_email", "")
    subject   = data.get("subject", "")
    demo_url  = data.get("demo_url", "")

    if to_email and email_msg:
        try:
            if not subject:
                subject, email_msg = parse_subject_body(email_msg)
            tracking_id = str(uuid.uuid4())
            send_email(to_email, subject, email_msg, tracking_id, demo_url, business_id=bid)
            mark_sent(bid, "email", is_autopilot=False, subject_used=subject, tracking_id=tracking_id)
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)})

    update_business_status(bid, "sent")
    return JSONResponse({"ok": True})


@app.post("/leads/{bid}/skip")
async def skip_lead(bid: int):
    update_business_status(bid, "skipped")
    return JSONResponse({"ok": True})


@app.post("/api/leads/{bid}/status")
async def set_lead_status(bid: int, request: Request):
    data = await request.json()
    status = data.get("status", "new")
    allowed = {"new", "approved", "sent", "replied", "closed", "skipped", "negotiating", "opted_out"}
    if status not in allowed:
        return JSONResponse({"ok": False, "error": "Invalid status"}, status_code=400)
    update_business_status(bid, status)
    return JSONResponse({"ok": True})


@app.get("/leads/{bid}/drafts")
def get_drafts(bid: int):
    """Return the latest saved outreach draft per channel for a lead."""
    from database import get_conn
    conn = get_conn()
    rows = conn.execute("""
        SELECT channel, final_message, draft, subject_options
        FROM outreach WHERE business_id=? AND status != 'sent'
        ORDER BY id DESC
    """, (bid,)).fetchall()
    conn.close()
    # latest per channel wins
    seen = {}
    for r in rows:
        ch = r["channel"]
        if ch not in seen:
            seen[ch] = {
                "draft": r["final_message"] or r["draft"] or "",
                "subject_options": json.loads(r["subject_options"] or "[]"),
            }
    return JSONResponse(seen)


@app.post("/leads/{bid}/delete")
async def delete_lead(bid: int):
    from database import get_conn
    conn = get_conn()
    row = conn.execute("SELECT name FROM businesses WHERE id=?", (bid,)).fetchone()
    name = row["name"] if row else ""
    conn.execute("DELETE FROM outreach    WHERE business_id=?", (bid,))
    conn.execute("DELETE FROM follow_ups  WHERE business_id=?", (bid,))
    conn.execute("DELETE FROM deals       WHERE business_id=?", (bid,))
    conn.execute("DELETE FROM contacts    WHERE business_id=?", (bid,))
    conn.execute("DELETE FROM businesses  WHERE id=?",          (bid,))
    conn.commit()
    conn.close()
    # Remove demo files if present (both legacy {bid}.html and current {slug}.html)
    for demo_file in (DEMOS_DIR / f"{bid}.html", DEMOS_DIR / f"{slug_for(bid, name)}.html"):
        if demo_file.exists():
            demo_file.unlink()
    DEMO_CACHE.pop(bid, None)
    # Stop any running tunnel
    old = DEMO_TUNNELS.pop(bid, None)
    if old:
        try: old["proc"].terminate()
        except Exception as _e: log.warning(f"Demo tunnel proc terminate error: {_e}")
        try: old["server"].shutdown()
        except Exception as _e: log.warning(f"Demo server shutdown error: {_e}")
    return JSONResponse({"ok": True})


# ── Demo sites listing ────────────────────────────────────────────────────

@app.get("/demos", response_class=HTMLResponse)
def demos_page(request: Request):
    from database import get_conn
    import os
    conn = get_conn()
    rows = conn.execute("""
        SELECT b.id, b.name, b.city, b.country, b.category, b.website, b.lead_score, b.demo_tunnel_url, b.template_id
        FROM businesses b
        WHERE b.status NOT IN ('skipped', 'opted_out')
        ORDER BY b.lead_score DESC, b.found_at DESC
    """).fetchall()
    conn.close()
    
    # Load available templates
    avail_templates = []
    tpl_dir = os.path.join(str(BASE), "demo_templates")
    if os.path.exists(tpl_dir):
        avail_templates = [f for f in os.listdir(tpl_dir) if f.endswith(".html")]
        
    businesses = []
    for r in rows:
        b = dict(r)
        b["has_demo"] = ((DEMOS_DIR / f"{slug_for(b['id'], b.get('name',''))}.html").exists()
                         or (DEMOS_DIR / f"{b['id']}.html").exists())
        businesses.append(b)
    demo_base = _get_demo_base_url()
    return templates.TemplateResponse(request, "demos.html", ctx(request, "demos", businesses=businesses, demo_base=demo_base, avail_templates=avail_templates))


@app.get("/demos/{bid}/build/stream")
async def build_demo_stream(bid: int, use_stock: int = 0):
    from database import get_conn
    from demo_generator import _scrape_site, generate_demo_html, generate_gym_demo_html, _is_gym

    conn = get_conn()
    row = conn.execute("""
        SELECT b.*, c.email, c.instagram FROM businesses b
        LEFT JOIN contacts c ON c.business_id = b.id
        WHERE b.id=?
    """, (bid,)).fetchone()
    conn.close()

    async def generator():
        # Padding comment forces browser to flush small SSE events immediately
        PAD = ": " + " " * 1024 + "\n\n"
        yield PAD

        def evt(step, pct, **kw):
            payload = json.dumps({'step': step, 'pct': pct, **kw})
            # 1KB padding after each event ensures browser flushes without buffering
            return f"data: {payload}\n\n{PAD}"

        if not row:
            yield evt("Lead not found", 0, error=True)
            return

        lead = dict(row)
        website = lead.get("website", "")
        loop = asyncio.get_event_loop()

        yield evt("Fetching existing website…", 10)
        await asyncio.sleep(0.4)

        # Blocking HTTP scrape — run in thread
        data = await loop.run_in_executor(None, _scrape_site, website) if website else {}
        await asyncio.sleep(0.3)

        found = []
        if data.get("hero_text"):  found.append("hero text")
        if data.get("about_text"): found.append("about section")
        if data.get("services"):   found.append(f"{len(data['services'])} services")
        if data.get("og_image"):   found.append("hero image")
        if data.get("images"):     found.append(f"{len(data['images'])} photo(s)")
        detail = ", ".join(found) if found else "using business info"

        yield evt(f"Extracted: {detail}", 40)
        await asyncio.sleep(0.5)

        yield evt("Building demo HTML…", 70)
        await asyncio.sleep(0.4)

        category = lead.get("category", "")
        name_val = lead.get("name", "")
        if lead.get("pitch_type") == "instagram_reach" or lead.get("source") == "instagram_reach":
            from demo_generator import generate_instagram_custom_demo_html
            html = await loop.run_in_executor(
                None, generate_instagram_custom_demo_html, lead
            )
        elif _is_gym(category, name_val):
            import functools
            html = await loop.run_in_executor(
                None, functools.partial(generate_gym_demo_html, lead, data, use_stock=bool(use_stock))
            )
        else:
            import functools
            html = await loop.run_in_executor(
                None, functools.partial(generate_demo_html, lead, data, use_stock=bool(use_stock))
            )

        yield evt("Saving…", 90)
        DEMO_CACHE[bid] = html
        (DEMOS_DIR / f"{bid}.html").write_text(html, encoding="utf-8")

        yield evt("Starting Cloudflare tunnel…", 93)
        tunnel_url = await loop.run_in_executor(None, _start_demo_tunnel, bid, html)
        demo_url = tunnel_url or f"{_get_demo_base_url()}/demo/{bid}"

        yield evt("Done", 100, done=True, url=demo_url)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/demos/{bid}/build")
async def build_demo(bid: int, use_stock: int = 0):
    from database import get_conn
    from demo_generator import generate_gym_demo_html, _is_gym, _scrape_site
    conn = get_conn()
    row = conn.execute("""
        SELECT b.*, c.email, c.hunter_email, c.apollo_email, c.apollo_person_name, c.instagram FROM businesses b
        LEFT JOIN contacts c ON c.business_id = b.id
        WHERE b.id=?
    """, (bid,)).fetchone()
    conn.close()
    if not row:
        return JSONResponse({"ok": False, "error": "Not found"})
    try:
        loop = asyncio.get_event_loop()
        lead = dict(row)
        if lead.get("pitch_type") == "instagram_reach" or lead.get("source") == "instagram_reach":
            from demo_generator import generate_instagram_custom_demo_html
            html = await loop.run_in_executor(None, generate_instagram_custom_demo_html, lead)
        elif _is_gym(lead.get("category",""), lead.get("name","")):
            import functools
            scraped = await loop.run_in_executor(None, _scrape_site, lead.get("website",""))
            html = await loop.run_in_executor(
                None, functools.partial(generate_gym_demo_html, lead, scraped, use_stock=bool(use_stock))
            )
        else:
            html = await loop.run_in_executor(None, generate_demo_html, lead)
        DEMO_CACHE[bid] = html
        (DEMOS_DIR / f"{bid}.html").write_text(html, encoding="utf-8")
        tunnel_url = await loop.run_in_executor(None, _start_demo_tunnel, bid, html)
        demo_url = tunnel_url or f"{_get_demo_base_url()}/demo/{bid}"
        return JSONResponse({"ok": True, "url": demo_url})

    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


# ── Demo site ──────────────────────────────────────────────────────────────

@app.get("/demo/{bid}", response_class=HTMLResponse)
def demo_site(bid: str):
    import re
    m = re.search(r'-?(\d+)$', bid)
    real_id = int(m.group(1)) if m else int(bid)
    
    if real_id in DEMO_CACHE:
        return HTMLResponse(DEMO_CACHE[real_id])
    # Try disk cache first
    disk_file = DEMOS_DIR / f"{real_id}.html"
    if disk_file.exists():
        html = disk_file.read_text(encoding="utf-8")
        DEMO_CACHE[real_id] = html
        return HTMLResponse(html)
    from database import get_conn
    conn = get_conn()
    row = conn.execute("""
        SELECT b.*, c.email, c.hunter_email, c.apollo_email, c.apollo_person_name, c.instagram FROM businesses b
        LEFT JOIN contacts c ON c.business_id = b.id
        WHERE b.id=?
    """, (real_id,)).fetchone()
    conn.close()
    if not row:
        return HTMLResponse("<h1>Demo not found</h1>", status_code=404)
    
    from demo_generator import _is_gym, generate_gym_demo_html, generate_demo_html, generate_saas_crm_demo_html, _scrape_site
    lead = dict(row)
    
    pitch_type = lead.get("pitch_type", "")
    if pitch_type in ("leadflow_saas", "both"):
        html = generate_saas_crm_demo_html(lead)
    elif _is_gym(lead.get("category", ""), lead.get("name", "")):
        try:
            scraped = _scrape_site(lead.get("website", ""))
        except Exception:
            scraped = {}
        html = generate_gym_demo_html(lead, scraped)
    else:
        html = generate_demo_html(lead)
        
    DEMO_CACHE[real_id] = html
    disk_file.write_text(html, encoding="utf-8")
    return HTMLResponse(html)


# ── Interactive Audit report ───────────────────────────────────────────────

@app.get("/audit/{bid}", response_class=HTMLResponse)
async def serve_audit_report(bid: int):
    conn = get_conn()
    lead = conn.execute("SELECT * FROM businesses WHERE id = ?", (bid,)).fetchone()
    conn.close()
    if not lead or not lead.get("website"):
        return HTMLResponse("<h1>No website found for this lead</h1>", status_code=404)
    
    url = lead["website"]
    try:
        from analyzer import full_audit
        import asyncio
        loop = asyncio.get_event_loop()
        audit_res = await loop.run_in_executor(None, full_audit, url)
        direct = audit_res["direct"]
        ps = audit_res["pagespeed"] or {}
        
        import re
        def clean_unit(v, fallback="1.5"):
            if not v or v == "—":
                return fallback
            match = re.search(r'[\d\.]+', str(v))
            return match.group(0) if match else fallback
            
        lh = {
            "score": audit_res["score"],
            "fcp": clean_unit(ps.get("fcp"), str(direct.get("response_time_s") or 1.5)),
            "speed_index": clean_unit(ps.get("speed_index"), str(direct.get("response_time_s") or 2.0)),
            "interactive": clean_unit(ps.get("tbt"), str(direct.get("response_time_s") or 1.0)),
        }
        
        seo = {
            "title": direct.get("title") or "",
            "description": direct.get("meta_description") or "",
            "h1_count": 1 if direct.get("title") else 0
        }
        
        # Get demo url for the side-by-side comparison
        demo_url = lead.get("demo_tunnel_url")
        if not demo_url or not demo_url.startswith("http"):
            demo_url = demo_url_for(bid, lead["name"])
            
        booking_url = os.getenv("BOOKING_URL", "https://calendly.com")
        
        score_color = "#00f2fe" if lh['score'] > 80 else ("#f59e0b" if lh['score'] > 50 else "#ef4444")
        
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Website Performance & SEO Audit - {lead['name']}</title>
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg: #05060f;
    --card-bg: rgba(20, 22, 35, 0.7);
    --border: rgba(255, 255, 255, 0.08);
    --accent: #00f2fe;
    --accent-glow: rgba(0, 242, 254, 0.2);
    --text: #f1f5f9;
    --text-dim: #94a3b8;
    --danger: #ef4444;
    --warning: #f59e0b;
    --success: #10b981;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: 'Plus Jakarta Sans', sans-serif; }}
  body {{ 
    background-color: var(--bg); color: var(--text); 
    background-image: radial-gradient(circle at top right, rgba(0,242,254,0.05), transparent 400px),
                      radial-gradient(circle at bottom left, rgba(0,242,254,0.05), transparent 400px);
    min-height: 100vh; padding: 40px 20px; line-height: 1.6; overflow-x: hidden;
  }}
  .container {{ max-width: 1400px; margin: 0 auto; }}
  header {{ text-align: center; margin-bottom: 50px; animation: fadeInDown 0.8s ease-out; }}
  h1 {{ font-size: 2.5rem; font-weight: 800; margin-bottom: 10px; background: linear-gradient(135deg, #fff, #94a3b8); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
  .subtitle {{ color: var(--text-dim); font-size: 1.1rem; max-width: 600px; margin: 0 auto; }}
  
  .dashboard {{ display: grid; grid-template-columns: 1fr 1fr; gap: 30px; animation: fadeInUp 1s ease-out; }}
  @media (max-width: 900px) {{ .dashboard {{ grid-template-columns: 1fr; }} }}
  
  .panel {{
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: 20px;
    padding: 30px;
    backdrop-filter: blur(10px);
    box-shadow: 0 10px 30px rgba(0,0,0,0.5);
    transition: transform 0.3s ease, box-shadow 0.3s ease;
  }}
  .panel:hover {{ transform: translateY(-5px); box-shadow: 0 15px 40px rgba(0,242,254,0.1); }}
  
  .panel-header {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 25px; }}
  .panel-title {{ font-size: 1.4rem; font-weight: 700; display: flex; align-items: center; gap: 10px; }}
  .badge {{ padding: 6px 12px; border-radius: 20px; font-size: 0.85rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }}
  .badge-current {{ background: rgba(239, 68, 68, 0.1); color: var(--danger); border: 1px solid rgba(239, 68, 68, 0.2); }}
  .badge-proposed {{ background: rgba(16, 185, 129, 0.1); color: var(--success); border: 1px solid rgba(16, 185, 129, 0.2); }}
  
  .preview-container {{
    width: 100%; height: 450px; border-radius: 12px; overflow: hidden;
    border: 1px solid var(--border); position: relative; margin-bottom: 25px;
  }}
  .preview-container::before {{
    content: ''; position: absolute; top: 0; left: 0; right: 0; height: 30px;
    background: #1e293b; border-bottom: 1px solid var(--border);
    display: flex; align-items: center; padding: 0 15px; z-index: 10;
  }}
  .preview-container::after {{
    content: '•••'; position: absolute; top: 2px; left: 15px;
    color: #64748b; font-size: 24px; letter-spacing: 2px; z-index: 11;
  }}
  .browser-url {{
    position: absolute; top: 6px; left: 70px; right: 20px; height: 18px;
    background: #0f172a; border-radius: 4px; z-index: 11; opacity: 0.5;
  }}
  iframe {{ width: 100%; height: 100%; border: none; padding-top: 30px; background: #fff; }}
  
  .metrics-grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 15px; }}
  .metric-card {{
    background: rgba(0,0,0,0.3); border: 1px solid var(--border);
    border-radius: 12px; padding: 15px; text-align: center;
  }}
  .metric-value {{ font-size: 1.8rem; font-weight: 800; margin-bottom: 5px; }}
  .metric-label {{ font-size: 0.85rem; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.5px; }}
  
  .score-circle {{
    display: inline-flex; align-items: center; justify-content: center;
    width: 70px; height: 70px; border-radius: 50%; font-size: 1.5rem; font-weight: 800;
  }}
  .score-bad {{ border: 4px solid var(--danger); color: var(--danger); box-shadow: 0 0 15px rgba(239,68,68,0.2); }}
  .score-good {{ border: 4px solid var(--success); color: var(--success); box-shadow: 0 0 15px rgba(16,185,129,0.2); }}
  
  .issues-list {{ margin-top: 25px; }}
  .issue-item {{
    display: flex; align-items: flex-start; gap: 12px;
    padding: 12px; background: rgba(239, 68, 68, 0.05);
    border-left: 3px solid var(--danger); border-radius: 0 8px 8px 0; margin-bottom: 10px;
  }}
  .issue-item.resolved {{ background: rgba(16, 185, 129, 0.05); border-left-color: var(--success); }}
  .issue-icon {{ font-size: 1.2rem; }}
  .issue-text h4 {{ font-size: 0.95rem; margin-bottom: 2px; }}
  .issue-text p {{ font-size: 0.85rem; color: var(--text-dim); }}
  
  .cta-section {{ text-align: center; margin-top: 60px; animation: fadeInUp 1.2s ease-out; }}
  .btn {{
    display: inline-block; padding: 16px 40px; font-size: 1.1rem; font-weight: 700;
    color: #05060f; background: var(--accent); border-radius: 30px;
    text-decoration: none; text-transform: uppercase; letter-spacing: 1px;
    box-shadow: 0 0 20px var(--accent-glow); transition: all 0.3s ease;
  }}
  .btn:hover {{ transform: translateY(-2px) scale(1.02); box-shadow: 0 0 30px rgba(0, 242, 254, 0.4); }}
  
  @keyframes fadeInDown {{ from {{ opacity: 0; transform: translateY(-20px); }} to {{ opacity: 1; transform: translateY(0); }} }}
  @keyframes fadeInUp {{ from {{ opacity: 0; transform: translateY(20px); }} to {{ opacity: 1; transform: translateY(0); }} }}
</style>
</head>
<body>
<div class="container">
  <header>
    <h1>Website Performance Audit</h1>
    <p class="subtitle">A real-time analysis of <b>{lead['name']}</b> vs. modern industry standards.</p>
  </header>

  <div class="dashboard">
    <!-- Current Site Panel -->
    <div class="panel">
      <div class="panel-header">
        <div class="panel-title">Your Current Site</div>
        <div class="badge badge-current">Needs Optimization</div>
      </div>
      
      <div class="preview-container">
        <div class="browser-url"></div>
        <iframe src="{lead['website']}" sandbox="allow-scripts allow-same-origin"></iframe>
      </div>
      
      <div class="metrics-grid">
        <div class="metric-card">
          <div class="score-circle score-bad">{lh['score']}</div>
          <div class="metric-label" style="margin-top:10px;">Performance Score</div>
        </div>
        <div class="metric-card" style="display:flex; flex-direction:column; justify-content:center;">
          <div class="metric-value" style="color:var(--danger);">{lh['fcp']}s</div>
          <div class="metric-label">Load Time (FCP)</div>
          <div style="height:10px;"></div>
          <div class="metric-value" style="color:var(--warning);">{lh['interactive']}s</div>
          <div class="metric-label">Time to Interactive</div>
        </div>
      </div>
      
      <div class="issues-list">
        <div class="issue-item">
          <div class="issue-icon">⚠️</div>
          <div class="issue-text">
            <h4>Slow Load Speeds</h4>
            <p>Losing up to {min(40, int(float(lh['fcp']) * 10))}% of visitors before they see your services.</p>
          </div>
        </div>
        <div class="issue-item">
          <div class="issue-icon">🔍</div>
          <div class="issue-text">
            <h4>SEO Deficiencies</h4>
            <p>Missing optimized tags: Title ({'Found' if seo['title'] else 'Missing'}), Meta ({'Found' if seo['description'] else 'Missing'}).</p>
          </div>
        </div>
      </div>
    </div>

    <!-- Proposed Upgrade Panel -->
    <div class="panel" style="border-color: rgba(0, 242, 254, 0.3); box-shadow: 0 10px 40px rgba(0, 242, 254, 0.05);">
      <div class="panel-header">
        <div class="panel-title" style="color: var(--accent);">Proposed Upgrade</div>
        <div class="badge badge-proposed">Optimized & Fast</div>
      </div>
      
      <div class="preview-container" style="border-color: rgba(0, 242, 254, 0.2);">
        <div class="browser-url"></div>
        <iframe src="{demo_url}"></iframe>
      </div>
      
      <div class="metrics-grid">
        <div class="metric-card">
          <div class="score-circle score-good">98+</div>
          <div class="metric-label" style="margin-top:10px;">Performance Score</div>
        </div>
        <div class="metric-card" style="display:flex; flex-direction:column; justify-content:center;">
          <div class="metric-value" style="color:var(--success);">0.8s</div>
          <div class="metric-label">Load Time (FCP)</div>
          <div style="height:10px;"></div>
          <div class="metric-value" style="color:var(--success);">0.9s</div>
          <div class="metric-label">Time to Interactive</div>
        </div>
      </div>
      
      <div class="issues-list">
        <div class="issue-item resolved">
          <div class="issue-icon">⚡</div>
          <div class="issue-text">
            <h4>Lightning Fast & Mobile First</h4>
            <p>Instant loading on all devices maximizes your conversion rate.</p>
          </div>
        </div>
        <div class="issue-item resolved">
          <div class="issue-icon">🎯</div>
          <div class="issue-text">
            <h4>Built-in SEO & Lead Capture</h4>
            <p>Fully optimized structure designed specifically to turn visitors into clients.</p>
          </div>
        </div>
      </div>
    </div>
  </div>
  
  <div class="cta-section">
    <h2 style="margin-bottom: 20px;">Ready to stop losing customers to a slow website?</h2>
    <a href="{booking_url}" class="btn" target="_blank">Claim Your Free Upgrade Strategy Call</a>
    <p style="margin-top: 15px; color: var(--text-dim); font-size: 0.9rem;">No obligation. Just a clear roadmap to better results.</p>
  </div>
</div>
</body>
</html>"""
        return HTMLResponse(html)
    except Exception as e:
        return HTMLResponse(f"<h1>Error generating audit: {str(e)}</h1>", status_code=500)


# ── Email tracking ─────────────────────────────────────────────────────────

@app.get("/track/open/{tracking_id}")
def track_open(tracking_id: str, request: Request):
    """Record email open. Resolves business_id from outreach table so we never get orphaned events."""
    bid = 0
    try:
        _conn = get_conn()
        row = _conn.execute(
            "SELECT business_id FROM outreach WHERE tracking_id=? UNION "
            "SELECT business_id FROM follow_ups WHERE tracking_id=? LIMIT 1",
            (tracking_id, tracking_id)
        ).fetchone()
        if row:
            bid = row[0] or 0
        _conn.close()
    except Exception:
        pass
    record_tracking_event(tracking_id, bid, "open")
    return Response(content=PIXEL_GIF, media_type="image/gif")


@app.get("/track/click/{tracking_id}")
def track_click(tracking_id: str, url: str = ""):
    """Record demo link click. Resolves business_id from outreach/follow_ups."""
    bid = 0
    try:
        _conn = get_conn()
        row = _conn.execute(
            "SELECT business_id FROM outreach WHERE tracking_id=? UNION "
            "SELECT business_id FROM follow_ups WHERE tracking_id=? LIMIT 1",
            (tracking_id, tracking_id)
        ).fetchone()
        if row:
            bid = row[0] or 0
            # Mark clicked in outreach table
            cursor = _conn.execute(
                "UPDATE outreach SET clicked=1 WHERE tracking_id=?",
                (tracking_id,)
            )
            if cursor.rowcount == 0 and bid:
                _conn.execute(
                    "UPDATE outreach SET clicked=1 WHERE business_id=? AND channel='email'",
                    (bid,)
                )
            _conn.commit()
        _conn.close()
    except Exception:
        pass
    record_tracking_event(tracking_id, bid, "click", url)
    return RedirectResponse(url=url or "/")


@app.get("/unsubscribe", response_class=HTMLResponse)
def unsubscribe(e: str = ""):
    """One-click / link unsubscribe — adds the address to the suppression list."""
    if e:
        suppress(e)
    return HTMLResponse(
        "<html><body style='font-family:sans-serif;text-align:center;padding:60px'>"
        "<h2>You're unsubscribed</h2>"
        "<p>You won't receive any more emails from us. Sorry for the interruption.</p>"
        "</body></html>"
    )


@app.get("/unsubscribe/{tracking_id}", response_class=HTMLResponse)
def unsubscribe_by_tracking(tracking_id: str):
    """Path-based unsubscribe used by the email footer link (no email address required)."""
    try:
        _conn = get_conn()
        row = _conn.execute(
            "SELECT c.email FROM outreach o JOIN contacts c ON c.business_id=o.business_id "
            "WHERE o.tracking_id=? LIMIT 1",
            (tracking_id,)
        ).fetchone()
        if row and row[0]:
            suppress(row[0])
        _conn.close()
    except Exception:
        pass
    return HTMLResponse(
        "<html><body style='font-family:sans-serif;text-align:center;padding:60px'>"
        "<h2>You're unsubscribed ✓</h2>"
        "<p>You won't receive any more emails from us. Sorry for the interruption.</p>"
        "</body></html>"
    )


# ── Sent / tracking ────────────────────────────────────────────────────────

@app.get("/sent", response_class=HTMLResponse)
def sent_page(request: Request):
    from database import get_conn
    conn = get_conn()
    rows = conn.execute("""
        SELECT b.*, c.email, c.instagram,
               MAX(o.opened) as opened,
               MAX(o.open_count) as open_count,
               MAX(o.clicked) as clicked,
               MAX(o.sent_at) as sent_at
        FROM businesses b
        LEFT JOIN contacts c ON c.business_id = b.id
        LEFT JOIN outreach o ON o.business_id = b.id AND o.status = 'sent'
        WHERE b.status IN ('sent','replied','closed')
        GROUP BY b.id
        ORDER BY b.found_at DESC
    """).fetchall()
    conn.close()
    leads = [dict(r) for r in rows]
    return templates.TemplateResponse(request, "sent.html", ctx(request, "sent", leads=leads))


@app.post("/sent/{bid}/replied")
async def mark_replied(bid: int):
    update_business_status(bid, "replied")
    return JSONResponse({"ok": True})


# ── Follow-ups ─────────────────────────────────────────────────────────────

@app.get("/followups", response_class=HTMLResponse)
def followups_page(request: Request):
    now = datetime.utcnow().isoformat()
    fus = get_all_follow_ups()
    for f in fus:
        f["is_due"] = (f.get("scheduled_for") or "") <= now and f["status"] == "pending"
    return templates.TemplateResponse(request, "followups.html", ctx(request, "followups", followups=fus))


@app.post("/followups/{fid}/send")
async def send_follow_up(fid: int):
    from database import get_conn
    conn = get_conn()
    row = conn.execute("""
        SELECT f.*, c.email, b.demo_tunnel_url FROM follow_ups f
        JOIN businesses b ON b.id = f.business_id
        LEFT JOIN contacts c ON c.business_id = f.business_id
        WHERE f.id=?
    """, (fid,)).fetchone()
    conn.close()
    if not row:
        return JSONResponse({"ok": False, "error": "Not found"})
    f = dict(row)
    if f.get("email") and f.get("draft"):
        try:
            subject, body = parse_subject_body(f["draft"])
            tracking_id = str(uuid.uuid4())
            send_email(f["email"], subject, body, tracking_id, f.get("demo_tunnel_url") or "", business_id=f["business_id"])
            mark_follow_up_sent(fid, tracking_id)
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)})
    return JSONResponse({"ok": True})


@app.post("/followups/{fid}/skip")
async def skip_follow_up(fid: int):
    from database import get_conn
    conn = get_conn()
    conn.execute("UPDATE follow_ups SET status='skipped' WHERE id=?", (fid,))
    conn.commit()
    conn.close()
    return JSONResponse({"ok": True})


# ── Kanban ─────────────────────────────────────────────────────────────────

@app.get("/kanban", response_class=HTMLResponse)
def kanban_page(request: Request):
    all_leads = get_all_leads_for_kanban()
    by_status: dict[str, list] = {}
    for lead in all_leads:
        s = lead["status"]
        if s == "sent":
            if lead.get("demo_viewed") or lead.get("email_clicked"):
                s = "demo_viewed"
            elif lead.get("email_opened"):
                s = "opened"
        elif s == "closed":
            s = "converted"
        by_status.setdefault(s, []).append(lead)
    return templates.TemplateResponse(request, "kanban.html", ctx(request, "kanban", leads_by_status=by_status))


@app.post("/kanban/{bid}/move")
async def kanban_move(bid: int, request: Request):
    data = await request.json()
    status = data["status"]
    if status == "converted":
        status = "closed"
    elif status in ("opened", "demo_viewed"):
        status = "sent"
    update_business_status(bid, status)
    return JSONResponse({"ok": True})


# ── Analytics ──────────────────────────────────────────────────────────────

@app.get("/analytics", response_class=HTMLResponse)
def analytics_page(request: Request):
    a = get_analytics()
    return templates.TemplateResponse(request, "analytics.html", ctx(request, "analytics", a=a))


@app.get("/demos/templates")
def get_demo_templates():
    import json
    config_path = os.path.join(str(BASE), "demo_templates", "config.json")
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            return JSONResponse(json.load(f))
    return JSONResponse({"templates": []})


@app.post("/demos/templates/toggle")
async def toggle_demo_template(request: Request):
    import json
    try:
        body = await request.json()
        filename = body.get("file")
        enabled = body.get("enabled", True)
        
        config_path = os.path.join(str(BASE), "demo_templates", "config.json")
        if os.path.exists(config_path):
            with open(config_path, "r+", encoding="utf-8") as f:
                data = json.load(f)
                templates_list = data.get("templates", [])
                for tpl in templates_list:
                    if tpl.get("file") == filename:
                        tpl["enabled"] = enabled
                        break
                f.seek(0)
                json.dump(data, f, indent=2)
                f.truncate()
            return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    return JSONResponse({"ok": False, "error": "Template not found"}, status_code=400)


@app.get("/analytics/funnel")
def analytics_funnel():
    from database import get_conn
    conn = get_conn()
    funnel = {
        'found':      conn.execute('SELECT COUNT(*) FROM businesses').fetchone()[0],
        'generated':  conn.execute("SELECT COUNT(DISTINCT business_id) FROM outreach WHERE status='draft' OR status='sent'").fetchone()[0],
        'sent':       conn.execute("SELECT COUNT(DISTINCT business_id) FROM outreach WHERE status='sent'").fetchone()[0],
        'opened':     conn.execute('SELECT COUNT(DISTINCT business_id) FROM outreach WHERE opened=1').fetchone()[0],
        'demo_viewed':conn.execute("SELECT COUNT(*) FROM businesses WHERE demo_viewed=1").fetchone()[0],
        'replied':    conn.execute("SELECT COUNT(DISTINCT business_id) FROM outreach WHERE replied=1").fetchone()[0],
        'converted':  conn.execute("SELECT COUNT(*) FROM businesses WHERE status='converted'").fetchone()[0],
    }
    conn.close()
    return JSONResponse(funnel)


@app.get("/analytics/by-niche")
def analytics_by_niche():
    from database import get_conn
    conn = get_conn()
    rows = conn.execute("""
        SELECT category, COUNT(*) as found,
               SUM(CASE WHEN b.status IN ('sent','replied','converted') THEN 1 ELSE 0 END) as sent,
               SUM(CASE WHEN o.opened = 1 THEN 1 ELSE 0 END) as opened,
               SUM(CASE WHEN o.replied = 1 THEN 1 ELSE 0 END) as replied,
               SUM(CASE WHEN b.status = 'converted' THEN 1 ELSE 0 END) as converted
        FROM businesses b
        LEFT JOIN outreach o ON o.business_id = b.id AND o.channel = 'email'
        GROUP BY category ORDER BY found DESC LIMIT 15
    """).fetchall()
    conn.close()
    return JSONResponse([dict(r) for r in rows])


@app.get("/analytics/by-city")
def analytics_by_city():
    from database import get_conn
    conn = get_conn()
    rows = conn.execute("""
        SELECT city, COUNT(*) as found,
               SUM(CASE WHEN b.status IN ('sent','replied','converted') THEN 1 ELSE 0 END) as sent,
               SUM(CASE WHEN o.opened = 1 THEN 1 ELSE 0 END) as opened,
               SUM(CASE WHEN o.replied = 1 THEN 1 ELSE 0 END) as replied
        FROM businesses b
        LEFT JOIN outreach o ON o.business_id = b.id AND o.channel = 'email'
        GROUP BY city ORDER BY found DESC LIMIT 15
    """).fetchall()
    conn.close()
    return JSONResponse([dict(r) for r in rows])


@app.get("/analytics/daily")
def analytics_daily():
    from database import get_conn
    conn = get_conn()
    rows = conn.execute("""
        SELECT DATE(found_at) as date, COUNT(*) as count 
        FROM businesses 
        GROUP BY DATE(found_at) 
        ORDER BY DATE(found_at) DESC 
        LIMIT 30
    """).fetchall()
    conn.close()
    return JSONResponse([dict(r) for r in rows])


@app.get("/analytics/ab-subjects")
def analytics_ab_subjects():
    from database import get_conn
    conn = get_conn()
    rows = conn.execute("""
        SELECT subject_used, COUNT(*) as sends, SUM(opened) as opens 
        FROM outreach 
        WHERE subject_used IS NOT NULL AND subject_used != '' 
        GROUP BY subject_used 
        ORDER BY opens DESC
    """).fetchall()
    conn.close()
    return JSONResponse([dict(r) for r in rows])


# ── A/B Test Dashboard ──────────────────────────────────────────────────────

@app.get("/ab-test", response_class=HTMLResponse)
def ab_test_page(request: Request):
    return templates.TemplateResponse(request, "ab_test.html", ctx(request, "ab_test"))


@app.get("/api/ab-test")
def api_ab_test_data():
    """Return aggregate + per-row A/B test data for the dashboard."""
    from database import get_conn
    conn = get_conn()

    # Aggregate: grouped totals
    agg = conn.execute("""
        SELECT
            COALESCE(experiment, 'old_vs_new')  AS experiment,
            COALESCE(label_a, 'Old Formula')     AS label_a,
            COALESCE(label_b, 'New Formula')     AS label_b,
            SUM(sent_a)  AS sent_a, SUM(sent_b)  AS sent_b,
            SUM(opens_a) AS opens_a, SUM(opens_b) AS opens_b,
            SUM(CASE WHEN winner='A' THEN 1 ELSE 0 END) AS wins_a,
            SUM(CASE WHEN winner='B' THEN 1 ELSE 0 END) AS wins_b
        FROM ab_tests GROUP BY experiment
    """).fetchall()

    # Demo views per variant
    demo_a = conn.execute("""
        SELECT COUNT(DISTINCT b.id) FROM businesses b
        JOIN outreach o ON o.business_id = b.id
        JOIN ab_tests t ON t.business_id = b.id
        WHERE b.demo_viewed = 1 AND o.subject_used = t.subject_a
    """).fetchone()[0] or 0

    demo_b = conn.execute("""
        SELECT COUNT(DISTINCT b.id) FROM businesses b
        JOIN outreach o ON o.business_id = b.id
        JOIN ab_tests t ON t.business_id = b.id
        WHERE b.demo_viewed = 1 AND o.subject_used = t.subject_b
    """).fetchone()[0] or 0

    # Replies per variant
    reply_a = conn.execute("""
        SELECT COUNT(DISTINCT b.id) FROM businesses b
        JOIN outreach o ON o.business_id = b.id
        JOIN ab_tests t ON t.business_id = b.id
        WHERE o.replied = 1 AND o.subject_used = t.subject_a
    """).fetchone()[0] or 0

    reply_b = conn.execute("""
        SELECT COUNT(DISTINCT b.id) FROM businesses b
        JOIN outreach o ON o.business_id = b.id
        JOIN ab_tests t ON t.business_id = b.id
        WHERE o.replied = 1 AND o.subject_used = t.subject_b
    """).fetchone()[0] or 0

    # Per-row detail table (latest 50)
    rows = conn.execute("""
        SELECT
            t.id, COALESCE(t.experiment,'old_vs_new') AS experiment,
            COALESCE(t.label_a,'Old Formula') AS label_a,
            COALESCE(t.label_b,'New Formula') AS label_b,
            b.name AS business_name, b.category,
            t.subject_a, t.subject_b,
            t.sent_a, t.sent_b, t.opens_a, t.opens_b,
            t.winner, t.created_at, b.demo_viewed, o.replied
        FROM ab_tests t
        JOIN businesses b ON b.id = t.business_id
        LEFT JOIN outreach o ON o.business_id = t.business_id AND o.channel='email'
        ORDER BY t.created_at DESC LIMIT 50
    """).fetchall()
    conn.close()

    agg_list = [dict(r) for r in agg]
    return JSONResponse({
        "aggregate": agg_list,
        "totals": {"demo_a": demo_a, "demo_b": demo_b, "reply_a": reply_a, "reply_b": reply_b},
        "rows": [dict(r) for r in rows],
    })


# ── Templates Management ───────────────────────────────────────────────────

import os

DEMO_TEMPLATES_DIR = os.path.join(str(BASE), "demo_templates")
os.makedirs(DEMO_TEMPLATES_DIR, exist_ok=True)

@app.get("/templates")
async def templates_page(request: Request):
    return templates.TemplateResponse(request, "templates.html", ctx(request, "templates"))

@app.get("/api/templates")
async def api_list_templates():
    files = [f for f in os.listdir(DEMO_TEMPLATES_DIR) if f.endswith(".html")]
    return JSONResponse(files)

@app.get("/api/templates/preview/{filename}")
async def api_preview_template(filename: str):
    path = os.path.join(DEMO_TEMPLATES_DIR, filename)
    if not os.path.exists(path):
        return HTMLResponse("<h1>Template not found</h1>", status_code=404)
        
    with open(path, "r", encoding="utf-8") as f:
        template_str = f.read()
        
    from jinja2 import Template
    t = Template(template_str)
    
    preview_configs = {
        "gym.html": {
            "name": "Peak Fitness Studio",
            "category": "Fitness Center & Gym",
            "hero_img": "https://images.unsplash.com/photo-1534438327276-14e5300c3a48?w=1600&q=80",
            "about_img": "https://images.unsplash.com/photo-1581009146145-b5ef050c2e1e?w=800&q=80",
            "about_text": "We are a high-end strength and conditioning facility dedicated to excellence and community results.",
            "services": ["Personal Training", "Group Functional Fitness Classes", "Strength & Cardio Equipment Access"]
        },
        "restaurant.html": {
            "name": "Bella Italia Bistro",
            "category": "Italian Restaurant & Cafe",
            "hero_img": "https://images.unsplash.com/photo-1414235077428-338989a2e8c0?w=1400",
            "about_img": "https://images.unsplash.com/photo-1550966871-3ed3cdb5ed0c?w=600",
            "about_text": "Authentic stone-baked pizza, hand-tossed pasta, and premium Italian wines served in a cozy ambiance.",
            "services": ["Fine Casual Dining", "Wine Pairing Nights", "Wood-Fired Pizza Catering"]
        },
        "dentist.html": {
            "name": "Bright Smiles Dental",
            "category": "Dental & Healthcare Clinic",
            "hero_img": "https://images.unsplash.com/photo-1588776814546-daab30f310ce?w=1400",
            "about_img": "https://images.unsplash.com/photo-1629909613654-28e377c37b09?w=600",
            "about_text": "Gentle, high-tech dental care specializing in general dentistry, teeth whitening, veneers, and smile design.",
            "services": ["Teeth Cleaning & Checkups", "Professional Laser Whitening", "Cosmetic Veneers & Implants"]
        },
        "barbershop.html": {
            "name": "Classic Cut Barbershop",
            "category": "Barbershop & Beauty Salon",
            "hero_img": "https://images.unsplash.com/photo-1503951914875-452162b0f3f1?w=1400",
            "about_img": "https://images.unsplash.com/photo-1593702295094-aec22597af65?w=600",
            "about_text": "Precision haircuts, custom fades, hot towel straight-razor shaves, and top-shelf men's grooming products.",
            "services": ["Precision Fades & Scissor Cuts", "Classic Straight-Razor Shaves", "Beard Maintenance & Lineups"]
        },
        "realestate.html": {
            "name": "Apex Realty Group",
            "category": "Real Estate Brokerage",
            "hero_img": "https://images.unsplash.com/photo-1600596542815-ffad4c1539a9?w=1400",
            "about_img": "https://images.unsplash.com/photo-1600607687939-ce8a6c25118c?w=600",
            "about_text": "A premier team of high-end real estate advisors helping buyers and sellers secure luxury residential properties.",
            "services": ["Exclusive Property Listing", "Luxury Buyer Representation", "Complimentary Home Valuations"]
        },
        "roofer.html": {
            "name": "Summit Roofing Solutions",
            "category": "Roofing & Contractor Services",
            "hero_img": "/static/roofer_hero.jpg",
            "about_img": "/static/roofer_about.jpg",
            "about_text": "Professional roofing replacement, leak detection, roof inspections, and gutter repair contractor.",
            "services": ["Complete Roof Replacements", "Emergency Structural Repairs", "Seamless Gutter Installation"]
        },
        "hvac.html": {
            "name": "Comfort Air Solutions",
            "category": "HVAC Heating & Cooling",
            "hero_img": "/static/hvac_hero.jpg",
            "about_img": "/static/hvac_about.jpg",
            "about_text": "Certified HVAC technicians providing rapid heating repairs, central AC installations, and indoor air filtration.",
            "services": ["AC Repairs & Tuning", "Furnace Installation & Maintenance", "Indoor Air Filtration Systems"]
        },
        "solar.html": {
            "name": "Volt Solar Energy",
            "category": "Solar & Clean Energy Systems",
            "hero_img": "/static/solar_hero.jpg",
            "about_img": "/static/solar_about.jpg",
            "about_text": "Harness clean, renewable energy. Professional solar panel installations and smart home battery setups.",
            "services": ["Custom Solar Panel Layouts", "Battery Storage Installations", "Energy Auditing & Consulting"]
        },
        "lawyer.html": {
            "name": "Vanguard Law Offices",
            "category": "Law Firm & Legal Counsel",
            "hero_img": "https://images.unsplash.com/photo-1589829545856-d10d557cf95f?w=1400",
            "about_img": "https://images.unsplash.com/photo-1450133064473-71024230f91b?w=600",
            "about_text": "Providing dedicated litigation, corporate counsel, estate planning, and compassionate personal representation.",
            "services": ["Corporate Litigation", "Estate Planning & Wills", "Personal Injury Counsel"]
        },
        "medspa.html": {
            "name": "Aura Aesthetics Clinic",
            "category": "Medical Spa & Aesthetics",
            "hero_img": "https://images.unsplash.com/photo-1522335789203-aabd1fc54bc9?w=1400",
            "about_img": "https://images.unsplash.com/photo-1512290923902-8a9f81dc236c?w=600",
            "about_text": "Expert skincare clinic offering botox, dermal fillers, medical facials, and advanced anti-aging treatments.",
            "services": ["Botox & Dermal Fillers", "Laser Hair Removal", "Chemical Peels & Facials"]
        },
        "remodeler.html": {
            "name": "Apex Remodeling Group",
            "category": "High-End Home Remodeling",
            "hero_img": "https://images.unsplash.com/photo-1600585154340-be6161a56a0c?w=1400",
            "about_img": "https://images.unsplash.com/photo-1600585154526-990dced4db0d?w=600",
            "about_text": "Award-winning kitchen, bathroom, and custom whole-home renovations built with premium craftsmanship.",
            "services": ["Luxury Kitchen Remodeling", "Bathroom Refinement", "Whole-Home Additions"]
        },
        "cleaning.html": {
            "name": "Pristine Facility Solutions",
            "category": "Commercial Cleaning & Janitorial",
            "hero_img": "/static/cleaning_hero.jpg",
            "about_img": "/static/cleaning_about.jpg",
            "about_text": "Medical-grade office cleaning, floor sanitization, and janitorial contracts for workspaces.",
            "services": ["Office Janitorial Services", "Medical Facility Disinfection", "Commercial Carpet & Floor Care"]
        },
        "detailing.html": {
            "name": "Velocity Detail Studio",
            "category": "Auto Detailing & Ceramic Coating",
            "hero_img": "/static/detailing_hero.jpg",
            "about_img": "/static/detailing_about.jpg",
            "about_text": "Elite paint correction, certified ceramic coatings, and premium auto detailing interior/exterior care.",
            "services": ["Certified Ceramic Coatings", "Multi-Stage Paint Correction", "Obsessive Interior Steam Clean"]
        },
        "treeservice.html": {
            "name": "Timberline Tree Services",
            "category": "Tree Care & Arborist Services",
            "hero_img": "/static/treeservice_hero.jpg",
            "about_img": "/static/treeservice_about.jpg",
            "about_text": "Certified arborist tree care, crane removals, stump grinding, and rapid emergency dispatch.",
            "services": ["Safe Hazardous Tree Removal", "Arborist Trimming & Pruning", "24/7 Storm Response Dispatch"]
        },
        "electrician.html": {
            "name": "VoltWorks Electrical",
            "category": "Electrician & Electrical Services",
            "hero_img": "/static/electrician_hero.jpg",
            "about_img": "/static/electrician_about.jpg",
            "about_text": "Licensed and insured electrical experts handling everything from panel upgrades to smart home installations.",
            "services": ["Panel Upgrades", "EV Charger Installation", "Smart Home Wiring"]
        },
        "pool.html": {
            "name": "Oasis Pool Design",
            "category": "Pool & Spa Design",
            "hero_img": "/static/pool_hero.jpg",
            "about_img": "/static/pool_about.jpg",
            "about_text": "Custom-designed luxury pools and spas built to last a lifetime with unmatched craftsmanship.",
            "services": ["Custom Pool Design", "Spa Installations", "Weekly Maintenance"]
        },
        "painting.html": {
            "name": "Precision Painting",
            "category": "Painting & Refinishing",
            "hero_img": "/static/painting_hero.jpg",
            "about_img": "/static/painting_about.jpg",
            "about_text": "Professional interior and exterior painting services that completely transform your living spaces.",
            "services": ["Interior Painting", "Exterior Painting", "Cabinet Refinishing"]
        },
        "orthodontist.html": {
            "name": "Premium Orthodontics",
            "category": "Orthodontist & Smile Design",
            "hero_img": "/static/orthodontist_hero.jpg",
            "about_img": "/static/orthodontist_about.jpg",
            "about_text": "Board-certified orthodontic specialists providing modern braces and clear aligner treatments.",
            "services": ["Invisalign Aligners", "Traditional Braces", "Smile Design Consultation"]
        },
        "flooring.html": {
            "name": "Signature Flooring",
            "category": "Flooring Installation",
            "hero_img": "/static/flooring_hero.jpg",
            "about_img": "/static/flooring_about.jpg",
            "about_text": "Premium hardwood, luxury vinyl, and tile installations by fully licensed and insured craftsmen.",
            "services": ["Hardwood Installation", "Luxury Vinyl Plank", "Floor Refinishing"]
        },
        "chiropractor.html": {
            "name": "Vitality Spine & Wellness",
            "category": "Chiropractor & Pain Relief",
            "hero_img": "https://power7t.github.io/leadflow-demos/chiro-hero.jpg",
            "about_img": "https://power7t.github.io/leadflow-demos/chiro-about.jpg",
            "about_text": "We believe your body has the innate ability to heal itself when the spine and nervous system are functioning optimally. Our doctors take a personalized, comprehensive approach to every patient.",
            "services": ["Spinal Adjustments", "Sciatica Treatment", "Sports Injury Recovery"]
        },
        "plumber.html": {
            "name": "Elite Plumbing Pros",
            "category": "Plumbing Services",
            "hero_img": "https://power7t.github.io/leadflow-demos/plumber-hero.jpg",
            "about_img": "https://power7t.github.io/leadflow-demos/plumber-about.jpg",
            "about_text": "Expert plumbing services for luxury homes. We handle everything from pipe repairs to full modern bathroom fixture installations.",
            "services": ["Pipe Leak Detection", "Water Heater Installation", "Luxury Fixture Upgrades"]
        },
        "valet_laundry.html": {
            "name": "Elegance Dry Cleaners",
            "category": "Valet Laundry Service",
            "hero_img": "https://power7t.github.io/leadflow-demos/laundry-hero.jpg",
            "about_img": "https://power7t.github.io/leadflow-demos/laundry-about.jpg",
            "about_text": "Premium valet laundry and dry cleaning services. We treat your delicate fabrics and luxury garments with the utmost care.",
            "services": ["Luxury Dry Cleaning", "Wash & Fold", "Delicate Fabric Care"]
        },
        "accountant.html": {
            "name": "Axiom Wealth Management",
            "category": "CPA & Wealth Management",
            "hero_img": "https://power7t.github.io/leadflow-demos/accountant-hero.jpg",
            "about_img": "https://power7t.github.io/leadflow-demos/accountant-about.jpg",
            "about_text": "A premier team of CPA and wealth management advisors dedicated to securing your financial future and optimizing your corporate tax strategies.",
            "services": ["Corporate Tax Planning", "Wealth Management", "Financial Auditing"]
        },
        "moving.html": {
            "name": "Apex Premium Relocation",
            "category": "Moving & Relocation",
            "hero_img": "https://power7t.github.io/leadflow-demos/moving-hero.jpg",
            "about_img": "https://power7t.github.io/leadflow-demos/moving-about.jpg",
            "about_text": "We offer white-glove luxury relocation services. Our professionals ensure your high-end furniture and valuables are transported with absolute care.",
            "services": ["White-Glove Moving", "Long Distance Relocation", "Luxury Furniture Packing"]
        },
        "landscaping.html": {
            "name": "Verdant Landscapes",
            "category": "Landscaping & Hardscaping",
            "hero_img": "https://power7t.github.io/leadflow-demos/landscaping-hero.jpg",
            "about_img": "https://power7t.github.io/leadflow-demos/landscaping-about.jpg",
            "about_text": "Transforming outdoor spaces into stunning luxury retreats. Our architectural landscape designers create perfectly manicured environments.",
            "services": ["Custom Patio Hardscaping", "Luxury Garden Design", "Premium Lawn Care"]
        },
        "interiordesign.html": {
            "name": "Lumina Interior Design",
            "category": "Interior Design",
            "hero_img": "https://power7t.github.io/leadflow-demos/interiordesign-hero.jpg",
            "about_img": "https://power7t.github.io/leadflow-demos/interiordesign-about.jpg",
            "about_text": "Award-winning interior designers specializing in elegant, modern luxury spaces. We bring your architectural vision to life.",
            "services": ["Luxury Home Staging", "Custom Furniture Sourcing", "Modern Space Planning"]
        }
    }

    cfg = preview_configs.get(filename, {
        "name": "Elite Professional Services",
        "category": "General Services",
        "hero_img": "https://images.unsplash.com/photo-1557683316-973673baf926?w=1600&q=80",
        "about_img": "https://images.unsplash.com/photo-1522071820081-009f0129c71c?w=800&q=80",
        "about_text": "We are a professional service agency dedicated to quality work and trusted solutions.",
        "services": ["Premium Service 1", "Professional Option 2", "Custom Service 3"]
    })

    mock_lead = {
        "name": cfg["name"],
        "category": cfg["category"],
        "address": "123 Commercial Way, Suite A",
        "city": "Denver",
        "phone": "+1 (303) 555-0149",
        "email": f"info@{cfg['name'].lower().replace(' ', '')}.com",
        "instagram": cfg["name"].lower().replace(" ", "_"),
        "website": f"{cfg['name'].lower().replace(' ', '')}.com",
        "google_rating": "4.9",
        "google_reviews": "142",
        "maps_url": "https://maps.google.com"
    }
    
    html = t.render(
        lead=mock_lead,
        scraped={"about_text": cfg["about_text"], "services": cfg["services"]},
        hero_img=cfg["hero_img"],
        about_img=cfg["about_img"]
    )
    return HTMLResponse(html)

@app.post("/api/leads/{bid}/template")
async def api_assign_template(bid: int, request: Request):
    from database import get_conn
    data = await request.json()
    template_id = data.get("template_id")
    
    conn = get_conn()
    conn.execute("UPDATE businesses SET template_id = ? WHERE id = ?", (template_id, bid))
    conn.commit()
    conn.close()
    
    return JSONResponse({"ok": True})

# ── Demos ──────────────────────────────────────────────────────────────────

@app.post("/deals")
async def log_deal(request: Request):
    data = await request.json()
    insert_deal(data["business_id"], data["value_usd"], data["service"], data.get("notes", ""))
    return JSONResponse({"ok": True})


# ── Audit API ──────────────────────────────────────────────────────────────

@app.get("/api/audit")
async def audit_site(url: str):
    if not url:
        return JSONResponse({"error": "no url"})
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, full_audit, url)
    return JSONResponse(result)


# ── Tunnel URLs ────────────────────────────────────────────────────────────

def _get_base_url() -> str:
    try:
        url = Path("/tmp/leadflow-tunnel-url.txt").read_text().strip()
        if url.startswith("https://"):
            return url
    except Exception:
        pass
    return "http://127.0.0.1:8765"


def _get_demo_base_url() -> str:
    try:
        url = Path("/tmp/leadflow-demo-tunnel-url.txt").read_text().strip()
        if url.startswith("https://"):
            return url
    except Exception:
        pass
    return "http://127.0.0.1:8766"


@app.get("/api/tunnel-url")
def tunnel_url():
    try:
        url = Path("/tmp/leadflow-tunnel-url.txt").read_text().strip()
        return JSONResponse({"url": url if url.startswith("https://") else ""})
    except Exception:
        return JSONResponse({"url": ""})


@app.get("/api/stats")
def api_stats():
    return JSONResponse(get_stats())


@app.get("/api/demo-url/{bid}")
def demo_url_endpoint(bid: int):
    conn = get_conn()
    row = conn.execute("SELECT name, demo_tunnel_url FROM businesses WHERE id=?", (bid,)).fetchone()
    conn.close()
    if row:
        if row["demo_tunnel_url"] and row["demo_tunnel_url"].startswith("http"):
            return JSONResponse({"url": row["demo_tunnel_url"]})
        # Fallback: read the demo tunnel URL file directly if the DB entry is missing or invalid
        try:
            file_url = Path("/tmp/leadflow-demo-tunnel-url.txt").read_text().strip()
            if file_url.startswith("https://"):
                return JSONResponse({"url": file_url})
        except Exception:
            pass
        return JSONResponse({"url": demo_url_for(bid, row["name"])})
    return JSONResponse({"url": "https://power7t.github.io/leadflow-demos"})
@app.post("/api/generate-audit/{bid}")
async def generate_audit_report(bid: int):
    conn = get_conn()
    lead = conn.execute("SELECT * FROM businesses WHERE id = ?", (bid,)).fetchone()
    conn.close()
    if not lead or not lead.get("website"):
        return JSONResponse({"error": "No website found"}, status_code=400)
    
    url = lead["website"]
    try:
        from analyzer import full_audit
        import asyncio
        loop = asyncio.get_event_loop()
        audit_res = await loop.run_in_executor(None, full_audit, url)
        direct = audit_res["direct"]
        ps = audit_res["pagespeed"] or {}
        
        import re
        def clean_unit(v, fallback="1.5"):
            if not v or v == "—":
                return fallback
            match = re.search(r'[\d\.]+', str(v))
            return match.group(0) if match else fallback
            
        lh = {
            "score": audit_res["score"],
            "fcp": clean_unit(ps.get("fcp"), str(direct.get("response_time_s") or 1.5)),
            "speed_index": clean_unit(ps.get("speed_index"), str(direct.get("response_time_s") or 2.0)),
            "interactive": clean_unit(ps.get("tbt"), str(direct.get("response_time_s") or 1.0)),
        }
        
        seo = {
            "title": direct.get("title") or "",
            "description": direct.get("meta_description") or "",
            "h1_count": 1 if direct.get("title") else 0
        }
        
        import re
        def slugify(text: str) -> str:
            t = " ".join(text.split()[:3]).lower()
            return re.sub(r'[^a-z0-9]+', '-', t).strip('-')
        slug = slugify(lead["name"]) + f"-{bid}"
        filename = f"{slug}-audit.html"
        
        # Get demo url for the side-by-side comparison
        demo_url = lead.get("demo_tunnel_url")
        if not demo_url or not demo_url.startswith("http"):
            demo_url = demo_url_for(bid, lead["name"])
            
        score_color = "#00f2fe" if lh['score'] > 80 else ("#f59e0b" if lh['score'] > 50 else "#ef4444")
        
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Website Performance & SEO Audit - {lead['name']}</title>
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg: #05060f;
    --card-bg: rgba(20, 22, 35, 0.7);
    --border: rgba(255, 255, 255, 0.08);
    --accent: #00f2fe;
    --accent-glow: rgba(0, 242, 254, 0.2);
    --text: #f1f5f9;
    --text-dim: #94a3b8;
    --danger: #ef4444;
    --warning: #f59e0b;
    --success: #10b981;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: 'Plus Jakarta Sans', sans-serif; }}
  body {{ 
    background-color: var(--bg); color: var(--text); 
    background-image: radial-gradient(circle at top right, rgba(0,242,254,0.05), transparent 400px),
                      radial-gradient(circle at bottom left, rgba(0,242,254,0.05), transparent 400px);
    min-height: 100vh; padding: 40px 20px; line-height: 1.6; overflow-x: hidden;
  }}
  .container {{ max-width: 1400px; margin: 0 auto; }}
  header {{ text-align: center; margin-bottom: 50px; animation: fadeInDown 0.8s ease-out; }}
  h1 {{ font-size: 2.5rem; font-weight: 800; margin-bottom: 10px; background: linear-gradient(135deg, #fff, #94a3b8); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
  .subtitle {{ color: var(--text-dim); font-size: 1.1rem; max-width: 600px; margin: 0 auto; }}
  
  .dashboard {{ display: grid; grid-template-columns: 1fr 1fr; gap: 30px; animation: fadeInUp 1s ease-out; }}
  @media (max-width: 900px) {{ .dashboard {{ grid-template-columns: 1fr; }} }}
  
  .panel {{
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: 20px;
    padding: 30px;
    backdrop-filter: blur(10px);
    box-shadow: 0 10px 30px rgba(0,0,0,0.5);
    transition: transform 0.3s ease, box-shadow 0.3s ease;
  }}
  .panel:hover {{ transform: translateY(-5px); box-shadow: 0 15px 40px rgba(0,242,254,0.1); }}
  
  .panel-header {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 25px; }}
  .panel-title {{ font-size: 1.4rem; font-weight: 700; display: flex; align-items: center; gap: 10px; }}
  .badge {{ padding: 6px 12px; border-radius: 20px; font-size: 0.85rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }}
  .badge-current {{ background: rgba(239, 68, 68, 0.1); color: var(--danger); border: 1px solid rgba(239, 68, 68, 0.2); }}
  .badge-proposed {{ background: rgba(16, 185, 129, 0.1); color: var(--success); border: 1px solid rgba(16, 185, 129, 0.2); }}
  
  .preview-container {{
    width: 100%; height: 450px; border-radius: 12px; overflow: hidden;
    border: 1px solid var(--border); position: relative; margin-bottom: 25px;
  }}
  .preview-container::before {{
    content: ''; position: absolute; top: 0; left: 0; right: 0; height: 30px;
    background: #1e293b; border-bottom: 1px solid var(--border);
    display: flex; align-items: center; padding: 0 15px; z-index: 10;
  }}
  .preview-container::after {{
    content: '•••'; position: absolute; top: 2px; left: 15px;
    color: #64748b; font-size: 24px; letter-spacing: 2px; z-index: 11;
  }}
  .browser-url {{
    position: absolute; top: 6px; left: 70px; right: 20px; height: 18px;
    background: #0f172a; border-radius: 4px; z-index: 11; opacity: 0.5;
  }}
  iframe {{ width: 100%; height: 100%; border: none; padding-top: 30px; background: #fff; }}
  
  .metrics-grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 15px; }}
  .metric-card {{
    background: rgba(0,0,0,0.3); border: 1px solid var(--border);
    border-radius: 12px; padding: 15px; text-align: center;
  }}
  .metric-value {{ font-size: 1.8rem; font-weight: 800; margin-bottom: 5px; }}
  .metric-label {{ font-size: 0.85rem; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.5px; }}
  
  .score-circle {{
    display: inline-flex; align-items: center; justify-content: center;
    width: 70px; height: 70px; border-radius: 50%; font-size: 1.5rem; font-weight: 800;
  }}
  .score-bad {{ border: 4px solid var(--danger); color: var(--danger); box-shadow: 0 0 15px rgba(239,68,68,0.2); }}
  .score-good {{ border: 4px solid var(--success); color: var(--success); box-shadow: 0 0 15px rgba(16,185,129,0.2); }}
  
  .issues-list {{ margin-top: 25px; }}
  .issue-item {{
    display: flex; align-items: flex-start; gap: 12px;
    padding: 12px; background: rgba(239, 68, 68, 0.05);
    border-left: 3px solid var(--danger); border-radius: 0 8px 8px 0; margin-bottom: 10px;
  }}
  .issue-item.resolved {{ background: rgba(16, 185, 129, 0.05); border-left-color: var(--success); }}
  .issue-icon {{ font-size: 1.2rem; }}
  .issue-text h4 {{ font-size: 0.95rem; margin-bottom: 2px; }}
  .issue-text p {{ font-size: 0.85rem; color: var(--text-dim); }}
  
  .cta-section {{ text-align: center; margin-top: 60px; animation: fadeInUp 1.2s ease-out; }}
  .btn {{
    display: inline-block; padding: 16px 40px; font-size: 1.1rem; font-weight: 700;
    color: #05060f; background: var(--accent); border-radius: 30px;
    text-decoration: none; text-transform: uppercase; letter-spacing: 1px;
    box-shadow: 0 0 20px var(--accent-glow); transition: all 0.3s ease;
  }}
  .btn:hover {{ transform: translateY(-2px) scale(1.02); box-shadow: 0 0 30px rgba(0, 242, 254, 0.4); }}
  
  @keyframes fadeInDown {{ from {{ opacity: 0; transform: translateY(-20px); }} to {{ opacity: 1; transform: translateY(0); }} }}
  @keyframes fadeInUp {{ from {{ opacity: 0; transform: translateY(20px); }} to {{ opacity: 1; transform: translateY(0); }} }}
</style>
</head>
<body>
<div class="container">
  <header>
    <h1>Website Performance Audit</h1>
    <p class="subtitle">A real-time analysis of <b>{lead['name']}</b> vs. modern industry standards.</p>
  </header>

  <div class="dashboard">
    <!-- Current Site Panel -->
    <div class="panel">
      <div class="panel-header">
        <div class="panel-title">Your Current Site</div>
        <div class="badge badge-current">Needs Optimization</div>
      </div>
      
      <div class="preview-container">
        <div class="browser-url"></div>
        <iframe src="{lead['website']}" sandbox="allow-scripts allow-same-origin"></iframe>
      </div>
      
      <div class="metrics-grid">
        <div class="metric-card">
          <div class="score-circle score-bad">{lh['score']}</div>
          <div class="metric-label" style="margin-top:10px;">Performance Score</div>
        </div>
        <div class="metric-card" style="display:flex; flex-direction:column; justify-content:center;">
          <div class="metric-value" style="color:var(--danger);">{lh['fcp']}s</div>
          <div class="metric-label">Load Time (FCP)</div>
          <div style="height:10px;"></div>
          <div class="metric-value" style="color:var(--warning);">{lh['interactive']}s</div>
          <div class="metric-label">Time to Interactive</div>
        </div>
      </div>
      
      <div class="issues-list">
        <div class="issue-item">
          <div class="issue-icon">⚠️</div>
          <div class="issue-text">
            <h4>Slow Load Speeds</h4>
            <p>Losing up to {min(40, int(float(lh['fcp']) * 10))}% of visitors before they see your services.</p>
          </div>
        </div>
        <div class="issue-item">
          <div class="issue-icon">🔍</div>
          <div class="issue-text">
            <h4>SEO Deficiencies</h4>
            <p>Missing optimized tags: Title ({'Found' if seo['title'] else 'Missing'}), Meta ({'Found' if seo['description'] else 'Missing'}).</p>
          </div>
        </div>
      </div>
    </div>

    <!-- Proposed Upgrade Panel -->
    <div class="panel" style="border-color: rgba(0, 242, 254, 0.3); box-shadow: 0 10px 40px rgba(0, 242, 254, 0.05);">
      <div class="panel-header">
        <div class="panel-title" style="color: var(--accent);">Proposed Upgrade</div>
        <div class="badge badge-proposed">Optimized & Fast</div>
      </div>
      
      <div class="preview-container" style="border-color: rgba(0, 242, 254, 0.2);">
        <div class="browser-url"></div>
        <iframe src="{demo_url}"></iframe>
      </div>
      
      <div class="metrics-grid">
        <div class="metric-card">
          <div class="score-circle score-good">98+</div>
          <div class="metric-label" style="margin-top:10px;">Performance Score</div>
        </div>
        <div class="metric-card" style="display:flex; flex-direction:column; justify-content:center;">
          <div class="metric-value" style="color:var(--success);">0.8s</div>
          <div class="metric-label">Load Time (FCP)</div>
          <div style="height:10px;"></div>
          <div class="metric-value" style="color:var(--success);">0.9s</div>
          <div class="metric-label">Time to Interactive</div>
        </div>
      </div>
      
      <div class="issues-list">
        <div class="issue-item resolved">
          <div class="issue-icon">⚡</div>
          <div class="issue-text">
            <h4>Lightning Fast & Mobile First</h4>
            <p>Instant loading on all devices maximizes your conversion rate.</p>
          </div>
        </div>
        <div class="issue-item resolved">
          <div class="issue-icon">🎯</div>
          <div class="issue-text">
            <h4>Built-in SEO & Lead Capture</h4>
            <p>Fully optimized structure designed specifically to turn visitors into clients.</p>
          </div>
        </div>
      </div>
    </div>
  </div>
  
  <div class="cta-section">
    <h2 style="margin-bottom: 20px;">Ready to stop losing customers to a slow website?</h2>
    <a href="#" class="btn" onclick="alert('Booking calendar would open here'); return false;">Claim Your Free Upgrade Strategy Call</a>
    <p style="margin-top: 15px; color: var(--text-dim); font-size: 0.9rem;">No obligation. Just a clear roadmap to better results.</p>
  </div>
</div>
</body>
</html>"""
        
        result = await loop.run_in_executor(None, functools.partial(deploy_raw, filename, html))
        if not result["ok"]:
            return JSONResponse({"error": f"deploy failed: {result['error']}"}, status_code=500)
        return JSONResponse({"status": "ok", "url": result["url"]})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)



@app.post("/api/live-followup/{bid}")
async def generate_live_followup(bid: int, request: Request):
    conn = get_conn()
    lead = conn.execute("SELECT * FROM businesses WHERE id = ?", (bid,)).fetchone()
    conn.close()
    if not lead:
        return JSONResponse({"error": "Not found"}, status_code=404)
        
    try:
        # Parse JSON request body safely
        body = {}
        try:
            body = await request.json()
        except Exception:
            pass
        channel = body.get("channel", "email")
        feedback = body.get("feedback")
        
        from demo_generator import _scrape_site
        import asyncio
        loop = asyncio.get_event_loop()
        scraped = {}
        if lead["website"]:
            try:
                scraped = await loop.run_in_executor(None, _scrape_site, lead["website"])
            except Exception:
                pass
                
        from ai_writer import write_live_followup
        draft = await loop.run_in_executor(
            None, functools.partial(write_live_followup, dict(lead), scraped, channel, feedback)
        )
        return JSONResponse({"draft": draft})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)



@app.get("/api/random-location")
def api_random_location():
    """Return a random location from the saved autopilot locations config."""
    import random as _random
    try:
        from database import get_conn
        import json as _json
        conn = get_conn()
        row = conn.execute("SELECT locations FROM scheduler_config LIMIT 1").fetchone()
        conn.close()
        if row and row["locations"]:
            locs = _json.loads(row["locations"])
            if locs:
                return JSONResponse({"location": _random.choice(locs)})
    except Exception:
        pass
    # Fallback if nothing configured yet
    fallback = [
        "New York, NY, USA", "London, UK", "Sydney, NSW, Australia",
        "Toronto, Canada", "Dubai, UAE", "Los Angeles, CA, USA",
        "Chicago, IL, USA", "Manchester, UK", "Melbourne, VIC, Australia",
    ]
    return JSONResponse({"location": _random.choice(fallback)})


@app.get("/api/random-locations")
def api_random_locations(n: int = 5):
    """Return n unique random locations from the saved autopilot config."""
    import random as _random
    try:
        from database import get_conn
        import json as _json
        conn = get_conn()
        row = conn.execute("SELECT locations FROM scheduler_config LIMIT 1").fetchone()
        conn.close()
        if row and row["locations"]:
            locs = _json.loads(row["locations"])
            if locs:
                return JSONResponse({"locations": _random.sample(locs, min(n, len(locs)))})
    except Exception:
        pass
    return JSONResponse({"locations": []})


@app.get("/api/track.png")

def track_demo_view(bid: int = 0):
    if bid:
        try:
            conn = get_conn()
            row = conn.execute("SELECT name, demo_viewed FROM businesses WHERE id=?", (bid,)).fetchone()
            if row:
                # Update DB and notify if it's their first time viewing
                if not row["demo_viewed"]:
                    conn.execute("UPDATE businesses SET demo_viewed=1 WHERE id=?", (bid,))
                    conn.commit()
                    import requests, os as _ntfy_os
                    _ntfy_topic = _ntfy_os.getenv("NTFY_TOPIC", "leadflow-chandan-secret")  # fix #12
                    requests.post(
                        f"https://ntfy.sh/{_ntfy_topic}",
                        data=f"🔥 {row['name']} just opened your demo!".encode("utf-8")
                    )
            conn.close()
        except Exception:
            pass
    # Return 1x1 transparent PNG
    import base64
    from fastapi.responses import Response
    pixel = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=")
    return Response(content=pixel, media_type="image/png")


# High-intent events that warrant an instant operator ping.
_ENGAGE_ALERTS = {
    "cta_book_bar":   "💰 {name} clicked “Book a free call” on their demo!",
    "cta_book_modal": "💰 {name} clicked “Claim this website” — hot lead!",
    "cta_whatsapp":   "💬 {name} tapped WhatsApp from their demo!",
    "scroll_90":      "👀 {name} read their whole demo (90% scroll).",
}


@app.get("/api/engage")
def track_engage(bid: int = 0, ev: str = ""):
    """Demo-page engagement beacon: scroll depth, dwell, and CTA clicks.

    Records every event for analytics and fires an ntfy alert on buying-intent
    signals so the operator can follow up while the prospect is still looking.
    """
    if bid and ev:
        try:
            conn = get_conn()
            row = conn.execute("SELECT name FROM businesses WHERE id=?", (bid,)).fetchone()
            record_tracking_event("", bid, f"engage:{ev}")
            if row and ev in _ENGAGE_ALERTS:
                import requests, os as _ntfy_os2
                _ntfy_topic2 = _ntfy_os2.getenv("NTFY_TOPIC", "leadflow-chandan-secret")  # fix #12
                requests.post(
                    f"https://ntfy.sh/{_ntfy_topic2}",
                    data=_ENGAGE_ALERTS[ev].format(name=row["name"]).encode("utf-8"),
                    headers={"Tags": "fire", "Priority": "high"},
                    timeout=5,
                )
            conn.close()
        except Exception:
            pass
    return JSONResponse({"ok": True})


@app.get("/api/tunnel-status")
def tunnel_status():
    """Return current tunnel URLs for LeadFlow + all per-demo tunnels."""
    lf_url = ""
    try:
        lf_url = Path("/tmp/leadflow-tunnel-url.txt").read_text().strip()
        if not lf_url.startswith("https://"):
            lf_url = ""
    except Exception:
        pass
    demos = {str(bid): info["url"] for bid, info in DEMO_TUNNELS.items() if info.get("url")}
    return JSONResponse({"leadflow": lf_url, "demos": demos})


@app.post("/api/refresh-tunnels")
async def refresh_tunnels(request: Request):
    """Kill all tunnels and restart them. Accepts optional bid to refresh only one demo."""
    data = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    bid_only = data.get("bid") if data else None
    loop = asyncio.get_event_loop()

    if bid_only is not None:
        # Refresh single demo tunnel
        bid_only = int(bid_only)
        html_path = DEMOS_DIR / f"{bid_only}.html"
        if not html_path.exists():
            return JSONResponse({"ok": False, "error": "Demo not built yet"})
        html = html_path.read_text(encoding="utf-8")
        url = await loop.run_in_executor(None, _start_demo_tunnel, bid_only, html)
        return JSONResponse({"ok": bool(url), "url": url, "bid": bid_only})

    # Refresh everything
    def _refresh_all():
        # Restart LeadFlow tunnel
        lf_url = _start_leadflow_tunnel()
        # Restart all demo tunnels
        demo_urls = {}
        import time
        for html_file in sorted(DEMOS_DIR.glob("*.html")):
            try:
                bid = int(html_file.stem)
            except ValueError:
                continue
            html = html_file.read_text(encoding="utf-8")
            url = _start_demo_tunnel(bid, html)
            if url:
                demo_urls[bid] = url
            time.sleep(0.5)
        return lf_url, demo_urls

    lf_url, demo_urls = await loop.run_in_executor(None, _refresh_all)
    return JSONResponse({"ok": True, "leadflow": lf_url, "demos": {str(k): v for k, v in demo_urls.items()}})


if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8765, reload=False, workers=1, timeout_keep_alive=30)
