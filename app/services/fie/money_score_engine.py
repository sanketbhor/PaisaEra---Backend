"""
Money Score Engine — third stage of the FIE pipeline.

This supersedes the standalone app/services/money_score_service.py from the
previous pass: the calculation logic now lives here as pure functions
operating on data the caller supplies, and money_score_service.py becomes a
thin DB-access wrapper that calls into this engine (kept for backward
compatibility with the existing /money-score router — see the bottom of
this file).
"""
from dataclasses import dataclass, field

from app.services.fie.budget_engine import CategoryBudget, budget_discipline_ratio

COMPONENT_WEIGHTS = {
    "budget_discipline": 150,
    "savings_behaviour": 150,
    "expense_behaviour": 100,
    "goal_achievement": 100,
    "money_habits": 100,
    "income_stability": 100,
    "financial_awareness": 100,
    "financial_safety": 100,
}
BASE_SCORE = 500
MAX_SCORE = 850


@dataclass
class ScoreComponentResult:
    component: str
    points: int
    reason: str


@dataclass
class MoneyScoreResult:
    total_score: int
    level: str
    components: list[ScoreComponentResult] = field(default_factory=list)


def _level_for_score(score: int) -> str:
    if score >= 800:
        return "Money Master"
    if score >= 700:
        return "Money Builder"
    if score >= 600:
        return "Money Learner"
    return "Money Starter"


def score_budget_discipline(categories: list[CategoryBudget]) -> ScoreComponentResult:
    if not categories:
        return ScoreComponentResult("budget_discipline", 0, "Koi active budget nahi mila")
    ratio = budget_discipline_ratio(categories)
    pts = int(COMPONENT_WEIGHTS["budget_discipline"] * ratio)
    return ScoreComponentResult("budget_discipline", pts, f"Budget discipline {int(ratio*100)}%")


def score_savings_behaviour(total_income_30d: float, total_expense_30d: float) -> ScoreComponentResult:
    if total_income_30d <= 0:
        return ScoreComponentResult("savings_behaviour", 0, "Is mahine koi income record nahi hui")
    savings_rate = max(0.0, (total_income_30d - total_expense_30d) / total_income_30d)
    pts = int(COMPONENT_WEIGHTS["savings_behaviour"] * min(1.0, savings_rate * 2))
    return ScoreComponentResult("savings_behaviour", pts, f"Is mahine ~{int(savings_rate*100)}% income bachai")


def score_goal_achievement(goal_progress_ratios: list[float]) -> ScoreComponentResult:
    if not goal_progress_ratios:
        return ScoreComponentResult("goal_achievement", 0, "Koi active goal nahi hai")
    avg = sum(goal_progress_ratios) / len(goal_progress_ratios)
    pts = int(COMPONENT_WEIGHTS["goal_achievement"] * min(1.0, avg))
    return ScoreComponentResult("goal_achievement", pts, f"Goals average {int(avg*100)}% complete hai")


def compute_money_score(
    categories: list[CategoryBudget],
    total_income_30d: float,
    total_expense_30d: float,
    goal_progress_ratios: list[float],
) -> MoneyScoreResult:
    """
    The three implemented components (budget_discipline, savings_behaviour,
    goal_achievement) plus five not-yet-implemented ones
    (expense_behaviour, money_habits, income_stability,
    financial_awareness, financial_safety), which contribute 0 until real
    signal sources exist for them — same honest-gap approach as the
    previous pass, just now organized as engine functions instead of
    inline in a service.
    """
    components = [
        score_budget_discipline(categories),
        score_savings_behaviour(total_income_30d, total_expense_30d),
        score_goal_achievement(goal_progress_ratios),
    ]
    total = BASE_SCORE + sum(c.points for c in components)
    total = max(0, min(MAX_SCORE, total))
    return MoneyScoreResult(total_score=total, level=_level_for_score(total), components=components)
