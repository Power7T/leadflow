"""
Demo site generator — scrapes the business's REAL website, extracts
actual content (text, services, images, colors), then builds a modern
redesign using their own material. Not a template — a real demo.
"""
import re
import base64
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

from conversion import cta_block
from deploy import public_base

# Stock imagery shipped with the templates. We NEVER put the prospect's own
# images on a demo — always these, so nothing can hotlink-break or look "theirs".
_STOCK_HERO  = "https://images.unsplash.com/photo-1497366216548-37526070297c?w=1600&q=80" # Modern professional office interior
_STOCK_ABOUT = "https://images.unsplash.com/photo-1522071820081-009f0129c71c?w=800&q=80"


def _track_pixel(business: dict) -> str:
    """Demo-open tracking pixel with the public URL baked in at build time.

    (The old template used {{TUNNEL_URL}} placeholders that were never actually
    substituted — single vs double braces — so open-tracking silently never
    fired. Baking the value here fixes that.)"""
    base = public_base()
    bid = business.get("id", "")
    if not base or not bid:
        return ""
    return (
        '<!-- TRACKING SCRIPT -->\n<script>\n'
        f'  try {{ fetch("{base}/api/track.png?bid={bid}", {{mode:"no-cors"}}); }} catch(e) {{}}\n'
        '</script>'
    )


def _inject_conversion(html: str, business: dict) -> str:
    """Add the conversion CTA layer + working open-tracking to rendered HTML
    (used for external Jinja templates, which don't include them)."""
    extra = cta_block(business) + "\n" + _track_pixel(business)
    if "</body>" in html:
        return html.replace("</body>", extra + "\n</body>", 1)
    return html + extra


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "Chrome/120.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}
TIMEOUT = 10

# Noise selectors to strip before extracting text
STRIP_TAGS = ["script", "style", "noscript", "nav", "header", "footer",
              "form", "iframe", "svg", "button", "aside"]

_MIME_MAP = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
    "gif": "image/gif", "webp": "image/webp", "avif": "image/avif",
    "svg": "image/svg+xml",
}

def _fetch_gmaps_photos(place_id: str, n: int = 4) -> list[str]:
    """Return up to n base64 data-URIs for a Google Maps place."""
    try:
        import os
        key = os.getenv("GOOGLE_MAPS_API_KEY", "")
        if not key or not place_id:
            return []
        r = requests.get(
            "https://maps.googleapis.com/maps/api/place/details/json",
            params={"place_id": place_id, "fields": "photos", "key": key},
            timeout=10,
            verify=False
        )
        photos = r.json().get("result", {}).get("photos", [])[:n]
        result = []
        for p in photos:
            ref = p.get("photo_reference", "")
            if not ref:
                continue
            img_r = requests.get(
                "https://maps.googleapis.com/maps/api/place/photo",
                params={"maxwidth": 1200, "photo_reference": ref, "key": key},
                timeout=10, allow_redirects=True,
                verify=False
            )
            if img_r.status_code == 200 and len(img_r.content) < 800_000:
                mime = img_r.headers.get("content-type", "image/jpeg").split(";")[0]
                b64  = base64.b64encode(img_r.content).decode()
                result.append(f"data:{mime};base64,{b64}")
        return result
    except Exception:
        return []


def _img_to_datauri(url: str, referer: str = "") -> str:
    """Download an image and return a base64 data URI. Falls back to URL on error."""
    if not url or url.startswith("data:"):
        return url
    try:
        headers = {**HEADERS, "Referer": referer or url}
        r = requests.get(url, headers=headers, timeout=8, stream=True)
        if r.status_code != 200:
            return url
        # Skip huge images (>600KB) — keep file size reasonable
        content = b""
        for chunk in r.iter_content(8192):
            content += chunk
            if len(content) > 600_000:
                return url
        ext = url.split("?")[0].rsplit(".", 1)[-1].lower()
        mime = r.headers.get("content-type", "").split(";")[0].strip() or _MIME_MAP.get(ext, "image/jpeg")
        b64 = base64.b64encode(content).decode()
        return f"data:{mime};base64,{b64}"
    except Exception:
        return url

# Keywords that suggest a services/features block
SERVICE_KEYWORDS = re.compile(
    r"service|offer|menu|special|feature|package|plan|product|treatment|"
    r"class|course|session|dish|item|solution|what we do|how we help",
    re.I,
)

CATEGORY_FALLBACK_COLORS = {
    "restaurant": ("#d4a853", "#1a1208"),
    "cafe":       ("#7ab87a", "#0d1a0d"),
    "coffee":     ("#a07850", "#1a100a"),
    "bakery":     ("#d4836a", "#1a0d0b"),
    "gym":        ("#4d9fff", "#080f1a"),
    "fitness":    ("#4d9fff", "#080f1a"),
    "salon":      ("#cc7ecc", "#140d1a"),
    "spa":        ("#6ecfbe", "#0d1a17"),
    "hotel":      ("#c9b36e", "#1a150a"),
    "bar":        ("#d47070", "#1a0a0a"),
    "dentist":    ("#5bb8d4", "#081318"),
    "dental":     ("#5bb8d4", "#081318"),
    "clinic":     ("#5bd48a", "#081a0f"),
    "plumber":    ("#e09050", "#1a1008"),
    "electrician":("#f5d742", "#1a1800"),
    "real estate":("#4da6ff", "#08101a"),
    "default":    ("#00c896", "#0d1a15"),
}


def get_competitor_name(category: str, city: str, business_name: str) -> str:
    """Search Google via Serper API to find the top local competitor."""
    info = get_competitor_info(category, city, business_name)
    return info.get("name", "")


def get_competitor_info(category: str, city: str, business_name: str) -> dict:
    """Return {name, url, score} for the top local competitor.

    score is the website quality score (0-100) from score_website().
    Returns empty dict on failure.
    """
    if not category or not city or not business_name:
        return {}
    import os
    api_key = os.getenv("SERPER_API_KEY")
    if not api_key:
        return {}
    try:
        query = f"top {category} in {city}"
        payload = {"q": query, "location": city}
        headers = {'X-API-KEY': api_key, 'Content-Type': 'application/json'}
        response = requests.post("https://google.serper.dev/search", json=payload, headers=headers, timeout=5)
        if response.status_code != 200:
            return {}
        data = response.json()
        name = ""
        url = ""
        # Try places (local map pack) first
        places = data.get("places", [])
        for place in places:
            title = place.get("title", "")
            if title and business_name.lower() not in title.lower() and "yelp" not in title.lower():
                name = title
                url = place.get("website", "") or place.get("link", "")
                break
        # Fallback to organic results
        if not name:
            organic = data.get("organic", [])
            for org in organic:
                title = org.get("title", "").split("-")[0].split("|")[0].strip()
                if title and business_name.lower() not in title.lower() and "yelp" not in title.lower() and "bbb" not in title.lower():
                    name = title
                    url = org.get("link", "")
                    break
        if not name:
            return {}
        score = 0
        if url:
            try:
                from analyzer import score_website
                score = score_website(url) or 0
            except Exception:
                pass
        return {"name": name, "url": url, "score": int(score)}
    except Exception:
        pass
    return {}

# ── Scraping ──────────────────────────────────────────────────────────────────

def _scrape_site(url: str) -> dict:
    """Fetch and extract everything useful from the existing website, including Deep-Dive into About/Services."""
    out = {
        "title": "", "description": "", "og_image": "",
        "about_text": "", "services": [], "images": [],
        "accent_color": "", "hero_text": "", "tagline": "",
    }
    if not url:
        return out

    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        if r.status_code not in (200, 203):
            return out
        soup = BeautifulSoup(r.text, "lxml")
    except Exception:
        return out

    base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"

    # Meta basics
    out["title"] = (soup.title.string or "").strip()[:80]

    desc_tag = soup.find("meta", {"name": re.compile("description", re.I)})
    if desc_tag:
        out["description"] = (desc_tag.get("content") or "").strip()[:300]

    og_img = soup.find("meta", property="og:image")
    if og_img:
        src = og_img.get("content", "")
        out["og_image"] = src if src.startswith("http") else urljoin(base, src)

    og_desc = soup.find("meta", property="og:description")
    if og_desc and not out["description"]:
        out["description"] = (og_desc.get("content") or "").strip()[:300]

    tc = soup.find("meta", {"name": "theme-color"})
    if tc:
        out["accent_color"] = tc.get("content", "")

    for tag in soup.find_all(["h1", "h2"]):
        text = tag.get_text(" ", strip=True)
        if 4 < len(text) < 120 and not any(bad in text.lower() for bad in ["cookie", "menu", "nav", "skip"]):
            out["hero_text"] = text
            break

    # Find Deep-Dive Links before decomposing noise
    about_link = None
    services_link = None
    for a in soup.find_all("a", href=True):
        href = a["href"].lower()
        text = a.get_text(" ", strip=True).lower()
        if not about_link and ("about" in href or "about" in text or "story" in href):
            about_link = urljoin(base, a["href"])
        if not services_link and ("service" in href or "service" in text or "treatment" in href):
            services_link = urljoin(base, a["href"])

    for t in soup.find_all(STRIP_TAGS):
        t.decompose()

    for h in soup.find_all(["h1", "h2"]):
        sib = h.find_next_sibling()
        if sib and sib.name == "p":
            text = sib.get_text(" ", strip=True)
            if 10 < len(text) < 250:
                out["tagline"] = text
                break

    paras = []
    for p in soup.find_all("p"):
        text = p.get_text(" ", strip=True)
        if 50 < len(text) < 500:
            paras.append(text)
    if paras:
        out["about_text"] = max(paras, key=len)

    services = []
    for section in soup.find_all(["section", "div", "article"]):
        heading = section.find(["h2", "h3", "h4"])
        if not heading:
            continue
        heading_text = heading.get_text(strip=True)
        if not SERVICE_KEYWORDS.search(heading_text):
            continue
        items = []
        for li in section.find_all("li"):
            t = li.get_text(" ", strip=True)
            if 3 < len(t) < 80:
                items.append({"title": t, "desc": ""})
        if not items:
            for h in section.find_all(["h3", "h4", "h5"]):
                title = h.get_text(strip=True)
                if 2 < len(title) < 60:
                    items.append({"title": title, "desc": ""})
        if items:
            services.extend(items[:6])
            break

    if not services:
        for ul in soup.find_all("ul"):
            items = []
            for li in ul.find_all("li", recursive=False):
                t = li.get_text(" ", strip=True)
                if 3 < len(t) < 70:
                    items.append({"title": t, "desc": ""})
            if len(items) >= 3:
                services = items[:6]
                break
    out["services"] = services

    # ── DEEP-DIVE ─────────────────────────────────────────────────────────────
    # If homepage was thin on About/Story, scrape the About page
    if about_link and (not out["about_text"] or len(out["about_text"]) < 100):
        try:
            r = requests.get(about_link, headers=HEADERS, timeout=5)
            if r.status_code == 200:
                sub_soup = BeautifulSoup(r.text, "lxml")
                for t in sub_soup.find_all(STRIP_TAGS): t.decompose()
                sub_paras = [p.get_text(" ", strip=True) for p in sub_soup.find_all("p")]
                long_paras = [p for p in sub_paras if 100 < len(p) < 600 and "cookie" not in p.lower()]
                if long_paras:
                    out["about_text"] = max(long_paras, key=len)  # Best guess at founding story
        except Exception:
            pass

    # If homepage was thin on Services, scrape the Services page
    if services_link and len(out["services"]) < 3:
        try:
            r = requests.get(services_link, headers=HEADERS, timeout=5)
            if r.status_code == 200:
                sub_soup = BeautifulSoup(r.text, "lxml")
                for t in sub_soup.find_all(STRIP_TAGS): t.decompose()
                sub_svcs = []
                # Look for h2/h3 as service titles
                for h in sub_soup.find_all(["h2", "h3"]):
                    t = h.get_text(" ", strip=True)
                    if 4 < len(t) < 40 and "contact" not in t.lower() and "about" not in t.lower():
                        sub_svcs.append({"title": t, "desc": ""})
                if len(sub_svcs) >= 3:
                    out["services"] = sub_svcs[:6]
        except Exception:
            pass
    # ──────────────────────────────────────────────────────────────────────────

    out["images"] = []
    return out



# ── HTML builder ──────────────────────────────────────────────────────────────

def _accent_for_category(category: str, scraped_color: str) -> tuple[str, str]:
    if scraped_color and scraped_color.startswith("#") and len(scraped_color) in (4, 7):
        return scraped_color, "#0d0d0d"
    cat = (category or "").lower()
    for key, colors in CATEGORY_FALLBACK_COLORS.items():
        if key in cat:
            return colors
    return CATEGORY_FALLBACK_COLORS["default"]


GYM_KEYWORDS = re.compile(
    r"gym|fit|fitness|crossfit|boxing|mma|martial art|yoga|pilates|"
    r"health club|workout|training center|athletic|sport|ymca|studio",
    re.I,
)

def _is_gym(category: str, name: str) -> bool:
    cat = (category or "").lower()
    nm = (name or "").lower()
    return bool(GYM_KEYWORDS.search(nm) or GYM_KEYWORDS.search(cat))


def _pick_real_testimonials(reviews_list: list, count: int = 4) -> list[str]:
    """Return up to `count` verbatim 4-5★ Google review texts, cleaned for HTML.

    Only positive reviews (rating >= 4) are used — reviews that read like
    complaints about staff/food/price are filtered client-side by the caller.
    Returns an empty list if no qualifying reviews exist.
    """
    good = [r for r in (reviews_list or []) if isinstance(r, dict) and r.get("rating", 0) >= 4 and r.get("text", "").strip()]
    # Prefer longer reviews with more substance; cap at 300 chars for layout
    good.sort(key=lambda r: len(r["text"]), reverse=True)
    out = []
    for r in good[:count]:
        text = r["text"].strip().replace('"', '“').replace('"', '”')
        # Trim to 280 chars so testimonial cards don't overflow demo layout
        if len(text) > 280:
            text = text[:277].rstrip() + "…"
        out.append(f'"{text}"')
    return out


def generate_gym_demo_html(business: dict, scraped: dict, use_stock: bool = False) -> str:
    """APEX GYM–style gym demo. pms5566/gym-website template, real gym info swapped in."""
    name      = business.get("name", "Your Gym")
    address   = business.get("address", "")
    phone     = business.get("phone", "")
    email     = business.get("email", "")
    instagram = business.get("instagram", "")
    rating    = business.get("google_rating")
    reviews   = business.get("google_reviews")
    website   = business.get("website", "")
    maps_url  = business.get("maps_url", "")
    category  = business.get("category", "")

    about_text = (scraped.get("about_text") or scraped.get("description") or
        f"{name} is a premier fitness facility committed to helping every member achieve "
        "their health and performance goals. Whether you're a beginner or an elite athlete, "
        "our coaches and equipment are here to support your journey.")

    # Rating display
    rating_str = str(rating) if rating else "5.0"
    reviews_str = str(reviews) if reviews else ""

    # CDN base for all template images
    _CDN = "https://pms5566.github.io/gym-website/images/"

    # Testimonials — prefer real Google reviews, fall back to template default cards
    real_quotes = _pick_real_testimonials(scraped.get("reviews", []), count=5)
    if real_quotes:
        testi_cards_html = ""
        for q in real_quotes:
            testi_cards_html += (
                '<div class="testi-card">' +
                '<div class="testi-stars">★★★★★</div>' +
                f'<blockquote>{q}</blockquote>' +
                '<div class="testi-author">' +
                '<div class="ta-ava">🙋</div>' +
                f'<div><b>Happy Member</b><span>Verified Review</span></div>' +
                '</div></div>'
            )
    else:
        testi_cards_html = (
            '<div class="testi-card">' +
            '<div class="testi-stars">★★★★★</div>' +
            f'<blockquote>"{name} changed my life. The trainers are incredibly supportive and the facility is top-notch.</blockquote>' +
            '<div class="testi-author"><div class="ta-ava">🙋‍♀️</div>' +
            '<div><b>Happy Member</b><span>Verified Review</span></div></div></div>'
            '<div class="testi-card">' +
            '<div class="testi-stars">★★★★★</div>' +
            '<blockquote>Best gym in the area. Amazing community, expert coaches, and premium equipment.</blockquote>' +
            '<div class="testi-author"><div class="ta-ava">🙋‍♂️</div>' +
            '<div><b>Loyal Member</b><span>Verified Review</span></div></div></div>'
            '<div class="testi-card">' +
            '<div class="testi-stars">★★★★★</div>' +
            f'<blockquote>The classes here are unmatched. I&#8217;ve never been in better shape since joining {name}.</blockquote>' +
            '<div class="testi-author"><div class="ta-ava">🙋‍♀️</div>' +
            '<div><b>Dedicated Member</b><span>Verified Review</span></div></div></div>'
        )

    # Contact info lines
    address_line = f"📍 {address}" if address else "📍 Visit us in-gym"
    phone_line   = f"📞 {phone}"    if phone   else ""
    email_line   = f"✉️ {email}"    if email   else ""

    # Pixel tracker
    pixel_html = _track_pixel(business)

    # ─── Assemble HTML ────────────────────────────────────────────────────────
    # CSS and JS are inlined via concatenation (not f-strings) to avoid
    # escaping the thousands of { } braces in the stylesheet and JS template literals.

    part_head = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
  <title>{name} — Flex Beyond Limits</title>
  <meta name="description" content="{name} — Where elite fitness meets cutting-edge training. Join our members transforming their bodies and lives.">
  <meta name="keywords" content="gym, fitness, workout, personal training, HIIT, strength training, yoga, boxing">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Inter:wght@300;400;500;600;700;800;900&display=swap" rel="stylesheet">
  <style>
