"""
Financial Intelligence Engine — the orchestrator.

    Transaction → Categorizer → Budget Engine → Money Score Engine →
    Money DNA Engine → Recommendation Engine → AI Response

This is the single class the rest of the backend should call for anything
"intelligence"-shaped. Routers and Celery tasks call `FinancialIntelligenceEngine`,
never the individual engine modules directly — that indirection is what
lets the pipeline evolve (add a stage, reorder, swap an implementation)
without every call site needing to change.

DB access is intentionally kept OUT of this class — it takes plain data in
and returns plain dataclasses out. The router/service layer is responsible
for fetching from Postgres and handing this class clean inputs, which is
what makes every stage independently unit-testable without a database.
"""
from dataclasses import dataclass

from app.services.fie.categorizer import categorize, is_recurring_candidate
from app.services.fie.budget_engine import CategoryBudget, safe_to_spend_today
from app.services.fie.money_score_engine import compute_money_score, MoneyScoreResult
from app.services.fie.money_dna_engine import classify_money_dna, MoneyDNAResult
from app.services.fie.recommendation_engine import generate_recommendations, Recommendation


@dataclass
class FIESnapshot:
    """Everything the AI Gateway / API layer needs to respond intelligently
    about a user's current financial state, computed in one pass."""

    money_score: MoneyScoreResult
    money_dna: MoneyDNAResult
    recommendations: list[Recommendation]
    safe_to_spend_today: float


class FinancialIntelligenceEngine:
    @staticmethod
    def categorize_transaction(merchant_name: str) -> dict:
        return {
            "category": categorize(merchant_name),
            "is_recurring_candidate": is_recurring_candidate(merchant_name),
        }

    @staticmethod
    def compute_snapshot(
        categories: list[CategoryBudget],
        total_income_30d: float,
        total_expense_30d: float,
        goal_progress_ratios: list[float],
        category_spend_pct: dict[str, float],
        monthly_income: float | None,
    ) -> FIESnapshot:
        """
        One call, full picture. This is what a Celery nightly job (or, for
        now, an on-demand router call — see app/routers/money_score.py)
        should invoke rather than calling three separate engines and
        hoping call sites stay in sync with each other.
        """
        money_score = compute_money_score(
            categories=categories,
            total_income_30d=total_income_30d,
            total_expense_30d=total_expense_30d,
            goal_progress_ratios=goal_progress_ratios,
        )
        savings_rate = (
            max(0.0, (total_income_30d - total_expense_30d) / total_income_30d)
            if total_income_30d
            else 0.0
        )
        money_dna = classify_money_dna(category_spend_pct, savings_rate)
        recommendations = generate_recommendations(categories, monthly_income)
        safe_spend = safe_to_spend_today(categories)

        return FIESnapshot(
            money_score=money_score,
            money_dna=money_dna,
            recommendations=recommendations,
            safe_to_spend_today=safe_spend,
        )


# Module-level singleton — the engine itself is stateless (pure functions
# under the hood), so one shared instance is safe and avoids re-instantiating
# per request.
fie = FinancialIntelligenceEngine()
