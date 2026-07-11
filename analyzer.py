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

        # Strip scripts and styles
        for element in soup(["script", "style"]):
            element.extract()
        
        # Has real content
        if len(soup.get_text(separator=" ", strip=True)) > 300:
            score += 7
            details["has_content"] = True
            
        # Penalize DIY Builders (Wix, Squarespace, Google Sites, Weebly, GoDaddy)
        html_lower = resp.text.lower()
        if "sites.google.com" in html_lower or "gstatic.com/atari" in html_lower:
            score -= 40
            details["builder"] = "Google Sites"
        elif "wix.com" in html_lower or "wixsite.com" in html_lower or "x-wix" in html_lower:
            score -= 30
            details["builder"] = "Wix"
        elif "squarespace" in html_lower:
            score -= 30
            details["builder"] = "Squarespace"
        elif "weebly" in html_lower:
            score -= 30
            details["builder"] = "Weebly"
        elif "godaddy" in html_lower or "secureserver.net" in html_lower:
            score -= 30
            details["builder"] = "GoDaddy"

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
    key = os.getenv("GOOGLE_PAGESPEED_API_KEY", "")
    if not key:
        return None

    try:
        params = {"url": url, "strategy": "mobile", "key": key}
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


def score_website_with_details(url: str) -> tuple[int, str]:
    """Returns (score, builder_name). builder_name is '' if no DIY builder detected."""
    if not url:
        return 0, ""
    if not url.startswith("http"):
        url = "https://" + url
    score, details = _direct_check(url)
    return score, details.get("builder", "")


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
        return (f"Website scores {score}/100 — broken, very slow, or generic DIY template", "website_redesign")
    if score < 60:
        return (f"Website scores {score}/100 — outdated design, generic builder, or needs mobile/speed polish", "website_redesign")
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


