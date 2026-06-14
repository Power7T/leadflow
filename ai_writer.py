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

SYSTEM_CONTEXT = """You are a highly persuasive, world-class outbound sales copywriter for Chandan Gosavi, an elite automation specialist and web developer from India.

Rules for high-converting but professional copy:
- Never sound like a generic salesperson. Create a "Pattern Interrupt" by starting with genuine, specific praise about their business (e.g., their great reviews).
- Highlight the opportunity cost (e.g., "you might be missing out on local searches because...") rather than insulting them. DO NOT be rude or aggressive.
- Build extreme CURIOSITY about the custom work you've already done for them.
- Keep emails under 100 words, DMs under 50 words. Punchy, short sentences.
- Use psychological triggers: FOMO, exclusivity, and undeniable value upfront, but keep a friendly, professional tone.
- Never use: "I hope this finds you well", "touch base", "circle back", "synergy".
- Include a very brief, confident, and honest introduction (e.g., "Hey, I'm Chandan—I build high-performing websites to help businesses like yours grow.") but keep the focus 90% on them and the value you're providing.
- STRICTLY end the message with a confident statement (e.g., "Check it out and let me know what you think." or "If you like it, let me know."). NEVER use a question mark (?) at the end of the message.
- GOLDEN TEMPLATE STRUCTURE: "Hey, I'm Chandan—I build high-performing websites to help [niche] like yours grow. [Business Name] has awesome [X]★ reviews, but without a website, you're missing out on local members searching online. I built this custom demo to show you what's possible: [link]. Check it out and let me know what you think."
- Plain conversational English. Write ready to send.
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
{'ABSOLUTE REQUIREMENT: You MUST paste the exact link ' + demo_url + ' directly into your email body. Do not ask if they want to see it.' if demo_url else ''}

Write a highly-converting cold email under 100 words.
Subject line on first line, blank line, then body.
Start with a genuine compliment based on their business details, then gently point out the missing revenue opportunity (like not having a website).
Build immense curiosity around the demo you built for them. 
You MUST explicitly mention their business name, but use a shortened conversational version if it is too long (e.g. use "247 Gym" instead of "247 Gym - The Fitness District").
End with a confident statement. Ready to send — no placeholders."""
    return _run(prompt)


def write_instagram_dm(business: dict, demo_url: str = "", scraped: dict | None = None) -> str:
    prompt = f"""{_business_context(business, scraped)}
Offer: {_pitch_context(business.get('pitch_type',''), demo_url)}
{'ABSOLUTE REQUIREMENT: You MUST paste the exact link ' + demo_url + ' directly into your message. Do not ask if they want to see it.' if demo_url else ''}

Write a punchy, curiosity-inducing Instagram DM under 50 words.
Hook them with a compliment, mention the opportunity they are missing (like local searches), and present the demo link as a high-value solution. Be friendly, NOT aggressive.
You MUST explicitly mention their business name, but use a shortened conversational version if it is too long (e.g. use "247 Gym" instead of "247 Gym - The Fitness District").
No hashtags. End with a confident statement. Ready to send."""
    return _run(prompt)


def write_linkedin_dm(business: dict, demo_url: str = "", scraped: dict | None = None) -> str:
    prompt = f"""{_business_context(business, scraped)}
LinkedIn: {business.get('linkedin_name','')}
Offer: {_pitch_context(business.get('pitch_type',''), demo_url)}
{'ABSOLUTE REQUIREMENT: You MUST paste the exact link ' + demo_url + ' directly into your message. Do not ask if they want to see it.' if demo_url else ''}

Write a professional LinkedIn DM under 70 words.
Reference a specific real detail about the business. 
You MUST explicitly mention their business name, but use a shortened conversational version if it is too long.
End with a confident statement. Ready to send."""
    return _run(prompt)


def write_whatsapp_dm(business: dict, demo_url: str = "", scraped: dict | None = None) -> str:
    prompt = f"""{_business_context(business, scraped)}
Offer: {_pitch_context(business.get('pitch_type',''), demo_url)}
{'ABSOLUTE REQUIREMENT: You MUST paste the exact link ' + demo_url + ' directly into your message. Do not ask if they want to see it.' if demo_url else ''}

Write a WhatsApp message under 50 words.
Be direct but conversational and friendly. Highlight a missed opportunity (like no website) constructively, and make them curious to click the link.
You MUST explicitly mention their business name, but use a shortened conversational version if it is too long (e.g. use "247 Gym" instead of "247 Gym - The Fitness District").
No formal greetings. End with a confident statement (e.g., "Check it out."). Ready to send."""
    return _run(prompt)


def write_live_followup(business: dict, scraped: dict | None = None) -> str:
    prompt = f"""{_business_context(business, scraped)}

Write a highly-converting, hyper-casual message under 50 words to send to this business owner RIGHT NOW while they are actively looking at the demo site I sent them.
Rule: Start by saying you noticed they are checking out the prototype.
Rule: Do NOT sound creepy. Sound helpful and excited.
Rule: Create urgency. Offer to answer any questions or hop on a 2-minute call to take it live.
Rule: You MUST explicitly mention their business name, but use a shortened conversational version if it is too long.
End with a confident statement. Ready to send."""
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
