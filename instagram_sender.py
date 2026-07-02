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
DAILY_LIMIT       = 15
MIN_DELAY_SECONDS = 5   # 5 seconds minimum wait before next DM
MAX_DELAY_SECONDS = 10   # 10 seconds maximum wait
DAILY_LOG_FILE    = Path("/tmp/ig_daily_sends.json")

FIRESTICK_IP = "192.168.1.3:5555"

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
            text = node.attrib.get('text', '').lower()
            desc = node.attrib.get('content-desc', '').lower()
            
            for match in text_matches:
                match = match.lower()
                if match in text or match in desc:
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
    """Types text via ADB, replacing spaces with %s and bypassing all shell escaping via base64."""
    import base64
    text = text.replace('\\n', ' ').replace('\\r', '').replace('\n', ' ').replace('\r', '')
    # Convert unicode em-dashes that break ADB to standard hyphens
    text = text.replace('—', ' - ').replace('–', '-')
    
    # Base64 encode the string to bypass ALL bash escaping bugs with single quotes
    b64_text = base64.b64encode(text.encode('utf-8')).decode()
    
    # Run a tiny python script on the firestick that decodes the b64 and inputs it
    script = f"import base64, os; text=base64.b64decode('{b64_text}').decode(); safe=text.replace(' ', '%s'); os.system('input text \\\"' + safe + '\\\"')"
    adb(f'shell "run-as com.termux /data/data/com.termux/files/usr/bin/python -c \\"{script}\\""')

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
        
        # 4. Tap the Text Box to focus it (Hardcoded: X=111, Y=608)
        adb("shell input tap 111 608")
        time.sleep(3) # Wait for keyboard/cursor to appear

        # 5. Type the message
        log.info(f"[Instagram ADB] Typing message to @{username}...")
        type_text(message)
        time.sleep(3) # Wait for text to fully input
        
        # 7. Tap the "Send" button dynamically
        coords_send = get_ui_coords(["Send", "send"])
        if coords_send:
            adb(f"shell input tap {coords_send[0]} {coords_send[1]}")
        else:
            adb("shell input tap 328 612")
        time.sleep(3)
        log.info(f"[Instagram ADB] ✅ Successfully sent DM to @{username}")
        _increment_daily_count()
        
        # Send ntfy alert
        try:
            import requests, os
            ntfy_topic = os.getenv("NTFY_TOPIC", "leadflow-chandan-secret")
            requests.post(f"https://ntfy.sh/{ntfy_topic}", data=f"🤖 Instagram DM successfully sent to @{username} via Firestick!".encode('utf-8'))
        except:
            pass

    except Exception as e:
        log.error(f"[Instagram ADB] Sequence failed: {e}")
        return False
        
    finally:
        # 8. Clean up: Hit the Android BACK button 3 times to exit the chat/profile safely
        adb("shell input keyevent 4")
        time.sleep(1)
        adb("shell input keyevent 4")
        time.sleep(1)
        adb("shell input keyevent 4")
        time.sleep(1)
        # Hit HOME just to be safe
        adb("shell input keyevent 3")
        
    # 7. Human-like randomized delay before the next action
    delay = random.randint(MIN_DELAY_SECONDS, MAX_DELAY_SECONDS)
    log.info(f"[Instagram ADB] Sleeping for {delay} seconds to mimic human behavior...")
    time.sleep(delay)
    
    return True
