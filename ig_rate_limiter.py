"""
ig_rate_limiter.py — Autonomous Rate Limiter for Instagram Automation

State machine:
  WARMING_UP   → 5 pairs/day for first 3 days (new account protection)
  NORMAL       → 10 pairs/day (cruise speed)
  COOLING_DOWN → 3 pairs/day (after action block detected)
  FROZEN       → 0 actions (after repeated blocks; auto-thaws after cooldown period)

Action block detection:
  Parses uiautomator XML for Instagram's "Try Again Later" popup and similar
  block patterns. On detection, transitions state down and records the event.

Self-healing:
  - Single block → COOLING_DOWN for 24h, then back to NORMAL
  - 2 blocks in 48h → FROZEN for 48h, then WARMING_UP
  - 3+ blocks in 72h → FROZEN for 7 days, then WARMING_UP
"""

import logging
import time
import random
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

from ig_rate_db import get_rate_state, update_rate_state, get_todays_pair_count

log = logging.getLogger("ig_rate_limiter")

# ── Block detection patterns (found in Instagram's "Try Again Later" popup) ─
BLOCK_PATTERNS = [
    "try again later",
    "we limit how often",
    "action blocked",
    "temporarily blocked",
    "we restrict certain activity",
    "please try again",
    "you're temporarily restricted",
    "this action was blocked",
    "challenge_required",
    "feedback_required",
]

# ── State budget: how many follow+DM pairs allowed per state ────────────────
STATE_BUDGETS = {
    "WARMING_UP":   5,
    "NORMAL":       10,
    "COOLING_DOWN": 3,
    "FROZEN":       0,
}

# ── Cooldown durations ──────────────────────────────────────────────────────
COOLDOWN_HOURS = {
    1: 24,    # first block → 24h cooldown
    2: 48,    # second block within 48h → 48h cooldown
}
FROZEN_HOURS_MAX = 168   # 3+ blocks → 7 days frozen


def _send_telegram_alert(message: str) -> None:
    """Fire-and-forget Telegram alert. Silently swallows all errors."""
    try:
        import os
        import requests
        bot_token = os.getenv("TELEGRAM_CONTROL_BOT_TOKEN", "")
        user_id = os.getenv("TELEGRAM_CONTROL_USER_ID", "")
        if not bot_token or not user_id:
            return
        requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": user_id, "text": message, "parse_mode": "HTML"},
            timeout=5,
        )
    except Exception:
        pass


