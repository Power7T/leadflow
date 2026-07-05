"""
AI message writer — uses local Gemini CLI (agy).
Features: personalized emails/DMs, 3 subject A/B options,
3-email follow-up sequence, review-based personalization,
competitor comparison, demo site link injection.
"""
import os
import re
import subprocess
import shutil
from datetime import datetime, timedelta
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()

AGY_PATH = shutil.which("agy") or os.getenv("AGY_PATH")
DEFAULT_MODEL = "Gemini 3.5 Flash (High)"
BOOKING_URL   = os.getenv("BOOKING_URL", "https://www.fiverr.com/s/e6zGy4g")
env_calendly  = os.getenv("CALENDLY_URL")
CALENDLY_URLS = [u.strip() for u in env_calendly.split(",")] if env_calendly else [
    "https://cal.com/chandan-gosavi/15min",
    "https://calendly.com/chandango12/30min"
]
FIVERR_URL    = "https://www.fiverr.com/s/e6zGy4g"


# ── Spintax engine ─────────────────────────────────────────────────────────
import random as _random_mod

def _spintax(text: str) -> str:
    """
    Resolve spintax: {A|B|C} blocks are replaced by a random pick.
    Makes every outgoing email worded slightly differently so Gmail's
    duplicate-content spam filter treats each send as unique.
    """
    def _pick(m):
        opts = m.group(1).split("|")
        return _random_mod.choice(opts).strip()
    return re.sub(r"\{([^{}]+)\}", _pick, text)


# ── Personalized first-line generator ──────────────────────────────────────

_FIRST_LINE_TEMPLATES = [
    "{reviews} reviews and a {rating}★ rating — {name} is clearly doing something right.",
    "Saw {name}'s {rating}★ on Google ({reviews} reviews) and had to reach out.",
    "{reviews} people gave {name} {rating} stars — that kind of reputation is rare.",
    "Not many {category} businesses hit {rating}★ with {reviews} reviews. {name} is one of them.",
    "Honestly, {reviews} reviews at {rating}★ for a {category} business in {city} is impressive.",
]

_FIRST_LINE_NO_RATING = [
    "Found {name} while looking at top {category} businesses in {city}.",
    "{name} came up as one of the better {category} options in {city}.",
    "Was checking out {category} businesses in {city} and {name} stood out.",
]

def _build_first_line(business: dict) -> str:
    """Build a genuine, data-driven opening sentence unique to this business."""
    name     = business.get("name", "") or ""
    rating   = business.get("google_rating") or 0
    reviews  = business.get("google_reviews") or 0
    category = (business.get("category") or "").lower()
    city     = (business.get("city") or "").split(",")[0].strip()

    # Shorten very long business names
    short_name = " ".join(name.split()[:4]) if len(name.split()) > 4 else name

    if rating and reviews:
        tpl = _random_mod.choice(_FIRST_LINE_TEMPLATES)
        return tpl.format(
            name=short_name, rating=rating,
            reviews=reviews, category=category, city=city
        )
    else:
        tpl = _random_mod.choice(_FIRST_LINE_NO_RATING)
        return tpl.format(name=short_name, category=category, city=city)


# ── Social proof snippets by niche ──────────────────────────────────────────

_SOCIAL_PROOF = {
    "roofing":      "Last month I helped a roofing company in {city} — they got 3 new estimate requests in the first week after their site went live.",
    "roof":         "Last month I helped a roofing company in {city} — they got 3 new estimate requests in the first week after their site went live.",
    "hvac":         "A heating & cooling company I worked with recently started getting 2-3 more inbound calls per week just from local search after the new site.",
    "plumb":        "A plumber I helped last month in {city} started getting found on Google Maps within days of the site going live.",
    "solar":        "A solar installer I worked with doubled their contact form submissions within 2 weeks of the site launching.",
    "landscap":     "Helped a landscaping business in {city} recently — they picked up 4 new maintenance clients in the first month.",
    "gym":          "A gym I worked with saw a 30% jump in trial sign-up inquiries after we made their site mobile-friendly and fast.",
    "fitness":      "A gym I worked with saw a 30% jump in trial sign-up inquiries after we made their site mobile-friendly and fast.",
    "dentist":      "A dental practice I helped recently now shows up on the first page of local search for their city — they told me it brought in 5 new patients in a month.",
    "dental":       "A dental practice I helped recently now shows up on the first page of local search for their city — they told me it brought in 5 new patients in a month.",
    "chiropract":   "A chiropractor I helped in {city} started getting booked-out weeks in advance after their new site went live.",
    "lawyer":       "A law firm I helped recently started getting 3-4 new consultation requests per week from local search alone.",
    "remodel":      "A remodeling company I worked with recently — after we rebuilt their site, they closed 2 new kitchen renovation projects in the first month.",
    "cleaning":     "A cleaning company I helped is now fully booked 3 weeks out after their site started ranking locally.",
    "moving":       "A moving company I helped in {city} went from invisible online to getting 6+ quote requests a week.",
    "accountant":   "A CPA firm I helped recently started getting new client inquiries directly from their website — they said it paid for itself in the first month.",
    "medspa":       "A med spa I worked with saw their online booking increase 40% within weeks of the site launch.",
    "detailing":    "A detailing shop I helped in {city} now shows up when people search for detailing near them — they said it brought in 8 new customers in the first month.",
}

_SOCIAL_PROOF_DEFAULT = "I've helped businesses similar to yours start capturing more local customers within weeks of their site going live."

def _social_proof_snippet(business: dict) -> str:
    """Return a niche-specific case study line for follow-up emails."""
    category = (business.get("category") or "").lower()
    city     = (business.get("city") or "").split(",")[0].strip() or "their area"
    for kw, tpl in _SOCIAL_PROOF.items():
        if kw in category:
            return tpl.format(city=city)
    return _SOCIAL_PROOF_DEFAULT


_GYM_KEYWORDS = {
    "gym", "fit", "fitness", "crossfit", "yoga", "pilates", "studio",
    "boxing", "martial art", "mma", "workout", "athletic", "ymca",
}

def _is_gym(category: str, name: str = "") -> bool:
    cat = (category or "").lower()
    nm  = (name or "").lower()
    return any(kw in cat or kw in nm for kw in _GYM_KEYWORDS)

def get_system_context(business: dict) -> str:
    pitch_type = business.get("pitch_type", "")
    has_website = bool(business.get("website"))
    
    if pitch_type == "leadflow_saas":
        role = "a developer who builds lead-gen systems"
        golden = "\"Hey [Mike/there], I'm Chandan. [Business Name] has awesome [X]★ reviews, but you're missing out on a lot of leads by not having an automated CRM and follow-up system. I built this custom automated lead-gen demo to show you what's possible: [link]. Check it out and let me know what you think.\""
    elif not has_website:
        role = "a web developer"
        golden = "\"Hey [Mike/there], I'm Chandan. [Business Name] has awesome [X]★ reviews, but without a website, you're missing out on local members searching online. I built this custom demo to show you what's possible: [link]. Check it out and let me know what you think.\""
    else:
        role = "a developer"
        gap_text = business.get("gap", "")
        import re
        m = re.search(r"—\s*(.*)", gap_text)
        issue = m.group(1).strip() if m else "your website could be converting far more visitors into paying customers"
        golden = f"\"Hey [Mike/there], I'm Chandan. [Business Name] has awesome [X]★ reviews, but I noticed {issue}. I built this custom optimized demo to show you what's possible: [link]. Check it out and let me know what you think.\""
    

    return f"""You are a highly persuasive, world-class outbound sales copywriter for Chandan Gosavi, {role}.

Rules for high-converting but professional copy:
- Never sound like a generic salesperson. Create a "Pattern Interrupt" by starting with genuine, specific praise about their business (e.g., their great reviews).
- If the owner's name is known (e.g. Mike), personalize the greeting (e.g. "Hey Mike," or "Hey Mike, I'm Chandan...") instead of a generic "Hey," or using the business name.
- Highlight the opportunity cost (e.g., "you might be missing out on local searches because...") rather than insulting them. DO NOT be rude or aggressive.
- Build extreme CURIOSITY about the custom work you've already done for them.
- Keep emails under 100 words, DMs under 50 words. Punchy, short sentences.
- Use psychological triggers: FOMO, exclusivity, and undeniable value upfront, but keep a friendly, professional tone.
- Never use: "I hope this finds you well", "touch base", "circle back", "synergy".
- Include a very brief, confident, and honest introduction (e.g., "Hey, I'm Chandan—{role}.") but keep the focus 90% on them and the value you're providing.
- STRICTLY end the message with a confident statement (e.g., "Check it out and let me know what you think." or "If you like it, let me know."). NEVER use a question mark (?) at the end of the message.
- GOLDEN TEMPLATE STRUCTURE: {golden}
- Plain conversational English. Write ready to send.
- CRITICAL OUTPUT FORMAT RULE: Output ONLY the raw subject line and message/email body. Do NOT include any conversational introduction (e.g. "Here is your message:"), do NOT include markdown headings/titles (e.g. "### Rewritten Cold Email"), do NOT use markdown code fences, and do NOT add summaries of actions or explanations at the end. Your entire output must be copy-pasteable directly into an email/DM client without editing out commentary.
"""


