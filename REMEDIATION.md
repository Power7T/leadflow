# LeadFlow Audit & Remediation Log

This document records all audits, bug fixes, performance optimizations, security patches, and feature additions applied to the LeadFlow codebase in chronological order.

---

## ✅ Phase 1 — Foundation & Security (June 14–15, 2026)

### 1. Autopilot Spam & Reputation Protection
- **CAN-SPAM Opt-Out Footer (`sender.py`):** Cold outreach emails and follow-ups now append a compliant opt-out footer allowing recipients to reply `"stop"` to unsubscribe.
- **Auto-Opt-Out Detection (`imap_sync.py`):** IMAP reply sync detects opt-out/unsubscribe intent in message bodies, automatically sets lead status to `opted_out`, and cancels all pending follow-up triggers.
- **Daily Sending Limits (`scheduler.py` & `database.py`):** Added `get_emails_sent_today()` and enforced a 25 emails/day limit in background jobs to prevent sending spikes that trigger spam filters.

### 2. CRM & Visual Pipeline Improvements
- **Approved Column (`templates/kanban.html`):** Added `👍 Approved` Kanban column between `Replied` and `Converted`.
- **Card Button Cleanup:** Dragging cards dynamically removes action buttons (e.g. `+ Log Deal`) when moved out of the `Replied` column.
- **Opt-Out UI (`templates/leads.html` & `base.html`):**
  - Added red `OPTED_OUT` badge to lead list entries.
  - Added a red warning banner inside the selected lead view for blacklisted contacts.
  - Disabled all interactive controls (preview, copy link, draft generation) for opted-out leads.
  - Added sidebar stats counter for opted-out leads.
- **Autopilot Status Badge (`base.html`, `style.css`, `database.py`):** Pulsing green/gray real-time status indicator in the sidebar showing whether Autopilot is active or stopped.

### 3. Database Integrity & Connection Leak Prevention
- **Deduplication (`database.py`):** `insert_business()` now checks for duplicates via website domain, name similarity (>85%, difflib), phone number, and city.
- **Safe Binding Defaults:** All optional parameters in `insert_business()` have defaults to prevent sqlite3 driver crashes on incomplete scrape data.
- **Connection Leak Fixes (`imap_sync.py`):** Wrapped all SQLite and IMAP connections in `try...finally` blocks.
- **Scheduler Optimization (`scheduler.py`):** Background tasks now fetch data, close DB connections immediately, then perform network I/O — eliminating resource lock contention.
- **Deal Revenue Tracking (`database.py`):** Fixed `insert_deal()` to record `status=closed` and `closed_at` timestamp for accurate dashboard revenue totals.

### 4. Git Deployment & Demo Resolver Fixes
- **Concurrency Protection (`server.py`):** Added `git pull --rebase` before every automated push to avoid non-fast-forward rejections.
- **Demo Site Cache Sync:** Fixed `/demo/{bid}` to regenerate missing demos from templates on cache miss.
- **Copy-Link Endpoint:** `/api/demo-url/{bid}` now queries `demo_tunnel_url` from DB first, ensuring the correct URL scheme is returned.

---

## ✅ Phase 2 — Intelligence & Template Expansion (June 16–17, 2026)

### 5. Multi-Niche Demo Templates
- Added 4 new premium Jinja2 demo templates:
  - `restaurant.html` — Warm amber food aesthetics, Playfair Display + Lato fonts
  - `dentist.html` — Clean teal medical layout, Inter font
  - `barbershop.html` — Vintage burgundy portfolio, Oswald + Open Sans fonts
  - `realestate.html` — Navy/gold luxury property layout, Cormorant Garamond + Raleway fonts
- All templates include: sticky glassmorphism nav, scroll-reveal animations, demo banner with Fiverr CTA, Jinja2 lead variables (`{{ lead.name }}`, `{{ lead.city }}`, etc.), and tracking pixel.
- **Template Config System (`demo_templates/config.json`):** Centralised enable/disable toggle for each template with niche keyword matching.
- **Template Toggle UI (`templates/demos.html`):** ON/OFF pill toggles per template from the dashboard.

### 6. Data Intelligence Upgrades
- **Owner Name Extraction (`extractor.py`):** Scrapes About/Team pages for owner patterns; result stored in `contacts.owner_name` and used in AI greeting personalization.
- **Hot/Warm/Cold Badges (`templates/leads.html`):** Lead list and detail panel now show visual temperature badges based on `website_score`.
- **A/B Subject Tracking (`database.py`, `server.py`, `templates/analytics.html`):** Records `subject_used` per send; `/analytics/ab-subjects` endpoint returns per-subject open rates for the analytics dashboard.

### 7. AI Model Routing & Settings UI
- **Configurable Model Slots (`templates/settings.html`):** All 6 model routing slots (REST Primary/Secondary/Tertiary, agy Audit/Default/Chat) are now selectable from the Settings page with dropdowns.
- **Single Key Field with Rotation (`templates/settings.html`):** One `GEMINI_API_KEY` field accepts a comma-separated pool of keys; commas are hidden in password mode but preserved in the actual value.
- **Show/Hide Secrets Toggle:** Single checkbox reveals all password fields simultaneously (GEMINI, OPENAI, Maps, Hunter, Apollo, SMTP).
- **REST → agy Task Routing (`ai_writer.py`):** Outreach uses Gemini REST API keys first; complex logic/audits are routed to local `agy` CLI models.

---

## ✅ Phase 3 — API Key Validation & Reliability (June 17–18, 2026)

### 8. Gemini API Key Test Tool
- **Backend Endpoint (`server.py` — `POST /settings/test-gemini`):**
  - Accepts comma-separated key pool from the frontend.
  - Validates each key individually against `gemini-2.5-flash` (updated from deprecated `gemini-1.5-flash` which returns 404 for new `AQ.` keys).
  - Returns per-key status: `active` / `exhausted` / `invalid` with masked key display (`AQ.Ab8...LklQ`).
  - Uses `ssl._create_unverified_context()` to bypass macOS local SSL certificate verification errors.
  - Maps HTTP 400/403/404 → `Invalid API Key`, HTTP 429/503 → `Quota / Temporarily Unavailable`.
- **Frontend UI (`templates/settings.html`):**
  - **🔌 Test Keys** button inline with the Gemini API key field.
  - Results displayed as per-key status cards with colored badges (✅ green / ⚠️ amber / ❌ red).

### 9. Sticky Retry-Before-Rotate Key Logic (`ai_writer.py`, `server.py`)
- **Old behaviour:** Try key #1 → fail → immediately try key #2.
- **New behaviour:** Try key #1 → fail → wait 1s → retry key #1 → fail again → rotate to key #2.
- Prevents abandoning a healthy key on a single transient 503 / Google edge-node blip.
- Same logic applied in both runtime AI calls and the test endpoint.
- Removed stale `gemini-1.5-flash` fallback from `_run_gemini_rest()` (model is deprecated for new keys).

---

- Updated `fix_tracking.py` to use `os.getenv('HOME')` for demo directory path.

*Last updated: June 18, 2026*