class RateLimiter:
    """Autonomous rate limiter with self-healing state machine."""

    def __init__(self):
        self._ensure_state()

    def _ensure_state(self):
        """Load or initialize state from DB."""
        state = get_rate_state()
        if not state:
            from ig_rate_db import migrate
            migrate()
            state = get_rate_state()
        self.state = state

    def reload(self):
        """Reload state from DB (call after external changes)."""
        self.state = get_rate_state()

    @property
    def current_state(self) -> str:
        return self.state.get("state", "WARMING_UP")

    @property
    def pairs_budget(self) -> int:
        """How many follow+DM pairs can we do today."""
        return STATE_BUDGETS.get(self.current_state, 0)

    @property
    def pairs_remaining(self) -> int:
        """How many pairs left today."""
        self._check_day_reset()
        done = get_todays_pair_count()
        return max(0, self.pairs_budget - done)

    def can_act(self) -> bool:
        """Check if we're allowed to perform a follow+DM pair right now."""
        self.reload()
        self._check_day_reset()
        self._check_thaw()

        if self.current_state == "FROZEN":
            frozen_until = self.state.get("frozen_until")
            if frozen_until:
                log.info(f"FROZEN until {frozen_until}. No actions allowed.")
            return False

        if self.current_state == "COOLING_DOWN":
            cooldown_until = self.state.get("cooldown_until")
            if cooldown_until:
                cd = datetime.fromisoformat(cooldown_until)
                if datetime.now() < cd:
                    log.info(f"COOLING_DOWN until {cooldown_until}. Checking budget...")
                    # Still in cooldown, but may have reduced budget available
                    pass

        remaining = self.pairs_remaining
        if remaining <= 0:
            log.info(f"Daily budget exhausted ({self.current_state}: {self.pairs_budget} pairs/day). Done for today.")
            return False

        log.info(f"State={self.current_state} | Budget={self.pairs_budget} | Remaining={remaining}")
        return True

    def get_delay(self) -> int:
        """Get randomized delay between actions based on current state."""
        if self.current_state == "WARMING_UP":
            return random.randint(180, 360)      # 3-6 minutes (extra cautious)
        elif self.current_state == "NORMAL":
            return random.randint(90, 180)        # 1.5-3 minutes
        elif self.current_state == "COOLING_DOWN":
            return random.randint(300, 600)       # 5-10 minutes (very cautious)
        return 600  # FROZEN — shouldn't be called, but safe fallback

    def record_success(self):
        """Record a successful follow+DM pair."""
        update_rate_state(
            last_action_at=datetime.now().isoformat(),
            pairs_today=get_todays_pair_count(),
        )
        log.info(f"Action recorded. Pairs today: {get_todays_pair_count()}")

        # Auto-promote from WARMING_UP to NORMAL after 3 days
        if self.current_state == "WARMING_UP":
            warmup_day = self.state.get("warmup_day", 1)
            if warmup_day >= 3:
                log.info("WARMING_UP complete (3 days). Promoting to NORMAL.")
                update_rate_state(state="NORMAL", warmup_day=0)
            else:
                # Increment warmup day if this is a new calendar day
                today = datetime.now().strftime("%Y-%m-%d")
                if self.state.get("today_date") != today:
                    update_rate_state(warmup_day=warmup_day + 1, today_date=today)

    def record_block(self):
        """Handle an action block event. Transition state downward."""
        now = datetime.now()
        block_count = self.state.get("block_count", 0) + 1
        last_block = self.state.get("last_block_at")

        # Check if blocks are clustered (within 72 hours)
        recent_blocks = block_count
        if last_block:
            try:
                lb = datetime.fromisoformat(last_block)
                if (now - lb).total_seconds() > 72 * 3600:
                    # Old block, reset counter
                    recent_blocks = 1
                    block_count = 1
            except Exception:
                pass

        log.warning(f"ACTION BLOCK detected! Block #{block_count} (recent cluster: {recent_blocks})")
        _send_telegram_alert(
            f"🚨 <b>LeadFlow IG Block Detected</b>\n"
            f"State: {self.state.get('state', 'UNKNOWN')}\n"
            f"Consecutive blocks: {block_count}"
        )

        if recent_blocks >= 3:
            # 3+ blocks in 72h → FROZEN for 7 days
            frozen_until = (now + timedelta(hours=FROZEN_HOURS_MAX)).isoformat()
            update_rate_state(
                state="FROZEN",
                block_count=block_count,
                last_block_at=now.isoformat(),
                frozen_until=frozen_until,
                pairs_today=0,
            )
            log.warning(f"FROZEN for 7 days (until {frozen_until}). Too many blocks.")

        elif recent_blocks >= 2:
            # 2 blocks in 48h → FROZEN for 48h
            frozen_until = (now + timedelta(hours=COOLDOWN_HOURS[2])).isoformat()
            update_rate_state(
                state="FROZEN",
                block_count=block_count,
                last_block_at=now.isoformat(),
                frozen_until=frozen_until,
                pairs_today=0,
            )
            log.warning(f"FROZEN for 48h (until {frozen_until}). Repeated blocks.")

        else:
            # First block → COOLING_DOWN for 24h
            cooldown_until = (now + timedelta(hours=COOLDOWN_HOURS[1])).isoformat()
            update_rate_state(
                state="COOLING_DOWN",
                block_count=block_count,
                last_block_at=now.isoformat(),
                cooldown_until=cooldown_until,
            )
            log.warning(f"COOLING_DOWN for 24h (until {cooldown_until}).")

    def _check_day_reset(self):
        """Reset daily pair counter if it's a new day."""
        today = datetime.now().strftime("%Y-%m-%d")
        if self.state.get("today_date") != today:
            update_rate_state(pairs_today=0, today_date=today)
            self.reload()

    def _check_thaw(self):
        """Check if a FROZEN or COOLING_DOWN period has expired and promote state."""
        now = datetime.now()

        if self.current_state == "FROZEN":
            frozen_until = self.state.get("frozen_until")
            if frozen_until:
                try:
                    fu = datetime.fromisoformat(frozen_until)
                    if now >= fu:
                        log.info("FROZEN period expired. Thawing to WARMING_UP.")
                        update_rate_state(
                            state="WARMING_UP",
                            frozen_until=None,
                            warmup_day=1,
                            block_count=0,
                            pairs_today=0,
                        )
                        self.reload()
                except Exception:
                    pass

        elif self.current_state == "COOLING_DOWN":
            cooldown_until = self.state.get("cooldown_until")
            if cooldown_until:
                try:
                    cu = datetime.fromisoformat(cooldown_until)
                    if now >= cu:
                        log.info("COOLING_DOWN period expired. Returning to NORMAL.")
                        update_rate_state(
                            state="NORMAL",
                            cooldown_until=None,
                        )
                        self.reload()
                except Exception:
                    pass


