#!/usr/bin/env python3.12
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

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
    get_conn,
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


def _start_leadflow_tunnel() -> str:
    """Start cloudflared tunnel for the main LeadFlow app on port 8765. Returns URL."""
    global _leadflow_tunnel_proc
    if _leadflow_tunnel_proc and _leadflow_tunnel_proc.poll() is None:
        try:
            url = Path("/tmp/leadflow-tunnel-url.txt").read_text().strip()
            if url.startswith("https://"):
                return url
        except Exception:
            pass

    proc = _subprocess.Popen(
        ["/opt/homebrew/bin/cloudflared", "tunnel", "--url", "http://127.0.0.1:8765"],
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
    init_db()
    start_scheduler()
    asyncio.create_task(update_tunnel_urls())

    # Start demo server on 8766 if not already running
    try:
        s = _socket.create_connection(("127.0.0.1", 8766), timeout=0.5)
        s.close()
    except OSError:
        _demo_proc = _subprocess.Popen(
            ["python3.12", str(BASE / "demo_server.py")],
            stdout=_subprocess.DEVNULL, stderr=_subprocess.DEVNULL,
        )

    # Always start cloudflared tunnels in background threads
    _threading.Thread(target=_start_leadflow_tunnel, daemon=True, name="cf-leadflow").start()
    _threading.Thread(target=_restore_demo_tunnels, daemon=True, name="cf-demos").start()

    yield
    stop_scheduler()
    if _demo_proc:
        _demo_proc.terminate()
    if _leadflow_tunnel_proc:
        try: _leadflow_tunnel_proc.terminate()
        except Exception: pass


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")


def ctx(request: Request, page: str, **extra):
    return {"request": request, "page": page, "stats": get_stats(), **extra}


# ── Dashboard ──────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    all_leads = get_leads("new") + get_leads("sent") + get_leads("replied")
    recent = sorted(all_leads, key=lambda x: x.get("found_at", ""), reverse=True)[:8]
    return templates.TemplateResponse("index.html", ctx(request, "home", recent=recent))


# ── Find businesses ────────────────────────────────────────────────────────

@app.get("/find", response_class=HTMLResponse)
def find_page(request: Request):
    cfg = _get_scheduler_cfg()
    return templates.TemplateResponse("find.html", ctx(request, "find", sched=cfg))


# ── Autopilot Page ─────────────────────────────────────────────────────────

@app.get("/autopilot", response_class=HTMLResponse)
def autopilot_page(request: Request):
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
            "total_sent": conn.execute("SELECT COUNT(*) FROM outreach WHERE status='sent' AND is_autopilot=1").fetchone()[0],
            "total_replied": conn.execute("SELECT COUNT(*) FROM outreach WHERE replied=1 AND is_autopilot=1").fetchone()[0],
            "total_opened": conn.execute("SELECT COUNT(*) FROM outreach WHERE opened=1 AND is_autopilot=1").fetchone()[0],
            "total_clicked": conn.execute("SELECT COUNT(*) FROM outreach WHERE clicked=1 AND is_autopilot=1").fetchone()[0],
        }
    finally:
        conn.close()
    
    sent_today = get_emails_sent_today()
    return templates.TemplateResponse(
        "autopilot.html",
        ctx(
            request,
            "autopilot",
            cfg=cfg,
            sent_today=sent_today,
            recent_sent=recent_sent,
            recent_found=recent_found,
            stats_data=stats_data
        )
    )

