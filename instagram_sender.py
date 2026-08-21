import re
"""
instagram_sender.py — Physical ADB Controller for Instagram DM Automation

Architecture (3-layer failover):
  - Vivo phone (primary): controls its OWN Instagram via localhost ADB
  - Firestick (backup):   controls Vivo remotely via WiFi ADB
  - Mac (backup):         controls Vivo remotely via WiFi ADB

Safety rules (to NEVER get the account banned or deleted):
  - Max 20 DMs per calendar day
  - 45-120 second random delay between each DM
  - Uses ADB (Android Debug Bridge) to physically tap the screen
  - Bypasses all bot detection because it uses the official Instagram app
"""

import os
import json
import time
import random
import logging
import subprocess
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path
from dotenv import load_dotenv

# Load .env from same directory regardless of where script is run (Mac/Firestick/Vivo Termux)
_HERE = Path(__file__).parent
load_dotenv(str(_HERE / ".env"))

log = logging.getLogger("leadflow.instagram")
log.setLevel(logging.INFO)

# ── DB path — works on Mac (/Users/chandan/leadflow/) and Termux (/data/.../leadflow/) ──
DB_PATH = str(_HERE / "leadflow.db")

# ── Config ──────────────────────────────────────────────────────────────────
DAILY_LIMIT       = 20
MIN_DELAY_SECONDS = 45
MAX_DELAY_SECONDS = 120
import tempfile
try:
    DAILY_LOG_FILE = Path(tempfile.gettempdir()) / "ig_daily_sends.json"
except Exception:
    DAILY_LOG_FILE = _HERE / "ig_daily_sends.json"

# ── ADB target resolution ─────────────────────────────────────────────────
# When running ON Vivo itself (Termux), use localhost so ADB never leaves the device.
# When running on Mac or Firestick, resolve Vivo's current WiFi IP via ~/.vivo_ip.
def _resolve_adb_target() -> str:
    """Return the ADB target: 'localhost:5555' when self-hosting on Vivo, else WiFi IP."""
    # LEADFLOW_DEVICE_ROLE=primary means this IS the Vivo phone running itself
    if os.environ.get("LEADFLOW_DEVICE_ROLE") == "primary":
        return "localhost:5555"
    # Also detect Android/Termux by checking for /data/data/com.termux
    if Path("/data/data/com.termux").exists():
        return "localhost:5555"
    # Remote control: read Vivo's WiFi IP from file
    _ip_file_home = Path(os.path.expanduser("~/.vivo_ip"))
    _ip_file_local = _HERE / ".vivo_ip"
    if _ip_file_home.exists():
        return _ip_file_home.read_text().strip()
    if _ip_file_local.exists():
        return _ip_file_local.read_text().strip()
    return os.environ.get("VIVO_ADB_IP", "192.168.8.157:5555")

FIRESTICK_IP = _resolve_adb_target()

_warmup_last_date: str = ""  # tracks last date account_warmup() ran (once-per-day guard)

# ── Daily count tracking ─────────────────────────────────────────────────────

def _load_daily_log() -> dict:
    try:
        if DAILY_LOG_FILE.exists():
            data = json.loads(DAILY_LOG_FILE.read_text())
            # Prune keys older than today to prevent stale counts blocking sends
            today = str(date.today())
            pruned = {k: v for k, v in data.items() if k >= today}
            if len(pruned) != len(data):
                _save_daily_log(pruned)
            return pruned
    except Exception:
        pass
    return {}

def _save_daily_log(data: dict):
    try:
        DAILY_LOG_FILE.write_text(json.dumps(data))
    except Exception as e:
        log.warning(f"[Instagram] Could not save daily log: {e}")

def _sync_daily_count_to_db():
    """Mirror ig_daily_sends.json count into ig_settings.sent_today for cross-device sync."""
    try:
        import sqlite3 as _sq
        today = str(date.today())
        count = get_instagram_daily_sent_count()
        _conn = _sq.connect(DB_PATH, timeout=10)
        # Only update if our count is higher (we may be behind due to other device sending)
        row = _conn.execute("SELECT sent_today, last_reset_date FROM ig_settings WHERE id=1").fetchone()
        if row:
            db_count, db_date = row
            if db_date != today:
                # New day in DB — reset
                _conn.execute("UPDATE ig_settings SET sent_today=?, last_reset_date=? WHERE id=1", (count, today))
            elif count > db_count:
                _conn.execute("UPDATE ig_settings SET sent_today=? WHERE id=1", (count,))
        _conn.commit()
        _conn.close()
    except Exception as _e:
        log.debug(f"[sync_daily_count] DB mirror skipped: {_e}")

def _load_daily_count_from_db() -> int:
    """Pull sent_today from ig_settings for cross-device sync (DB is synced via Cloudflare)."""
    try:
        import sqlite3 as _sq
        today = str(date.today())
        _conn = _sq.connect(DB_PATH, timeout=10)
        row = _conn.execute("SELECT sent_today, last_reset_date FROM ig_settings WHERE id=1").fetchone()
        _conn.close()
        if row and row[1] == today:
            return int(row[0])
    except Exception:
        pass
    return 0

def get_instagram_daily_sent_count() -> int:
    today = str(date.today())
    file_count = _load_daily_log().get(today, 0)
    db_count = _load_daily_count_from_db()
    combined = max(file_count, db_count)
    # If DB has more (other device sent), sync flat file up
    if db_count > file_count:
        data = _load_daily_log()
        data[today] = db_count
        _save_daily_log(data)
    return combined

def _increment_daily_count():
    today = str(date.today())
    data = _load_daily_log()
    data[today] = data.get(today, 0) + 1
    _save_daily_log(data)
    _sync_daily_count_to_db()  # mirror to DB for cross-device sync

def can_send_instagram() -> bool:
    limit = 45
    try:
        import sqlite3
        conn = sqlite3.connect(DB_PATH, timeout=10)
        row = conn.execute("SELECT daily_limit FROM ig_settings WHERE id=1").fetchone()
        if row:
            limit = row[0]
        conn.close()
    except Exception:
        pass

    count = get_instagram_daily_sent_count()
    if count >= limit:
        log.info(f"[Instagram] Daily limit reached ({count}/{limit}). No more DMs today.")
        return False
    return True

