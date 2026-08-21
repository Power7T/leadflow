#!/usr/bin/env python3
import os
import sys
import time
import argparse
import sqlite3
import logging
import xml.etree.ElementTree as ET
from datetime import datetime

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger("ig_reply_responder")

# Add leadflow path
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)
from vivo_ig_ui_sender import adb, unlock_screen, get_ui_coords, type_text_safe, confirm_message_typed

DB_PATH = os.path.join(_SCRIPT_DIR, "leadflow.db")

# Resolve device IP dynamically
from pathlib import Path
DEVICE_IP = "192.168.8.157:5555" # Default fallback
try:
    _ip_file_home = Path(os.path.expanduser("~/.vivo_ip"))
    _ip_file_local = Path(__file__).parent / ".vivo_ip"
    if _ip_file_home.exists():
        DEVICE_IP = _ip_file_home.read_text().strip()
    elif _ip_file_local.exists():
        DEVICE_IP = _ip_file_local.read_text().strip()
except Exception:
    pass

def adb_run(args):
    import subprocess
    cmd = ["adb", "-s", DEVICE_IP] + args
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
    return res.stdout

def get_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn

def find_matching_business(conn, display_name):
    """Find a business by username or business name matching the inbox thread name."""
    clean_name = display_name.strip().lower()
    
    # Try exact username match first
    r = conn.execute("""
        SELECT b.id, b.name, b.demo_tunnel_url, c.instagram 
        FROM businesses b 
        JOIN contacts c ON c.business_id = b.id 
        WHERE LOWER(c.instagram) = ?
    """, (clean_name,)).fetchone()
    
    if r:
        return dict(r)
        
    # Try exact business name match
    r = conn.execute("""
        SELECT b.id, b.name, b.demo_tunnel_url, c.instagram 
        FROM businesses b 
        JOIN contacts c ON c.business_id = b.id 
        WHERE LOWER(b.name) = ?
    """, (clean_name,)).fetchone()
    
    if r:
        return dict(r)
        
    # Try substring match on business name
    r = conn.execute("""
        SELECT b.id, b.name, b.demo_tunnel_url, c.instagram 
        FROM businesses b 
        JOIN contacts c ON c.business_id = b.id 
        WHERE LOWER(b.name) LIKE ? OR ? LIKE '%' || LOWER(b.name) || '%'
        LIMIT 1
    """, (f"%{clean_name}%", clean_name)).fetchone()
    
    if r:
        return dict(r)
        
    return None

def parse_chat_messages():
    """Dump chat thread and return list of parsed message bubbles."""
    adb_run(["shell", "uiautomator dump /sdcard/chat_thread.xml"])
    xml_data = adb_run(["shell", "cat /sdcard/chat_thread.xml"])
    if not xml_data or "ERROR" in xml_data:
        return []
        
    try:
        root = ET.fromstring(xml_data)
        messages = []
        for node in root.iter('node'):
            clazz = node.attrib.get('class', '')
            text = node.attrib.get('text', '')
            bounds = node.attrib.get('bounds', '')
            
            if clazz == "android.widget.TextView" and text and bounds:
                b = bounds.replace('[', '').replace(']', ',').split(',')
                x1, y1, x2, y2 = int(b[0]), int(b[1]), int(b[2]), int(b[3])
                
                # Check message viewport limits (typically y=168 to y=1300)
                if 168 < y1 < 1300 and x1 > 10:
                    sender = "PROSPECT" if x1 < 150 else "US"
                    messages.append({
                        "text": text,
                        "sender": sender,
                        "y_coord": y1
                    })
        messages.sort(key=lambda x: x["y_coord"])
        return messages
    except Exception as e:
        log.error(f"Error parsing chat messages XML: {e}")
        return []

