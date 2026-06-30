# LeadFlow

LeadFlow is an autonomous, end-to-end outbound sales and lead generation system designed for freelancers and web development agencies. It works silently in the background to scrape Google Maps, analyze business websites, build fully customized demo websites, draft AI-personalized outreach, and automatically send emails and follow-ups.

---

## Key Features

### 1. Automated Lead Generation & Deduplication
- **Intelligent Scraping:** Uses the Google Places API to find local businesses based on niche and location.
- **Smart Deduplication:** Performs domain-based extraction and name-similarity comparisons to avoid reaching out to the same business twice.
- **Contact Enrichment:** Scrapes emails, social profiles, and verifies if phone numbers are WhatsApp-ready.
- **Owner Name Extraction:** Scrapes the business "About" or "Team" pages to identify owner names, automatically personalizing salutations (e.g. *Hey Mike,* instead of *Hey there,*).

### 2. Website Performance Auditing & Grading
- **Automatic Grading:** Evaluates lead websites using the Google PageSpeed Insights API.
- **Visual CRM Badging:** Marks leads with Hot (🔥), Warm (🌡️), or Cold (🧊) badges based on site performance scores, helping prioritize outreach to low-performing sites.

### 3. Premium Demo Generation & Deployment
- **Niche Templates:** Pre-designed premium HTML templates for multiple niches:
  - **Fitness & Gyms** — Dark neon sports aesthetics
  - **Restaurants & Cafes** — Warm amber food-photography aesthetics
  - **Dentist & Clinics** — Clean teal medical layout
  - **Barbershops & Salons** — Vintage burgundy grooming portfolio
  - **Real Estate** — Navy and gold luxury properties
- **Central Template Manager:** Enable/disable specific templates dynamically from the dashboard.
- **Cloudflare Edge Rendering (Zero Latency):** Demos are rendered instantly on the Cloudflare Edge network. Data is synced to Cloudflare KV, meaning demos load globally in milliseconds with zero server load on the local machine.


### 4. Cloudflare Worker Telegram Bot & Mobile Outreach
- **IG DM & WhatsApp Modes:** Swipe through generated outreach directly from your phone on Telegram. Tap buttons to view demo, copy DM text, open WhatsApp, or mark as sent.
- **Auto-Sync & Tracking:** Click tracking (via NTFY push notifications) and `/replied` command tracking immediately sync to the Cloudflare KV store and propagate down to the local database.
- **Serverless Webhook:** The Telegram bot runs 100% on Cloudflare Workers, ensuring 99.99% uptime and zero local API polling overhead.

### 5. High-Availability (HA) Firestick + Mac Split-Brain
- **Offloaded Background Jobs:** Heavy scraping, AI generation, and scheduling run 24/7 on an Android Firestick via Termux to save Mac battery and resources.
- **Cloudflare KV Sync:** The Mac and Firestick never talk directly; they both sync their state, stats, and queues (like `ig_done_queue` and `wa_done_queue`) via Cloudflare KV, creating a resilient split-brain architecture.

### 6. Smart Multi-Model Copywriter & Key Rotation Pool
- **5-Tier Fallback Chain:** Directs prompt requests through a self-healing chain of AI services:
  `agy CLI → Gemini REST API → OpenAI → Claude → Offline Templates`
- **Gemini API Key Rotation Pool:**
  - Supports up to 8+ comma-separated Gemini API keys in `.env` for free-tier rate limit bypass.
  - Uses **one key at a time** — retries the same key once (with 1s delay) before rotating to the next key. Only moves to key #2 if key #1 fails twice in a row.
  - Compatible with both legacy `AIzaSy...` keys and new AI Studio `AQ.Ab8...` keys.
- **Test Keys Button:** Settings page includes a one-click **🔌 Test Keys** button that validates each key in the pool individually against `gemini-2.5-flash` and reports Active / Quota Exhausted / Invalid status per key.
- **Smart Model Routing:**
  - **Outreach & Sequences:** Uses REST API keys first with configurable primary/secondary/tertiary models (`gemini-2.5-flash`, `gemini-2.5-pro`, `gemini-3-flash-preview`) to save local system resources.
  - **Audits & Complex Logic:** Reserves local `agy` CLI models (e.g. `Claude Sonnet 4.6 (Thinking)`, `Gemini 3.1 Pro (High)`) for logical tasks.
  - All 6 model slots are configurable from the Settings page without touching code.