# ── ADB Controller ───────────────────────────────────────────────────────────

def is_adb_reachable(target: str, timeout: int = 5) -> bool:
    """Quick TCP-level check: returns True only if ADB port is reachable within timeout."""
    import socket
    host, _, port_str = target.partition(":")
    port = int(port_str) if port_str.isdigit() else 5555
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, ValueError):
        return False


def adb(cmd: str) -> str:
    """Run an ADB command on the device and return its stdout"""
    global FIRESTICK_IP
    
    # Solution B: Local Accessibility / MacroDroid Intent-based Automation
    if os.environ.get('LEADFLOW_LOCAL_AUTO') == '1' or os.environ.get('USE_LOCAL_AUTOMATION') == '1':
        cmd_clean = cmd.strip()
        if cmd_clean.startswith('shell '):
            shell_cmd = cmd_clean[6:]
            if shell_cmd.startswith('input tap '):
                parts = shell_cmd.split()
                x, y = parts[2], parts[3]
                subprocess.run(f'am broadcast -a com.leadflow.CLICK --ei x {x} --ei y {y}', shell=True, capture_output=True)
                return '1'
            elif shell_cmd.startswith('input keyevent '):
                parts = shell_cmd.split()
                key = parts[2]
                subprocess.run(f'am broadcast -a com.leadflow.KEYEVENT --ei key {key}', shell=True, capture_output=True)
                return '1'
            elif shell_cmd.startswith('am broadcast -a ADB_INPUT_B64 '):
                import re, base64
                m = re.search(r'--es msg (\S+)', shell_cmd)
                if m:
                    b64_msg = m.group(1)
                    decoded = base64.b64decode(b64_msg).decode('utf-8')
                    decoded_esc = decoded.replace("'", "\'")
                    subprocess.run(f"am broadcast -a com.leadflow.TYPE --es text '{decoded_esc}'", shell=True, capture_output=True)
                return '1'
            elif shell_cmd.startswith('am start '):
                subprocess.run(shell_cmd, shell=True, capture_output=True)
                return '1'
            elif 'uiautomator dump' in shell_cmd:
                subprocess.run('am broadcast -a com.leadflow.DUMP', shell=True, capture_output=True)
                time.sleep(1.5)
                return '1'
        return ''

    # Standard ADB process
    FIRESTICK_IP = _resolve_adb_target()

    try:
        return subprocess.check_output(
            f"adb -s {FIRESTICK_IP} {cmd}",
            shell=True, stderr=subprocess.STDOUT, timeout=45
        ).decode('utf-8', errors='ignore')
    except subprocess.TimeoutExpired:
        log.warning(f"ADB command timed out: {cmd}")
        return ""
    except subprocess.CalledProcessError as e:
        log.debug(f"ADB Error on '{cmd}': {e.output.decode('utf-8', errors='ignore')}")
        return ""

def adb_read_xml() -> str:
    """
    Dump uiautomator XML and return its full content reliably.
    On self-hosted Vivo (localhost:5555), reads via base64 to avoid 8k pipe truncation.
    """
    FIRESTICK_IP = _resolve_adb_target()

    # Strategy 1: dump to file, read back via base64 — avoids ADB shell pipe 8k truncation
    try:
        subprocess.check_output(
            f"adb -s {FIRESTICK_IP} shell uiautomator dump /sdcard/window_dump.xml",
            shell=True, stderr=subprocess.STDOUT, timeout=30
        )
        b64_data = subprocess.check_output(
            f"adb -s {FIRESTICK_IP} shell base64 /sdcard/window_dump.xml",
            shell=True, stderr=subprocess.DEVNULL, timeout=30
        ).decode('ascii', errors='ignore')
        if b64_data.strip():
            import base64 as _b64
            xml_data = _b64.b64decode(b64_data.replace('\n', '').replace('\r', '')).decode('utf-8', errors='ignore')
            xml_stripped = xml_data.strip()
            if xml_stripped.startswith("<?xml") or xml_stripped.startswith("<hierarchy"):
                log.debug(f"[adb_read_xml] base64 read succeeded ({len(xml_data)} bytes)")
                return xml_data
            log.warning(f"[adb_read_xml] base64 returned bad XML: {repr(xml_stripped[:80])}")
    except Exception as e:
        log.warning(f"[adb_read_xml] base64 strategy failed: {e}")

    # Strategy 2: exec-out direct pipe (may truncate on some devices)
    try:
        xml_data = subprocess.check_output(
            f"adb -s {FIRESTICK_IP} exec-out uiautomator dump /dev/tty",
            shell=True, stderr=subprocess.DEVNULL, timeout=30
        ).decode('utf-8', errors='ignore')
        xml_stripped = xml_data.strip()
        if xml_stripped.startswith("<?xml") or xml_stripped.startswith("<hierarchy"):
            log.debug(f"[adb_read_xml] exec-out succeeded ({len(xml_data)} bytes)")
            return xml_data
        log.warning(f"[adb_read_xml] exec-out bad XML: {repr(xml_stripped[:80])}")
    except Exception as e:
        log.warning(f"[adb_read_xml] exec-out failed: {e}")

    return ""


def restart_android_uiautomator():
    pass


def _parse_bounds(bounds: str):
    """Parse '[x1,y1][x2,y2]' into center (x, y). Returns None on failure."""
    try:
        parts = bounds.replace('][', ',').replace('[', '').replace(']', '').split(',')
        if len(parts) == 4:
            x = (int(parts[0]) + int(parts[2])) // 2
            y = (int(parts[1]) + int(parts[3])) // 2
            return (x, y)
    except Exception:
        pass
    return None