# ── XML-based block detection ───────────────────────────────────────────────

def check_for_action_block(xml_data: str) -> bool:
    """Parse uiautomator XML and check for Instagram action block popup.

    Returns True if a block pattern is detected.
    """
    if not xml_data or "ERROR" in xml_data:
        return False

    try:
        root = ET.fromstring(xml_data)
        for node in root.iter('node'):
            text = node.attrib.get('text', '').lower()
            content_desc = node.attrib.get('content-desc', '').lower()
            combined = text + " " + content_desc

            for pattern in BLOCK_PATTERNS:
                if pattern in combined:
                    log.warning(f"Block pattern detected in XML: '{pattern}' in '{combined[:80]}'")
                    return True
    except ET.ParseError:
        log.warning("Failed to parse XML for block detection")

    return False


def dismiss_block_popup(adb_fn):
    """Try to dismiss an action block popup by tapping OK/Got It."""
    # Known OK button coordinates on Vivo phone for "Try Again Later"
    # First try via UI element search
    time.sleep(1)
    adb_fn("shell uiautomator dump /sdcard/window_dump.xml")
    time.sleep(0.5)
    xml_data = adb_fn("shell cat /sdcard/window_dump.xml")

    if xml_data and "ERROR" not in xml_data:
        try:
            root = ET.fromstring(xml_data)
            for node in root.iter('node'):
                text = node.attrib.get('text', '').strip().lower()
                if text in ('ok', 'got it', 'tell us', 'close'):
                    bounds = node.attrib.get('bounds', '')
                    if bounds:
                        b = bounds.replace('[', '').replace(']', ',').split(',')
                        x = (int(b[0]) + int(b[2])) // 2
                        y = (int(b[1]) + int(b[3])) // 2
                        log.info(f"Dismissing block popup: tapping '{text}' at ({x},{y})")
                        adb_fn(f"shell input tap {x} {y}")
                        time.sleep(2)
                        return True
        except ET.ParseError:
            pass

    # Fallback: hardcoded OK button position on Vivo (360, 873)
    log.info("Dismissing block popup via hardcoded OK position (360, 873)")
    adb_fn("shell input tap 360 873")
    time.sleep(2)
    return True


def get_screen_xml(adb_fn) -> str:
    """Dump and read current screen XML."""
    adb_fn("shell uiautomator dump /sdcard/window_dump.xml")
    time.sleep(0.5)
    return adb_fn("shell cat /sdcard/window_dump.xml")


# ── Convenience ─────────────────────────────────────────────────────────────

def check_and_handle_block(adb_fn, limiter: RateLimiter) -> bool:
    """Check current screen for block, handle it, update rate state.

    Returns True if a block was detected (caller should abort current action).
    """
    xml_data = get_screen_xml(adb_fn)
    if check_for_action_block(xml_data):
        dismiss_block_popup(adb_fn)
        limiter.record_block()
        return True
    return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    from ig_rate_db import migrate
    migrate()

    rl = RateLimiter()
    print(f"Current state: {rl.current_state}")
    print(f"Budget today:  {rl.pairs_budget}")
    print(f"Remaining:     {rl.pairs_remaining}")
    print(f"Can act:       {rl.can_act()}")
    print(f"Delay:         {rl.get_delay()}s")
