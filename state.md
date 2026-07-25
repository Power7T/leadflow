# LeadFlow State — 2026-07-19

## Architecture
- FastAPI server (`server.py`) on port 8765, APScheduler in `scheduler.py`
- ADB over WiFi: Firestick (192.168.0.113:5555), Vivo phone (192.168.0.162:5555)
- MAC resolution in `resolve_devices.py` — `get_subnet()` → `scan_network()` → `resolve()`
- Cloudflare Pages: `npx wrangler pages deploy demos/` with Account API Token (`cfat_...`)
- Gmail IMAP via `SENDER_APP_PASSWORD` env var (comma-separated for multiple accounts)

## Key Env Vars
- `SENDER_APP_PASSWORD='yisx ywet ajwj fihy, sqyt ngpg jymi uihi'` — chandango12 (new), bhartimitrabot (unchanged)
- `CLOUDFLARE_API_TOKEN='cfat_[REDACTED]'` (Account token, NOT User token)
- `LEADFLOW_DEVICE_ROLE='backup'` (on Mac)

## Completed Fixes (this session)
1. **App Password** — Updated chandango12 password in `.env` (Mac + Firestick via ADB push)
2. **Subnet auto-detect** — `resolve_devices.py` fallback now uses socket-based IP detection, falls back to `192.168.0` (not `192.168.1`)
3. **IG reply hardcoded path** — `scheduler.py` now uses `Path(__file__).parent / "ig_reply_responder.py"`
4. **ig_rate_state missing** — `scheduler.py` `job_unfollow_ghosts()` calls `ig_rate_db.migrate()` before unfollow routine
5. **OpenWRT router IP** — `get_active_network_name()` dynamically uses `get_subnet().1` instead of hardcoded `192.168.1.10`
6. **Internet check** — `ai_writer.py` `check_internet()` probes 4 endpoints for resilience
7. **Duplicate daemons** — `run_daemon.sh` has PID lockfile at `/tmp/leadflow_daemon.pid`
8. **Kanban sort crash** — `database.py` + `replicate.py` use `COALESCE(b.lead_score, 0)` for NULL-safe sort
9. **demos/ bloat** — `scheduler.py` weekly `job_cleanup_demos_dir()` removes HTMLs older than 30 days
10. **CF Pages artifacts** — `.wranglerignore` excludes `__pycache__`, `*.log`, `*.bak`, `*.db`, `fix_*.py`
11. **ADB timeouts** — `instagram_sender.py` ADB shell timeout increased 30→60s
12. **Watchdog logging** — `start_watchdog.sh` now logs heartbeat every 30 min + logs start event
13. **IMAP env reload** — `imap_sync.py` uses `load_dotenv(override=True)` to pick up new passwords
14. **Firestick disk** — Cleaned via ADB: truncated server_run.log/server.log, deleted 14 fix_*.py, removed __pycache__
15. **All files pushed** — scheduler.py, resolve_devices.py, database.py, replicate.py, ai_writer.py, instagram_sender.py, imap_sync.py, start_watchdog.sh, .env all pushed to Firestick

## Running Processes (Mac)
- `run_daemon.sh` PID 36049 → server.py PID 36051, demo_server.py PID 36052
- Server started 2026-07-19 22:03:51 with new .env loaded
- Tunnel URLs: https://regulated-cups-liability-rides.trycloudflare.com (8765), https://vast-often-careful-sessions.trycloudflare.com (8766)

## A/B Test Report — All Action Items Status (2026-07-20)

### 🔴 URGENT — DONE
- **AB open attribution wired**: `record_tracking_event()` now calls `record_ab_open(tracking_id)` on opens; `follow_ups.opened=1` and `follow_ups.clicked=1` also set
- **follow_ups schema**: Added `opened`, `clicked`, `replied` columns via migrate() ALTER TABLE
- **579 invalid AB tests reset**: `winner=NULL, resolved_at=NULL` for all tests with `opens_a=0 AND opens_b=0` — Mac DB done; Firestick pending `python3 firestick_db_fix.py`

### 🟠 HIGH — DONE
- **Variant A locked**: `ai_writer.py` — removed hashlib % 4 logic, `variant = "A"` unconditionally
- **425 unsent B/C/D leads migrated to A**: Mac DB done; Firestick pending `python3 firestick_db_fix.py`

### 🟡 MEDIUM — DONE
- **Category priority ORDER BY**: `scheduler.py` Pool A + Pool B queries now prioritise accountant/medspa/solar/gym/dentist (ORDER BY CASE WHEN ... THEN 0 ELSE 1 END ASC, lead_score DESC)
- **Tier scoring fixed**: `database.py` — gym/fitness/yoga/accountant/cpa promoted from Tier 2 → Tier 1 (A/B data shows they outperform)
- **follow_ups tracking**: opened/clicked/replied columns added + wired in database.py

### 🟢 LOW — DONE
- **ig_link_delivered flag**: `scheduler.py` sets `ig_link_delivered=1` after DM send when draft contains "http" or "www."
- **IG reply tracking**: `ig_reply_responder.py` `respond_with_link()` now also sets `outreach.replied=1` and `follow_ups.replied=1` on positive reply

### ⏳ PENDING (requires Firestick manual action)
1. **Restart server.py** on Firestick: `pkill -f server.py` in Termux (watchdog auto-restarts)
2. **Run Firestick DB fix**: `python3 /data/data/com.termux/files/home/leadflow/firestick_db_fix.py`
   - Adds follow_ups columns (opened/clicked/replied)
   - Resets bad AB tests (winner=NULL)
   - Migrates B/C/D leads to Variant A

### NOT YET DONE
- WhatsApp reply tracking (whatsapp_sender.py → mark outreach.replied=1)
- Tree service anomaly investigation
- Email body copy improvement for accountant/medspa categories


## Remote Architecture & Failover (Task 1)
- Saved architectural plan to [leadflow_remote_architecture_rfc.md](./leadflow_remote_architecture_rfc.md).
- Cloudflared tunnel deployed via Termux on Firestick (see `termux_cf_setup.sh`). This tunnel allows the remote Mac to bridge into the local ADB network.
- Bidirectional Failover uses the Cloudflare Worker KV (`is_leader()`) logic already in place: Firestick is Primary, Mac is Backup. If the Firestick misses heartbeats, the remote Mac assumes leadership and tunnels ADB commands through `cloudflared` down to the proxy Termux host, seamlessly controlling the Vivo phone.

## Failover Parity Fix (Task 2)
- **2026-07-21**: Removed `_firestick_only` decorators from WhatsApp and Instagram draft generation in `scheduler.py`. The Mac now serves as an exact, 100% mirrored bidirectional failover candidate, possessing all the same capabilities as the primary device.
