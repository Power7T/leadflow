import time
import logging
import xml.etree.ElementTree as ET
from instagram_sender import adb

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("vivo_ig")


def unlock_screen():
    """Wake up and unlock the Vivo phone reliably, resetting ADB first."""
    # Resolve device IP dynamically
    import os
    from pathlib import Path
    device_ip = "192.168.1.4:5555" # Default fallback
    try:
        _ip_file_home = Path(os.path.expanduser("~/.vivo_ip"))
        _ip_file_local = Path(__file__).parent / ".vivo_ip"
        if _ip_file_home.exists():
            device_ip = _ip_file_home.read_text().strip()
        elif _ip_file_local.exists():
            device_ip = _ip_file_local.read_text().strip()
    except Exception:
        pass

    log.info(f"Re-establishing ADB connection to {device_ip}...")
    import subprocess
    subprocess.run(f"adb disconnect {device_ip}", shell=True, capture_output=True)
    subprocess.run(f"adb connect {device_ip}", shell=True, capture_output=True)
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


def restart_android_uiautomator():
    log.info("[Self-Healing] uiautomator dump failed. Restarting Android UI framework...")
    adb("shell stop")
    time.sleep(3)
    adb("shell start")
    time.sleep(12)

def get_ui_coords(search_texts, retries=3):
    """Find UI element coordinates by text or content-desc."""
    for attempt in range(retries):
        adb("shell uiautomator dump /sdcard/window_dump.xml")
        time.sleep(0.5)
        xml_data = adb("shell cat /sdcard/window_dump.xml")
        if not xml_data or "ERROR" in xml_data or "error" in xml_data.lower():
            restart_android_uiautomator()
            continue
        try:
            root = ET.fromstring(xml_data)
            # First pass: exact match on text or content-desc
            for node in root.iter('node'):
                text = node.attrib.get('text', '')
                content_desc = node.attrib.get('content-desc', '')
                for s in search_texts:
                    if s == text or s == content_desc:
                        bounds = node.attrib.get('bounds')
                        if bounds:
                            b = bounds.replace('[', '').replace(']', ',').split(',')
                            x = (int(b[0]) + int(b[2])) // 2
                            y = (int(b[1]) + int(b[3])) // 2
                            log.info(f"Found '{s}' at ({x},{y}) via exact match")
                            return (x, y)
            # Second pass: substring match
            for node in root.iter('node'):
                text = node.attrib.get('text', '')
                content_desc = node.attrib.get('content-desc', '')
                for s in search_texts:
                    if s.lower() in text.lower() or s.lower() in content_desc.lower():
                        bounds = node.attrib.get('bounds')
                        if bounds:
                            b = bounds.replace('[', '').replace(']', ',').split(',')
                            x = (int(b[0]) + int(b[2])) // 2
                            y = (int(b[1]) + int(b[3])) // 2
                            log.info(f"Found '{s}' at ({x},{y}) via substring match")
                            return (x, y)
            # Third pass: class EditText fallback (for input fields)
            for node in root.iter('node'):
                clazz = node.attrib.get('class', '')
                if 'EditText' in clazz:
                    bounds = node.attrib.get('bounds')
                    if bounds:
                        b = bounds.replace('[', '').replace(']', ',').split(',')
                        x = (int(b[0]) + int(b[2])) // 2
                        y = (int(b[1]) + int(b[3])) // 2
                        log.info(f"Found EditText input field at ({x},{y}) via class fallback")
                        return (x, y)
        except ET.ParseError as e:
            log.warning(f"XML parse error on attempt {attempt+1}: {e}")
            restart_android_uiautomator()
        time.sleep(2)
    return None


def type_text_safe(message: str):
    """Types the message on the device safely in chunks using subprocess without host shell escaping issues."""
    import base64
    import subprocess
    import os
    from pathlib import Path
    
    # 1. Resolve device IP dynamically
    device_ip = "192.168.1.4:5555" # Default fallback
    try:
        _ip_file_home = Path(os.path.expanduser("~/.vivo_ip"))
        _ip_file_local = Path(__file__).parent / ".vivo_ip"
        if _ip_file_home.exists():
            device_ip = _ip_file_home.read_text().strip()
        elif _ip_file_local.exists():
            device_ip = _ip_file_local.read_text().strip()
    except Exception:
        pass
        
    # 2. Format the message for keyevents
    text = message.replace('★', ' star')
    text = text.replace('\\n', ' ').replace('\\r', '').replace('\n', ' ').replace('\r', '')
    text = text.replace('—', ' - ').replace('–', '-')
    text = text.replace('"', '').replace("'", "")
    text = text.encode('ascii', errors='ignore').decode('ascii')
    
    # 3. Split into random-sized chunks (10 to 25 chars) to mimic human typing bursts
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
        
        # Execute directly via subprocess without host shell
        cmd = [
            "adb", "-s", device_ip, "shell",
            f"input text \"$(echo {b64_chunk} | base64 -d | sed 's/ /%s/g')\""
        ]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        # Human-like delay between bursts (1.5 to 3.5 seconds)
        time.sleep(random.uniform(1.5, 3.5))


