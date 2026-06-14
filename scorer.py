"""
Lead scorer — ranks each lead 0-100 by how likely they are to need our services
and how easy they are to reach. Higher score = better lead.
"""


def score_lead(business: dict, contacts: dict) -> int:
    score = 0
    site_score = business.get("website_score", 0)
    reviews = business.get("google_reviews") or 0
    rating = business.get("google_rating") or 0
    website = business.get("website", "")

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
    # Small-medium businesses are the best clients
    if 20 <= reviews <= 500:
        score += 8
    elif reviews > 500:
        score -= 5         # Getting big, may already have agency

    return min(score, 100)
