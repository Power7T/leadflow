"""
Business finder — uses Google Maps Places API to find businesses
by niche and location, then scores and saves them.
"""
import os
import time
import requests
from urllib.parse import urlparse, urlunparse
from rich.console import Console
from dotenv import load_dotenv
from database import insert_business, insert_contacts
from analyzer import score_website, detect_gap
from extractor import extract_contacts
from scorer import score_lead
from multi_finder import check_domain_available
import aiohttp
import asyncio

load_dotenv()
console = Console()

MAPS_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")
PLACES_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"

# Domains that are not real business websites
FAKE_WEBSITE_DOMAINS = {
    "instagram.com", "www.instagram.com",
    "facebook.com", "www.facebook.com", "m.facebook.com",
    "linktr.ee", "www.linktr.ee",
    "twitter.com", "x.com",
    "youtube.com", "www.youtube.com",
    "yelp.com", "www.yelp.com",
    "tripadvisor.com", "www.tripadvisor.com",
    "zomato.com", "www.zomato.com",
    "grubhub.com", "www.grubhub.com",
    "doordash.com", "www.doordash.com",
    "ubereats.com", "www.ubereats.com",
}

# If review count is above this, likely a big chain — skip
MAX_REVIEWS_FOR_LEAD = 2000


def clean_website_url(url: str) -> str:
    """
    Strip UTM params, trailing paths, and return just the homepage URL.
    Returns empty string if the URL is a social/aggregator domain.
    """
    if not url:
        return ""

    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower().lstrip("www.")

        # Reject social/aggregator links — not a real website
        if parsed.netloc.lower() in FAKE_WEBSITE_DOMAINS:
            return ""

        # Strip UTM params and return just scheme + domain
        clean = urlunparse((parsed.scheme, parsed.netloc, "/", "", "", ""))
        return clean.rstrip("/")
    except Exception:
        return url


def is_chain_or_too_big(name: str, reviews: int | None) -> bool:
    """
    Filter out large chains and franchise businesses.
    They already have agencies — not our target.
    """
    if reviews and reviews > MAX_REVIEWS_FOR_LEAD:
        return True

    chain_keywords = [
        "mcdonald", "starbucks", "subway", "kfc", "domino",
        "pizza hut", "burger king", "taco bell", "wendy's",
        "dunkin", "tim hortons", "costa coffee", "pret",
        "five guys", "nando", "wagamama", "yo! sushi",
        "hilton", "marriott", "hyatt", "sheraton", "ibis",
        "holiday inn", "best western", "radisson",
    ]
    name_lower = name.lower()
    return any(kw in name_lower for kw in chain_keywords)


def search_places(query: str, location: str, max_results: int = 20) -> list:
    url = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": MAPS_KEY,
        "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.websiteUri,places.internationalPhoneNumber,places.rating,places.userRatingCount,nextPageToken"
    }
    results = []
    next_token = None

    while len(results) < max_results:
        payload = {
            "textQuery": f"{query} in {location}",
            "pageSize": min(20, max_results - len(results))
        }
        if next_token:
            payload["pageToken"] = next_token

        resp = requests.post(url, json=payload, headers=headers, timeout=10)
        if resp.status_code != 200:
            console.print(f"[red]Maps API error: {resp.status_code} — {resp.text}")
            break

        data = resp.json()
        places = data.get("places", [])
        if not places:
            break

        for p in places:
            results.append({
                "place_id": p.get("id"),
                "name": p.get("displayName", {}).get("text", "Unknown"),
                "website": p.get("websiteUri", ""),
                "phone": p.get("internationalPhoneNumber", ""),
                "address": p.get("formattedAddress", ""),
                "rating": p.get("rating"),
                "reviews": p.get("userRatingCount", 0),
                "formatted_address": p.get("formattedAddress", ""),
                "international_phone_number": p.get("internationalPhoneNumber", ""),
                "formatted_phone_number": p.get("internationalPhoneNumber", ""),
                "user_ratings_total": p.get("userRatingCount", 0),
            })

        next_token = data.get("nextPageToken")
        if not next_token:
            break

    return results[:max_results]


async def search_places_async(query: str, location: str, max_results: int = 20) -> list:
    url = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": MAPS_KEY,
        "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.websiteUri,places.internationalPhoneNumber,places.rating,places.userRatingCount,nextPageToken"
    }
    results = []
    next_token = None

    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
        while len(results) < max_results:
            payload = {
                "textQuery": f"{query} in {location}",
                "pageSize": min(20, max_results - len(results))
            }
            if next_token:
                payload["pageToken"] = next_token

            async with session.post(url, json=payload, headers=headers, timeout=10, ssl=False) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    console.print(f"[red]Maps API error: {resp.status} — {text}")
                    break

                data = await resp.json()
                places = data.get("places", [])
                if not places:
                    break

                for p in places:
                    results.append({
                        "place_id": p.get("id"),
                        "name": p.get("displayName", {}).get("text", "Unknown"),
                        "website": p.get("websiteUri", ""),
                        "phone": p.get("internationalPhoneNumber", ""),
                        "address": p.get("formattedAddress", ""),
                        "rating": p.get("rating"),
                        "reviews": p.get("userRatingCount", 0),
                        "formatted_address": p.get("formattedAddress", ""),
                        "international_phone_number": p.get("internationalPhoneNumber", ""),
                        "formatted_phone_number": p.get("internationalPhoneNumber", ""),
                        "user_ratings_total": p.get("userRatingCount", 0),
                    })

                next_token = data.get("nextPageToken")
                if not next_token:
                    break

    return results[:max_results]


