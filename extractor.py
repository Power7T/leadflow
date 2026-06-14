"""
Contact extractor — finds email, Instagram, LinkedIn, WhatsApp
from a business website and Google search results.
"""
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
IG_RE = re.compile(r"instagram\.com/([a-zA-Z0-9_.]+)", re.IGNORECASE)
WHATSAPP_RE = re.compile(r"wa\.me/(\d+)", re.IGNORECASE)
LINKEDIN_RE = re.compile(r"linkedin\.com/in/([a-zA-Z0-9\-]+)", re.IGNORECASE)

# Emails to ignore (generic/support)
EMAIL_BLACKLIST = {
    "support", "noreply", "no-reply", "admin", "webmaster",
    "privacy", "legal", "abuse", "sales@example", "test@",
}


def _fetch(url: str, timeout: int = 8) -> str:
    """Fetch URL, return HTML text or empty string."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        if r.status_code == 200:
            return r.text
    except Exception:
        pass
    return ""


def _clean_email(email: str) -> str | None:
    email = email.lower().strip()
    if any(b in email for b in EMAIL_BLACKLIST):
        return None
    # Skip image files mistaken for emails
    if any(email.endswith(ext) for ext in (".png", ".jpg", ".gif", ".svg")):
        return None
    return email


def extract_from_website(url: str) -> dict:
    """Scrape email, Instagram, WhatsApp, LinkedIn from website."""
    contacts = {}
    if not url:
        return contacts

    if not url.startswith("http"):
        url = "https://" + url

    html = _fetch(url)
    if not html:
        return contacts

    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ")
    all_links = " ".join(a.get("href", "") for a in soup.find_all("a", href=True))
    full_text = html + " " + all_links

    # Email
    emails = EMAIL_RE.findall(full_text)
    for e in emails:
        cleaned = _clean_email(e)
        if cleaned:
            contacts["email"] = cleaned
            break

    # If no email found on homepage, try /contact page
    if not contacts.get("email"):
        for slug in ("/contact", "/contact-us", "/about", "/reach-us"):
            contact_html = _fetch(url.rstrip("/") + slug)
            if contact_html:
                found = EMAIL_RE.findall(contact_html)
                for e in found:
                    cleaned = _clean_email(e)
                    if cleaned:
                        contacts["email"] = cleaned
                        break
            if contacts.get("email"):
                break

    # Instagram
    ig = IG_RE.search(full_text)
    if ig and ig.group(1).lower() not in ("p", "reel", "explore", "accounts"):
        contacts["instagram"] = ig.group(1)

    # WhatsApp
    wa = WHATSAPP_RE.search(full_text)
    if wa:
        contacts["whatsapp"] = "+" + wa.group(1)

    # LinkedIn (personal profile of owner, not company page)
    li = LINKEDIN_RE.search(full_text)
    if li:
        handle = li.group(1)
        contacts["linkedin_name"] = handle
        contacts["linkedin_url"] = f"https://linkedin.com/in/{handle}"

    return contacts


def google_search_contacts(business_name: str, location: str) -> dict:
    """
    Fallback: use Google search to find Instagram/email when not on site.
    Uses a simple search scrape (no API needed).
    """
    contacts = {}
    query = f"{business_name} {location} instagram OR email contact"
    search_url = f"https://www.google.com/search?q={requests.utils.quote(query)}"

    html = _fetch(search_url)
    if not html:
        return contacts

    # Instagram from search results
    ig = IG_RE.search(html)
    if ig and ig.group(1).lower() not in ("p", "reel", "explore", "accounts"):
        contacts.setdefault("instagram", ig.group(1))

    # Email from search snippets
    emails = EMAIL_RE.findall(html)
    for e in emails:
        cleaned = _clean_email(e)
        if cleaned:
            contacts.setdefault("email", cleaned)
            break

    return contacts


def extract_contacts(website: str, business_name: str, location: str) -> dict:
    """
    Full contact extraction pipeline:
    1. Scrape website
    2. Fallback to Google search for missing fields
    """
    contacts = extract_from_website(website)

    # Fill gaps with Google search
    if not contacts.get("email") or not contacts.get("instagram"):
        fallback = google_search_contacts(business_name, location)
        for key, val in fallback.items():
            contacts.setdefault(key, val)

    return contacts
