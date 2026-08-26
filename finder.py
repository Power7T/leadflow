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
from analyzer import score_website, score_website_with_details, detect_gap
from extractor import extract_contacts
from scorer import score_lead
from multi_finder import check_domain_available
import aiohttp
import asyncio

load_dotenv()
console = Console()

def get_maps_key() -> str:
    return os.getenv("GOOGLE_MAPS_API_KEY", "")

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


def search_places(query: str, location: str, max_results: int = 100) -> list:
    url = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": get_maps_key(),
        "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.websiteUri,places.internationalPhoneNumber,places.rating,places.userRatingCount,places.reviews,nextPageToken"
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
                "reviews_list": p.get("reviews", []),
            })

        next_token = data.get("nextPageToken")
        if not next_token:
            break

    return results[:max_results]


async def search_places_async(query: str, location: str, max_results: int = 100) -> list:
    url = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": get_maps_key(),
        "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.websiteUri,places.internationalPhoneNumber,places.rating,places.userRatingCount,places.reviews,nextPageToken"
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
                        "reviews_list": p.get("reviews", []),
                    })

                next_token = data.get("nextPageToken")
                if not next_token:
                    break

    return results[:max_results]


def get_place_details(place_id: str) -> dict:
    url = f"https://places.googleapis.com/v1/places/{place_id}"
    headers = {
        "X-Goog-Api-Key": get_maps_key(),
        "X-Goog-FieldMask": "id,displayName,formattedAddress,websiteUri,internationalPhoneNumber,rating,userRatingCount,reviews,photos,regularOpeningHours,editorialSummary"
    }
    resp = requests.get(url, headers=headers, timeout=10)
    if resp.status_code != 200:
        return {}
    p = resp.json()
    photo_count = len(p.get("photos", []))
    has_hours = bool(p.get("regularOpeningHours"))
    has_description = bool(p.get("editorialSummary", {}).get("text", ""))
    gmb_gaps = []
    if photo_count < 5:
        gmb_gaps.append(f"only {photo_count} photo{'s' if photo_count != 1 else ''} on Google")
    if not has_hours:
        gmb_gaps.append("no opening hours listed")
    if not has_description:
        gmb_gaps.append("no business description")
    gmb_gap_hook = (
        "Their Google Business Profile is incomplete — " + ", ".join(gmb_gaps) + ". "
        "A polished profile with photos, hours, and a description gets 7× more clicks."
        if gmb_gaps else ""
    )
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
        "reviews_list": p.get("reviews", []),
        "gmb_gap_hook": gmb_gap_hook,
    }


async def get_place_details_async(place_id: str) -> dict:
    url = f"https://places.googleapis.com/v1/places/{place_id}"
    headers = {
        "X-Goog-Api-Key": get_maps_key(),
        "X-Goog-FieldMask": "id,displayName,formattedAddress,websiteUri,internationalPhoneNumber,rating,userRatingCount,reviews,photos,regularOpeningHours,editorialSummary"
    }
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
        async with session.get(url, headers=headers, timeout=10, ssl=False) as resp:
            if resp.status != 200:
                return {}
            p = await resp.json()
            photo_count = len(p.get("photos", []))
            has_hours = bool(p.get("regularOpeningHours"))
            has_description = bool(p.get("editorialSummary", {}).get("text", ""))
            gmb_gaps = []
            if photo_count < 5:
                gmb_gaps.append(f"only {photo_count} photo{'s' if photo_count != 1 else ''} on Google")
            if not has_hours:
                gmb_gaps.append("no opening hours listed")
            if not has_description:
                gmb_gaps.append("no business description")
            gmb_gap_hook = (
                "Their Google Business Profile is incomplete — " + ", ".join(gmb_gaps) + ". "
                "A polished profile with photos, hours, and a description gets 7× more clicks."
                if gmb_gaps else ""
            )
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
                "reviews_list": p.get("reviews", []),
                "gmb_gap_hook": gmb_gap_hook,
            }


