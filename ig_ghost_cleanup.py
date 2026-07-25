"""
ig_ghost_cleanup.py — Ghost Unfollow with Corrected Follower Verification

CORRECTED APPROACH:
  ❌ Old method: check for "Follows you" badge — BROKEN when we already follow them
     (Instagram hides the badge once WE follow them)
  ✅ New method: Open their followers list → search for "chandan.sol" → check if
     our username appears in results

Two unfollow categories:
  1. GHOSTS (7+ days): We followed + DMed them, they never followed us back
  2. SILENT FOLLOWBACKS (14+ days): They followed us back but never replied to our DM

Flow per target:
  1. Open profile via deep link
  2. Check for action block → skip if blocked
  3. Tap followers count to open followers list
  4. Search for our username ("chandan.sol") in search box
  5. Check if our username appears in results:
     - YES → they follow us → mark ig_follows_us_back=1
     - NO  → ghost → unfollow
  6. For silent followbacks (follow us but no reply after 14d) → unfollow

Usage:
  python3 ig_ghost_cleanup.py             # Run cleanup (respects rate limiter)
  python3 ig_ghost_cleanup.py --dry-run   # Check who would be unfollowed
  python3 ig_ghost_cleanup.py --stats     # Show ghost statistics
"""

import os
import sys
import time
import random
import sqlite3
import logging
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv("/Users/chandan/leadflow/.env")

