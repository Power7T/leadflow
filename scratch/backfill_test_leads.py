"""
Backfill existing test_leads with:
  - dollar-framed competitor_deficit
  - missed revenue (intent_score)
  - gap string with $ amount
"""
import sqlite3
from pathlib import Path

DB = Path(__file__).parents[2] / "leadflow.db"

# ── Niche ticket prices ──────────────────────────────────────────────────────
NICHE_TICKET = {
    "dentist": 320, "dental": 320, "orthodontist": 2800,
    "hvac": 275, "air conditioning": 275, "heating": 275,
    "roofing": 9500, "roofer": 9500,
    "plumbing": 220, "plumber": 220,
    "landscaping": 180, "lawn": 180, "landscaper": 180,
    "solar": 28000, "solar panel": 28000,
    "chiropractor": 120, "chiropractic": 120,
    "gym": 65, "fitness": 65, "personal trainer": 65,
    "lawyer": 1800, "attorney": 1800, "law": 1800,
    "remodeling": 14000, "remodel": 14000, "contractor": 5000,
    "electrician": 190, "electrical": 190,
    "financial": 600, "accountant": 400, "cpa": 400,
    "insurance": 900, "real estate": 6000, "realtor": 6000,
    "restaurant": 45, "cafe": 35,
}

# ── Click-share model ────────────────────────────────────────────────────────
MONTHLY_SEARCHES = 1000
CLICK_SHARE      = {1: 0.29, 2: 0.17, 3: 0.11}
OUTSIDE_SHARE    = 0.03
CALL_CVR         = 0.28
CLOSE_CVR        = 0.40
PACK_AVG         = sum(CLICK_SHARE.values()) / 3

def avg_ticket_for(niche: str) -> int:
    n = niche.lower()
    for key, price in NICHE_TICKET.items():
        if key in n:
            return price
    return 200

def missed_rev(rank: int, ticket: int) -> tuple[int, int]:
    cur  = MONTHLY_SEARCHES * CLICK_SHARE.get(rank, OUTSIDE_SHARE) * CALL_CVR * CLOSE_CVR
    pack = MONTHLY_SEARCHES * PACK_AVG * CALL_CVR * CLOSE_CVR
    leads = max(0, pack - cur)
    # For rank 1-3: show what they'd LOSE by dropping to rank 4 (at-risk amount)
    if rank <= 3:
        drop_leads = MONTHLY_SEARCHES * CLICK_SHARE.get(rank, 0.11) * CALL_CVR * CLOSE_CVR
        outside_leads = MONTHLY_SEARCHES * OUTSIDE_SHARE * CALL_CVR * CLOSE_CVR
        at_risk_leads = max(0, drop_leads - outside_leads)
        return int(at_risk_leads), int(at_risk_leads * ticket)
    return int(leads), int(leads * ticket)

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

leads = conn.execute(
    "SELECT * FROM businesses WHERE source='test_leads' ORDER BY city, maps_rank"
).fetchall()

# Group by city+category to find top competitor reviews per group
from collections import defaultdict
groups = defaultdict(list)
for r in leads:
    key = (r["city"].lower().strip(), r["category"].lower().strip())
    groups[key].append(dict(r))

updated = 0
for (city, cat), group in groups.items():
    # Sort by rank to find rank-1 competitor
    group.sort(key=lambda x: x.get("maps_rank") or 99)
    top       = group[0]
    top_name  = top["name"]
    top_rev   = int(top.get("google_reviews") or 0)
    ticket    = avg_ticket_for(cat)

    for lead in group:
        bid    = lead["id"]
        rank   = int(lead.get("maps_rank") or 1)
        reviews= int(lead.get("google_reviews") or 0)
        name   = lead["name"]

        missed_leads, missed_revenue = missed_rev(rank, ticket)

        # Competitor for review comparison
        if rank == 1 and len(group) > 1:
            comp       = group[1]
            comp_name  = comp["name"]
            comp_revs  = int(comp.get("google_reviews") or 0)
        else:
            comp_name  = top_name
            comp_revs  = top_rev
        review_gap = max(0, comp_revs - reviews)

        # ── Build deficit ────────────────────────────────────────────────────
        parts = []
        if rank > 3:
            parts.append(
                f"At rank #{rank} you're missing ~{missed_leads} new "
                f"{cat} inquiries/month worth ~${missed_revenue:,} in lost revenue "
                f"(${ticket:,} avg ticket) — all going to your 3-Pack competitors."
            )
        else:
            parts.append(
                f"Ranked #{rank} — one ranking slip drops you out of the 3-Pack entirely. "
                f"The gap between rank #3 and #4 is ~${missed_revenue:,}/month in booked "
                f"{cat} jobs at your avg ticket (${ticket:,})."
            )
        if review_gap > 10:
            parts.append(
                f"Review gap: {comp_name} has {comp_revs} reviews vs your {reviews} "
                f"({review_gap} more) — Google treats review count as a direct 3-Pack ranking signal."
            )
        deficit = " | ".join(parts)

        # ── Build gap string ─────────────────────────────────────────────────
        if rank > 3:
            gap_str = (
                f"Ranked #{rank} on Google Maps "
                f"(❌ Outside 3-Pack — est. ${missed_revenue:,}/mo in lost {cat} revenue)."
            )
        else:
            gap_str = (
                f"Ranked #{rank} on Google Maps "
                f"(⚠️ At risk of dropping from 3-Pack — ${missed_revenue:,}/mo at stake)."
            )

        conn.execute(
            """UPDATE businesses
               SET competitor_deficit=?, gap=?, intent_score=?
               WHERE id=?""",
            (deficit, gap_str, missed_revenue, bid)
        )
        print(f"  ✅ ID:{bid} [{rank}] {name[:40]}")
        print(f"     missed_rev: ${missed_revenue:,}  review_gap: {review_gap}")
        print(f"     deficit: {deficit[:120]}...")
        print()
        updated += 1

conn.commit()
conn.close()
print(f"\n✅ Backfilled {updated} test leads.")
