"""
Multi-source business finder — Yelp scraper + domain availability check.
Supplements Google Maps with additional leads.
"""
import re
import socket
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}


# ── Domain availability ────────────────────────────────────────────────────

def check_domain_available(business_name: str) -> dict:
    """
    Check if the .com domain for a business name is available.
    Returns dict with: domain, available (bool), checked (bool)
    """
    slug = re.sub(r"[^a-z0-9]", "", business_name.lower().replace(" ", ""))
    domain = f"{slug}.com"

    try:
        socket.gethostbyname(domain)
        return {"domain": domain, "available": False, "checked": True}
    except socket.gaierror:
        # Domain doesn't resolve — likely available
        return {"domain": domain, "available": True, "checked": True}
    except Exception:
        return {"domain": domain, "available": None, "checked": False}


# ── Yelp scraper ───────────────────────────────────────────────────────────

def scrape_yelp(niche: str, location: str, max_results: int = 20) -> list[dict]:
    """
    Scrape Yelp search results for businesses.
    Returns list of business dicts compatible with our DB schema.
    """
    results = []
    query = quote(niche)
    loc   = quote(location)
    url   = f"https://www.yelp.com/search?find_desc={query}&find_loc={loc}&limit=30"

    try:
        resp = requests.get(url, headers=HEADERS, timeout=12)
        if resp.status_code != 200:
            return []

        soup = BeautifulSoup(resp.text, "lxml")

        # Yelp biz cards — find structured data first (most reliable)
        import json
        scripts = soup.find_all("script", type="application/ld+json")
        for script in scripts:
            try:
                data = json.loads(script.string or "")
                if isinstance(data, list):
                    items = data
                elif data.get("@type") == "ItemList":
                    items = data.get("itemListElement", [])
                else:
                    continue

                for item in items:
                    biz = item.get("item", item)
                    if not biz.get("name"):
                        continue

                    addr = biz.get("address", {})
                    address_str = ", ".join(filter(None, [
                        addr.get("streetAddress", ""),
                        addr.get("addressLocality", ""),
                        addr.get("addressRegion", ""),
                        addr.get("addressCountry", ""),
                    ]))

                    rating_val = None
                    reviews_val = None
                    agg = biz.get("aggregateRating", {})
                    if agg:
                        rating_val  = agg.get("ratingValue")
                        reviews_val = agg.get("reviewCount")

                    results.append({
                        "name":          biz.get("name", ""),
                        "address":       address_str,
                        "city":          addr.get("addressLocality", ""),
                        "country":       addr.get("addressCountry", ""),
                        "phone":         biz.get("telephone", ""),
                        "website":       biz.get("url", ""),
                        "google_rating": float(rating_val) if rating_val else None,
                        "google_reviews": int(reviews_val) if reviews_val else None,
                        "source":        "yelp",
                    })

                    if len(results) >= max_results:
                        break
            except Exception:
                continue

            if len(results) >= max_results:
                break

    except Exception:
        pass

    return results[:max_results]
