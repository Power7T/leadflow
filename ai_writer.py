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

load_dotenv()

AGY_PATH      = shutil.which("agy") or "/Users/chandan/.local/bin/agy"
DEFAULT_MODEL = "Gemini 3.5 Flash (High)"
BOOKING_URL   = os.getenv("BOOKING_URL", "")
CALENDLY_URL  = os.getenv("CALENDLY_URL", "")
FIVERR_URL    = "https://www.fiverr.com/sellers/chandangosavi/"

_GYM_KEYWORDS = {
    "gym", "fit", "fitness", "crossfit", "yoga", "pilates", "studio",
    "boxing", "martial art", "mma", "workout", "athletic", "ymca",
}

def _is_gym(category: str, name: str = "") -> bool:
    cat = (category or "").lower()
    nm  = (name or "").lower()
    return any(kw in cat or kw in nm for kw in _GYM_KEYWORDS)

SYSTEM_CONTEXT = """You are a highly persuasive, world-class outbound sales copywriter for Chandan Gosavi, an elite automation specialist and web developer from India.

Rules for high-converting but professional copy:
- Never sound like a generic salesperson. Create a "Pattern Interrupt" by starting with genuine, specific praise about their business (e.g., their great reviews).
- If the owner's name is known (e.g. Mike), personalize the greeting (e.g. "Hey Mike," or "Hey Mike, I'm Chandan...") instead of a generic "Hey," or using the business name.
- Highlight the opportunity cost (e.g., "you might be missing out on local searches because...") rather than insulting them. DO NOT be rude or aggressive.
- Build extreme CURIOSITY about the custom work you've already done for them.
- Keep emails under 100 words, DMs under 50 words. Punchy, short sentences.
- Use psychological triggers: FOMO, exclusivity, and undeniable value upfront, but keep a friendly, professional tone.
- Never use: "I hope this finds you well", "touch base", "circle back", "synergy".
- Include a very brief, confident, and honest introduction (e.g., "Hey, I'm Chandan—I build high-performing websites to help businesses like yours grow.") but keep the focus 90% on them and the value you're providing.
- STRICTLY end the message with a confident statement (e.g., "Check it out and let me know what you think." or "If you like it, let me know."). NEVER use a question mark (?) at the end of the message.
- GOLDEN TEMPLATE STRUCTURE: "Hey [Mike/there], I'm Chandan—I build high-performing websites to help [niche] like yours grow. [Business Name] has awesome [X]★ reviews, but without a website, you're missing out on local members searching online. I built this custom demo to show you what's possible: [link]. Check it out and let me know what you think."
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


# ── Fallback Tier 2: Gemini REST API (google-generativeai) ─────────────────

def _run_gemini_rest(prompt: str, model: str = "gemini-2.5-flash") -> str | None:
    """Call Gemini directly via REST with support for a rotated key pool and model fallback."""
    keys_str = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_AI_API_KEY") or ""
    keys = [k.strip() for k in keys_str.split(",") if k.strip()]
    if not keys:
        return None
    
    import urllib.request, json
    full_prompt = SYSTEM_CONTEXT + "\n\n" + prompt
    payload = json.dumps({
        "contents": [{"parts": [{"text": full_prompt}]}],
        "generationConfig": {"maxOutputTokens": 512, "temperature": 0.9},
    }).encode()

    for idx, api_key in enumerate(keys):
        try:
            url = ("https://generativelanguage.googleapis.com/v1beta/models/"
                   f"{model}:generateContent?key={api_key}")
            req = urllib.request.Request(url, data=payload,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            out = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            if out:
                return out
        except Exception as e:
            print(f"[ai_writer] REST API key #{idx+1} failed for {model}: {str(e)[:80]}")
            # Try to fall back to stable gemini-1.5-flash for this key if it wasn't already tried
            if model != "gemini-1.5-flash":
                try:
                    url = ("https://generativelanguage.googleapis.com/v1beta/models/"
                           f"gemini-1.5-flash:generateContent?key={api_key}")
                    req = urllib.request.Request(url, data=payload,
                                                 headers={"Content-Type": "application/json"})
                    with urllib.request.urlopen(req, timeout=60) as resp:
                        data = json.loads(resp.read().decode('utf-8'))
                    out = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                    if out:
                        return out
                except Exception:
                    pass
            continue
    return None


# ── Fallback Tier 3: OpenAI ────────────────────────────────────────────────

def _run_openai(prompt: str) -> str | None:
    """Call OpenAI gpt-4o-mini — needs OPENAI_API_KEY in .env."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    try:
        import openai
        client = openai.OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_CONTEXT},
                {"role": "user",   "content": prompt},
            ],
            max_tokens=512,
            temperature=0.9,
        )
        return resp.choices[0].message.content.strip()
    except Exception:
        return None


