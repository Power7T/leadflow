#!/usr/bin/env python3.12
"""
LeadFlow Autopilot — runs forever without human input.
Cycle: scrape → AI-write → send emails → sleep → repeat.
"""
import time
import uuid
import logging
import os
import random

from rich.console import Console

from database import (
    init_db, get_leads, get_stats, get_unsent_lead_count,
    insert_outreach, mark_sent, update_business_status,
    get_dynamic_send_limit, get_emails_sent_today, can_sender_send,
)
from finder import run_finder
from ai_writer import generate_all
from sender import send_email, parse_subject_body

console = Console()
log = logging.getLogger("leadflow.autopilot")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ── Config ──────────────────────────────────────────────────────────────────
NICHES = [
    "restaurants", "gyms", "dental clinics", "real estate agents",
    "law firms", "auto repair shops", "salons", "plumbers",
    "electricians", "landscaping companies", "pet grooming", "chiropractors",
]
LOCATIONS = [
    "Austin, Texas, USA", "Dallas, Texas, USA", "Houston, Texas, USA",
    "Miami, Florida, USA", "Phoenix, Arizona, USA", "Atlanta, Georgia, USA",
    "Denver, Colorado, USA", "Seattle, Washington, USA",
]
SCRAPE_BATCH   = 100   # leads per scrape cycle
SCRAPE_EVERY   = 1800  # seconds between scrape cycles (30 min)
SEND_PAUSE     = 90    # seconds between individual email sends
CYCLE_SLEEP    = 300   # seconds to sleep when nothing to do (5 min)
MIN_NEW_LEADS  = 5     # scrape when new leads drop below this


def _scrape_cycle():
    niche    = random.choice(NICHES)
    location = random.choice(LOCATIONS)
    console.print(f"\n[bold cyan][Autopilot][/] Scraping {SCRAPE_BATCH} leads: [white]{niche}[/] in [white]{location}[/]")
    try:
        run_finder("google_search", niche, location, SCRAPE_BATCH)
    except Exception as e:
        console.print(f"[red][Autopilot] Scrape error: {e}[/]")


def _write_and_send(lead: dict) -> bool:
    """Generate AI message and send email. Returns True if sent."""
    if not lead.get("email"):
        update_business_status(lead["id"], "skipped")
        return False

    try:
        drafts = generate_all(lead, channels=["email"])
    except Exception as e:
        console.print(f"[red][Autopilot] AI write failed for {lead.get('name')}: {e}[/]")
        return False

    email_draft = drafts.get("email", "")
    if not email_draft:
        update_business_status(lead["id"], "skipped")
        return False

    try:
        subject, body = parse_subject_body(email_draft)
    except Exception:
        subject = f"Quick question about {lead.get('name', 'your business')}"
        body    = email_draft

    insert_outreach(lead["id"], "email", email_draft)

    try:
        tracking_id = str(uuid.uuid4())
        send_email(
            lead["email"], subject, body,
            tracking_id,
            lead.get("demo_tunnel_url") or "",
            business_id=lead["id"],
        )
        mark_sent(lead["id"], "email", is_autopilot=True,
                  subject_used=subject, tracking_id=tracking_id)
        console.print(f"[green][Autopilot] Sent → {lead.get('name')} <{lead['email']}>[/]")
        return True
    except Exception as e:
        console.print(f"[red][Autopilot] Send failed for {lead.get('name')}: {e}[/]")
        return False


def run_autopilot():
    init_db()
    console.print("\n[bold cyan]═══ LeadFlow Autopilot Started ═══[/]")
    console.print("[dim]Ctrl-C to stop. Running forever.\n[/]")

    last_scrape = 0.0

    while True:
        now = time.time()

        # ── Scrape if pool is low or timer elapsed ─────────────────────────
        new_count = get_unsent_lead_count()
        if new_count < MIN_NEW_LEADS or (now - last_scrape) >= SCRAPE_EVERY:
            _scrape_cycle()
            last_scrape = time.time()

        # ── Send emails for all approved leads ─────────────────────────────
        daily_limit = get_dynamic_send_limit()
        sent_today  = get_emails_sent_today()
        headroom    = daily_limit - sent_today

        if headroom <= 0:
            console.print(f"[yellow][Autopilot] Daily send limit reached ({sent_today}/{daily_limit}). Sleeping 1h.[/]")
            time.sleep(3600)
            continue

        # Auto-approve new leads (autopilot trusts the scraper/quality-gate)
        new_leads = get_leads(status="new")
        for lead in new_leads:
            update_business_status(lead["id"], "approved")

        approved = get_leads(status="approved")
        if not approved:
            stats = get_stats()
            console.print(
                f"[dim][Autopilot] Nothing to send. "
                f"new={stats.get('new',0)} approved={stats.get('approved',0)} "
                f"sent={stats.get('sent',0)} replied={stats.get('replied',0)}. "
                f"Sleeping {CYCLE_SLEEP}s.[/]"
            )
            time.sleep(CYCLE_SLEEP)
            continue

        sends = 0
        for lead in approved:
            if sends >= headroom:
                break
            if not can_sender_send(lead.get("email")):
                console.print("[yellow][Autopilot] Sender limit hit mid-batch.[/]")
                break
            sent = _write_and_send(lead)
            if sent:
                sends += 1
                time.sleep(SEND_PAUSE)

        if sends == 0:
            console.print(f"[dim][Autopilot] 0 sent this cycle (no valid emails). Sleeping {CYCLE_SLEEP}s.[/]")
            time.sleep(CYCLE_SLEEP)
        else:
            console.print(f"[bold green][Autopilot] Cycle done: {sends} emails sent.[/]")


if __name__ == "__main__":
    try:
        run_autopilot()
    except KeyboardInterrupt:
        console.print("\n[dim]Autopilot stopped.[/]\n")
