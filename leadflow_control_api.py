# leadflow_control_api.py – FastAPI wrapper to control LeadFlow app and IG outreach

"""Run with:
    uvicorn leadflow_control_api:app --host 127.0.0.1 --port 8000

Exports two main endpoints:
* GET  /health                 – pings the existing LeadFlow UI (192.168.1.3:8765).
* POST /generate_ig            – creates an IG DM link and profile link for a chosen tier or username,
                                 sends the draft to the Telegram destination chats, and notifies via ntfy.
"""

import os
import asyncio
import json
from typing import Optional

import aiohttp
from fastapi import FastAPI, HTTPException

# Import the shared Telegram client and logger from the main bot
from stealdeals_userbot import client, logger

# Re‑use the ntfy helper (same implementation as in leadflow_userbot)
NTFY_TOPIC = os.getenv("NTFY_TOPIC")
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"

async def ntfy_notify(title: str, message: str) -> None:
    payload = {"title": title, "message": message, "tags": ["rocket"]}
    async with aiohttp.ClientSession() as sess:
        try:
            async with sess.post(NTFY_URL, json=payload, timeout=5) as resp:
                if resp.status != 200:
                    logger.warning("ntfy notification failed %s: %s", resp.status, await resp.text())
        except Exception as exc:
            logger.exception("Exception during ntfy notification: %s", exc)

# IG helper imports
from leadflow_ig_helper import generate_dm_link, generate_profile_link, load_tiered_businesses, pick_business

app = FastAPI()

@app.get("/health")
async def health_check():
    """Ping the LeadFlow web UI and report status."""
    health_url = "http://192.168.1.3:8765/api/health"
    async with aiohttp.ClientSession() as sess:
        try:
            async with sess.get(health_url, timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return {"status": "ok", "detail": data}
                else:
                    raise HTTPException(status_code=502, detail=f"LeadFlow UI returned {resp.status}")
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc))

@app.post("/generate_ig")
async def generate_ig(tier: Optional[str] = None, username: Optional[str] = None, message: Optional[str] = "Hello!"):
    """Generate IG links, send a Telegram draft, and fire an ntfy alert.

    * If *username* is provided it is used directly.
    * Else a random username from the requested *tier* (tier1/tier2) is chosen.
    """
    # Resolve username
    if not username:
        if not tier:
            raise HTTPException(status_code=400, detail="Either tier or username must be supplied")
        businesses = load_tiered_businesses()
        username = pick_business(tier, businesses)
        if not username:
            raise HTTPException(status_code=404, detail=f"No usernames found for tier '{tier}'")

    dm_link = generate_dm_link(username, message)
    profile_link = generate_profile_link(username)
    draft_text = f"Demo DM for @{username}:\n{dm_link}\nProfile: {profile_link}"

    # Send to Telegram destination chats (read from env var or fallback)
    dest_env = os.getenv("LEADFLOW_DEST_CHATS")
    if dest_env:
        dest_ids = [int(x) for x in dest_env.split(",") if x.strip()]
    else:
        dest_ids = []
    if not dest_ids:
        logger.warning("No destination chats configured – draft not sent")
    else:
        await client.start()
        for dest in dest_ids:
            try:
                await client.send_message(dest, draft_text)
                logger.info("Sent IG outreach draft to %s", dest)
            except Exception as exc:
                logger.exception("Failed to send IG draft to %s: %s", dest, exc)
        await client.disconnect()

    # Notify via ntfy
    await ntfy_notify("LeadFlow IG draft generated", f"DM link: {dm_link}\nProfile: {profile_link}")

    return {"username": username, "dm_link": dm_link, "profile_link": profile_link}