"""

    part_css = '/* =====================================================\n   APEX GYM — style.css\n   Design inspired by ManFlex, Maove, RPA, UIXSHUVO,\n   MURA, ApeFit, and Gym App UI\n   ===================================================== */\n\n/* ===== TOKENS ===== */\n:root {\n  --bg:        #0A0A0A;\n  --bg-s:      #111111;\n  --bg-c:      #181818;\n  --bg-ch:     #1f1f1f;\n  --lime:      #C8FF00;\n  --lime-dim:  rgba(200,255,0,.12);\n  --lime-glow: rgba(200,255,0,.20);\n  --orange:    #FF6B35;\n  --white:     #FFFFFF;\n  --grey:      #AAAAAA;\n  --muted:     #555555;\n  --border:    rgba(255,255,255,.07);\n  --border-l:  rgba(200,255,0,.25);\n  --shadow:    0 8px 40px rgba(0,0,0,.5);\n  --r-sm:      8px;\n  --r-md:      14px;\n  --r-lg:      20px;\n  --r-xl:      28px;\n  --tr:        all .3s cubic-bezier(.4,0,.2,1);\n  --nav-h:     116px;\n  --bn-h:      76px;\n  --font-d:    \'Bebas Neue\', sans-serif;\n  --font-b:    \'Inter\', sans-serif;\n}\n\n/* ===== RESET ===== */\n*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }\nhtml { scroll-behavior: smooth; font-size: 16px; }\nbody {\n  font-family: var(--font-b);\n  background: var(--bg);\n  color: var(--white);\n  line-height: 1.6;\n  overflow-x: hidden;\n  -webkit-font-smoothing: antialiased;\n}\nimg  { max-width: 100%; display: block; }\na    { text-decoration: none; color: inherit; }\nbutton { cursor: pointer; border: none; outline: none; font-family: var(--font-b); }\nul   { list-style: none; }\n\n/* ===== SCROLLBAR ===== */\n::-webkit-scrollbar        { width: 3px; }\n::-webkit-scrollbar-track  { background: var(--bg); }\n::-webkit-scrollbar-thumb  { background: var(--lime); border-radius: 2px; }\n\n/* ===== LAYOUT ===== */\n.container {\n  max-width: 1160px;\n  margin: 0 auto;\n  padding: 0 24px;\n}\n.section     { padding: 96px 0; }\n.section-alt { background: var(--bg-s); border-top: 1px solid var(--border); border-bottom: 1px solid var(--border); }\n.desk-only   { display: inline-flex; }\n\n/* ===== TYPOGRAPHY HELPERS ===== */\n.sec-label {\n  font-size: 11px;\n  font-weight: 700;\n  letter-spacing: 4px;\n  text-transform: uppercase;\n  color: var(--lime);\n  display: flex;\n  align-items: center;\n  gap: 10px;\n  margin-bottom: 12px;\n}\n.sec-label::before {\n  content: \'\';\n  display: inline-block;\n  width: 28px; height: 2px;\n  background: var(--lime);\n}\n.sec-title {\n  font-family: var(--font-d);\n  font-size: clamp(36px, 5.5vw, 64px);\n  line-height: 1;\n  letter-spacing: 1px;\n  text-transform: uppercase;\n}\n.sec-title span { color: var(--lime); }\n.sec-sub {\n  font-size: 15px;\n  color: var(--grey);\n  max-width: 520px;\n  line-height: 1.75;\n  margin-top: 14px;\n}\n.lime-text { color: var(--lime); }\n\n/* ===== BUTTONS ===== */\n.btn-primary {\n  display: inline-flex;\n  align-items: center;\n  gap: 6px;\n  background: var(--lime);\n  color: #0A0A0A;\n  font-weight: 800;\n  font-size: 13px;\n  letter-spacing: 1px;\n  text-transform: uppercase;\n  padding: 13px 26px;\n  border-radius: 50px;\n  border: 2px solid var(--lime);\n  transition: var(--tr);\n  white-space: nowrap;\n}\n.btn-primary:hover {\n  background: transparent;\n  color: var(--lime);\n  box-shadow: 0 0 28px var(--lime-glow);\n  transform: translateY(-2px);\n}\n.btn-ghost {\n  display: inline-flex;\n  align-items: center;\n  gap: 6px;\n  background: transparent;\n  color: var(--white);\n  font-weight: 600;\n  font-size: 13px;\n  letter-spacing: 1px;\n  text-transform: uppercase;\n  padding: 13px 26px;\n  border-radius: 50px;\n  border: 2px solid var(--border);\n  transition: var(--tr);\n  white-space: nowrap;\n}\n.btn-ghost:hover {\n  border-color: var(--lime);\n  color: var(--lime);\n  transform: translateY(-2px);\n}\n.btn-lg  { padding: 16px 32px; font-size: 14px; }\n.btn-sm  { padding: 10px 20px; font-size: 12px; }\n\n/* ===== SCROLL ANIMATIONS ===== */\n.anim-up    { opacity: 0; transform: translateY(36px); transition: opacity .65s ease, transform .65s ease; transition-delay: var(--d, 0s); }\n.anim-left  { opacity: 0; transform: translateX(-36px); transition: opacity .7s ease, transform .7s ease; }\n.anim-right { opacity: 0; transform: translateX(36px); transition: opacity .7s ease, transform .7s ease; }\n.anim-up.vis, .anim-left.vis, .anim-right.vis { opacity: 1; transform: none; }\n\n/* ===== NAVBAR ===== */\n.navbar {\n  position: fixed;\n  top: 0; left: 0; right: 0;\n  z-index: 1000;\n  height: var(--nav-h);\n  display: flex;\n  align-items: center;\n  padding: 0 24px;\n  background: transparent;\n  transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);\n}\n.navbar-inner {\n  max-width: 1160px;\n  margin: 0 auto;\n  width: 100%;\n  display: grid;\n  grid-template-columns: 1.2fr 0.6fr 1.2fr;\n  align-items: center;\n  transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);\n}\n.navbar-links {\n  display: flex;\n  align-items: center;\n  gap: 18px;\n  justify-content: flex-start;\n}\n.navbar-links a {\n  font-size: 12px;\n  font-weight: 700;\n  letter-spacing: 1.5px;\n  text-transform: uppercase;\n  color: #CCCCCC;\n  transition: var(--tr);\n  position: relative;\n}\n.navbar-links a::after {\n  content: \'\';\n  position: absolute;\n  bottom: -4px; left: 0;\n  width: 0; height: 2px;\n  background: var(--lime);\n  transition: width .3s ease;\n}\n.navbar-links a:hover { color: var(--white); }\n.navbar-links a:hover::after { width: 100%; }\n\n.navbar-logo {\n  font-family: var(--font-d);\n  font-size: 52px;\n  letter-spacing: 3px;\n  display: flex;\n  align-items: center;\n  gap: 4px;\n  color: var(--white);\n  justify-self: center;\n}\n.navbar-logo span { color: #88D600; }\n.logo-bolt { font-size: 18px; margin-right: 2px; color: #88D600; }\n.nav-logo-img {\n  height: 84px;\n  width: auto;\n  margin-right: 14px;\n  display: block;\n}\n.footer-logo-img {\n  height: 76px;\n  width: auto;\n  margin-right: 14px;\n  display: block;\n}\n.drawer-logo-img {\n  height: 64px;\n  width: auto;\n  margin-right: 14px;\n  display: block;\n}\n\n.navbar-cta {\n  display: flex;\n  align-items: center;\n  gap: 14px;\n  justify-self: flex-end;\n}\n.nav-contact-btn {\n  background: transparent;\n  color: var(--white);\n  font-weight: 700;\n  font-size: 11px;\n  letter-spacing: 1.5px;\n  text-transform: uppercase;\n  padding: 10px 20px;\n  border-radius: 50px;\n  border: 2px solid var(--white);\n  transition: var(--tr);\n  white-space: nowrap;\n}\n.nav-contact-btn:hover {\n  background: var(--lime);\n  border-color: var(--lime);\n  color: #0A0A0A;\n}\n.nav-profile-icon {\n  width: 36px;\n  height: 36px;\n  border-radius: 50%;\n  border: 1.5px solid var(--white);\n  display: flex;\n  align-items: center;\n  justify-content: center;\n  color: var(--white);\n  transition: var(--tr);\n}\n.nav-profile-icon:hover {\n  background: var(--lime);\n  border-color: var(--lime);\n  color: #0A0A0A;\n}\n.nav-profile-icon svg {\n  width: 16px;\n  height: 16px;\n}\n\n.hamburger {\n  display: none;\n  flex-direction: column;\n  gap: 5px;\n  background: none;\n  padding: 6px;\n}\n.hamburger span {\n  display: block;\n  width: 22px; height: 2px;\n  background: var(--white);\n  border-radius: 2px;\n  transition: var(--tr);\n}\n.hamburger.open span:nth-child(1) { transform: translateY(7px) rotate(45deg); }\n.hamburger.open span:nth-child(2) { opacity: 0; }\n.hamburger.open span:nth-child(3) { transform: translateY(-7px) rotate(-45deg); }\n\n/* MOBILE MENU */\n.mobile-menu {\n  position: fixed;\n  top: var(--nav-h); left: 0; right: 0;\n  background: rgba(17, 17, 17, 0.97);\n  backdrop-filter: blur(20px);\n  -webkit-backdrop-filter: blur(20px);\n  padding: 20px 28px 32px;\n  z-index: 999;\n  transform: translateY(-110%);\n  transition: transform .38s cubic-bezier(.4,0,.2,1);\n  border-bottom: 1px solid rgba(255, 255, 255, 0.08);\n}\n.mobile-menu.open { transform: translateY(0); }\n.mobile-menu a {\n  display: block;\n  padding: 15px 0;\n  font-family: var(--font-d);\n  font-size: 28px;\n  letter-spacing: 2px;\n  color: var(--grey);\n  border-bottom: 1px solid rgba(255, 255, 255, 0.06);\n  transition: var(--tr);\n}\n.mobile-menu a:hover, .mobile-menu .mm-cta { color: var(--lime); }\n.mm-overlay {\n  display: none;\n  position: fixed;\n  inset: 0;\n  background: rgba(0,0,0,.6);\n  z-index: 998;\n}\n.mm-overlay.show { display: block; }\n\n/* ===== HERO ===== */\n.hero {\n  min-height: 100vh;\n  position: relative;\n  display: flex;\n  align-items: center;\n  padding-top: var(--nav-h);\n  overflow: hidden;\n}\n.hero-bg {\n  position: absolute;\n  inset: 0;\n  background: linear-gradient(135deg, #0A0A0A 0%, #0f0f0f 100%);\n}\n.hero-glow {\n  position: absolute;\n  border-radius: 50%;\n  filter: blur(80px);\n  pointer-events: none;\n}\n.hero-glow.g1 {\n  width: 600px; height: 400px;\n  top: 10%; right: 5%;\n  background: radial-gradient(ellipse, rgba(200,255,0,.08) 0%, transparent 70%);\n}\n.hero-glow.g2 {\n  width: 400px; height: 300px;\n  bottom: 10%; left: 5%;\n  background: radial-gradient(ellipse, rgba(255,107,53,.06) 0%, transparent 70%);\n}\n.hero-grid-bg {\n  position: absolute;\n  inset: 0;\n  background-image: linear-gradient(rgba(200,255,0,.025) 1px, transparent 1px),\n                    linear-gradient(90deg, rgba(200,255,0,.025) 1px, transparent 1px);\n  background-size: 56px 56px;\n}\n.hero-content {\n  position: relative;\n  z-index: 2;\n  display: grid;\n  grid-template-columns: 1fr 1fr;\n  gap: 64px;\n  align-items: center;\n  padding-top: 40px;\n  padding-bottom: 60px;\n  width: 100%;\n}\n.hero-badge {\n  display: inline-flex;\n  align-items: center;\n  gap: 8px;\n  background: var(--lime-dim);\n  border: 1px solid var(--border-l);\n  padding: 7px 16px;\n  border-radius: 50px;\n  font-size: 11px;\n  font-weight: 700;\n  letter-spacing: 2px;\n  text-transform: uppercase;\n  color: var(--lime);\n  margin-bottom: 22px;\n}\n.badge-dot {\n  width: 6px; height: 6px;\n  background: var(--lime);\n  border-radius: 50%;\n  animation: blink 2s ease-in-out infinite;\n}\n@keyframes blink {\n  0%,100% { opacity: 1; transform: scale(1); }\n  50%      { opacity: .4; transform: scale(.75); }\n}\n.hero-title {\n  font-family: var(--font-d);\n  font-size: clamp(58px, 9vw, 108px);\n  line-height: .92;\n  letter-spacing: 2px;\n  text-transform: uppercase;\n  margin-bottom: 22px;\n  display: flex;\n  flex-direction: column;\n}\n.hero-title span { display: block; }\n.ht-white   { color: var(--white); }\n.ht-lime    { color: var(--lime); }\n.ht-outline {\n  color: transparent;\n  -webkit-text-stroke: 2px var(--white);\n}\n.hero-desc {\n  font-size: 15px;\n  color: var(--grey);\n  line-height: 1.8;\n  max-width: 440px;\n  margin-bottom: 32px;\n}\n.hero-actions {\n  display: flex;\n  align-items: center;\n  gap: 14px;\n  flex-wrap: wrap;\n  margin-bottom: 44px;\n}\n.hero-stats {\n  display: flex;\n  align-items: center;\n  gap: 28px;\n}\n.hs { display: flex; flex-direction: column; }\n.hs-num {\n  font-family: var(--font-d);\n  font-size: 34px;\n  color: var(--lime);\n  line-height: 1;\n}\n.hs-lbl {\n  font-size: 11px;\n  letter-spacing: 1.5px;\n  text-transform: uppercase;\n  color: var(--muted);\n  margin-top: 3px;\n}\n.hs-div { width: 1px; height: 38px; background: var(--border); }\n\n/* Hero Card */\n.hero-visual {\n  position: relative;\n  display: flex;\n  align-items: center;\n  justify-content: center;\n  opacity: 0;\n  transform: translateY(24px);\n  transform-style: preserve-3d;\n  animation: heroVisIn .9s ease .4s forwards;\n}\n@keyframes heroVisIn {\n  to { opacity: 1; transform: none; }\n}\n.hero-mockup {\n  position: relative;\n  width: 100%;\n  max-width: 480px;\n  transform: perspective(800px) rotateY(-8deg) rotateX(4deg);\n  transition: transform 0.5s ease;\n  z-index: 1;\n}\n.hero-mockup:hover {\n  transform: perspective(800px) rotateY(0deg) rotateX(0deg);\n}\n.dashboard-img {\n  width: 100%;\n  height: auto;\n  border-radius: var(--r-xl);\n  box-shadow: 0 20px 48px rgba(0,0,0,0.6);\n  display: block;\n}\n\n/* Floating badges */\n.hero-float {\n  position: absolute;\n  background: var(--bg-c);\n  border: 1px solid var(--border);\n  border-radius: var(--r-md);\n  padding: 10px 14px;\n  display: flex;\n  align-items: center;\n  gap: 10px;\n  box-shadow: var(--shadow);\n  white-space: nowrap;\n  z-index: 2;\n}\n.hf-tr { top: -24px; right: -56px; animation: floatUD-tr 3s ease-in-out infinite; }\n.hf-bl { bottom: -24px; left: -56px; animation: floatUD-bl 3s ease-in-out infinite; }\n@keyframes floatUD-tr {\n  0%,100% { transform: translateY(0) translateZ(50px); }\n  50%      { transform: translateY(-7px) translateZ(50px); }\n}\n@keyframes floatUD-bl {\n  0%,100% { transform: translateY(0) translateZ(50px); }\n  50%      { transform: translateY(7px) translateZ(50px); }\n}\n.hf-ico {\n  width: 34px; height: 34px;\n  background: var(--lime-dim);\n  border-radius: 8px;\n  display: flex;\n  align-items: center;\n  justify-content: center;\n  font-size: 16px;\n  flex-shrink: 0;\n}\n.hf-text { display: flex; flex-direction: column; }\n.hf-text strong { font-size: 13px; font-weight: 700; }\n.hf-text span   { font-size: 11px; color: var(--muted); }\n\n/* Hero scroll hint */\n.hero-scroll {\n  position: absolute;\n  bottom: 28px; left: 50%;\n  transform: translateX(-50%);\n  display: flex;\n  flex-direction: column;\n  align-items: center;\n  gap: 8px;\n  z-index: 2;\n}\n.hero-scroll span { font-size: 10px; letter-spacing: 3px; text-transform: uppercase; color: var(--muted); }\n.hs-line {\n  width: 1px; height: 40px;\n  background: linear-gradient(to bottom, var(--lime), transparent);\n  animation: lineGrow 2s ease-in-out infinite;\n}\n@keyframes lineGrow {\n  0%,100% { transform: scaleY(1); opacity: 1; }\n  50%      { transform: scaleY(.5); opacity: .3; }\n}\n\n/* Hero text entrance */\n#heroText {\n  opacity: 0;\n  transform: translateY(28px);\n  animation: heroTextIn .8s ease .1s forwards;\n}\n@keyframes heroTextIn {\n  to { opacity: 1; transform: none; }\n}\n\n/* ===== MARQUEE ===== */\n.marquee-band {\n  overflow: hidden;\n  background: var(--bg-s);\n  border-top: 1px solid var(--border);\n  border-bottom: 1px solid var(--border);\n  padding: 18px 0;\n}\n.marquee-track {\n  display: flex;\n  gap: 56px;\n  animation: marquee 24s linear infinite;\n  white-space: nowrap;\n  width: max-content;\n}\n.marquee-track span {\n  font-family: var(--font-d);\n  font-size: 17px;\n  letter-spacing: 3px;\n  color: var(--muted);\n  flex-shrink: 0;\n}\n@keyframes marquee {\n  from { transform: translateX(0); }\n  to   { transform: translateX(-50%); }\n}\n\n/* ===== SECTION HEADER ===== */\n.sec-head {\n  display: flex;\n  justify-content: space-between;\n  align-items: flex-end;\n  margin-bottom: 44px;\n  gap: 20px;\n}\n.sec-head.center { flex-direction: column; align-items: center; text-align: center; margin-bottom: 50px; }\n\n/* ===== CLASSES GRID ===== */\n.classes-grid {\n  display: grid;\n  grid-template-columns: repeat(3, 1fr);\n  gap: 18px;\n}\n.cc {\n  background: var(--bg-c);\n  border: 1px solid var(--border);\n  border-radius: var(--r-lg);\n  padding: 32px 26px 26px;\n  position: relative;\n  overflow: hidden;\n  cursor: pointer;\n  transition: var(--tr);\n  display: flex;\n  flex-direction: column;\n  justify-content: flex-end;\n  min-height: 320px;\n}\n.cc-bg {\n  position: absolute;\n  inset: 0;\n  background-size: cover;\n  background-position: center;\n  opacity: 0.16;\n  transition: transform 0.8s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.4s ease;\n  z-index: 0;\n}\n.cc:hover .cc-bg {\n  transform: scale(1.08);\n  opacity: 0.38;\n}\n.cc-overlay {\n  position: absolute;\n  inset: 0;\n  background: linear-gradient(to top, rgba(10,10,10,0.96) 20%, rgba(10,10,10,0.5) 70%, transparent 100%);\n  z-index: 1;\n  transition: var(--tr);\n}\n.cc:hover .cc-overlay {\n  background: linear-gradient(to top, rgba(10,10,10,0.92) 20%, rgba(10,10,10,0.3) 75%, rgba(200,255,0,0.04) 100%);\n}\n.cc::before {\n  content: \'\';\n  position: absolute;\n  inset: 0;\n  background: linear-gradient(135deg, var(--lime-dim) 0%, transparent 70%);\n  opacity: 0;\n  transition: opacity .3s ease;\n  z-index: 2;\n}\n.cc:hover {\n  border-color: var(--border-l);\n  transform: translateY(-6px);\n  box-shadow: var(--shadow), 0 0 24px rgba(200,255,0,.08);\n}\n.cc:hover::before { opacity: 1; }\n.cc-icon {\n  width: 52px; height: 52px;\n  background: var(--lime-dim);\n  border-radius: var(--r-md);\n  display: flex; align-items: center; justify-content: center;\n  font-size: 24px;\n  margin-bottom: 18px;\n  transition: var(--tr);\n  position: relative; z-index: 3;\n}\n.cc:hover .cc-icon { background: var(--lime); }\n.cc-name {\n  font-family: var(--font-d);\n  font-size: 24px;\n  letter-spacing: 1px;\n  margin-bottom: 8px;\n  position: relative; z-index: 3;\n}\n.cc-desc {\n  font-size: 13px;\n  color: var(--grey);\n  line-height: 1.65;\n  margin-bottom: 18px;\n  position: relative; z-index: 3;\n}\n.cc-foot {\n  display: flex;\n  align-items: center;\n  gap: 10px;\n  position: relative; z-index: 3;\n}\n.cc-dur { font-size: 13px; color: var(--lime); font-weight: 700; margin-right: auto; }\n.cc-lvl {\n  font-size: 10px;\n  letter-spacing: 1px;\n  text-transform: uppercase;\n  color: var(--muted);\n  background: rgba(255,255,255,.05);\n  padding: 3px 10px;\n  border-radius: 50px;\n}\n.cc-arr {\n  width: 32px; height: 32px;\n  background: var(--lime);\n  border-radius: 50%;\n  display: flex; align-items: center; justify-content: center;\n  color: #0A0A0A;\n  font-size: 16px;\n  font-weight: 800;\n  transition: var(--tr);\n}\n.cc:hover .cc-arr { transform: rotate(45deg); }\n.cc-featured {\n  background: linear-gradient(135deg, #141a00 0%, #0e1200 100%);\n  border-color: var(--border-l);\n}\n\n/* ===== STATS BAND ===== */\n.stats-band {\n  background: var(--bg-s);\n  border-top: 1px solid var(--border);\n  border-bottom: 1px solid var(--border);\n  padding: 70px 0;\n}\n.stats-grid {\n  display: grid;\n  grid-template-columns: repeat(4, 1fr);\n  gap: 1px;\n  background: var(--border);\n}\n.si {\n  background: var(--bg-s);\n  padding: 40px 28px;\n  text-align: center;\n  position: relative;\n  overflow: hidden;\n  transition: var(--tr);\n}\n.si::before {\n  content: \'\';\n  position: absolute;\n  inset: 0;\n  background: var(--lime-dim);\n  opacity: 0;\n  transition: opacity .3s;\n}\n.si:hover::before { opacity: 1; }\n.si-num {\n  font-family: var(--font-d);\n  font-size: 58px;\n  color: var(--lime);\n  line-height: 1;\n  margin-bottom: 8px;\n  position: relative; z-index: 1;\n}\n.si-lbl {\n  font-size: 12px;\n  color: var(--grey);\n  letter-spacing: 2px;\n  text-transform: uppercase;\n  position: relative; z-index: 1;\n}\n\n/* ===== ABOUT ===== */\n.about-grid {\n  display: grid;\n  grid-template-columns: 1fr 1fr;\n  gap: 72px;\n  align-items: center;\n}\n.about-left { position: relative; }\n.about-main-card {\n  background: linear-gradient(135deg, #171700 0%, #101000 100%);\n  border: 1px solid var(--border-l);\n  border-radius: var(--r-xl);\n  padding: 36px;\n  position: relative;\n  overflow: hidden;\n}\n.amc-glow {\n  position: absolute;\n  top: -30%; left: -20%;\n  width: 240px; height: 240px;\n  background: radial-gradient(circle, rgba(200,255,0,.08) 0%, transparent 70%);\n  pointer-events: none;\n}\n.amc-quote {\n  font-family: var(--font-d);\n  font-size: clamp(26px, 3.5vw, 36px);\n  line-height: 1.1;\n  letter-spacing: 1px;\n  margin-bottom: 18px;\n  position: relative; z-index: 1;\n}\n.amc-quote span { color: var(--lime); }\n.amc-author {\n  font-size: 11px;\n  color: var(--muted);\n  letter-spacing: 2.5px;\n  text-transform: uppercase;\n  position: relative; z-index: 1;\n}\n.about-side-card {\n  position: absolute;\n  bottom: -22px; right: -22px;\n  background: var(--bg-c);\n  border: 1px solid var(--border-l);\n  border-radius: var(--r-lg);\n  padding: 18px 22px;\n  box-shadow: var(--shadow);\n}\n.asc-val {\n  font-family: var(--font-d);\n  font-size: 38px;\n  color: var(--lime);\n  line-height: 1;\n}\n.asc-lbl {\n  font-size: 11px;\n  color: var(--muted);\n  letter-spacing: 1.5px;\n  text-transform: uppercase;\n  margin-top: 4px;\n}\n.about-feats {\n  display: flex;\n  flex-direction: column;\n  gap: 14px;\n  margin-top: 32px;\n}\n.af {\n  display: flex;\n  align-items: flex-start;\n  gap: 14px;\n  padding: 14px 16px;\n  background: var(--bg-c);\n  border: 1px solid var(--border);\n  border-radius: var(--r-md);\n  transition: var(--tr);\n}\n.af:hover { border-color: var(--border-l); transform: translateX(5px); }\n.af-ico {\n  width: 40px; height: 40px;\n  background: var(--lime-dim);\n  border-radius: 9px;\n  display: flex; align-items: center; justify-content: center;\n  font-size: 18px;\n  flex-shrink: 0;\n}\n.af b   { display: block; font-size: 14px; font-weight: 700; margin-bottom: 3px; }\n.af p   { font-size: 13px; color: var(--grey); line-height: 1.5; margin: 0; }\n\n/* ===== TRAINERS ===== */\n.trainers-grid {\n  display: grid;\n  grid-template-columns: repeat(3, 1fr);\n  gap: 22px;\n}\n.tc {\n  background: var(--bg-c);\n  border: 1px solid var(--border);\n  border-radius: var(--r-xl);\n  overflow: hidden;\n  transition: var(--tr);\n  cursor: pointer;\n}\n.tc:hover { border-color: var(--border-l); transform: translateY(-7px); box-shadow: var(--shadow), 0 0 36px rgba(200,255,0,.08); }\n.tc-img {\n  height: 280px;\n  background: linear-gradient(160deg, #1a2200 0%, #0f0f0f 100%);\n  position: relative;\n  overflow: hidden;\n}\n.tc-img img {\n  width: 100%;\n  height: 100%;\n  object-fit: cover;\n  object-position: center 15%;\n  transition: transform 0.6s cubic-bezier(0.4, 0, 0.2, 1);\n}\n.tc:hover .tc-img img {\n  transform: scale(1.06);\n}\n.tc-ov {\n  position: absolute;\n  inset: 0;\n  background: linear-gradient(to top, rgba(10,10,10,.85) 0%, rgba(10,10,10,.25) 50%, transparent 100%);\n  z-index: 1;\n}\n.tc-tags {\n  position: absolute;\n  bottom: 14px; left: 14px;\n  display: flex; gap: 6px; flex-wrap: wrap;\n  z-index: 2;\n}\n.tc-tags span {\n  background: rgba(200,255,0,.2);\n  border: 1px solid rgba(200,255,0,.35);\n  color: var(--lime);\n  font-size: 10px;\n  font-weight: 700;\n  letter-spacing: 1px;\n  text-transform: uppercase;\n  padding: 3px 8px;\n  border-radius: 50px;\n}\n.tc-body { padding: 18px 22px 22px; }\n.tc-name { font-family: var(--font-d); font-size: 22px; letter-spacing: 1px; margin-bottom: 3px; }\n.tc-role { font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 1px; margin-bottom: 14px; }\n.tc-stats { display: flex; gap: 18px; }\n.tc-stats span { font-size: 13px; color: var(--grey); }\n.tc-stats b { color: var(--lime); }\n\n/* ===== SCHEDULE ===== */\n.sched-tabs {\n  display: flex;\n  gap: 8px;\n  margin-bottom: 24px;\n  overflow-x: auto;\n  scrollbar-width: none;\n  padding-bottom: 2px;\n}\n.sched-tabs::-webkit-scrollbar { display: none; }\n.sched-tab {\n  padding: 9px 20px;\n  border-radius: 50px;\n  font-size: 13px;\n  font-weight: 600;\n  letter-spacing: 1px;\n  white-space: nowrap;\n  cursor: pointer;\n  transition: var(--tr);\n  background: var(--bg-c);\n  border: 1px solid var(--border);\n  color: var(--grey);\n}\n.sched-tab.active {\n  background: var(--lime);\n  color: #0A0A0A;\n  border-color: var(--lime);\n}\n.sched-list { display: flex; flex-direction: column; gap: 10px; }\n.sched-item {\n  display: flex;\n  align-items: center;\n  gap: 18px;\n  background: var(--bg-c);\n  border: 1px solid var(--border);\n  border-radius: var(--r-md);\n  padding: 16px 22px;\n  transition: var(--tr);\n  cursor: pointer;\n}\n.sched-item:hover { border-color: var(--border-l); background: var(--bg-ch); }\n.sched-time { font-family: var(--font-d); font-size: 18px; color: var(--lime); min-width: 72px; }\n.sched-div  { width: 1px; height: 36px; background: var(--border); }\n.sched-info { flex: 1; }\n.sched-name { font-weight: 700; font-size: 14px; margin-bottom: 2px; }\n.sched-trainer { font-size: 12px; color: var(--muted); }\n.sched-spots { font-size: 12px; color: var(--lime); font-weight: 600; white-space: nowrap; }\n.sched-btn {\n  padding: 7px 14px;\n  background: var(--lime-dim);\n  border: 1px solid var(--border-l);\n  border-radius: 50px;\n  font-size: 11px;\n  font-weight: 700;\n  color: var(--lime);\n  transition: var(--tr);\n  white-space: nowrap;\n}\n.sched-btn:hover { background: var(--lime); color: #0A0A0A; }\n\n/* ===== PRICING ===== */\n.pricing-grid {\n  display: grid;\n  grid-template-columns: repeat(3, 1fr);\n  gap: 20px;\n  margin-top: 50px;\n}\n.pc {\n  background: var(--bg-c);\n  border: 1px solid var(--border);\n  border-radius: var(--r-xl);\n  padding: 32px;\n  position: relative;\n  overflow: hidden;\n  transition: var(--tr);\n}\n.pc:hover:not(.pc-pop) { border-color: var(--border-l); transform: translateY(-5px); }\n.pc-pop {\n  background: linear-gradient(150deg, #131a00 0%, #0c1100 100%);\n  border-color: var(--lime);\n  transform: scale(1.035);\n  box-shadow: 0 0 40px rgba(200,255,0,.12);\n}\n.pc-badge {\n  position: absolute;\n  top: 18px; right: 18px;\n  background: var(--lime);\n  color: #0A0A0A;\n  font-size: 10px;\n  font-weight: 800;\n  letter-spacing: 1px;\n  text-transform: uppercase;\n  padding: 3px 10px;\n  border-radius: 50px;\n}\n.pc-tier { font-size: 11px; font-weight: 700; letter-spacing: 3px; text-transform: uppercase; color: var(--muted); margin-bottom: 14px; }\n.pc-price { display: flex; align-items: baseline; gap: 2px; margin-bottom: 4px; }\n.pc-cur { font-size: 18px; font-weight: 700; color: var(--lime); }\n.pc-amt { font-family: var(--font-d); font-size: 58px; line-height: 1; }\n.pc-per { font-size: 13px; color: var(--muted); }\n.pc-desc { font-size: 13px; color: var(--grey); margin-bottom: 22px; padding-bottom: 22px; border-bottom: 1px solid var(--border); line-height: 1.6; }\n.pc-feats { display: flex; flex-direction: column; gap: 10px; margin-bottom: 24px; }\n.pf {\n  font-size: 13px;\n  color: var(--grey);\n  display: flex;\n  align-items: center;\n  gap: 10px;\n}\n.pf::before {\n  content: \'✓\';\n  width: 18px; height: 18px;\n  background: var(--lime-dim);\n  border-radius: 50%;\n  display: flex; align-items: center; justify-content: center;\n  color: var(--lime);\n  font-size: 10px;\n  font-weight: 800;\n  flex-shrink: 0;\n}\n.pf.no { color: var(--muted); }\n.pf.no::before {\n  content: \'✗\';\n  background: rgba(255,255,255,.04);\n  color: var(--muted);\n}\n.pc-btn {\n  width: 100%;\n  padding: 13px;\n  border-radius: 50px;\n  font-weight: 700;\n  font-size: 13px;\n  letter-spacing: 1px;\n  text-transform: uppercase;\n  transition: var(--tr);\n}\n.pc-btn.solid { background: var(--lime); color: #0A0A0A; border: 2px solid var(--lime); }\n.pc-btn.solid:hover { background: transparent; color: var(--lime); }\n.pc-btn.ghost { background: transparent; color: var(--white); border: 2px solid var(--border); }\n.pc-btn.ghost:hover { border-color: var(--lime); color: var(--lime); }\n\n/* ===== TESTIMONIALS ===== */\n.testi-wrap { overflow: hidden; }\n.testi-track {\n  display: flex;\n  gap: 20px;\n  transition: transform .5s cubic-bezier(.4,0,.2,1);\n}\n.testi-card {\n  background: var(--bg-c);\n  border: 1px solid var(--border);\n  border-radius: var(--r-xl);\n  padding: 28px;\n  flex: 0 0 calc(33.333% - 14px);\n  transition: var(--tr);\n}\n.testi-card:hover { border-color: var(--border-l); }\n.testi-stars { color: var(--lime); font-size: 15px; letter-spacing: 2px; margin-bottom: 16px; }\n.testi-card blockquote {\n  font-size: 14px;\n  color: var(--grey);\n  line-height: 1.75;\n  margin-bottom: 22px;\n  font-style: italic;\n  quotes: "\\201C" "\\201D";\n  position: relative;\n  padding-left: 22px;\n}\n.testi-card blockquote::before {\n  content: \'"\';\n  font-family: var(--font-d);\n  font-size: 52px;\n  color: var(--lime);\n  line-height: .5;\n  position: absolute;\n  left: 0; top: 8px;\n  font-style: normal;\n}\n.testi-author {\n  display: flex;\n  align-items: center;\n  gap: 12px;\n}\n.ta-ava {\n  width: 44px; height: 44px;\n  border-radius: 50%;\n  background: var(--bg-s);\n  border: 2px solid var(--border-l);\n  display: flex; align-items: center; justify-content: center;\n  font-size: 20px;\n  flex-shrink: 0;\n}\n.testi-author b    { display: block; font-size: 14px; }\n.testi-author span { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 1px; }\n.testi-dots {\n  display: flex;\n  justify-content: center;\n  gap: 10px;\n  margin-top: 28px;\n}\n.td {\n  width: 8px; height: 8px;\n  border-radius: 50%;\n  background: var(--muted);\n  cursor: pointer;\n  transition: var(--tr);\n  border: none;\n}\n.td.active { width: 24px; border-radius: 4px; background: var(--lime); }\n\n/* ===== CTA ===== */\n.cta-box {\n  background: linear-gradient(140deg, #101a00 0%, #0a0a0a 50%, #0d0010 100%);\n  border: 1px solid var(--border);\n  border-radius: var(--r-xl);\n  padding: 72px 56px;\n  text-align: center;\n  position: relative;\n  overflow: hidden;\n}\n.cta-glow {\n  position: absolute;\n  top: -40%; left: 50%;\n  transform: translateX(-50%);\n  width: 500px; height: 300px;\n  background: radial-gradient(ellipse, rgba(200,255,0,.12) 0%, transparent 70%);\n  pointer-events: none;\n}\n.cta-grid-bg {\n  position: absolute;\n  inset: 0;\n  background-image: linear-gradient(rgba(200,255,0,.025) 1px, transparent 1px),\n                    linear-gradient(90deg, rgba(200,255,0,.025) 1px, transparent 1px);\n  background-size: 38px 38px;\n}\n.cta-inner { position: relative; z-index: 1; }\n.cta-title {\n  font-family: var(--font-d);\n  font-size: clamp(36px, 5.5vw, 62px);\n  line-height: 1;\n  letter-spacing: 2px;\n  text-transform: uppercase;\n  margin-bottom: 18px;\n}\n.cta-title span { color: var(--lime); }\n.cta-desc {\n  font-size: 15px;\n  color: var(--grey);\n  max-width: 460px;\n  margin: 0 auto 30px;\n  line-height: 1.7;\n}\n.cta-form {\n  display: flex;\n  gap: 10px;\n  max-width: 440px;\n  margin: 0 auto;\n}\n.cta-input {\n  flex: 1;\n  background: rgba(255,255,255,.06);\n  border: 1px solid var(--border);\n  border-radius: 50px;\n  padding: 14px 20px;\n  font-family: var(--font-b);\n  font-size: 14px;\n  color: var(--white);\n  outline: none;\n  transition: var(--tr);\n}\n.cta-input::placeholder { color: var(--muted); }\n.cta-input:focus { border-color: var(--lime); background: rgba(200,255,0,.05); }\n.cta-fine { font-size: 12px; color: var(--muted); margin-top: 14px; }\n\n/* ===== FOOTER ===== */\n.footer { padding: 72px 0 36px; border-top: 1px solid var(--border); }\n.footer-grid {\n  display: grid;\n  grid-template-columns: 2fr 1fr 1fr 1fr;\n  gap: 52px;\n  margin-bottom: 52px;\n}\n.fb p { font-size: 13px; color: var(--grey); line-height: 1.7; margin-top: 8px; max-width: 260px; }\n.fb-socials { display: flex; gap: 8px; margin-top: 20px; }\n.soc {\n  width: 36px; height: 36px;\n  background: var(--bg-c);\n  border: 1px solid var(--border);\n  border-radius: 9px;\n  display: flex; align-items: center; justify-content: center;\n  font-size: 11px;\n  font-weight: 700;\n  text-transform: uppercase;\n  transition: var(--tr);\n  color: var(--grey);\n}\n.soc:hover { background: var(--lime-dim); border-color: var(--border-l); color: var(--lime); transform: translateY(-2px); }\n.ft { font-size: 11px; font-weight: 700; letter-spacing: 2.5px; text-transform: uppercase; color: var(--white); margin-bottom: 18px; }\n.fl { display: flex; flex-direction: column; gap: 10px; }\n.fl a { font-size: 13px; color: var(--grey); transition: var(--tr); display: inline-block; }\n.fl a:hover { color: var(--lime); transform: translateX(4px); }\n.footer-bottom {\n  display: flex;\n  justify-content: space-between;\n  align-items: center;\n  padding-top: 28px;\n  border-top: 1px solid var(--border);\n  font-size: 12px;\n  color: var(--muted);\n}\n.footer-bottom div { display: flex; gap: 22px; }\n.footer-bottom a { color: var(--muted); transition: var(--tr); }\n.footer-bottom a:hover { color: var(--lime); }\n\n/* ===== BOTTOM NAV ===== */\n.bottom-nav {\n  display: none;\n  position: fixed;\n  bottom: 0; left: 0; right: 0;\n  z-index: 990;\n  background: rgba(17,17,17,.97);\n  backdrop-filter: blur(18px);\n  -webkit-backdrop-filter: blur(18px);\n  border-top: 1px solid var(--border);\n  padding: 8px 10px 0;\n  /* Pushes content above system nav bar on both Android & iOS */\n  padding-bottom: max(16px, env(safe-area-inset-bottom, 16px));\n}\n.bottom-nav > * {\n  display: flex;\n  flex-direction: row;\n  justify-content: space-around;\n  align-items: center;\n  width: 100%;\n}\n.bn {\n  display: flex;\n  flex-direction: column;\n  align-items: center;\n  justify-content: center;\n  gap: 3px;\n  padding: 7px 10px;\n  border-radius: 12px;\n  background: none;\n  border: none;\n  color: var(--muted);\n  transition: var(--tr);\n  -webkit-tap-highlight-color: transparent;\n  flex: 1;\n}\n.bn > span:first-child { font-size: 20px; line-height: 1; }\n.bn > span:last-child  { font-size: 9px; letter-spacing: .5px; text-transform: uppercase; font-weight: 600; }\n.bn.active { background: var(--lime-dim); color: var(--lime); }\n\n/* ===== SCROLL-TO-TOP ===== */\n.scroll-top {\n  position: fixed;\n  bottom: 88px; right: 22px;\n  width: 44px; height: 44px;\n  background: var(--lime);\n  color: #0A0A0A;\n  border-radius: 50%;\n  display: flex; align-items: center; justify-content: center;\n  font-size: 18px;\n  font-weight: 800;\n  z-index: 900;\n  opacity: 0;\n  transform: translateY(16px);\n  transition: var(--tr);\n  box-shadow: 0 4px 18px rgba(200,255,0,.3);\n  border: none;\n}\n.scroll-top.vis { opacity: 1; transform: translateY(0); }\n.scroll-top:hover { transform: translateY(-3px); }\n\n/* ===== GALLERY ===== */\n.gallery-grid {\n  display: grid;\n  grid-template-columns: repeat(3, 1fr);\n  grid-auto-rows: 260px;\n  gap: 18px;\n}\n.gallery-item {\n  position: relative;\n  overflow: hidden;\n  border-radius: var(--r-lg);\n  border: 1px solid var(--border);\n  cursor: pointer;\n  background: var(--bg-c);\n}\n.gallery-item.tall {\n  grid-row: span 2;\n}\n.gallery-item img {\n  width: 100%;\n  height: 100%;\n  object-fit: cover;\n  transition: transform 0.8s cubic-bezier(0.4, 0, 0.2, 1);\n}\n.gallery-item:hover img {\n  transform: scale(1.08);\n}\n.gi-overlay {\n  position: absolute;\n  inset: 0;\n  background: linear-gradient(to top, rgba(10,10,10,0.92) 0%, rgba(10,10,10,0.3) 60%, transparent 100%);\n  display: flex;\n  align-items: flex-end;\n  padding: 24px;\n  opacity: 0;\n  transition: opacity 0.3s ease;\n  z-index: 1;\n}\n.gallery-item:hover .gi-overlay {\n  opacity: 1;\n}\n.gi-content {\n  transform: translateY(14px);\n  transition: transform 0.45s cubic-bezier(0.4, 0, 0.2, 1);\n  width: 100%;\n}\n.gallery-item:hover .gi-content {\n  transform: translateY(0);\n}\n.gi-tag {\n  display: inline-block;\n  background: var(--lime);\n  color: #0A0A0A;\n  font-size: 10px;\n  font-weight: 800;\n  text-transform: uppercase;\n  letter-spacing: 1px;\n  padding: 2px 8px;\n  border-radius: 4px;\n  margin-bottom: 8px;\n}\n.gi-title {\n  font-family: var(--font-d);\n  font-size: 22px;\n  letter-spacing: 1px;\n  line-height: 1.1;\n  text-transform: uppercase;\n}\n\n/* ===== RESPONSIVE ===== */\n@media (max-width: 1024px) {\n  .classes-grid  { grid-template-columns: repeat(2, 1fr); }\n  .stats-grid    { grid-template-columns: repeat(2, 1fr); }\n  .gallery-grid  { grid-template-columns: repeat(2, 1fr); }\n  .footer-grid   { grid-template-columns: 1fr 1fr; gap: 36px; }\n}\n\n@media (max-width: 768px) {\n  :root { --nav-h: 60px; }\n  .section { padding: 64px 0; }\n\n  /* Nav */\n  .navbar-inner {\n    display: flex !important;\n    justify-content: space-between !important;\n    align-items: center !important;\n  }\n  .navbar-links, .navbar-cta { display: none !important; }\n  .hamburger { display: flex !important; }\n  .navbar.scrolled {\n    background: rgba(10, 10, 10, 0.95) !important;\n    border-bottom: 1px solid rgba(255, 255, 255, 0.08) !important;\n  }\n\n  /* Hero */\n  .hero-content {\n    grid-template-columns: 1fr;\n    gap: 36px;\n    padding-top: 28px;\n    padding-bottom: 90px;\n  }\n  .hero-text { text-align: center; }\n  .hero-badge { justify-content: center; display: inline-flex; }\n  .hero-desc  { margin-left: auto; margin-right: auto; }\n  .hero-actions { justify-content: center; }\n  .hero-stats   { justify-content: center; }\n  .hero-visual  { justify-content: center; }\n  .hf-tr, .hf-bl { display: none; }\n  .hero-card { max-width: 100%; }\n  .hero-scroll { display: none; }\n\n  /* ===== SECTION GLOBAL ===== */\n  .section { padding: 64px 0; }\n  .sec-head { flex-direction: column; align-items: flex-start; gap: 16px; }\n  .sec-head.center { align-items: center; text-align: center; }\n  .sec-title { font-size: clamp(32px, 8vw, 52px); }\n  .sec-sub { font-size: 14px; }\n  .desk-only { display: none; }\n\n  /* ===== CLASSES ===== */\n  .classes-grid {\n    grid-template-columns: 1fr;\n    gap: 16px;\n  }\n  .cc { height: 260px; }\n  .cc-featured { height: 300px; }\n\n  /* ===== STATS BAND ===== */\n  .stats-grid { grid-template-columns: 1fr 1fr; gap: 24px; }\n  .si-num { font-size: 44px; }\n\n  /* ===== ABOUT ===== */\n  .about-grid {\n    grid-template-columns: 1fr;\n    gap: 40px;\n  }\n  .about-left { order: 2; }\n  .about-right { order: 1; }\n  .about-main-card { padding: 32px 24px; }\n  .amc-quote { font-size: 20px; }\n  .about-side-card {\n    position: static;\n    margin-top: 14px;\n    display: inline-block;\n  }\n  .about-feats { gap: 20px; }\n  .af { gap: 12px; }\n\n  /* ===== TRAINERS ===== */\n  .trainers-grid {\n    grid-template-columns: 1fr;\n    gap: 20px;\n  }\n  .tc-img { height: 280px; }\n  .tc-body { padding: 16px 20px; }\n  .tc-name { font-size: 18px; }\n\n  /* ===== SCHEDULE ===== */\n  .sched-tabs {\n    display: flex;\n    flex-wrap: wrap;\n    gap: 8px;\n    justify-content: center;\n    margin-bottom: 24px;\n  }\n  .sched-tab {\n    padding: 8px 16px;\n    font-size: 13px;\n    flex: 1 1 calc(25% - 8px);\n    min-width: 60px;\n    text-align: center;\n  }\n  .sched-item {\n    flex-direction: column;\n    align-items: flex-start;\n    gap: 8px;\n    padding: 16px 18px;\n  }\n  .si-time { font-size: 13px; width: auto; }\n  .si-info { gap: 4px; }\n  .si-name { font-size: 15px; }\n  .si-trainer { font-size: 12px; }\n  .si-badge { align-self: flex-start; font-size: 11px; }\n\n  /* ===== GALLERY ===== */\n  .gallery-grid {\n    grid-template-columns: 1fr 1fr;\n    grid-auto-rows: 200px;\n    gap: 12px;\n  }\n  .gallery-item.tall { grid-row: span 1; }\n  .gi-overlay { opacity: 1; }\n  .gi-content { transform: translateY(0); }\n  .gi-title { font-size: 14px; }\n  .gi-tag { font-size: 10px; padding: 3px 8px; }\n\n  /* ===== PRICING ===== */\n  .pricing-grid {\n    grid-template-columns: 1fr;\n    gap: 20px;\n    max-width: 480px;\n    margin: 0 auto;\n  }\n  .pc { padding: 32px 24px; }\n  .pc-pop { transform: scale(1); }\n  .pc-amt { font-size: 52px; }\n  .pc-name { font-size: 18px; }\n\n  /* ===== TESTIMONIALS ===== */\n  .testi-card { flex: 0 0 100%; }\n\n  /* ===== CTA ===== */\n  .cta-box  { padding: 52px 24px; }\n  .cta-form { flex-direction: column; }\n  .cta-title { font-size: 34px; }\n\n  /* ===== FOOTER ===== */\n  .footer-grid { grid-template-columns: 1fr; gap: 16px; }\n  .footer-grid > div {\n    border-bottom: 1px solid rgba(255, 255, 255, 0.06);\n    padding-bottom: 12px;\n  }\n  .footer-grid > div:last-child {\n    border-bottom: none;\n  }\n  .footer-grid .ft {\n    display: flex;\n    justify-content: space-between;\n    align-items: center;\n    cursor: pointer;\n    margin-bottom: 0 !important;\n    padding: 8px 0;\n  }\n  .footer-grid .ft::after {\n    content: \'+\';\n    font-size: 18px;\n    color: var(--lime);\n    transition: transform 0.3s ease;\n  }\n  .footer-grid .ft.active::after {\n    content: \'−\';\n    transform: rotate(180deg);\n  }\n  .footer-grid .fl {\n    max-height: 0;\n    overflow: hidden;\n    transition: max-height 0.3s ease-out;\n    margin-top: 0;\n  }\n  .footer-grid .ft.active + .fl {\n    max-height: 300px;\n    margin-top: 12px;\n  }\n  .footer-bottom { flex-direction: column; gap: 10px; text-align: center; }\n\n  /* ===== BOTTOM NAV ===== */\n  .bottom-nav { display: block; }\n  body { padding-bottom: var(--bn-h); }\n  .scroll-top { bottom: calc(var(--bn-h) + 12px); }\n}\n\n/* ===== TABLET (641px – 768px) ===== */\n@media (min-width: 641px) and (max-width: 768px) {\n  .classes-grid   { display: grid !important; grid-template-columns: 1fr 1fr; gap: 16px; }\n  .cc             { flex: unset !important; height: 280px !important; }\n  .cc-featured    { grid-column: span 2; height: 300px !important; }\n  .trainers-grid  { display: grid !important; grid-template-columns: 1fr 1fr; gap: 20px; }\n  .tc             { flex: unset !important; }\n  .gallery-grid   { display: grid !important; grid-template-columns: 1fr 1fr; grid-auto-rows: 220px; gap: 14px; }\n  .gallery-item   { flex: unset !important; height: unset !important; }\n  .gallery-item.tall { grid-row: span 2; }\n  .pricing-grid   { display: grid !important; grid-template-columns: 1fr 1fr; gap: 20px; max-width: 100% !important; width: auto !important; margin: 0 !important; }\n  .pc             { flex: unset !important; transform: none; }\n  .pc-pop         { transform: scale(1.02); }\n  .stats-grid     { grid-template-columns: repeat(4, 1fr); }\n  .sched-tab      { flex: 1 1 auto; }\n  .about-grid     { grid-template-columns: 1fr 1fr; gap: 32px; }\n  .about-left     { order: 1; }\n  .about-right    { order: 2; }\n}\n\n@media (max-width: 640px) {\n  /* ── Typography adjustments ─────────────────────── */\n  .hero-title  { font-size: 42px; }\n  .si-num      { font-size: 40px; }\n  .pc-amt      { font-size: 44px; }\n  .cta-title   { font-size: 30px; }\n  .sec-title   { font-size: 32px; }\n  .container   { padding: 0 16px; }\n  .gallery-item.tall { grid-row: span 1; }\n  .sched-tab   { flex: 1 1 calc(33% - 8px); }\n\n  /* ── Parent section: allow horizontal bleed for carousels ─ */\n  #classes .container,\n  #trainers .container,\n  #gallery .container,\n  #pricing .container {\n    overflow: visible !important;\n  }\n\n  /* ── SHARED CAROUSEL WRAPPER ─────────────────────── */\n  .classes-grid,\n  .trainers-grid,\n  .gallery-grid,\n  .pricing-grid {\n    display: flex !important;\n    flex-direction: row !important;\n    flex-wrap: nowrap !important;\n    overflow-x: auto !important;\n    overflow-y: visible !important;\n    scroll-snap-type: x mandatory !important;\n    scroll-behavior: smooth !important;\n    -webkit-overflow-scrolling: touch !important;\n    gap: 14px !important;\n    padding: 8px 16px 24px !important;\n    margin: 0 -16px !important;\n    width: calc(100% + 32px) !important;\n    max-width: unset !important;\n    grid-template-columns: unset !important;\n    align-items: stretch !important;\n    box-sizing: border-box !important;\n  }\n\n  /* Hide scrollbar on all carousels */\n  .classes-grid::-webkit-scrollbar,\n  .trainers-grid::-webkit-scrollbar,\n  .gallery-grid::-webkit-scrollbar,\n  .pricing-grid::-webkit-scrollbar {\n    display: none !important;\n  }\n\n  /* ── CLASSES CAROUSEL ────────────────────────────── */\n  .cc {\n    flex: 0 0 78vw !important;\n    width: 78vw !important;\n    max-width: 280px !important;\n    height: 300px !important;\n    min-height: unset !important;\n    scroll-snap-align: start !important;\n    border-radius: 16px !important;\n    overflow: hidden !important;\n  }\n  .cc-featured {\n    flex: 0 0 85vw !important;\n    width: 85vw !important;\n    max-width: 310px !important;\n    height: 300px !important;\n  }\n  .cc-bg   { height: 100% !important; }\n  .cc-overlay { border-radius: 0 !important; }\n\n  /* ── TRAINERS CAROUSEL ───────────────────────────── */\n  .tc {\n    flex: 0 0 72vw !important;\n    width: 72vw !important;\n    max-width: 280px !important;\n    min-width: unset !important;\n    scroll-snap-align: start !important;\n    overflow: hidden !important;\n    border-radius: 16px !important;\n  }\n  .tc-img-wrap { height: 200px !important; }\n  .tc-info     { padding: 16px !important; }\n\n  /* ── GALLERY (FACILITY) CAROUSEL ─────────────────── */\n  .gallery-item {\n    flex: 0 0 80vw !important;\n    width: 80vw !important;\n    max-width: 300px !important;\n    height: 240px !important;\n    min-height: unset !important;\n    scroll-snap-align: start !important;\n    border-radius: 14px !important;\n    overflow: hidden !important;\n  }\n  .gallery-item img {\n    width: 100% !important;\n    height: 100% !important;\n    object-fit: cover !important;\n    display: block !important;\n  }\n\n  /* ── PRICING CAROUSEL ────────────────────────────── */\n  .pricing-grid {\n    align-items: flex-start !important;\n    padding-bottom: 28px !important;\n  }\n  .pc {\n    flex: 0 0 82vw !important;\n    width: 82vw !important;\n    max-width: 300px !important;\n    scroll-snap-align: start !important;\n    padding: 24px 20px !important;\n    transform: none !important;\n    border-radius: 18px !important;\n    box-shadow: 0 4px 24px rgba(0,0,0,0.3) !important;\n  }\n  .pc-pop {\n    transform: none !important;\n    border-width: 2px !important;\n  }\n  .pc-amt { font-size: 44px !important; }\n}\n\n/* ===== TOAST NOTIFICATION ===== */\n.toast {\n  position: fixed;\n  top: calc(var(--nav-h) + 12px);\n  right: 20px;\n  background: var(--bg-c);\n  border: 1px solid var(--border-l);\n  border-radius: var(--r-md);\n  padding: 14px 20px;\n  font-size: 14px;\n  box-shadow: var(--shadow);\n  z-index: 2000;\n  transform: translateX(110%);\n  transition: transform .35s cubic-bezier(.34,1.56,.64,1);\n  max-width: 280px;\n}\n.toast.show { transform: translateX(0); }\n.toast-icon { margin-right: 6px; }\n\n/* ===== SPLIT SCREEN HERO (DESKTOP) ===== */\n@media (min-width: 769px) {\n  /* Mobile-only elements must be completely hidden on desktop */\n  .mobile-menu,\n  .mm-overlay,\n  .hamburger {\n    display: none !important;\n  }\n\n  .hero {\n    display: flex;\n    align-items: stretch;\n    min-height: 100vh;\n    padding-top: var(--nav-h);\n  }\n  .hero-content {\n    max-width: 100% !important;\n    width: 100%;\n    padding: 0 !important;\n    display: grid !important;\n    grid-template-columns: 1.15fr 0.85fr;\n    gap: 0 !important;\n    align-items: stretch;\n  }\n  .hero-text {\n    padding-left: max(24px, calc((100vw - 1160px) / 2 + 24px));\n    padding-right: 80px;\n    padding-top: 80px;\n    padding-bottom: 80px;\n    display: flex;\n    flex-direction: column;\n    justify-content: center;\n  }\n  .hero-visual {\n    height: 100%;\n    width: 100%;\n    min-height: 100vh;\n    padding: 0;\n    margin: 0;\n  }\n  .hero-mockup {\n    width: 100%;\n    height: 100%;\n    max-width: 100%;\n    transform: none !important;\n    border: none;\n    border-radius: 0;\n    padding: 0;\n    box-shadow: none;\n  }\n  .dashboard-img {\n    width: 100%;\n    height: 100%;\n    object-fit: cover;\n    border-radius: 0;\n    box-shadow: none;\n  }\n  .hf-tr {\n    top: 40px;\n    right: 40px;\n  }\n  .hf-bl {\n    bottom: 40px;\n    left: 40px;\n  }\n\n\n  /* ALWAYS: .navbar is a transparent shell, positioned to center the capsule */\n  .navbar {\n    top: 0;\n    left: 0;\n    right: 0;\n    transform: none;\n    width: 100%;\n    height: var(--nav-h);\n    background: transparent !important;\n    backdrop-filter: none !important;\n    -webkit-backdrop-filter: none !important;\n    border: none !important;\n    box-shadow: none !important;\n    border-radius: 0 !important;\n    padding: 0 24px;\n    display: flex;\n    align-items: center;\n    justify-content: center;\n  }\n\n  /* BEFORE SCROLL: .navbar-inner is a floating dark glass capsule */\n  .navbar-inner {\n    width: 100%;\n    max-width: 1100px;\n    height: 72px;\n    margin: 0 auto;\n    padding: 0 32px;\n    background: rgba(17, 17, 17, 0.82);\n    backdrop-filter: blur(14px);\n    -webkit-backdrop-filter: blur(14px);\n    border-radius: 50px;\n    border: 1px solid rgba(255, 255, 255, 0.08);\n    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);\n    display: grid;\n    grid-template-columns: 1.2fr 0.6fr 1.2fr;\n    align-items: center;\n  }\n\n  /* AFTER SCROLL: capsule gets lime border glow */\n  .navbar.scrolled .navbar-inner {\n    background: rgba(17, 17, 17, 0.95);\n    backdrop-filter: blur(20px);\n    -webkit-backdrop-filter: blur(20px);\n    border: 1px solid rgba(136, 214, 0, 0.45);\n    box-shadow: 0 16px 40px rgba(0,0,0,0.7), 0 0 16px rgba(136,214,0,0.12);\n  }\n}\n\n/* ===== PROFILE DRAWER ===== */\n.profile-drawer {\n  position: fixed;\n  top: 0; right: 0; bottom: 0;\n  width: 100%;\n  max-width: 380px;\n  background: rgba(17, 17, 17, 0.95);\n  backdrop-filter: blur(24px);\n  -webkit-backdrop-filter: blur(24px);\n  border-left: 1px solid var(--border);\n  box-shadow: -10px 0 40px rgba(0, 0, 0, 0.7);\n  z-index: 2000;\n  transform: translateX(110%);\n  transition: transform 0.4s cubic-bezier(0.4, 0, 0.2, 1);\n  display: flex;\n  flex-direction: column;\n}\n.profile-drawer.open {\n  transform: translateX(0);\n}\n.pd-header {\n  padding: 24px;\n  border-bottom: 1px solid var(--border);\n  display: flex;\n  align-items: center;\n  justify-content: space-between;\n}\n.pd-header h3 {\n  font-family: var(--font-d);\n  font-size: 24px;\n  letter-spacing: 1px;\n  text-transform: uppercase;\n  color: var(--white);\n}\n.pd-close {\n  background: none;\n  border: none;\n  font-size: 32px;\n  color: var(--grey);\n  cursor: pointer;\n  transition: var(--tr);\n  line-height: 1;\n}\n.pd-close:hover {\n  color: var(--lime);\n}\n.pd-body {\n  flex: 1;\n  padding: 24px;\n  overflow-y: auto;\n  display: flex;\n  flex-direction: column;\n  gap: 24px;\n}\n.pd-user-info {\n  display: flex;\n  align-items: center;\n  gap: 16px;\n}\n.pd-avatar {\n  width: 56px;\n  height: 56px;\n  border-radius: 50%;\n  background: var(--lime-dim);\n  border: 2px solid var(--border-l);\n  color: var(--lime);\n  display: flex;\n  align-items: center;\n  justify-content: center;\n  font-weight: 800;\n  font-size: 18px;\n}\n.pd-name {\n  font-size: 16px;\n  font-weight: 700;\n  color: var(--white);\n}\n.pd-badge {\n  display: inline-block;\n  font-size: 10px;\n  font-weight: 700;\n  text-transform: uppercase;\n  letter-spacing: 1px;\n  color: var(--lime);\n  background: rgba(200, 255, 0, 0.1);\n  padding: 2px 8px;\n  border-radius: 4px;\n  margin-top: 2px;\n}\n.pd-stats-card {\n  background: var(--bg-c);\n  border: 1px solid var(--border);\n  border-radius: var(--r-md);\n  padding: 20px;\n}\n.pd-stats-row {\n  display: grid;\n  grid-template-columns: repeat(3, 1fr);\n  text-align: center;\n  gap: 10px;\n  padding-bottom: 18px;\n  border-bottom: 1px solid var(--border);\n}\n.pd-stat-lbl {\n  font-size: 10px;\n  color: var(--muted);\n  text-transform: uppercase;\n  letter-spacing: 1px;\n}\n.pd-stat-val {\n  font-family: var(--font-d);\n  font-size: 22px;\n  color: var(--lime);\n  margin-top: 4px;\n}\n.pd-barcode-zone {\n  padding-top: 18px;\n  text-align: center;\n}\n.pd-barcode {\n  display: flex;\n  align-items: stretch;\n  justify-content: center;\n  height: 38px;\n  gap: 2px;\n  background: #FFF;\n  padding: 6px 12px;\n  border-radius: 4px;\n  margin-bottom: 6px;\n}\n.pd-bar-line {\n  background: #000;\n}\n.pd-barcode-num {\n  font-family: monospace;\n  font-size: 11px;\n  color: var(--grey);\n  letter-spacing: 1.5px;\n}\n.pd-menu {\n  display: flex;\n  flex-direction: column;\n  gap: 4px;\n}\n.pd-menu-title {\n  font-size: 11px;\n  font-weight: 700;\n  text-transform: uppercase;\n  color: var(--muted);\n  letter-spacing: 1.5px;\n  margin-bottom: 8px;\n}\n.pd-menu a {\n  padding: 12px 16px;\n  background: var(--bg-c);\n  border: 1px solid var(--border);\n  border-radius: var(--r-sm);\n  font-size: 13px;\n  color: var(--grey);\n  display: flex;\n  align-items: center;\n  transition: var(--tr);\n}\n.pd-menu a:hover {\n  border-color: var(--border-l);\n  color: var(--lime);\n  transform: translateX(4px);\n}\n.pd-logout-btn {\n  margin-top: auto;\n  width: 100%;\n  padding: 12px;\n  background: rgba(255, 107, 53, 0.1);\n  border: 1px solid rgba(255, 107, 53, 0.2);\n  border-radius: var(--r-sm);\n  color: var(--orange);\n  font-weight: 700;\n  text-transform: uppercase;\n  letter-spacing: 1px;\n  font-size: 12px;\n  transition: var(--tr);\n}\n.pd-logout-btn:hover {\n  background: var(--orange);\n  color: #FFFFFF;\n}\n.pd-overlay {\n  position: fixed;\n  inset: 0;\n  background: rgba(0, 0, 0, 0.5);\n  backdrop-filter: blur(4px);\n  -webkit-backdrop-filter: blur(4px);\n  z-index: 1999;\n  opacity: 0;\n  pointer-events: none;\n  transition: opacity 0.3s ease;\n}\n.pd-overlay.show {\n  opacity: 1;\n  pointer-events: auto;\n}\n\n\n\n'

    part_mid = f"""  </style>