def extract_solvable_complaints_ai(reviews: list, business_name: str) -> str:
    """
    Examines Google Reviews and identifies complaints related ONLY to digital/technical aspects
    that our generated demo sites solve:
    1. Website speed, loading issues, outdated website design, or lack of a website.
    2. Online booking issues, scheduling difficulties, or lack of online booking/scheduling.
    3. Missing or slow customer support, slow response times, or lack of instant chat/FAQ support.
    4. Difficulty finding contact info, address, phone number, menu, or pricing online.
    
    Any other complaints (rude staff, bad service, quality, physical location, pricing of services) must be ignored.
    """
    if not reviews:
        return ""
    
    # Format reviews into a string
    reviews_text = ""
    for r in reviews[:10]:
        rating = r.get("rating", "")
        text = r.get("text", {})
        if isinstance(text, dict):
            text = text.get("text", "")
        else:
            text = r.get("text", "") or r.get("comment", "")
            
        if text:
            reviews_text += f"- [{rating}★] {text}\n"
            
    if not reviews_text.strip():
        return ""
        
    # Safely compress the reviews using LLMLingua-2 to save tokens
    compressed_reviews = reviews_text
    try:
        from llmlingua import PromptCompressor
        global _compressor
        if '_compressor' not in globals():
            _compressor = PromptCompressor(
                model_name="microsoft/llmlingua-2-bert-base-multilingual-cased-meetingbank",
                use_llmlingua2=True,
                device_map="cpu"
            )
        if len(reviews_text.split()) > 100:
            compression_res = _compressor.compress_prompt(reviews_text, rate=0.4)
            compressed_reviews = compression_res.get("compressed_prompt", reviews_text)
            tokens_saved = compression_res.get("origin_tokens", 0) - compression_res.get("compressed_tokens", 0)
            if tokens_saved > 0:
                print(f"[LLMLingua] Compressed reviews for {business_name} (Saved {tokens_saved} tokens)")
    except Exception as e:
        print(f"[LLMLingua] Skipping compression due to error: {e}")
        
    prompt = f"""
Business Name: {business_name}
Google Reviews (Compressed):
{compressed_reviews}

Analyze the above customer reviews for {business_name}. 
Identify complaints that are SPECIFICALLY and ONLY about the following digital/website issues that our demo websites solve:
1. Website speed, loading issues, outdated website design, or lack of a website.
2. Online booking issues, scheduling difficulties, or lack of online booking/scheduling.
3. Missing or slow customer support, slow response times, or lack of instant chat/FAQ support.
4. Difficulty finding contact info, address, phone number, menu, or pricing online.

CRITICAL RULES:
- Ignore all offline/in-person/operational complaints (e.g., rude staff, bad service, bad quality, long physical lines, pricing of items/services, cleanliness, environment).
- ONLY extract complaints that match the 4 digital issues above.
- If there are no such digital complaints, return exactly: "No solvable digital gaps found."
- If there are such complaints, summarize them concisely in a single brief sentence pointing out the gap, for example: "Reviews mention scheduling difficulty and slow response times to simple questions."
- Do not mention rude staff, service quality, or other physical/offline issues under any circumstances.
- Keep the response short, under 20 words, ready to be stored in a database column.
"""
    try:
        from ai_writer import _run
        res = _run(prompt)
        res_clean = res.strip().strip('"').strip("'")
        if "No solvable digital gaps" in res_clean or "no solvable digital" in res_clean.lower():
            return ""
        return res_clean
    except Exception as e:
        print(f"Error calling AI for reviews analysis: {e}")
        return ""