def generate_audit_html(business: dict, audit: dict) -> str:
    # Get values safely
    score = audit.get("score", 0)
    direct = audit.get("direct", {})
    ps = audit.get("pagespeed") or {}
    
    # PageSpeed metrics
    perf = ps.get("performance", "—")
    access = ps.get("accessibility", "—")
    bp = ps.get("best_practices", "—")
    seo = ps.get("seo", "—")
    
    # Direct diagnostics
    https_status = "✓ Secures with HTTPS" if direct.get("https") else "✗ Missing HTTPS / Insecure"
    https_color = "#10b981" if direct.get("https") else "#ef4444"
    
    load_time = direct.get("response_time_s", "—")
    speed_status = "✓ Loads fast" if (isinstance(load_time, float) and load_time < 2.0) else "✗ Loads slow"
    speed_color = "#10b981" if speed_status.startswith("✓") else "#ef4444"
    
    vp_status = "✓ Optimized for mobile" if direct.get("mobile_viewport") else "✗ Desktop-only layout"
    vp_color = "#10b981" if direct.get("mobile_viewport") else "#ef4444"
    
    title_text = direct.get("title") or "—"
    meta_text = direct.get("meta_description") or "—"
    
    opportunities = ps.get("opportunities") or []
    opp_html = "".join(f"<li style='margin-bottom:8px;color:#cbd5e0;list-style:none'><span style='color:#fbbf24;margin-right:8px'>⚠</span>{opp}</li>" for opp in opportunities)
    if not opp_html:
        opp_html = "<li style='color:#a0aec0;font-style:italic;list-style:none'>No severe opportunities found.</li>"
        
    booking_url = os.getenv("BOOKING_URL", "https://calendly.com")
    agency_name = os.getenv("AGENCY_NAME", "LeadFlow Agency")
    
    # Score color
    score_color = "#ef4444" if score < 45 else ("#f59e0b" if score < 80 else "#10b981")
    
    # Calculate SVG dashoffset (circumference of 120 diameter circle is ~377)
    circumference = 376.99
    stroke_offset = circumference - (score / 100.0) * circumference
    
    # Format templates
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{business.get('name')} - Website Performance Audit</title>
  <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;600;700&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg: #090a0f;
      --card-bg: #12131a;
      --border: rgba(255,255,255,0.08);
      --text: #ffffff;
      --text-dim: #a0aec0;
      --accent: #2563eb;
    }}
    body {{
      background: var(--bg);
      color: var(--text);
      font-family: 'Inter', sans-serif;
      margin: 0;
      padding: 0;
      line-height: 1.6;
    }}
    .container {{
      max-width: 1100px;
      margin: 0 auto;
      padding: 40px 20px;
    }}
    .header {{
      text-align: center;
      margin-bottom: 40px;
    }}
    .header h1 {{
      font-family: 'Outfit', sans-serif;
      font-size: 36px;
      margin: 0 0 10px 0;
      font-weight: 700;
    }}
    .header p {{
      color: var(--text-dim);
      font-size: 16px;
      margin: 0;
    }}
    .grid {{
      display: grid;
      grid-template-columns: 1fr 1.5fr;
      gap: 30px;
      margin-bottom: 40px;
    }}
    @media (max-width: 800px) {{
      .grid {{ grid-template-columns: 1fr; }}
    }}
    .card {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 20px;
      padding: 30px;
      box-shadow: 0 10px 30px rgba(0,0,0,0.5);
    }}
    .score-circle-container {{
      display: flex;
      flex-direction: column;
      align-items: center;
      text-align: center;
      margin-bottom: 30px;
    }}
    .score-ring {{
      position: relative;
      width: 150px;
      height: 150px;
      margin-bottom: 16px;
    }}
    .score-ring svg {{
      transform: rotate(-90deg);
      width: 100%;
      height: 100%;
    }}
    .score-ring circle {{
      fill: none;
      stroke-width: 10;
    }}
    .score-ring .bg {{
      stroke: rgba(255,255,255,0.05);
    }}
    .score-ring .val {{
      stroke: {score_color};
      stroke-linecap: round;
      stroke-dasharray: 377;
      stroke-dashoffset: {stroke_offset};
      transition: stroke-dashoffset 1s ease-in-out;
    }}
    .score-ring .num {{
      position: absolute;
      inset: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 38px;
      font-weight: 700;
      font-family: 'Outfit', sans-serif;
      color: {score_color};
    }}
    .sub-scores {{
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 12px;
      margin-top: 20px;
    }}
    .sub-score-box {{
      background: rgba(255,255,255,0.02);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 12px;
      text-align: center;
    }}
    .sub-score-label {{
      font-size: 11px;
      color: var(--text-dim);
      text-transform: uppercase;
      letter-spacing: 0.5px;
      margin-bottom: 6px;
    }}
    .sub-score-val {{
      font-size: 20px;
      font-weight: 700;
      color: #fff;
    }}
    .diag-list {{
      display: flex;
      flex-direction: column;
      gap: 16px;
    }}
    .diag-item {{
      background: rgba(255,255,255,0.02);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 16px;
    }}
    .diag-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-weight: 600;
      font-size: 14px;
      margin-bottom: 6px;
    }}
    .diag-body {{
      font-size: 13px;
      color: var(--text-dim);
    }}
    .opp-list {{
      list-style: none;
      padding: 0;
      margin: 0;
    }}
    .cta-banner {{
      background: linear-gradient(135deg, #1d4ed8, #1e3a8a);
      border: 1px solid rgba(255,255,255,0.15);
      border-radius: 20px;
      padding: 40px;
      text-align: center;
      box-shadow: 0 15px 40px rgba(37,99,235,0.25);
    }}
    .cta-banner h2 {{
      font-family: 'Outfit', sans-serif;
      font-size: 28px;
      margin: 0 0 10px 0;
    }}
    .cta-banner p {{
      max-width: 600px;
      margin: 0 auto 24px;
      color: rgba(255,255,255,0.8);
      font-size: 15px;
    }}
    .btn {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      background: #ffffff;
      color: #090a0f;
      text-decoration: none;
      font-weight: 700;
      padding: 12px 28px;
      border-radius: 999px;
      box-shadow: 0 4px 15px rgba(0,0,0,0.3);
      transition: transform 0.2s;
    }}
    .btn:hover {{
      transform: translateY(-2px);
    }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <p>WEBSITE DIAGNOSTIC REPORT</p>
      <h1>{business.get('name')}</h1>
      <p style="margin-top:6px">Analyzed url: <a href="{business.get('website')}" target="_blank" style="color:#3b82f6;text-decoration:none">{business.get('website')}</a></p>
    </div>
    
    <div class="grid">
      <!-- Left Column: Scores -->
      <div class="card" style="display:flex;flex-direction:column;justify-content:center">
        <div class="score-circle-container">
          <div class="score-ring">
            <svg>
              <circle class="bg" cx="75" cy="75" r="60"></circle>
              <circle class="val" cx="75" cy="75" r="60"></circle>
            </svg>
            <div class="num">{score}</div>
          </div>
          <div style="font-weight:700;font-size:18px;font-family:'Outfit'">Overall Performance Score</div>
          <p style="color:var(--text-dim);font-size:13px;margin:6px 0 0">Blending response latency, mobile viewport tags, and Lighthouse diagnostics.</p>
        </div>
        
        <div class="sub-scores">
          <div class="sub-score-box">
            <div class="sub-score-label">Perf</div>
            <div class="sub-score-val" style="color:{score_color}">{perf}</div>
          </div>
          <div class="sub-score-box">
            <div class="sub-score-label">Access</div>
            <div class="sub-score-val">{access}</div>
          </div>
          <div class="sub-score-box">
            <div class="sub-score-label">Practices</div>
            <div class="sub-score-val">{bp}</div>
          </div>
          <div class="sub-score-box">
            <div class="sub-score-label">SEO</div>
            <div class="sub-score-val">{seo}</div>
          </div>
        </div>
      </div>
      
      <!-- Right Column: Diagnostics -->
      <div class="card">
        <div style="font-family:'Outfit';font-size:20px;font-weight:700;margin-bottom:20px;border-bottom:1px solid var(--border);padding-bottom:10px">Technical Diagnostics</div>
        
        <div class="diag-list">
          <div class="diag-item">
            <div class="diag-header">
              <span>Security (SSL/HTTPS)</span>
              <span style="color:{https_color}">{https_status}</span>
            </div>
            <div class="diag-body">Ensures all traffic is encrypted and builds customer browser trust.</div>
          </div>
          
          <div class="diag-item">
            <div class="diag-header">
              <span>Response Latency</span>
              <span style="color:{speed_color}">{speed_status} ({load_time}s)</span>
            </div>
            <div class="diag-body">Fast response times keep visitors on page and directly boosts SEO indexing.</div>
          </div>
          
          <div class="diag-item">
            <div class="diag-header">
              <span>Mobile Responsiveness</span>
              <span style="color:{vp_color}">{vp_status}</span>
            </div>
            <div class="diag-body">Correct mobile viewport settings ensures layout is clean on phones & tablets.</div>
          </div>
          
          <div class="diag-item">
            <div class="diag-header">
              <span>Metadata Diagnostics</span>
              <span>Checked</span>
            </div>
            <div class="diag-body">
              <strong>Title:</strong> {title_text}<br>
              <strong style="display:inline-block;margin-top:4px">Meta Desc:</strong> {meta_text}
            </div>
          </div>
        </div>
      </div>
    </div>
    
    <div class="card" style="margin-bottom:40px">
      <div style="font-family:'Outfit';font-size:20px;font-weight:700;margin-bottom:20px;border-bottom:1px solid var(--border);padding-bottom:10px">Google Lighthouse Optimization Gaps</div>
      <p style="font-size:13px;color:var(--text-dim);margin:0 0 16px">Top recommendations identified by Google Lighthouse crawler to increase speed and user engagement:</p>
      <ul class="opp-list">
        {opp_html}
      </ul>
    </div>
    
    <div class="cta-banner">
      <h2>Let's Get These Issues Solved</h2>
      <p>I custom-built this performance diagnostic report for {business.get('name')}. Schedule a free 15-minute screen-share call, and I will show you how we can fix these gaps to drive more customers.</p>
      <a href="{booking_url}" target="_blank" class="btn">Schedule Free Strategy Call &rarr;</a>
    </div>
  </div>
</body>
</html>"""
    return html