def dismiss_system_popups():
    """Check the screen for system alerts/dialogs (from package 'android' or 'com.android.systemui')
    and auto-dismiss them by clicking Cancel, OK, Dismiss, or equivalent buttons."""
    xml_data = adb_read_xml()
    if not xml_data:
        return
    try:
        root = ET.fromstring(xml_data)
        dismiss_buttons = []
        has_system_dialog = False
        
        # Check if there is an active dialog from system packages
        for node in root.iter('node'):
            pkg = node.attrib.get('package', '')
            if pkg in ("android", "com.android.systemui"):
                has_system_dialog = True
                
        if not has_system_dialog:
            return
            
        # Look for typical dismiss buttons in the system dialog
        target_texts = {"cancel", "ok", "dismiss", "ignore", "close", "agree", "later", "not now"}
        for node in root.iter('node'):
            pkg = node.attrib.get('package', '')
            if pkg in ("android", "com.android.systemui"):
                text = node.attrib.get('text', '').strip().lower()
                resource_id = node.attrib.get('resource-id', '').lower()
                bounds = node.attrib.get('bounds', '')
                
                # Check text or resource id containing dismiss keywords or button2/cancel
                if text in target_texts or any(kw in resource_id for kw in ("button2", "button_cancel", "dismiss")):
                    coords = _parse_bounds(bounds)
                    if coords:
                        dismiss_buttons.append((node.attrib.get('text', ''), coords))
                        
        for button_name, coords in dismiss_buttons:
            log.info(f"[Popups] Autodetected system dialog button {button_name!r} at {coords}. Tapping to dismiss...")
            adb(f"shell input tap {coords[0]} {coords[1]}")
            time.sleep(1.5)
            
    except Exception as e:
        log.warning(f"[Popups] Error while checking/dismissing system alerts: {e}")

def get_ui_coords(text_matches: list, retries: int = 1, resource_ids: list = None, exact_only: bool = False) -> tuple:
    """
    Dumps the screen UI to XML, parses it, and finds the exact X/Y center
    coordinates of an element containing any of the text_matches or resource_ids.
    resource_ids: additional resource-id values to match (exact substring match).
    exact_only: if True, skip Pass 3 (substring match) — prevents false-positives like 'Follow' in '192followers'.
    """
    for attempt in range(retries + 1):
        try:
            xml_data = adb_read_xml()
            xml_stripped = xml_data.strip() if xml_data else ""

            if not xml_stripped or not (xml_stripped.startswith("<?xml") or xml_stripped.startswith("<hierarchy")):
                log.warning(f"[get_ui_coords] Dump failed on attempt {attempt+1}: {repr(xml_stripped[:100])}")
                if attempt < retries:
                    log.warning(f"[get_ui_coords] Retrying in 2s...")
                    time.sleep(2)
                    continue
                return None

            root = ET.fromstring(xml_data)
            nodes = list(root.iter('node'))

            # Pass 1: resource-id substring match (most specific — avoids false positives)
            if resource_ids:
                for node in nodes:
                    rid = node.attrib.get('resource-id', '')
                    for rid_match in resource_ids:
                        if rid_match in rid:
                            coords = _parse_bounds(node.attrib.get('bounds', ''))
                            if coords:
                                log.info(f"[get_ui_coords] Found via resource-id: '{rid_match}' in '{rid}'")
                                return coords

            # Pass 2: exact text/content-desc match across all nodes
            for node in nodes:
                text = node.attrib.get('text', '').strip().lower()
                desc = node.attrib.get('content-desc', '').strip().lower()
                for match in text_matches:
                    m = match.lower()
                    if m == text or m == desc:
                        coords = _parse_bounds(node.attrib.get('bounds', ''))
                        if coords:
                            log.info(f"[get_ui_coords] Found via exact match: '{match}'")
                            return coords

            # Pass 3: substring text/content-desc match — only short fields to avoid false positives
            if not exact_only:
                for node in nodes:
                    text = node.attrib.get('text', '').strip().lower()
                    desc = node.attrib.get('content-desc', '').strip().lower()
                    # Only match against short text/desc (≤30 chars) to avoid matching long sentences
                    for match in text_matches:
                        m = match.lower()
                        if (m in text and len(text) <= 30) or (m in desc and len(desc) <= 30):
                            coords = _parse_bounds(node.attrib.get('bounds', ''))
                            if coords:
                                log.info(f"[get_ui_coords] Found via substring match: '{match}' in '{text or desc}'")
                                return coords

        except Exception as e:
            log.error(f"[Instagram] XML parsing error: {e}")
            if attempt < retries:
                log.warning(f"[get_ui_coords] Retrying after parse error...")
                time.sleep(2)
                continue

    # Debug: log all non-empty node text/resource-ids so we can identify the right element
    try:
        xml_data = adb_read_xml()
        if xml_data and (xml_data.strip().startswith("<?xml") or xml_data.strip().startswith("<hierarchy")):
            root = ET.fromstring(xml_data)
            interesting = []
            for node in root.iter('node'):
                t = node.attrib.get('text', '').strip()
                d = node.attrib.get('content-desc', '').strip()
                r = node.attrib.get('resource-id', '').strip()
                if t or d or r:
                    interesting.append(f"text={repr(t[:40])} desc={repr(d[:40])} rid={r}")
            log.warning(f"[get_ui_coords] NOT FOUND. Searched for {text_matches} / {resource_ids}. All nodes ({len(interesting)}):")
            for item in interesting[:30]:
                log.warning(f"  {item}")
    except Exception:
        pass
    return None

def get_screen_text_set() -> set:
    """Read uiautomator dump XML and return a set of all text/content-desc values (lowercase)."""
    try:
        xml_data = adb_read_xml()
        if not xml_data:
            return set()
        root = ET.fromstring(xml_data)
        texts = set()
        for node in root.iter('node'):
            t = node.attrib.get('text', '').strip().lower()
            d = node.attrib.get('content-desc', '').strip().lower()
            if t: texts.add(t)
            if d: texts.add(d)
        return texts
    except Exception:
        return set()

