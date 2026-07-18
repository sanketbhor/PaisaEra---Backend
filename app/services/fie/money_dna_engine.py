"""
Money DNA Engine — fourth stage of the FIE pipeline.

Classifies a user's spending pattern into one of the archetypes named in
the Moat Strategy doc. This is a real rule-based classifier over category
spend percentages — deliberately not an LLM call, per the same
hallucination-prevention principle applied throughout the FIE: a
behavioral classification should be a deterministic, explainable function
of real data, not a model's guess. The LLM's role (elsewhere, in the AI
Gateway) is only to phrase the result, never to decide it.
"""
from dataclasses import dataclass

ARCHETYPES = [
    "Planner", "Saver", "Investor", "Minimalist",
    "Explorer", "Impulse Buyer", "Strategic Builder",
]


@dataclass
class MoneyDNAResult:
    primary_archetype: str
    breakdown: list[dict]  # [{"label": str, "pct": int}]


def classify_money_dna(category_spend_pct: dict[str, float], savings_rate: float) -> MoneyDNAResult:
    """
    `category_spend_pct` — e.g. {"Investment": 0.35, "Khana": 0.25, "Shopping": 0.20, ...}
    (fractions of total spend, should sum to ~1.0). `savings_rate` — 0.0-1.0.

    Rule set is intentionally simple and hand-written, not ML — appropriate
    for launch-stage data volume. Revisit with a real model once there's
    enough labeled behavioral history to justify one (the Moat Strategy doc
    itself frames Money DNA as evolving monthly, which fits a
    scheduled-recompute batch job either way — see money_dna_engine usage
    in the daily/monthly Celery task, not per-request).
    """
    investment_pct = category_spend_pct.get("Investment", 0.0)
    food_pct = category_spend_pct.get("Khana", 0.0)
    shopping_pct = category_spend_pct.get("Shopping", 0.0)

    scores = {
        "Investor": investment_pct * 100 + savings_rate * 40,
        "Saver": savings_rate * 100,
        "Foodie": food_pct * 100,
        "Impulse Buyer": shopping_pct * 100 - savings_rate * 30,
        "Minimalist": (1 - food_pct - shopping_pct) * 60 + savings_rate * 30,
    }
    # Clip negatives, then normalize to percentages that sum to 100 for the
    # top 3 — matches the "65% / 25% / 10%" breakdown shape from the product spec.
    scores = {k: max(0.0, v) for k, v in scores.items()}
    total = sum(scores.values()) or 1.0
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:3]
    breakdown = [{"label": label, "pct": round(val / total * 100)} for label, val in ranked]

    # Normalize rounding so the displayed percentages actually sum to 100
    diff = 100 - sum(b["pct"] for b in breakdown)
    if breakdown:
        breakdown[0]["pct"] += diff

    primary = "Strategic Builder" if investment_pct > 0.2 and savings_rate > 0.15 else breakdown[0]["label"]
    return MoneyDNAResult(primary_archetype=primary, breakdown=breakdown)