# ── Fallback Tier 4: Anthropic Claude ─────────────────────────────────────

def _run_anthropic(prompt: str) -> str | None:
    """Call Claude Haiku — needs ANTHROPIC_API_KEY in .env."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=512,
            system=SYSTEM_CONTEXT,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text.strip()
    except Exception:
        return None


# ── Fallback Tier 5: Smart template (always works, zero cost) ─────────────

def _run_template(prompt: str) -> str:
    """Extract key details from the prompt and fill a proven template.
    This is the last-resort fallback — it never fails.
    """
    # Extract business name
    name_m = re.search(r"Business:\s*(.+)", prompt)
    name   = name_m.group(1).strip() if name_m else "your business"
    # Shorten very long names (take first 3 words)
    short_name = " ".join(name.split()[:3]) if len(name.split()) > 3 else name

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
    calendly_url = calendly_m.group(1).strip() if calendly_m else CALENDLY_URL
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

    # Determine channels
    is_instagram = "instagram" in prompt.lower()
    is_whatsapp  = "whatsapp" in prompt.lower()
    is_linkedin  = "linkedin" in prompt.lower()
    is_email     = not (is_instagram or is_whatsapp or is_linkedin)

    # 1. Subject Line Options
    if "3 different" in prompt.lower() and "subject line" in prompt.lower():
        return (
            f"1. Quick question for {short_name}\n"
            f"2. Idea for {short_name}\n"
            f"3. {short_name} - custom website concept"
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
            f"Quick audit for {short_name}\n\n"
            f"{owner_part}\n\n"
            f"I ran a quick performance audit on {short_name}'s website. The speed score is currently {score_str}, and there are some optimization gaps: {gap_str}.\n\n"
            f"This is likely costing you local clients who bounce when the site loads slowly.\n\n"
            f"We can fix this setup safely on Fiverr to improve your load times and capture those lost leads: {booking_url}\n\n"
            f"Let me know if you'd like to get this updated."
        )

    # 5. No Website Pitch
    if "no website" in prompt.lower() or "currently has no website" in prompt.lower():
        owner_part = f"Hey {owner_name}," if owner_name else "Hey there,"
        loc_part = f" in {location}" if location else " in your area"
        cat_part = category if category else "business"
        return (
            f"Quick question for {short_name}\n\n"
            f"{owner_part}\n\n"
            f"I noticed {short_name} has great local reviews{loc_part}, but you don't have a website listed.\n\n"
            f"Without one, you're missing out on a lot of local customers searching online for a {cat_part}{loc_part}.\n\n"
            f"I build high-performing, fast websites to help local businesses scale. We can build one for you safely via my Fiverr page: {booking_url}\n\n"
            f"Let me know if you want to get this set up."
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
                f"Idea for {short_name}\n\n"
                f"{owner_part}\n\n"
                f"I know you're busy running {short_name}, so I'll keep this brief.\n\n"
                f"I built a custom demo website to show you how we can bring in more local customers: {demo}\n\n"
                f"We can customize this to fit your brand and take it live safely via Fiverr: {booking_url}\n\n"
                f"Let me know if you want to make any adjustments to the demo."
            )
        else:
            return (
                f"Idea for {short_name}\n\n"
                f"{owner_part}\n\n"
                f"I know you're busy running {short_name}, so I'll keep this brief.\n\n"
                f"I build high-performing websites to help businesses like yours bring in more local customers.\n\n"
                f"We can set this up safely via my Fiverr page: {booking_url}\n\n"
                f"Let me know if you'd like to see a custom concept."
            )

    # 8. Follow-up sequence Email #2 (Day 9)
    if "follow-up email #2" in prompt.lower() or "email #2" in prompt.lower():
        owner_part = f"Hey {owner_name}," if owner_name else "Hey there,"
        demo_str = f" ({demo})" if demo else ""
        calendly_str = f"booking a quick call here ({calendly_url}) or " if calendly_url else ""
        return (
            f"Final try - {short_name}\n\n"
            f"{owner_part}\n\n"
            f"I haven't heard back, so I'll assume this isn't a priority for {short_name} right now.\n\n"
            f"If you ever want to revive your online presence or check out the demo I built{demo_str}, feel free to reach out.\n\n"
            f"You can also {calendly_str}order safely on Fiverr: {booking_url}\n\n"
            f"Let me know if you change your mind."
        )

    # 9. Follow-up sequence Instagram DM (Day 6)
    if is_instagram and "follow-up" in prompt.lower():
        greet = f"Hey {owner_name or short_name},"
        if demo:
            return f"{greet} just wanted to see if you had a second to look at the custom website demo I built: {demo}. We can customize this and get it live safely via Fiverr ({booking_url}). Let me know what you think."
        else:
            return f"{greet} just wanted to see if you had a second to check out my website design services. We can build a custom demo for you and get it live safely via Fiverr ({booking_url}). Let me know what you think."

    # 10. Initial Outreach Messages (Email, DMs)
    if is_email:
        owner_part = f"Hey {owner_name}," if owner_name else "Hey there,"
        rating_str = f" — and that {rating}★ rating is impressive" if rating else ""
        if is_gym_biz and demo:
            return (
                f"Quick thought on {short_name}\n\n"
                f"{owner_part}\n\n"
                f"I'm Chandan — I build high-performing websites to help fitness studios like yours grow.\n\n"
                f"{short_name} has awesome {rating}★ reviews, but without a website, you're missing out on local members searching online.\n\n"
                f"I built this custom demo to show you what's possible: {demo}\n\n"
                f"We can customize this for your gym and take it live safely on Fiverr: {booking_url}\n\n"
                f"Check it out and let me know what you think."
            )
        else:
            return (
                f"Quick thought on {short_name}\n\n"
                f"{owner_part}\n\n"
                f"I'm Chandan — I build high-performing websites to help businesses like yours grow.\n\n"
                f"{short_name} has awesome reviews{rating_str}, but your online presence could be pulling in way more local clients.\n\n"
                f"If you'd like to see a custom design concept for your business, message me on Fiverr where we can build a demo and take it live safely: {booking_url}\n\n"
                f"Let me know if you want to take a look."
            )

    elif is_instagram:
        greet = f"Hey {owner_name or short_name}!"
        rating_str = f" with your {rating}★ reviews" if rating else ""
        if is_gym_biz and demo:
            return f"{greet} I'm Chandan — I build websites for gyms. Noticed {short_name} is doing great{rating_str} but your site could be pulling in way more members. I built this custom demo for you: {demo}. Let me know what you think."
        else:
            return f"{greet} I'm Chandan — I build websites for local businesses. Noticed {short_name} is doing great{rating_str} but your online presence could be stronger. Drop me a line on Fiverr if you'd like a custom demo: {booking_url}. Let me know what you think."

    elif is_linkedin:
        owner_part = f"Hey {owner_name}," if owner_name else "Hey there,"
        rating_str = f" with your {rating}★ reviews" if rating else ""
        if is_gym_biz and demo:
            return (
                f"{owner_part}\n\n"
                f"I'm Chandan — I build high-performing websites for fitness studios.\n\n"
                f"{short_name} has great reviews, but without a website, you are missing out on local members searching online. I built this custom demo to show you what's possible: {demo}\n\n"
                f"We can customize this and set it up safely on Fiverr. Let me know what you think."
            )
        else:
            return (
                f"{owner_part}\n\n"
                f"I'm Chandan — I build high-performing websites for local businesses.\n\n"
                f"{short_name} has great reviews{rating_str}, but your online presence could be pulling in way more local clients.\n\n"
                f"If you'd like to see a custom design concept, message me on Fiverr where we can build a demo and take it live safely: {booking_url}\n\n"
                f"Let me know if you think."
            )

    elif is_whatsapp:
        greet = f"Hey {owner_name or short_name}!"
        rating_str = f" with your {rating}★ reviews" if rating else ""
        if is_gym_biz and demo:
            return f"{greet} I'm Chandan — I build websites for gyms. Noticed {short_name} is doing great{rating_str} but you could be getting way more members online. I built this custom demo for you: {demo}. Let me know what you think."
        else:
            return f"{greet} I'm Chandan — I build websites for businesses. Noticed {short_name} is doing great{rating_str} but your online presence could be stronger. Drop me a line on Fiverr if you'd like to see a custom demo: {booking_url}. Let me know what you think."

    # General Fallback
    demo_part = f" Demo: {demo}" if demo else ""
    return (
        f"Quick thought on {short_name}\n\n"
        f"Hey, I'm Chandan — I build high-performing websites for businesses like yours. "
        f"{short_name} has {rating + '★ reviews' if rating else 'great reviews'} but your online presence "
        f"could be pulling in way more local customers.{demo_part} Check it out and let me know what you think."
    )


# ── Main runner with full fallback chain ───────────────────────────────────

def _get_routing_for_prompt(prompt: str) -> dict:
    """Return the primary tier, REST model, and agy model for a given prompt."""
    p = prompt.lower()
    
    # 1. Audit / Gap Analysis / Competitor analysis (Logic heavy)
    # Uses powerful agy models first (like Sonnet or 3.1 Pro), then falls back to REST 2.5 Pro
    if "audit" in p or "website score" in p or "gaps found" in p or "competitor" in p:
        return {
            "primary": "agy",
            "rest_model": os.getenv("REST_AUDIT_MODEL", "gemini-2.5-pro"),
            "agy_model": os.getenv("AGY_AUDIT_MODEL", "Claude Sonnet 4.6 (Thinking)")
        }
        
    # 2. Writing tasks (Emails, DMs, subject lines, followups, chat)
    # Uses REST gemini-2.5-pro first, then falls back to agy Gemini 3.5 Flash (Low)
    return {
        "primary": "rest",
        "rest_model": os.getenv("REST_DEFAULT_MODEL", "gemini-2.5-pro"),
        "agy_model": os.getenv("AGY_DEFAULT_MODEL", "Gemini 3.5 Flash (Low)")
    }


# ── Main runner with full fallback chain ───────────────────────────────────

def _run(prompt: str, attempts: int = 2) -> str:
    """Call AI with a 5-tier fallback chain so generation NEVER gets stuck.

    Tier 1/2: Smart routing based on task (REST gemini-2.5-pro vs local agy Gemini 3.5 Flash Low)
    Tier 3: OpenAI gpt-4o-mini (OPENAI_API_KEY in .env)
    Tier 4: Anthropic Claude Haiku (ANTHROPIC_API_KEY in .env)
    Tier 5: Smart template (always works, zero cost, zero dependencies)
    """
    import time
    full = SYSTEM_CONTEXT + "\n\n" + prompt
    
    route = _get_routing_for_prompt(prompt)
    primary = route["primary"]
    rest_model = route["rest_model"]
    agy_model = route["agy_model"]

    # Build execution chain of primary vs fallback models
    execution_chain = []
    
    if primary == "rest":
        execution_chain.append(("rest", rest_model))
        execution_chain.append(("agy", agy_model))
    else:
        execution_chain.append(("agy", agy_model))
        execution_chain.append(("rest", rest_model))

    # Add general fallback models (prioritizing Gemini 3.5 Flash (Low) for agy fallback)
    for m in ["Gemini 3.5 Flash (Low)", DEFAULT_MODEL, "Gemini 3.5 Flash (Medium)", "Gemini 3.5 Flash (High)"]:
        if ("agy", m) not in execution_chain:
            execution_chain.append(("agy", m))
            
    if ("rest", "gemini-1.5-flash") not in execution_chain:
        execution_chain.append(("rest", "gemini-1.5-flash"))

    # Execute the chain
    for tier, model in execution_chain:
        if tier == "rest":
            print(f"[ai_writer] Trying REST API with model: {model}")
            out = _run_gemini_rest(prompt, model)
            if out:
                return out
        elif tier == "agy":
            for i in range(attempts):
                try:
                    print(f"[ai_writer] Trying agy with model: {model}")
                    result = subprocess.run(
                        [AGY_PATH, "--model", model, "-p", full],
                        capture_output=True, text=True, timeout=120,
                    )
                    out = (result.stdout or "").strip()
                    stderr = (result.stderr or "").strip()

                    if result.returncode == 0 and out:
                        return out

                    last_err = stderr or "empty response"

                    if _is_quota_error(last_err) or _is_quota_error(out) or "not found" in last_err.lower():
                        print(f"[ai_writer] agy model {model} failed/rate-limited — trying fallback. ({last_err[:80]})")
                        break

                except subprocess.TimeoutExpired:
                    pass
                except Exception:
                    pass

                if i < attempts - 1:
                    time.sleep(1.5 * (i + 1))

    # ── Tier 3: OpenAI ──
    print("[ai_writer] Trying Tier 3: OpenAI gpt-4o-mini")
    out = _run_openai(prompt)
    if out:
        return out

    # ── Tier 4: Anthropic ──
    print("[ai_writer] Trying Tier 4: Anthropic Claude Haiku")
    out = _run_anthropic(prompt)
    if out:
        return out

    # ── Tier 5: Smart template (never fails) ──
    print("[ai_writer] All AI tiers exhausted — using smart template fallback")
    return _run_template(prompt)



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
    prompt = f"""{ctx}

