import time
import random
import logging
import xml.etree.ElementTree as ET
from instagram_sender import adb, _resolve_adb_target, ensure_adbkeyboard

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("vivo_ig")


def unlock_screen():
    """Wake up and unlock the Vivo phone reliably."""
    import subprocess
    device_ip = _resolve_adb_target()

    if device_ip == "localhost:5555":
        # Self-hosting on Vivo — start local ADB daemon
        subprocess.run("adb start-server", shell=True, capture_output=True, timeout=15)
        subprocess.run("adb connect localhost:5555", shell=True, capture_output=True, timeout=15)
    else:
        import resolve_devices
        resolved = resolve_devices.ensure_connected("vivo")
        if resolved:
            device_ip = resolved
        else:
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
                    if s.lower() == "following" and (any(c.isdigit() for c in text) or any(c.isdigit() for c in content_desc)):
                        continue
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
                    if s.lower() == "following" and (any(c.isdigit() for c in text) or any(c.isdigit() for c in content_desc)):
                        continue
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
    """Types the message on the device safely using ADBKeyboard (AdbIME).
    Falls back to normal typing if ADBKeyboard IME is not active."""
    import base64
    import subprocess
    import random

    device_ip = _resolve_adb_target()

    # Ensure ADBKeyboard is active
    try:
        ensure_adbkeyboard()
    except Exception as e:
        log.warning(f'Could not ensure ADBKeyboard: {e}')

    # 1. Normalize linebreaks for safety in messaging apps
    text = message.replace('\\n', ' ').replace('\\r', '').replace('\n', ' ').replace('\r', '')
    text = text.replace('—', ' - ').replace('–', '-')

    # 2. Check if AdbIME is active
    try:
        res = subprocess.run(
            ["adb", "-s", device_ip, "shell", "settings get secure default_input_method"],
            capture_output=True, text=True, timeout=5
        )
        ime = res.stdout.strip()
        use_adbkeyboard = "AdbIME" in ime or "ADBKeyboard" in ime
    except Exception:
        use_adbkeyboard = False

    if use_adbkeyboard:
        log.info("Typing via ADBKeyboard broadcast (instant & safe)...")
        # ADBKeyboard expects base64 payload to ensure unicode safety
        b64_text = base64.b64encode(text.encode('utf-8')).decode('utf-8')
        cmd = [
            "adb", "-s", device_ip, "shell",
            f"am broadcast -a ADB_INPUT_B64 --es msg {b64_text}"
        ]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(1.0)
        return

    log.warning("ADBKeyboard IME not active. Falling back to chunked keyboard simulation.")
    # Fallback to character stripping to prevent adb shell command crashes
    text_clean = text.replace('★', ' star').replace('"', '').replace('\'', '')
    text_clean = text_clean.encode('ascii', errors='ignore').decode('ascii')

    # Split into random-sized chunks (10 to 25 chars) to mimic human typing
    chunks = []
    i = 0
    while i < len(text_clean):
        chunk_len = random.randint(10, 25)
        chunks.append(text_clean[i:i+chunk_len])
        i += chunk_len

    for chunk in chunks:
        if not chunk:
            continue
        b64_chunk = base64.b64encode(chunk.encode('utf-8')).decode('utf-8')
        cmd = [
            "adb", "-s", device_ip, "shell",
            f"input text \"$(echo {b64_chunk} | base64 -d | sed 's/ /%%s/g')\""
        ]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(random.uniform(1.5, 3.5))


def normalize_for_comparison(text: str) -> str:
    if not text:
        return ""
    text = text.lower()
    text = text.replace('★', ' star')
    text = text.replace('\\n', ' ').replace('\\r', '').replace('\n', ' ').replace('\r', '')
    text = text.replace('—', ' - ').replace('–', '-')
    text = text.replace('"', '').replace('\'', '').replace('’', '').replace('`', '')
    text = text.replace(" ", "")  # Remove all spaces.
    text = text.encode('ascii', errors='ignore').decode('ascii')
    return text.strip()


def confirm_message_typed(expected_message: str, timeout: float = 15.0) -> bool:
    """Wait and verify that the expected message has been fully typed into the input field."""
    norm_expected = normalize_for_comparison(expected_message)
    # Take the end marker (normalized last 25 chars)
    end_marker = norm_expected[-25:] if len(norm_expected) > 25 else norm_expected

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
                        norm_text_val = normalize_for_comparison(text_val)
                        if end_marker in norm_text_val:
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

        norm_expected = normalize_for_comparison(message)
        # Take the start marker (normalized first 35 chars)
        marker = norm_expected[:35] if len(norm_expected) > 35 else norm_expected

        root = ET.fromstring(xml_data)
        for node in root.iter('node'):
            clazz = node.attrib.get('class', '')
            text_val = node.attrib.get('text', '')
            if 'EditText' not in clazz:
                norm_text_val = normalize_for_comparison(text_val)
                if marker in norm_text_val:
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
