"""
Beacon relay — publishes the current tunnel URL to GitHub Pages
as beacon-config.json so ALL deployed demo pages can look it up
at runtime. This completely decouples the engagement beacon from the
Cloudflare tunnel URL that was baked in at deploy-time.

Every demo's JavaScript now does:
  1. Fetch https://power7t.github.io/leadflow-demos/beacon-config.json
  2. Read the "url" field
  3. Use that as BEACON for all engagement pings

When the tunnel rotates, call publish_beacon_config() once and every
demo page instantly starts using the new URL — no redeployment needed.
"""
import json
import threading
from pathlib import Path


_UPDATE_LOCK = threading.Lock()


def publish_beacon_config(tunnel_url: str) -> dict:
    """
    Push beacon-config.json to GitHub Pages.
    Returns {ok, error}.
    """
    from deploy import deploy_raw
    payload = json.dumps({"url": tunnel_url, "v": 2}, indent=2)
    return deploy_raw("beacon-config.json", payload)


def get_published_beacon_url() -> str:
    """Return the URL that is currently published in beacon-config.json."""
    try:
        import urllib.request, ssl
        # fix #7: use verified SSL context (certifi bundle if available, else system)
        try:
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            ctx = ssl.create_default_context()
        with urllib.request.urlopen(
            "https://power7t.github.io/leadflow-demos/beacon-config.json",
            timeout=8,
            context=ctx,
        ) as r:
            data = json.loads(r.read().decode())
            return data.get("url", "")
    except Exception:
        return ""


def sync_beacon_if_stale(current_tunnel_url: str) -> bool:
    """
    Compare current tunnel URL with what's published.
    If different, publish the new one. Returns True if an update was pushed.
    """
    if not current_tunnel_url or not current_tunnel_url.startswith("https://"):
        return False
    with _UPDATE_LOCK:
        published = get_published_beacon_url()
        if published == current_tunnel_url:
            return False  # already up to date
        result = publish_beacon_config(current_tunnel_url)
        if result.get("ok"):
            print(f"[beacon_relay] Published new beacon URL: {current_tunnel_url}")
        else:
            print(f"[beacon_relay] Failed to publish beacon: {result.get('error')}")
        return result.get("ok", False)