Write 3 different cold email subject lines for this business.
Each should be short (under 8 words), specific, and intriguing.
Reference a real detail from their business where possible.
Make them very different from each other — one question, one statement, one curiosity.
Output exactly 3 lines, numbered 1. 2. 3. — nothing else."""
    raw = _run(prompt)
    lines = [l.lstrip("123. ").strip() for l in raw.strip().split("\n") if l.strip()]
    return lines[:3] if len(lines) >= 3 else lines + ["Quick question about your website"] * (3 - len(lines))


# ── Primary outreach ───────────────────────────────────────────────────────

def write_email(business: dict, demo_url: str = "", scraped: dict | None = None) -> str:
    is_gym_biz = _is_gym(business.get("category", ""), business.get("name", ""))
    booking_part = f"\nFiverr Gig Link: {BOOKING_URL}\nRule: You can optionally mention they can view my profile or order safely on Fiverr using this link." if BOOKING_URL else ""

    if is_gym_biz and demo_url:
        demo_part = f"{'ABSOLUTE REQUIREMENT: You MUST paste the exact link ' + demo_url + ' directly into your email body. Do not ask if they want to see it.'}"
        offer = _pitch_context(business.get('pitch_type', ''), demo_url)
    else:
        # Non-gym: no demo. Ask them to message on Fiverr for a custom demo.
        demo_part = f"IMPORTANT: Do NOT mention a demo link — there is no demo for this business yet. Instead, naturally invite them to message you on Fiverr ({FIVERR_URL}) where you can show them a custom demo and take it live safely."
        offer = _pitch_context(business.get('pitch_type', ''), "")

    prompt = f"""{_business_context(business, scraped)}