@app.get("/autopilot/logs")
def get_autopilot_logs():
    try:
        from pathlib import Path
        import re
        log_path = Path("/tmp/leadflow_server.log")
        if log_path.exists():
            lines = log_path.read_text(encoding="utf-8").splitlines()
            clean_lines = []
            for line in lines[-150:]:
                line = re.sub(r'\s{10,}', ' ', line)
                if line.strip():
                    clean_lines.append(line)
            return {"logs": "\n".join(clean_lines[-60:])}
    except Exception as e:
        return {"logs": f"Error reading logs: {e}"}
    return {"logs": "No logs available."}

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
    jobs = {
        "find": (scheduler.job_daily_find, "Daily Lead Finder"),
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
    return templates.TemplateResponse("settings.html", ctx(request, "settings", env=env))

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
    context = ssl._create_unverified_context()

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
                yield send(f"  ✓ {name} | score={score} | email={has_email} ig={has_ig}", "ok")
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


# ── Leads review ───────────────────────────────────────────────────────────

@app.get("/leads", response_class=HTMLResponse)
def leads_page(request: Request):
    leads = get_all_active_leads()
    return templates.TemplateResponse("leads.html", ctx(request, "leads", leads=leads))


@app.post("/leads/{bid}/generate")
async def generate_messages(bid: int, request: Request):
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    channels = body.get("channels") or None  # None = all channels

    lead = next((l for l in get_all_active_leads() if l["id"] == bid), None)
    if not lead:
        return JSONResponse({"error": "Lead not found"}, status_code=404)

    # Scrape the business website once — used for both demo build and AI context
    from demo_generator import _scrape_site, _is_gym, generate_gym_demo_html
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
        if _is_gym(lead.get("category", ""), lead.get("name", "")):
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

        leads = get_all_active_leads()
        lead = next((l for l in leads if l["id"] == bid), None)
        if not lead:
            return JSONResponse({"error": "Lead not found"}, status_code=404)

        loop = asyncio.get_event_loop()
        scraped = None
        if lead.get("website"):
            scraped = await loop.run_in_executor(None, full_audit, lead["website"])

        from ai_writer import _business_context, _run
        prompt = f"{_business_context(lead, scraped)}\n\nPrevious conversation:\n"
        for h in history[-5:]: # only last 5 turns to save tokens
            role = "User" if h["role"] == "user" else "AI"
            prompt += f"{role}: {h['content']}\n"
        
        prompt += f"\nUser: {message}\n\nAnswer concisely and accurately based ONLY on the business context provided above."
        
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

    lead = next((l for l in get_all_active_leads() if l["id"] == bid), None)
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
        FROM outreach WHERE business_id=?
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
        except Exception: pass
        try: old["server"].shutdown()
        except Exception: pass
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
    return templates.TemplateResponse("demos.html", ctx(request, "demos", businesses=businesses, demo_base=demo_base, avail_templates=avail_templates))


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
        if _is_gym(category, name_val):
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
        if _is_gym(lead.get("category",""), lead.get("name","")):
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
def demo_site(bid: int):
    if bid in DEMO_CACHE:
        return HTMLResponse(DEMO_CACHE[bid])
    # Try disk cache first
    disk_file = DEMOS_DIR / f"{bid}.html"
    if disk_file.exists():
        html = disk_file.read_text(encoding="utf-8")
        DEMO_CACHE[bid] = html
        return HTMLResponse(html)
    from database import get_conn
    conn = get_conn()
    row = conn.execute("""
        SELECT b.*, c.email, c.hunter_email, c.apollo_email, c.apollo_person_name, c.instagram FROM businesses b
        LEFT JOIN contacts c ON c.business_id = b.id
        WHERE b.id=?
    """, (bid,)).fetchone()
    conn.close()
    if not row:
        return HTMLResponse("<h1>Demo not found</h1>", status_code=404)
    
    from demo_generator import _is_gym, generate_gym_demo_html, _scrape_site
    lead = dict(row)
    if _is_gym(lead.get("category", ""), lead.get("name", "")):
        try:
            scraped = _scrape_site(lead.get("website", ""))
        except Exception:
            scraped = {}
        html = generate_gym_demo_html(lead, scraped)
    else:
        html = generate_demo_html(lead)
        
    DEMO_CACHE[bid] = html
    disk_file.write_text(html, encoding="utf-8")
    return HTMLResponse(html)


# ── Email tracking ─────────────────────────────────────────────────────────

@app.get("/track/open/{tracking_id}")
def track_open(tracking_id: str, request: Request):
    record_tracking_event(tracking_id, 0, "open")
    return Response(content=PIXEL_GIF, media_type="image/gif")


@app.get("/track/click/{tracking_id}")
def track_click(tracking_id: str, url: str = ""):
    record_tracking_event(tracking_id, 0, "click", url)
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


# ── Sent / tracking ────────────────────────────────────────────────────────

@app.get("/sent", response_class=HTMLResponse)
def sent_page(request: Request):
    from database import get_conn
    conn = get_conn()
    rows = conn.execute("""
        SELECT b.*, c.email, c.instagram,
               o.opened, o.open_count, o.clicked, o.sent_at
        FROM businesses b
        LEFT JOIN contacts c ON c.business_id = b.id
        LEFT JOIN outreach o ON o.business_id = b.id AND o.channel = 'email'
        WHERE b.status IN ('sent','replied','closed')
        GROUP BY b.id
        ORDER BY b.found_at DESC
    """).fetchall()
    conn.close()
    leads = [dict(r) for r in rows]
    return templates.TemplateResponse("sent.html", ctx(request, "sent", leads=leads))


@app.post("/sent/{bid}/replied")
async def mark_replied(bid: int):
    update_business_status(bid, "replied")
    return JSONResponse({"ok": True})


# ── Follow-ups ─────────────────────────────────────────────────────────────

@app.get("/followups", response_class=HTMLResponse)
def followups_page(request: Request):
    now = datetime.now().isoformat()
    fus = get_all_follow_ups()
    for f in fus:
        f["is_due"] = (f.get("scheduled_for") or "") <= now and f["status"] == "pending"
    return templates.TemplateResponse("followups.html", ctx(request, "followups", followups=fus))


@app.post("/followups/{fid}/send")
async def send_follow_up(fid: int):
    from database import get_conn
    conn = get_conn()
    row = conn.execute("""
        SELECT f.*, c.email FROM follow_ups f
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
            send_email(f["email"], subject, body, business_id=f["business_id"])
            mark_follow_up_sent(fid)
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
    return templates.TemplateResponse("kanban.html", ctx(request, "kanban", leads_by_status=by_status))


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
    return templates.TemplateResponse("analytics.html", ctx(request, "analytics", a=a))


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


# ── Templates Management ───────────────────────────────────────────────────

import os

DEMO_TEMPLATES_DIR = os.path.join(str(BASE), "demo_templates")
os.makedirs(DEMO_TEMPLATES_DIR, exist_ok=True)

@app.get("/templates")
async def templates_page(request: Request):
    return templates.TemplateResponse("templates.html", ctx(request, "templates"))

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
            "hero_img": "https://images.unsplash.com/photo-1621905251189-08b45d6a269e?w=1400",
            "about_img": "https://images.unsplash.com/photo-1581094288338-2314dddb7ecc?w=600",
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


@app.get("/api/demo-url/{bid}")
def demo_url_endpoint(bid: int):
    conn = get_conn()
    row = conn.execute("SELECT name, demo_tunnel_url FROM businesses WHERE id=?", (bid,)).fetchone()
    conn.close()
    if row:
        if row["demo_tunnel_url"] and row["demo_tunnel_url"].startswith("http"):
            return JSONResponse({"url": row["demo_tunnel_url"]})
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
        
        score_color = "#4d9fff" if lh['score'] > 80 else ("#ffb84d" if lh['score'] > 50 else "#ff4d4d")
        
        html = f"""<!DOCTYPE html>
<html>
<head>
<title>Performance & SEO Audit - {lead['name']}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body {{ background:#080808; color:#fff; font-family:sans-serif; padding:40px; line-height:1.6; }}
.container {{ max-width:800px; margin:0 auto; }}
h1 {{ border-bottom:1px solid #333; padding-bottom:20px; }}
.score-box {{ background:#111; padding:30px; border-radius:12px; text-align:center; border:1px solid #222; margin-bottom:30px; }}
.score-circle {{ display:inline-block; width:120px; height:120px; border-radius:50%; border:8px solid {score_color}; line-height:120px; font-size:40px; font-weight:bold; }}
.card {{ background:#111; padding:20px; border-radius:12px; margin-bottom:20px; border:1px solid #222; }}
.card h2 {{ margin-top:0; color:#4d9fff; }}
.metric {{ display:flex; justify-content:space-between; padding:10px 0; border-bottom:1px solid #222; }}
</style>
</head>
<body>
<div class="container">
  <h1>Website Audit Report: {lead['name']}</h1>
  <div class="score-box">
    <div class="score-circle">{lh['score']}</div>
    <h3>Performance Score</h3>
    <p>Your website loads in {lh['fcp']}s. A slow website loses up to 40% of potential clients before they even see your services.</p>
  </div>
  <div class="card">
    <h2>Performance Details</h2>
    <div class="metric"><span>Speed Index:</span> <span>{lh['speed_index']}s</span></div>
    <div class="metric"><span>Time to Interactive:</span> <span>{lh['interactive']}s</span></div>
  </div>
  <div class="card">
    <h2>SEO & Critical Errors</h2>
    <div class="metric"><span>Title Tag:</span> <span>{'Found' if seo['title'] else 'MISSING'}</span></div>
    <div class="metric"><span>Meta Description:</span> <span>{'Found' if seo['description'] else 'MISSING'}</span></div>
    <div class="metric"><span>H1 Tags:</span> <span>{seo['h1_count']}</span></div>
    <p style="color:#ffb84d; margin-top:15px; font-weight:bold;">We can fix all of these issues and build you a lightning-fast, highly-converting website.</p>
  </div>
  <p style="text-align:center; margin-top:40px; color:#888;">Report generated by Chandan Gosavi</p>
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
                    import requests
                    requests.post(
                        "https://ntfy.sh/leadflow-chandan-secret", 
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
                import requests
                requests.post(
                    "https://ntfy.sh/leadflow-chandan-secret",
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
    uvicorn.run("server:app", host="127.0.0.1", port=8765, reload=False)
