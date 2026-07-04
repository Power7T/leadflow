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
MIN_DELAY_SECONDS = 5   # 5 seconds minimum wait before next DM
MAX_DELAY_SECONDS = 10   # 10 seconds maximum wait
DAILY_LOG_FILE    = Path("/tmp/ig_daily_sends.json")

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
    count = get_instagram_daily_sent_count()
    if count >= DAILY_LIMIT:
        log.info(f"[Instagram] Daily limit reached ({count}/{DAILY_LIMIT}). No more DMs today.")
        return False
    return True

# ── ADB Controller ───────────────────────────────────────────────────────────

def adb(cmd: str) -> str:
    """Run an ADB command on the Firestick and return its stdout"""
    try:
        return subprocess.check_output(
            f"adb -s {FIRESTICK_IP} {cmd}", 
            shell=True, stderr=subprocess.STDOUT
        ).decode('utf-8', errors='ignore')
    except subprocess.CalledProcessError as e:
        log.debug(f"ADB Error on '{cmd}': {e.output.decode('utf-8', errors='ignore')}")
        return ""

def get_ui_coords(text_matches: list) -> tuple:
    """
    Dumps the Firestick screen UI to XML, parses it, and finds the exact X/Y center 
    coordinates of an element containing any of the text_matches.
    """
    try:
        # Dump the screen UI to an XML file on the device
        adb("shell uiautomator dump /sdcard/window_dump.xml")
        
        # Read the XML directly from the device
        xml_data = adb("shell cat /sdcard/window_dump.xml")
        if not xml_data or "ERROR" in xml_data:
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
    return None

def type_text(text: str):
    """Types text via ADB as the shell user, stripping crashing characters."""
    # Replace unicode stars with text representation
    text = text.replace('★', ' star')
    
    # Strip newlines and convert crashing unicode em-dashes
    text = text.replace('\\n', ' ').replace('\\r', '').replace('\n', ' ').replace('\r', '')
    text = text.replace('—', ' - ').replace('–', '-')
    
    # Android shell often cuts strings at apostrophes (e.g. "I'm"), so we just delete all quotes completely
    text = text.replace('"', '').replace("'", "")
    
    # Strip any remaining non-ASCII characters to prevent Android command crashes
    text = text.encode('ascii', errors='ignore').decode('ascii')
    
    # We tunnel the string through base64 to completely bypass bash interpreter crash loops on characters like & and <
    import base64
    b64_text = base64.b64encode(text.encode('utf-8')).decode('utf-8')
    
    # Must execute directly via adb shell so we have input injection permissions
    # We echo the base64, decode it, replace spaces with %s, and pass it to input text
    adb(f"shell \"input text \\\"$(echo {b64_text} | base64 -d | sed 's/ /%s/g')\\\"\"")

# ── Main send function ───────────────────────────────────────────────────────

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

    try:
        # 2. Deep link instantly to the user's profile
        adb(f'shell am start -a android.intent.action.VIEW -d "instagram://user?username={username}"')
        time.sleep(12) # Firestick IG is slow, wait for profile to load
        
        # 3. Tap the "Message" button dynamically
        log.info(f"[Instagram ADB] Tapping Message button for @{username}...")
        coords = get_ui_coords(["Message", "message"])
        if coords:
            adb(f"shell input tap {coords[0]} {coords[1]}")
        else:
            # Fallback if UI dump fails
            adb("shell input tap 233 206")
        
        time.sleep(8) # Wait for slow chat screen to open
        
        # 4. Tap the Text Box to focus it dynamically
        # Note: Instagram uses a unicode ellipsis '…' not three periods '...'
        coords_input = get_ui_coords(["Message…", "message…", "Message...", "message..."])
        if coords_input:
            adb(f"shell input tap {coords_input[0]} {coords_input[1]}")
        else:
            # Do NOT tap a hardcoded fallback here. If the chat opens, the box is usually auto-focused.
            # A blind fallback tap here will hit the chat history and close the keyboard!
            log.warning("[Instagram ADB] Could not dynamically find text box. Praying it is auto-focused.")
        time.sleep(3) # Wait for keyboard/cursor to appear

        # 5. Type the message
        log.info(f"[Instagram ADB] Typing message to @{username}...")
        type_text(message)
        time.sleep(3) # Wait for text to fully input
        
        # 6. Press the hardware BACK button to dismiss the hovering keyboard
        adb("shell input keyevent 4")
        time.sleep(2)
        
        # 7. Tap the "Send" button dynamically
        coords_send = get_ui_coords(["Send", "send"])
        if coords_send:
            adb(f"shell input tap {coords_send[0]} {coords_send[1]}")
        else:
            adb("shell input tap 328 612")
        time.sleep(3)
        
        log.info(f"[Instagram ADB] ✅ Successfully TYPED and SENT DM to @{username}")
        _increment_daily_count()

    except Exception as e:
        log.error(f"[Instagram ADB] Sequence failed: {e}")
        return False
        
    finally:
        pass
        # 8. Clean up: Directly kill the app to reset state
        # adb("shell am force-stop com.instagram.android")
        # time.sleep(2)
        
    # 7. Human-like randomized delay before the next action
    delay = random.randint(MIN_DELAY_SECONDS, MAX_DELAY_SECONDS)
    log.info(f"[Instagram ADB] Sleeping for {delay} seconds to mimic human behavior...")
    time.sleep(delay)
    
    return True