Offer: {offer}{booking_part}
{demo_part}

Write a highly-converting cold email under 100 words.
Subject line on first line, blank line, then body.
Start with a genuine compliment based on their business details, then gently point out the missing revenue opportunity (like not having a website).
You MUST explicitly mention their business name, but use a shortened conversational version if it is too long (e.g. use "247 Gym" instead of "247 Gym - The Fitness District").
End with a confident statement. Ready to send — no placeholders."""
    return _run(prompt)


def write_instagram_dm(business: dict, demo_url: str = "", scraped: dict | None = None) -> str:
    is_gym_biz = _is_gym(business.get("category", ""), business.get("name", ""))
    if is_gym_biz and demo_url:
        demo_part = f"ABSOLUTE REQUIREMENT: You MUST paste the exact link {demo_url} directly into your message. Do not ask if they want to see it."
        offer = _pitch_context(business.get('pitch_type', ''), demo_url)
    else:
        demo_part = f"IMPORTANT: Do NOT mention a demo link. Instead invite them to message you on Fiverr ({FIVERR_URL}) to see a custom demo."
        offer = _pitch_context(business.get('pitch_type', ''), "")

    prompt = f"""{_business_context(business, scraped)}
Offer: {offer}
{demo_part}

Write a punchy, curiosity-inducing Instagram DM under 50 words.
Hook them with a compliment, mention the opportunity they are missing (like local searches). Be friendly, NOT aggressive.
You MUST explicitly mention their business name, but use a shortened conversational version if it is too long.
No hashtags. End with a confident statement. Ready to send."""
    return _run(prompt)


def write_linkedin_dm(business: dict, demo_url: str = "", scraped: dict | None = None) -> str:
    is_gym_biz = _is_gym(business.get("category", ""), business.get("name", ""))
    if is_gym_biz and demo_url:
        demo_part = f"ABSOLUTE REQUIREMENT: You MUST paste the exact link {demo_url} directly into your message. Do not ask if they want to see it."
        offer = _pitch_context(business.get('pitch_type', ''), demo_url)
    else:
        demo_part = f"IMPORTANT: Do NOT mention a demo link. Instead invite them to message you on Fiverr ({FIVERR_URL}) to see a custom demo for their business."
        offer = _pitch_context(business.get('pitch_type', ''), "")

    prompt = f"""{_business_context(business, scraped)}