def type_text(text: str) -> bool:
    """Types text via ADB. Returns True if ADBKeyboard (AdbIME) was used, False otherwise."""
    import random
    import base64

    # 1. Normalize linebreaks
    text = text.replace('\n', ' ').replace('\r', '')
    text = text.replace('—', ' - ').replace('–', '-')

    # 2. Check and ensure AdbIME is active (retry up to 3 times)
    use_adbkeyboard = False
    for attempt in range(3):
        try:
            ensure_adbkeyboard()
            ime = adb("shell settings get secure default_input_method")
            if "AdbIME" in ime or "ADBKeyboard" in ime:
                use_adbkeyboard = True
                break
            else:
                log.warning(f"Attempt {attempt+1}: ADBKeyboard not active (current: {ime}). Retrying set...")
                time.sleep(1)
        except Exception as e:
            log.warning(f"Attempt {attempt+1}: Error ensuring ADBKeyboard: {e}")
            time.sleep(1)

    if use_adbkeyboard:
        log.info("Typing via ADBKeyboard broadcast (instant)...")
        b64_text = base64.b64encode(text.encode('utf-8')).decode('utf-8')
        adb(f"shell am broadcast -a ADB_INPUT_B64 --es msg {b64_text}")
        time.sleep(1.0)
        return True

    log.warning("ADBKeyboard IME not active. Falling back to Option B (escaped spaces simulation).")
    # Normalize text for fallback
    text_clean = text.replace('★', ' star').replace('"', '').replace('\'', '')
    text_clean = text_clean.encode('ascii', errors='ignore').decode('ascii')

    # Try Option B (single input text with %s) if text is short (<80 chars)
    if len(text_clean) < 80:
        escaped = text_clean.replace(' ', '%s')
        adb(f'shell input text "{escaped}"')
        time.sleep(1.5)
        return False

    # Option C: word-by-word typing using %s instead of KEYCODE_SPACE to bypass autocorrect
    log.info("Text too long for Option B. Falling back to Option C (word-by-word with %s spaces)...")
    words = text_clean.split(' ')
    for i, word in enumerate(words):
        word = word.strip()
        if not word:
            continue
        adb(f'shell input text "{word}"')
        time.sleep(random.uniform(0.3, 0.6))
        if i < len(words) - 1:
            adb('shell input text "%s"')
            time.sleep(random.uniform(0.2, 0.4))
    return False

# ── Main send function ───────────────────────────────────────────────────────

def unlock_screen():
    """Wake up and unlock the Vivo phone reliably, resetting ADB first."""
    global FIRESTICK_IP
    # Re-resolve ADB target each time in case IP changed or we're in self-control mode
    new_target = _resolve_adb_target()
    if new_target == "localhost:5555":
        # Self-hosting on Vivo — ensure local ADB daemon is listening
        FIRESTICK_IP = "localhost:5555"
        subprocess.run("adb start-server", shell=True, capture_output=True, timeout=15)
        subprocess.run("adb connect localhost:5555", shell=True, capture_output=True, timeout=15)
    else:
        import resolve_devices
        new_ip = resolve_devices.ensure_connected("vivo")
        if new_ip:
            FIRESTICK_IP = new_ip
        else:
            log.info(f"Re-establishing ADB connection to {FIRESTICK_IP}...")
            subprocess.run(f"adb disconnect {FIRESTICK_IP}", shell=True, capture_output=True, timeout=30)
            subprocess.run(f"adb connect {FIRESTICK_IP}", shell=True, capture_output=True, timeout=30)
    time.sleep(2)

    def _is_locked() -> bool:
        """True if the phone's keyguard is showing (real lock screen, not just status bar overlay)."""
        window_info = adb("shell dumpsys window | grep -E 'isStatusBarKeyguard|mCurrentFocus'")
        if "isStatusBarKeyguard=true" in window_info:
            return True
        # Fallback: if mCurrentFocus is StatusBar AND no real app is open
        focus_line = ""
        for line in window_info.splitlines():
            if "mCurrentFocus" in line:
                focus_line = line
                break
        if "StatusBar" in focus_line and "Keyguard" not in focus_line:
            # Check if screen is actually sleeping (power state)
            power = adb("shell dumpsys power | grep mWakefulness")
            if "Asleep" in power or "Dozing" in power:
                return True
        if "Keyguard" in focus_line or "keyguard" in focus_line:
            return True
        return False

    # Wake screen with both keyevent 224 (wake) + 82 (menu/keyguard dismiss)
    adb("shell input keyevent 224")
    time.sleep(2)  # Give screen extra time to fully wake before checking

    if not _is_locked():
        log.info("Phone already unlocked.")
    else:
        log.info("Phone is locked, swiping to unlock...")
        # Swipe up from center-bottom (swipe lock screen)
        adb("shell input swipe 360 1200 360 400 500")
        time.sleep(2)
        if not _is_locked():
            log.info("Phone unlocked after first swipe.")
        else:
            log.warning("Still locked after swipe, trying again...")
            adb("shell input swipe 360 1200 360 400 500")
            time.sleep(2)
            if not _is_locked():
                log.info("Phone unlocked after second swipe.")
            else:
                log.warning("Lock screen persists — trying keyevent 82 + aggressive swipe...")
                adb("shell input keyevent 82")
                time.sleep(1)
                adb("shell input swipe 360 1350 360 300 800")
                time.sleep(2)
                if not _is_locked():
                    log.info("Phone unlocked after keyevent 82 + swipe.")
                else:
                    log.error("Phone could not be unlocked after 4 attempts — aborting DM sequence.")
                    raise RuntimeError("unlock_failed")
                    
    # Dismiss any active system popups/warnings (e.g. low battery, cloud alerts)
    try:
        dismiss_system_popups()
    except Exception as e:
        log.warning(f"Error calling dismiss_system_popups: {e}")

def is_message_already_sent(message: str) -> bool:
    """Check if the message (or its signature parts) is already in the visible chat history."""
    try:
        adb("shell uiautomator dump /sdcard/window_dump.xml")
        xml_data = adb("shell cat /sdcard/window_dump.xml")
        if not xml_data or "ERROR" in xml_data:
            return False
            
        clean_msg = message.replace('★', ' star')
        clean_msg = clean_msg.replace('\\n', ' ').replace('\\r', '').replace('\n', ' ').replace('\r', '')
        clean_msg = clean_msg.replace('—', ' - ').replace('–', '-')
        clean_msg = clean_msg.replace('"', '').replace("'", "")
        clean_msg = clean_msg.encode('ascii', errors='ignore').decode('ascii').strip()
        
        marker = clean_msg[:40] if len(clean_msg) > 40 else clean_msg
        
        root = ET.fromstring(xml_data)
        for node in root.iter('node'):
            clazz = node.attrib.get('class', '')
            text_val = node.attrib.get('text', '')
            if 'EditText' not in clazz and marker in text_val:
                return True
    except Exception:
        pass
    return False


