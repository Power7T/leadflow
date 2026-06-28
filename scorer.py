"""
Lead scorer — ranks each lead 0-100 by how likely they are to need our services
and how easy they are to reach. Higher score = better lead.
"""
import re


def score_lead(business: dict, contacts: dict) -> int:
    score = 0
    site_score = business.get("website_score", 0)
    reviews = business.get("google_reviews") or 0
    rating = business.get("google_rating") or 0
    website = business.get("website", "")
    pitch_type = business.get("pitch_type", "")
    category = (business.get("category") or "").lower()
    name = (business.get("name") or "").lower()

    # Determine if this business qualifies for the LeadFlow SaaS Campaign
    saas_niches = {"roof", "hvac", "solar", "plumb", "dent", "ortho", "gym", "fitness", "contractor", "electrician", "painter", "landscap"}
    is_saas_campaign = pitch_type == "leadflow_saas" or any(kw in category or kw in name for kw in saas_niches)

    if is_saas_campaign:
        # SaaS CRM & Leads scoring profile:
        # We target established service providers who need leads.
        # Too few reviews = brand new, no budget.
        if reviews < 10:
            return 0
        
        # Too many reviews = giant enterprise, likely already has full CRM setup.
        if reviews > 500:
            return 0

        # Highly active marketing profile (sweet spot)
        if 30 <= reviews <= 400:
            score += 50
        else:
            score += 20
        
        # Good ratings are nice, means they do good work and can close our leads
        if rating >= 4.0:
            score += 10
            
        # Having contact details is critical for outreach
        if contacts.get("email"):
            score += 25
        if contacts.get("instagram"):
            score += 10
        if contacts.get("whatsapp"):
            score += 5
            
        # Give a small boost if they have a decent website since we are driving ads/leads
        if website and site_score >= 70:
            score += 10
        elif not website:
            # We can still sell SaaS with a custom landing page, but slightly lower priority
            score += 5

        # ── Intent signal bonuses ─────────────────────────────────────
        if business.get('has_google_ads', 0):
            score += 15
        if business.get('social_active', 0):
            score += 8
        score += business.get('intent_score', 0)
        if reviews >= 50 and rating >= 4.3:
            score += 7
        if contacts.get('email') and (contacts.get('instagram') or contacts.get('linkedin_url')):
            score += 5

    else:
        # Legacy Web Design & Redesign scoring profile:
        # ── Website gap (biggest signal) ──────────────────────────────
        if not website:
            score += 60        # No website = biggest opportunity
        elif site_score >= 70:
            return 0           # Good site — completely ignore, they don't need a website
        elif site_score < 35:
            score += 40        # Terrible site
        elif site_score < 60:
            score += 25        # Bad site
        else:
            score += 5         # Mediocre site (60-69)

        # ── Reachability ─────────────────────────────────────────────
        if contacts.get("email"):
            score += 20
        if contacts.get("instagram"):
            score += 12
        if contacts.get("linkedin_url"):
            score += 10
        if contacts.get("whatsapp"):
            score += 8

        # ── Business health (has customers, worth pitching) ───────────
        if reviews >= 20:
            score += 5
        if reviews >= 100:
            score += 5
        if rating >= 4.0:
            score += 5
        if rating >= 4.5:
            score += 3

        # ── Sweet spot: established but not giant ─────────────────────
        if 20 <= reviews <= 500:
            score += 8
        elif reviews > 500:
            score -= 5         # Getting big, may already have agency

        # ── Intent signal bonuses ─────────────────────────────────────
        if business.get('has_google_ads', 0):
            score += 15
        if business.get('social_active', 0):
            score += 8
        score += business.get('intent_score', 0)
        if reviews >= 50 and rating >= 4.3:
            score += 7
        if contacts.get('email') and (contacts.get('instagram') or contacts.get('linkedin_url')):
            score += 5

    return min(score, 100)


def detect_intent_signals(business: dict, html_content: str = '') -> dict:
    """
    Analyse raw HTML from a business website to detect intent signals.
    Returns a dict with keys: has_google_ads, social_active, intent_score.
    """
    html_lower = html_content.lower()
    result = {'has_google_ads': 0, 'social_active': 0, 'intent_score': 0}

    # ── Google Ads / Tag Manager / DoubleClick detection ────────────────
    google_ads_markers = [
        'googleads', 'adwords', 'google_conversion', 'gtag', 'gads', 'ad-client',
        'googleadservices.com', 'googletagservices.com', 'doubleclick.net',
        'google_ad_client', 'adsbygoogle', 'googletagmanager.com/gtm.js',
        'gtm.js?id='
    ]
    if any(marker in html_lower for marker in google_ads_markers):
        result['has_google_ads'] = 1

    # ── Meta / Facebook Ads detection ──────────────────────────────────
    meta_ads_markers = [
        'connect.facebook.net/en_us/fbevents.js', 'fbq(', 'fb-pixel',
        'facebook pixel', 'facebook-jssdk', 'fbevents.js'
    ]
    has_meta_ads = any(marker in html_lower for marker in meta_ads_markers)

    # ── Other Ads pixels (TikTok, Bing, Pinterest) ─────────────────────
    other_ads_markers = [
        'analytics.tiktok.com/i18n/pixel/sdk.js', 'bat.bing.com/bat.js',
        'ct.pinterest.com/v3/'
    ]
    has_other_ads = any(marker in html_lower for marker in other_ads_markers)

    # ── Promote has_google_ads if any ad system pixel is detected ──────
    if has_meta_ads or has_other_ads:
        # Mark as active ads tracker — they have ad budgets and tracking
        result['has_google_ads'] = 1

    # ── Marketing tools detection ─────────────────────────────────────
    marketing_markers = ['facebook pixel', 'fb-pixel', 'hotjar', 'hubspot', 'mailchimp', 'klaviyo', 'intercom']
    marketing_count = sum(1 for marker in marketing_markers if marker in html_lower)

    # ── Social media links ────────────────────────────────────────────
    social_domains = ['facebook.com', 'instagram.com', 'twitter.com', 'linkedin.com', 'tiktok.com']
    social_count = sum(1 for domain in social_domains if domain in html_lower)
    if social_count >= 1:
        result['social_active'] = 1

    # ── Intent score (0-20) ───────────────────────────────────────────
    intent = 0
    if result['has_google_ads']:
        intent += 8
    if marketing_count >= 1:
        intent += 4
    if marketing_count >= 3:
        intent += 4
    if social_count >= 2:
        intent += 2
    if social_count >= 4:
        intent += 2
    result['intent_score'] = min(intent, 20)

    return result