def search_duckduckgo(query: str, location: str = "") -> list:
    """Query DuckDuckGo HTML search for organic B2B websites completely for free."""
    import requests, time
    from bs4 import BeautifulSoup
    import urllib.parse
    
    q_str = f"{query} {location}" if location else query
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36'
    }
    
    try:
        url = "https://html.duckduckgo.com/html/"
        r = requests.post(url, data={'q': q_str}, headers=headers, timeout=10)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, 'html.parser')
            links = soup.find_all('a', class_='result__url')
            combined = []
            
            for index, l in enumerate(links):
                link = l['href']
                title = l.text.strip()
                
                # Clean DuckDuckGo redirect parameters
                if 'duckduckgo.com/l/?' in link:
                    parsed = urllib.parse.urlparse(link)
                    qs = urllib.parse.parse_qs(parsed.query)
                    if 'uddg' in qs:
                        link = qs['uddg'][0]
                
                # Exclude social aggregator sites
                if link and not any(domain in link for domain in FAKE_WEBSITE_DOMAINS):
                    title_clean = title.split(" - ")[0].split(" | ")[0].strip()
                    combined.append({
                        "name": title_clean,
                        "website": link,
                        "address": location or "",
                        "phone": "",
                        "rating": None,
                        "reviews": 0,
                        "place_id": f"org_{index}_{int(time.time())}",
                        "is_ad": False
                    })
            return combined
    except Exception as e:
        print(f"Error querying DuckDuckGo free search: {e}")
    return []


def search_google_serp(query: str, location: str = "", gl: str = "us", only_ads: bool = False) -> list:
    """Query Serper.dev standard search to extract paid ads and organic results."""
    import os, json, requests
    key = os.getenv("SERPER_API_KEY")
    if not key:
        print("[yellow]SERPER_API_KEY not set. Skipping search source.[/]")
        return []
    
    q_str = f"{query} in {location}" if location else query
    try:
        url = "https://google.serper.dev/search"
        payload = {"q": q_str, "gl": gl}
        headers = {"X-API-KEY": key, "Content-Type": "application/json"}
        r = requests.post(url, headers=headers, json=payload, timeout=12)
        if r.status_code == 200:
            data = r.json()
            combined = []
            
            # 1. Parse sponsored search ads (highest priority!)
            for index, ad in enumerate(data.get("ads", [])):
                link = ad.get("link")
                title = ad.get("title", "Sponsored Ad")
                if link:
                    combined.append({
                        "name": title,
                        "website": link,
                        "address": location or ad.get("displayedLink", ""),
                        "phone": "",
                        "rating": None,
                        "reviews": 0,
                        "place_id": f"ad_{index}_{int(time.time())}",
                        "is_ad": True
                    })
            
            if only_ads:
                return combined

            # 2. Parse organic web results
            for index, org in enumerate(data.get("organic", [])):
                link = org.get("link")
                title = org.get("title", "Organic Result")
                snippet = org.get("snippet", "")
                if link:
                    # Clean title (e.g. remove trailing site name)
                    title_clean = title.split(" - ")[0].split(" | ")[0].strip()
                    combined.append({
                        "name": title_clean,
                        "website": link,
                        "address": location or snippet[:50],
                        "phone": "",
                        "rating": None,
                        "reviews": 0,
                        "place_id": f"org_{index}_{int(time.time())}",
                        "is_ad": False
                    })
            return combined
        else:
            print(f"[red]Serper API error: {r.status_code} — {r.text}. Scraper will skip this query.[/]")
    except Exception as e:
        print(f"Error querying Serper search API: {e}")
    return []


