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


# ── Scraping ──────────────────────────────────────────────────────────────────

def _scrape_site(url: str) -> dict:
    """Fetch and extract everything useful from the existing website."""
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

    # Accent color from theme-color meta
    tc = soup.find("meta", {"name": "theme-color"})
    if tc:
        out["accent_color"] = tc.get("content", "")

    # Hero text — first big h1 or h2
    for tag in soup.find_all(["h1", "h2"]):
        text = tag.get_text(" ", strip=True)
        if 4 < len(text) < 120 and not any(bad in text.lower() for bad in ["cookie", "menu", "nav", "skip"]):
            out["hero_text"] = text
            break

    # Strip noise before deep extraction
    for t in soup.find_all(STRIP_TAGS):
        t.decompose()

    # Tagline — first p after h1/h2
    for h in soup.find_all(["h1", "h2"]):
        sib = h.find_next_sibling()
        if sib and sib.name == "p":
            text = sib.get_text(" ", strip=True)
            if 10 < len(text) < 250:
                out["tagline"] = text
                break

    # About — biggest coherent paragraph (50–500 chars)
    paras = []
    for p in soup.find_all("p"):
        text = p.get_text(" ", strip=True)
        if 50 < len(text) < 500:
            paras.append(text)
    if paras:
        # Prefer the longest meaningful paragraph
        out["about_text"] = max(paras, key=len)

    # Services — headings/items inside a service-like section
    services = []
    for section in soup.find_all(["section", "div", "article"]):
        heading = section.find(["h2", "h3", "h4"])
        if not heading:
            continue
        heading_text = heading.get_text(strip=True)
        if not SERVICE_KEYWORDS.search(heading_text):
            continue
        # Collect child items (li or sub-headings + their p)
        items = []
        for li in section.find_all("li"):
            t = li.get_text(" ", strip=True)
            if 3 < len(t) < 80:
                items.append({"title": t, "desc": ""})
        if not items:
            for h in section.find_all(["h3", "h4", "h5"]):
                title = h.get_text(strip=True)
                desc_p = h.find_next_sibling("p")
                desc = desc_p.get_text(" ", strip=True)[:120] if desc_p else ""
                if 2 < len(title) < 60:
                    items.append({"title": title, "desc": desc})
        if items:
            services.extend(items[:6])
            break

    # Fallback services — pull from any ul with 3+ short items
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

    # We never use the prospect's own images on demos — only built-in stock —
    # so don't bother scraping them.
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