</head>
<body>

  <!-- NAVBAR -->
  <nav class="navbar" id="navbar">
    <div class="navbar-inner">
      <ul class="navbar-links">
        <li><a href="#classes">Classes</a></li>
        <li><a href="#about">About</a></li>
        <li><a href="#trainers">Trainers</a></li>
        <li><a href="#schedule">Schedule</a></li>
        <li><a href="#gallery">Gallery</a></li>
        <li><a href="#pricing">Pricing</a></li>
      </ul>

      <a href="#home" class="navbar-logo">
        <img src="{_CDN}logo-emblem-dark.png" alt="{name} Logo" class="nav-logo-img">
        {name}
      </a>

      <div class="navbar-cta">
        <a href="#contact" class="nav-contact-btn">Contact Us</a>
        <a href="javascript:void(0)" onclick="openProfileDrawer(event)" class="nav-profile-icon" aria-label="Profile">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>
        </a>
      </div>

      <button class="hamburger" id="hamburger" aria-label="Menu">
        <span></span><span></span><span></span>
      </button>
    </div>
  </nav>

  <!-- MOBILE MENU -->
  <div class="mobile-menu" id="mobileMenu">
    <a href="#classes"  onclick="closeMobileMenu()">Classes</a>
    <a href="#about"    onclick="closeMobileMenu()">About Us</a>
    <a href="#trainers" onclick="closeMobileMenu()">Trainers</a>
    <a href="#schedule" onclick="closeMobileMenu()">Schedule</a>
    <a href="#gallery"  onclick="closeMobileMenu()">Gallery</a>
    <a href="#pricing"  onclick="closeMobileMenu()">Pricing</a>
    <a href="#contact"  onclick="closeMobileMenu()" class="mm-cta">Join Now Free &#8594;</a>
  </div>
  <div class="mm-overlay" id="mmOverlay" onclick="closeMobileMenu()"></div>

  <!-- HERO -->
  <section class="hero" id="home">
    <div class="hero-bg">
      <div class="hero-glow g1"></div>
      <div class="hero-glow g2"></div>
      <div class="hero-grid-bg"></div>
    </div>
    <div class="hero-content container">
      <div class="hero-text" id="heroText">
        <div class="hero-badge">
          <span class="badge-dot"></span>
          Now Open &middot; 5AM &ndash; 11PM Daily
        </div>
        <h1 class="hero-title">
          <span class="ht-white">STRONGER</span>
          <span class="ht-lime">EVERY</span>
          <span class="ht-outline">DAY</span>
          <span class="ht-white">FITTER</span>
        </h1>
        <p class="hero-desc">
          Where fitness meets inspiration. Every drop of sweat tells a story of determination.
          Join our members who chose {name} to transform their bodies and lives.
        </p>
        <div class="hero-actions">
          <a href="#pricing" class="btn-primary btn-lg">Start Today &#8594;</a>
          <a href="#about"   class="btn-ghost btn-lg">&#9654; How It Works</a>
        </div>
        <div class="hero-stats">
          <div class="hs">
            <span class="hs-num" data-count="1200" data-suffix="+">0</span>
            <span class="hs-lbl">Members</span>
          </div>
          <div class="hs-div"></div>
          <div class="hs">
            <span class="hs-num" data-count="10" data-suffix="+">0</span>
            <span class="hs-lbl">Trainers</span>
          </div>
          <div class="hs-div"></div>
          <div class="hs">
            <span class="hs-num" data-count="{int(float(rating_str)*10) if rating else 50}" data-suffix="">0</span>
            <span class="hs-lbl">★ Google Rating</span>
          </div>
        </div>
      </div>

      <div class="hero-visual" id="heroVisual">
        <div class="hero-mockup">
          <img src="{_CDN}gym-full.png" alt="{name} Facility" class="dashboard-img">
        </div>
      </div>
    </div>
    <div class="hero-scroll">
      <span>Scroll</span>
      <div class="hs-line"></div>
    </div>
  </section>

  <!-- MARQUEE -->
  <div class="marquee-band" aria-hidden="true">
    <div class="marquee-track">
      <span>&#128170; STRENGTH TRAINING</span><span>&#9889; HIIT CARDIO</span>
      <span>&#129336; YOGA &amp; MINDFULNESS</span><span>&#129354; COMBAT SPORTS</span>
      <span>&#128692; CYCLING STUDIO</span><span>&#128100; PERSONAL COACHING</span>
      <span>&#129367; NUTRITION PLANS</span><span>&#128705; RECOVERY ZONE</span>
      <span>&#128170; STRENGTH TRAINING</span><span>&#9889; HIIT CARDIO</span>
      <span>&#129336; YOGA &amp; MINDFULNESS</span><span>&#129354; COMBAT SPORTS</span>
      <span>&#128692; CYCLING STUDIO</span><span>&#128100; PERSONAL COACHING</span>
      <span>&#129367; NUTRITION PLANS</span><span>&#128705; RECOVERY ZONE</span>
    </div>
  </div>

  <!-- CLASSES -->
  <section class="section" id="classes">
    <div class="container">
      <div class="sec-head anim-up">
        <div>
          <div class="sec-label">What We Offer</div>
          <h2 class="sec-title">OUR <span>CLASSES</span></h2>
          <p class="sec-sub">Find your perfect class &mdash; from high-intensity cardio to mindful recovery.</p>
        </div>
        <a href="#schedule" class="btn-ghost btn-sm desk-only">View Schedule &#8594;</a>
      </div>
      <div class="classes-grid">
        <div class="cc anim-up" style="--d:.05s">
          <div class="cc-bg" style="background-image: url('{_CDN}athlete.png');"></div>
          <div class="cc-overlay"></div>
          <div class="cc-icon">&#127947;&#65039;</div>
          <div class="cc-name">Strength &amp; Power</div>
          <div class="cc-desc">Build raw strength with compound lifting using free weights and machines.</div>
          <div class="cc-foot"><span class="cc-dur">60 min</span><span class="cc-lvl">All Levels</span><span class="cc-arr">&#8594;</span></div>
        </div>
        <div class="cc anim-up" style="--d:.10s">
          <div class="cc-bg" style="background-image: url('{_CDN}hiit.png');"></div>
          <div class="cc-overlay"></div>
          <div class="cc-icon">&#9889;</div>
          <div class="cc-name">HIIT Cardio</div>
          <div class="cc-desc">Torch calories and elevate your metabolism for 24+ hours post-workout.</div>
          <div class="cc-foot"><span class="cc-dur">45 min</span><span class="cc-lvl">Intermediate</span><span class="cc-arr">&#8594;</span></div>
        </div>
        <div class="cc cc-featured anim-up" style="--d:.15s">
          <div class="cc-bg" style="background-image: url('{_CDN}boxing.png');"></div>
          <div class="cc-overlay"></div>
          <div class="cc-icon">&#129354;</div>
          <div class="cc-name">Combat HIIT</div>
          <div class="cc-desc">Boxing fused with HIIT cardio &mdash; sharpen reflexes while burning serious fat.</div>
          <div class="cc-foot"><span class="cc-dur">50 min</span><span class="cc-lvl">Advanced</span><span class="cc-arr">&#8594;</span></div>
        </div>
        <div class="cc anim-up" style="--d:.20s">
          <div class="cc-bg" style="background-image: url('{_CDN}yoga.png');"></div>
          <div class="cc-overlay"></div>
          <div class="cc-icon">&#129336;</div>
          <div class="cc-name">Yoga &amp; Flow</div>
          <div class="cc-desc">Restore mobility and build core strength with dynamic yoga sessions.</div>
          <div class="cc-foot"><span class="cc-dur">60 min</span><span class="cc-lvl">Beginner</span><span class="cc-arr">&#8594;</span></div>
        </div>
        <div class="cc anim-up" style="--d:.25s">
          <div class="cc-bg" style="background-image: url('{_CDN}spin.png');"></div>
          <div class="cc-overlay"></div>
          <div class="cc-icon">&#128692;</div>
          <div class="cc-name">Spin Studio</div>
          <div class="cc-desc">Indoor cycling with immersive music &amp; LED lighting. Burn 600+ calories.</div>
          <div class="cc-foot"><span class="cc-dur">45 min</span><span class="cc-lvl">All Levels</span><span class="cc-arr">&#8594;</span></div>
        </div>
        <div class="cc anim-up" style="--d:.30s">
          <div class="cc-bg" style="background-image: url('{_CDN}interior.png');"></div>
          <div class="cc-overlay"></div>
          <div class="cc-icon">&#127939;</div>
          <div class="cc-name">Functional Fit</div>
          <div class="cc-desc">Train movements not muscles. Improve performance with athletic drills.</div>
          <div class="cc-foot"><span class="cc-dur">55 min</span><span class="cc-lvl">All Levels</span><span class="cc-arr">&#8594;</span></div>
        </div>
      </div>
    </div>
  </section>

  <!-- STATS -->
  <div class="stats-band">
    <div class="container">
      <div class="stats-grid">
        <div class="si anim-up" style="--d:.00s"><div class="si-num" data-count="1200" data-suffix="+">0</div><div class="si-lbl">Active Members</div></div>
        <div class="si anim-up" style="--d:.08s"><div class="si-num" data-count="10"   data-suffix="+">0</div><div class="si-lbl">Expert Trainers</div></div>
        <div class="si anim-up" style="--d:.16s"><div class="si-num" data-count="98"   data-suffix="%">0</div><div class="si-lbl">Satisfaction Rate</div></div>
        <div class="si anim-up" style="--d:.24s"><div class="si-num" data-count="30"   data-suffix="+">0</div><div class="si-lbl">Weekly Classes</div></div>
      </div>
    </div>
  </div>

  <!-- ABOUT -->
  <section class="section" id="about">
    <div class="container">
      <div class="about-grid">
        <div class="about-left anim-left">
          <div class="about-main-card">
            <div class="amc-quote">&ldquo;Built for those who choose<br><span>POWER</span>, Purpose &amp; Progress.&rdquo;</div>
            <div class="amc-author">&mdash; {name.upper()} PHILOSOPHY</div>
            <div class="amc-glow"></div>
          </div>
          <div class="about-side-card">
            <div class="asc-val">10+</div>
            <div class="asc-lbl">Years of Excellence</div>
          </div>
        </div>
        <div class="about-right anim-right">
          <div class="sec-label">Who We Are</div>
          <h2 class="sec-title">ELEVATE YOUR<br><span>FITNESS</span> JOURNEY</h2>
          <p class="sec-sub">{about_text}</p>
          <div class="about-feats">
            <div class="af"><div class="af-ico">&#9881;&#65039;</div><div><b>Cutting-Edge Equipment</b><p>Premium machines and free weights for every muscle group.</p></div></div>
            <div class="af"><div class="af-ico">&#128101;</div><div><b>Expert Guidance</b><p>Certified coaches with proven methods to accelerate your results.</p></div></div>
            <div class="af"><div class="af-ico">&#127775;</div><div><b>Atmosphere &amp; Community</b><p>A motivating environment where every member feels supported.</p></div></div>
            <div class="af"><div class="af-ico">&#128336;</div><div><b>Flexible Hours</b><p>Open 5AM&ndash;11PM daily. Your schedule never stops your fitness.</p></div></div>
          </div>
        </div>
      </div>
    </div>
  </section>

  <!-- TRAINERS -->
  <section class="section section-alt" id="trainers">
    <div class="container">
      <div class="sec-head center anim-up">
        <div class="sec-label" style="justify-content:center">Meet The Team</div>
        <h2 class="sec-title">OUR <span>EXPERT</span> TRAINERS</h2>
        <p class="sec-sub" style="max-width:500px;margin:12px auto 0">Certified professionals who bring passion and personalized attention to every session.</p>
      </div>
      <div class="trainers-grid">
        <div class="tc anim-up" style="--d:.05s">
          <div class="tc-img">
            <img src="{_CDN}athlete.png" alt="Head Strength Coach">
            <div class="tc-ov"></div>
            <div class="tc-tags"><span>Strength</span><span>Powerlifting</span></div>
          </div>
          <div class="tc-body"><div class="tc-name">MARCUS REEVES</div><div class="tc-role">Head Strength Coach</div><div class="tc-stats"><span><b>8yr</b> Exp.</span><span><b>200+</b> Clients</span><span><b>4.9&#9733;</b></span></div></div>
        </div>
        <div class="tc anim-up" style="--d:.15s">
          <div class="tc-img">
            <img src="{_CDN}hiit.png" alt="HIIT Specialist">
            <div class="tc-ov"></div>
            <div class="tc-tags"><span>HIIT</span><span>Cardio</span></div>
          </div>
          <div class="tc-body"><div class="tc-name">SARAH CHEN</div><div class="tc-role">HIIT &amp; Cardio Specialist</div><div class="tc-stats"><span><b>6yr</b> Exp.</span><span><b>180+</b> Clients</span><span><b>4.8&#9733;</b></span></div></div>
        </div>
        <div class="tc anim-up" style="--d:.25s">
          <div class="tc-img">
            <img src="{_CDN}boxing.png" alt="Combat Sports Coach">
            <div class="tc-ov"></div>
            <div class="tc-tags"><span>Boxing</span><span>MMA</span></div>
          </div>
          <div class="tc-body"><div class="tc-name">DEREK STONE</div><div class="tc-role">Combat Sports Coach</div><div class="tc-stats"><span><b>10yr</b> Exp.</span><span><b>150+</b> Clients</span><span><b>5.0&#9733;</b></span></div></div>
        </div>
      </div>
    </div>
  </section>

  <!-- SCHEDULE -->
  <section class="section" id="schedule">
    <div class="container">
      <div class="sec-head anim-up">
        <div>
          <div class="sec-label">Book Your Session</div>
          <h2 class="sec-title">WEEKLY <span>SCHEDULE</span></h2>
          <p class="sec-sub">Reserve your spot. Classes fill fast &mdash; don&#8217;t miss out.</p>
        </div>
      </div>
      <div class="sched-tabs" id="schedTabs">
        <button class="sched-tab active" data-day="mon">Mon</button>
        <button class="sched-tab" data-day="tue">Tue</button>
        <button class="sched-tab" data-day="wed">Wed</button>
        <button class="sched-tab" data-day="thu">Thu</button>
        <button class="sched-tab" data-day="fri">Fri</button>
        <button class="sched-tab" data-day="sat">Sat</button>
        <button class="sched-tab" data-day="sun">Sun</button>
      </div>
      <div class="sched-list anim-up" id="schedList"></div>
    </div>
  </section>

  <!-- GALLERY -->
  <section class="section section-alt" id="gallery">
    <div class="container">
      <div class="sec-head center anim-up">
        <div class="sec-label" style="justify-content:center">Virtual Tour</div>
        <h2 class="sec-title">OUR <span>FACILITY</span></h2>
        <p class="sec-sub" style="max-width:500px;margin:12px auto 0">Take a virtual tour of our premium spaces, top-of-the-line equipment, and dynamic fitness studios.</p>
      </div>
      <div class="gallery-grid">
        <div class="gallery-item anim-up tall" style="--d:.05s">
          <img src="{_CDN}interior.png" alt="{name} Weight Room">
          <div class="gi-overlay"><div class="gi-content"><span class="gi-tag">Strength Zone</span><h3 class="gi-title">Main Weight Floor</h3></div></div>
        </div>
        <div class="gallery-item anim-up" style="--d:.10s">
          <img src="{_CDN}athlete.png" alt="Athlete Training">
          <div class="gi-overlay"><div class="gi-content"><span class="gi-tag">Coaching</span><h3 class="gi-title">Personal Training Zone</h3></div></div>
        </div>
        <div class="gallery-item anim-up" style="--d:.15s">
          <img src="{_CDN}boxing.png" alt="Boxing training">
          <div class="gi-overlay"><div class="gi-content"><span class="gi-tag">Combat Studio</span><h3 class="gi-title">Heavy Bag Arena</h3></div></div>
        </div>
        <div class="gallery-item anim-up" style="--d:.20s">
          <img src="{_CDN}yoga.png" alt="Yoga Class">
          <div class="gi-overlay"><div class="gi-content"><span class="gi-tag">Mindfulness</span><h3 class="gi-title">Zen Yoga Studio</h3></div></div>
        </div>
        <div class="gallery-item anim-up tall" style="--d:.25s">
          <img src="{_CDN}spin.png" alt="Spin Studio">
          <div class="gi-overlay"><div class="gi-content"><span class="gi-tag">Cycling</span><h3 class="gi-title">Velo Spin Theater</h3></div></div>
        </div>
        <div class="gallery-item anim-up" style="--d:.30s">
          <img src="{_CDN}hiit.png" alt="HIIT Class">
          <div class="gi-overlay"><div class="gi-content"><span class="gi-tag">HIIT Studio</span><h3 class="gi-title">Group Circuit Arena</h3></div></div>
        </div>
      </div>
    </div>
  </section>

  <!-- PRICING -->
  <section class="section section-alt" id="pricing">
    <div class="container">
      <div class="sec-head center anim-up">
        <div class="sec-label" style="justify-content:center">Simple Pricing</div>
        <h2 class="sec-title">CHOOSE YOUR <span>PLAN</span></h2>
        <p class="sec-sub" style="max-width:460px;margin:12px auto 0">No hidden fees. Cancel anytime. Start your transformation today.</p>
      </div>
      <div class="pricing-grid">
        <div class="pc anim-up" style="--d:.05s">
          <div class="pc-tier">Daily Pass</div>
          <div class="pc-price"><span class="pc-cur">$</span><span class="pc-amt" data-count="12">12</span><span class="pc-per">/day</span></div>
          <div class="pc-desc">Perfect for visitors or occasional training with no commitment.</div>
          <div class="pc-feats">
            <div class="pf yes">Full gym access</div>
            <div class="pf yes">Locker rooms &amp; showers</div>
            <div class="pf yes">1 Group class</div>
            <div class="pf no">Personal trainer session</div>
            <div class="pf no">Nutrition consultation</div>
          </div>
          <button class="pc-btn ghost" onclick="selectPlan('Daily Pass')">Get Day Pass</button>
        </div>
        <div class="pc pc-pop anim-up" style="--d:.15s">
          <div class="pc-badge">Most Popular</div>
          <div class="pc-tier">Monthly</div>
          <div class="pc-price"><span class="pc-cur">$</span><span class="pc-amt" data-count="89">89</span><span class="pc-per">/month</span></div>
          <div class="pc-desc">Our most popular plan. Unlimited access to transform your fitness.</div>
          <div class="pc-feats">
            <div class="pf yes">Unlimited gym access</div>
            <div class="pf yes">All group classes</div>
            <div class="pf yes">2 PT sessions/month</div>
            <div class="pf yes">Nutrition plan access</div>
            <div class="pf no">Private coaching</div>
          </div>
          <button class="pc-btn solid" onclick="selectPlan('Monthly')">Start Monthly</button>
        </div>
        <div class="pc anim-up" style="--d:.25s">
          <div class="pc-tier">Yearly Elite</div>
          <div class="pc-price"><span class="pc-cur">$</span><span class="pc-amt" data-count="799">799</span><span class="pc-per">/year</span></div>
          <div class="pc-desc">Best value for serious athletes. Save $270+ vs monthly billing.</div>
          <div class="pc-feats">
            <div class="pf yes">Everything in Monthly</div>
            <div class="pf yes">Weekly PT sessions</div>
            <div class="pf yes">Private coaching</div>
            <div class="pf yes">Body composition scans</div>
            <div class="pf yes">Priority class booking</div>
          </div>
          <button class="pc-btn ghost" onclick="selectPlan('Yearly Elite')">Go Elite &#8594;</button>
        </div>
      </div>
    </div>
  </section>

  <!-- TESTIMONIALS -->
  <section class="section" id="testimonials">
    <div class="container">
      <div class="sec-head anim-up">
        <div>
          <div class="sec-label">Real Results</div>
          <h2 class="sec-title">FROM OUR <span>MEMBERS</span></h2>
        </div>
      </div>
      <div class="testi-wrap">
        <div class="testi-track" id="testiTrack">
