import sqlite3
import os
import time
import random
import logging
from datetime import datetime, timedelta
import subprocess

from instagram_sender import FIRESTICK_IP, acquire_phone_lock, unlock_screen, get_ui_coords, adb

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger("unfollow_ghosts")

DB_PATH = "/Users/chandan/leadflow/leadflow.db"

def run_unfollow_routine():
    log.info("Starting Auto-Unfollow Ghosts Routine...")
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    # Find businesses sent a DM > 7 days ago, not replied, not already unfollowed
    query = """
        SELECT b.id, c.instagram, b.ig_dm_sent_at 
        FROM businesses b
        JOIN contacts c ON c.business_id = b.id
        WHERE b.ig_dm_sent = 1 
          AND b.ig_unfollowed = 0 
          AND b.replied_at IS NULL
          AND b.ig_dm_sent_at < datetime('now', '-7 days')
          AND c.instagram IS NOT NULL
    """
    ghosts = conn.execute(query).fetchall()
    
    if not ghosts:
        log.info("No ghosts found to unfollow today (all 7+ day old DMs have either replied or been unfollowed already).")
        conn.close()
        return

    # Randomize the list
    ghosts = list(ghosts)
    random.shuffle(ghosts)
    
    # Cap to just 1 or 2 unfollows per run to spread them randomly throughout the entire day
    ghosts_to_process = ghosts[:random.randint(1, 2)]
    log.info(f"Found {len(ghosts)} total ghosts. Selecting {len(ghosts_to_process)} random ghosts to unfollow this session.")
    
    # Acquire lock
    if not acquire_phone_lock(FIRESTICK_IP):
        log.warning("Phone is locked. Aborting unfollow routine (will try again next time).")
        conn.close()
        return

    try:
        unlock_screen()
        
        for g in ghosts_to_process:
            username = g['instagram'].lstrip('@').strip()
            if not username:
                continue
                
            log.info(f"Processing ghost: @{username} (Sent DM at {g['ig_dm_sent_at']})")
            
            # Deep link to profile
            adb(f'shell am start -a android.intent.action.VIEW -d "instagram://user?username={username}"')
            time.sleep(6) # Wait for profile to render

            # Never unfollow someone who follows us back
            if get_ui_coords(["Follows you"]):
                log.info(f"@{username} follows you back — skipping unfollow permanently.")
                continue

            # Find the "Following" button
            coords = get_ui_coords(["Following"])
            if coords:
                log.info(f"Found 'Following' button at {coords}. Tapping to open menu...")
                adb(f"shell input tap {coords[0]} {coords[1]}")
                time.sleep(3) # Wait for bottom sheet menu
                
                # The bottom menu has an "Unfollow" option
                unfollow_coords = get_ui_coords(["Unfollow"])
                if unfollow_coords:
                    adb(f"shell input tap {unfollow_coords[0]} {unfollow_coords[1]}")
                    log.info(f"✅ Successfully unfollowed @{username}.")
                    
                    # Mark in DB
                    conn.execute("UPDATE businesses SET ig_unfollowed = 1 WHERE id = ?", (g['id'],))
                    conn.commit()
                else:
                    log.warning(f"Could not find 'Unfollow' confirmation button for @{username}.")
            else:
                log.info(f"Could not find 'Following' button for @{username}. We may already not follow them.")
                # Mark as unfollowed anyway so we don't keep checking this account
                conn.execute("UPDATE businesses SET ig_unfollowed = 1 WHERE id = ?", (g['id'],))
                conn.commit()
                
            # Random organic delay between unfollows (25 to 60 seconds)
            delay = random.randint(25, 60)
            log.info(f"Waiting {delay}s organically before the next unfollow...")
            time.sleep(delay)
            
    except Exception as e:
        log.error(f"Fatal error during unfollow sequence: {e}")
    finally:
        log.info("Releasing physical phone lock...")
        subprocess.run(f"adb -s {FIRESTICK_IP} shell rmdir /sdcard/ig_automation_lock 2>/dev/null", shell=True)
        conn.close()
        # Return to Android home screen
        adb("shell input keyevent 3")

if __name__ == "__main__":
    run_unfollow_routine()