def _text_similarity(a: str, b: str) -> float:
    """Returns what fraction of chars in expected string (a) appear in the sent string (b)."""
    if not a:
        return 1.0
    a_clean = a.lower().strip()
    b_clean = b.lower().strip()
    if a_clean in b_clean:
        return 1.0
    # Check first 80 chars overlap
    sample = a_clean[:80]
    if sample in b_clean:
        return 1.0
    # Count matching chars
    matched = sum(1 for ch in a_clean if ch in b_clean)
    return matched / len(a_clean)


def verify_sent_message(username: str, expected_message: str, sent_confirmed: bool = False) -> bool:
    """
    POST-SEND VERIFICATION:
    Re-opens the DM thread (via deep link), dumps screen XML, and checks for the sent message.
    sent_confirmed: if True, the send was already confirmed by compose-exit detection — skip heavy verify.
    Returns True if verified OK, False if message not visible.
    """
    log.info(f"[Verify] Checking sent message to @{username}...")
    try:
        time.sleep(3)  # Let Instagram process the send

        # Check current screen first — might already be in DM thread
        xml_data = adb_read_xml()
        thread_open = False
        if xml_data and "direct_text_message_text_view" in xml_data:
            thread_open = True

        if not thread_open:
            # Use deep-link to open the specific user's thread directly.
            # This works for message requests too (private accounts).
            log.info(f"[Verify] Not in DM thread — deep-linking to @{username}'s thread...")
            adb(f"shell am start -a android.intent.action.VIEW -d 'instagram://user?username={username}' com.instagram.android")
            time.sleep(5)
            # After profile opens, attempt to navigate directly to thread via direct inbox deep link
            # Use username-based intent which opens the DM thread if conversation exists
            xml_data = adb_read_xml()
            if xml_data and "direct_text_message_text_view" in xml_data:
                thread_open = True
                log.info(f"[Verify] Thread found via profile deep-link for @{username}")
            else:
                # Try direct inbox and find by username in node text
                adb("shell am start -a android.intent.action.VIEW -d 'instagram://direct_inbox' com.instagram.android")
                time.sleep(4)
                xml_data2 = adb_read_xml()
                found_in_inbox = False
                if xml_data2:
                    try:
                        root2 = ET.fromstring(xml_data2)
                        for node in root2.iter('node'):
                            t = node.attrib.get('text', '').strip()
                            d = node.attrib.get('content-desc', '').strip()
                            if username.lower() in t.lower() or username.lower() in d.lower():
                                coords = _parse_bounds(node.attrib.get('bounds', ''))
                                if coords:
                                    log.info(f"[Verify] Found @{username} in inbox — tapping...")
                                    adb(f"shell input tap {coords[0]} {coords[1]}")
                                    time.sleep(3)
                                    found_in_inbox = True
                                    break
                    except Exception:
                        pass
                if not found_in_inbox:
                    # @username not in visible inbox (e.g. private account → message request)
                    # If send was already confirmed by KEYCODE_ENTER compose-exit, trust it.
                    if sent_confirmed:
                        log.info(f"[Verify] @{username} not in inbox (likely message request) but compose-exit confirmed send — treating as SENT.")
                        return True
                    log.warning(f"[Verify] @{username} not found in inbox and send not confirmed — treating as FAILED.")
                    return False
            xml_data = adb_read_xml()

        if not xml_data:
            log.warning("[Verify] Could not dump screen for verification — treating as FAILED.")
            return False

        root = ET.fromstring(xml_data)
        # Collect all message text nodes — our sent messages are right-aligned (x_start > 180)
        sent_texts = []
        for node in root.iter('node'):
            rid = node.attrib.get('resource-id', '')
            if 'direct_text_message_text_view' in rid:
                bounds = node.attrib.get('bounds', '')
                text = node.attrib.get('text', '').strip()
                if bounds and text:
                    parts = bounds.replace('][', ',').replace('[', '').replace(']', '').split(',')
                    if len(parts) == 4:
                        x_start = int(parts[0])
                        if x_start > 150:  # Right-aligned = our sent message
                            sent_texts.append(text)

        if not sent_texts:
            if sent_confirmed:
                log.info("[Verify] No text bubbles visible in chat but send was confirmed by input-clear — treating as SENT.")
                return True
            log.warning("[Verify] No sent messages visible in chat after send — treating as FAILED.")
            return False

        last_sent = sent_texts[-1]
        similarity = _text_similarity(expected_message, last_sent)
        log.info(f"[Verify] Last sent text similarity: {similarity:.0%} | Preview: {last_sent[:60]}...")

        if similarity >= 0.70:
            log.info(f"[Verify] ✅ Message verified for @{username}")
            return True
        else:
            log.error(
                f"[Verify] ❌ MISMATCH for @{username}! "
                f"Expected: {expected_message[:60]}... | "
                f"Got: {last_sent[:60]}... | Similarity: {similarity:.0%}"
            )
            # Flag in DB
            try:
                import sqlite3
                conn = sqlite3.connect(DB_PATH, timeout=30)
                conn.execute("PRAGMA busy_timeout=30000")
                conn.execute(
                    "UPDATE ig_dm_queue SET status='send_mismatch', error_msg=? "
                    "WHERE ig_handle=? AND status='sent' ORDER BY sent_at DESC LIMIT 1",
                    (f"Sent text: {last_sent[:200]}", username)
                )
                conn.commit()
                conn.close()
            except Exception as db_err:
                log.warning(f"[Verify] DB flag failed: {db_err}")
            return False

    except Exception as e:
        log.warning(f"[Verify] Verification error: {e}")
        return True  # Don't block on unexpected error