def respond_with_link(business, last_msg_text):
    """Sends the automated response with the mockup link and updates the DB."""
    demo_url = business.get("demo_tunnel_url") or ""
    if not demo_url:
        log.warning(f"No demo URL found for business ID {business['id']}. Skipping link delivery.")
        return False
        
    responder_message = f"Awesome! Here is the mockup design layout I put together for you: {demo_url}. Let me know what you think!"
    log.info(f"Delivering link to @{business.get('instagram') or business['name']}: {demo_url}")
    
    # Tap composer input box
    coords_input = get_ui_coords(["Message...", "message...", "Message", "Add a message"])
    if coords_input:
        adb_run(["shell", "input", "tap", str(coords_input[0]), str(coords_input[1])])
        time.sleep(1)
    else:
        log.warning("Could not find message input box coordinates.")
        return False
        
    # Clear input draft
    adb_run(["shell", "input keyevent 123 && for i in {1..350}; do input keyevent 67; done"])
    time.sleep(0.5)
    
    # Type link message
    type_text_safe(responder_message)
    time.sleep(2)
    
    # Verify typing
    if not confirm_message_typed(responder_message):
        log.error("Message was not fully typed in composer. Aborting send.")
        return False
        
    # Send
    coords_send = get_ui_coords(["Send", "send"])
    if coords_send:
        log.info(f"Tapping Send button at {coords_send}...")
        adb_run(["shell", "input", "tap", str(coords_send[0]), str(coords_send[1])])
        time.sleep(2)
        
        # Update Database — mark as replied and cancel pending follow-ups
        conn = get_db_connection()
        conn.execute("UPDATE businesses SET ig_link_delivered = 1, status = 'replied' WHERE id = ?", (business["id"],))
        conn.execute("UPDATE follow_ups SET status = 'cancelled' WHERE business_id = ? AND status = 'pending'", (business["id"],))
        # Also stamp outreach.replied and follow_ups.replied for tracking consistency
        conn.execute("UPDATE outreach SET replied=1 WHERE business_id=? AND channel='instagram'", (business["id"],))
        conn.execute("UPDATE follow_ups SET replied=1 WHERE business_id=?", (business["id"],))
        conn.commit()
        conn.close()
        log.info(f"✅ Successfully delivered mockup link, marked as replied, and cancelled pending follow-ups for ID {business['id']}!")
        return True
    else:
        log.error("Could not locate Send button in chat screen.")
        return False

def check_reply_and_respond(business):
    """Parses active chat thread. If prospect replied positively, sends the link."""
    messages = parse_chat_messages()
    if not messages:
        log.info("No message history detected on screen.")
        return False
        
    last_msg = messages[-1]
    log.info(f"Last message in thread: [{last_msg['sender']}] {repr(last_msg['text'])}")
    
    if last_msg["sender"] == "PROSPECT":
        reply_lower = last_msg["text"].lower()
        positive_keywords = ["yes", "sure", "ok", "yep", "show", "link", "send", "yeah", "cool", "send it", "please"]
        
        # Accept short replies under 12 characters (like 'yes please', 'ok sure') or matching keywords
        is_positive = any(k in reply_lower for k in positive_keywords) or len(reply_lower) < 12
        if is_positive:
            return respond_with_link(business, last_msg["text"])
        else:
            log.info("Reply was not classified as positive. No action taken.")
    else:
        log.info("Last message was sent by us. Awaiting prospect reply.")
    return False

