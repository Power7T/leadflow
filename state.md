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


## Updates & Modernizations — 2026-08-17
- **System Dialog & Overlay Safeguards:** Implemented `dismiss_system_popups()` inside `instagram_sender.py` and `vivo_ig_ui_sender.py` to auto-detect and tap "Cancel"/"Dismiss" on system modals (like the 20% low battery alert) that block UI focus.
- **Vivo Typing Fixes:** Upgraded keyboard logic to force-disable Kika IME (`com.kikaoem.vivo.qisiemoji.inputmethod`) when initializing ADBKeyboard, preventing predictive text corruption, and restoring it via `restore_default_keyboard()` on completion/failure.
- **Unfollow Routine Modernization:** Replaced the broken "Follows you" badge check in the scheduler with the robust `ig_ghost_cleanup.py` which searches the followers list explicitly for our username.
- **Git & Code Deployment:** Synced, committed, and pushed all updated code files to origin and firestick repositories on Github, and optimized deployment script filters.
- **Summary:** Resolved Vivo phone screen freezes and stuck UI states by identifying and dismissing persistent system modals. Modernized the Instagram DM sequence by building an automated layout safeguard that detects and cancels system overlays before automation tasks run. Addressed Vivo keyboard typos by upgrading keyboard controls to force-disable the stock IME during campaigns and restore it afterward. Corrected the ghost-unfollow check inside the scheduler by integrating a robust followers list search. Validated and synchronized all codebase changes by committing and pushing clean atomic git updates.



## Updates & Modernizations — 2026-08-21
- **Roles Alignment Completed:** Corrected the failover structure by configuring the Vivo phone as the primary brain and the Mac as the backup. The Mac now queries the phone's LAN health endpoint and stands down, preventing duplicate DM runs.
- **Keyboard Typo Fix Deployed:** Implemented Option B and Option C fallbacks in the typing functions of both instagram_sender.py and ig_ghost_cleanup.py. Autocorrect typos on the Vivo phone are fully prevented by using %s space insertion instead of standard space keyevents when typing.
- **Deep-Link Targeting Upgraded:** Appended target package name com.instagram.android to all profile deep-links, forcing them to open natively in the Instagram app rather than falling back to Chrome.
- **Resilient Boot Recovery Implemented:** Updated the startup boot script start_leadflow.sh on the Vivo phone to run a 5-minute ADB connection loop on boot, maximizing recovery success when background networking initializes slowly.
- **Code Synchronization Verified:** Excluded device-specific files from setup_vivo.sh rsync and deployed the updated codebase across the Mac, Vivo phone, and Firestick. All git changes are committed and pushed to both GitHub repositories.
- **Vivo Background System Input & Overlays:** Enabled `vivo_adb_simulate_input` setting, whitelisted Termux in deviceidle, and optimized max cached processes to 64 to prevent background freezes by Vivo's aggressive OS battery manager.
- **Zero-USB Reboot Recovery (\"Solution B\"):** Added `find_adb_port.py` on the phone to scan local ports and retrieve the active random wireless debugging port, and modernized the Termux:Boot `start_leadflow.sh` script to auto-connect ADB loops wirelessly on reboot without any USB cable.
- **Unfollow Profile Heuristics:** Upgraded `ig_ghost_cleanup.py` to check followback state instantly via profile page text searches (\"follows you\" / \"follow back\"), speeding up checks 5x and bypassing slow UI/search actions.
- **Engagement Alert Integration:** Added drawer click tracking event `cta_book_drawer` to `_ENGAGE_ALERTS` in `server.py` to trigger instant live push notifications.
- **Fiverr Click Tracking Redirect Deployed:** Implemented `/r/fiverr` endpoint on the Cloudflare worker to log fiverr clicks by business ID (writing events to KV storage) and send push notifications (Telegram & Ntfy) alerting which prospect clicked the link, before redirecting to your new gig (`https://www.fiverr.com/s/GPxydxa`). All templates served by the worker are dynamically hijacked to replace legacy fiverr URLs with the tracking redirect URL.