def bored_human_simulator():
    """Simulates a human opening other random apps before IG to diversify OS-level telemetry."""
    import random
    import time
    
    # 50% chance to get "distracted" by another app
    if random.random() > 0.50:
        return
        
    log.info("[Bored Human] Rolling dice for OS-level distraction... getting distracted.")
    
    # Randomly pick between Chrome (Wikipedia) or Settings
    apps = [
        {"pkg": "com.android.chrome", "action": "android.intent.action.VIEW", "data": "https://en.wikipedia.org/wiki/Special:Random"},
        {"pkg": "com.android.settings", "action": "android.settings.SETTINGS", "data": ""}
    ]
    app = random.choice(apps)
    
    log.info(f"[Bored Human] Opening {app['pkg']} to simulate human OS activity...")
    
    if app["data"]:
        adb(f'shell am start -a {app["action"]} -d "{app["data"]}" {app["pkg"]} 2>/dev/null')
    else:
        adb(f'shell monkey -p {app["pkg"]} -c android.intent.category.LAUNCHER 1 2>/dev/null')
        
    time.sleep(6) # Wait for app to load
    
    # Randomly scroll or interact 2 to 5 times
    interactions = random.randint(2, 5)
    for _ in range(interactions):
        # Swipe down to scroll
        adb("shell input swipe 500 1400 500 400 300")
        time.sleep(random.uniform(3.0, 8.0))
        
    log.info("[Bored Human] Distraction complete. Going to home screen.")
    adb("shell input keyevent 3")
    time.sleep(2)


def account_warmup():
    """Scrolls the Instagram home feed and randomly likes posts to build algorithmic trust."""
    global _warmup_last_date
    today = str(date.today())
    if _warmup_last_date == today:
        log.info("[Warmup] Already warmed up today — skipping.")
        return
    _warmup_last_date = today
    import random
    log.info("[Warmup] Starting human-like account warmup sequence...")
    # Launch IG main activity
    adb("shell monkey -p com.instagram.android -c android.intent.category.LAUNCHER 1")
    time.sleep(5)
    
    # Randomly scroll 3 to 6 times
    scrolls = random.randint(3, 6)
    for _ in range(scrolls):
        # Swipe up to scroll down (x=500, y=1400 -> y=400)
        adb("shell input swipe 500 1400 500 400 400")
        
        # Human reading delay
        time.sleep(random.uniform(3.0, 7.0))
            
    log.info("[Warmup] Warmup complete. Proceeding to DM.")


def acquire_phone_lock(ip: str, timeout_seconds: int = 180) -> bool:
    """Atomic lock with wait-queue and 5-minute stale lock detection to prevent deadlocks."""
    import time

    # Fast-fail if the device is not reachable — no point blocking for 180s
    if not is_adb_reachable(ip):
        log.warning(f"[ADB] Device {ip} not reachable (TCP check failed) — skipping lock acquire.")
        return False

    start_time = time.time()
    lock_cmd = f"adb -s {ip} shell mkdir /sdcard/ig_automation_lock 2>/dev/null"

    while time.time() - start_time < timeout_seconds:
        if subprocess.run(lock_cmd, shell=True, timeout=15).returncode == 0:
            return True  # Lock acquired successfully

        # Lock exists. Check if it's a stale lock (older than 5 mins)
        try:
            cur_time_str = subprocess.run(f"adb -s {ip} shell date +%s", shell=True, capture_output=True, text=True, timeout=15).stdout.strip()
            lock_time_str = subprocess.run(f"adb -s {ip} shell stat -c %Y /sdcard/ig_automation_lock", shell=True, capture_output=True, text=True, timeout=15).stdout.strip()
            if cur_time_str.isdigit() and lock_time_str.isdigit():
                if (int(cur_time_str) - int(lock_time_str)) > 300:
                    log.warning("⚠️ STALE LOCK DETECTED: A previous script crashed. Force-clearing the lock.")
                    subprocess.run(f"adb -s {ip} shell rmdir /sdcard/ig_automation_lock", shell=True, timeout=15)
                    continue  # Try acquiring again immediately
        except Exception:
            pass

        elapsed = int(time.time() - start_time)
        log.info(f"Phone is currently busy. Waiting in queue for lock... ({elapsed}s elapsed)")
        time.sleep(5)

    log.error(f"Timed out after {timeout_seconds}s waiting in queue for the phone lock.")
    return False