LinkedIn: {business.get('linkedin_name','')}
Offer: {offer}
{demo_part}

Write a professional LinkedIn DM under 70 words.
Reference a specific real detail about the business.
You MUST explicitly mention their business name, but use a shortened conversational version if it is too long.
End with a confident statement. Ready to send."""
    return _run(prompt)


def write_whatsapp_dm(business: dict, demo_url: str = "", scraped: dict | None = None) -> str:
    is_gym_biz = _is_gym(business.get("category", ""), business.get("name", ""))
    if is_gym_biz and demo_url:
        demo_part = f"ABSOLUTE REQUIREMENT: You MUST paste the exact link {demo_url} directly into your message. Do not ask if they want to see it."
        offer = _pitch_context(business.get('pitch_type', ''), demo_url)
    else:
        demo_part = f"IMPORTANT: Do NOT mention a demo link. Instead invite them to message you on Fiverr ({FIVERR_URL}) to see a custom demo."
        offer = _pitch_context(business.get('pitch_type', ''), "")

    prompt = f"""{_business_context(business, scraped)}
Offer: {offer}
{demo_part}

Write a WhatsApp message under 50 words.
Be direct but conversational and friendly. Highlight a missed opportunity constructively, make them curious.
You MUST explicitly mention their business name, but use a shortened conversational version if it is too long.
No formal greetings. End with a confident statement. Ready to send."""
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

def write_follow_up_sequence(business: dict, demo_url: str = "") -> list[dict]:
    """
    Generate a 3-email follow-up sequence.
    Returns list of dicts with: num, channel, draft, scheduled_for
    """
    ctx = _business_context(business)
    offer = _pitch_context(business.get("pitch_type", ""), demo_url)
    now = datetime.now()

    sequences = []

    # Follow-up 1 — Day 4: add value, not just "checking in"
    booking_part = f"\nFiverr Gig Link: {BOOKING_URL}\nRule: You can optionally mention they can view my profile or order safely on Fiverr using this link." if BOOKING_URL else ""
    prompt1 = f"""{ctx}