"""

    part_testimonials = testi_cards_html

    part_after_testi = f"""        </div>
      </div>
      <div class="testi-dots" id="testiDots">
        <button class="td active" data-i="0"></button>
        <button class="td" data-i="1"></button>
        <button class="td" data-i="2"></button>
      </div>
    </div>
  </section>

  <!-- CTA / CONTACT -->
  <section class="section" id="contact">
    <div class="container">
      <div class="cta-box anim-up">
        <div class="cta-glow"></div>
        <div class="cta-grid-bg"></div>
        <div class="cta-inner">
          <div class="sec-label" style="justify-content:center;margin-bottom:14px">Join The Movement</div>
          <h2 class="cta-title">LET&#8217;S BUILD YOUR<br><span>BEST SELF</span></h2>
          <p class="cta-desc">Get your free first session and see why members choose {name}. No commitment required.</p>
          <form class="cta-form" onsubmit="handleCTA(event)">
            <input type="email" class="cta-input" id="ctaEmail" placeholder="Enter your email address" required>
            <button type="submit" class="btn-primary btn-lg">Get Started &#8594;</button>
          </form>
          <p class="cta-fine">Free first session &middot; No credit card &middot; Cancel anytime</p>
        </div>
      </div>
    </div>
  </section>

  <!-- FOOTER -->
  <footer class="footer" id="footer">
    <div class="container">
      <div class="footer-grid">
        <div class="fb">
          <div class="navbar-logo" style="font-size:22px;margin-bottom:12px;color:#FFFFFF;display:flex;align-items:center;">
            <img src="{_CDN}logo-emblem-dark.png" alt="{name} Logo" class="footer-logo-img">
            {name}
          </div>
          <p>Join our community of dedicated athletes. Transform your body. Transform your life.</p>
          <div class="fb-socials">
            <a href="{'https://instagram.com/' + instagram.lstrip('@') if instagram else '#'}" class="soc" aria-label="Instagram" {"target=_blank rel=noopener" if instagram else ""}>
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="20" height="20" rx="5" ry="5"></rect><path d="M16 11.37A4 4 0 1 1 12.63 8 4 4 0 0 1 16 11.37z"></path><line x1="17.5" y1="6.5" x2="17.51" y2="6.5"></line></svg>
            </a>
            <a href="{website if website else '#'}" class="soc" aria-label="Website" {"target=_blank rel=noopener" if website else ""}>
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="2" y1="12" x2="22" y2="12"></line><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path></svg>
            </a>
            <a href="{maps_url if maps_url else '#'}" class="soc" aria-label="Google Maps" {"target=_blank rel=noopener" if maps_url else ""}>
              <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5c-1.38 0-2.5-1.12-2.5-2.5s1.12-2.5 2.5-2.5 2.5 1.12 2.5 2.5-1.12 2.5-2.5 2.5z"/></svg>
            </a>
          </div>
        </div>
        <div>
          <div class="ft">Quick Links</div>
          <ul class="fl"><li><a href="#home">Home</a></li><li><a href="#classes">Classes</a></li><li><a href="#about">About Us</a></li><li><a href="#trainers">Trainers</a></li><li><a href="#schedule">Schedule</a></li></ul>
        </div>
        <div>
          <div class="ft">Programs</div>
          <ul class="fl"><li><a href="#classes">Strength Training</a></li><li><a href="#classes">HIIT Cardio</a></li><li><a href="#classes">Yoga &amp; Flow</a></li><li><a href="#classes">Combat HIIT</a></li><li><a href="#classes">Personal Training</a></li></ul>
        </div>
        <div>
          <div class="ft">Contact</div>
          <ul class="fl">
            <li><a href="{maps_url if maps_url else '#'}" {"target=_blank rel=noopener" if maps_url else ""}>{address_line}</a></li>
            {'<li><a href="tel:' + phone + '">' + phone_line + '</a></li>' if phone else ''}
            {'<li><a href="mailto:' + email + '">' + email_line + '</a></li>' if email else ''}
            <li><a href="#">&#128336; Mon&ndash;Sun: 5AM&ndash;11PM</a></li>
          </ul>
        </div>
      </div>
      <div class="footer-bottom">
        <span>&copy; 2025 {name}. All Rights Reserved.</span>
        <div><a href="#">Privacy Policy</a><a href="#">Terms</a></div>
      </div>
    </div>
  </footer>

  <!-- MOBILE BOTTOM NAV -->
  <nav class="bottom-nav" id="bottomNav">
    <div style="display:flex;justify-content:space-around;align-items:center;width:100%">
      <button class="bn active" id="bn-home"     onclick="bnNav(this,'#home')">
        <span>&#127968;</span><span>Home</span>
      </button>
      <button class="bn"        id="bn-classes"  onclick="bnNav(this,'#classes')">
        <span>&#127947;&#65039;</span><span>Classes</span>
      </button>
      <button class="bn"        id="bn-schedule" onclick="bnNav(this,'#schedule')">
        <span>&#128197;</span><span>Schedule</span>
      </button>
      <button class="bn"        id="bn-pricing"  onclick="bnNav(this,'#pricing')">
        <span>&#128179;</span><span>Plans</span>
      </button>
      <button class="bn"        id="bn-contact"  onclick="bnNav(this,'#contact')">
        <span>&#128100;</span><span>Join</span>
      </button>
    </div>
  </nav>

  <!-- SCROLL TO TOP -->
  <button class="scroll-top" id="scrollTop" onclick="window.scrollTo({{top:0,behavior:'smooth'}})">&#8593;</button>

  <!-- PROFILE DRAWER -->
  <div class="profile-drawer" id="profileDrawer">
    <div class="pd-header">
      <div class="navbar-logo" style="font-size:18px;color:#FFFFFF;display:flex;align-items:center;">
        <img src="{_CDN}logo-emblem-dark.png" alt="{name} Logo" class="drawer-logo-img">
        {name}
      </div>
      <button class="pd-close" onclick="closeProfileDrawer()">&#215;</button>
    </div>
    <div class="pd-body">
      <div class="pd-user-info">
        <div class="pd-avatar">{''.join(c for c in name.upper() if c.isalpha())[:2]}</div>
        <div>
          <h4 class="pd-name">{name}</h4>
          <span class="pd-badge">Elite Member</span>
        </div>
      </div>
      <div class="pd-menu">
        <div class="pd-menu-title">Quick Actions</div>
        <a href="#contact" onclick="closeProfileDrawer()">&#128197; Book a Free Session</a>
        <a href="#classes" onclick="closeProfileDrawer()">&#127947;&#65039; View Classes</a>
        <a href="#pricing" onclick="closeProfileDrawer()">&#128179; Membership Plans</a>
        <a href="#schedule" onclick="closeProfileDrawer()">&#128336; Weekly Schedule</a>
      </div>
    </div>
  </div>
  <div class="pd-overlay" id="pdOverlay" onclick="closeProfileDrawer()"></div>

  {pixel_html}

  <script>
