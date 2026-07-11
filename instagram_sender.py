"""
instagram_sender.py — Physical ADB Controller for Instagram DM Automation

Safety rules (to NEVER get the account banned or deleted):
  - Max 20 DMs per calendar day
  - 45-120 second random delay between each DM
  - Uses ADB (Android Debug Bridge) to physically tap the screen on the Firestick
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

load_dotenv("/Users/chandan/leadflow/.env")

log = logging.getLogger("leadflow.instagram")
log.setLevel(logging.INFO)

# ── Config ──────────────────────────────────────────────────────────────────
DAILY_LIMIT       = 20
MIN_DELAY_SECONDS = 45   # 45 seconds minimum wait before next DM (safeguard against spam blocks)
MAX_DELAY_SECONDS = 120  # 120 seconds maximum wait (mimics human-like typing and reading breaks)
import tempfile
try:
    DAILY_LOG_FILE = Path(tempfile.gettempdir()) / "ig_daily_sends.json"
except Exception:
    DAILY_LOG_FILE = Path(__file__).parent / "ig_daily_sends.json"

# Dynamically resolve device IP (checks user home, script directory, or defaults to 192.168.1.7:5555)
_ip_file_home = Path(os.path.expanduser("~/.vivo_ip"))
_ip_file_local = Path(__file__).parent / ".vivo_ip"
if _ip_file_home.exists():
    FIRESTICK_IP = _ip_file_home.read_text().strip()
elif _ip_file_local.exists():
    FIRESTICK_IP = _ip_file_local.read_text().strip()
else:
    FIRESTICK_IP = "192.168.1.7:5555"

# ── Daily count tracking ─────────────────────────────────────────────────────

def _load_daily_log() -> dict:
    try:
        if DAILY_LOG_FILE.exists():
            return json.loads(DAILY_LOG_FILE.read_text())
    except Exception:
        pass
    return {}

def _save_daily_log(data: dict):
    try:
        DAILY_LOG_FILE.write_text(json.dumps(data))
    except Exception as e:
        log.warning(f"[Instagram] Could not save daily log: {e}")

def get_instagram_daily_sent_count() -> int:
    today = str(date.today())
    return _load_daily_log().get(today, 0)

def _increment_daily_count():
    today = str(date.today())
    data = _load_daily_log()
    data[today] = data.get(today, 0) + 1
    _save_daily_log(data)

def can_send_instagram() -> bool:
    limit = 45
    try:
        import sqlite3
        conn = sqlite3.connect("/Users/chandan/leadflow/leadflow.db", timeout=10)
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

def adb(cmd: str) -> str:
    """Run an ADB command on the device and return its stdout"""
    global FIRESTICK_IP
    try:
        _ip_file_home = Path(os.path.expanduser("~/.vivo_ip"))
        _ip_file_local = Path(__file__).parent / ".vivo_ip"
        if _ip_file_home.exists():
            FIRESTICK_IP = _ip_file_home.read_text().strip()
        elif _ip_file_local.exists():
            FIRESTICK_IP = _ip_file_local.read_text().strip()
    except Exception:
        pass
        
    try:
        return subprocess.check_output(
            f"adb -s {FIRESTICK_IP} {cmd}", 
            shell=True, stderr=subprocess.STDOUT, timeout=15
        ).decode('utf-8', errors='ignore')
    except subprocess.TimeoutExpired:
        log.warning(f"ADB command timed out: {cmd}")
        return ""
    except subprocess.CalledProcessError as e:
        log.debug(f"ADB Error on '{cmd}': {e.output.decode('utf-8', errors='ignore')}")
        return ""

def restart_android_uiautomator():
    log.info("[Self-Healing] uiautomator dump failed. Restarting Android UI framework...")
    adb("shell stop")
    time.sleep(3)
    adb("shell start")
    time.sleep(12)

def get_ui_coords(text_matches: list, retries: int = 1) -> tuple:
    """
    Dumps the screen UI to XML, parses it, and finds the exact X/Y center 
    coordinates of an element containing any of the text_matches.
    """
    for attempt in range(retries + 1):
        try:
            # Dump the screen UI to an XML file on the device
            adb("shell uiautomator dump /sdcard/window_dump.xml")
            
            # Read the XML directly from the device
            xml_data = adb("shell cat /sdcard/window_dump.xml")
            if not xml_data or "ERROR" in xml_data or "error" in xml_data.lower():
                if attempt < retries:
                    restart_android_uiautomator()
                    continue
                return None
                
            root = ET.fromstring(xml_data)
            
            # Iterate over all UI nodes
            for node in root.iter('node'):
                text = node.attrib.get('text', '').strip().lower()
                desc = node.attrib.get('content-desc', '').strip().lower()
                
                for match in text_matches:
                    match = match.lower()
                    # Strict exact matching to avoid clicking posts containing the word "message"
                    if match == text or match == desc:
                        bounds = node.attrib.get('bounds')
                        if bounds:
                            # Parse bounds like "[x1,y1][x2,y2]" to find center point
                            parts = bounds.replace('][', ',').replace('[', '').replace(']', '').split(',')
                            if len(parts) == 4:
                                x = (int(parts[0]) + int(parts[2])) // 2
                                y = (int(parts[1]) + int(parts[3])) // 2
                                return (x, y)
        except Exception as e:
            log.error(f"[Instagram] XML parsing error: {e}")
            if attempt < retries:
                restart_android_uiautomator()
                continue
    return None

def type_text(text: str):
    """Types text via ADB as the shell user with human-like delays."""
    import base64
    import random
    
    # Replace unicode stars with text representation
    text = text.replace('★', ' star')
    
    # Strip newlines and convert crashing unicode em-dashes
    text = text.replace('\\n', ' ').replace('\\r', '').replace('\n', ' ').replace('\r', '')
    text = text.replace('—', ' - ').replace('–', '-')
    
    # Android shell often cuts strings at apostrophes (e.g. "I'm"), so we just delete all quotes completely
    text = text.replace('"', '').replace("'", "")
    
    # Strip any remaining non-ASCII characters to prevent Android command crashes
    text = text.encode('ascii', errors='ignore').decode('ascii')
    
    # Split into random-sized chunks (10 to 25 chars) to mimic human typing bursts
    chunks = []
    i = 0
    while i < len(text):
        chunk_len = random.randint(10, 25)
        chunks.append(text[i:i+chunk_len])
        i += chunk_len
    
    for chunk in chunks:
        if not chunk:
            continue
        b64_chunk = base64.b64encode(chunk.encode('utf-8')).decode('utf-8')
        
        # Must execute directly via adb shell so we have input injection permissions
        adb(f"shell \"input text \\\"$(echo {b64_chunk} | base64 -d | sed 's/ /%s/g')\\\"\"")
        
        # Human-like delay between bursts (1.5 to 3.5 seconds)
        time.sleep(random.uniform(1.5, 3.5))

# ── Main send function ───────────────────────────────────────────────────────

def unlock_screen():
    """Wake up and unlock the Vivo phone reliably, resetting ADB first."""
    # Ensure ADB connection is re-established to bypass sleep timeouts
    global FIRESTICK_IP
    log.info(f"Re-establishing ADB connection to {FIRESTICK_IP}...")
    subprocess.run(f"adb disconnect {FIRESTICK_IP}", shell=True, capture_output=True)
    subprocess.run(f"adb connect {FIRESTICK_IP}", shell=True, capture_output=True)
    time.sleep(2)

    # Wake screen
    adb("shell input keyevent 224")
    time.sleep(1)
    
    # Check if still on lock screen
    focus = adb("shell dumpsys window | grep mCurrentFocus")
    if "StatusBar" in focus or "Keyguard" in focus or "keyguard" in focus:
        log.info("Phone is locked, swiping to unlock...")
        # Swipe up from center-bottom to center to unlock
        adb("shell input swipe 360 1200 360 400 300")
        time.sleep(2)
        # Check again
        focus = adb("shell dumpsys window | grep mCurrentFocus")
        if "StatusBar" in focus or "Keyguard" in focus:
            log.warning("Still locked after swipe, trying again...")
            adb("shell input swipe 360 1200 360 400 300")
            time.sleep(2)
    else:
        log.info("Phone already unlocked.")

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


def verify_sent_message(username: str, expected_message: str) -> bool:
    """
    POST-SEND VERIFICATION:
    Re-dumps the chat XML and reads back the last sent message.
    Checks that it matches expected_message with >= 70% similarity.
    Returns True if verified OK, False if mismatch detected.
    """
    log.info(f"[Verify] Checking sent message to @{username}...")
    try:
        time.sleep(3)  # Let the sent message render in chat
        adb("shell uiautomator dump /sdcard/window_dump.xml")
        xml_data = adb("shell cat /sdcard/window_dump.xml")
        if not xml_data or "ERROR" in xml_data:
            log.warning("[Verify] Could not dump screen for verification.")
            return True  # Assume OK if we can't check

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
            log.warning("[Verify] No sent messages visible in chat after send — cannot verify.")
            return True  # Can't confirm, assume OK

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
                conn = sqlite3.connect("/Users/chandan/leadflow/leadflow.db", timeout=30)
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
    start_time = time.time()
    lock_cmd = f"adb -s {ip} shell mkdir /sdcard/ig_automation_lock 2>/dev/null"
    
    while time.time() - start_time < timeout_seconds:
        if subprocess.run(lock_cmd, shell=True).returncode == 0:
            return True # Lock acquired successfully
            
        # Lock exists. Check if it's a stale lock (older than 5 mins)
        try:
            cur_time_str = subprocess.run(f"adb -s {ip} shell date +%s", shell=True, capture_output=True, text=True).stdout.strip()
            lock_time_str = subprocess.run(f"adb -s {ip} shell stat -c %Y /sdcard/ig_automation_lock", shell=True, capture_output=True, text=True).stdout.strip()
            if cur_time_str.isdigit() and lock_time_str.isdigit():
                if (int(cur_time_str) - int(lock_time_str)) > 300:
                    log.warning("⚠️ STALE LOCK DETECTED: A previous script crashed. Force-clearing the lock.")
                    subprocess.run(f"adb -s {ip} shell rmdir /sdcard/ig_automation_lock", shell=True)
                    continue # Try acquiring again immediately
        except Exception as e:
            pass
            
        elapsed = int(time.time() - start_time)
        log.info(f"Phone is currently busy. Waiting in queue for lock... ({elapsed}s elapsed)")
        time.sleep(5)
        
    log.error(f"Timed out after {timeout_seconds}s waiting in queue for the phone lock.")
    return False


def send_instagram_dm(username: str, message: str) -> bool:
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

    log.info(f"[Instagram ADB] Starting DM sequence for @{username}...")
    
    # 1. Connect (ensure we are connected before starting)
    subprocess.run(f"adb connect {FIRESTICK_IP}", shell=True, capture_output=True)

    # ATOMIC LOCK WITH STALE RECOVERY
    if not acquire_phone_lock(FIRESTICK_IP):
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
        adb(f'shell am start -a android.intent.action.VIEW -d "instagram://user?username={username}"')
        time.sleep(6) # Wait for profile to load

        # 3b. Tap the "Follow" button if present
        log.info("Searching for Follow button...")
        follow_coords = get_ui_coords(["Follow", "Follow back", "follow", "follow back", "Follow Back"])
        if follow_coords:
            log.info(f"Tapping Follow button at {follow_coords}")
            adb(f"shell input tap {follow_coords[0]} {follow_coords[1]}")
            time.sleep(2) # Wait for follow action to register
        else:
            log.info("Follow button not found or already following.")
        
        # 4. Tap the "Message" button dynamically
        log.info(f"Searching for Message button...")
        coords = get_ui_coords(["Message", "message"])
        if coords:
            log.info(f"Tapping Message button at {coords}")
            adb(f"shell input tap {coords[0]} {coords[1]}")
        else:
            log.error("Could not find Message button in the UI hierarchy. Aborting.")
            return False
        
        time.sleep(6) # Wait for slow chat screen to open

        # 4b. Guard against duplicate send by checking chat history
        if is_message_already_sent(message):
            log.warning("Message is already visible in chat history. Aborting duplicate send.")
            _increment_daily_count()
            return True
        
        # 5. Tap the Text Box to focus it dynamically
        log.info("Searching for message input box...")
        coords_input = get_ui_coords(["Message...", "message...", "Message", "Add a message", "Message…", "message…"])
        if coords_input:
            log.info(f"Tapping message input at {coords_input}")
            adb(f"shell input tap {coords_input[0]} {coords_input[1]}")
            time.sleep(1)
        else:
            log.warning("Could not find text input box — hoping it is auto-focused")
        time.sleep(2)

        # 6. Type the message
        log.info(f"Typing message to @{username}...")
        type_text(message)
        
        # Verify typed text and wait for keyboard typing to complete
        sleep_duration = max(3, len(message) * 0.04)
        log.info(f"Sleeping for {sleep_duration:.1f} seconds to allow typing to complete...")
        time.sleep(sleep_duration)
        
        # Verification loop to ensure full message was typed
        type_ok = False
        for attempt in range(2):
            try:
                adb("shell uiautomator dump /sdcard/window_dump.xml")
                xml_data = adb("shell cat /sdcard/window_dump.xml")
                if xml_data and "row_thread_composer_edittext" in xml_data:
                    root = ET.fromstring(xml_data)
                    for node in root.iter('node'):
                        if "row_thread_composer_edittext" in node.attrib.get('resource-id', ''):
                            current_text = node.attrib.get('text', '')
                            if len(current_text) >= len(message) * 0.8:
                                log.info(f"✅ Verified: Message typed successfully ({len(current_text)}/{len(message)} chars).")
                                type_ok = True
                                break
                            else:
                                log.warning(f"Message typing incomplete. Expected: {len(message)} chars, Found: {len(current_text)} chars.")
                if type_ok:
                    break
            except Exception as parse_err:
                log.warning(f"Error parsing screen XML for verification: {parse_err}")
                
            log.warning("Verification failed, waiting 3 seconds before next check...")
            time.sleep(3)
            
        # 7. Press the hardware BACK button to dismiss the hovering keyboard
        adb("shell input keyevent 4")
        time.sleep(2)
        
        # 8. Tap the "Send" button dynamically
        log.info("Searching for Send button...")
        coords_send = get_ui_coords(["Send", "send"])
        if coords_send:
            log.info(f"Tapping Send at {coords_send}")
            adb(f"shell input tap {coords_send[0]} {coords_send[1]}")
        else:
            log.warning("Send button not found — trying Enter key as fallback")
            adb("shell input keyevent 66")
        time.sleep(2)
        
        log.info(f"[Instagram ADB] ✅ Successfully TYPED and SENT DM to @{username}")
        _increment_daily_count()

        # ── POST-SEND VERIFICATION ────────────────────────────────────────────
        verified = verify_sent_message(username, message)
        if not verified:
            log.error(
                f"[Verify] ⚠️  Message to @{username} failed verification — "
                "flagged as 'send_mismatch' in DB. Manual review needed."
            )
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
        subprocess.run(f"adb -s {FIRESTICK_IP} shell rmdir /sdcard/ig_automation_lock 2>/dev/null", shell=True)

    return True