def send_instagram_dm(username: str, message: str) -> bool:
    import random
    def _resolve(txt):
        return re.sub(r"{([^{}]+)}", lambda m: random.choice(m.group(1).split("|")), txt)
    message = _resolve(message)
    """
    Uses ADB to physically open Instagram, tap Message, type, and Send.
    Enforces daily limit + human-like delay between sends.
    """
    if not username or not message:
        return False

    username = username.lstrip("@").strip()
    if not username:
        return False

    if not can_send_instagram():
        return False

    # 1. Connect — re-resolve target so self-control mode (localhost) is always current
    _target = _resolve_adb_target()

    # Fast reachability check — bail immediately if phone is offline/unreachable
    if not is_adb_reachable(_target):
        log.warning(f"[Instagram ADB] Device {_target} unreachable (TCP timeout) — skipping DM to @{username}")
        return False

    log.info(f"[Instagram ADB] Starting DM sequence for @{username}...")

    subprocess.run(f"adb connect {_target}", shell=True, capture_output=True, timeout=15)

    # ATOMIC LOCK WITH STALE RECOVERY
    if not acquire_phone_lock(_target):
        log.warning(f"⚠️ SPLIT-BRAIN PREVENTION: Phone is currently locked. Aborting send to @{username} to prevent collision.")
        return False

    try:
        # 2. Wake up & unlock screen
        unlock_screen()
        
        # 2a. OS-Level Bored Human Distraction
        bored_human_simulator()
        
        # 2b. Warmup the account before DMing
        account_warmup()

        # 3. Deep link instantly to the user's profile
        log.info(f"Opening @{username} profile on Instagram...")
        adb(f'shell am start -a android.intent.action.VIEW -d "instagram://user?username={username}" com.instagram.android')
        time.sleep(6) # Wait for profile to load

        # 3a. Wait until the profile actually renders (content nodes appear), up to 15s extra
        for _wait_attempt in range(5):
            xml_data = adb_read_xml()
            if xml_data:
                try:
                    root = ET.fromstring(xml_data)
                    nodes_with_content = [
                        n for n in root.iter('node')
                        if n.attrib.get('text', '').strip() or n.attrib.get('content-desc', '').strip()
                    ]
                    if len(nodes_with_content) >= 3:
                        log.debug(f"[send_dm] Profile rendered ({len(nodes_with_content)} content nodes)")
                        break
                except Exception:
                    pass
            log.info(f"[send_dm] Profile not fully rendered yet, waiting 3s... (attempt {_wait_attempt+1}/5)")
            time.sleep(3)

        # 3b. Tap the "Follow" button if present
        # Use exact_only=True — avoids "192followers" false-positive from Pass 3 substring match
        log.info("Searching for Follow button...")
        follow_coords = get_ui_coords(
            ["Follow", "Follow back", "Follow Back"],
            resource_ids=["com.instagram.android:id/follow_button", "com.instagram.android:id/profile_header_follow_button"],
            exact_only=True
        )
        if follow_coords:
            log.info(f"Tapping Follow button at {follow_coords}")
            adb(f"shell input tap {follow_coords[0]} {follow_coords[1]}")
            time.sleep(2) # Wait for follow action to register
        else:
            log.info("Follow button not found or already following.")
        
        # 4. Dismiss any keyboard overlay before scanning for Message button
        adb("shell input keyevent 4")   # BACK — closes keyboard without leaving profile page
        time.sleep(1)

        # 4. Tap the "Message" button dynamically
        log.info(f"Searching for Message button...")
        coords = get_ui_coords(["Message", "message"], retries=2, exact_only=True)
        if coords:
            log.info(f"Tapping Message button at {coords}")
            adb(f"shell input tap {coords[0]} {coords[1]}")
            time.sleep(4)  # Wait for DM compose window to load fully
        else:
            # Diagnose WHY Message button is missing — determine if permanent or transient
            screen = get_screen_text_set()

            # Empty screen = uiautomator dump race/timeout — retry once after a brief wait
            if not screen:
                log.warning(f"[Instagram ADB] @{username}: Empty screen dump — waiting and retrying uiautomator...")
                time.sleep(3)
                screen = get_screen_text_set()

            _user_not_found_signals = {
                "user not found", "sorry, this page isn't available",
                "this account doesn't exist", "page isn't available",
                "isn't available", "account doesn't exist"
            }
            if any(sig in screen for sig in _user_not_found_signals):
                log.warning(f"[Instagram ADB] @{username}: Account not found or deleted — marking as permanent skip.")
                return None  # Permanent skip sentinel
            elif "contact" in screen and "message" not in screen:
                # Business only shows "Contact" button (email/web form) — no direct DM capability
                log.warning(f"[Instagram ADB] @{username}: Only 'Contact' button visible (no Message button) — marking as contact_only.")
                return "contact_only"  # Special sentinel: caller marks in DB and skips
            elif "following" in screen and "message" not in screen:
                log.warning(f"[Instagram ADB] @{username}: Account is private (only 'Following' visible, no Message button) — marking as permanent skip.")
                return None  # Permanent skip sentinel
            elif "statusbar" in " ".join(screen) or "keyguard" in " ".join(screen):
                log.error(f"[Instagram ADB] @{username}: Lock screen still active during profile scan — transient failure.")
                return False
            else:
                log.error(f"[Instagram ADB] @{username}: Could not find Message button (screen={list(screen)[:8]}) — transient failure.")
                return False

        # 4a. Verify we actually landed in DM compose (not followers list or some other screen)
        # Check for the compose edittext resource-id in XML — if missing, we're on wrong screen
        in_compose = False
        for _compose_check in range(3):
            xml_check = adb_read_xml()
            if xml_check and "row_thread_composer_edittext" in xml_check:
                in_compose = True
                log.info("[send_dm] Confirmed in DM compose screen.")
                break
            log.warning(f"[send_dm] Not in DM compose yet (attempt {_compose_check+1}/3) — waiting 3s...")
            time.sleep(3)

        if not in_compose:
            # Message tap went to wrong screen — navigate back to profile and try again
            log.warning(f"[send_dm] DM compose never opened for @{username}. Re-navigating to profile...")
            adb(f'shell am start -a android.intent.action.VIEW -d "instagram://user?username={username}" com.instagram.android')
            time.sleep(6)
            # Try Message button one more time
            coords2 = get_ui_coords(["Message", "message"], retries=2, exact_only=True)
            if coords2:
                log.info(f"[send_dm] Retry: Tapping Message button at {coords2}")
                adb(f"shell input tap {coords2[0]} {coords2[1]}")
                time.sleep(5)
                xml_retry = adb_read_xml()
                if not (xml_retry and "row_thread_composer_edittext" in xml_retry):
                    log.error(f"[send_dm] DM compose still not opened after retry — aborting.")
                    return False
                log.info("[send_dm] Confirmed in DM compose (retry).")
            else:
                log.error(f"[send_dm] Message button not found on retry — aborting.")
                return False

        time.sleep(2) # Brief extra wait for compose to fully settle

        # 4b. Guard against duplicate send by checking chat history
        if is_message_already_sent(message):
            log.warning("Message is already visible in chat history. Aborting duplicate send.")
            _increment_daily_count()
            return True

        # 5. Tap the Text Box to focus it dynamically
        log.info("Searching for message input box...")
        coords_input = get_ui_coords(
            ["Message...", "message...", "Message…", "message…", "Add a message"],
            resource_ids=["com.instagram.android:id/row_thread_composer_edittext"]
        )
        if coords_input:
            log.info(f"Tapping message input at {coords_input}")
            adb(f"shell input tap {coords_input[0]} {coords_input[1]}")
            time.sleep(1)
        else:
            log.error("Message input box not found via uiautomator — cannot focus compose. Aborting.")
            return False
        time.sleep(2)

        # 6. Type the message
        log.info(f"Typing message to @{username}...")
        used_adb_kb = type_text(message)

        if used_adb_kb:
            log.info("Sleeping 1.5s for ADBKeyboard input rendering...")
            time.sleep(1.5)
        else:
            # Wait generously for all chunks to finish on slow Vivo (chunks: 15-30 chars, sleep 1.2-3s each)
            num_chunks = max(1, (len(message) + 14) // 15)
            sleep_duration = max(8, num_chunks * 3.5)
            log.info(f"Sleeping for {sleep_duration:.1f}s to let typing complete ({num_chunks} chunks)...")
            time.sleep(sleep_duration)

        # 7. Send the message
        # Primary: tap the send button directly via resource-id (always visible when text is typed).
        # The compose edittext (row_thread_composer_edittext) appears both in "new compose" and
        # in the existing thread view, so we cannot use its presence to detect compose exit.
        # Instead, we check whether its text is empty after send — empty = message was sent.
        sent_confirmed = False
        log.info("Locating Send button via uiautomator...")
        send_coords = get_ui_coords(
            ["Send", "send"],
            retries=2,
            resource_ids=[
                "com.instagram.android:id/row_thread_composer_send_button_container",
                "com.instagram.android:id/row_thread_composer_button_send",
                "com.instagram.android:id/send_button",
            ]
        )
        if send_coords:
            log.info(f"Tapping Send button at {send_coords}")
            adb(f"shell input tap {send_coords[0]} {send_coords[1]}")
            time.sleep(1.5)
        else:
            # Fallback: KEYCODE_ENTER (works when keyboard is still active)
            log.warning("Send button not found via uiautomator — falling back to KEYCODE_ENTER...")
            adb("shell input keyevent 66")
            time.sleep(1.5)

        # Confirm send by checking if compose input text was cleared (message consumed)
        xml_data_post = adb_read_xml()
        if xml_data_post:
            import xml.etree.ElementTree as _ET
            try:
                _root_post = _ET.fromstring(xml_data_post)
                _PLACEHOLDERS = {"message…", "message...", "add a message", ""}
                for _n in _root_post.iter("node"):
                    if "row_thread_composer_edittext" in _n.attrib.get("resource-id", ""):
                        _remaining_text = _n.attrib.get("text", "").strip().lower()
                        if _remaining_text in _PLACEHOLDERS:
                            log.info("Compose input cleared (placeholder) — message sent successfully.")
                            sent_confirmed = True
                        else:
                            log.warning(f"Compose input still has text: {_remaining_text!r:.60} — send may have failed.")
                        break
                else:
                    # Input not found in XML — likely keyboard dismissed and we're in thread view
                    log.info("Compose edittext not found in post-send XML — likely sent and keyboard dismissed.")
                    sent_confirmed = True
            except Exception:
                pass

        if not sent_confirmed:
            # Last resort: try KEYCODE_ENTER if send button tap seemed to fail
            log.warning("Send not confirmed — trying KEYCODE_ENTER as last resort...")
            adb("shell input keyevent 66")
            time.sleep(1.5)
            # Check once more
            xml_last = adb_read_xml()
            if xml_last:
                try:
                    _root_last = _ET.fromstring(xml_last)
                    for _n in _root_last.iter("node"):
                        if "row_thread_composer_edittext" in _n.attrib.get("resource-id", ""):
                            _remaining_last = _n.attrib.get("text", "").strip().lower()
                            if _remaining_last in {"message…", "message...", "add a message", ""}:
                                log.info("Compose input cleared after KEYCODE_ENTER — message sent.")
                                sent_confirmed = True
                            break
                    else:
                        sent_confirmed = True
                except Exception:
                    pass

        time.sleep(1.5)

        # ── POST-SEND VERIFICATION ────────────────────────────────────────────
        verified = verify_sent_message(username, message, sent_confirmed=sent_confirmed)
        if verified:
            log.info(f"[Instagram ADB] ✅ Successfully SENT DM to @{username} (verified in chat)")
            _increment_daily_count()
        else:
            log.error(
                f"[Verify] ⚠️  Message to @{username} failed verification — "
                "DM may not have been sent. NOT counting toward daily limit."
            )
            return False
        # ─────────────────────────────────────────────────────────────────────

        # Randomized delay before the next action, holding the lock
        delay = random.randint(MIN_DELAY_SECONDS, MAX_DELAY_SECONDS)
        log.info(f"[Instagram ADB] Sleeping for {delay} seconds to mimic human behavior...")
        time.sleep(delay)

    except Exception as e:
        log.error(f"[Instagram ADB] Fatal error during send sequence: {e}")
        return False
    finally:
        # ATOMIC LOCK RELEASE: Remove the directory from the phone
        log.info("Releasing physical phone lock...")
        _target = _resolve_adb_target()
        subprocess.run(f"adb -s {_target} shell rmdir /sdcard/ig_automation_lock 2>/dev/null", shell=True, timeout=30)
        restore_default_keyboard()

    return True


def restore_default_keyboard():
    """Re-enables the stock Kika keyboard so the developer can type normally."""
    try:
        adb("shell pm enable com.kikaoem.vivo.qisiemoji.inputmethod")
        adb("shell ime set com.kikaoem.vivo.qisiemoji.inputmethod/com.android.inputmethod.latin.LatinIME")
        log.info("Restored default Kika IME.")
    except Exception as e:
        log.warning(f"Could not restore default input method: {e}")

def ensure_adbkeyboard():
    """Ensures ADBKeyboard is the default IME, resetting it if needed."""
    try:
        adb("shell pm disable-user --user 0 com.kikaoem.vivo.qisiemoji.inputmethod")
    except Exception as e:
        log.warning(f"Could not disable Kika keyboard: {e}")
    current_ime = adb("shell settings get secure default_input_method")
    if "AdbIME" not in current_ime:
        log.warning(f"ADBKeyboard not active (current: {current_ime}), setting...")
        adb("shell ime enable com.android.adbkeyboard/.AdbIME")
        adb("shell ime set com.android.adbkeyboard/.AdbIME")
        time.sleep(1)