def generate_gym_demo_html(business: dict, scraped: dict, use_stock: bool = False) -> str:
    """Iron Peak–style gym demo. Exact same design, real gym info swapped in."""
    name      = business.get("name", "Your Gym")
    address   = business.get("address", "")
    phone     = business.get("phone", "")
    email     = business.get("email", "")
    instagram = business.get("instagram", "")
    rating    = business.get("google_rating")
    reviews   = business.get("google_reviews")
    website   = business.get("website", "")
    maps_url  = business.get("maps_url", "")

    # Split name for logo two-tone styling
    parts   = name.strip().split()
    logo_p1 = parts[0].upper() if parts else name.upper()
    logo_p2 = " ".join(parts[1:]).upper() if len(parts) > 1 else ""

    about_text = (scraped.get("about_text") or scraped.get("description") or
        f"{name} is a premier fitness facility committed to helping every member achieve their health and performance goals. "
        "Whether you're a beginner or an elite athlete, our coaches and equipment are here to support your journey.")

    # ── Image allocation ─────────────────────────────────────────────────────────
    # Always use the template's built-in stock photos — never the prospect's images.
    _IPG = "https://pms5566.github.io/Iron-Peak-Gym/images/"
    hero_img     = _IPG + "hero-bg.png"
    about_img    = _IPG + "about.png"
    gallery_imgs = []

    # Build hero CSS background (no background-attachment:fixed — janky on mobile).
    hero_bg = (
        f"linear-gradient(rgba(8,9,12,0.55),rgba(8,9,12,0.85)),url('{hero_img}') center/cover no-repeat"
    )

    # hero_bg computed below after fallback images are resolved

    # About image HTML
    about_img_html = (
        f'<img src="{about_img}" alt="{name}" class="about-image" onerror="this.parentElement.style.opacity=\'0.3\'">'
        if about_img else
        '<div class="about-image" style="background:linear-gradient(135deg,#1a0a05,#08090C);display:flex;align-items:center;justify-content:center;font-size:6rem;border-radius:24px;">🏋️</div>'
    )

    # Gallery section from scraped photos
    if gallery_imgs:
        gallery_items = "".join(
            f'<div class="gallery-item reveal reveal-scale-in" style="transition-delay:{i*0.1:.1f}s">'
            f'<img src="{img}" alt="{name} photo {i+1}" loading="lazy" onerror="this.parentElement.style.display=\'none\'">'
            f'</div>'
            for i, img in enumerate(gallery_imgs)
        )
        gallery_section = (
            f'<section class="gallery-section" id="gallery"><div class="container">'
            f'<div style="text-align:center;margin-bottom:4rem"><span class="section-tag">Our Space</span>'
            f'<h2 class="section-title" style="max-width:700px;margin:.5rem auto 0">Inside {name}</h2></div>'
            f'<div class="gallery-grid">{gallery_items}</div></div></section>'
        )
    else:
        gallery_section = ""

    category_lower = (category or "gym").lower()
    
    if "chiropractor" in category_lower or "chiropractic" in category_lower:
        default_svcs = [
            ("Spinal Adjustments", "Gentle, precise alignments to relieve nerve pressure and restore mobility."),
            ("Pain Management", "Comprehensive care plans to alleviate chronic back, neck, and joint pain."),
            ("Sports Recovery", "Specialized therapies to help athletes heal faster and perform at their peak."),
            ("Posture Correction", "Targeted plans to correct spinal curvature and improve daily posture."),
            ("Massage Therapy", "Deep tissue relaxation to complement and enhance your chiropractic adjustments."),
            ("Wellness Consultations", "Holistic advice on ergonomics, nutrition, and long-term joint health.")
        ]
        icons = ["🦴","🧘","🏃","🛌","💆","📈"]
        prog_tag = "Our Treatments"
        prog_title = "Engineered For <span class=\"text-gradient-orange\">Pain Relief</span>"
        prog_desc = "Discover targeted treatments structured to improve mobility, alleviate pain, and restore your well-being."
        testi_tag = "Patient Reviews"
        testi_title = "Real Healing, <span class=\"text-gradient-orange\">Real Relief</span>"
        testi_1 = f"\"Coming to {name} was life-changing. The doctors are incredibly knowledgeable and I am finally pain-free after years of back issues.\""
        testi_2 = f"\"The atmosphere at {name} is incredibly welcoming. They took the time to explain my x-rays and the adjustments have drastically improved my sleep.\""
        testi_3 = f"\"I've tried many clinics, but {name} is on a different level. The personalized recovery plan got me back to running in just a few weeks.\""
        testi_4 = f"\"Best investment I've made in my health. The staff is supportive, the clinic is modern, and the adjustments provide instant relief.\""
        phrase1_def = "PAIN RELIEF"
        phrase2 = "SPINAL HEALTH"
        phrase3 = "TRUE WELLNESS"
        page_title = f"{name} | Expert Chiropractic Care"
        page_desc = f"Welcome to {name}. Premium chiropractic facility in your city."
    else:
        default_svcs = [
            ("Strength Training","Build muscle and power through progressive overload and compound movements."),
            ("HIIT & Cardio","Torch fat and boost cardiovascular fitness with high-intensity circuits."),
            ("Personal Training","One-on-one coaching sessions tailored entirely to your body and goals."),
            ("Yoga & Recovery","Improve flexibility and restore your body between intense training sessions."),
            ("Group Classes","High-energy group sessions that push you further than training alone."),
            ("Nutrition Coaching","Expert nutrition plans to fuel performance and maximise your results."),
        ]
        icons = ["🏋️","🔥","🥊","🧘","🏃","💪"]
        prog_tag = "Our Programs"
        prog_title = "Engineered For <span class=\"text-gradient-orange\">Extraordinary</span> Results"
        prog_desc = "Discover programs structured to improve strength, conditioning, agility and mental resilience."
        testi_tag = "What Members Say"
        testi_title = "Real Stories, <span class=\"text-gradient-orange\">Real Results</span>"
        testi_1 = f"\"Joining {name} was the best decision I made. The coaches are incredible and the equipment is top-notch. I've seen results I never thought possible.\""
        testi_2 = f"\"The atmosphere at {name} is unmatched. Everyone is motivated and the trainers really push you to your limits while keeping it safe and fun.\""
        testi_3 = f"\"I've tried many gyms but {name} is on a different level. The personal training sessions changed my physique completely in just 6 months.\""
        testi_4 = f"\"Best investment I've made in my health. The group classes are energetic, the staff is supportive and the facilities are always clean and modern.\""
        phrase1_def = "PEAK POWER"
        phrase2 = "INNER BEAST"
        phrase3 = "TRUE POTENTIAL"
        page_title = f"{name} | Elevate Your Performance"
        page_desc = f"Welcome to {name}. Premium fitness facility in your city."

    # Program cards — use scraped services or defaults
    services = (scraped.get("services") or [])[:6]
    
    if services:
        prog_cards = ""
        for i, svc in enumerate(services):
            icon  = icons[i % len(icons)]
            delay = f"transition-delay:{(i%3)*0.1:.1f}s" if i % 3 > 0 else ""
            title = svc["title"] if isinstance(svc, dict) else str(svc)
            desc  = (svc.get("desc") or f"Expert {title.lower()} and world-class care.") if isinstance(svc, dict) else f"World-class {title.lower()} at {name}."
            prog_cards += (
                f'<div class="program-card reveal reveal-slide-up" style="{delay}">'
                f'<div class="program-icon">{icon}</div>'
                f'<h3>{title}</h3>'
                f'<p>{desc}</p>'
                f'<a href="#contact" class="program-link">Get Started →</a></div>'
            )
    else:
        prog_cards = "".join(
            f'<div class="program-card reveal reveal-slide-up" style="{"transition-delay:"+str(i%3*0.1)+"s" if i%3>0 else ""}">'
            f'<div class="program-icon">{icons[i]}</div><h3>{title}</h3><p>{desc}</p>'
            f'<a href="#contact" class="program-link">Get Started →</a></div>'
            for i, (title, desc) in enumerate(default_svcs)
        )

    # Stats
    review_stat = f"{reviews:,}+" if reviews else "500+"
    rating_val  = f"{rating}" if rating else "5.0"

    # Contact items
    contact_items = ""
    if phone:
        contact_items += f'<a href="tel:{phone}" class="cinfo-item">\U0001f4de {phone}</a>'
    if email:
        contact_items += f'<a href="mailto:{email}" class="cinfo-item">✉ {email}</a>'
    if address:
        contact_items += f'<div class="cinfo-item">\U0001f4cd {address.split(",")[0]}</div>'
    if instagram:
        contact_items += f'<a href="https://instagram.com/{instagram}" target="_blank" class="cinfo-item">\U0001f4f8 @{instagram}</a>'
    if maps_url:
        contact_items += f'<a href="{maps_url}" target="_blank" class="cinfo-item">\U0001f5fa View on Google Maps</a>'

    ig_link  = f'<a href="https://instagram.com/{instagram}" target="_blank" class="social-btn">IG</a>' if instagram else ""
    map_btn  = f'<a href="{maps_url}" target="_blank" class="social-btn">\U0001f4cd</a>' if maps_url else ""

    orig_note  = f'Based on {website}' if website else 'Built from Google Maps data'
    addr_parts = [a.strip() for a in address.split(",")]
    city       = addr_parts[1] if len(addr_parts) > 1 else (addr_parts[0] if addr_parts else "your city")

    # Cycling hero text — use scraped hero_text as first phrase if available
    phrase1 = (scraped.get("hero_text") or phrase1_def).upper()[:30]

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{page_title}</title>
<meta name="description" content="{page_desc}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Outfit:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Outfit:wght@400;500;600;700;800;900&display=swap');
:root{{--bg-primary:#08090C;--bg-secondary:#101217;--bg-tertiary:#161A22;--accent-orange:#FF4D24;--accent-orange-glow:rgba(255,77,36,0.45);--accent-teal:#00F2FE;--accent-teal-glow:rgba(0,242,254,0.3);--text-white:#FFFFFF;--text-gray:#A2A7B6;--text-muted:#626775;--glass-bg:rgba(16,18,23,0.75);--glass-border:rgba(255,255,255,0.05);--glass-border-hover:rgba(255,77,36,0.3);--border-radius-sm:8px;--border-radius-md:16px;--border-radius-lg:24px;--shadow-sm:0 4px 12px rgba(0,0,0,0.3);--shadow-md:0 12px 32px rgba(0,0,0,0.5);--shadow-lg:0 24px 64px rgba(0,0,0,0.7);--shadow-orange:0 0 30px rgba(255,77,36,0.35);--transition-fast:0.2s cubic-bezier(0.25,1,0.5,1);--transition-smooth:0.4s cubic-bezier(0.25,1,0.5,1);--transition-slow:0.8s cubic-bezier(0.25,1,0.5,1)}}
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
html{{scroll-behavior:smooth;background-color:var(--bg-primary);color:var(--text-white);font-family:'Inter',sans-serif;overflow-x:hidden}}
body{{overflow-x:hidden;line-height:1.6;cursor:none}}
::-webkit-scrollbar{{width:8px}}::-webkit-scrollbar-track{{background:var(--bg-primary)}}::-webkit-scrollbar-thumb{{background:var(--bg-tertiary);border-radius:4px}}::-webkit-scrollbar-thumb:hover{{background:var(--accent-orange)}}
h1,h2,h3,h4,h5,h6{{font-family:'Outfit',sans-serif;font-weight:800;letter-spacing:-0.02em;line-height:1.1;color:var(--text-white)}}
p{{color:var(--text-gray);font-weight:400}}
a{{text-decoration:none;color:inherit}}
.text-gradient-orange{{background:linear-gradient(135deg,#FF8E53 0%,#FF4D24 50%,#C41F00 100%);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}}
.text-gradient-teal{{background:linear-gradient(135deg,#00F2FE 0%,#4FACFE 100%);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}}
.container{{width:100%;max-width:1300px;margin:0 auto;padding:0 2rem}}
.btn{{display:inline-flex;align-items:center;justify-content:center;gap:.6rem;padding:.9rem 2.2rem;font-family:'Outfit',sans-serif;font-size:1rem;font-weight:700;text-transform:uppercase;letter-spacing:.05em;text-decoration:none;border-radius:var(--border-radius-sm);border:2px solid transparent;cursor:pointer;transition:var(--transition-smooth);overflow:hidden}}
.btn-primary{{background-color:var(--accent-orange);color:#fff;box-shadow:var(--shadow-sm)}}.btn-primary:hover{{background:transparent;border-color:var(--accent-orange);box-shadow:var(--shadow-orange);transform:translateY(-3px)}}
.btn-secondary{{background:transparent;border-color:var(--glass-border);color:#fff}}.btn-secondary:hover{{background:rgba(255,255,255,.05);border-color:#fff;transform:translateY(-3px)}}
section{{padding:8rem 0;position:relative;overflow:hidden}}
.section-tag{{font-family:'Outfit',sans-serif;font-weight:700;font-size:.9rem;text-transform:uppercase;letter-spacing:.15em;color:var(--accent-orange);margin-bottom:1rem;display:inline-block}}
.section-title{{font-size:2.8rem;margin-bottom:1.5rem}}
.section-desc{{font-size:1.1rem;max-width:600px;margin-bottom:4rem}}
/* REVEAL */
.reveal{{opacity:0;transition:var(--transition-slow)}}.reveal-slide-up{{transform:translateY(60px)}}.reveal-slide-left{{transform:translateX(60px)}}.reveal-slide-right{{transform:translateX(-60px)}}.reveal-scale-in{{transform:scale(.9)}}.reveal.revealed{{opacity:1;transform:none}}
.delay-100{{transition-delay:.1s}}.delay-200{{transition-delay:.2s}}.delay-300{{transition-delay:.3s}}.delay-400{{transition-delay:.4s}}.delay-500{{transition-delay:.5s}}
/* CURSOR */
.custom-cursor-dot{{position:fixed;width:8px;height:8px;background:var(--accent-orange);border-radius:50%;pointer-events:none;z-index:9999;transform:translate(-50%,-50%);transition:width .2s,height .2s,background .2s}}
.custom-cursor-ring{{position:fixed;width:40px;height:40px;border:1.5px solid var(--accent-orange);border-radius:50%;pointer-events:none;z-index:9998;transform:translate(-50%,-50%);transition:width .3s,height .3s,border-color .3s,opacity .3s;opacity:.6}}
body.cursor-hover .custom-cursor-dot{{width:6px;height:6px;background:var(--accent-teal)}}
body.cursor-hover .custom-cursor-ring{{width:60px;height:60px;border-color:var(--accent-teal);opacity:.4}}
@media(max-width:768px){{.custom-cursor-dot,.custom-cursor-ring{{display:none}}body{{cursor:auto}}}}
/* SPOTLIGHT */
.spotlight{{position:absolute;width:600px;height:600px;background:radial-gradient(circle,var(--accent-orange-glow) 0%,transparent 70%);pointer-events:none;z-index:0;opacity:.5}}
/* DEMO BANNER */
.demo-banner{{background:var(--accent-orange);color:#000;text-align:center;padding:12px 20px;font-size:13px;font-weight:700;position:sticky;top:0;z-index:10000;display:flex;align-items:center;justify-content:center;gap:16px;flex-wrap:wrap}}
.demo-banner a{{color:#000;text-decoration:underline;font-weight:800}}
.demo-banner .orig{{font-size:11px;font-weight:400;opacity:.65}}
/* NAVBAR */
.navbar{{position:fixed;top:48px;left:0;width:100%;z-index:1000;transition:var(--transition-smooth)}}
.navbar.scrolled{{background:var(--glass-bg);backdrop-filter:blur(15px);-webkit-backdrop-filter:blur(15px);border-bottom:1px solid var(--glass-border)}}
.nav-container{{display:flex;justify-content:space-between;align-items:center;height:85px;transition:var(--transition-smooth)}}
.navbar.scrolled .nav-container{{height:70px}}
.logo{{font-family:'Outfit',sans-serif;font-size:1.8rem;font-weight:900;color:#fff;display:flex;align-items:center;gap:.5rem}}
.logo span{{color:var(--accent-orange)}}
.logo-icon{{width:32px;height:32px;background:linear-gradient(135deg,var(--accent-orange),#C41F00);clip-path:polygon(50% 0%,100% 25%,100% 75%,50% 100%,0% 75%,0% 25%);position:relative;flex-shrink:0;box-shadow:var(--shadow-orange)}}
.logo-icon::after{{content:'';position:absolute;width:14px;height:14px;background:#fff;clip-path:polygon(50% 15%,85% 85%,15% 85%);top:50%;left:50%;transform:translate(-50%,-55%)}}
.nav-links{{display:flex;gap:2.5rem;list-style:none}}
.nav-links a{{color:var(--text-gray);font-weight:500;font-size:.95rem;transition:var(--transition-fast);position:relative;padding:.5rem 0}}
.nav-links a::after{{content:'';position:absolute;bottom:0;left:0;width:0;height:2px;background:var(--accent-orange);transition:var(--transition-smooth)}}
.nav-links a:hover,.nav-links a.active{{color:#fff}}.nav-links a:hover::after,.nav-links a.active::after{{width:100%}}
.nav-actions{{display:flex;align-items:center;gap:1.5rem}}
.hamburger{{display:none;cursor:pointer;background:none;border:none;padding:.5rem}}
.hamburger span{{display:block;width:25px;height:2px;background:#fff;margin:6px 0;transition:var(--transition-smooth)}}
.hamburger.active span:nth-child(1){{transform:rotate(-45deg) translate(-5px,6px)}}.hamburger.active span:nth-child(2){{opacity:0}}.hamburger.active span:nth-child(3){{transform:rotate(45deg) translate(-5px,-6px)}}
/* HERO */
.hero{{height:100vh;min-height:700px;display:flex;align-items:center;background:{hero_bg};position:relative;padding-top:133px}}
.hero::before{{content:'';position:absolute;inset:0;background:linear-gradient(0deg,var(--bg-primary) 0%,rgba(8,9,12,.4) 50%,rgba(8,9,12,.75) 100%);z-index:1}}
.hero .container{{position:relative;z-index:2}}
.hero-content{{max-width:800px}}
.hero-tag{{background:rgba(255,77,36,.15);border:1px solid var(--accent-orange);color:#fff;padding:.4rem 1.2rem;border-radius:50px;font-family:'Outfit',sans-serif;font-weight:700;font-size:.85rem;letter-spacing:.1em;text-transform:uppercase;display:inline-flex;align-items:center;gap:.5rem;margin-bottom:2rem}}
.hero-tag::before{{content:'';width:6px;height:6px;background:var(--accent-orange);border-radius:50%;box-shadow:0 0 8px var(--accent-orange);animation:pulse 1.5s infinite}}
@keyframes pulse{{0%,100%{{transform:scale(1);opacity:1}}50%{{transform:scale(1.6);opacity:.5}}}}
.hero-name{{font-size:4.5rem;line-height:.95;text-transform:uppercase;margin-bottom:.5rem}}
.hero-subtitle-wrapper{{overflow:hidden;height:5rem;margin-bottom:1.5rem}}
.hero-subtitle-track{{animation:slideUpDown 9s cubic-bezier(0.76,0,0.24,1) infinite}}
@keyframes slideUpDown{{0%,25%{{transform:translateY(0)}}33%,58%{{transform:translateY(-100%)}}66%,91%{{transform:translateY(-200%)}}100%{{transform:translateY(0)}}}}
.hero-subtitle-track span{{display:block;height:5rem;font-family:'Outfit',sans-serif;font-size:4.5rem;font-weight:900;line-height:1.1;text-transform:uppercase}}
.hero-desc{{font-size:1.2rem;color:var(--text-gray);margin-bottom:3rem;max-width:600px}}
.hero-btns{{display:flex;gap:1.5rem;flex-wrap:wrap}}
/* STATS */
.stats{{padding:0;margin-top:-60px;position:relative;z-index:10}}
.stats-grid{{display:grid;grid-template-columns:repeat(4,1fr);background:var(--bg-secondary);border:1px solid var(--glass-border);border-radius:var(--border-radius-md);padding:2.5rem;box-shadow:var(--shadow-lg);position:relative;overflow:hidden}}
.stats-grid::before{{content:'';position:absolute;top:0;left:0;width:100%;height:3px;background:linear-gradient(90deg,var(--accent-orange),var(--accent-teal))}}
.stat-item{{display:flex;flex-direction:column;align-items:center;text-align:center;position:relative}}
.stat-item:not(:last-child)::after{{content:'';position:absolute;right:0;top:15%;height:70%;width:1px;background:linear-gradient(180deg,transparent,rgba(255,255,255,.1),transparent)}}
.stat-number{{font-family:'Outfit',sans-serif;font-size:3.2rem;font-weight:900;line-height:1;margin-bottom:.5rem;letter-spacing:-.03em}}
.stat-label{{font-size:.85rem;text-transform:uppercase;letter-spacing:.1em;color:var(--text-gray);font-weight:500}}
/* ABOUT */
.about-grid{{display:grid;grid-template-columns:1.1fr .9fr;gap:5rem;align-items:center}}
.about-features{{display:grid;grid-template-columns:1fr 1fr;gap:2rem;margin-top:3rem}}
.about-feature{{display:flex;gap:1rem}}
.about-feature-icon{{width:48px;height:48px;background:var(--bg-tertiary);border:1px solid var(--glass-border);border-radius:var(--border-radius-sm);display:flex;align-items:center;justify-content:center;flex-shrink:0;font-size:1.4rem;transition:var(--transition-smooth)}}
.about-feature:hover .about-feature-icon{{background:var(--accent-orange);border-color:var(--accent-orange);box-shadow:var(--shadow-orange)}}
.about-feature h4{{font-size:1.05rem;margin-bottom:.4rem}}.about-feature p{{font-size:.9rem;line-height:1.5}}
.about-img-wrapper{{position:relative;display:flex;justify-content:center;align-items:center}}
.about-image{{width:100%;max-width:460px;aspect-ratio:1;border-radius:var(--border-radius-lg);object-fit:cover;position:relative;z-index:2;box-shadow:var(--shadow-lg);border:1px solid var(--glass-border)}}
.about-img-frame{{position:absolute;width:calc(100% - 40px);max-width:460px;aspect-ratio:1;border:2px solid var(--accent-orange);border-radius:var(--border-radius-lg);z-index:1;transform:translate(20px,20px);transition:var(--transition-smooth)}}
.about-img-wrapper:hover .about-img-frame{{transform:translate(10px,10px)}}
.about-badge{{position:absolute;bottom:30px;left:-15px;background:var(--bg-secondary);border:1px solid var(--glass-border);backdrop-filter:blur(10px);border-radius:var(--border-radius-md);padding:1rem 1.5rem;display:flex;align-items:center;gap:.8rem;z-index:3;box-shadow:var(--shadow-md)}}
.badge-icon{{width:36px;height:36px;border-radius:50%;background:rgba(255,77,36,.12);display:flex;align-items:center;justify-content:center;color:var(--accent-orange);font-size:1.1rem}}
.about-badge h5{{font-size:1.1rem;margin-bottom:.1rem}}.about-badge p{{font-size:.7rem;text-transform:uppercase;letter-spacing:.05em}}
/* GALLERY */
.gallery-section{{background:var(--bg-secondary)}}
.gallery-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:1rem}}
.gallery-item{{aspect-ratio:1;border-radius:var(--border-radius-md);overflow:hidden;border:1px solid var(--glass-border)}}
.gallery-item img{{width:100%;height:100%;object-fit:cover;transition:transform .5s ease}}
.gallery-item:hover img{{transform:scale(1.06)}}
/* PROGRAMS */
.programs-section{{background:var(--bg-secondary)}}
.programs-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:2rem;margin-top:5rem}}
.program-card{{background:var(--bg-tertiary);border:1px solid var(--glass-border);border-radius:var(--border-radius-md);padding:3rem 2.5rem;position:relative;overflow:hidden;transition:var(--transition-smooth);display:flex;flex-direction:column}}
.program-card::before{{content:'';position:absolute;inset:0;background:radial-gradient(circle at 100% 0%,var(--accent-orange-glow),transparent 60%);opacity:0;transition:var(--transition-smooth)}}
.program-card:hover{{transform:translateY(-8px);border-color:var(--glass-border-hover);box-shadow:var(--shadow-md)}}.program-card:hover::before{{opacity:1}}
.program-icon{{width:60px;height:60px;background:var(--bg-secondary);border:1px solid var(--glass-border);border-radius:var(--border-radius-sm);display:flex;align-items:center;justify-content:center;margin-bottom:2rem;font-size:1.8rem;transition:var(--transition-smooth);position:relative;z-index:1}}
.program-card:hover .program-icon{{background:var(--accent-orange);border-color:var(--accent-orange);box-shadow:var(--shadow-orange);transform:scale(1.08)}}
.program-card h3{{font-size:1.45rem;margin-bottom:.8rem;position:relative;z-index:1}}.program-card p{{font-size:.95rem;line-height:1.6;margin-bottom:2rem;position:relative;z-index:1}}
.program-link{{margin-top:auto;display:inline-flex;align-items:center;gap:.5rem;color:#fff;font-family:'Outfit',sans-serif;font-weight:700;font-size:.9rem;text-transform:uppercase;letter-spacing:.05em;transition:var(--transition-fast);position:relative;z-index:1}}
.program-card:hover .program-link{{color:var(--accent-orange)}}
/* TESTIMONIALS */
.testimonials-section{{padding:8rem 0}}
.t-slider-outer{{overflow:hidden;margin-top:4rem}}
.t-slider{{display:flex;gap:2rem;transition:transform .5s ease;cursor:grab}}
.t-slider.dragging{{cursor:grabbing;transition:none}}
.t-card{{background:var(--bg-secondary);border:1px solid var(--glass-border);border-radius:var(--border-radius-md);padding:2.5rem;flex:0 0 calc(33.333% - 1.33rem);min-width:280px}}
.t-stars{{color:var(--accent-orange);font-size:1rem;margin-bottom:1.2rem;letter-spacing:2px}}
.t-card p{{font-size:.95rem;line-height:1.7;margin-bottom:1.8rem;font-style:italic}}
.t-author{{font-family:'Outfit',sans-serif;font-weight:700;font-size:.9rem}}
.t-author span{{display:block;font-family:'Inter',sans-serif;font-weight:400;font-size:.8rem;color:var(--text-muted);margin-top:.3rem}}
.t-controls{{display:flex;align-items:center;justify-content:center;gap:1.5rem;margin-top:2.5rem}}
.t-btn{{width:44px;height:44px;border-radius:50%;background:var(--bg-secondary);border:1px solid var(--glass-border);color:#fff;cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:1rem;transition:var(--transition-fast)}}
.t-btn:hover{{background:var(--accent-orange);border-color:var(--accent-orange)}}
.t-dots{{display:flex;gap:.6rem}}
.t-dot{{width:8px;height:8px;border-radius:50%;background:var(--text-muted);cursor:pointer;transition:var(--transition-fast)}}.t-dot.active{{background:var(--accent-orange);width:20px;border-radius:4px}}
/* CTA */
.cta-section{{padding:8rem 0}}
.cta-banner{{background:var(--bg-secondary);border:1px solid var(--glass-border);border-radius:var(--border-radius-lg);padding:6rem 4rem;text-align:center;position:relative;overflow:hidden;box-shadow:var(--shadow-lg)}}
.cta-banner::before{{content:'';position:absolute;top:0;left:0;width:100%;height:4px;background:linear-gradient(90deg,var(--accent-orange),var(--accent-teal))}}
.cta-banner::after{{content:'';position:absolute;bottom:-100px;right:-100px;width:400px;height:400px;background:radial-gradient(circle,var(--accent-orange-glow),transparent 70%);pointer-events:none}}
.cta-banner h2{{font-size:3.2rem;max-width:700px;margin:0 auto 1.5rem;text-transform:uppercase}}
.cta-banner p{{font-size:1.1rem;max-width:550px;margin:0 auto 3rem}}
/* CONTACT */
.contact-section{{background:var(--bg-secondary)}}
.cinfo-grid{{display:flex;flex-wrap:wrap;gap:14px;justify-content:center;margin-top:3rem}}
.cinfo-item{{display:flex;align-items:center;gap:12px;background:var(--bg-tertiary);border:1px solid var(--glass-border);border-radius:var(--border-radius-sm);padding:16px 24px;color:var(--text-gray);font-size:.95rem;transition:var(--transition-fast)}}
.cinfo-item:hover{{border-color:var(--accent-orange);color:#fff}}
/* FOOTER */
.footer{{background:#050608;border-top:1px solid var(--glass-border);padding:6rem 0 3rem}}
.footer-grid{{display:grid;grid-template-columns:1.2fr .8fr .8fr;gap:4rem;margin-bottom:5rem}}
.footer-col h4{{font-size:1.1rem;margin-bottom:2rem;padding-bottom:.5rem;position:relative}}
.footer-col h4::after{{content:'';position:absolute;bottom:0;left:0;width:28px;height:2px;background:var(--accent-orange)}}
.footer-about p{{font-size:.9rem;margin-top:1.2rem;margin-bottom:2rem}}
.social-links{{display:flex;gap:1rem}}
.social-btn{{width:42px;height:42px;border-radius:var(--border-radius-sm);background:var(--bg-secondary);border:1px solid var(--glass-border);color:#fff;display:flex;align-items:center;justify-content:center;font-size:.75rem;font-weight:700;transition:var(--transition-smooth);text-decoration:none}}
.social-btn:hover{{background:var(--accent-orange);border-color:var(--accent-orange);transform:translateY(-3px)}}
.footer-links{{list-style:none}}.footer-links li{{margin-bottom:.9rem}}.footer-links a{{color:var(--text-gray);font-size:.9rem;transition:var(--transition-fast)}}.footer-links a:hover{{color:#fff;padding-left:5px}}
.footer-bottom{{border-top:1px solid var(--glass-border);padding-top:3rem;display:flex;justify-content:space-between;align-items:center}}
.footer-bottom p{{font-size:.85rem;color:var(--text-muted)}}
.footer-bottom a{{color:var(--accent-orange)}}
@media(max-width:991px){{.about-grid{{grid-template-columns:1fr;gap:3rem}}.about-img-wrapper{{order:-1}}.hamburger{{display:block}}.nav-links{{position:fixed;top:0;right:-100%;width:300px;height:100vh;background:var(--bg-secondary);border-left:1px solid var(--glass-border);flex-direction:column;padding:100px 2.5rem;gap:2rem;transition:var(--transition-smooth);z-index:1000}}.nav-links.active{{right:0}}.nav-actions{{margin-right:3rem}}.gallery-grid{{grid-template-columns:repeat(2,1fr)}}}}
@media(max-width:768px){{.hero-name,.hero-subtitle-track span{{font-size:2.8rem}}.hero-subtitle-wrapper{{height:3.5rem}}.section-title{{font-size:2.1rem}}.programs-grid{{grid-template-columns:1fr}}.t-card{{flex:0 0 calc(100% - 1rem)}}.stats-grid{{grid-template-columns:repeat(2,1fr)}}.cta-banner{{padding:3.5rem 1.5rem}}.cta-banner h2{{font-size:2.2rem}}.footer-grid{{grid-template-columns:1fr;gap:2.5rem}}.footer-bottom{{flex-direction:column;gap:1rem;text-align:center}}.gallery-grid{{grid-template-columns:repeat(2,1fr)}}}}
@media(max-width:480px){{.hero-name,.hero-subtitle-track span{{font-size:2.2rem}}.stats-grid{{grid-template-columns:1fr 1fr}}}}
</style>
</head>
<body>

<!-- Custom cursor -->
<div class="custom-cursor-dot" id="cursorDot"></div>
<div class="custom-cursor-ring" id="cursorRing"></div>

<!-- Demo banner -->
<div class="demo-banner">
  ✨ FREE demo built for {name} by Chandan Gosavi &mdash;
  <a href="https://www.fiverr.com/s/e6zGy4g" target="_blank">hire me to take it live &rarr;</a>
  <span class="orig">{orig_note}</span>
</div>

<!-- Spotlights -->
<div class="spotlight" style="top:-100px;left:-150px"></div>
<div class="spotlight" style="top:40%;right:-200px;background:radial-gradient(circle,var(--accent-teal-glow),transparent 70%)"></div>
<div class="spotlight" style="bottom:10%;left:-100px"></div>

<!-- Navbar -->
<nav class="navbar" id="navbar">
  <div class="container nav-container">
    <a href="#home" class="logo">
      <div class="logo-icon"></div>
      {logo_p1}{'<span>' + logo_p2 + '</span>' if logo_p2 else ''}
    </a>
    <ul class="nav-links" id="navLinks">
      <li><a href="#home" class="active">Home</a></li>
      <li><a href="#about">About</a></li>
      <li><a href="#programs">Programs</a></li>
      {'<li><a href="#gallery">Gallery</a></li>' if gallery_imgs else ''}
      <li><a href="#contact">Contact</a></li>
    </ul>
    <div class="nav-actions">
      <a href="#contact" class="btn btn-secondary" style="padding:.6rem 1.5rem;font-size:.85rem">Join Now</a>
    </div>
    <button class="hamburger" id="hamburger" aria-label="Menu">
      <span></span><span></span><span></span>
    </button>
  </div>
</nav>

<!-- Hero -->
<section class="hero" id="home">
  <div class="container">
    <div class="hero-content reveal reveal-slide-up">
      <div class="hero-tag">&#x2022; Redefine Your Limits</div>
      <h1 class="hero-name text-gradient-orange">{name}</h1>
      <div class="hero-subtitle-wrapper">
        <div class="hero-subtitle-track">
          <span>{phrase1}</span>
          <span>{phrase2}</span>
          <span>{phrase3}</span>
        </div>
      </div>
      <p class="hero-desc">{about_text[:200]}{"…" if len(about_text) > 200 else ""}</p>
      <div class="hero-btns">
        <a href="#contact" class="btn btn-primary">Get Started Today</a>
        <a href="#programs" class="btn btn-secondary">Explore Programs</a>
      </div>
    </div>
  </div>
</section>

<!-- Stats bar -->
<section class="stats" id="stats">
  <div class="container">
    <div class="stats-grid reveal reveal-scale-in">
      <div class="stat-item">
        <div class="stat-number text-gradient-orange" data-target="{review_stat}">{review_stat}</div>
        <div class="stat-label">Google Reviews</div>
      </div>
      <div class="stat-item">
        <div class="stat-number text-gradient-orange">{rating_val}&#9733;</div>
        <div class="stat-label">Google Rating</div>
      </div>
      <div class="stat-item">
        <div class="stat-number text-gradient-orange">24/7</div>
        <div class="stat-label">Access Available</div>
      </div>
      <div class="stat-item">
        <div class="stat-number text-gradient-orange">100%</div>
        <div class="stat-label">Committed to You</div>
      </div>
    </div>
  </div>
</section>

<!-- About -->
<section class="about" id="about">
  <div class="container">
    <div class="about-grid">
      <div class="about-content reveal reveal-slide-right">
        <span class="section-tag">Who We Are</span>
        <h2 class="section-title">Where Strength Is<br><span class="text-gradient-orange">Forged</span> &amp; Limits Shattered</h2>
        <p class="section-desc">{about_text}</p>
        <div class="about-features">
          <div class="about-feature">
            <div class="about-feature-icon">\U0001f3cb️</div>
            <div><h4>Elite Equipment</h4><p>State-of-the-art machines and free weights for every level.</p></div>
          </div>
          <div class="about-feature">
            <div class="about-feature-icon">⏰</div>
            <div><h4>Flexible Hours</h4><p>Open early mornings, late nights &amp; weekends.</p></div>
          </div>
          <div class="about-feature">
            <div class="about-feature-icon">\U0001f465</div>
            <div><h4>Expert Coaches</h4><p>Certified trainers to guide every step of your journey.</p></div>
          </div>
          <div class="about-feature">
            <div class="about-feature-icon">\U0001f4aa</div>
            <div><h4>Real Results</h4><p>Proven programs built around your goals, not ours.</p></div>
          </div>
        </div>
      </div>
      <div class="about-img-wrapper reveal reveal-slide-left">
        <div class="about-img-frame"></div>
        {about_img_html}
        <div class="about-badge">
          <div class="badge-icon">✓</div>
          <div><h5>{rating_val}&#9733; Rated</h5><p>On Google Maps</p></div>
        </div>
      </div>
    </div>
  </div>
</section>

{gallery_section}

<!-- Programs -->
<section class="programs-section" id="programs">
  <div class="container">
    <div style="text-align:center">
      <span class="section-tag">{prog_tag}</span>
      <h2 class="section-title" style="max-width:700px;margin:.5rem auto 0">{prog_title}</h2>
      <p class="section-desc" style="max-width:580px;margin:1.5rem auto 0">{prog_desc}</p>
    </div>
    <div class="programs-grid">{{prog_cards}}</div>
  </div>
</section>

<!-- Testimonials -->
<section class="testimonials-section" id="testimonials">
  <div class="container">
    <div style="text-align:center">
      <span class="section-tag">{testi_tag}</span>
      <h2 class="section-title" style="max-width:700px;margin:.5rem auto 0">{testi_title}</h2>
    </div>
    <div class="t-slider-outer">
      <div class="t-slider" id="tSlider">
        <div class="t-card">
          <div class="t-stars">&#9733;&#9733;&#9733;&#9733;&#9733;</div>
          <p>{testi_1}</p>
          <div class="t-author">Sarah M.<span>Member since 2023</span></div>
        </div>
        <div class="t-card">
          <div class="t-stars">&#9733;&#9733;&#9733;&#9733;&#9733;</div>
          <p>{testi_2}</p>
          <div class="t-author">James K.<span>Member since 2022</span></div>
        </div>
        <div class="t-card">
          <div class="t-stars">&#9733;&#9733;&#9733;&#9733;&#9733;</div>
          <p>{testi_3}</p>
          <div class="t-author">Priya R.<span>Member since 2024</span></div>
        </div>
        <div class="t-card">
          <div class="t-stars">&#9733;&#9733;&#9733;&#9733;&#9733;</div>
          <p>{testi_4}</p>
          <div class="t-author">Ahmed N.<span>Member since 2023</span></div>
        </div>
      </div>
    </div>
    <div class="t-controls">
      <button class="t-btn" id="tPrev">&larr;</button>
      <div class="t-dots" id="tDots"></div>
      <button class="t-btn" id="tNext">&rarr;</button>
    </div>
  </div>
</section>

<!-- CTA -->
<section class="cta-section">
  <div class="container">
    <div class="cta-banner reveal reveal-scale-in">
      <span class="section-tag">Are You Ready?</span>
      <h2>Start Your Journey at<br><span class="text-gradient-orange">{name}</span> Today</h2>
      <p>Take the first step. Contact us now and let's build the strongest version of you.</p>
      <a href="#contact" class="btn btn-primary" style="margin-top:.5rem">Contact Us Now</a>
    </div>
  </div>
</section>

<!-- Contact -->
<section class="contact-section" id="contact">
  <div class="container" style="text-align:center">
    <span class="section-tag">Find Us</span>
    <h2 class="section-title" style="margin:.5rem auto 1rem">Get in Touch with <span class="text-gradient-orange">{name}</span></h2>
    <p>We'd love to hear from you. Walk in, call, or message us anytime.</p>
    <div class="cinfo-grid">{contact_items or '<div class="cinfo-item">\U0001f4ec Contact us today</div>'}</div>
  </div>
</section>

<!-- Footer -->
<footer class="footer">
  <div class="container">
    <div class="footer-grid">
      <div class="footer-col footer-about">
        <a href="#home" class="logo" style="font-size:1.5rem">
          <div class="logo-icon"></div>
          {logo_p1}{'<span>' + logo_p2 + '</span>' if logo_p2 else ''}
        </a>
        <p>A premier fitness facility committed to building strength, endurance, and an unstoppable mindset in {city}.</p>
        <div class="social-links">{ig_link}{map_btn}</div>
      </div>
      <div class="footer-col">
        <h4>Quick Links</h4>
        <ul class="footer-links">
          <li><a href="#home">Home</a></li>
          <li><a href="#about">About</a></li>
          <li><a href="#programs">Programs</a></li>
          <li><a href="#contact">Contact</a></li>
        </ul>
      </div>
      <div class="footer-col">
        <h4>Contact</h4>
        <ul class="footer-links">
          {f'<li>{phone}</li>' if phone else ''}
          {f'<li>{email}</li>' if email else ''}
          {f'<li>{address}</li>' if address else ''}
        </ul>
      </div>
    </div>
    <div class="footer-bottom">
      <p>&copy; 2025 {name}. Demo by <a href="https://www.fiverr.com/s/e6zGy4g" target="_blank">Chandan Gosavi</a></p>
      <p>Want this live? <a href="https://www.fiverr.com/s/e6zGy4g" target="_blank">Order here &rarr;</a></p>
    </div>
  </div>
</footer>

<script>
// Custom cursor
const dot=document.getElementById('cursorDot'),ring=document.getElementById('cursorRing');
let mx=0,my=0,rx=0,ry=0;
document.addEventListener('mousemove',e=>{{mx=e.clientX;my=e.clientY;dot.style.left=mx+'px';dot.style.top=my+'px'}});
(function animRing(){{rx+=(mx-rx)*.15;ry+=(my-ry)*.15;ring.style.left=rx+'px';ring.style.top=ry+'px';requestAnimationFrame(animRing)}})();
document.querySelectorAll('a,button,.program-card,.t-btn,.gallery-item').forEach(el=>{{
  el.addEventListener('mouseenter',()=>document.body.classList.add('cursor-hover'));
  el.addEventListener('mouseleave',()=>document.body.classList.remove('cursor-hover'));
}});

// Navbar scroll + active link
const navbar=document.getElementById('navbar');
const sections=document.querySelectorAll('section[id]');
function onScroll(){{
  navbar.classList.toggle('scrolled',scrollY>50);
  let cur='';
  sections.forEach(s=>{{if(scrollY>=s.offsetTop-200)cur=s.id}});
  document.querySelectorAll('.nav-links a').forEach(a=>a.classList.toggle('active',a.getAttribute('href')==='#'+cur));
}}
window.addEventListener('scroll',onScroll,{{passive:true}});

// Hamburger
const hamburger=document.getElementById('hamburger'),navLinks=document.getElementById('navLinks');
hamburger.addEventListener('click',()=>{{hamburger.classList.toggle('active');navLinks.classList.toggle('active')}});
navLinks.querySelectorAll('a').forEach(a=>a.addEventListener('click',()=>{{hamburger.classList.remove('active');navLinks.classList.remove('active')}}));

// Scroll reveal
const revObs=new IntersectionObserver(entries=>entries.forEach(e=>{{if(e.isIntersecting){{e.target.classList.add('revealed');revObs.unobserve(e.target)}}}},{{threshold:0.1}}));
document.querySelectorAll('.reveal').forEach(el=>revObs.observe(el));

// Testimonials slider
(function(){{
  const slider=document.getElementById('tSlider'),dotsEl=document.getElementById('tDots');
  const cards=Array.from(slider.children);
  let cur=0,startX=0,dragX=0,isDrag=false;
  function visible(){{return window.innerWidth>991?3:window.innerWidth>600?2:1}}
  function buildDots(){{
    const pages=Math.ceil(cards.length/visible());
    dotsEl.innerHTML='';
    for(let i=0;i<pages;i++){{
      const d=document.createElement('div');d.className='t-dot'+(i===Math.floor(cur/visible())?' active':'');
      d.addEventListener('click',()=>goto(i*visible()));dotsEl.appendChild(d);
    }}
  }}
  function goto(n){{
    const max=cards.length-visible();cur=Math.max(0,Math.min(n,max));
    const w=cards[0].offsetWidth+32;slider.style.transform=`translateX(${{-cur*w}}px)`;
    buildDots();
  }}
  document.getElementById('tPrev').addEventListener('click',()=>goto(cur-visible()));
  document.getElementById('tNext').addEventListener('click',()=>goto(cur+visible()));
  slider.addEventListener('mousedown',e=>{{isDrag=true;startX=e.clientX;slider.classList.add('dragging')}});
  window.addEventListener('mousemove',e=>{{if(isDrag)dragX=e.clientX-startX}});
  window.addEventListener('mouseup',()=>{{
    if(!isDrag)return;isDrag=false;slider.classList.remove('dragging');
    const w=cards[0].offsetWidth+32;if(Math.abs(dragX)>w*.25)goto(dragX<0?cur+visible():cur-visible());else goto(cur);
    dragX=0;
  }});
  slider.addEventListener('touchstart',e=>{{startX=e.touches[0].clientX}},{{passive:true}});
  slider.addEventListener('touchend',e=>{{
    const dx=e.changedTouches[0].clientX-startX;
    const w=cards[0].offsetWidth+32;if(Math.abs(dx)>w*.25)goto(dx<0?cur+visible():cur-visible());
  }},{{passive:true}});
  buildDots();
  window.addEventListener('resize',()=>goto(0));
}})();
</script>


{cta_block(business)}

{_track_pixel(business)}

</body>
</html>"""



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
            else:
                hero_img, about_img = _STOCK_HERO, _STOCK_ABOUT

            t = Template(template_str)
            custom_html = t.render(
                lead=business, 
                scraped=website_data, 
                hero_img=hero_img, 
                about_img=about_img
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
    # For now, we wrap the generic demo HTML to satisfy the import. 
    # In a full implementation, you could build a distinct Jinja template for SaaS.
    return generate_demo_html(business)