- **Offline Template Fallback:** Provides pre-written copy variants for all outreach contexts (initial, follow-ups, audits, no-website, live follow-ups) if all APIs are offline.

### 7. Interactive Kanban Pipeline & CRM
- **Pipeline Stages:** Manage leads through a visual drag-and-drop pipeline: *New → Generated → Sent → Opened → Demo Viewed → Replied → Approved → Converted*.
- **Interaction Logging:** Tracks real-time events like email opens, demo site visits, and replies.
- **Opt-Out Blacklisting:** Automatically detects opt-out replies ("stop", "unsubscribe") via IMAP sync, marks leads as opted-out, cancels all pending follow-ups, and disables all communication controls for that lead.

### 8. Campaign Analytics & A/B Testing
- **Conversion Funnel:** Visualizes transition rates from discovery to conversion.
- **A/B Subject Line Performance:** Logs which subject line was used per send and computes per-subject open rates to surface top performers.
- **Performance Matrices:** Breaks down outreach performance by city and business category.

### 9. Settings & Configuration
- **In-Dashboard `.env` Editor:** All API keys, SMTP credentials, model selections, and URLs are editable directly from the web UI — no terminal required.
- **Show/Hide Secrets Toggle:** One-click checkbox to reveal or mask all password fields simultaneously.
- **API Key Validator:** Test each Gemini key individually from the settings page with real-time status badges.
- **Gmail Connection Tester:** Verifies SMTP + IMAP credentials before enabling Autopilot.

---

## Technology Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12, FastAPI, Uvicorn |
| Database | SQLite (via `database.py`) |
| Frontend | HTML5, Vanilla CSS, JavaScript (ES6) |
| Automation | APScheduler |
| AI / LLM | Google Antigravity SDK (`agy` CLI) & Gemini REST API |
| Outreach | Gmail (SMTP/IMAP) + Telegram UI (IG DM / WA Mode) |
| Deployment | Cloudflare Workers (Bot & Demos), Cloudflare KV (State Sync) |
| Process Management | macOS LaunchAgent + Firestick Termux (24/7 Headless) |

---

## Setup & Installation

> **⚠️ Never commit your `.env` file. All API keys must stay secret.**

### 1. Clone & Install Dependencies
```bash
git clone https://github.com/Power7T/leadflow.git
cd leadflow
pip install -r requirements.txt
pip install phonenumbers --break-system-packages
```

### 2. Create Your `.env` File
```env
# Gemini AI Studio keys — comma-separated pool (up to 8+, supports AQ. and AIzaSy. prefixes)
GEMINI_API_KEY=AQ.key1,AQ.key2,AIzaSykey3

# Google APIs
GOOGLE_MAPS_API_KEY=your_maps_api_key
GOOGLE_PAGESPEED_API_KEY=your_pagespeed_api_key

# OpenAI fallback
OPENAI_API_KEY=sk-...

# GitHub Pages demo deployment
GITHUB_TOKEN=your_github_pat
GITHUB_DEMO_REPO=your_username/leadflow-demos

# Gmail SMTP/IMAP outreach
SENDER_EMAIL=you@gmail.com
SENDER_APP_PASSWORD=your_16_char_app_password

# Booking & Payment links
BOOKING_URL=https://calendly.com/your-username
STRIPE_PAYMENT_LINK=https://buy.stripe.com/...

# AI Model Routing (optional — defaults set automatically)
REST_PRIMARY_MODEL=gemini-2.5-flash
REST_SECONDARY_MODEL=gemini-2.5-pro
REST_TERTIARY_MODEL=gemini-3-flash-preview
```

### 3. Start LeadFlow
```bash
# Option A — macOS LaunchAgent (runs as background daemon, auto-restarts on reboot)
launchctl load ~/Library/LaunchAgents/com.leadflow.app.plist

# Option B — Direct
python3.12 -u server.py
```

### 4. Open Dashboard
```
http://127.0.0.1:8765
```

---

## Key Rotation Logic

LeadFlow's Gemini API key pool uses a **sticky retry-before-rotate** strategy:

```
Key #1 → Try
         ❌ Fail → wait 1s → Retry Key #1
                   ❌ Fail again → rotate to Key #2

Key #2 → Try
         ❌ Fail → wait 1s → Retry Key #2
                   ❌ Fail again → rotate to Key #3
...
```

This prevents abandoning a key on a single transient 503/quota blip.

---

## Disclaimer
This project is built for autonomous lead generation. Always ensure compliance with local anti-spam laws (CAN-SPAM, GDPR) when automating outreach.
