"""
Website quality scorer — combines direct HTTP checks + Google PageSpeed API.
Returns a score 0-100 plus a detailed audit dict for display in the dashboard.
"""
import os
import re
import time
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

PAGESPEED_KEY = os.getenv("GOOGLE_PAGESPEED_API_KEY", "")
PAGESPEED_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


# ── Direct HTTP check ─────────────────────────────────────────────────────────

def _direct_check(url: str) -> tuple[int, dict]:
    """
    Fetch the site directly and score it.
    Returns (score, details_dict).
    """
    details = {
        "https": False,
        "loads": False,
        "status_code": None,
        "response_time_s": None,
        "mobile_viewport": False,
        "title": None,
        "meta_description": None,
        "has_content": False,
        "bot_blocked": False,
    }
    score = 0

    if url.startswith("https://"):
        score += 15
        details["https"] = True

    try:
        t0 = time.time()
        resp = requests.get(url, headers=HEADERS, timeout=10, allow_redirects=True)
        elapsed = round(time.time() - t0, 2)
        details["response_time_s"] = elapsed
        details["status_code"] = resp.status_code

        if resp.status_code == 200:
            score += 20
            details["loads"] = True
        elif resp.status_code in (202, 403, 429, 503):
            details["bot_blocked"] = True
            return 75, details
        elif resp.status_code in (301, 302):
            score += 10
            details["loads"] = True
        else:
            return max(score, 5), details

        # Speed
        if elapsed < 1.0:
            score += 20
        elif elapsed < 2.0:
            score += 14
        elif elapsed < 4.0:
            score += 7

        soup = BeautifulSoup(resp.text, "lxml")

        # Mobile viewport
        vp = soup.find("meta", attrs={"name": re.compile("viewport", re.I)})
        if vp and "width=device-width" in vp.get("content", ""):
            score += 20
            details["mobile_viewport"] = True

        # Title
        title = soup.find("title")
        if title and title.text.strip():
            score += 10
            details["title"] = title.text.strip()[:80]

        # Meta description
        md = soup.find("meta", attrs={"name": re.compile("description", re.I)})
        if md and md.get("content", "").strip():
            score += 8
            details["meta_description"] = md.get("content", "").strip()[:120]

        # Has real content
        if len(soup.get_text(separator=" ", strip=True)) > 300:
            score += 7
            details["has_content"] = True

    except requests.exceptions.SSLError:
        details["https"] = False
        score = max(0, score - 15)
        try:
            resp2 = requests.get(url.replace("https://", "http://"), headers=HEADERS, timeout=8)
            if resp2.status_code == 200:
                score += 10
                details["loads"] = True
        except Exception:
            pass
    except requests.exceptions.ConnectionError:
        return 0, details
    except requests.exceptions.Timeout:
        details["response_time_s"] = ">10s"
        return max(score, 8), details
    except Exception:
        return max(score, 5), details

    return min(score, 100), details


# ── PageSpeed API check ───────────────────────────────────────────────────────

def _pagespeed_check(url: str) -> dict | None:
    """
    Call Google PageSpeed Insights API.
    Returns structured audit data or None on failure.
    """
    if not PAGESPEED_KEY:
        return None

    try:
        params = {"url": url, "strategy": "mobile", "key": PAGESPEED_KEY}
        resp = requests.get(PAGESPEED_URL, params=params, timeout=30)
        data = resp.json()

        if "error" in data or "lighthouseResult" not in data:
            return None

        lhr = data["lighthouseResult"]
        cats = lhr.get("categories", {})
        audits = lhr.get("audits", {})

        def cat_score(key):
            s = cats.get(key, {}).get("score")
            return int(s * 100) if s is not None else None

        def audit_val(key, field="displayValue"):
            return audits.get(key, {}).get(field, "—")

        return {
            "performance":   cat_score("performance"),
            "accessibility": cat_score("accessibility"),
            "best_practices": cat_score("best-practices"),
            "seo":           cat_score("seo"),
            "fcp":           audit_val("first-contentful-paint"),
            "lcp":           audit_val("largest-contentful-paint"),
            "tbt":           audit_val("total-blocking-time"),
            "cls":           audit_val("cumulative-layout-shift"),
            "speed_index":   audit_val("speed-index"),
            "opportunities": _top_opportunities(audits),
        }
    except Exception:
        return None


def _top_opportunities(audits: dict) -> list[str]:
    """Extract top 3 improvement opportunities from Lighthouse audits."""
    opp_keys = [
        "render-blocking-resources",
        "unused-javascript",
        "unused-css-rules",
        "uses-optimized-images",
        "uses-responsive-images",
        "efficiently-cache-static-assets",
        "uses-text-compression",
    ]
    found = []
    for key in opp_keys:
        audit = audits.get(key, {})
        if audit.get("score") is not None and audit["score"] < 0.9:
            title = audit.get("title", key)
            saving = audit.get("displayValue", "")
            found.append(f"{title}{' — ' + saving if saving else ''}")
        if len(found) >= 3:
            break
    return found


# ── Public interface ──────────────────────────────────────────────────────────

def score_website(url: str) -> int:
    """Quick score 0-100. Used by finder for fast batch processing."""
    if not url:
        return 0
    if not url.startswith("http"):
        url = "https://" + url
    score, _ = _direct_check(url)
    return score


def full_audit(url: str) -> dict:
    """
    Full audit combining direct check + PageSpeed API.
    Returns everything needed for the detail panel.
    """
    if not url:
        return {"score": 0, "direct": {}, "pagespeed": None}

    if not url.startswith("http"):
        url = "https://" + url

    score, direct = _direct_check(url)
    ps = _pagespeed_check(url)

    # If PageSpeed returned a performance score, blend it with our score
    if ps and ps.get("performance") is not None:
        blended = int(score * 0.4 + ps["performance"] * 0.6)
        score = blended

    return {
        "score": min(score, 100),
        "direct": direct,
        "pagespeed": ps,
    }


def detect_gap(website: str, score: int) -> tuple[str, str]:
    if not website:
        return ("No website — losing customers who search online", "website_new")
    if score < 35:
        return (f"Website scores {score}/100 — broken on mobile, very slow, or outdated", "website_redesign")
    if score < 60:
        return (f"Website scores {score}/100 — needs mobile-friendliness and speed improvements", "website_redesign")
    if score < 80:
        return (f"Website scores {score}/100 — decent but missing SEO and performance polish", "automation")
    return (f"Website scores {score}/100 — solid site, opportunity for AI automation or booking system", "automation")


PITCH_LABELS = {
    "website_new":      "Build new website",
    "website_redesign": "Website redesign",
    "automation":       "AI automation / email system",
    "ai_setup":         "ClawdBot AI assistant setup",
    "leadflow_saas":    "LeadFlow CRM & Leads",
}