Offer: {offer}{booking_part}
{'ABSOLUTE REQUIREMENT: You MUST paste the exact link ' + demo_url + ' directly into your email body. Do not ask if they want to see it.' if demo_url else ''}

Write follow-up email #1 (sent 4 days after first email, no reply received).
Don't say "just checking in" — instead add a specific insight or observation about their business.
Under 80 words. Subject on first line. Ready to send."""
    f1 = _run(prompt1)
    sequences.append({
        "num": 1,
        "channel": "email",
        "draft": f1,
        "scheduled_for": (now + timedelta(days=4)).isoformat(),
    })

    # Follow-up 2 — Day 9: social proof + soft close
    calendly_part = f"\nBooking Link: {CALENDLY_URL}\nRule: Naturally suggest they can book a free 15-minute call using this booking link if they'd like to discuss how to grow their business." if CALENDLY_URL else ""
    prompt2 = f"""{ctx}
Offer: {offer}{booking_part}{calendly_part}
{'ABSOLUTE REQUIREMENT: You MUST paste the exact link ' + demo_url + ' directly into your email body. Do not ask if they want to see it.' if demo_url else ''}

Write follow-up email #2 (sent 9 days after first email, still no reply).
Mention that you've helped similar businesses. Keep it short — under 60 words.
This is the last email. Make it easy to say yes or to say they're not interested.
Subject on first line. Ready to send."""
    f2 = _run(prompt2)
    sequences.append({
        "num": 2,
        "channel": "email",
        "draft": f2,
        "scheduled_for": (now + timedelta(days=9)).isoformat(),
    })

    # Instagram DM follow-up — Day 6
    if business.get("instagram"):
        prompt3 = f"""{ctx}
Offer: {offer}
{'ABSOLUTE REQUIREMENT: You MUST paste the exact link ' + demo_url + ' directly into your message. Do not ask if they want to see it.' if demo_url else ''}

Write a short Instagram DM follow-up (sent 6 days after first contact).
Very casual. Under 40 words. Don't mention the email. Fresh angle. Ready to send."""
        f3 = _run(prompt3)
        sequences.append({
            "num": 3,
            "channel": "instagram",
            "draft": f3,
            "scheduled_for": (now + timedelta(days=6)).isoformat(),
        })

    return sequences


# ── Main entry ─────────────────────────────────────────────────────────────

def generate_all(business: dict, demo_url: str = "", channels: list | None = None, scraped: dict | None = None) -> dict:
    """Generate outreach for selected channels. channels=None means all."""
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
