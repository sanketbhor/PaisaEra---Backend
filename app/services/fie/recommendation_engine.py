"""
Recommendation Engine — fifth stage of the FIE pipeline, feeding directly
into the AI Response stage (AI Gateway narrates these, never invents them).

Every recommendation is a structured object with reason/confidence/
supporting_factors, matching the Explainable AI requirement (Moat 6) and
the `ai_messages.explanation` JSON field in the Backend Schemas Document.
"""
from dataclasses import dataclass, field

from app.services.fie.budget_engine import CategoryBudget, overspend_alerts


@dataclass
class Recommendation:
    type: str
    summary: str  # short, factual — the AI Gateway phrases this in-voice, doesn't alter the facts
    confidence: str  # "high" | "medium" | "low"
    supporting_factors: list[str] = field(default_factory=list)


def generate_recommendations(
    categories: list[CategoryBudget],
    income: float | None,
) -> list[Recommendation]:
    """
    Rule-based recommendation generation. Each rule below corresponds
    directly to one of the "instead of X, AI says Y" examples from the
    product spec — the point being that the *insight* (the comparison, the
    percentage) is computed here deterministically, and only the *phrasing*
    is left to the AI Gateway.
    """
    recs: list[Recommendation] = []

    for alert in overspend_alerts(categories, threshold=0.85):
        pct_of_income = (alert["spent"] / income * 100) if income else None
        supporting = [f"{alert['category']} spend at {alert['pct_used']}% of budget"]
        if pct_of_income:
            supporting.append(f"{round(pct_of_income)}% of monthly income")
        recs.append(
            Recommendation(
                type="overspend_category",
                summary=f"{alert['category']} spending is at {alert['pct_used']}% of budget"
                + (f", {round(pct_of_income)}% of income" if pct_of_income else ""),
                confidence="high",
                supporting_factors=supporting,
            )
        )

    # Placeholder for the "Store A vs Store B" and "EMI prepay" style
    # recommendations from the product spec — those need merchant-level
    # price comparison data and loan/EMI tracking respectively, neither of
    # which exists in the current schema. Flagged rather than faked with
    # a made-up merchant comparison.

    return recs
