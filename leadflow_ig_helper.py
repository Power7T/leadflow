# leadflow_ig_helper.py – utilities for manual IG outreach

"""Utility functions to generate Instagram DM and profile links for manual outreach.

These helpers are used by the LeadFlow control API and CLI to create copy‑able
messages that can be sent via the Telegram bot.
"""

import urllib.parse
from typing import Dict, List


def generate_dm_link(username: str, message: str) -> str:
    """Return an Instagram direct‑message URL with the provided message.

    The message is URL‑encoded and appended to the standard DM creation URL.
    """
    encoded_msg = urllib.parse.quote_plus(message)
    return f"https://www.instagram.com/direct/new/?text={encoded_msg}"


def generate_profile_link(username: str) -> str:
    """Return the public Instagram profile URL for a given username."""
    safe_user = urllib.parse.quote_plus(username)
    return f"https://instagram.com/{safe_user}"


def load_tiered_businesses(path: str = "tiered_businesses.json") -> Dict[str, List[str]]:
    """Load a JSON file that maps tier names to a list of Instagram usernames.

    Example file content:
    {
        "tier1": ["highvalue1", "highvalue2"],
        "tier2": ["midvalue1", "midvalue2"]
    }
    """
    import json, os
    if not os.path.isfile(path):
        return {"tier1": [], "tier2": []}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def pick_business(tier: str, data: Dict[str, List[str]]) -> str:
    """Pick a random business username from the requested tier.

    Returns an empty string if the tier is unknown or empty.
    """
    import random
    businesses = data.get(tier.lower(), [])
    if not businesses:
        return ""
    return random.choice(businesses)
