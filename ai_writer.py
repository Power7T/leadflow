"""
AI message writer — uses local Gemini CLI (agy).
Features: personalized emails/DMs, 3 subject A/B options,
3-email follow-up sequence, review-based personalization,
competitor comparison, demo site link injection.
"""
import subprocess
import shutil
from datetime import datetime, timedelta

AGY_PATH      = shutil.which("agy") or "/Users/chandan/.local/bin/agy"
DEFAULT_MODEL = "Gemini 3.5 Flash (High)"

SYSTEM_CONTEXT = """You are an expert cold outreach copywriter for Chandan Gosavi, a freelance web developer and automation specialist from India.

Rules:
- Never sound like AI or a template
- Reference specific real details about the business
- Lead with genuine praise or a positive observation about their business (e.g., their great reviews or services)
- NEVER pretend to be a customer looking to use their services. Be direct that you are a web developer who noticed them.
- Keep emails under 120 words, DMs under 60 words
- Never use: "I hope this finds you well", "touch base", "circle back", "synergy", "leverage"
- End with ONE easy yes/no question
- No bullet points or headers in message body
- Plain conversational English
- Write ready to send — no [Name] or [Business] placeholders
"""


def _run(prompt: str) -> str:
    full = SYSTEM_CONTEXT + "\n\n" + prompt
    result = subprocess.run(
        [AGY_PATH, "--model", DEFAULT_MODEL, "-p", full],
        capture_output=True, text=True, timeout=90,
    )
    if result.returncode != 0:
        raise RuntimeError(f"agy error: {result.stderr.strip()}")
    return result.stdout.strip()


def _business_context(b: dict, scraped: dict | None = None) -> str:
    rating  = b.get("google_rating")
    reviews = b.get("google_reviews")
    rating_line = f"{rating}★ across {reviews:,} reviews" if rating and reviews else ""
    ctx = f"""Business: {b.get('name','')}
Location: {b.get('city','')}
Category: {b.get('category','')}
Google: {rating_line}
Website: {b.get('website') or 'NONE'}
Website score: {b.get('website_score',0)}/100
Gap: {b.get('gap','')}"""

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
    prompt = f"""{_business_context(business, scraped)}
Offer: {_pitch_context(business.get('pitch_type',''), demo_url)}
{'Demo site built: ' + demo_url if demo_url else ''}

Write a cold email under 120 words.
Subject line on first line, blank line, then body.
Reference one specific real detail from their website or business.
{"Mention the free demo site link naturally in the email." if demo_url else ""}
Ready to send — no placeholders."""
    return _run(prompt)


def write_instagram_dm(business: dict, scraped: dict | None = None) -> str:
    prompt = f"""{_business_context(business, scraped)}
Offer: {_pitch_context(business.get('pitch_type',''))}

Write a casual Instagram DM under 60 words.
Sound like a real person who looked at their profile and website.
Reference one specific real detail about this business.
No hashtags. End with one easy question. Ready to send."""
    return _run(prompt)


def write_linkedin_dm(business: dict, scraped: dict | None = None) -> str:
    prompt = f"""{_business_context(business, scraped)}
LinkedIn: {business.get('linkedin_name','')}
Offer: {_pitch_context(business.get('pitch_type',''))}

Write a professional LinkedIn DM under 70 words.
Reference a specific real detail about the business. End with one question. Ready to send."""
    return _run(prompt)


def write_whatsapp_dm(business: dict, demo_url: str = "", scraped: dict | None = None) -> str:
    prompt = f"""{_business_context(business, scraped)}
Offer: {_pitch_context(business.get('pitch_type',''), demo_url)}
{'Demo site built: ' + demo_url if demo_url else ''}

Write a WhatsApp message under 60 words.
Casual and friendly like texting a local business owner you just discovered.
Reference one specific real detail about their business (from website content if available).
{"Include the demo link naturally." if demo_url else ""}
No formal greetings. End with one easy yes/no question. Ready to send."""
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
    prompt1 = f"""{ctx}
Offer: {offer}

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
    prompt2 = f"""{ctx}
Offer: {offer}

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
        drafts["instagram"] = write_instagram_dm(business, scraped)
    if "whatsapp" in want:
        drafts["whatsapp"] = write_whatsapp_dm(business, demo_url, scraped)
    if "linkedin" in want and business.get("linkedin_url"):
        drafts["linkedin"] = write_linkedin_dm(business, scraped)

    return drafts


def rewrite_message(business: dict, channel: str, current_text: str, instruction: str, scraped: dict | None = None) -> str:
    """Rewrite an existing draft following a specific instruction."""
    channel_label = {"email": "cold email", "instagram": "Instagram DM",
                     "whatsapp": "WhatsApp message", "linkedin": "LinkedIn DM"}.get(channel, channel)
    prompt = f"""{_business_context(business, scraped)}

Original {channel_label}:
{current_text}

Edit instruction: {instruction}

Rewrite the {channel_label} following the instruction exactly.
Keep it personalized to this specific business. Ready to send — no placeholders."""
    return _run(prompt)