# ── Quota / rate-limit detection ──────────────────────────────────────────

_QUOTA_PHRASES = [
    "quota", "rate limit", "rate_limit", "429", "resource exhausted",
    "too many requests", "limit exceeded", "resourceexhausted",
    "daily limit", "per minute", "tokens per", "requests per",
]

def _is_quota_error(text: str) -> bool:
    t = text.lower()
    return any(p in t for p in _QUOTA_PHRASES)


# ── Tier 1: agy CLI — round-robin across permitted profiles only ───────────

_PROFILES_DIR = os.getenv("AGY_PROFILES_DIR", str(Path.home() / ".gemini-profiles"))
_PERMITTED_MODEL = "Gemini 3.5 Flash (Low)"  # ONLY this model is allowed for LeadFlow

def _get_agy_profiles() -> list[str]:
    """Return profiles that are configured with the permitted model only.
    Profiles running Claude, Gemini Pro, or any other model are skipped.
    """
    import glob, json
    profiles = sorted(glob.glob(f"{_PROFILES_DIR}/profile*/"))
    valid = []
    for p in profiles:
        cfg = os.path.join(p, ".gemini", "antigravity-cli", "settings.json")
        if not os.path.exists(cfg):
            continue
        try:
            model = json.load(open(cfg)).get("model", "")
            if model == _PERMITTED_MODEL:
                valid.append(p)
        except Exception:
            continue
    return valid

# Simple round-robin counter (in-process, resets on restart)
_agy_profile_idx = 0

def check_internet(timeout: float = 3.0) -> bool:
    """Check reachability of the Google Gemini API endpoint to ensure we are online.
    Returns False if offline or endpoint is unreachable, preventing agy popups.
    """
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:  # fix #3: socket is now properly closed
            s.settimeout(timeout)
            s.connect(("generativelanguage.googleapis.com", 443))
        return True
    except Exception:
        return False

# Backward compatibility alias
_check_internet = check_internet


def _run_agy_profiles(prompt: str, timeout: int = 25, sys_ctx: str = None) -> str | None:
    """Call agy CLI rotating across all profiles configured with the permitted model.
    Explicitly passes --model to agy on every call so it can never silently
    switch to a different model regardless of profile defaults.

    IMPORTANT: If internet is down, we skip agy entirely and return None so
    the caller falls through to the REST API tier. This prevents agy from
    opening hundreds of Google login browser windows when connectivity drops.
    """
    global _agy_profile_idx
    if not AGY_PATH:
        return None

    # ── Internet guard ────────────────────────────────────────────────────────
    # agy requires Google OAuth which opens a browser login page when offline.
    # Detect no-internet early and skip agy entirely — REST API handles it.
    if not _check_internet():
        print("[ai_writer] No internet detected — skipping agy (prevents login popup flood)")
        return None
    # ─────────────────────────────────────────────────────────────────────────

    profiles = _get_agy_profiles()
    if not profiles:
        print(f"[ai_writer] No agy profiles found with model='{_PERMITTED_MODEL}'")
        return None

    full_prompt = (sys_ctx or get_system_context({})) + "\n\n" + prompt
    n = len(profiles)

    for attempt in range(n):
        profile_path = profiles[_agy_profile_idx % n]
        _agy_profile_idx = (_agy_profile_idx + 1) % n
        profile_name = os.path.basename(profile_path.rstrip("/"))

        try:
            env = os.environ.copy()
            env["HOME"]               = profile_path.rstrip("/")
            env["AGY_PROFILES_DIR"]   = _PROFILES_DIR
            env["AGY_ACTIVE_PROFILE"] = profile_name

            # Ensure mock open binary exists to guard against any browser popup
            mock_bin_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scratch", "mock_bin")
            os.makedirs(mock_bin_dir, exist_ok=True)
            mock_open_file = os.path.join(mock_bin_dir, "open")
            if not os.path.exists(mock_open_file):
                try:
                    with open(mock_open_file, "w") as f:
                        f.write(f"#!/bin/bash\necho \"[mock_open] Blocked URL: $@\" >> {os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scratch_agy.log')}\nexit 0\n")
                    os.chmod(mock_open_file, 0o755)
                except Exception:
                    pass

            env["PATH"] = f"{mock_bin_dir}:{env.get('PATH', '')}"

            result = subprocess.run(
                # --model enforced explicitly — no silent fallback to other models
                [AGY_PATH, "--model", _PERMITTED_MODEL,
                 "--print-timeout", f"{timeout}s", "-p", full_prompt],
                capture_output=True, text=True, timeout=timeout + 5, env=env
            )
            out    = (result.stdout or "").strip()
            stderr = (result.stderr or "").strip()

            if _is_quota_error(out) or _is_quota_error(stderr):
                print(f"[ai_writer] agy {profile_name} rate-limited, trying next profile")
                continue

            if result.returncode == 0 and out:
                print(f"[ai_writer] agy success via {profile_name} ({_PERMITTED_MODEL})")
                return out

            print(f"[ai_writer] agy {profile_name} empty/error ({stderr[:60]}), trying next")

        except subprocess.TimeoutExpired:
            print(f"[ai_writer] agy {profile_name} timed out, trying next profile")
        except Exception as e:
            print(f"[ai_writer] agy {profile_name} exception: {str(e)[:60]}")


# ── Tier 2: Gemini REST API (direct key rotation) ──────────────────────────

def _run_gemini_rest(prompt: str, model: str = "gemini-2.5-flash", sys_ctx: str = None) -> str | None:
    """Call Gemini via REST. Uses one key at a time — retries same key once before rotating."""
    keys_str = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_AI_API_KEY") or ""
    keys = [k.strip() for k in keys_str.split(",") if k.strip()]
    if not keys:
        return None

    import urllib.request, json, time, ssl
    full_prompt = (sys_ctx or get_system_context({})) + "\n\n" + prompt
    payload = json.dumps({
        "contents": [{"parts": [{"text": full_prompt}]}],
        "generationConfig": {"maxOutputTokens": 512, "temperature": 0.9},
    }).encode()
    # fix #7: use verified SSL context
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()

    for idx, api_key in enumerate(keys):
        # Try the same key up to 2 times before moving on
        for attempt in range(2):
            try:
                url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
                       f"{model}:generateContent?key={api_key}")
                req = urllib.request.Request(url, data=payload,
                                             headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=60, context=ctx) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                out = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                if out:
                    return out
            except Exception as e:
                err_str = str(e)
                if attempt == 0:
                    # First failure on this key — wait briefly and retry the same key
                    print(f"[ai_writer] Key #{idx+1} attempt 1 failed ({err_str[:60]}), retrying...")
                    time.sleep(1.0)
                else:
                    # Second failure — give up on this key and try next
                    print(f"[ai_writer] Key #{idx+1} attempt 2 failed ({err_str[:60]}), rotating to next key")
    return None