def get_place_details(place_id: str) -> dict:
    url = f"https://places.googleapis.com/v1/places/{place_id}"
    headers = {
        "X-Goog-Api-Key": MAPS_KEY,
        "X-Goog-FieldMask": "id,displayName,formattedAddress,websiteUri,internationalPhoneNumber,rating,userRatingCount"
    }
    resp = requests.get(url, headers=headers, timeout=10)
    if resp.status_code != 200:
        return {}
    p = resp.json()
    return {
        "place_id": p.get("id"),
        "name": p.get("displayName", {}).get("text", "Unknown"),
        "website": p.get("websiteUri", ""),
        "phone": p.get("internationalPhoneNumber", ""),
        "address": p.get("formattedAddress", ""),
        "rating": p.get("rating"),
        "reviews": p.get("userRatingCount", 0),
        "formatted_address": p.get("formattedAddress", ""),
        "international_phone_number": p.get("internationalPhoneNumber", ""),
        "formatted_phone_number": p.get("internationalPhoneNumber", ""),
        "user_ratings_total": p.get("userRatingCount", 0),
    }


async def get_place_details_async(place_id: str) -> dict:
    url = f"https://places.googleapis.com/v1/places/{place_id}"
    headers = {
        "X-Goog-Api-Key": MAPS_KEY,
        "X-Goog-FieldMask": "id,displayName,formattedAddress,websiteUri,internationalPhoneNumber,rating,userRatingCount"
    }
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
        async with session.get(url, headers=headers, timeout=10, ssl=False) as resp:
            if resp.status != 200:
                return {}
            p = await resp.json()
            return {
                "place_id": p.get("id"),
                "name": p.get("displayName", {}).get("text", "Unknown"),
                "website": p.get("websiteUri", ""),
                "phone": p.get("internationalPhoneNumber", ""),
                "address": p.get("formattedAddress", ""),
                "rating": p.get("rating"),
                "reviews": p.get("userRatingCount", 0),
                "formatted_address": p.get("formattedAddress", ""),
                "international_phone_number": p.get("internationalPhoneNumber", ""),
                "formatted_phone_number": p.get("internationalPhoneNumber", ""),
                "user_ratings_total": p.get("userRatingCount", 0),
            }


