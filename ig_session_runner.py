"""
ig_session_runner.py — Follow+DM Paired Session Runner

Flow per target:
  1. Open profile via instagram://user?username=X
  2. Check for action block popup → dismiss + abort if found
  3. Check if "Message" button exists → skip if not (can't DM this account)
  4. Tap "Follow" button (if present, meaning we don't already follow them)
  5. Wait 3-5s (let follow register)
  6. Tap "Message" button
  7. Wait for chat to load
  8. Type and send the DM
  9. Verify message was sent
  10. Mark in DB: ig_dm_sent=1, ig_followed_at=now

Session wrapper:
  - Loads candidates from DB (businesses with IG handles, not yet DMed)
  - Checks rate limiter budget before each pair
  - After each pair: random delay from rate limiter (state-dependent)
  - On block: stops session immediately, records block in rate limiter
  - On completion: logs summary

Usage:
  python3 ig_session_runner.py               # Run a session (respects rate limiter)
  python3 ig_session_runner.py --dry-run     # Don't actually send anything
  python3 ig_session_runner.py --status      # Show current rate state + candidates
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

load_dotenv(str(Path(__file__).parent / ".env"))

# Import our modules
from ig_rate_db import (
    migrate, get_dm_candidates, mark_followed, log_action,
    get_todays_pair_count, DB_PATH,
)
from ig_rate_limiter import (
    RateLimiter, check_and_handle_block, check_for_action_block,
    dismiss_block_popup, get_screen_xml,
)

# Import existing ADB infrastructure
from instagram_sender import adb, acquire_phone_lock, FIRESTICK_IP
from vivo_ig_ui_sender import (
    unlock_screen, get_ui_coords, type_text_safe,
    restart_android_uiautomator, confirm_message_typed,
    is_message_already_sent,
)
from ig_phone_status import (
    start_session as ps_start, end_session as ps_end,
    update_activity as ps_activity,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("ig_session")

OUR_USERNAME = os.getenv("INSTAGRAM_USERNAME", "chandan.sol")


# ── DM message templates ────────────────────────────────────────────────────

def build_dm_message(business: dict) -> str:
    """Build a personalized DM message for the business.

    Uses the existing ig_dm_variant from the DB if set, otherwise
    generates a simple outreach message.
    """
    name = business.get("name", "there")
    city = business.get("city", "")
    category = business.get("category", "")

    # Check if there's a pre-generated variant in the DB
    variant = business.get("ig_dm_variant")
    if variant and variant.strip():
        return variant.strip()

    # Default template — simple, friendly, non-spammy
    templates = [
        f"Hey {name}! I came across your page and love what you're doing{' in ' + city if city else ''}. I help businesses like yours get more customers through a better online presence. Would you be open to a quick chat?",
        f"Hi {name}! Your {category or 'business'} caught my eye{' in ' + city if city else ''}. I specialize in helping local businesses stand out online — happy to share a few ideas if you're interested!",
        f"Hey {name}! Just wanted to reach out — I noticed your business{' in ' + city if city else ''} and think there's some quick wins to get you more visibility online. Mind if I share a few thoughts?",
    ]
    return random.choice(templates)


# ── Core flow: Follow + DM one target ───────────────────────────────────────

def follow_and_dm(username: str, message: str, business_id: int,
                  limiter: RateLimiter, dry_run: bool = False) -> str:
    """Execute the paired Follow+DM flow for one target.

    Returns:
        'success'           — follow+DM completed
        'skip_no_msg_btn'   — no Message button (can't DM them)
        'skip_already_dmd'  — message already in chat (duplicate)
        'blocked'           — action block detected
        'error'             — unexpected failure
    """
    log.info(f"{'[DRY RUN] ' if dry_run else ''}=== Follow+DM → @{username} ===")

    # ── Step 1: Open profile via deep link ──────────────────────────────
    ps_activity("open_profile", f"Opening profile", target_username=username)
    adb(f'shell am start -a android.intent.action.VIEW -d "instagram://user?username={username}" com.instagram.android')
    time.sleep(random.uniform(4.5, 6.5))  # Human-like wait for profile load

    # ── Step 2: Check for action block popup ────────────────────────────
    if check_and_handle_block(adb, limiter):
        ps_activity("block_detected", "Action block on profile open", target_username=username)
        log_action(username, "skip_blocked", business_id, "Action block on profile open")
        return "blocked"

    # ── Step 3: Check if "Message" button exists ────────────────────────
    # This is the CRITICAL pre-check: some accounts can't be DMed until
    # they follow/message us first. If no Message button → skip.
    log.info("Checking for Message button (pre-follow check)...")
    msg_coords = get_ui_coords(["Message"])
    if not msg_coords:
        log.info(f"@{username} has no Message button — skipping (can't DM until they follow us)")
        ps_activity("skip", "No Message button", target_username=username)
        log_action(username, "skip_no_msg_btn", business_id, "No Message button on profile")
        # Go back
        adb("shell input keyevent 4")
        time.sleep(1)
        return "skip_no_msg_btn"

    # ── Step 4: Tap Follow button (if we don't already follow them) ─────
    log.info("Looking for Follow button...")
    follow_coords = get_ui_coords(["Follow", "Follow back", "Follow Back"])
    if follow_coords:
        if dry_run:
            log.info(f"[DRY RUN] Would tap Follow at {follow_coords}")
        else:
            log.info(f"Tapping Follow button at {follow_coords}")
            adb(f"shell input tap {follow_coords[0]} {follow_coords[1]}")
            time.sleep(random.uniform(2.5, 4.0))

            # Check if follow triggered a block
            if check_and_handle_block(adb, limiter):
                log_action(username, "skip_blocked", business_id, "Action block on follow")
                return "blocked"

        # Record the follow
        mark_followed(business_id, username)
        ps_activity("follow", "Followed", target_username=username)
        log.info(f"✅ Followed @{username}")
    else:
        # Already following — that's fine, still send DM
        log.info(f"Already following @{username} (or Follow button not found)")

    # ── Step 5: Tap Message button ──────────────────────────────────────
    # Re-find it (screen may have changed after follow)
    time.sleep(1)
    msg_coords = get_ui_coords(["Message"])
    if not msg_coords:
        log.warning(f"Message button disappeared after follow for @{username}")
        log_action(username, "error", business_id, "Message button gone after follow")
        adb("shell input keyevent 4")
        return "error"

    if dry_run:
        log.info(f"[DRY RUN] Would tap Message at {msg_coords}")
    else:
        log.info(f"Tapping Message button at {msg_coords}")
        adb(f"shell input tap {msg_coords[0]} {msg_coords[1]}")

    time.sleep(random.uniform(4.0, 6.0))  # Wait for chat screen to load

    # Check for block on DM screen
    if not dry_run and check_and_handle_block(adb, limiter):
        log_action(username, "skip_blocked", business_id, "Action block on DM screen")
        return "blocked"

    # ── Step 6: Check for duplicate messages ────────────────────────────
    if is_message_already_sent(message):
        log.warning(f"Message already visible in chat with @{username}. Skipping duplicate.")
        log_action(username, "skip_already_dmd", business_id, "Duplicate message in chat")
        adb("shell input keyevent 4")
        return "skip_already_dmd"

    # ── Step 7: Find input box and type message ─────────────────────────
    log.info("Searching for message input box...")
    input_coords = get_ui_coords(["Message...", "message...", "Message", "Add a message"])
    if input_coords:
        if not dry_run:
            adb(f"shell input tap {input_coords[0]} {input_coords[1]}")
            time.sleep(1)
    else:
        log.warning("Input box not found — hoping it's auto-focused")

    # Clear any existing draft
    if not dry_run:
        adb('shell "input keyevent 123 && for i in {1..350}; do input keyevent 67; done"')
        time.sleep(0.5)

    # Type the message
    log.info(f"Typing message ({len(message)} chars)...")
    if dry_run:
        log.info(f"[DRY RUN] Would type: {message[:80]}...")
    else:
        ps_activity("typing", f"Typing DM ({len(message)} chars)", target_username=username, notify_phone=False)
        type_text_safe(message)

        # Verify message was fully typed
        if not confirm_message_typed(message):
            log.error(f"Message NOT fully typed for @{username}! Aborting send.")
            log_action(username, "error", business_id, "Message typing incomplete")
            adb("shell input keyevent 4")
            return "error"

    # ── Step 8: Send the message ────────────────────────────────────────
    if dry_run:
        log.info(f"[DRY RUN] Would tap Send for @{username}")
    else:
        send_coords = get_ui_coords(["Send", "send"])
        if send_coords:
            log.info(f"Tapping Send at {send_coords}")
            adb(f"shell input tap {send_coords[0]} {send_coords[1]}")
        else:
            log.warning("Send button not found — pressing Enter as fallback")
            adb("shell input keyevent 66")

        time.sleep(2)

        # Check for post-send block — verify if message typed/sent before marking as sent
        if check_and_handle_block(adb, limiter):
            ps_activity("block_detected", "Action block after send attempt", target_username=username)
            if confirm_message_typed(message, timeout=5.0):
                log.info(f"Message confirmed sent before action block popup for @{username}")
                _mark_dm_sent(business_id)
                log_action(username, "dm_blocked_after", business_id, "Action block after confirmed send")
            else:
                log.warning(f"Action block triggered before send completed for @{username} — NOT marking as sent")
                log_action(username, "skip_blocked", business_id, "Action block before send confirmed")
            return "blocked"

    # ── Step 9: Mark success in DB ──────────────────────────────────────
    if not dry_run:
        _mark_dm_sent(business_id)
    log_action(username, "dm", business_id, f"DM sent: {message[:50]}...")
    ps_activity("dm", "DM sent", target_username=username)

    log.info(f"✅ Follow+DM completed for @{username}")

    # Go back to home
    adb("shell input keyevent 4")
    time.sleep(1)

    return "success"


def _mark_dm_sent(business_id: int):
    """Mark business as DMed in the main businesses table."""
    conn = sqlite3.connect(DB_PATH, timeout=15)
    try:
        conn.execute(
            "UPDATE businesses SET ig_dm_sent=1, ig_dm_sent_at=datetime('now') WHERE id=?",
            (business_id,)
        )
        conn.commit()
    finally:
        conn.close()


# ── Session runner ──────────────────────────────────────────────────────────

def run_session(dry_run: bool = False):
    """Run a full Follow+DM session respecting rate limits."""
    migrate()
    limiter = RateLimiter()

    log.info("=" * 60)
    log.info(f"  Instagram Follow+DM Session")
    log.info(f"  State: {limiter.current_state} | Budget: {limiter.pairs_budget}/day")
    log.info(f"  Pairs done today: {get_todays_pair_count()}")
    log.info(f"  Remaining: {limiter.pairs_remaining}")
    log.info(f"  Dry run: {dry_run}")
    log.info("=" * 60)

    if not limiter.can_act():
        log.info("Rate limiter says NO. Session aborted.")
        return

    # Load candidates
    candidates = get_dm_candidates(limit=limiter.pairs_remaining + 10)  # extra buffer for skips
    if not candidates:
        log.info("No DM candidates available. All businesses already contacted.")
        return

    log.info(f"Loaded {len(candidates)} candidates. Will attempt up to {limiter.pairs_remaining} pairs.")

    # Start phone status session
    session_id = ps_start("ig_session_runner") if not dry_run else None

    # Acquire phone lock
    if not dry_run:
        from instagram_sender import _resolve_adb_target
        _adb_target = _resolve_adb_target()
        if not acquire_phone_lock(_adb_target):
            log.error("Could not acquire phone lock. Another session may be running. Aborting.")
            return
        try:
            unlock_screen()
        except Exception as e:
            log.error(f"Failed to unlock screen: {e}")
            subprocess.run(
                f"adb -s {_adb_target} shell rmdir /sdcard/ig_automation_lock 2>/dev/null",
                shell=True
            )
            return

    stats = {"success": 0, "skipped": 0, "blocked": 0, "errors": 0}

    try:
        for candidate in candidates:
            # Check budget before each pair
            if not limiter.can_act():
                log.info("Budget exhausted or rate limited. Stopping session.")
                break

            username = candidate["instagram"].lstrip("@").strip()
            if not username:
                continue

            message = build_dm_message(candidate)

            result = follow_and_dm(
                username=username,
                message=message,
                business_id=candidate["id"],
                limiter=limiter,
                dry_run=dry_run,
            )

            if result == "success":
                stats["success"] += 1
                limiter.record_success()
            elif result == "blocked":
                stats["blocked"] += 1
                log.warning("Session terminated early due to action block.")
                break
            elif result.startswith("skip"):
                stats["skipped"] += 1
            else:
                stats["errors"] += 1

            # Delay between pairs (state-dependent)
            if limiter.can_act():  # Don't delay if we're done
                delay = limiter.get_delay()
                log.info(f"Sleeping {delay}s before next pair...")
                time.sleep(delay)

    except KeyboardInterrupt:
        log.info("Session interrupted by user.")
    except Exception as e:
        log.error(f"Fatal session error: {e}", exc_info=True)
    finally:
        if not dry_run:
            from instagram_sender import _resolve_adb_target
            # Release phone lock
            subprocess.run(
                f"adb -s {_resolve_adb_target()} shell rmdir /sdcard/ig_automation_lock 2>/dev/null",
                shell=True
            )
            # Go home
            adb("shell input keyevent 3")
            # End phone status session
            if session_id:
                summary = (f"{stats['success']} sent, {stats['skipped']} skipped, "
                           f"{stats['blocked']} blocked, {stats['errors']} errors")
                ps_end(session_id, summary)

    # Summary
    log.info("=" * 60)
    log.info(f"  Session Complete")
    log.info(f"  Success: {stats['success']} | Skipped: {stats['skipped']}")
    log.info(f"  Blocked: {stats['blocked']} | Errors: {stats['errors']}")
    log.info(f"  Total pairs today: {get_todays_pair_count()}")
    log.info("=" * 60)


def show_status():
    """Display current rate limiter state and upcoming candidates."""
    migrate()
    limiter = RateLimiter()
    state = limiter.state

    print("\n" + "=" * 60)
    print("  Instagram Automation Status")
    print("=" * 60)
    print(f"  State:           {limiter.current_state}")
    print(f"  Budget:          {limiter.pairs_budget} pairs/day")
    print(f"  Done today:      {get_todays_pair_count()}")
    print(f"  Remaining:       {limiter.pairs_remaining}")
    print(f"  Block count:     {state.get('block_count', 0)}")
    print(f"  Last block:      {state.get('last_block_at', 'never')}")
    print(f"  Cooldown until:  {state.get('cooldown_until', '-')}")
    print(f"  Frozen until:    {state.get('frozen_until', '-')}")
    print(f"  Warmup day:      {state.get('warmup_day', '-')}")
    print(f"  Can act now:     {limiter.can_act()}")
    print(f"  Next delay:      {limiter.get_delay()}s")
    print()

    candidates = get_dm_candidates(5)
    if candidates:
        print("  Next candidates:")
        for c in candidates:
            print(f"    @{c['instagram']:20s}  {c['name'][:30]:30s}  {c.get('city', '')}")
    else:
        print("  No candidates available.")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    if "--status" in sys.argv:
        show_status()
    elif "--dry-run" in sys.argv:
        run_session(dry_run=True)
    else:
        run_session(dry_run=False)