"""

    part_js = '/* =====================================================\n   APEX GYM — app.js\n   ===================================================== */\n\n\'use strict\';\n\n/* ===== SCHEDULE DATA ===== */\nconst SCHEDULE = {\n  mon: [\n    { time:\'06:00\', name:\'Power Surge HIIT\',       trainer:\'Sarah Chen\',    spots:\'4 spots left\' },\n    { time:\'08:00\', name:\'Strength Foundations\',   trainer:\'Marcus Reeves\', spots:\'8 spots left\' },\n    { time:\'10:00\', name:\'Yoga Flow\',              trainer:\'Anya Patel\',    spots:\'12 spots left\' },\n    { time:\'12:00\', name:\'Lunch Burn HIIT\',        trainer:\'Sarah Chen\',    spots:\'2 spots left\' },\n    { time:\'17:00\', name:\'Combat HIIT\',            trainer:\'Derek Stone\',   spots:\'6 spots left\' },\n    { time:\'19:00\', name:\'Evening Strength\',       trainer:\'Marcus Reeves\', spots:\'10 spots left\' },\n  ],\n  tue: [\n    { time:\'06:00\', name:\'Morning Cardio Blast\',   trainer:\'Sarah Chen\',    spots:\'5 spots left\' },\n    { time:\'09:00\', name:\'Functional Fitness\',     trainer:\'Anya Patel\',    spots:\'9 spots left\' },\n    { time:\'11:00\', name:\'Boxing Fundamentals\',    trainer:\'Derek Stone\',   spots:\'3 spots left\' },\n    { time:\'17:30\', name:\'Power Yoga\',             trainer:\'Anya Patel\',    spots:\'7 spots left\' },\n    { time:\'19:00\', name:\'Advanced HIIT\',          trainer:\'Sarah Chen\',    spots:\'1 spot left\'  },\n  ],\n  wed: [\n    { time:\'06:00\', name:\'Strength & Power\',       trainer:\'Marcus Reeves\', spots:\'6 spots left\' },\n    { time:\'08:30\', name:\'Spin Studio\',            trainer:\'Jenny Liu\',     spots:\'10 spots left\' },\n    { time:\'12:00\', name:\'Combat HIIT\',            trainer:\'Derek Stone\',   spots:\'4 spots left\' },\n    { time:\'17:00\', name:\'Yoga & Stretch\',         trainer:\'Anya Patel\',    spots:\'14 spots left\' },\n    { time:\'19:00\', name:\'Night Burn HIIT\',        trainer:\'Sarah Chen\',    spots:\'8 spots left\' },\n  ],\n  thu: [\n    { time:\'07:00\', name:\'Morning Power\',          trainer:\'Marcus Reeves\', spots:\'5 spots left\' },\n    { time:\'09:30\', name:\'Cardio Dance\',           trainer:\'Jenny Liu\',     spots:\'11 spots left\' },\n    { time:\'12:00\', name:\'Core & Stability\',       trainer:\'Anya Patel\',    spots:\'9 spots left\' },\n    { time:\'18:00\', name:\'Kickboxing HIIT\',        trainer:\'Derek Stone\',   spots:\'2 spots left\' },\n    { time:\'20:00\', name:\'Strength Session\',       trainer:\'Marcus Reeves\', spots:\'6 spots left\' },\n  ],\n  fri: [\n    { time:\'06:00\', name:\'Friday Fire HIIT\',       trainer:\'Sarah Chen\',    spots:\'3 spots left\' },\n    { time:\'08:00\', name:\'Spin Studio\',            trainer:\'Jenny Liu\',     spots:\'7 spots left\' },\n    { time:\'10:00\', name:\'Strength Training\',      trainer:\'Marcus Reeves\', spots:\'8 spots left\' },\n    { time:\'12:00\', name:\'Boxing Class\',           trainer:\'Derek Stone\',   spots:\'5 spots left\' },\n    { time:\'17:00\', name:\'Yoga Recovery\',          trainer:\'Anya Patel\',    spots:\'12 spots left\' },\n  ],\n  sat: [\n    { time:\'08:00\', name:\'Weekend Warrior\',        trainer:\'Marcus Reeves\', spots:\'2 spots left\' },\n    { time:\'10:00\', name:\'Combat Conditioning\',    trainer:\'Derek Stone\',   spots:\'6 spots left\' },\n    { time:\'12:00\', name:\'Power Yoga\',             trainer:\'Anya Patel\',    spots:\'10 spots left\' },\n    { time:\'14:00\', name:\'HIIT Circuit\',           trainer:\'Sarah Chen\',    spots:\'4 spots left\' },\n  ],\n  sun: [\n    { time:\'09:00\', name:\'Sunday Reset Yoga\',      trainer:\'Anya Patel\',    spots:\'15 spots left\' },\n    { time:\'11:00\', name:\'Active Recovery\',        trainer:\'Jenny Liu\',     spots:\'8 spots left\' },\n    { time:\'14:00\', name:\'Light Strength\',         trainer:\'Marcus Reeves\', spots:\'10 spots left\' },\n  ],\n};\n\n/* ===== RENDER SCHEDULE ===== */\nfunction renderSchedule(day) {\n  const list = document.getElementById(\'schedList\');\n  if (!list) return;\n  const items = SCHEDULE[day] || [];\n  list.innerHTML = items.map(item => `\n    <div class="sched-item">\n      <div class="sched-time">${item.time}</div>\n      <div class="sched-div"></div>\n      <div class="sched-info">\n        <div class="sched-name">${item.name}</div>\n        <div class="sched-trainer">with ${item.trainer}</div>\n      </div>\n      <div class="sched-spots">${item.spots}</div>\n      <button class="sched-btn" onclick="bookClass(\'${item.name}\')">Book →</button>\n    </div>\n  `).join(\'\');\n}\n\n/* ===== SCHEDULE TABS ===== */\nconst schedTabs = document.getElementById(\'schedTabs\');\nif (schedTabs) {\n  schedTabs.addEventListener(\'click\', e => {\n    const tab = e.target.closest(\'.sched-tab\');\n    if (!tab) return;\n    schedTabs.querySelectorAll(\'.sched-tab\').forEach(t => t.classList.remove(\'active\'));\n    tab.classList.add(\'active\');\n    renderSchedule(tab.dataset.day);\n  });\n}\n\n/* Set today\'s tab as active */\nconst DAYS = [\'sun\',\'mon\',\'tue\',\'wed\',\'thu\',\'fri\',\'sat\'];\nconst todayKey = DAYS[new Date().getDay()];\nconst todayTab = document.querySelector(`[data-day="${todayKey}"]`);\nif (todayTab) {\n  document.querySelectorAll(\'.sched-tab\').forEach(t => t.classList.remove(\'active\'));\n  todayTab.classList.add(\'active\');\n  renderSchedule(todayKey);\n} else {\n  renderSchedule(\'mon\');\n}\n\nfunction bookClass(name) {\n  showToast(`🎉 Booking sent for "${name}"! Check your email.`);\n}\n\n/* ===== NAVBAR SCROLL ===== */\nconst navbar = document.getElementById(\'navbar\');\nconst scrollTopBtn = document.getElementById(\'scrollTop\');\n\nwindow.addEventListener(\'scroll\', () => {\n  const y = window.scrollY;\n  navbar?.classList.toggle(\'scrolled\', y > 50);\n  scrollTopBtn?.classList.toggle(\'vis\', y > 400);\n  updateBottomNav(y);\n}, { passive: true });\n\n/* ===== HAMBURGER / MOBILE MENU ===== */\nconst hamburger = document.getElementById(\'hamburger\');\nconst mobileMenu = document.getElementById(\'mobileMenu\');\nconst mmOverlay  = document.getElementById(\'mmOverlay\');\n\nhamburger?.addEventListener(\'click\', () => {\n  const isOpen = mobileMenu.classList.toggle(\'open\');\n  hamburger.classList.toggle(\'open\', isOpen);\n  mmOverlay?.classList.toggle(\'show\', isOpen);\n  document.body.style.overflow = isOpen ? \'hidden\' : \'\';\n});\n\nfunction closeMobileMenu() {\n  mobileMenu?.classList.remove(\'open\');\n  hamburger?.classList.remove(\'open\');\n  mmOverlay?.classList.remove(\'show\');\n  document.body.style.overflow = \'\';\n}\n\n/* ===== COUNTER ANIMATION ===== */\nconst counted = new WeakSet();\n\nfunction animateCount(el) {\n  if (counted.has(el)) return;\n  counted.add(el);\n\n  const raw    = parseInt(el.dataset.count, 10);\n  const suffix = el.dataset.suffix || \'\';\n  const dur    = 1800;\n  const start  = performance.now();\n\n  function tick(now) {\n    const p = Math.min((now - start) / dur, 1);\n    const e = 1 - Math.pow(1 - p, 3); // ease-out-cubic\n    const v = Math.round(e * raw);\n\n    if (raw >= 1000) {\n      /* suffix like "K+" already includes K, so just strip the K from suffix if present */\n      const cleanSuffix = suffix.startsWith(\'K\') ? suffix.slice(1) : suffix;\n      el.textContent = (v >= 1000 ? (v / 1000).toFixed(0) : v) + \'K\' + cleanSuffix;\n    } else {\n      el.textContent = v + suffix;\n    }\n    if (p < 1) requestAnimationFrame(tick);\n  }\n  requestAnimationFrame(tick);\n}\n\n/* ===== INTERSECTION OBSERVER ===== */\nconst io = new IntersectionObserver(entries => {\n  entries.forEach(entry => {\n    if (!entry.isIntersecting) return;\n    const el = entry.target;\n    el.classList.add(\'vis\');\n    /* trigger counters inside this element */\n    el.querySelectorAll(\'[data-count]\').forEach(animateCount);\n    /* if the element itself is a counter */\n    if (el.hasAttribute(\'data-count\')) animateCount(el);\n  });\n}, { threshold: 0.14 });\n\ndocument.querySelectorAll(\n  \'.anim-up, .anim-left, .anim-right, .si, [data-count]\'\n).forEach(el => io.observe(el));\n\n/* Run hero stat counters after a short delay */\nsetTimeout(() => {\n  document.querySelectorAll(\'.hs-num[data-count]\').forEach(animateCount);\n}, 900);\n\n/* ===== TESTIMONIALS SLIDER ===== */\nlet currentSlide = 0;\nconst testiTrack = document.getElementById(\'testiTrack\');\nconst testiDots  = document.querySelectorAll(\'.td\');\nlet autoSlide;\n\nfunction perView() { return window.innerWidth <= 768 ? 1 : 3; }\nfunction maxSlide() {\n  return Math.max(0, (testiTrack?.children.length || 0) - perView());\n}\n\nfunction goSlide(idx) {\n  if (!testiTrack) return;\n  currentSlide = Math.max(0, Math.min(idx, maxSlide()));\n  const w = testiTrack.children[0]?.offsetWidth + 20 || 0;\n  testiTrack.style.transform = `translateX(-${currentSlide * w}px)`;\n  testiDots.forEach((d, i) => d.classList.toggle(\'active\', i === currentSlide));\n}\n\ntestiDots.forEach(dot => {\n  dot.addEventListener(\'click\', () => goSlide(+dot.dataset.i));\n});\n\nfunction startAutoSlide() {\n  stopAutoSlide();\n  autoSlide = setInterval(() => goSlide((currentSlide + 1) > maxSlide() ? 0 : currentSlide + 1), 4500);\n}\nfunction stopAutoSlide() { clearInterval(autoSlide); }\n\nstartAutoSlide();\n\n/* Touch swipe */\nlet tx = 0;\ntestiTrack?.addEventListener(\'touchstart\', e => { tx = e.touches[0].clientX; stopAutoSlide(); }, { passive: true });\ntestiTrack?.addEventListener(\'touchend\', e => {\n  const diff = tx - e.changedTouches[0].clientX;\n  if (Math.abs(diff) > 44) goSlide(currentSlide + (diff > 0 ? 1 : -1));\n  startAutoSlide();\n});\n\nwindow.addEventListener(\'resize\', () => goSlide(0));\n\n/* ===== PRICING COUNTERS ===== */\nconst pcObserver = new IntersectionObserver(entries => {\n  entries.forEach(entry => {\n    if (entry.isIntersecting) {\n      entry.target.querySelectorAll(\'.pc-amt[data-count]\').forEach(animateCount);\n    }\n  });\n}, { threshold: 0.3 });\ndocument.querySelectorAll(\'.pc\').forEach(c => pcObserver.observe(c));\n\n/* ===== BOTTOM NAV ===== */\nconst BN_MAP = [\n  { id: \'bn-home\',     section: \'home\'     },\n  { id: \'bn-classes\',  section: \'classes\'  },\n  { id: \'bn-schedule\', section: \'schedule\' },\n  { id: \'bn-pricing\',  section: \'pricing\'  },\n  { id: \'bn-contact\',  section: \'contact\'  },\n];\n\nfunction bnNav(btn, href) {\n  document.querySelectorAll(\'.bn\').forEach(b => b.classList.remove(\'active\'));\n  btn.classList.add(\'active\');\n  document.querySelector(href)?.scrollIntoView({ behavior: \'smooth\' });\n}\n\nfunction updateBottomNav(y) {\n  let current = \'\';\n  BN_MAP.forEach(({ section }) => {\n    const el = document.getElementById(section);\n    if (el && y >= el.offsetTop - 220) current = section;\n  });\n  BN_MAP.forEach(({ id, section }) => {\n    document.getElementById(id)?.classList.toggle(\'active\', section === current);\n  });\n}\n\n/* ===== CTA FORM ===== */\nfunction handleCTA(e) {\n  e.preventDefault();\n  const email = document.getElementById(\'ctaEmail\')?.value || \'\';\n  if (!email || !email.includes(\'@\')) {\n    showToast(\'⚠️ Please enter a valid email address.\');\n    return;\n  }\n  showToast(`🎉 Welcome! Free session details sent to ${email.split(\'@\')[0]}@...`);\n  document.getElementById(\'ctaEmail\').value = \'\';\n}\n\n/* ===== SELECT PLAN ===== */\nfunction selectPlan(plan) {\n  showToast(`✅ You selected the ${plan} plan! Redirecting to checkout...`);\n}\n\n/* ===== TOAST NOTIFICATION ===== */\nlet toastTimer;\nfunction showToast(msg) {\n  let toast = document.getElementById(\'apex-toast\');\n  if (!toast) {\n    toast = document.createElement(\'div\');\n    toast.id = \'apex-toast\';\n    toast.className = \'toast\';\n    document.body.appendChild(toast);\n  }\n  toast.textContent = msg;\n  toast.classList.add(\'show\');\n  clearTimeout(toastTimer);\n  toastTimer = setTimeout(() => toast.classList.remove(\'show\'), 3600);\n}\n\n/* ===== SMOOTH CLOSE: click nav links ===== */\ndocument.querySelectorAll(\'a[href^="#"]\').forEach(a => {\n  a.addEventListener(\'click\', e => {\n    const target = document.querySelector(a.getAttribute(\'href\'));\n    if (target) {\n      e.preventDefault();\n      target.scrollIntoView({ behavior: \'smooth\' });\n    }\n  });\n});\n\n/* ===== PERFORMANCE: lazy-start marquee pause on hover ===== */\nconst marqueeTrack = document.querySelector(\'.marquee-track\');\nmarqueeTrack?.parentElement?.addEventListener(\'mouseenter\', () => {\n  marqueeTrack.style.animationPlayState = \'paused\';\n});\nmarqueeTrack?.parentElement?.addEventListener(\'mouseleave\', () => {\n  marqueeTrack.style.animationPlayState = \'running\';\n});\n\n/* ===== PROFILE DRAWER CONTROL ===== */\nfunction openProfileDrawer(event) {\n  event?.preventDefault();\n  event?.stopPropagation();\n  const drawer = document.getElementById(\'profileDrawer\');\n  const overlay = document.getElementById(\'pdOverlay\');\n  drawer?.classList.add(\'open\');\n  overlay?.classList.add(\'show\');\n  document.body.style.overflow = \'hidden\';\n}\n\nfunction closeProfileDrawer() {\n  const drawer = document.getElementById(\'profileDrawer\');\n  const overlay = document.getElementById(\'pdOverlay\');\n  drawer?.classList.remove(\'open\');\n  overlay?.classList.remove(\'show\');\n  document.body.style.overflow = \'\';\n}\n\n/* ===== MOBILE FOOTER ACCORDION ===== */\ndocument.querySelectorAll(\'.footer-grid .ft\').forEach(header => {\n  header.addEventListener(\'click\', () => {\n    if (window.innerWidth <= 768) {\n      header.classList.toggle(\'active\');\n    }\n  });\n});\n\n'

    part_tail = """
  </script>
