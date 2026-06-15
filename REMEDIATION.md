# LeadFlow Audit & Remediation Log

This document records the comprehensive audit, bug fixes, performance optimizations, and security patches applied to the LeadFlow codebase to ensure robustness, compliance, and clean operation.

## 🛠️ Summary of Key Remediations

### 1. Autopilot Spam & Reputation Protection
* **Automatic Opt-Out Footer (`sender.py`):** Cold outreach emails and follow-ups now append a CAN-SPAM compliant opt-out footer allowing users to reply `"stop"` to unsubscribe.
* **Auto-Opt-Out Detection (`imap_sync.py`):** Inbox reply sync reads message bodies and detects opt-out/unsubscribe intent. On detection, it automatically transitions the lead status to `opted_out` and deletes all pending follow-up triggers.
* **Daily Sending Limits (`scheduler.py` & `database.py`):** Added a daily tracking function (`get_emails_sent_today`) and enforced a strict limit of 25 sent emails per day in background jobs to prevent sudden sending spikes that trigger spam filters.

### 2. CRM & Visual Pipeline Improvements
* **Approved Column Category (`templates/kanban.html`):** Restructured the Kanban layout to include the `👍 Approved` column (`var(--orange)`).
* **Card Button Cleanup:** Dragging cards dynamically removes action buttons (like `+ Log Deal`) when they are moved out of the `Replied` column.
* **Red-Flagged Opt-Out UI (`templates/leads.html` & `base.html`):** 
  * Added red-badge styling (`OPTED_OUT`) to the lead lists.
  * Added a prominent red warning banner inside the selected lead view indicating they are blacklisted.
  * Disabled all interactive controls (preview, copy link, draft generation) for blacklisted contacts to prevent accidental communication.
  * Added a sidebar statistics counter specifically for blacklisted opt-outs.

### 3. Database Integrity & Leak Prevention
* **Deduplication (`database.py`):** Implemented validation in `insert_business` to prevent duplicate business rows from being created on repeated scans by checking matches on website URLs, names, phone numbers, and cities.
* **Safe Binding Parameter Defaults:** Configured defaults for all optional parameters in `insert_business` to prevent sqlite3 driver crashes when scraping incomplete data.
* **Connection Leak Auditing:** Wrapped SQLite and IMAP connections in `imap_sync.py` in `try...finally` blocks to ensure they are cleanly closed even in the case of network errors.
* **Scheduler Optimization:** Refactored background tasks in `scheduler.py` to fetch row data, immediately close connections, and sleep/call external APIs offline, preventing database resource locks.
* **Closed Deal Revenue tracking:** Fixed `insert_deal` in `database.py` to record deal status as `closed` and update `closed_at`, allowing accurate dashboard revenue calculations.

### 4. Git Deployment & Demo Resolvers
* **Deployment Concurrency Protection:** Added `git pull --rebase` before every automated `git add/commit/push` command in `server.py` to avoid non-fast-forward push rejections.
* **Demo Site Logic Sync:** Fixed the `/demo/{bid}` endpoint in `server.py` to dynamically inspect and regenerate Gym-specific templates using `generate_gym_demo_html` if cache is absent.
* **Correct Copy-Link Endpoint:** Updated `/api/demo-url/{bid}` to query `demo_tunnel_url` from the database first, ensuring copied links resolve to the correct URL scheme (whether folder-based or slug-based).

---
*Log generated and confirmed on June 15, 2026.*
