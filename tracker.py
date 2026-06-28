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
    """Return tunnel URL if available, else fallback to LEADFLOW_PUBLIC_URL from env, else localhost."""
    try:
        from pathlib import Path
        url = Path("/tmp/leadflow-tunnel-url.txt").read_text().strip()
        if url.startswith("https://"):
            return url
    except Exception:
        pass
    import os
    env_url = os.getenv("LEADFLOW_PUBLIC_URL", "")
    if env_url.startswith("https://"):
        return env_url
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


def make_demo_button(url: str, tracking_id: str) -> str:
    """
    Return a prominent, click-tracked CTA button for the demo link.
    High contrast — designed to stand out in Gmail/Outlook and drive clicks.
    """
    base = get_base_url()
    import urllib.parse
    encoded = urllib.parse.quote(url, safe="")
    redirect = f"{base}/track/click/{tracking_id}?url={encoded}"
    return f"""
<table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:18px 0 12px 0;">
  <tr>
    <td align="left">
      <a href="{redirect}" target="_blank" rel="noopener"
         style="display:inline-block;background:#1a56db;color:#ffffff;
                font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
                font-size:15px;font-weight:600;text-decoration:none;
                padding:12px 28px;border-radius:6px;
                letter-spacing:0.3px;">
        👀 View your free demo site →
      </a>
    </td>
  </tr>
  <tr>
    <td style="padding-top:6px;">
      <span style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
                   font-size:12px;color:#888;">
        Or copy this link: <a href="{redirect}" style="color:#1a56db;word-break:break-all;">{url}</a>
      </span>
    </td>
  </tr>
</table>"""


def inject_tracking_into_email(body_text: str, tracking_id: str, demo_url: str = "") -> str:
    """
    Convert plain text email to HTML with:
    - tracking pixel at bottom
    - demo site link replaced with a prominent CTA button
    Returns HTML string.
    """
    # Convert plain text to basic HTML
    html_body = body_text.replace("\n", "<br>")

    if demo_url:
        demo_button = make_demo_button(demo_url, tracking_id)

        if demo_url in html_body:
            # Find the raw URL in the converted HTML and replace with button
            # Remove the leading <br> before the URL if it is on its own line
            # to avoid extra spacing
            html_body = re.sub(
                r'(<br>)?' + re.escape(demo_url),
                demo_button,
                html_body,
                count=1,
            )
        else:
            # If not in body, append the button prominently
            html_body += f"<br>{demo_button}"

    pixel = make_tracking_pixel(tracking_id)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
</head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;
             font-size:15px;line-height:1.65;color:#1a1a1a;background:#ffffff;
             max-width:580px;margin:0 auto;padding:24px 20px">
{html_body}
{pixel}
<br>
<p style="font-size:11px;color:#999;margin-top:32px;border-top:1px solid #eee;padding-top:12px;">
  You received this message because your business appeared in our local search results.
  <a href="{get_base_url()}/unsubscribe/{tracking_id}" style="color:#999;">Unsubscribe</a>
</p>
</body>
</html>"""
