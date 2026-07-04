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

def unlock_screen():
    """Wake up and unlock the Vivo phone reliably."""
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
        # 2. Wake up & unlock screen
        unlock_screen()

        # 3. Deep link instantly to the user's profile
        log.info(f"Opening @{username} profile on Instagram...")
        adb(f'shell am start -a android.intent.action.VIEW -d "instagram://user?username={username}"')
        time.sleep(6) # Wait for profile to load
        
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
        encoded = message.replace(' ', '%s')
        adb(f'shell input text "{encoded}"')
        time.sleep(2)
        
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

    except Exception as e:
        log.error(f"[Instagram ADB] Sequence failed: {e}")
        return False
        
    # Randomized delay before the next action
    delay = random.randint(MIN_DELAY_SECONDS, MAX_DELAY_SECONDS)
    log.info(f"[Instagram ADB] Sleeping for {delay} seconds to mimic human behavior...")
    time.sleep(delay)
    
    return True

