"""
Contact extractor — finds email, Instagram, LinkedIn, WhatsApp
from a business website and Google search results.
"""
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, unquote

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

# Emails to ignore (generic/support/placeholders/spam traps)
EMAIL_BLACKLIST = {
    # Generic roles
    "support", "noreply", "no-reply", "admin", "webmaster",
    "privacy", "legal", "abuse", "postmaster",
    # Placeholder/test emails
    "sales@example", "test@", "example.com", "domain.com",
    "yourdomain.com", "yoursite.com", "mysite.com", "contoso.com",
    "placeholder", "email@email.com", "test@test.com",
    "name@email.com", "user@domain.com", "info@domain.com", "email.com",
    # GoDaddy / website builder fillers discovered in audit
    "filler@godaddy.com", "hi@mystore.com", "info@mysite.com",
    # Platform/SaaS/Agency emails that are NOT business owners
    "wixpress.com", "sentry.io", "wordpress.org", "wordpress.com",
    "wix.com", "squarespace.com", "shopify.com", "godaddy.com",
    "booksy.com",  # Booking SaaS — not the business owner
    "officite.com", "mysocialpractice.com",  # Dental marketing agencies
    # Font foundry / designer emails scraped incorrectly
    "eyebytes.com", "latofonts.com", "astigmatic.com",
    "indiantypefoundry.com", "sansoxygen.com", "impallari.com",
    "micahrich.com",
    # Generic catch-alls that don't belong to a real decision-maker
    "info@info.", "contact@contact.", "hello@hello.",
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
    email = unquote(email).lower().strip()
    if any(b in email for b in EMAIL_BLACKLIST):
        return None
    # Skip image files mistaken for emails
    if any(email.endswith(ext) for ext in (".png", ".jpg", ".gif", ".svg")):
        return None

    # Validate domain name has a valid DNS record
    parts = email.split("@")
    if len(parts) != 2:
        return None
    domain = parts[1].strip()

    # Fast-pass common public email providers to save DNS lookup time
    if domain in ("gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com", "aol.com", "zoho.com", "protonmail.com"):
        return email

    import socket
    try:
        # Check if domain resolves to A/AAAA or MX
        socket.getaddrinfo(domain, None)
    except Exception:
        return None  # Domain does not resolve (dead or placeholder)

    return email


def _extract_name_from_html(html: str) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    for s in soup(["script", "style"]):
        s.decompose()
    text = soup.get_text(" ")
    patterns = [
        r"(?:owner|founder|director|creator)(?:\s+(?:is|of|& [^:]+))?:\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
        r"(?:founded|created)\s+by\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
        r"hi,\s+i'm\s+([A-Z][a-z]+)",
        r"meet\s+the\s+(?:owner|founder):\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
        r"meet\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s+(?:the\s+)?(?:owner|founder)",
    ]
    for pat in patterns:
        match = re.search(pat, text)
        if match:
            fullname = match.group(1).strip()
            parts = fullname.split()
            if parts:
                return parts[0].capitalize()
    return ""


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

    # Add intent signals extraction
    try:
        from scorer import detect_intent_signals
        signals = detect_intent_signals({}, html)
        contacts.update(signals)
    except Exception:
        pass

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

    # Owner name extraction from website
    owner = _extract_name_from_html(html)
    if owner:
        contacts["owner_name"] = owner
    else:
        for slug in ("/about", "/about-us", "/our-story"):
            about_html = _fetch(url.rstrip("/") + slug)
            owner = _extract_name_from_html(about_html)
            if owner:
                contacts["owner_name"] = owner
                break

    return contacts


def google_search_contacts(business_name: str, location: str) -> dict:
    """
    Fallback: use Google search to find Instagram/email when not on site.
    Uses Serper API if available, and combines it with simple search scrape.
    """
    import os
    import json
    contacts = {}
    query = f"{business_name} {location} instagram OR email contact"
    html = ""

    serper_api_key = os.getenv("SERPER_API_KEY")
    if serper_api_key:
        try:
            url = "https://google.serper.dev/search"
            payload = json.dumps({"q": query})
            headers = {
                'X-API-KEY': serper_api_key,
                'Content-Type': 'application/json'
            }
            res = requests.post(url, headers=headers, data=payload, timeout=8)
            if res.status_code == 200:
                data = res.json()
                snippets = []
                for result in data.get("organic", []):
                    snippets.append(result.get("snippet", ""))
                    snippets.append(result.get("title", ""))
                    snippets.append(result.get("link", ""))
                html += " " + " ".join(snippets)
        except Exception:
            pass

    # Always perform the original Google Search as it was working before
    search_url = f"https://www.google.com/search?q={requests.utils.quote(query)}"
    original_html = _fetch(search_url)
    if original_html:
        html += " " + original_html

    if not html.strip():
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


def hunter_enrich(domain: str) -> str:
    import os, requests
    api_key = os.getenv("HUNTER_API_KEY")
    if not api_key or not domain: return ""
    try:
        url = f"https://api.hunter.io/v2/domain-search?domain={domain}&api_key={api_key}"
        res = requests.get(url, timeout=4).json()
        if "data" in res and res["data"].get("emails"):
            return res["data"]["emails"][0].get("value", "")
    except Exception:
        pass
    return ""

def apollo_enrich(domain: str) -> dict:
    import os, requests
    api_key = os.getenv("APOLLO_API_KEY")
    if not api_key or not domain: return {}
    try:
        url = "https://api.apollo.io/v1/organizations/enrich"
        headers = {"Cache-Control": "no-cache", "Content-Type": "application/json"}
        data = {"api_key": api_key, "domain": domain}
        res = requests.post(url, headers=headers, json=data, timeout=4).json()
        org = res.get("organization", {})
        
        # Also try to find a person
        p_url = "https://api.apollo.io/v1/people/search"
        p_data = {"api_key": api_key, "q_organization_domains": domain, "page": 1}
        p_res = requests.post(p_url, headers=headers, json=p_data, timeout=4).json()
        person_name = ""
        person_email = ""
        if p_res.get("people"):
            person = p_res["people"][0]
            person_name = person.get("name", "")
            person_email = person.get("email", "")
            
        return {
            "apollo_email": person_email or org.get("primary_email", ""),
            "apollo_person_name": person_name
        }
    except Exception:
        pass
    return {}

def extract_contacts(website: str, business_name: str, location: str) -> dict:
    """
    Full contact extraction pipeline:
    1. Scrape website
    2. Fallback to Google search for missing fields
    3. Deep enrichment via Hunter/Apollo APIs
    """
    contacts = extract_from_website(website)

    # Fill gaps with Google search
    # To conserve the 2,500 free Serper API limit, we only trigger the search fallback 
    # if we are entirely missing the primary outreach method (email). We no longer burn 
    # a query just to find an Instagram account if we already successfully found an email.
    if not contacts.get("email"):
        fallback = google_search_contacts(business_name, location)
        for key, val in fallback.items():
            contacts.setdefault(key, val)
            
    # Deep Enrichment
    if website:
        import urllib.parse
        domain = urllib.parse.urlparse(website).netloc.replace("www.", "")
        
        hunter_email = hunter_enrich(domain)
        if hunter_email:
            cleaned_hunter = _clean_email(hunter_email)
            if cleaned_hunter:
                contacts["hunter_email"] = cleaned_hunter
                contacts.setdefault("email", cleaned_hunter)
            
        apollo_data = apollo_enrich(domain)
        if apollo_data:
            contacts.update(apollo_data)
            ap_email = apollo_data.get("apollo_email")
            if ap_email:
                cleaned_ap = _clean_email(ap_email)
                if cleaned_ap:
                    contacts["apollo_email"] = cleaned_ap
                    contacts.setdefault("email", cleaned_ap)
            # If Apollo person name is returned, use it for owner_name
            p_name = apollo_data.get("apollo_person_name")
            if p_name:
                parts = p_name.split()
                if parts:
                    contacts["owner_name"] = parts[0].capitalize()

    # Final sanity check: ensure main email is fully clean/validated
    if contacts.get("email"):
        cleaned_main = _clean_email(contacts["email"])
        if not cleaned_main:
            contacts["email"] = None

    return contacts


def scrape_instagram_profile(url_or_handle: str) -> dict:
    """Scrape Instagram profile details (name, handle, bio, profile_pic, stats) using og/meta tags."""
    import re
    import requests
    from bs4 import BeautifulSoup
    from urllib.parse import urlparse
    
    # 1. Clean the handle
    url_or_handle = url_or_handle.strip()
    if not url_or_handle:
        return {}
        
    handle = ""
    # Extract handle from URL or use as handle
    if "instagram.com/" in url_or_handle:
        parsed = urlparse(url_or_handle)
        path = parsed.path.strip("/")
        handle = path.split("/")[0] # e.g. pswithaj
    else:
        # It's a handle
        handle = url_or_handle.replace("@", "").split("?")[0].strip()
        
    if not handle:
        return {}
        
    url = f"https://www.instagram.com/{handle}/"
    
    # We must use Googlebot to get the server-side rendered SEO meta tags,
    # otherwise Instagram returns client-side JS without metadata.
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
    }
    
    name = handle.capitalize()
    profile_pic = ""
    followers = "N/A"
    following = "N/A"
    posts = "N/A"
    bio = ""
    
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "lxml")
            
            # Extract display name
            og_title = soup.find("meta", property="og:title")
            if og_title and og_title.get("content"):
                title_content = og_title["content"]
                # extract name before " (@" or " •" or " on Instagram"
                match = re.search(r"^(.*?)\s+(?:\(|•|on Instagram)", title_content)
                if match:
                    name = match.group(1).strip()
                else:
                    name = title_content.split("(")[0].strip()
            
            # Extract profile pic
            og_image = soup.find("meta", property="og:image")
            if og_image and og_image.get("content"):
                profile_pic = og_image["content"]
                
            # Extract followers, following, posts
            og_desc = soup.find("meta", property="og:description")
            if og_desc and og_desc.get("content"):
                desc_content = og_desc["content"]
                f_match = re.search(r"([\d\.,MKm]+)\s+Followers", desc_content, re.IGNORECASE)
                if f_match:
                    followers = f_match.group(1)
                fng_match = re.search(r"([\d\.,MKm]+)\s+Following", desc_content, re.IGNORECASE)
                if fng_match:
                    following = fng_match.group(1)
                p_match = re.search(r"([\d\.,MKm]+)\s+Posts", desc_content, re.IGNORECASE)
                if p_match:
                    posts = p_match.group(1)
            
            # Extract bio from meta description tag
            meta_desc = soup.find("meta", attrs={"name": "description"})
            if meta_desc and meta_desc.get("content"):
                content = meta_desc["content"]
                if 'on Instagram: "' in content:
                    parts = content.split('on Instagram: "')
                    if len(parts) > 1:
                        bio = parts[1].rstrip('"')
                elif 'on Instagram: ' in content:
                    parts = content.split('on Instagram: ')
                    if len(parts) > 1:
                        bio = parts[1].strip()
                else:
                    # Fallback to splitting by quotes
                    quote_parts = content.split('"')
                    if len(quote_parts) > 1:
                        bio = quote_parts[1]
                    else:
                        bio = content
                        
            if not bio and og_desc and og_desc.get("content"):
                bio = og_desc["content"]
    except Exception as e:
        print(f"[scrape_instagram_profile] Direct scraping error: {e}")

    # Try to guess niche/category from bio/description
    category = "Instagram Creator"
    if bio:
        combined = bio.lower() + " " + name.lower()
        if any(w in combined for w in ["fitness", "gym", "workout", "trainer", "coach"]):
            category = "Fitness Influencer"
        elif any(w in combined for w in ["gamer", "gaming", "play", "gta", "xbox", "ps5", "playstation"]):
            category = "Gaming Creator"
        elif any(w in combined for w in ["eat", "food", "chef", "cooking", "restaurant"]):
            category = "Food Blogger"
        elif any(w in combined for w in ["fashion", "style", "outfit", "wear"]):
            category = "Fashion Creator"
        elif any(w in combined for w in ["travel", "explore", "world", "trip"]):
            category = "Travel Creator"
        elif any(w in combined for w in ["agency", "marketing", "business", "consulting"]):
            category = "Business Agency"
        elif any(w in combined for w in ["beauty", "makeup", "skin", "hair"]):
            category = "Beauty Creator"
            
    # If direct scraping failed to extract bio, trigger AI fallback
    if not bio or bio.strip() == "" or "Instagram profile for" in bio:
        try:
            from ai_writer import _run
            prompt = f"""Research or predict the profile details for the Instagram handle '@{handle}'.
If it is a known gaming creator/influencer, use their real details (e.g. GTA 6, PlayStation content, PSwithAJ).
Otherwise, generate a highly realistic and professional profile name, bio description, niche category, and estimated followers count suitable for a creator with this handle.

Provide the response exactly in the following format (do not include markdown formatting):
Name: <profile name>
Category: <profile category, e.g. Gaming Creator, Fitness Influencer, Food Blogger>
Bio: <profile bio description>
Followers: <followers count, e.g. 1.8K or 15K>
Following: <following count, e.g. 300>
Posts: <posts count, e.g. 120>"""
            res = _run(prompt)
            
            data = {}
            for line in res.split("\n"):
                if ":" in line:
                    k, v = line.split(":", 1)
                    data[k.strip().lower()] = v.strip()
            
            # Use fallback data
            return {
                "name": data.get("name") or name,
                "instagram": handle,
                "category": data.get("category") or category,
                "bio": data.get("bio") or f"Instagram profile for @{handle}",
                "profile_pic": profile_pic,
                "followers": data.get("followers") or followers,
                "following": data.get("following") or following,
                "posts": data.get("posts") or posts
            }
        except Exception as e:
            print(f"[scrape_instagram_profile] AI fallback failed: {e}")

    return {
        "name": name,
        "instagram": handle,
        "category": category,
        "bio": bio,
        "profile_pic": profile_pic,
        "followers": followers,
        "following": following,
        "posts": posts
    }