# ─────────────────────────────────────────────────────────────────────────────
# METHOD A: Direct Queue Check
# ─────────────────────────────────────────────────────────────────────────────
def run_queue_method():
    log.info("=== Starting Method A: Direct Queue Check ===")
    conn = get_db_connection()
    # Fetch all leads where message was sent but link not delivered yet
    leads = conn.execute("""
        SELECT b.id, b.name, b.demo_tunnel_url, c.instagram 
        FROM businesses b
        JOIN contacts c ON c.business_id = b.id
        WHERE b.ig_dm_sent = 1 AND b.ig_link_delivered = 0 AND c.instagram IS NOT NULL AND c.instagram != ''
          AND b.ig_dm_sent_at > datetime('now', '-7 days')
    """).fetchall()
    conn.close()
    
    if not leads:
        log.info("No pending leads in the queue waiting for link delivery.")
        return
        
    log.info(f"Found {len(leads)} pending leads in queue to check.")
    unlock_screen()
    
    for lead in leads:
        lead_dict = dict(lead)
        username = lead_dict["instagram"]
        log.info(f"Checking chat for @{username}...")
        
        # Launch Instagram Profile deep link
        adb_run(["shell", f'am start -a android.intent.action.VIEW -d "instagram://user?username={username}" com.instagram.android'])
        time.sleep(5)
        
        # Tap Message Button
        coords = get_ui_coords(["Message"])
        if coords:
            adb_run(["shell", "input", "tap", str(coords[0]), str(coords[1])])
            time.sleep(4)
            
            # Check reply and deliver link
            check_reply_and_respond(lead_dict)
            
            # Close chat and return to home
            adb_run(["shell", "input keyevent 4"]) # Back
            time.sleep(1)
        else:
            log.warning(f"Could not open chat for @{username} (Message button not found).")
            
    # Return to phone home
    adb_run(["shell", "input keyevent 3"])

# ─────────────────────────────────────────────────────────────────────────────
# METHOD B: Inbox Scan (Scale / Passive Replies)
# ─────────────────────────────────────────────────────────────────────────────
def run_inbox_method():
    log.info("=== Starting Method B: Inbox Scan ===")
    unlock_screen()
    
    # Launch Direct Inbox directly
    log.info("Opening Instagram Direct Inbox...")
    adb_run(["shell", 'am start -a android.intent.action.VIEW -d "instagram://direct-inbox"'])
    time.sleep(5)
    
    log.info("Dumping Inbox list XML...")
    adb_run(["shell", "uiautomator dump /sdcard/inbox_list.xml"])
    xml_data = adb_run(["shell", "cat /sdcard/inbox_list.xml"])
    
    if not xml_data or "ERROR" in xml_data:
        log.error("Failed to dump inbox layout.")
        return
        
    try:
        root = ET.fromstring(xml_data)
        unread_threads = []
        
        # Find all row containers
        containers = []
        for node in root.iter('node'):
            if node.attrib.get('resource-id') == "com.instagram.android:id/row_inbox_container":
                containers.append(node)
                
        log.info(f"Found {len(containers)} total threads visible in viewport.")
        
        for c in containers:
            # Check if this thread has the unread status dot
            has_unread_dot = False
            username = None
            digest_text = ""
            c_bounds = c.attrib.get('bounds', '')
            cb = c_bounds.replace('[', '').replace(']', ',').split(',')
            cx1, cy1, cx2, cy2 = int(cb[0]), int(cb[1]), int(cb[2]), int(cb[3])
            
            # Scan child elements inside this container's vertical span
            for child in c.iter('node'):
                res_id = child.attrib.get('resource-id', '')
                text = child.attrib.get('text', '')
                
                if res_id == "com.instagram.android:id/row_inbox_username":
                    username = text
                elif res_id == "com.instagram.android:id/row_inbox_digest":
                    digest_text = text
                elif res_id == "com.instagram.android:id/thread_indicator_status_dot":
                    has_unread_dot = True
            
            # Heuristic for unread/replied thread:
            # 1. Has explicit status dot OR
            # 2. Last message text does NOT start with 'Sent', 'You', 'Liked', or 'Draft' (case-insensitive, ignoring hidden chars)
            cleaned_digest = ''.join(ch for ch in (digest_text or '') if ch.isprintable()).strip().lower()
            is_from_us = (
                cleaned_digest.startswith('sent') or
                cleaned_digest.startswith('you ') or
                cleaned_digest.startswith('liked ') or
                cleaned_digest.startswith('draft')
            )
            is_unread = has_unread_dot or (bool(cleaned_digest) and not is_from_us)
            
            if is_unread and username:
                center_y = int((cy1 + cy2) / 2)
                unread_threads.append({
                    "username": username,
                    "tap_coords": (360, center_y),
                    "digest": digest_text
                })
                
        log.info(f"Found {len(unread_threads)} UNREAD threads waiting for response.")
        
        conn = get_db_connection()
        for t in unread_threads:
            log.info(f"Processing unread thread for: {t['username']} (Preview: '{t['digest']}')")
            
            # Try to match contact in database
            biz = find_matching_business(conn, t["username"])
            if not biz:
                log.info(f"Thread '{t['username']}' could not be matched with any lead in DB. Skipping.")
                continue
                
            log.info(f"Matched thread '{t['username']}' to DB Business ID {biz['id']} ({biz['name']})")
            
            # Tap thread to open chat
            log.info(f"Tapping thread at {t['tap_coords']}...")
            adb_run(["shell", "input", "tap", str(t['tap_coords'][0]), str(t['tap_coords'][1])])
            time.sleep(4)
            
            # Check reply and deliver link
            success = check_reply_and_respond(biz)
            
            # Press Back to return to inbox list
            adb_run(["shell", "input keyevent 4"])
            time.sleep(2)
            
        conn.close()
    except Exception as e:
        log.error(f"Error executing Inbox Scan loop: {e}")
        
    # Return to phone home
    adb_run(["shell", "input keyevent 3"])

