import time
import logging
import xml.etree.ElementTree as ET
from instagram_sender import adb

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("vivo_ig")


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


def get_ui_coords(search_texts, retries=3):
    """Find UI element coordinates by text or content-desc."""
    for attempt in range(retries):
        adb("shell uiautomator dump /sdcard/window_dump.xml")
        time.sleep(0.5)
        xml_data = adb("shell cat /sdcard/window_dump.xml")
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
        except ET.ParseError as e:
            log.warning(f"XML parse error on attempt {attempt+1}: {e}")
        time.sleep(2)
    return None


def send_dm_via_vivo(username: str, message: str, dry_run: bool = False):
    log.info(f"=== Starting DM to @{username} ===")

    # 1. Wake up & unlock screen
    unlock_screen()

    # 2. Launch Instagram via deep link
    log.info(f"Opening @{username} profile on Instagram...")
    adb(f'shell am start -a android.intent.action.VIEW -d "instagram://user?username={username}"')
    time.sleep(5)  # Give Instagram enough time to fully load the profile

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

    # 4. Find message input box
    log.info("Searching for message input box...")
    coords_input = get_ui_coords(["Message...", "message...", "Message", "Add a message"])
    if coords_input:
        log.info(f"Tapping message input at {coords_input}")
        adb(f"shell input tap {coords_input[0]} {coords_input[1]}")
        time.sleep(1)
    else:
        log.warning("Could not find text input box — hoping it is auto-focused")

    # 5. Type the message
    log.info(f"Typing message: {repr(message)}")
    # Encode spaces as %s for adb input text
    encoded = message.replace(' ', '%s')
    adb(f'shell input text "{encoded}"')
    time.sleep(2)

    if dry_run:
        log.info(f"✅ [DRY RUN] Message drafted for @{username}, NOT sent.")
        return True

    # 6. Find and tap Send button
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

    # 7. Go back to home
    adb("shell input keyevent 4")
    return True


if __name__ == "__main__":
    send_dm_via_vivo("instagram", "hi", dry_run=False)