def confirm_message_typed(expected_message: str, timeout: float = 15.0) -> bool:
    """Wait and verify that the expected message has been fully typed into the input field."""
    # Format same as typed message for matching
    clean_expected = expected_message.replace('★', ' star')
    clean_expected = clean_expected.replace('\\n', ' ').replace('\\r', '').replace('\n', ' ').replace('\r', '')
    clean_expected = clean_expected.replace('—', ' - ').replace('–', '-')
    clean_expected = clean_expected.replace('"', '').replace("'", "")
    clean_expected = clean_expected.encode('ascii', errors='ignore').decode('ascii')
    
    # Check if the end marker of our expected text is present in the text box
    end_marker = clean_expected[-30:] if len(clean_expected) > 30 else clean_expected
    
    start_time = time.time()
    while time.time() - start_time < timeout:
        adb("shell uiautomator dump /sdcard/window_dump.xml")
        xml_data = adb("shell cat /sdcard/window_dump.xml")
        if xml_data and "ERROR" not in xml_data:
            try:
                root = ET.fromstring(xml_data)
                for node in root.iter('node'):
                    clazz = node.attrib.get('class', '')
                    text_val = node.attrib.get('text', '')
                    is_focused = node.attrib.get('focused') == 'true'
                    
                    if 'EditText' in clazz or is_focused:
                        log.info(f"Current input box text: {repr(text_val)}")
                        if end_marker in text_val:
                            log.info("Verified: Entire message has been typed successfully!")
                            return True
            except Exception as e:
                log.warning(f"Error parsing UI XML: {e}")
        time.sleep(1.5)
    
    return False


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

def send_dm_via_vivo(username: str, message: str, dry_run: bool = False):
    log.info(f"=== Starting DM to @{username} ===")

    # 1. Wake up & unlock screen
    unlock_screen()

    # 2. Launch Instagram via deep link
    log.info(f"Opening @{username} profile on Instagram...")
    adb(f'shell am start -a android.intent.action.VIEW -d "instagram://user?username={username}"')
    time.sleep(5)  # Give Instagram enough time to fully load the profile

    # 2b. Tap the "Follow" button if present
    log.info("Searching for Follow button...")
    follow_coords = get_ui_coords(["Follow", "Follow back", "Follow Back"])
    if follow_coords:
        log.info(f"Tapping Follow button at {follow_coords}")
        adb(f"shell input tap {follow_coords[0]} {follow_coords[1]}")
        time.sleep(2) # Wait for follow action to register
    else:
        log.info("Follow button not found or already following.")

    # 3. Find & Click the Message button
    log.info("Searching for Message button...")
    coords = get_ui_coords(["Message"])
    if coords:
        log.info(f"Tapping Message button at {coords}")
        adb(f"shell input tap {coords[0]} {coords[1]}")
    else:
        log.error("Could not find Message button in the UI hierarchy. Aborting.")
        return False

    time.sleep(5)  # Wait for the DM chat screen to load

    # Guard against duplicate send by checking chat history
    if is_message_already_sent(message):
        log.warning("Message is already visible in chat history. Aborting duplicate send.")
        # Go back to home to exit chat screen safely
        adb("shell input keyevent 4")
        return True

    # 4. Find message input box
    log.info("Searching for message input box...")
    coords_input = get_ui_coords(["Message...", "message...", "Message", "Add a message"])
    if coords_input:
        log.info(f"Tapping message input at {coords_input}")
        adb(f"shell input tap {coords_input[0]} {coords_input[1]}")
        time.sleep(1)
    else:
        log.warning("Could not find text input box — hoping it is auto-focused")

    # 5. Type the message using host-shell-safe method
    log.info("Clearing any existing text draft in the input box...")
    adb("shell \"input keyevent 123 && for i in {1..350}; do input keyevent 67; done\"")
    time.sleep(0.5)

    log.info(f"Typing message: {repr(message)}")
    type_text_safe(message)
    
    # 6. Verify that the message is fully typed before sending
    log.info("Verifying that the entire message has been typed...")
    if not confirm_message_typed(message):
        log.error("CRITICAL: Message was NOT fully typed in the input box! Aborting send to prevent half-assed DM.")
        # Go back to home to exit chat screen safely
        adb("shell input keyevent 4")
        return False

    if dry_run:
        log.info(f"✅ [DRY RUN] Message drafted for @{username}, NOT sent.")
        return True

    # 7. Find and tap Send button
    log.info("Searching for Send button...")
    coords_send = get_ui_coords(["Send", "send"])
    if coords_send:
        log.info(f"Tapping Send at {coords_send}")
        adb(f"shell input tap {coords_send[0]} {coords_send[1]}")
    else:
        log.warning("Send button not found — trying Enter key as fallback")
        adb("shell input keyevent 66")

    time.sleep(2)
    log.info(f"✅ DM sent to @{username}!")

    # 8. Go back to home
    adb("shell input keyevent 4")
    return True


if __name__ == "__main__":
    send_dm_via_vivo("instagram", "hi", dry_run=False)
