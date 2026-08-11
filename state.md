# LeadFlow State — 2026-08-08

## Architecture
- FastAPI server (`server.py`) on port 8765, APScheduler in `scheduler.py`
- ADB over WiFi: Firestick (`192.168.8.246:5555`), Vivo phone (`192.168.8.157:5555`)
- MAC resolution in `resolve_devices.py` — `get_subnet()` → `scan_network()` → `resolve()`
- Subnet auto-detects correctly as `192.168.8` (verified)
- Split-node architecture v1.1.0: Firestick=Gateway, Vivo=Primary Brain, Mac=Active-Active Fallback

## Network (2026-07-31) — RESOLVED
WiFi subnet changed 192.168.0.x → 192.168.8.x. All devices updated, IPs confirmed.

| Device     | IP              | ADB Status  |
|------------|-----------------|-------------|
| Firestick  | 192.168.8.246   | TCP/5555    |
| Vivo phone | 192.168.8.157   | TCP/5555    |
| Mac        | 192.168.8.225   | N/A         |

## Auto-Heal System (resolve_devices.py) — UPGRADED 2026-07-31

`ensure_connected(target)` has 3 layers:
1. Try cached IP → ADB shell test
2. MAC-based network scan → re-resolve IP → reconnect
3. **(Vivo only)** USB fallback: find USB-connected Android → `adb tcpip 5555` → reconnect wirelessly

ntfy push sent on IP change and on USB recovery event.

## Instagram DM Fixes — 2026-08-08

### Fix 1: unlock_screen() — accurate lock detection + phone stay-awake
- **Problem**: False-positive lock detection — `mCurrentFocus=StatusBar` fires when notification shade is open, not just when locked. Also phone's 30s screen timeout caused real locks between DM sequences.
- **Fix 1a (code)**: Replaced `mCurrentFocus=StatusBar` heuristic with `isStatusBarKeyguard=true` from `dumpsys window` as the authoritative check. Added `dumpsys power` wakefulness fallback. Now an inner `_is_locked()` function checks real keyguard state.
- **Fix 1b (device settings via ADB)**:
  - `settings put global stay_on_while_plugged_in 3` — screen stays on while charging (USB/AC)
  - `settings put secure lockscreen.disabled 1` — lock screen disabled entirely (swipe-only phone)
  - `settings put system screen_off_timeout 1800000` — 30 min timeout backup

### Fix 2: Permanent account skip detection
- **Problem**: Some accounts show "User not found", white screen, or "Following only" (private accounts). These returned `False` (transient) and were retried every hour indefinitely.
- **Fix**: Added `get_screen_text_set()` helper that reads existing `/sdcard/window_dump.xml` to diagnose screen state when Message button not found.
- **Return value semantics**: `send_instagram_dm()` returns `True` (success), `False` (transient, retry next hour), `None` (permanent skip — account deleted / private).
- **DB changes**: New `outreach.status = 'ig_skip'` for permanently inaccessible accounts. `follow_ups.status = 'skipped'` for follow-up sequences.
- **Scheduler**: Both `job_auto_send_instagram_dms` and `job_auto_send_followups` check `if ok is None:` to trigger ig_skip DB update.

### Server restart
- Server restarted via `launchctl kickstart -k gui/$(id -u)/com.leadflow.app` at ~22:58
- New PID confirmed active, both files passed `python3 -m py_compile` before restart
- Next IG DM job fires hourly; job at 23:00 is the first run with new code

## Files Updated (2026-08-08)
- `instagram_sender.py` — `unlock_screen()` 4-attempt fix, `get_screen_text_set()` helper, permanent skip detection in `send_instagram_dm()`
- `scheduler.py` — `ig_skip` handling in `job_auto_send_instagram_dms`, `skipped` handling in `job_auto_send_followups`

## Files Updated (2026-07-31)
- `resolve_devices.py` — fallback subnet `192.168.8`, upgraded `ensure_connected`, cleaned duplicate imports
- `database.py` — added `is_suppressed(email, business_id=None)` at EOF (fixes followup failures)
- `scheduler.py` — `job_adb_keepalive` `misfire_grace_time=60`, `job_device_health` `misfire_grace_time=300`
- IP cache files (`~/.vivo_ip`, `~/.firestick_ip`, `leadflow/.vivo_ip`) updated
- All 20 live .py files: fallback IPs updated (192.168.0.113→.8.246, 192.168.0.162→.8.157)
- `templates/base.html` sidebar links updated
- Firestick `/data/local/tmp/` — pushed: database.py, resolve_devices.py, scheduler.py, sender.py, server.py, .firestick_ip, .vivo_ip

## Vivo Self-Hosting Status (2026-08-08)
- Vivo's `server.py` is a **stub** FastAPI app — all routes return "LeadFlow Split-Architecture Active - Vivo Node"
- Only ONE Python process on Vivo (PID 27262): the stub server.py
- No `ig_session_runner.py` or `vivo_ig_ui_sender.py` is running — they exist on disk but are not executed
- **Mac handles ALL IG DMs** via ADB-over-WiFi to Vivo (192.168.8.157:5555)
- Termux `allow-external-apps = true` now enabled — future RUN_COMMAND broadcasts will work
- Termux wake-lock active — Termux won't be killed by Android

## Known Issues / TODOs
- `database.py` replication path: verify `import os` present (may be missing in one codepath)
- Instagram Reply job: verify `from pathlib import Path` present
- Firestick disk at **100% full** — needs log/cache cleanup. ADB push may fail.
- Firestick running Python processes: cloudflared/watchdog/bot not confirmed running — needs investigation
- Vivo CPU load was elevated (3.23–4.57) after WiFi reconnect — monitor for normalization


## Updates (2026-08-11)
- Implemented ADB Keyboard (AdbIME) on the Vivo device to bypass the Kika IME's autocorrect engine, completely resolving mangled DM inputs.
- Modified `type_text` in `instagram_sender.py` and `type_text_safe` in `vivo_ig_ui_sender.py` to transmit messages instantly and safely via base64 ADB broadcasts.
- Reduced post-typing sleep duration from up to 40 seconds down to 1.5 seconds when using ADB Keyboard, massively speeding up outreach sessions.
- Upgraded coordinate validation checks in `confirm_message_typed` and duplicate check sequences to normalize special characters, spaces, and contractions.
- Fixed the AI writer's `clean_ai_output` parser in `ai_writer.py` to extract responses on the same line as keywords, preventing fallbacks to raw prompt texts.