def run_finder(niche: str, location: str, max_results: int = 20, source: str = "google_maps", max_score: int = 70, require_email: bool = True) -> int:
    console.print(f"\n[bold cyan]Searching:[/] {niche} in {location} via {source} (up to {max_results} results)\n")

    if source == "yelp":
        from multi_finder import scrape_yelp
        places_data = scrape_yelp(niche, location, max_results)
        saved = 0
        skipped = 0
        for biz in places_data:
            name = biz.get("name", "Unknown")
            console.print(f"[dim]Processing:[/] {name}...", end=" ")
            website = clean_website_url(biz.get("website", ""))
            score = score_website(website) if website else 0
            
            # Detect if this is a high-ticket SaaS campaign target
            cat_lower = niche.lower()
            saas_niches = {"roof", "hvac", "solar", "plumb", "dent", "ortho", "gym", "fitness", "contractor", "electrician", "painter", "landscap"}
            is_saas_campaign = any(kw in cat_lower for kw in saas_niches)

            if not is_saas_campaign and score >= max_score:
                console.print(f"[dim]skipped (score >= {max_score})[/]")
                skipped += 1
                continue

            if is_saas_campaign:
                biz["pitch_type"] = "leadflow_saas"
                biz["gap"] = "Opportunity for SaaS CRM, automated follow-ups, and lead-gen landing page"
            else:
                gap, pitch_type = detect_gap(website, score)
                biz["pitch_type"] = pitch_type
                biz["gap"] = gap

            contacts = extract_contacts(website, name, location)
            
            # Autopilot requirements: Require email for high quality outreach
            if require_email and not contacts.get("email"):
                console.print(f"[dim]skipped (no email)[/]")
                skipped += 1
                continue
            elif not require_email and not any([contacts.get("email"), contacts.get("instagram")]):
                console.print(f"[dim]skipped (no email/ig)[/]")
                skipped += 1
                continue
            biz["website"] = website
            biz["website_score"] = score
            biz["category"] = niche
            biz["lead_score"] = score_lead(biz, contacts)
            biz["source"] = "yelp"
            biz_id = insert_business(biz)
            insert_contacts(biz_id, contacts)
            saved += 1
            console.print("[green]Saved![/]")
        return saved

    # Default: Google Maps (or LinkedIn which uses Maps logic + LinkedIn filter)
    query = f"B2B {niche} companies" if source == "linkedin" else niche
    places = search_places(query, location, max_results)
    if not places:
        console.print("[yellow]No results found.")
        return 0

    saved = 0
    skipped = 0

    for place in places:
        name = place.get("name", "Unknown")
        console.print(f"[dim]Processing:[/] {name}...", end=" ")

        # Use already fetched details from new Places API, fallback to get_place_details if missing
        raw_website = place.get("website") or ""
        phone = place.get("phone") or place.get("international_phone_number") or place.get("formatted_phone_number", "")
        address = place.get("address") or place.get("formatted_address", "")
        rating = place.get("rating")
        reviews = place.get("reviews") or place.get("user_ratings_total") or 0

        if raw_website == "" and phone == "" and address == "":
            details = get_place_details(place["place_id"])
            raw_website = details.get("website", "")
            phone = details.get("international_phone_number") or details.get("formatted_phone_number", "")
            address = details.get("formatted_address", "")
            rating = details.get("rating")
            reviews = details.get("user_ratings_total") or 0

        # Skip big chains — not our clients
        if is_chain_or_too_big(name, reviews):
            console.print(f"[dim]skipped (chain/too big — {reviews} reviews)[/]")
            skipped += 1
            continue

        # Clean URL — strip UTM, reject social links
        website = clean_website_url(raw_website)

        score = score_website(website) if website else 0
        
        # Detect if this is a high-ticket SaaS campaign target
        cat_lower = niche.lower()
        saas_niches = {"roof", "hvac", "solar", "plumb", "dent", "ortho", "gym", "fitness", "contractor", "electrician", "painter", "landscap"}
        is_saas_campaign = any(kw in cat_lower for kw in saas_niches)

        # STRICT RULE: Never save leads with a website score >= max_score (unless it's a SaaS CRM target)
        if not is_saas_campaign and score >= max_score:
            console.print(f"[dim]skipped (website score >= {max_score})[/]")
            skipped += 1
            continue

        if is_saas_campaign:
            pitch_type = "leadflow_saas"
            gap = "Opportunity for SaaS CRM, automated follow-ups, and lead-gen landing page"
        else:
            gap, pitch_type = detect_gap(website, score)

        parts = address.split(",")
        city = parts[-3].strip() if len(parts) >= 3 else ""
        country = parts[-1].strip() if parts else ""

        business_data = {
            "name": name,
            "category": niche,
            "address": address,
            "city": city,
            "country": country,
            "phone": phone,
            "website": website,
            "website_score": score,
            "google_rating": rating,
            "google_reviews": reviews,
            "gap": gap,
            "pitch_type": pitch_type,
        }

        # Domain availability for businesses with no website
        domain_info = check_domain_available(name) if not website else {}
        domain_available = domain_info.get("domain") if domain_info.get("available") else None

        contacts = extract_contacts(website, name, location)

        if source == "linkedin":
            if not contacts.get("linkedin_url"):
                contacts["linkedin_url"] = f"https://linkedin.com/company/{name.lower().replace(' ', '-')}"
                console.print(f"[dim]generated linkedin profile[/]", end=" ")

        # ── Promote mobile numbers to WhatsApp ────────────────────────
        if phone and not contacts.get("whatsapp"):
            try:
                import phonenumbers
                from phonenumbers.phonenumberutil import number_type, PhoneNumberType
                parsed = phonenumbers.parse(phone, "US")  # Fallback to US if no country code
                t = number_type(parsed)
                if t in (PhoneNumberType.MOBILE, PhoneNumberType.FIXED_LINE_OR_MOBILE):
                    contacts["whatsapp"] = phone
            except Exception:
                pass

        # Skip if no email found — we need email to perform outreach
        if require_email and not contacts.get("email"):
            console.print(f"[dim]skipped (no email)[/]")
            skipped += 1
            continue
        elif not require_email and not any([contacts.get("email"), contacts.get("instagram"),
                    contacts.get("linkedin_url"), contacts.get("whatsapp")]):
            console.log(f"[dim]skipped (no contacts)[/]")
            skipped += 1
            continue

        lead_score = score_lead(business_data, contacts)

        business_data["lead_score"]      = lead_score
        business_data["domain_available"] = domain_available
        business_data["source"]          = source
        business_data["maps_url"]        = f"https://www.google.com/maps/place/?q=place_id:{place['place_id']}"

        bid = insert_business(business_data)
        insert_contacts(bid, contacts)

        has_email = "✓" if contacts.get("email") else "✗"
        has_ig    = "✓" if contacts.get("instagram") else "✗"
        console.print(f"[green]saved[/] | lead={lead_score} | score={score} | email={has_email} ig={has_ig}")
        saved += 1

    console.print(f"\n[bold green]{saved} saved[/]  [dim]{skipped} skipped (chains/no contacts)[/]")
    return saved