# ─────────────────────────────────────────────────────────────────────────────
# Main Executor
# ─────────────────────────────────────────────────────────────────────────────
def acquire_phone_lock(ip: str, timeout_seconds: int = 180) -> bool:
    """Atomic lock with wait-queue and 5-minute stale lock detection to prevent deadlocks."""
    import time
    start_time = time.time()
    lock_cmd = f"adb -s {ip} shell mkdir /sdcard/ig_automation_lock 2>/dev/null"
    
    while time.time() - start_time < timeout_seconds:
        if subprocess.run(lock_cmd, shell=True, timeout=30).returncode == 0:
            return True # Lock acquired successfully
            
        # Lock exists. Check if it's a stale lock (older than 5 mins)
        try:
            cur_time_str = subprocess.run(f"adb -s {ip} shell date +%s", shell=True, capture_output=True, text=True, timeout=30).stdout.strip()
            lock_time_str = subprocess.run(f"adb -s {ip} shell stat -c %Y /sdcard/ig_automation_lock", shell=True, capture_output=True, text=True, timeout=30).stdout.strip()
            if cur_time_str.isdigit() and lock_time_str.isdigit():
                if (int(cur_time_str) - int(lock_time_str)) > 300:
                    log.warning("⚠️ STALE LOCK DETECTED: A previous script crashed. Force-clearing the lock.")
                    subprocess.run(f"adb -s {ip} shell rmdir /sdcard/ig_automation_lock", shell=True, timeout=30)
                    continue # Try acquiring again immediately
        except Exception as e:
            pass
            
        elapsed = int(time.time() - start_time)
        log.info(f"Phone is currently busy. Waiting in queue for lock... ({elapsed}s elapsed)")
        time.sleep(5)
        
    log.error(f"Timed out after {timeout_seconds}s waiting in queue for the phone lock.")
    return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LeadFlow Instagram DM Reply Responder")
    parser.add_argument("--method", choices=["queue", "inbox", "both"], default="both")
    args = parser.parse_args()
    
    # ATOMIC LOCK WITH STALE RECOVERY
    import subprocess
    if not acquire_phone_lock(DEVICE_IP):
        log.warning(f"⚠️ SPLIT-BRAIN PREVENTION: Phone is currently locked by another automation script. Aborting IG Reply Responder.")
        sys.exit(0)
        
    try:
        if args.method == "inbox":
            run_inbox_method()
        elif args.method == "queue":
            run_queue_method()
        else:
            run_inbox_method()
            time.sleep(3)
            run_queue_method()
        log.info("=== IG Reply Responder run completed successfully! ===")
    finally:
        # ATOMIC LOCK RELEASE
        log.info("Releasing physical phone lock...")
        subprocess.run(f"adb -s {DEVICE_IP} shell rmdir /sdcard/ig_automation_lock 2>/dev/null", shell=True, timeout=30)