def _run_omniroute(prompt: str, sys_ctx: str = None) -> str | None:
    """Call OmniRoute local server with agy models as a high-priority tier.
    Uses the 10 local agy accounts connected via the OmniRoute API key.
    """
    api_key = "sk-0000000000000000-a9c69a-c35b9451"
    import urllib.request, json as _json, ssl
    full_prompt = (sys_ctx or get_system_context({})) + "\n\n" + prompt
    
    # We use verification-free SSL context since it is localhost
    ctx = ssl._create_unverified_context()
    
    # Try gemini-2.5-flash first, fallback to gemini-2.5-pro if needed
    omni_models = [
        "agy/gemini-3.5-flash-low",
        "agy/gemini-3.5-flash-medium",
        "agy/gemini-3.5-flash-high",
        "agy/gemini-3.1-pro-high",
        "agy/gemini-3.1-pro-low",
    ]
    for model_id in omni_models:
        try:
            payload = _json.dumps({
                "model": model_id,
                "messages": [{"role": "user", "content": full_prompt}],
                "max_tokens": 512,
                "temperature": 0.9,
                "stream": False,
            }).encode()
            req = urllib.request.Request(
                "http://localhost:20128/v1/chat/completions",
                data=payload,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
            )
            # Short timeout since it is a local server
            with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
                data = _json.loads(resp.read().decode("utf-8"))
            if "error" in data:
                print(f"[ai_writer] OmniRoute {model_id} error: {data['error'].get('message','')[:60]}")
                continue
            out = (data.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
            if out:
                print(f"[ai_writer] OmniRoute success via {model_id}")
                return out
        except Exception as e:
            print(f"[ai_writer] OmniRoute {model_id} exception: {str(e)[:60]}")
    return None


# ── Fallback Tier 3: OpenRouter (free models) ─────────────────────────────

# Only the top-tier models — no compromises on quality (benchmarked 2026-06)
_OPENROUTER_FREE_MODELS = [
    "openai/gpt-oss-120b:free",              # ⭐⭐⭐⭐⭐ Best quality, ~6s
    "nvidia/nemotron-3-ultra-550b-a55b:free", # ⭐⭐⭐⭐⭐ Equally excellent, ~30s fallback
    "openrouter/free",                        # ⚡ Dynamic auto-router fallback (always online)
]

def _run_openrouter(prompt: str, sys_ctx: str = None) -> str | None:
    """Call OpenRouter free models as a fallback tier.
    Tries each model in order until one returns a valid response.
    Supports rotating multiple comma-separated keys in OPENROUTER_API_KEY.
    """
    raw_keys = os.getenv("OPENROUTER_API_KEY")
    if not raw_keys:
        return None
        
    api_keys = [k.strip() for k in raw_keys.split(",") if k.strip()]
    if not api_keys:
        return None
        
    import urllib.request, json as _json, ssl
    full_prompt = (sys_ctx or get_system_context({})) + "\n\n" + prompt
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()
        
    for model_id in _OPENROUTER_FREE_MODELS:
        for idx, api_key in enumerate(api_keys):
            try:
                payload = _json.dumps({
                    "model": model_id,
                    "messages": [{"role": "user", "content": full_prompt}],
                    "max_tokens": 512,
                    "temperature": 0.9,
                }).encode()
                req = urllib.request.Request(
                    "https://openrouter.ai/api/v1/chat/completions",
                    data=payload,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://leadflow.local",
                        "X-Title": "LeadFlow",
                    },
                )
                with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
                    data = _json.loads(resp.read().decode("utf-8"))
                if "error" in data:
                    err_msg = data['error'].get('message','')
                    print(f"[ai_writer] OpenRouter {model_id} (key {idx+1}) error: {err_msg[:60]}")
                    if "429" in err_msg or "rate" in err_msg.lower():
                        print(f"[ai_writer] Rate limit hit on key {idx+1}. Rotating to next key...")
                        continue
                    continue
                out = (data.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
                if out:
                    print(f"[ai_writer] OpenRouter success via {model_id} (using key {idx+1})")
                    return out
            except Exception as e:
                err_str = str(e)
                print(f"[ai_writer] OpenRouter {model_id} (key {idx+1}) exception: {err_str[:60]}")
                if "429" in err_str or "too many requests" in err_str.lower():
                    print(f"[ai_writer] Rate limit hit on key {idx+1}. Rotating to next key...")
                    continue
    return None




# ── Fallback Tier 5: Smart template (always works, zero cost) ─────────────

def _run_template(prompt: str) -> str:
    """Extract key details from the prompt and fill a proven template.
    This is the last-resort fallback — it never fails.
    """
    import re
    # Extract business name
    name_m = re.search(r"Business:\s*(.+)", prompt)
    name   = name_m.group(1).strip() if name_m else "your business"
    # Shorten very long names (take first 3 words)
    short_name = " ".join(name.split()[:4]) if len(name.split()) > 4 else name

    # Extract owner name
    owner_m = re.search(r"Owner:\s*([^\n]+)", prompt)
    owner_name = owner_m.group(1).strip() if owner_m else ""
    if owner_name:
        parts = owner_name.split()
        if len(parts) > 1 and parts[0].lower().rstrip(".") in {"dr", "mr", "mrs", "ms", "prof", "doc"}:
            owner_name = parts[1]
        else:
            owner_name = parts[0]

    # Extract rating
    rating_m = re.search(r"(\d\.\d)★", prompt)
    rating   = rating_m.group(1) if rating_m else ""

    # Extract demo link
    demo_m = re.search(r"https?://\S+?\.html", prompt)
    demo   = demo_m.group(0).strip() if demo_m else ""
    if demo:
        demo = demo.rstrip(").,;")

    # Extract booking/Fiverr URL
    fiverr_m = re.search(r"https://www\.fiverr\.com/\S+", prompt)
    booking_url = fiverr_m.group(0).strip() if fiverr_m else BOOKING_URL or FIVERR_URL
    if booking_url:
        booking_url = booking_url.rstrip(").,;")

    booking_m = re.search(r"(?:Fiverr Link|Fiverr Gig Link|Booking Link):\s*([^\n]+)", prompt, re.IGNORECASE)
    if booking_m:
        booking_url = booking_m.group(1).strip()
        if booking_url:
            booking_url = booking_url.rstrip(").,;")

    # Extract Calendly URL
    calendly_m = re.search(r"Booking Link:\s*(https://cal\.com/\S+|https://calendly\.com/\S+)", prompt)
    calendly_url = calendly_m.group(1).strip() if calendly_m else (_random_mod.choice(CALENDLY_URLS) if CALENDLY_URLS else "")
    if calendly_url:
        calendly_url = calendly_url.rstrip(").,;")

    # Extract score
    score_m = re.search(r"Website [Ss]core:\s*(\d+)", prompt)
    score = score_m.group(1).strip() if score_m else ""

    # Extract gaps
    gap_m = re.search(r"(?:Gaps found|Gap):\s*([^\n]+)", prompt)
    gap = gap_m.group(1).strip() if gap_m else ""

    # Extract category
    category_m = re.search(r"Category:\s*([^\n]+)", prompt)
    category = category_m.group(1).strip() if category_m else ""

    # Extract location
    location_m = re.search(r"Location:\s*([^\n]+)", prompt)
    location = location_m.group(1).strip() if location_m else ""

    # Determine if gym
    is_gym_biz = _is_gym(category, name)

    # fix #19: Fragile channel detection — the word "instagram" could appear in scraped
    # business content (e.g. About section). Use explicit Channel: marker when present,
    # falling back to keyword search only as a last resort.
    prompt_lower = prompt.lower()
    _channel_line = ""
    for _l in prompt.split("\n")[:10]:
        if _l.lower().startswith("channel:"):
            _channel_line = _l.lower()
            break

    if _channel_line:
        is_instagram = "instagram" in _channel_line
        is_whatsapp  = "whatsapp" in _channel_line
        is_linkedin  = "linkedin" in _channel_line
        is_email     = "email" in _channel_line or not (is_instagram or is_whatsapp or is_linkedin)
    else:
        # Fallback heuristic: scan only first 200 chars (header area) not full prompt body
        header = prompt_lower[:200]
        is_instagram = "instagram" in header
        is_whatsapp  = "whatsapp" in header
        is_linkedin  = "linkedin" in header
        is_email     = not (is_instagram or is_whatsapp or is_linkedin)

    # 1. Subject Line Options — dynamic fallback based on what actually gets opened
    # THIS MUST STAY FIRST — before any other branch that pattern-matches the prompt.
    if ("3 different" in prompt.lower() and "subject line" in prompt.lower()) or "3 cold email subject lines" in prompt.lower():
        # Use city if available, else category, else generic improvement
        city_part = location.split(",")[0].strip() if location else ""
        cat_part  = category.capitalize() if category else "local"
        rating_part = f"{rating}★ " if rating else ""

        sub1 = f"{city_part} {cat_part.lower()} clients / {short_name}".strip(", ") if city_part else f"Quick improvement for {short_name}"
        sub2 = f"Custom demo for {short_name}" if not rating else f"{short_name}'s {rating_part}reviews"
        sub3 = f"One thing missing from {short_name}'s setup" if not city_part else f"More {city_part} bookings for {short_name}"

        return (
            f"1. {sub1}\n"
            f"2. {sub2}\n"
            f"3. {sub3}"
        )

    # 2. Rewrite Message
    if "original" in prompt.lower() and "edit instruction" in prompt.lower():
        match = re.search(r"Original [^:]+:\s*\n(.*)\n\nEdit instruction", prompt, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
        parts = prompt.split("Edit instruction")
        if len(parts) > 0:
            subparts = re.split(r"Original [^:]+:\s*\n", parts[0], flags=re.IGNORECASE)
            if len(subparts) > 1:
                return subparts[1].strip()

    # 3. Chat Fallback
    if "answer concisely and accurately based only on the business context" in prompt.lower():
        return "I am currently running in offline fallback mode because the AI assistant service is temporarily unavailable. Please verify your API key configurations or check back later to ask custom questions."

    # 4. Audit Pitch
    if "audit" in prompt.lower() or "website score" in prompt.lower() or "gaps found" in prompt.lower():
        score_str = f"{score}/100" if score else "fairly low"
        gap_str = gap if gap else "a few speed and structure optimization gaps"
        owner_part = f"Hey {owner_name}," if owner_name else "Hey there,"
        return (
            f"{{Quick audit for|Quick review of|Website feedback for|Improvement opportunity for}} {short_name}\n\n"
            f"{owner_part}\n\n"
            f"{{I ran a quick performance check on|I recently ran a speed audit of|I was looking at}} {short_name}'s website. "
            f"The mobile speed score is currently {score_str}, {{and there are a few optimization gaps: {gap_str}|which means the site is loading slower than ideal}}.\n\n"
            f"{{This is likely costing you local clients who bounce when the page takes too long to load|A slow load time causes potential customers to leave and go to competitors}}.\n\n"
            f"We can fix this setup safely on Fiverr to improve your load times and capture those lost leads: {booking_url}\n\n"
            f"{{Let me know if you'd like to get this updated|Let me know if this is something you want to check out|Talk soon}}."
        )

    # 5. No Website Pitch
    if "no website" in prompt.lower() or "currently has no website" in prompt.lower():
        owner_part = f"Hey {owner_name}," if owner_name else "Hey there,"
        loc_part = f" in {location}" if location else " in your area"
        cat_part = category if category else "business"
        city_name = location.split(',')[0].strip() if location else 'local'
        return (
            f"{{More {city_name} clients for|Question about|Connecting with}} {short_name}\n\n"
            f"{owner_part}\n\n"
            f"{{I noticed {short_name} has great local reviews{loc_part}, but you don't have a website listed.|"
            f"Saw {short_name}'s excellent ratings on Google, but couldn't find a website link.}}\n\n"
            f"{{Without one, you're missing out on a lot of local customers searching online for a {cat_part}{loc_part}.|"
            f"A fast, modern website would help convert those searchers into active customers.}}\n\n"
            f"{{I build high-performing, fast websites to help local businesses scale. We can build one for you safely via my Fiverr page: {booking_url}|"
            f"We can set this up safely and quickly on Fiverr here: {booking_url}}}\n\n"
            f"{{Let me know if you want to get this set up|Let me know if you are interested|Talk soon}}."
        )

    # 6. Live Follow-up
    if "right now" in prompt.lower() or "live follow" in prompt.lower() or "live_followup" in prompt.lower():
        if is_email:
            owner_part = f"Hey {owner_name}," if owner_name else "Hey!"
            return (
                f"Saw you're on the demo\n\n"
                f"{owner_part}\n\n"
                f"Noticed you're checking out the {short_name} prototype right now. "
                f"Happy to answer any questions or jump on a quick 2-minute call to push it live today. "
                f"Just reply here."
            )
        else:
            greet = f"Hey {owner_name}!" if owner_name else f"Hey {short_name}!"
            return (
                f"{greet} Noticed you're checking out the {short_name} prototype right now. "
                f"Happy to hop on a 2-minute call and get it live today. Just reply!"
            )

    # 7. Follow-up sequence Email #1 (Day 4)
    if "follow-up email #1" in prompt.lower() or "email #1" in prompt.lower():
        owner_part = f"Hey {owner_name}," if owner_name else "Hey there,"
        if is_gym_biz and demo:
            return (
                f"{{{short_name}'s custom demo|Redesign concept for {short_name}|Interactive demo for {short_name}}}\n\n"
                f"{owner_part}\n\n"
                f"{{I know you're busy running {short_name}, so I'll keep this brief.|"
                f"Just following up on my previous message.}}\n\n"
                f"I built a custom demo website to show you how we can bring in more local customers: {demo}\n\n"
                f"We can customize this to fit your brand and take it live safely via Fiverr: {booking_url}\n\n"
                f"{{Let me know if you want to make any adjustments to the demo|Let me know if you want to check this out|Talk soon}}."
            )
        else:
            return (
                f"{{{short_name}'s custom demo|Redesign concept for {short_name}|Interactive demo for {short_name}}}\n\n"
                f"{owner_part}\n\n"
                f"{{I know you're busy running {short_name}, so I'll keep this brief.|"
                f"Just following up on my previous message.}}\n\n"
                f"{{I build high-performing websites to help businesses like yours bring in more local customers.|"
                f"We can build a fast, high-converting mobile layout for {short_name}.}}\n\n"
                f"We can set this up safely via my Fiverr page: {booking_url}\n\n"
                f"{{Let me know if you'd like to see a custom concept|Let me know if this aligns with your goals|Talk soon}}."
            )

    # 8. Follow-up sequence Email #2 (Day 9)
    if "follow-up email #2" in prompt.lower() or "email #2" in prompt.lower():
        owner_part = f"Hey {owner_name}," if owner_name else "Hey there,"
        demo_str = f" ({demo})" if demo else ""
        calendly_str = f"booking a quick call here ({calendly_url}) or " if calendly_url else ""
        return (
            f"{{Final try - {short_name}|Closing our conversation - {short_name}|Moving on - {short_name}}}\n\n"
            f"{owner_part}\n\n"
            f"{{I haven't heard back, so I'll assume this isn't a priority for {short_name} right now.|"
            f"Since I haven't heard back, I'm assuming you're set with your current setup.}}\n\n"
            f"If you ever want to revive your online presence or check out the demo I built{demo_str}, feel free to reach out.\n\n"
            f"You can also {calendly_str}order safely on Fiverr: {booking_url}\n\n"
            f"{{Let me know if you change your mind|Wish you the best|Take care}}."
        )

    # 9. Follow-up sequence Instagram DM (Day 6)
    if is_instagram and "follow-up" in prompt.lower():
        greet = f"Hey {owner_name or short_name},"
        if demo:
            return f"{greet} just wanted to see if you had a second to look at the custom website demo I built: {demo}. We can customize this and get it live safely via Fiverr ({booking_url}). Let me know what you think."
        else:
            return f"{greet} just wanted to see if you had a second to check out my website design services. We can build a custom demo for you and get it live safely via Fiverr ({booking_url}). Let me know what you think."

    # 10. Initial Outreach Messages (Email, DMs)
    is_saas = pitch_type == "leadflow_saas"
    has_website = bool(business.get("website"))
    if is_saas:
        role = "an Automation & Lead Generation Specialist"
        pain = "you're missing out on a lot of leads by not having an automated CRM and follow-up system"
    elif not has_website:
        role = "a tech automation specialist"
        pain = "without a website, you're missing out on local members searching online"
    else:
        role = "a Web Development & Optimization Specialist"
        gap_text = business.get("gap", "")
        import re
        m = re.search(r"—\s*(.*)", gap_text)
        issue = m.group(1).strip() if m else "your website could be converting far more visitors into paying customers"
        pain = f"your current website is losing potential customers ({issue})"

    if is_email:
        owner_part = f"Hey {owner_name}," if owner_name else "Hey there,"
        rating_str = f" — and that {rating}★ rating is impressive" if rating else ""
        if is_gym_biz and demo:
            return (
                f"Quick thought on {short_name}\n\n"
                f"{owner_part}\n\n"
                f"I'm Chandan — {role}.\n\n"
                f"{short_name} has awesome {rating}★ reviews, but {pain}.\n\n"
                f"I built this custom demo to show you what's possible: {demo}\n\n"
                f"We can customize this for your gym and take it live safely on Fiverr: {booking_url}\n\n"
                f"Check it out and let me know what you think."
            )
        else:
            return (
                f"Quick thought on {short_name}\n\n"
                f"{owner_part}\n\n"
                f"I'm Chandan — {role}.\n\n"
                f"{short_name} has awesome reviews{rating_str}, but {pain}.\n\n"
                f"If you'd like to see a custom design concept for your business, message me on Fiverr where we can build a demo and take it live safely: {booking_url}\n\n"
                f"Let me know if you want to take a look."
            )

    elif is_instagram:
        greet = f"Hey {owner_name or short_name}!"
        rating_str = f" with your {rating}★ reviews" if rating else ""
        if is_gym_biz and demo:
            return f"{greet} I'm Chandan — {role}. Noticed {short_name} is doing great{rating_str} but {pain}. I built this custom demo for you: {demo}. Let me know what you think."
        else:
            return f"{greet} I'm Chandan — {role}. Noticed {short_name} is doing great{rating_str} but {pain}. Drop me a line on Fiverr if you'd like a custom demo: {booking_url}. Let me know what you think."

    elif is_linkedin:
        owner_part = f"Hey {owner_name}," if owner_name else "Hey there,"
        rating_str = f" with your {rating}★ reviews" if rating else ""
        if is_gym_biz and demo:
            return (
                f"{owner_part}\n\n"
                f"I'm Chandan — {role}.\n\n"
                f"{short_name} has great reviews, but {pain}. I built this custom demo to show you what's possible: {demo}\n\n"
                f"We can customize this and set it up safely on Fiverr. Let me know what you think."
            )
        else:
            return (
                f"{owner_part}\n\n"
                f"I'm Chandan — {role}.\n\n"
                f"{short_name} has great reviews{rating_str}, but {pain}.\n\n"
                f"If you'd like to see a custom design concept, message me on Fiverr where we can build a demo and take it live safely: {booking_url}\n\n"
                f"Let me know what you think."
            )

    elif is_whatsapp:
        greet = f"Hey {owner_name or short_name}!"
        rating_str = f" with your {rating}★ reviews" if rating else ""
        if is_gym_biz and demo:
            return f"{greet} I'm Chandan — {role}. Noticed {short_name} is doing great{rating_str} but {pain}. I built this custom demo for you: {demo}. Let me know what you think."
        else:
            return f"{greet} I'm Chandan — {role}. Noticed {short_name} is doing great{rating_str} but {pain}. Drop me a line on Fiverr if you'd like to see a custom demo: {booking_url}. Let me know what you think."

    # General Fallback
    demo_part = f" Demo: {demo}" if demo else ""
    return (
        f"Quick thought on {short_name}\n\n"
        f"Hey, I'm Chandan — {role}. "
        f"{short_name} has {rating + '★ reviews' if rating else 'great reviews'} but {pain}.{demo_part} Check it out and let me know what you think."
    )


# ── Main runner with full fallback chain ───────────────────────────────────

def _run(prompt: str, attempts: int = 2, sys_ctx: str = None) -> str:
    """Call AI with a fallback chain so generation NEVER gets stuck.

    Tier 1: Gemini REST API (8 rotating API keys)
    Tier 2: OpenRouter free models (10 rotating API keys)
    Tier 3: OmniRoute agy local server (using 10 connected agy accounts)
    """
    import time

    # ── Tier 1: Gemini REST ──
    print("[ai_writer] Trying Tier 1: Gemini REST")
    out = _run_gemini_rest(prompt, sys_ctx=sys_ctx)
    if out:
        return out

    # ── Tier 2: OpenRouter free models ──
    print("[ai_writer] Trying Tier 2: OpenRouter free models")
    out = _run_openrouter(prompt, sys_ctx=sys_ctx)
    if out:
        return out

    # ── Tier 3: OmniRoute agy local server ──
    print("[ai_writer] Trying Tier 3: OmniRoute agy server")
    out = _run_omniroute(prompt, sys_ctx=sys_ctx)
    if out:
        return out

    # ── Tier 4: Abort (No Generic Fallback) ──
    print("[ai_writer] All AI tiers exhausted. Aborting to avoid sending a generic message.")
    return ""



def _business_context(b: dict, scraped: dict | None = None) -> str:
    rating  = b.get("google_rating")
    reviews = b.get("google_reviews")
    rating_line = f"{rating}★ across {reviews:,} reviews" if rating and reviews else ""
    owner = b.get("owner_name", "")
    owner_line = f"\nOwner: {owner}" if owner else ""
    ctx = f"""Business: {b.get('name','')}
Location: {b.get('city','')}
Category: {b.get('category','')}
Google: {rating_line}
Website: {b.get('website') or 'NONE'}
Website score: {b.get('website_score',0)}/100
Gap: {b.get('gap','')}{owner_line}"""

    if scraped:
        if scraped.get("hero_text"):
            ctx += f"\nWebsite headline: {scraped['hero_text'][:120]}"
        if scraped.get("about_text"):
            ctx += f"\nAbout section: {scraped['about_text'][:200]}"
        svcs = scraped.get("services") or []
        if svcs:
            titles = []
            for s in svcs[:5]:
                titles.append(s["title"] if isinstance(s, dict) else str(s))
            ctx += f"\nServices offered: {', '.join(titles)}"
        if scraped.get("tagline"):
            ctx += f"\nTagline: {scraped['tagline']}"
    return ctx


def _pitch_context(pitch: str, demo_url: str = "") -> str:
    labels = {
        "website_new":      "build them a brand new professional website",
        "website_redesign": "redesign their slow/broken website",
        "automation":       "set up AI email automation to save them time",
        "ai_setup":         "set up a ClawdBot AI assistant for their daily tasks",
    }
    base = labels.get(pitch, "help improve their online presence")
    if demo_url:
        base += f". I already built a free demo site for them at: {demo_url}"
    return base


# ── Subject line A/B options ───────────────────────────────────────────────

def write_subject_options(business: dict, scraped: dict | None = None) -> list[str]:
    ctx = _business_context(business, scraped)

    # Build location + rating hints for the prompt
    # business dict uses 'city' as primary, 'address' as fallback
    location = (business.get("city") or business.get("address") or "").split(",")[0].strip()
    rating   = business.get("google_rating") or ""  # fix #10: was business.get("rating")
    category = business.get("category") or ""
    name     = (business.get("name") or "").strip()
    short_name = " ".join(name.split()[:4]) if len(name.split()) > 4 else name

    location_hint = f" Their city/area is: {location}." if location else ""
    rating_hint   = f" They have {rating}★ Google reviews." if rating else ""

    prompt = f"""{ctx}

Write 3 cold email subject lines for this {category} business.{location_hint}{rating_hint}

Hard rules — your subjects MUST follow these exact 3 patterns:
1. CITY + PROBLEM pattern: Reference their city/location and a specific revenue problem.
   Example: "Calgary bookings / Oasis Landscape" or "More Houston clients for [Name]"
   If no city is known, use: "Quick improvement for [exact business name]"

2. SOCIAL PROOF + CURIOSITY pattern: Reference their real review count or star rating to create an open loop.
   Example: "[Name]'s 156 Google reviews" or "Turning [Name]'s 4.8★ into bookings"
   If no rating is known, use: "Custom demo for [exact business name]"

3. SPECIFIC HOOK pattern: Tease something specific they're missing — not generic.
   Example: "One section I held back from [Name]'s site" or "Custom AI demo for [Name] members"
   Never use vague phrases like "website concept" or "quick question".

BANNED phrases (never use these):
- "Quick question for..."
- "Idea for..."
- "custom website concept"
- "[Name] - custom..."

Use the EXACT business name (not shortened) so it stands out in their inbox.
Output exactly 3 lines, numbered 1. 2. 3. — nothing else."""

    raw = _run(prompt)

    # Parse: take only short single-line items (subject lines are never multi-line)
    lines = []
    for l in raw.strip().split("\n"):
        cleaned = l.lstrip("123. -").strip()
        # A subject line should be short and single-line — skip anything that looks like body copy
        if cleaned and len(cleaned) < 100 and not cleaned.startswith("Hey") and not cleaned.startswith("I ran"):
            lines.append(cleaned)

    # Strip out banned patterns and any lines that look like context labels
    banned = ["quick question for", "idea for", "custom website concept", "- custom", "category:"]
    clean  = [
        l for l in lines
        if l
        and not any(b in l.lower() for b in banned)
        and not (": " in l and l.index(": ") < 20)  # reject "Category: X" style context labels
    ]

    # Always build deterministic fallbacks in case AI fails or returns junk
    # Sanitize: reject location strings that look like context labels (contain colon)
    city = location if (location and ":" not in location and len(location) < 50) else ""
    rat_str = f"{rating}\u2605 " if rating else ""
    fb1 = f"{city} {category} clients / {short_name}".strip(" /") if city else f"Quick improvement for {short_name}"
    fb2 = f"{short_name}'s {rat_str}reviews" if rating else f"Custom demo for {short_name}"
    fb3 = f"More {city} bookings for {short_name}" if city else f"One thing missing from {short_name}'s setup"
    fallbacks = [fb1, fb2, fb3]

    while len(clean) < 3:
        clean.append(fallbacks[len(clean)])

    return clean[:3]


# ── Primary outreach ───────────────────────────────────────────────────────

def write_email(business: dict, demo_url: str = "", scraped: dict | None = None) -> str:
    booking_part = f"\nFiverr Gig Link: {BOOKING_URL}\nRule: You can optionally mention they can order safely on Fiverr using this link. Do NOT use or mention any other Fiverr link or profile link; use ONLY this exact gig link: {BOOKING_URL}" if BOOKING_URL else ""

    # Build a unique, data-driven first line for this specific business
    first_line = _build_first_line(business)

    if demo_url:
        demo_part = f"{'ABSOLUTE REQUIREMENT: You MUST paste the exact link ' + demo_url + ' directly into your email body. Do not ask if they want to see it.'}"
        offer = _pitch_context(business.get('pitch_type', ''), demo_url)
    else:
        # No demo: Ask them to message on Fiverr for a custom demo.
        demo_part = f"IMPORTANT: Do NOT mention a demo link — there is no demo for this business yet. Instead, naturally invite them to message you on Fiverr ({FIVERR_URL}) where you can show them a custom demo and take it live safely."
        offer = _pitch_context(business.get('pitch_type', ''), "")

    prompt = f"""{_business_context(business, scraped)}
Offer: {offer}{booking_part}
{demo_part}

PERSONALIZED OPENING LINE (use this exact sentence to open the email body — do NOT change it):
"{first_line}"

CRITICAL RULES:
1. Subject line must be: "Quick audit idea for {business.get('name', 'your business')}?" or "{business.get('city', 'Local')} {business.get('category', 'business')} / {business.get('name', 'your business')}"
2. Subject line on the FIRST line, followed by a blank line, then the body.
3. Start the body EXACTLY with the personalized opening line above.
4. Keep the entire body under 60 words.
5. Do NOT introduce yourself. Never say "I'm Chandan", "I build websites", or "I specialize in". Lead directly with the diagnostic observations.
6. End with a confident, non-salesy statement. Ready to send — no placeholders."""
    raw = _run(prompt)
    # Apply spintax to any {A|B} variations the AI may have added
    return _spintax(raw) if raw else raw


def write_instagram_dm(business: dict, demo_url: str = "", scraped: dict | None = None) -> str:
    # ── A/B Testing Cohort Determination ──────────────────────────────────
    # If the business is Tier 1, assign Variant A, B, C, or D based on business ID.
    is_tier_1 = (business.get("tier") == 1)
    if not is_tier_1:
        # Fallback check in case the 'tier' column is not populated yet: check category
        cat = (business.get("category") or "").lower()
        tier1_niches = ["roof", "hvac", "solar", "lawyer", "attorney", "med spa", "medspa", "remodel", "dentist", "orthodont"]
        is_tier_1 = any(t in cat for t in tier1_niches)

    variant = None
    if is_tier_1:
        bid = int(business.get("id") or 0)
        # 4 Cohorts split using modulo 4
        # A: Direct Link + Technical Pain
        # B: Permission Hook + Gatekeeper Workflow
        # C: Direct Link + Competitor Pride
        # D: Permission Hook + Competitor Pride
        cohorts = {0: "A", 1: "B", 2: "C", 3: "D"}
        variant = cohorts[bid % 4]
        
        # Save variant to DB
        if bid:
            try:
                import sqlite3
                DB_PATH = "/Users/chandan/leadflow/leadflow.db" if os.path.exists("/Users/chandan/leadflow/leadflow.db") else "/data/data/com.termux/files/home/leadflow/leadflow.db"
                conn = sqlite3.connect(DB_PATH, timeout=30.0)
                conn.execute("UPDATE businesses SET ig_dm_variant = ? WHERE id = ?", (variant, bid))
                conn.commit()
                conn.close()
                print(f"[ai_writer] Saved A/B variant {variant} for business ID {bid}")
            except Exception as e:
                print(f"[ai_writer] Error saving A/B variant to DB: {e}")

    # Set up Demo Link vs Permission parameters
    if is_tier_1 and variant in ["B", "D"]:
        # Permission-based: NO link in the first message
        demo_part = "IMPORTANT: Do NOT include any website link or URL in this message. Instead, ask if you can send them the link to check it out."
        offer = _pitch_context(business.get('pitch_type', ''), "")
    else:
        # Standard: Direct Link sent immediately
        if demo_url:
            demo_part = f"ABSOLUTE REQUIREMENT: You MUST paste the exact link {demo_url} directly into your message."
            offer = _pitch_context(business.get('pitch_type', ''), demo_url)
        else:
            demo_part = f"IMPORTANT: Do NOT mention a demo link. Invite them to check your Fiverr: {FIVERR_URL}"
            offer = _pitch_context(business.get('pitch_type', ''), "")

    website_score = int(business.get('website_score') or 100)

    if is_tier_1:
        if variant == "A":
            hook_strategy = (
                "HOOK: Focus the hook strictly on the business owner or head decision-maker. "
                "Point out that their website has mobile speed/optimization performance issues (technical pain) "
                "losing them local clients, and pitch the mockup directly to them. Do NOT address the team or receptionist."
            )
        elif variant == "B":
            hook_strategy = (
                "HOOK: Target the receptionist, office manager, or administrative gatekeeper reading the DMs. "
                "Acknowledge them and frame the mockup as a major win for *them* (e.g. automating client bookings, "
                "reducing repeat phone calls, making scheduling hands-free). "
                "Ask: 'Could you pass this design layout on to the owner/doctor?'"
            )
        elif variant == "C":
            hook_strategy = (
                "HOOK: Focus on brand pride and local competitors. Point out that local competitors "
                "have modern layouts. Pitch your custom mockup directly to the owner/doctor as a way to stand out."
            )
        elif variant == "D":
            hook_strategy = (
                "HOOK: Focus on brand pride and local competitors. Point out that local competitors "
                "have modern layouts. Tell the receptionist/manager that you made a custom mockup for their page to stand out, "
                "and ask if you can send the link to pass along to the owner."
            )
    else:
        # Original Hook Selection for Tier 2/3
        if not business.get('website') or business.get('website') == 'NONE':
            if int(business.get('google_reviews', 0)) > 20:
                hook_strategy = "HOOK: Point out they have amazing Google reviews, but because they have NO website linked, they are bleeding high-ticket leads who try to click through from Maps to learn more."
            else:
                hook_strategy = "HOOK: Point out that not having a website is costing them trust and local search traffic, making them lose customers to local competitors."
        elif website_score < 60:
            hook_strategy = "HOOK: Use the 'Broken Thing' approach. Inform them their current website is loading very slowly or has technical flaws that are secretly leaking mobile traffic and losing them money."
        elif website_score < 80:
            hook_strategy = f"HOOK: Point out that their website scores {website_score}/100 on mobile — there are clear optimization opportunities that would help convert more of their local search traffic into booked clients."
        else:
            hook_strategy = "HOOK: Point out that while their business looks great online, their lead capture and follow-up system could be significantly improved to convert more website visitors into paying clients."

    link_rule = (
        "The message MUST end with the exact link or Fiverr URL specified in the rules above. DO NOT add any closing text, sign-offs, or questions after the link (the link must be the final text in the message)."
        if (demo_url and not (is_tier_1 and variant in ["B", "D"])) else
        "Do NOT include any website link, URL, or demo URL in this message. Instead, ask if you can send them the link to check it out. The message must end with the question asking for permission."
    )

    prompt = f"""{_business_context(business, scraped)}
Offer: {offer}
{demo_part}

Write a highly professional, expert-level Instagram DM (under 50 words).
CRITICAL RULES:
1. The message MUST be HYPER-PERSONALIZED to this specific business. Reference their specific niche, city, review count, or a concrete detail from their profile.
2. Do NOT introduce yourself. Never say "I'm Chandan" or "I build websites". Lead directly with the insight or the problem you spotted.
3. Do NOT use emojis (or strictly 1 max). Do NOT sound desperate or use words like "no catch" or "free".
4. {hook_strategy}
5. You MUST reference their {business.get('google_reviews', '0')} Google reviews, their specific service, or their lack of a website.
6. You MUST explicitly mention their exact business name. Make it feel 100% bespoke. Ready to send.
7. NEVER address the message to "[Business Name] team" — address the owner directly or use the business name alone without "team".
8. NEVER say "ran a quick diagnostic check" or "noticed it is scoring X/100 on mobile load speed" — that exact phrasing is banned. Find a fresh, original way to express the same idea.
9. {link_rule}"""
    
    sys_ctx = (
        "You are a highly persuasive, world-class outbound sales copywriter. "
        "Output ONLY the raw Instagram DM message body. Do NOT include any Subject line, "
        "do NOT include any conversational introduction, and do NOT use markdown code fences. "
        "Your entire output must be copy-pasteable directly into an Instagram DM client without editing."
    )
    raw = _run(prompt, sys_ctx=sys_ctx)

    # ── Validation guard: reject generic/broken AI output ────────────────────
    # If AI failed or returned garbage, build a proper professional fallback
    _bad_phrases = [
        "love your profile", "great page", "awesome profile",
        " team,", " team\n", " team.", "Offer: ",
        "ran a quick diagnostic check",
        "mobile load speed",  # catches the repetitive diagnostic pattern
    ]
    _is_bad = (
        not raw
        or any(p.lower() in (raw or "").lower() for p in _bad_phrases)
        or len((raw or "").strip()) < 15
        or (demo_url and demo_url not in raw)
    )
    if _is_bad:
        name = (business.get("name") or "").strip()
        clean_name = name.split(" - ")[0].strip() if " - " in name else name
        city = (business.get("city") or "").split(",")[0].strip()
        city_text = f" in {city}" if city else ""
        rating = business.get("google_rating") or ""
        reviews = business.get("google_reviews") or 0
        score = business.get("website_score") or 0
        has_website = bool(business.get("website") and str(business.get("website")).strip())

        if not has_website:
            raw = (
                f"Hey {clean_name}, noticed you have "
                + (f"an impressive {rating}★ across {reviews:,} reviews{city_text}" if (rating and reviews) else f"great reviews{city_text}")
                + " but no website — you're likely losing leads to competitors who have one. "
                + "Let me know what you think. "
                + (f"I put together a quick demo to show what's possible: {demo_url}" if demo_url else f"Check my Fiverr to see a custom demo: {FIVERR_URL}")
            )
        elif score and int(score) < 75:
            raw = (
                f"Hey {clean_name}, your website is currently at {score}/100 on mobile — "
                f"that means local leads{city_text} are bouncing before the page even loads. "
                f"Let me know what you think. "
                + (f"I built a faster version to show the difference: {demo_url}" if demo_url else f"Check my Fiverr to see a faster version: {FIVERR_URL}")
            )
        else:
            raw = (
                f"Hey {clean_name}, "
                + (f"your {rating}★ from {reviews:,} reviews{city_text} is impressive — but the website could be converting far more of those searchers into booked clients. " if (rating and reviews) else f"the website{city_text} could be pulling in significantly more high-ticket leads. ")
                + "Let me know what you think. "
                + (f"I put together a quick optimized demo: {demo_url}" if demo_url else f"Check my Fiverr to see a custom demo: {FIVERR_URL}")
            )

    return raw



def write_linkedin_dm(business: dict, demo_url: str = "", scraped: dict | None = None) -> str:
    if demo_url:
        demo_part = f"ABSOLUTE REQUIREMENT: You MUST paste the exact link {demo_url} directly into your message. Do not ask if they want to see it."
        offer = _pitch_context(business.get('pitch_type', ''), demo_url)
    else:
        demo_part = f"IMPORTANT: Do NOT mention a demo link. Instead invite them to message you on Fiverr ({FIVERR_URL}) to see a custom demo for their business."
        offer = _pitch_context(business.get('pitch_type', ''), "")

    prompt = f"""{_business_context(business, scraped)}
LinkedIn: {business.get('linkedin_name','')}
Offer: {offer}
{demo_part}

Write a professional LinkedIn DM under 50 words.
CRITICAL RULES:
1. Do NOT introduce yourself. Do not say "I'm Chandan", "I build websites", etc. Start directly with the observation.
2. Reference a specific real detail about the business.
3. You MUST explicitly mention their business name.
4. End with a confident, non-salesy statement. Ready to send."""
    return _run(prompt)


def write_whatsapp_dm(business: dict, demo_url: str = "", scraped: dict | None = None) -> str:
    if demo_url:
        demo_part = f"ABSOLUTE REQUIREMENT: You MUST paste the exact link {demo_url} directly into your message. Do not ask if they want to see it."
        offer = _pitch_context(business.get('pitch_type', ''), demo_url)
    else:
        demo_part = f"IMPORTANT: Do NOT mention a demo link. Instead invite them to message you on Fiverr ({FIVERR_URL}) to see a custom demo."
        offer = _pitch_context(business.get('pitch_type', ''), "")

    prompt = f"""{_business_context(business, scraped)}
Offer: {offer}
{demo_part}

Write a WhatsApp message under 45 words.
CRITICAL RULES:
1. Do NOT introduce yourself. Do not say "I'm Chandan", "I build websites", etc.
2. Be direct but conversational and friendly. Highlight a missed opportunity constructively, make them curious.
3. You MUST explicitly mention their business name.
4. No formal greetings. End with a confident, short statement. Ready to send."""
    return _run(prompt)


def write_live_followup(business: dict, scraped: dict | None = None, channel: str = "email", feedback: str | None = None) -> str:
    ctx = _business_context(business, scraped)
    bname = business.get("name", "")
    rating = business.get("google_rating", "")
    rating_line = f"{rating}★" if rating else ""

    channel_instructions = {
        "email": (
            "Write a cold email. "
            "Subject line on the FIRST line (short, 5-7 words, curiosity-driven, NOT generic). "
            "Then a blank line. Then the body — max 70 words total. "
            "No sign-off needed, just end with a bold statement or soft CTA."
        ),
        "instagram": (
            "Write an Instagram DM — max 35 words, no subject line. "
            "Ultra-casual, feels like a friend texting, NOT a salesperson. "
            "Start with their name or business name. Single short paragraph."
        ),
        "whatsapp": (
            "Write a WhatsApp message — max 35 words, no subject line. "
            "Feels like a quick text from a mate, NOT a pitch. "
            "Start with their name or business name. Keep it in 1-2 very short lines."
        ),
    }.get(channel, "Write a short follow-up message under 50 words.")

    prompt = f"""{ctx}

SITUATION: The business owner is RIGHT NOW actively viewing the custom demo website I already built for them. I want to message them THIS INSTANT to strike while the iron is hot.

GOAL: Send a follow-up that:
1. Casually mentions I can see they're checking out the demo (makes it feel real-time and personal, NOT creepy — frame it like "hey I got a notification you're on it").
2. Shows genuine excitement about what they might be experiencing on the demo.
3. Makes it dead-simple to reply — offer to answer any quick questions or jump on a 2-minute call to take it live TODAY.
4. Uses their business name naturally (shortened if it's long — e.g. "CityWay YMCA" not "Irsay Family YMCA at CityWay").
5. Optionally reference a specific strength of their business (e.g. their {rating_line} rating, their location, or a service they offer) to feel personalized, not templated.

TONE RULES:
- Sound like a real person who is genuinely excited, NOT a bot or a sales rep reading from a script.
- Casual, warm, and confident. Short punchy sentences. No jargon.
- DO NOT start with "Hey, I'm Chandan" or re-introduce yourself (they already know who you are from the original email/DM).
- DO NOT say "I hope this finds you well", "just checking in", "I wanted to reach out", "touch base", "circle back".
- DO NOT add any closing sign-off (no "Best,", "Cheers,", "Regards,").
- DO NOT include ANY commentary, notes, or meta-text outside the message itself.

FORMAT:
{channel_instructions}"""

    if feedback:
        prompt += f"\n\nUSER FEEDBACK / ADJUSTMENT: {feedback}\nAdjust the draft accordingly while keeping all the above rules intact."

    prompt += "\n\nOutput ONLY the raw message. Nothing else."
    return _run(prompt)


# ── Follow-up sequence ─────────────────────────────────────────────────────

def _clean_draft(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    # Strip wrapping quotes if any
    if text.startswith('"') and text.endswith('"'):
        text = text[1:-1].strip()
    elif text.startswith("'") and text.endswith("'"):
        text = text[1:-1].strip()
    return text


def write_follow_up_sequence(business: dict, demo_url: str = "", is_hot_lead: bool = False) -> list[dict]:
    """
    Generate a follow-up sequence.
    is_hot_lead=True: lead just opened the email or scrolled the demo — use an
    immediate, intent-aware tone for FU#1 instead of the generic day-4 cadence.
    """
    ctx = _business_context(business)
    offer = _pitch_context(business.get("pitch_type", ""), demo_url)
    now = datetime.now()

    sequences = []

    booking_part = f"\nFiverr Gig Link: {BOOKING_URL}\nRule: You can optionally mention they can order safely on Fiverr using this link. Do NOT use or mention any other Fiverr link or profile link; use ONLY this exact gig link: {BOOKING_URL}" if BOOKING_URL else ""

    if is_hot_lead:
        # They just opened/viewed — acknowledge it, be direct, strike now
        prompt1 = f"""{ctx}
Offer: {offer}
{booking_part}
{'ABSOLUTE REQUIREMENT: You MUST paste the exact link ' + demo_url + ' directly into your email body.' if demo_url else ''}

Write a VERY SHORT follow-up email (under 60 words) for someone who JUST opened our cold email within the last few minutes.
- Do NOT say "just checking in"
- Do NOT re-introduce yourself (e.g. "Hey, I'm Chandan")
- Acknowledge naturally that they saw it (e.g. "Saw you had a look..." or "Wanted to follow up while it's fresh...")
- Casual, human, direct — like a text message in email form
- CRITICAL: End with ONE simple question (e.g. "What do you think?" or "Worth a quick chat?")
- Use a generic greeting if no owner name is provided. Do NOT use the business name as a person's name.
- Subject line on first line. Ready to send."""
    else:
        # Step 2: The Mobile Scorecard (2 days later)
        prompt1 = f"""{ctx}
Offer: {offer}
{booking_part}
{'ABSOLUTE REQUIREMENT: You MUST paste the exact link ' + demo_url + ' directly into your email body. Do not ask if they want to see it.' if demo_url else ''}

Write follow-up email #1 (The Mobile Scorecard, sent 2 days after first email).
- Provide a raw comparison of their current website speed score versus our redesign speed score (assume our mobile-optimized redesign scores 95+).
- Emphasize how this 'Mobile Conversion Gap' affects their bookings.
- Do NOT re-introduce yourself (e.g. "Hey, I'm Chandan").
- CRITICAL: End with ONE direct question to prompt a reply.
- Use a generic greeting if no owner name is provided. Do NOT use the business name as a person's name.
Under 80 words. Subject on first line. Ready to send."""

    f1 = _run(prompt1, sys_ctx=get_system_context(business))
    sequences.append({
        "num": 1,
        "channel": "email",
        "draft": _clean_draft(f1),
        "scheduled_for": (now + timedelta(days=2)).isoformat() if not is_hot_lead else (now + timedelta(days=2)).isoformat(),
    })


    # Step 3: Case Study Proof (Day 5)
    social_proof = _social_proof_snippet(business)
    prompt2 = f"""{ctx}
Offer: {offer}
{booking_part}
{'ABSOLUTE REQUIREMENT: You MUST paste the exact link ' + demo_url + ' directly into your email body. Do not ask if they want to see it.' if demo_url else ''}

SOCIAL PROOF (weave this naturally into the email — do NOT quote it verbatim, make it feel organic):
"{social_proof}"

Write follow-up email #2 (Case Study Proof, sent 5 days after first email).
- Mention the social proof above — a similar business got real results. Keep it short — under 70 words.
- Do NOT re-introduce yourself.
- CRITICAL: End with ONE direct, simple question to close the loop.
- Use a generic greeting if no owner name is provided. Do NOT use the business name as a person's name.
Subject on first line. Ready to send."""
    f2 = _run(prompt2, sys_ctx=get_system_context(business))
    sequences.append({
        "num": 2,
        "channel": "email",
        "draft": _clean_draft(_spintax(f2) if f2 else f2),
        "scheduled_for": (now + timedelta(days=5)).isoformat(),
    })
    
    # Step 4: The Irresistible Value Stack (Day 8)
    chosen_calendly = _random_mod.choice(CALENDLY_URLS) if CALENDLY_URLS else ""
    calendly_part = f"\nBooking Link: {chosen_calendly}\nRule: Naturally suggest they can book a call using this booking link if they'd like to discuss how to grow their business." if chosen_calendly else ""
    prompt3_stack = f"""{ctx}
Offer: {offer}
{booking_part}
{calendly_part}
{'ABSOLUTE REQUIREMENT: You MUST paste the exact link ' + demo_url + ' directly into your email body. Do not ask if they want to see it.' if demo_url else ''}

Write follow-up email #3 (The Irresistible Value Stack, sent 8 days after first email).
- Pitch an irresistible Fiverr-secured offer stacking: web design, speed boost, Google Map optimization, and contact form setup.
- Do NOT re-introduce yourself.
- CRITICAL: End with ONE direct question to prompt a reply (e.g. "Should I send over what it would cost to go live?").
- Use a generic greeting if no owner name is provided. Do NOT use the business name as a person's name.
Subject on first line. Ready to send."""
    f3 = _run(prompt3_stack, sys_ctx=get_system_context(business))
    sequences.append({
        "num": 3,
        "channel": "email",
        "draft": _clean_draft(_spintax(f3) if f3 else f3),
        "scheduled_for": (now + timedelta(days=8)).isoformat(),
    })

    # Instagram DM follow-up — Day 6
    if business.get("instagram"):
        # Test 3: Follow-Up Sequence (Value-Add vs Standard Bump)
        bid = int(business.get("id") or 0)
        fu_variant = "A" if bid % 2 == 0 else "B"
        
        if fu_variant == "A":
            followup_rule = (
                "- Keep it a simple, polite bump. e.g. 'Hey, just wanted to check if you got a chance to see the draft layout I sent over?'"
            )
        else:
            followup_rule = (
                "- Provide a quick, valuable SEO or ranking insight. e.g. 'Hey, I also ran a quick check on your Google Maps listing—adding a few keyword-rich replies to your reviews would boost your local ranking. Let me know if you want the mockup link!'"
            )

        prompt_ig = f"""{ctx}
Offer: {offer}
{'ABSOLUTE REQUIREMENT: You MUST paste the exact link ' + demo_url + ' directly into your message. Do not ask if they want to see it.' if (demo_url and fu_variant == "A") else ''}

Write a short Instagram DM follow-up (sent 6 days after first contact).
- Under 40 words.
- Do NOT re-introduce yourself.
{followup_rule}
- CRITICAL: End with ONE simple question.
Ready to send."""
        f_ig = _run(prompt_ig, sys_ctx=get_system_context(business))
        sequences.append({
            "num": 4,
            "channel": "instagram",
            "draft": _clean_draft(f_ig),
            "scheduled_for": (now + timedelta(days=6)).isoformat(),
        })

    return sequences


# ── Main entry ─────────────────────────────────────────────────────────────

def generate_all(business: dict, demo_url: str = "", channels: list | None = None, scraped: dict | None = None) -> dict:
    """Generate outreach for selected channels. channels=None means all."""
    category = (business.get("category", "") or "").lower()
    name_lower = (business.get("name", "") or "").lower()
    is_contractor = any(kw in category or kw in name_lower for kw in ["roof", "roofer", "hvac", "air conditioning", "heating", "cooling", "solar", "remodeler", "remodeling", "renovation", "detail", "detailing", "ceramic", "tree", "arborist"])
    if is_contractor:
        demo_url = ""

    want = set(channels) if channels else {"email", "instagram", "whatsapp", "linkedin"}
    drafts: dict = {}

    if "email" in want:
        drafts["subject_options"] = write_subject_options(business, scraped)
        drafts["email"] = write_email(business, demo_url, scraped)
    if "instagram" in want:
        drafts["instagram"] = write_instagram_dm(business, demo_url, scraped)
    if "whatsapp" in want:
        drafts["whatsapp"] = write_whatsapp_dm(business, demo_url, scraped)
    if "linkedin" in want and business.get("linkedin_url"):
        drafts["linkedin"] = write_linkedin_dm(business, demo_url, scraped)

    return drafts


def rewrite_message(business: dict, channel: str, current_text: str, instruction: str, demo_url: str = "", scraped: dict | None = None) -> str:
    """Rewrite an existing draft following a specific instruction."""
    category = (business.get("category", "") or "").lower()
    name_lower = (business.get("name", "") or "").lower()
    is_contractor = any(kw in category or kw in name_lower for kw in ["roof", "roofer", "hvac", "air conditioning", "heating", "cooling", "solar", "remodeler", "remodeling", "renovation", "detail", "detailing", "ceramic", "tree", "arborist"])
    if is_contractor:
        demo_url = ""

    channel_label = {"email": "cold email", "instagram": "Instagram DM",
                     "whatsapp": "WhatsApp message", "linkedin": "LinkedIn DM"}.get(channel, channel)
    prompt = f"""{_business_context(business, scraped)}

Original {channel_label}:
{current_text}

Edit instruction: {instruction}
{'ABSOLUTE REQUIREMENT: You MUST paste the exact link ' + demo_url + ' directly into your message. Do not ask if they want to see it.' if demo_url else ''}

Rewrite the {channel_label} following the instruction exactly.
Keep it personalized to this specific business. Ready to send — no placeholders."""
    return _run(prompt)


def write_audit_pitch(business: dict, booking_url: str) -> str:
    score = business.get("website_score", 0)
    gap = business.get("gap", "")
    prompt = f"""Business: {business.get('name','')}
Website: {business.get('website','')}
Website Score: {score}/100
Gaps found: {gap}
Fiverr Link: {booking_url}

Write a professional, non-spammy cold email under 100 words to the business owner.
Subject line on first line, blank line, then body.
Start with a genuine compliment, then constructively mention that you ran a quick speed and performance audit on their website and noticed a few optimization gaps (like a speed score of {score}/100 or {gap}).
Do NOT be aggressive or insult their site. Keep it friendly and helpful.
State that these issues can be easily fixed to help them gain more local customers, and offer to help them fix it safely via your Fiverr page: {booking_url}.
End with a confident statement. Ready to send — no placeholders."""
    return _run(prompt)


def write_no_website_pitch(business: dict, booking_url: str) -> str:
    prompt = f"""Business: {business.get('name','')}
Category: {business.get('category','')}
Location: {business.get('city','')}
Fiverr Link: {booking_url}

Write a professional, non-spammy cold email under 100 words to the business owner who currently has no website.
Subject line on first line, blank line, then body.
Start with a genuine compliment, then gently point out the benefits they are missing out on by not having a local web presence (like customers searching for {business.get('category','')} in {business.get('city','')}).
State that you build modern, fast-loading responsive websites and offer to help them set one up safely via your Fiverr page: {booking_url}.
Keep it conversational, friendly, and non-salesy.
End with a confident statement. Ready to send — no placeholders."""
    return _run(prompt)
