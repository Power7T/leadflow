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

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn

from database import (
    init_db, get_leads, get_all_leads_for_kanban, get_all_active_leads, get_stats,
    update_business_status, insert_outreach, mark_sent,
    record_tracking_event, insert_follow_ups, get_all_follow_ups,
    mark_follow_up_sent, insert_deal, get_analytics, get_pending_follow_ups,
)
from finder import search_places, get_place_details, clean_website_url, is_chain_or_too_big, search_places_async, get_place_details_async
from extractor import extract_contacts
from analyzer import score_website, detect_gap, full_audit
from database import insert_business, insert_contacts
from ai_writer import generate_all, write_follow_up_sequence, rewrite_message
from sender import send_email, parse_subject_body
from demo_generator import generate_demo_html, generate_demo_html_stream
from scorer import score_lead
from multi_finder import check_domain_available, scrape_yelp
from tracker import PIXEL_GIF
from scheduler import start_scheduler, stop_scheduler, save_scheduler_config

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
    """
    Push the generated demo HTML to GitHub Pages (leadflow-demos repo).
    Returns the GitHub Pages URL.
    """
    import os
    import subprocess
    from pathlib import Path
    
    repo_dir = Path("/Users/chandan/leadflow/leadflow-demos")
    demo_dir = repo_dir / str(bid)
    demo_dir.mkdir(parents=True, exist_ok=True)
    
    # Write the html
    index_file = demo_dir / "index.html"
    index_file.write_text(html, encoding="utf-8")
    
    try:
        # Commit and push
        subprocess.run(["git", "add", "."], cwd=repo_dir, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["git", "commit", "-m", f"Deploy demo {bid}"], cwd=repo_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["git", "push"], cwd=repo_dir, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        url = f"https://power7t.github.io/leadflow-demos/{bid}/"
        
        # Persist URL to DB
        from database import get_conn
        conn = get_conn()
        conn.execute("UPDATE businesses SET demo_tunnel_url=? WHERE id=?", (url, bid))
        conn.commit()
        conn.close()
        
        return url
    except Exception as e:
        print(f"Failed to deploy to GitHub Pages: {e}")
        return ""


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
    """On startup, re-create tunnels for all previously-built demos."""
    import time
    from database import get_conn
    conn = get_conn()
    rows = conn.execute("SELECT id FROM businesses WHERE status NOT IN ('skipped')").fetchall()
    conn.close()
    for row in rows:
        bid = row["id"]
        html_path = DEMOS_DIR / f"{bid}.html"
        if not html_path.exists():
            continue
        try:
            html = html_path.read_text(encoding="utf-8")
            url = _start_demo_tunnel(bid, html)
            if url:
                print(f"[tunnel] Demo {bid}: {url}")
        except Exception as e:
            print(f"[tunnel] Demo {bid} failed: {e}")
        time.sleep(0.5)   # stagger to avoid cloudflared rate limits


@asynccontextmanager

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
async def find_stream(niche: str, location: str, max_results: int = 20, source: str = "google"):
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
                    score = score_website(website) if website else 0
                    gap, pitch_type = detect_gap(website, score)
                    reviews = biz.get("google_reviews")
                    if is_chain_or_too_big(name, reviews):
                        yield send(f"  skipped (chain)", "dim")
                        continue
                    domain_info = check_domain_available(name) if not website else {}
                    contacts = extract_contacts(website, name, location)
                    if not any([contacts.get("email"), contacts.get("instagram"),
                                contacts.get("linkedin_url"), contacts.get("whatsapp")]):
                        yield send(f"  skipped (no contacts)", "dim")
                        continue
                    business_data = {**biz, "website": website, "website_score": score,
                                     "gap": gap, "pitch_type": pitch_type,
                                     "lead_score": score_lead(biz, contacts),
                                     "domain_available": domain_info.get("domain") if domain_info.get("available") else None,
                                     "source": "yelp", "category": niche}
                    bid = insert_business(business_data)
                    insert_contacts(bid, contacts)
                    yield send(f"  ✓ {name} | score={score}", "ok")
                    saved += 1
                    await asyncio.sleep(0.02)
                yield f"data: {json.dumps({'type':'done','count':saved})}\n\n"
                return

            # Google Maps path
            places = await search_places_async(niche, location, max_results)
            if not places:
                yield f"data: {json.dumps({'type':'error','msg':'No results. Check niche/location or API key.'})}\n\n"
                return

            yield send(f"Found {len(places)} places. Fetching details...", "dim")
            saved = 0

            for place in places:
                name = place.get("name", "Unknown")
                yield send(f"Processing: {name}...", "dim")
                await asyncio.sleep(0.05)

                details   = await get_place_details_async(place["place_id"])
                raw_url   = details.get("website", "")
                website   = clean_website_url(raw_url)
                phone     = details.get("international_phone_number") or details.get("formatted_phone_number", "")
                address   = details.get("formatted_address", "")
                rating    = details.get("rating")
                reviews   = details.get("user_ratings_total")

                if is_chain_or_too_big(name, reviews):
                    yield send(f"  skipped ({reviews} reviews — chain)", "dim")
                    continue

                loop = asyncio.get_event_loop()
                score = await loop.run_in_executor(None, score_website, website) if website else 0
                gap, pitch_type = detect_gap(website, score)
                parts   = address.split(",")
                city    = parts[-3].strip() if len(parts) >= 3 else ""
                country = parts[-1].strip() if parts else ""

                domain_info = check_domain_available(name) if not website else {}
                contacts    = extract_contacts(website, name, location)

                if not any([contacts.get("email"), contacts.get("instagram"),
                            contacts.get("linkedin_url"), contacts.get("whatsapp"), phone]):
                    yield send(f"  skipped (no contacts)", "dim")
                    continue

                business_data = {
                    "name": name, "category": niche, "address": address,
                    "city": city, "country": country, "phone": phone,
                    "website": website, "website_score": score,
                    "google_rating": rating, "google_reviews": reviews,
                    "gap": gap, "pitch_type": pitch_type,
                    "lead_score": score_lead({"website": website, "website_score": score,
                                              "google_rating": rating, "google_reviews": reviews}, contacts),
                    "domain_available": domain_info.get("domain") if domain_info.get("available") else None,
                    "source": "google_maps",
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
                          int(data.get("hour", 6)), int(data.get("max_per", 20)))
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
    def slugify(text: str) -> str:
        import re
        t = " ".join(text.split()[:3]).lower()
        t = re.sub(r'[^a-z0-9]+', '-', t)
        return t.strip('-')
        
    slug = slugify(lead.get("name", "")) + f"-{bid}"
    demo_filename = f"{slug}.html"

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
            html = await loop.run_in_executor(None, generate_demo_html, lead)
        tunnel_url = ""
        try: tunnel_url = open("/tmp/leadflow-tunnel-url.txt").read().strip()
        except: pass
        html = html.replace("{{TUNNEL_URL}}", tunnel_url).replace("{{BID}}", str(bid))
        DEMO_CACHE[bid] = html
        (DEMOS_DIR / demo_filename).write_text(html, encoding="utf-8")
        import subprocess
        subprocess.Popen(f"cd {DEMOS_DIR} && git add {demo_filename} && git commit -m 'Auto-deploy {demo_filename}' && git push", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        demo_url = f"https://Power7T.github.io/leadflow-demos/{demo_filename}"
        
        # Persist URL to DB so UI shows the github pages link instead of cloudflare fallback
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

    def slugify(text: str) -> str:
        import re
        t = " ".join(text.split()[:3]).lower()
        return re.sub(r'[^a-z0-9]+', '-', t).strip('-')
        
    slug = slugify(lead.get("name", "")) + f"-{bid}"
    demo_url = f"https://Power7T.github.io/leadflow-demos/{slug}.html"

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
            send_email(to_email, subject, email_msg, tracking_id, demo_url)
            mark_sent(bid, "email")
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
    allowed = {"new", "approved", "sent", "replied", "closed", "skipped"}
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
    conn.execute("DELETE FROM outreach    WHERE business_id=?", (bid,))
    conn.execute("DELETE FROM follow_ups  WHERE business_id=?", (bid,))
    conn.execute("DELETE FROM deals       WHERE business_id=?", (bid,))
    conn.execute("DELETE FROM contacts    WHERE business_id=?", (bid,))
    conn.execute("DELETE FROM businesses  WHERE id=?",          (bid,))
    conn.commit()
    conn.close()
    # Remove demo file if present
    demo_file = DEMOS_DIR / f"{bid}.html"
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
    conn = get_conn()
    rows = conn.execute("""
        SELECT b.id, b.name, b.city, b.country, b.category, b.website, b.lead_score, b.demo_tunnel_url
        FROM businesses b
        WHERE b.status NOT IN ('skipped')
        ORDER BY b.lead_score DESC, b.found_at DESC
    """).fetchall()
    conn.close()
    businesses = []
    for r in rows:
        b = dict(r)
        b["has_demo"] = (DEMOS_DIR / f"{b['id']}.html").exists()
        # Prefer live in-memory tunnel URL over DB value
        if b["id"] in DEMO_TUNNELS:
            b["demo_tunnel_url"] = DEMO_TUNNELS[b["id"]]["url"]
        businesses.append(b)
    demo_base = _get_demo_base_url()
    return templates.TemplateResponse("demos.html", ctx(request, "demos", businesses=businesses, demo_base=demo_base))


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
            html = await loop.run_in_executor(None, generate_demo_html, lead)

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
        SELECT b.*, c.email, c.hunter_email, c.apollo_email, c.apollo_person_name, c.instagram, c.demo_viewed, c.replied_at FROM businesses b
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
    # Regenerate from DB
    from database import get_conn
    conn = get_conn()
    row = conn.execute("""
        SELECT b.*, c.email, c.instagram FROM businesses b
        LEFT JOIN contacts c ON c.business_id = b.id
        WHERE b.id=?
    """, (bid,)).fetchone()
    conn.close()
    if not row:
        return HTMLResponse("<h1>Demo not found</h1>", status_code=404)
    html = generate_demo_html(dict(row))
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
            send_email(f["email"], subject, body)
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
        by_status.setdefault(s, []).append(lead)
    return templates.TemplateResponse("kanban.html", ctx(request, "kanban", leads_by_status=by_status))


@app.post("/kanban/{bid}/move")
async def kanban_move(bid: int, request: Request):
    data = await request.json()
    update_business_status(bid, data["status"])
    return JSONResponse({"ok": True})


# ── Analytics ──────────────────────────────────────────────────────────────

@app.get("/analytics", response_class=HTMLResponse)
def analytics_page(request: Request):
    a = get_analytics()
    return templates.TemplateResponse("analytics.html", ctx(request, "analytics", a=a))


# ── Deals ──────────────────────────────────────────────────────────────────

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
    row = conn.execute("SELECT name FROM businesses WHERE id=?", (bid,)).fetchone()
    conn.close()
    if row:
        import re
        t = " ".join(row["name"].split()[:3]).lower()
        slug = re.sub(r'[^a-z0-9]+', '-', t).strip('-') + f"-{bid}"
        return JSONResponse({"url": f"https://Power7T.github.io/leadflow-demos/{slug}.html"})
    return JSONResponse({"url": "https://Power7T.github.io/leadflow-demos"})
@app.post("/api/generate-audit/{bid}")
async def generate_audit_report(bid: int):
    conn = get_conn()
    lead = conn.execute("SELECT * FROM businesses WHERE id = ?", (bid,)).fetchone()
    conn.close()
    if not lead or not lead.get("website"):
        return JSONResponse({"error": "No website found"}, status_code=400)
    
    url = lead["website"]
    try:
        from extractor import _run_lighthouse, _check_seo
        import asyncio
        loop = asyncio.get_event_loop()
        lh = await loop.run_in_executor(None, _run_lighthouse, url)
        seo = await loop.run_in_executor(None, _check_seo, url)
        
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
        
        (DEMOS_DIR / filename).write_text(html, encoding="utf-8")
        import subprocess
        subprocess.Popen(f"cd {DEMOS_DIR} && git add {filename} && git commit -m 'Auto-deploy audit {filename}' && git push", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        audit_url = f"https://Power7T.github.io/leadflow-demos/{filename}"
        
        return JSONResponse({"status": "ok", "url": audit_url})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)



@app.post("/api/live-followup/{bid}")
async def generate_live_followup(bid: int):
    conn = get_conn()
    lead = conn.execute("SELECT * FROM businesses WHERE id = ?", (bid,)).fetchone()
    conn.close()
    if not lead:
        return JSONResponse({"error": "Not found"}, status_code=404)
        
    try:
        import asyncio
        from ai_writer import write_live_followup
        loop = asyncio.get_event_loop()
        draft = await loop.run_in_executor(None, write_live_followup, dict(lead))
        return JSONResponse({"draft": draft})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)



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