def run_finder(source, 
    niche: str,
    location: str,
    max_results: int = 100,
    max_score: int = 100,
    require_email: bool = True,
    quality_gate: dict = None,
    stop_after_qualified: int = None,
) -> int:
    """
    Search for businesses and save qualifying leads.

    quality_gate (optional dict): If provided, a lead only counts toward
    stop_after_qualified if it passes ALL of these thresholds:
      - min_lead_score   (default 0)
      - min_rating       (default 0.0)
      - min_reviews      (default 0)
      - max_website_score (default 100 — leads must have BELOW this to qualify)

    stop_after_qualified (optional int): Stop scraping once this many leads
    have passed the quality_gate. Leads that fail the gate are still saved
    but don't count toward the cap.

    Returns: number of quality-gate-passing leads saved (or total saved if no gate).
    """
    console.print(f"\n[bold cyan]Searching:[/] {niche} in {location} via {source} (up to {max_results} results)\n")

    # Parse quality gate thresholds
    gate = quality_gate or {}
    gate_min_score   = gate.get("min_lead_score", 0)
    gate_min_rating  = gate.get("min_rating", 0.0)
    gate_min_reviews = gate.get("min_reviews", 0)
    gate_max_ws      = gate.get("max_website_score", 100)  # website_score must be BELOW this
    use_gate         = bool(quality_gate)
    qualified_saved  = 0  # leads that passed the quality gate

    if source == "yelp":
        from multi_finder import scrape_yelp
        places_data = scrape_yelp(niche, location, max_results)
        saved = 0
        skipped = 0
        for biz in places_data:
            name = biz.get("name", "Unknown")
            console.print(f"[dim]Processing:[/] {name}...", end=" ")
            website = clean_website_url(biz.get("website", ""))
            score, site_builder = score_website_with_details(website) if website else (0, "")
            
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
            biz["site_builder"] = site_builder
            biz["complaint_hook"] = ""
            biz["category"] = niche
            biz["has_google_ads"] = contacts.pop("has_google_ads", 0)
            biz["social_active"] = contacts.pop("social_active", 0)
            biz["intent_score"] = contacts.pop("intent_score", 0)
            biz["lead_score"] = score_lead(biz, contacts)
            biz["source"] = "yelp"
            biz_id = insert_business(biz)
            insert_contacts(biz_id, contacts)
            saved += 1

            # Check quality gate
            passes_gate = (
                biz["lead_score"] >= gate_min_score and
                (biz.get("google_rating") or 0) >= gate_min_rating and
                (biz.get("google_reviews") or 0) >= gate_min_reviews and
                score < gate_max_ws
            ) if use_gate else True
            if passes_gate:
                qualified_saved += 1
                console.print("[green]Saved! ✓ Quality gate passed[/]")
                if stop_after_qualified and qualified_saved >= stop_after_qualified:
                    console.print(f"[bold green]Stop: {stop_after_qualified} qualified leads reached.[/]")
                    break
            else:
                console.print("[green]Saved[/] [dim](below quality gate — won't count toward cap)[/]")
        return qualified_saved if use_gate else saved

    # Pick places database source based on type
    if source == "google_search":
        places = search_google_serp(niche, location, only_ads=False)
    elif source == "google_ads":
        places = search_google_serp(niche, location, only_ads=True)
    elif source == "duckduckgo_search":
        places = search_duckduckgo(niche, location)
    else:
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

        is_synthetic = place.get("place_id", "").startswith("ad_") or place.get("place_id", "").startswith("org_")

        # Use already fetched details from new Places API, fallback to get_place_details if missing
        raw_website = place.get("website") or ""
        phone = place.get("phone") or place.get("international_phone_number") or place.get("formatted_phone_number", "")
        address = place.get("address") or place.get("formatted_address", "")
        rating = place.get("rating")
        reviews = place.get("reviews") or place.get("user_ratings_total") or 0
        reviews_list = place.get("reviews_list", [])
        gmb_gap_hook = place.get("gmb_gap_hook", "")

        if not is_synthetic and raw_website == "" and phone == "" and address == "":
            details = get_place_details(place["place_id"])
            raw_website = details.get("website", "")
            phone = details.get("international_phone_number") or details.get("formatted_phone_number", "")
            address = details.get("formatted_address", "")
            rating = details.get("rating")
            reviews = details.get("user_ratings_total") or 0
            reviews_list = details.get("reviews_list", [])
            gmb_gap_hook = gmb_gap_hook or details.get("gmb_gap_hook", "")

        # Fetch details to get reviews list if not already fetched and there are reviews
        if not is_synthetic and not reviews_list and reviews > 0:
            details = get_place_details(place["place_id"])
            reviews_list = details.get("reviews_list", [])
            gmb_gap_hook = gmb_gap_hook or details.get("gmb_gap_hook", "")

        # Skip big chains — not our clients
        if is_chain_or_too_big(name, reviews):
            console.print(f"[dim]skipped (chain/too big — {reviews} reviews)[/]")
            skipped += 1
            continue

        # Clean URL — strip UTM, reject social links
        website = clean_website_url(raw_website)

        score, site_builder = score_website_with_details(website) if website else (0, "")
        
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

        # Extract digital-only review complaints as a separate pitch hook (never overwrites gap)
        complaint_hook = extract_solvable_complaints_ai(reviews_list, name) if reviews_list else ""

        # Competitor lookup — score their site so we only pitch if theirs beats ours
        from demo_generator import get_competitor_info
        competitor_info = get_competitor_info(niche, city, name) if website else {}

        parts = address.split(",")
        city = parts[-3].strip() if len(parts) >= 3 else ""
        country = parts[-1].strip() if parts else ""

        from scheduler import city_to_timezone
        business_data = {
            "name": name,
            "category": niche,
            "address": address,
            "city": city,
            "country": country,
            "timezone": city_to_timezone(city),
            "phone": phone,
            "website": website,
            "website_score": score,
            "google_rating": rating,
            "google_reviews": reviews,
            "gap": gap,
            "pitch_type": pitch_type,
            "site_builder": site_builder,
            "complaint_hook": complaint_hook,
            "gmb_gap_hook": gmb_gap_hook,
            "competitor_name": competitor_info.get("name", ""),
            "competitor_url": competitor_info.get("url", ""),
            "competitor_score": competitor_info.get("score", 0),
            "place_id": place.get("place_id", "") if not is_synthetic else "",
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

        # If it was found as a sponsored ad, flag it!
        if place.get("is_ad"):
            contacts["has_google_ads"] = 1

        lead_score = score_lead(business_data, contacts)

        business_data["lead_score"]      = lead_score
        business_data["domain_available"] = domain_available
        business_data["source"]          = source
        if is_synthetic:
            business_data["maps_url"]    = website or ""
        else:
            business_data["maps_url"]    = f"https://www.google.com/maps/place/?q=place_id:{place['place_id']}"

        bid = insert_business(business_data)
        insert_contacts(bid, contacts)

        has_email = "✓" if contacts.get("email") else "✗"
        has_ig    = "✓" if contacts.get("instagram") else "✗"

        # Check quality gate — does this lead count toward the daily cap?
        passes_gate = (
            lead_score >= gate_min_score and
            (rating or 0) >= gate_min_rating and
            (reviews or 0) >= gate_min_reviews and
            score < gate_max_ws
        ) if use_gate else True

        if passes_gate:
            qualified_saved += 1
            console.print(f"[green]saved ✓[/] | id={bid} | score={lead_score} | web_score={score} | email={has_email} ig={has_ig} [bold green](quality gate passed {qualified_saved})[/]")
        else:
            console.print(f"[green]saved[/] | id={bid} | score={lead_score} | web_score={score} | email={has_email} ig={has_ig} [dim](below quality gate)[/]")

        saved += 1

        # Stop early once we've hit the qualified lead cap for today
        if stop_after_qualified and qualified_saved >= stop_after_qualified:
            console.print(f"[bold green]\n✅ Daily cap reached: {stop_after_qualified} quality leads found. Stopping scraper.[/]")
            break

    console.print(f"\n[bold green]{saved} saved[/]  [dim]{skipped} skipped[/]  [bold cyan]{qualified_saved} passed quality gate[/]")
    return qualified_saved if use_gate else saved