from ig_rate_db import (
    migrate, get_pending_ghosts, get_silent_followbacks,
    mark_followback, mark_unfollowed, log_action, DB_PATH,
)
from ig_rate_limiter import (
    RateLimiter, check_and_handle_block, dismiss_block_popup,
)
from instagram_sender import adb, acquire_phone_lock, FIRESTICK_IP
from vivo_ig_ui_sender import (
    unlock_screen, get_ui_coords, restart_android_uiautomator,
)
from ig_phone_status import (
    start_session as ps_start, end_session as ps_end,
    update_activity as ps_activity,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("ig_ghost_cleanup")

OUR_USERNAME = os.getenv("INSTAGRAM_USERNAME", "chandan.sol")

# Max unfollows per run (spread throughout the day)
MAX_UNFOLLOWS_PER_RUN = 3
# Max follower checks per run (reading followers list is suspicious in bulk)
MAX_CHECKS_PER_RUN = 5


# ── Core: check if someone follows us ──────────────────────────────────────

def check_follows_us(username: str) -> bool | None:
    """Open a user's followers list and search for our username.

    Returns:
        True  — our username found in their followers (they follow us)
        False — our username NOT found (ghost)
        None  — couldn't determine (UI error, blocked, etc.)
    """
    log.info(f"Checking if @{username} follows us (@{OUR_USERNAME})...")
    ps_activity("check_follower", "Checking followback", target_username=username)

    # ── Open their profile ──────────────────────────────────────────
    adb(f'shell am start -a android.intent.action.VIEW -d "instagram://user?username={username}"')
    time.sleep(random.uniform(4.5, 6.5))

    # Check for action block
    xml_data = _dump_screen()
    if _has_block(xml_data):
        dismiss_block_popup(adb)
        return None

    # ── Find and tap their followers count ──────────────────────────
    # Instagram shows: "[N] followers" as a tappable element
    # We need to find the element with "followers" text and tap it
    log.info("Looking for followers count to tap...")

    followers_coords = _find_followers_button(xml_data)
    if not followers_coords:
        log.warning(f"Could not find followers count for @{username}")
        adb("shell input keyevent 4")
        return None

    log.info(f"Tapping followers at {followers_coords}")
    adb(f"shell input tap {followers_coords[0]} {followers_coords[1]}")
    time.sleep(random.uniform(3.0, 5.0))

    # ── Search for our username in their followers list ──────────────
    # The followers list has a search bar at the top
    xml_data = _dump_screen()
    if _has_block(xml_data):
        dismiss_block_popup(adb)
        adb("shell input keyevent 4")
        return None

    # Find the search box
    search_coords = _find_search_box(xml_data)
    if not search_coords:
        log.warning("Could not find search box in followers list")
        adb("shell input keyevent 4")
        time.sleep(1)
        adb("shell input keyevent 4")
        return None

    # Tap search box and type our username
    log.info(f"Tapping search box at {search_coords}, typing '{OUR_USERNAME}'...")
    adb(f"shell input tap {search_coords[0]} {search_coords[1]}")
    time.sleep(1)

    # Clear any existing text
    adb('shell "input keyevent 123 && for i in {1..50}; do input keyevent 67; done"')
    time.sleep(0.3)

    # Type our username
    adb(f'shell input text "{OUR_USERNAME}"')
    time.sleep(random.uniform(2.0, 3.5))  # Wait for search results to load

    # ── Check if our username appears in search results ─────────────
    xml_data = _dump_screen()
    found = _check_username_in_results(xml_data, OUR_USERNAME)

    # Clean up: go back twice (out of followers list, then out of profile)
    adb("shell input keyevent 4")
    time.sleep(1)
    adb("shell input keyevent 4")
    time.sleep(1)

    if found:
        log.info(f"✅ @{username} DOES follow us back")
        return True
    else:
        log.info(f"❌ @{username} does NOT follow us")
        return False


def _dump_screen() -> str:
    """Dump current screen to XML and return it."""
    adb("shell uiautomator dump /sdcard/window_dump.xml")
    time.sleep(0.5)
    return adb("shell cat /sdcard/window_dump.xml")


def _has_block(xml_data: str) -> bool:
    """Quick check for action block patterns in XML."""
    if not xml_data or "ERROR" in xml_data:
        return False
    from ig_rate_limiter import check_for_action_block
    return check_for_action_block(xml_data)


def _find_followers_button(xml_data: str) -> tuple | None:
    """Find the tappable followers count on a profile page.

    Instagram UI shows something like:
      "123 followers" or "followers" with a count nearby,
      or the content-desc contains "followers"
    """
    if not xml_data or "ERROR" in xml_data:
        return None

    try:
        root = ET.fromstring(xml_data)

        # Pass 1: Look for content-desc or text containing "follower"
        # (Instagram shows "N followers" as content-desc on the tappable area)
        for node in root.iter('node'):
            text = node.attrib.get('text', '').lower()
            desc = node.attrib.get('content-desc', '').lower()

            # Match "followers" but NOT "following"
            if ('follower' in desc and 'following' not in desc) or \
               ('follower' in text and 'following' not in text):
                bounds = node.attrib.get('bounds', '')
                if bounds:
                    b = bounds.replace('[', '').replace(']', ',').split(',')
                    x = (int(b[0]) + int(b[2])) // 2
                    y = (int(b[1]) + int(b[3])) // 2
                    log.info(f"Found followers element: text='{text}' desc='{desc}' at ({x},{y})")
                    return (x, y)

        # Pass 2: Look for text that's just "followers" (sometimes a separate label)
        for node in root.iter('node'):
            text = node.attrib.get('text', '').strip().lower()
            if text == 'followers':
                bounds = node.attrib.get('bounds', '')
                if bounds:
                    b = bounds.replace('[', '').replace(']', ',').split(',')
                    x = (int(b[0]) + int(b[2])) // 2
                    y = (int(b[1]) + int(b[3])) // 2
                    log.info(f"Found 'followers' label at ({x},{y})")
                    return (x, y)

    except ET.ParseError as e:
        log.warning(f"XML parse error finding followers: {e}")

    return None


def _find_search_box(xml_data: str) -> tuple | None:
    """Find the search box in the followers list."""
    if not xml_data or "ERROR" in xml_data:
        return None

    try:
        root = ET.fromstring(xml_data)

        # Look for search input: usually EditText or has "Search" text/hint
        for node in root.iter('node'):
            text = node.attrib.get('text', '').lower()
            desc = node.attrib.get('content-desc', '').lower()
            clazz = node.attrib.get('class', '')

            if 'search' in text or 'search' in desc or \
               ('EditText' in clazz and node.attrib.get('focusable') == 'true'):
                bounds = node.attrib.get('bounds', '')
                if bounds:
                    b = bounds.replace('[', '').replace(']', ',').split(',')
                    x = (int(b[0]) + int(b[2])) // 2
                    y = (int(b[1]) + int(b[3])) // 2
                    log.info(f"Found search box at ({x},{y}) class={clazz}")
                    return (x, y)

    except ET.ParseError as e:
        log.warning(f"XML parse error finding search box: {e}")

    return None


def _check_username_in_results(xml_data: str, username: str) -> bool:
    """Check if our username appears in the followers search results."""
    if not xml_data or "ERROR" in xml_data:
        return False

    try:
        root = ET.fromstring(xml_data)
        username_lower = username.lower()

        for node in root.iter('node'):
            text = node.attrib.get('text', '').strip().lower()
            desc = node.attrib.get('content-desc', '').strip().lower()

            # Exact match on username (Instagram shows exact handles)
            if text == username_lower or username_lower in desc:
                log.info(f"Found '{username}' in search results! text='{text}' desc='{desc}'")
                return True

        # Also check for "No results found" type indicators
        for node in root.iter('node'):
            text = node.attrib.get('text', '').strip().lower()
            if 'no results' in text or 'no users' in text:
                log.info(f"Search returned 'no results' — @{username} is not in their followers")
                return False

    except ET.ParseError as e:
        log.warning(f"XML parse error checking results: {e}")

    # If we didn't find our username and no "no results" message,
    # default to not found (conservative — don't skip unfollow)
    return False


# ── Unfollow action ─────────────────────────────────────────────────────────

def unfollow_user(username: str, business_id: int, reason: str,
                  dry_run: bool = False) -> bool:
    """Unfollow a user on Instagram.

    Returns True on success.
    """
    log.info(f"{'[DRY RUN] ' if dry_run else ''}Unfollowing @{username} (reason: {reason})")

    # Open their profile
    adb(f'shell am start -a android.intent.action.VIEW -d "instagram://user?username={username}"')
    time.sleep(random.uniform(4.5, 6.5))

    # Check for block
    xml_data = _dump_screen()
    if _has_block(xml_data):
        dismiss_block_popup(adb)
        return False

    # Find "Following" button
    following_coords = get_ui_coords(["Following"])
    if not following_coords:
        log.info(f"No 'Following' button for @{username}. Already unfollowed or never followed.")
        # Mark as unfollowed anyway so we don't keep checking
        if not dry_run:
            mark_unfollowed(business_id, username, reason=f"{reason}_already_gone")
        return True

    if dry_run:
        log.info(f"[DRY RUN] Would tap Following at {following_coords}")
        return True

    # Tap "Following" → opens bottom sheet with "Unfollow" option
    adb(f"shell input tap {following_coords[0]} {following_coords[1]}")
    time.sleep(random.uniform(2.0, 3.5))

    # Tap "Unfollow" in the bottom sheet
    unfollow_coords = get_ui_coords(["Unfollow"])
    if unfollow_coords:
        adb(f"shell input tap {unfollow_coords[0]} {unfollow_coords[1]}")
        time.sleep(2)
        log.info(f"✅ Unfollowed @{username}")
        mark_unfollowed(business_id, username, reason=reason)
        return True
    else:
        log.warning(f"Could not find 'Unfollow' button in bottom sheet for @{username}")
        # Press back to dismiss bottom sheet
        adb("shell input keyevent 4")
        return False


# ── Session runner ──────────────────────────────────────────────────────────

def run_ghost_cleanup(dry_run: bool = False):
    """Run the ghost cleanup routine.

    Steps:
    1. Check pending ghosts (7+ days, no followback verified)
    2. For each: check if they follow us by searching their followers list
    3. If ghost (doesn't follow us): unfollow
    4. If they follow us but never replied (14+ days): also unfollow
    """
    migrate()
    limiter = RateLimiter()

    log.info("=" * 60)
    log.info("  Ghost Cleanup Session")
    log.info(f"  Rate state: {limiter.current_state}")
    log.info(f"  Dry run: {dry_run}")
    log.info("=" * 60)

    # Don't run ghost cleanup when frozen (respect the rate limiter for unfollows too)
    if limiter.current_state == "FROZEN":
        log.info("Rate limiter is FROZEN. Skipping ghost cleanup.")
        return

    # ── Phase 1: Check pending ghosts (7+ days) ────────────────────────
    ghosts = get_pending_ghosts(min_days=7)
    # Filter to only those we haven't checked recently (or never checked)
    unchecked = [g for g in ghosts if g.get("ig_follows_us_back") is None]

    log.info(f"Total ghosts (7+ days): {len(ghosts)}")
    log.info(f"Unchecked (need follower verification): {len(unchecked)}")

    # Randomize and cap
    random.shuffle(unchecked)
    to_check = unchecked[:MAX_CHECKS_PER_RUN]

    # ── Phase 2: Check silent followbacks (14+ days) ───────────────────
    silent = get_silent_followbacks(min_days=14)
    log.info(f"Silent followbacks (14+ days, no reply): {len(silent)}")

    # Start phone status session
    session_id = ps_start("ig_ghost_cleanup") if not dry_run else None

    # Acquire phone lock
    if not dry_run:
        if not acquire_phone_lock(FIRESTICK_IP):
            log.error("Could not acquire phone lock. Aborting.")
            return
        try:
            unlock_screen()
        except Exception as e:
            log.error(f"Failed to unlock: {e}")
            subprocess.run(
                f"adb -s {FIRESTICK_IP} shell rmdir /sdcard/ig_automation_lock 2>/dev/null",
                shell=True
            )
            return

    unfollowed = 0
    checked = 0

    try:
        # ── Verify followback status for unchecked ghosts ───────────────
        for g in to_check:
            username = g["instagram"].lstrip("@").strip()
            if not username:
                continue

            if dry_run:
                log.info(f"[DRY RUN] Would check if @{username} follows us")
                checked += 1
                continue

            follows_us = check_follows_us(username)
            checked += 1

            if follows_us is None:
                log.warning(f"Could not determine followback for @{username} — skipping")
                continue
            elif follows_us:
                mark_followback(g["id"], True)
                log.info(f"@{username} follows us back! Keeping.")
            else:
                mark_followback(g["id"], False)
                log.info(f"@{username} is a GHOST. Unfollowing...")

                if unfollowed < MAX_UNFOLLOWS_PER_RUN:
                    ps_activity("unfollow", "Ghost unfollow (7d, no followback)", target_username=username)
                    success = unfollow_user(username, g["id"], "ghost_7d", dry_run)
                    if success:
                        unfollowed += 1

            # Delay between checks (30-60s to look human)
            delay = random.randint(30, 60)
            log.info(f"Waiting {delay}s before next check...")
            time.sleep(delay)

            if unfollowed >= MAX_UNFOLLOWS_PER_RUN:
                log.info(f"Hit max unfollows per run ({MAX_UNFOLLOWS_PER_RUN}). Stopping.")
                break

        # ── Unfollow silent followbacks (14+ days, followed back but no reply) ──
        if unfollowed < MAX_UNFOLLOWS_PER_RUN and silent:
            random.shuffle(silent)
            for s in silent:
                if unfollowed >= MAX_UNFOLLOWS_PER_RUN:
                    break

                username = s["instagram"].lstrip("@").strip()
                if not username:
                    continue

                log.info(f"Silent followback: @{username} (followed back, no reply in 14+ days)")
                ps_activity("unfollow", "Silent followback unfollow (14d, no reply)", target_username=username)
                success = unfollow_user(username, s["id"], "silent_14d", dry_run)
                if success:
                    unfollowed += 1

                delay = random.randint(30, 60)
                log.info(f"Waiting {delay}s...")
                time.sleep(delay)

    except KeyboardInterrupt:
        log.info("Cleanup interrupted by user.")
    except Exception as e:
        log.error(f"Fatal error during ghost cleanup: {e}", exc_info=True)
    finally:
        if not dry_run:
            subprocess.run(
                f"adb -s {FIRESTICK_IP} shell rmdir /sdcard/ig_automation_lock 2>/dev/null",
                shell=True
            )
            adb("shell input keyevent 3")
            # End phone status session
            if session_id:
                summary = f"Checked: {checked}, Unfollowed: {unfollowed}"
                ps_end(session_id, summary)

    log.info("=" * 60)
    log.info(f"  Ghost Cleanup Complete")
    log.info(f"  Checked: {checked} | Unfollowed: {unfollowed}")
    log.info("=" * 60)


def show_stats():
    """Show ghost statistics."""
    migrate()

    ghosts = get_pending_ghosts(min_days=7)
    silent = get_silent_followbacks(min_days=14)

    # Breakdown
    unchecked = [g for g in ghosts if g.get("ig_follows_us_back") is None]
    confirmed_ghosts = [g for g in ghosts if g.get("ig_follows_us_back") == 0]
    confirmed_followers = [g for g in ghosts if g.get("ig_follows_us_back") == 1]

    print("\n" + "=" * 60)
    print("  Ghost Cleanup Statistics")
    print("=" * 60)
    print(f"  Total pending (7+ days, not unfollowed): {len(ghosts)}")
    print(f"  ├─ Unchecked (never verified):           {len(unchecked)}")
    print(f"  ├─ Confirmed ghosts (no followback):     {len(confirmed_ghosts)}")
    print(f"  └─ Confirmed followers (followed back):  {len(confirmed_followers)}")
    print()
    print(f"  Silent followbacks (14d, no reply):      {len(silent)}")
    print()
    if ghosts:
        oldest = min(g["followed_at"] for g in ghosts if g.get("followed_at"))
        print(f"  Oldest unresolved follow:                {oldest}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    if "--stats" in sys.argv:
        show_stats()
    elif "--dry-run" in sys.argv:
        run_ghost_cleanup(dry_run=True)
    else:
        run_ghost_cleanup(dry_run=False)