</body>
</html>"""

    return (
        part_head +
        part_css +
        part_mid +
        part_testimonials +
        part_after_testi +
        part_js +
        part_tail
    )


def _services_html(services: list, accent: str) -> str:
    if not services:
        return ""
    cards = ""
    icons = ["✦", "◈", "⬡", "◉", "▸", "◆"]
    for i, s in enumerate(services[:6]):
        icon = icons[i % len(icons)]
        desc_html = f'<p class="svc-desc">{s["desc"]}</p>' if s["desc"] else ""
        cards += f"""
        <div class="svc-card">
          <span class="svc-icon">{icon}</span>
          <h3>{s["title"]}</h3>
          {desc_html}
        </div>"""
    return f"""
<section class="services-section">
  <div class="container">
    <h2 class="section-title">What We Offer</h2>
    <div class="svc-grid">{cards}
    </div>
  </div>
</section>"""


def _gallery_html(images: list, og_image: str) -> str:
    imgs = []
    if og_image and og_image not in images:
        imgs.append(og_image)
    imgs.extend(images)
    imgs = imgs[:3]
    if not imgs:
        return ""
    cards = "".join(f'<div class="gallery-img" style="background-image:url(\'{i}\')"></div>' for i in imgs)
    return f"""
<section class="gallery-section">
  <div class="container">
    <h2 class="section-title">Gallery</h2>
    <div class="gallery-grid">{cards}</div>
  </div>
