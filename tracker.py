"""
Email tracking — open pixel + click redirect.
Embeds a 1px tracking pixel into sent emails.
Records opens and clicks in the database.
"""
import base64
import re

# 1x1 transparent GIF
PIXEL_GIF = base64.b64decode(
    "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
)

APP_BASE_URL = "http://127.0.0.1:8765"  # Updated to tunnel URL at runtime if available


def get_base_url() -> str:
    """Return tunnel URL if available, else localhost."""
    try:
        from pathlib import Path
        url = Path("/tmp/leadflow-tunnel-url.txt").read_text().strip()
        if url.startswith("https://"):
            return url
    except Exception:
        pass
    return APP_BASE_URL


def make_tracking_pixel(tracking_id: str) -> str:
    """Return an HTML img tag for the tracking pixel."""
    base = get_base_url()
    return f'<img src="{base}/track/open/{tracking_id}" width="1" height="1" style="display:none" />'


def make_tracked_link(url: str, tracking_id: str, label: str = "") -> str:
    """Wrap a URL in a click-tracking redirect."""
    base = get_base_url()
    import urllib.parse
    encoded = urllib.parse.quote(url, safe="")
    redirect = f"{base}/track/click/{tracking_id}?url={encoded}"
    return f'<a href="{redirect}">{label or url}</a>'


def inject_tracking_into_email(body_text: str, tracking_id: str, demo_url: str = "") -> str:
    """
    Convert plain text email to HTML with:
    - tracking pixel at bottom
    - demo site link made trackable if present
    Returns HTML string.
    """
    # Convert plain text to basic HTML
    html_body = body_text.replace("\n", "<br>")

    # Inject trackable demo link if present
    if demo_url:
        tracked = make_tracked_link(demo_url, tracking_id, "View Your Free Demo Site →")
        html_body += f"<br><br>{tracked}"

    pixel = make_tracking_pixel(tracking_id)

    return f"""<html><body style="font-family:-apple-system,sans-serif;font-size:14px;line-height:1.7;color:#222;max-width:600px;margin:0 auto;padding:20px">
{html_body}
{pixel}
</body></html>"""