</section>"""


def generate_demo_html_stream(business: dict):
    """
    Generator version — yields (step, pct, html_or_none) tuples so the
    caller can stream progress. Final yield has html set.
    """
    name    = business.get("name", "Your Business")
    website = business.get("website", "")

    yield ("Fetching website…", 10, None)
    data = _scrape_site(website) if website else {}

    yield ("Extracting content…", 35, None)
    found = []
    if data.get("hero_text"):   found.append("hero text")
    if data.get("about_text"):  found.append("about")
    if data.get("services"):    found.append(f"{len(data['services'])} services")
    if data.get("og_image"):    found.append("hero image")
    if data.get("images"):      found.append(f"{len(data['images'])} images")
    detail = ", ".join(found) if found else "business info only"
    yield (f"Extracted: {detail}", 60, None)

    yield ("Building demo HTML…", 80, None)
    category = business.get("category", "")
    if _is_gym(category, name):
        html = generate_gym_demo_html(business, data)
    else:
        html = generate_demo_html(business)

    yield ("Saving to disk…", 95, None)
    yield ("Done", 100, html)


def generate_demo_html(business: dict, website_data: dict = None, use_stock: bool = True) -> str:
    # Check for custom Jinja2 templates first
    import os
    demo_templates_dir = os.path.join(os.path.dirname(__file__), "demo_templates")
    custom_html = None
    
    if os.path.exists(demo_templates_dir):
        category = business.get("category", "")
        assigned_template = business.get("template_id")
        
        target_template = None
        
        # Priority 1: Use explicitly assigned template
        if assigned_template and assigned_template.endswith(".html"):
            if os.path.exists(os.path.join(demo_templates_dir, assigned_template)):
                target_template = assigned_template
                
        # Priority 2: Use keyword matching based on config.json
        if not target_template:
            import json
            config_path = os.path.join(demo_templates_dir, "config.json")
            if os.path.exists(config_path):
                try:
                    with open(config_path, "r", encoding="utf-8") as cfg_f:
                        config_data = json.load(cfg_f)
                    templates_list = config_data.get("templates", [])
                    
                    category_lower = (category or "").lower()
                    name_lower = (business.get("name", "") or "").lower()
                    
                    for tpl in templates_list:
                        if not tpl.get("enabled", True):
                            continue
                        tpl_file = tpl.get("file")
                        if not tpl_file:
                            continue
                        niches = tpl.get("niches", [])
                        if any(n in category_lower or n in name_lower for n in niches):
                            if os.path.exists(os.path.join(demo_templates_dir, tpl_file)):
                                target_template = tpl_file
                                break
                except Exception as e:
                    print(f"[demo_generator] Error reading config.json: {e}")

        # Fallback to old matching if still no target template
        if not target_template:
            for tpl_file in os.listdir(demo_templates_dir):
                if not tpl_file.endswith(".html") or tpl_file == "config.json":
                    continue
                base_name = tpl_file.replace(".html", "").lower()
                if base_name in category.lower() or base_name in business.get("name", "").lower():
                    target_template = tpl_file
                    break
                    
        if target_template:
            from jinja2 import Template
            with open(os.path.join(demo_templates_dir, target_template), "r", encoding="utf-8") as f:
                template_str = f.read()
            
            # Select premium niche stock images based on target template
            if target_template == "gym.html":
                _IPG = "https://pms5566.github.io/Iron-Peak-Gym/images/"
                hero_img, about_img = _IPG + "hero-bg.png", _IPG + "about.png"
            elif target_template == "restaurant.html":
                hero_img = "https://images.unsplash.com/photo-1414235077428-338989a2e8c0?w=1400"
                about_img = "https://images.unsplash.com/photo-1550966871-3ed3cdb5ed0c?w=600"
            elif target_template == "dentist.html":
                hero_img = "https://images.unsplash.com/photo-1588776814546-daab30f310ce?w=1400"
                about_img = "https://images.unsplash.com/photo-1629909613654-28e377c37b09?w=600"
            elif target_template == "barbershop.html":
                hero_img = "https://images.unsplash.com/photo-1503951914875-452162b0f3f1?w=1400"
                about_img = "https://images.unsplash.com/photo-1593702295094-aec22597af65?w=600"
            elif target_template == "realestate.html":
                hero_img = "https://images.unsplash.com/photo-1600596542815-ffad4c1539a9?w=1400"
                about_img = "https://images.unsplash.com/photo-1600607687939-ce8a6c25118c?w=600"
            elif target_template == "roofer.html":
                hero_img = "/static/roofer_hero.jpg"
                about_img = "/static/roofer_about.jpg"
            elif target_template == "hvac.html":
                hero_img = "https://images.unsplash.com/photo-1621905251189-08b45d6a269e?w=1400"
                about_img = "https://images.unsplash.com/photo-1581094288338-2314dddb7ecc?w=600"
            elif target_template == "solar.html":
                hero_img = "/static/solar_hero.jpg"
                about_img = "/static/solar_about.jpg"
            elif target_template == "lawyer.html":
                hero_img = "https://images.unsplash.com/photo-1589829545856-d10d557cf95f?w=1400"
                about_img = "https://images.unsplash.com/photo-1450133064473-71024230f91b?w=600"
            elif target_template == "medspa.html":
                hero_img = "https://images.unsplash.com/photo-1522335789203-aabd1fc54bc9?w=1400"
                about_img = "https://images.unsplash.com/photo-1512290923902-8a9f81dc236c?w=600"
            elif target_template == "remodeler.html":
                hero_img = "https://images.unsplash.com/photo-1600585154340-be6161a56a0c?w=1400"
                about_img = "https://images.unsplash.com/photo-1600585154526-990dced4db0d?w=600"
            elif target_template == "cleaning.html":
                hero_img = "/static/cleaning_hero.jpg"
                about_img = "/static/cleaning_about.jpg"
            elif target_template == "detailing.html":
                hero_img = "/static/detailing_hero.jpg"
                about_img = "/static/detailing_about.jpg"
            elif target_template == "treeservice.html":
                hero_img = "/static/treeservice_hero.jpg"
                about_img = "/static/treeservice_about.jpg"
            elif target_template == "chiropractor.html":
                hero_img = "https://power7t.github.io/leadflow-demos/chiro-hero.jpg"
                about_img = "https://power7t.github.io/leadflow-demos/chiro-about.jpg"
            elif target_template == "plumber.html":
                hero_img = "https://power7t.github.io/leadflow-demos/plumber-hero.jpg"
                about_img = "https://power7t.github.io/leadflow-demos/plumber-about.jpg"
            elif target_template == "valet_laundry.html":
                hero_img = "https://power7t.github.io/leadflow-demos/laundry-hero.jpg"
                about_img = "https://power7t.github.io/leadflow-demos/laundry-about.jpg"
            elif target_template == "accountant.html":
                hero_img = "https://power7t.github.io/leadflow-demos/accountant-hero.jpg"
                about_img = "https://power7t.github.io/leadflow-demos/accountant-about.jpg"
            elif target_template == "moving.html":
                hero_img = "https://power7t.github.io/leadflow-demos/moving-hero.jpg"
                about_img = "https://power7t.github.io/leadflow-demos/moving-about.jpg"
            elif target_template == "landscaping.html":
                hero_img = "https://power7t.github.io/leadflow-demos/landscaping-hero.jpg"
                about_img = "https://power7t.github.io/leadflow-demos/landscaping-about.jpg"
            elif target_template == "interiordesign.html":
                hero_img = "https://power7t.github.io/leadflow-demos/interiordesign-hero.jpg"
                about_img = "https://power7t.github.io/leadflow-demos/interiordesign-about.jpg"
            elif target_template == "pestcontrol.html":
                hero_img = "https://images.unsplash.com/photo-1587825140062-720520658739?w=1400"
                about_img = "https://images.unsplash.com/photo-1584622650111-993a426fbf0a?w=600"
            elif target_template == "autorepair.html":
                hero_img = "https://images.unsplash.com/photo-1619642751034-765dfdf7c58e?w=1400"
                about_img = "https://images.unsplash.com/photo-1486262715619-67b85e0b08d3?w=600"
            elif target_template == "homebuilder.html":
                hero_img = "https://images.unsplash.com/photo-1600596542815-ffad4c1539a9?w=1400"
                about_img = "https://images.unsplash.com/photo-1600607687939-ce8a6c25118c?w=600"
            elif target_template == "vet.html":
                hero_img = "https://images.unsplash.com/photo-1583337130417-3346a1be7dee?w=1400"
                about_img = "https://images.unsplash.com/photo-1628009368231-7bb7cbcb8127?w=600"
            elif target_template == "wedding.html":
                hero_img = "https://images.unsplash.com/photo-1519741497674-611481863552?w=1400"
                about_img = "https://images.unsplash.com/photo-1465495976277-4387d4b0b4c6?w=600"
            elif target_template == "electrician.html":
                hero_img = "/static/electrician_hero.jpg"
                about_img = "/static/electrician_about.jpg"
            elif target_template == "orthodontist.html":
                hero_img = "/static/orthodontist_hero.jpg"
                about_img = "/static/orthodontist_about.jpg"
            elif target_template == "pool.html":
                hero_img = "/static/pool_hero.jpg"
                about_img = "/static/pool_about.jpg"
            elif target_template == "painting.html":
                hero_img = "/static/painting_hero.jpg"
                about_img = "/static/painting_about.jpg"
            elif target_template == "flooring.html":
                hero_img = "/static/flooring_hero.jpg"
                about_img = "/static/flooring_about.jpg"
            elif target_template == "trash.html":
                hero_img = "https://images.unsplash.com/photo-1532996122724-e3c354a0b15b?w=1400"
                about_img = "https://images.unsplash.com/photo-1605608670494-b2c65a444c15?w=600"
            elif target_template == "handyman.html":
                hero_img = "https://images.unsplash.com/photo-1540555700478-4be289fbecef?w=1400"
                about_img = "https://images.unsplash.com/photo-1504148455328-c376907d081c?w=600"
            else:
                hero_img, about_img = _STOCK_HERO, _STOCK_ABOUT

            t = Template(template_str)
            import os
            custom_html = t.render(
                lead=business,
                scraped=website_data,
                hero_img=hero_img,
                about_img=about_img,
                agency_whatsapp=os.getenv("AGENCY_WHATSAPP", "918669024169")
            )
                
    if custom_html:
        # Custom Jinja templates don't carry the conversion layer or working
        # tracking — inject both so every demo converts and reports opens.
        return _inject_conversion(custom_html, business)

    name     = business.get("name", "Your Business")
    category = business.get("category", "Business")
    address  = business.get("address", "")
    phone    = business.get("phone", "")
    website  = business.get("website", "")
    rating   = business.get("google_rating")
    reviews  = business.get("google_reviews")
    email    = business.get("email", "")
    instagram= business.get("instagram", "")

    # Use the already-scraped data if the caller passed it; only scrape if not.
    # Normalize so a partial dict can't KeyError downstream.
    if website_data is not None:
        data = {"title": "", "description": "", "og_image": "", "about_text": "",
                "services": [], "images": [], "accent_color": "", "hero_text": "",
                "tagline": "", **website_data}
    else:
        data = _scrape_site(website)

    # Route gym/fitness businesses to Iron Peak–style template
    if _is_gym(category, name):
        return generate_gym_demo_html(business, data)

    accent, bg_dark = _accent_for_category(category, data["accent_color"])

    # Choose best available text for each slot
    display_name = data["title"] or name
    hero_text    = data["hero_text"] or display_name
    tagline      = data["tagline"] or data["description"] or f"Professional {category.lower()} — here to serve you."
    about_text   = data["about_text"] or (
        f"{display_name} is a trusted {category.lower()} "
        + (f"with {reviews:,} Google reviews and a {rating}★ rating. " if rating and reviews else "")
        + "We are committed to delivering the best experience to every customer."
    )

    # Always built-in stock hero; never the prospect's images. No prospect gallery.
    hero_img      = _STOCK_HERO
    services_html = _services_html(data["services"], accent)
    gallery_html  = ""

    hero_style = (
        f'background:linear-gradient(rgba(0,0,0,0.5),rgba(0,0,0,0.65)),url("{hero_img}")center/cover no-repeat;'
    )

    stars = "★" * int(rating or 0) + "☆" * (5 - int(rating or 0)) if rating else ""
    rating_html = (
        f'<div class="hero-rating"><span class="stars">{stars}</span>'
        f'<span class="rating-num">{rating}</span>'
        f'<span class="rating-ct">({reviews:,} Google reviews)</span></div>'
        if rating and reviews else ""
    )

    contact_items = ""
    if phone:
        contact_items += f'<a href="tel:{phone}" class="cinfo"><span>📞</span><span>{phone}</span></a>'
    if email:
        contact_items += f'<a href="mailto:{email}" class="cinfo"><span>✉</span><span>{email}</span></a>'
    if address:
        contact_items += f'<div class="cinfo"><span>📍</span><span>{address}</span></div>'
    if instagram:
        contact_items += f'<a href="https://instagram.com/{instagram}" target="_blank" class="cinfo"><span>📸</span><span>@{instagram}</span></a>'
    if website:
        contact_items += f'<a href="{website}" target="_blank" class="cinfo"><span>🌐</span><span>Current website</span></a>'

    original_note = (
        f'<div class="orig-note">Based on content from <a href="{website}" target="_blank">{website}</a></div>'
        if website else
        '<div class="orig-note">Built from Google Maps business data — no existing website found.</div>'
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{display_name} — New Website Demo</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,sans-serif;background:#f8fafc;color:#1e293b;line-height:1.6}}

/* DEMO BANNER */
.demo-banner{{background:{accent};color:#fff;text-align:center;padding:12px 20px;font-size:14px;font-weight:700;position:sticky;top:0;z-index:200;display:flex;align-items:center;justify-content:center;gap:16px;flex-wrap:wrap;box-shadow:0 4px 12px rgba(0,0,0,0.1)}}
.demo-banner a{{color:#fff;text-decoration:underline;font-weight:700}}
.orig-note{{font-size:12px;font-weight:500;opacity:0.9}}

/* NAV */
.nav{{display:flex;align-items:center;justify-content:space-between;padding:20px 50px;background:rgba(255,255,255,0.95);backdrop-filter:blur(12px);position:sticky;top:48px;z-index:100;border-bottom:1px solid #e2e8f0;box-shadow:0 4px 6px -1px rgba(0,0,0,0.05)}}
.nav-brand{{font-size:22px;font-weight:800;color:{accent};letter-spacing:-0.5px}}
.nav-links{{display:flex;gap:32px}}
.nav-links a{{color:#475569;text-decoration:none;font-size:15px;font-weight:500;transition:color 0.2s}}
.nav-links a:hover{{color:{accent}}}
.nav-cta{{background:{accent};color:#fff;padding:10px 24px;border-radius:50px;font-size:14px;font-weight:700;text-decoration:none;transition:transform 0.15s,box-shadow 0.15s}}
.nav-cta:hover{{transform:translateY(-2px);box-shadow:0 4px 12px rgba(0,0,0,0.15)}}

/* HERO */
.hero{{{hero_style}min-height:85vh;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:100px 24px 80px}}
.hero-eyebrow{{font-size:14px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:#fff;margin-bottom:20px;text-shadow:0 2px 10px rgba(0,0,0,0.5)}}
.hero h1{{font-size:clamp(2.5rem,6vw,4.5rem);font-weight:900;letter-spacing:-1.5px;line-height:1.1;margin-bottom:24px;max-width:850px;color:#fff;text-shadow:0 4px 20px rgba(0,0,0,0.6)}}
.hero-tagline{{font-size:1.25rem;color:rgba(255,255,255,0.9);max-width:600px;margin:0 auto 40px;line-height:1.6;text-shadow:0 2px 10px rgba(0,0,0,0.5)}}
.hero-rating{{margin-bottom:40px;display:flex;align-items:center;gap:10px;justify-content:center;background:rgba(255,255,255,0.1);backdrop-filter:blur(10px);padding:10px 20px;border-radius:50px}}
.stars{{color:#fbbf24;font-size:1.3rem;letter-spacing:2px}}
.rating-num{{font-size:1.15rem;font-weight:800;color:#fff}}
.rating-ct{{color:rgba(255,255,255,0.8);font-size:0.95rem}}
.hero-btns{{display:flex;gap:16px;flex-wrap:wrap;justify-content:center}}
.btn-main{{background:{accent};color:#fff;padding:18px 42px;border-radius:50px;font-weight:800;font-size:1.1rem;text-decoration:none;transition:transform 0.2s,box-shadow 0.2s;box-shadow:0 8px 24px rgba(0,0,0,0.25)}}
.btn-main:hover{{transform:translateY(-3px);box-shadow:0 12px 36px rgba(0,0,0,0.35)}}
.btn-outline{{border:2px solid #fff;background:rgba(255,255,255,0.1);color:#fff;padding:16px 36px;border-radius:50px;font-weight:700;font-size:1.1rem;text-decoration:none;transition:all 0.2s}}
.btn-outline:hover{{background:#fff;color:#000}}

/* SECTIONS */
.container{{max-width:1100px;margin:0 auto;padding:0 24px}}
.section-title{{font-size:clamp(2rem,4vw,2.8rem);font-weight:800;letter-spacing:-0.5px;margin-bottom:16px;color:#0f172a}}
.section-sub{{color:#64748b;font-size:1.1rem;margin-bottom:56px;max-width:600px}}

/* ABOUT */
.about-section{{padding:112px 0;background:#ffffff}}
.about-inner{{display:grid;grid-template-columns:1fr 1fr;gap:80px;align-items:center}}
.about-text p{{color:#475569;font-size:1.1rem;line-height:1.8;margin-bottom:20px}}
.about-stat{{text-align:center;padding:32px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:16px;transition:transform 0.2s,box-shadow 0.2s}}
.about-stat:hover{{transform:translateY(-5px);box-shadow:0 12px 24px rgba(0,0,0,0.05)}}
.about-stat-num{{font-size:2.8rem;font-weight:900;color:{accent};display:block;margin-bottom:8px}}
.about-stat-label{{font-size:14px;font-weight:600;color:#64748b;text-transform:uppercase;letter-spacing:1px}}
.about-stats{{display:grid;grid-template-columns:1fr 1fr;gap:20px}}
@media(max-width:768px){{.about-inner{{grid-template-columns:1fr}}}}

/* SERVICES */
.svc-card:hover{{border-color:{accent};transform:translateY(-3px)}}
.svc-icon{{font-size:1.6rem;display:block;margin-bottom:14px;color:{accent}}}
.svc-card h3{{font-size:1.05rem;font-weight:700;margin-bottom:8px;color:#fff}}
.svc-desc{{font-size:0.88rem;color:#888;line-height:1.65}}

/* GALLERY */
.gallery-section{{padding:80px 0;background:#111}}
.gallery-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:40px}}
.gallery-img{{height:220px;border-radius:12px;background-size:cover;background-position:center;background-color:#1a1a1a}}
@media(max-width:640px){{.gallery-grid{{grid-template-columns:1fr}}}}

/* CONTACT */
.contact-section{{padding:96px 0;background:#0d0d0d;text-align:center}}
.cinfo-grid{{display:flex;flex-wrap:wrap;gap:14px;justify-content:center;margin-top:40px}}
.cinfo{{display:flex;align-items:center;gap:12px;background:#161616;border:1px solid #252525;border-radius:12px;padding:16px 24px;color:#e4e4e4;text-decoration:none;font-size:0.95rem;transition:border-color 0.2s,color 0.2s}}
.cinfo:hover{{border-color:{accent};color:{accent}}}
.cinfo span:first-child{{font-size:1.2rem}}

/* FOOTER */
footer{{text-align:center;padding:28px 20px;background:#080808;color:#444;font-size:12px;border-top:1px solid #1a1a1a}}
footer a{{color:{accent};text-decoration:none}}
footer a:hover{{text-decoration:underline}}
</style>
</head>
<body>

<!-- SCARCITY BANNER -->
<div id="countdown-banner" style="background:#ff4d4d; color:white; text-align:center; padding:10px; font-weight:bold; font-family:sans-serif; font-size:14px; position:sticky; top:0; z-index:9999;">
  ⏳ This free custom prototype expires and will be permanently deleted in: <span id="timer">47:59:59</span>
</div>
<script>
  let expires = localStorage.getItem("demo_expires_{business.get('id','')}");
  if (!expires) {{
    expires = Date.now() + 48 * 60 * 60 * 1000;
    localStorage.setItem("demo_expires_{business.get('id','')}", expires);
  }}
  setInterval(() => {{
    let diff = Math.max(0, expires - Date.now());
    let h = Math.floor(diff / 3600000).toString().padStart(2, '0');
    let m = Math.floor((diff % 3600000) / 60000).toString().padStart(2, '0');
    let s = Math.floor((diff % 60000) / 1000).toString().padStart(2, '0');
    document.getElementById("timer").textContent = h + ":" + m + ":" + s;
  }}, 1000);
</script>

<div class="demo-banner">
  ✨ FREE demo website built by Chandan Gosavi —
  <a href="https://www.fiverr.com/s/e6zGy4g" target="_blank">hire me to take it live →</a>
  {original_note}
</div>

<nav class="nav">
  <span class="nav-brand">{display_name}</span>
  <div class="nav-links">
    <a href="#about">About</a>
    {'<a href="#services">Services</a>' if data["services"] else ''}
    {'<a href="#gallery">Gallery</a>' if gallery_html else ''}
    <a href="#contact">Contact</a>
  </div>
  <a href="#contact" class="nav-cta">Get in Touch</a>
</nav>

<section class="hero">
  <div class="hero-eyebrow">{category}</div>
  <h1>{hero_text}</h1>
  <p class="hero-tagline">{tagline}</p>
  {rating_html}
  <div class="hero-btns">
    <a href="#contact" class="btn-main">Contact Us</a>
    {'<a href="#services" class="btn-outline">Our Services</a>' if data["services"] else '<a href="#about" class="btn-outline">Learn More</a>'}
  </div>
</section>

<section class="about-section" id="about">
  <div class="container">
    <div class="about-inner">
      <div class="about-text">
        <h2 class="section-title">About Us</h2>
        <p>{about_text}</p>
        {"<p>" + data['description'] + "</p>" if data['description'] and data['description'] != about_text else ""}
      </div>
      <div class="about-stats">
        {f'<div class="about-stat"><span class="about-stat-num">{rating}★</span><span class="about-stat-label">Google Rating</span></div>' if rating else ''}
        {f'<div class="about-stat"><span class="about-stat-num">{reviews:,}</span><span class="about-stat-label">Reviews</span></div>' if reviews else ''}
        <div class="about-stat"><span class="about-stat-num">✓</span><span class="about-stat-label">Trusted Business</span></div>
        <div class="about-stat"><span class="about-stat-num">24h</span><span class="about-stat-label">Response Time</span></div>
      </div>
    </div>
  </div>
</section>

{'<div id="services">' + services_html + '</div>' if services_html else ''}

{'<div id="gallery">' + gallery_html + '</div>' if gallery_html else ''}

<section class="contact-section" id="contact">
  <div class="container">
    <h2 class="section-title">Get in Touch</h2>
    <p class="section-sub">We'd love to hear from you. Reach out through any of the channels below.</p>
    <div class="cinfo-grid">
      {contact_items or '<div class="cinfo"><span>📬</span><span>Contact us today</span></div>'}
    </div>
  </div>
</section>

<footer>
  &copy; {display_name} &nbsp;·&nbsp;
  Website demo by <a href="https://www.fiverr.com/s/e6zGy4g" target="_blank">Chandan Gosavi</a>
  &nbsp;·&nbsp; Want this live? <a href="https://www.fiverr.com/s/e6zGy4g" target="_blank">Order here →</a>
</footer>



{cta_block(business)}

{_track_pixel(business)}

</body>
</html>"""


def generate_saas_crm_demo_html(business: dict) -> str:
    """
    Generates a SaaS CRM Demo landing page for the prospect.
    Falls back to the generic generate_demo_html but with a SaaS theme twist.
    """
    name = business.get("name", "Your Business")
    return f"""<!DOCTYPE html>
<html>
<head>
    <title>{name} - SaaS CRM Demo</title>
</head>
<body style="font-family: sans-serif; text-align: center; padding: 50px;">
    <h1>SaaS CRM Automation for {name}</h1>
    <p>We built a custom automated CRM and lead-nurturing pipeline specifically for your workflow.</p>
    <button style="padding: 15px 30px; font-size: 18px; background: #007bff; color: white; border: none; border-radius: 5px; cursor: pointer;">View Pipeline Setup</button>
    {_track_pixel(business)}
</body>
</html>"""
