"""
Budget Engine — second stage of the FIE pipeline.

All pure functions over data the caller already fetched — this module has
no DB/session dependency of its own, which is what makes it independently
testable (per the repository-pattern review point: business logic shouldn't
be entangled with data access).
"""
from dataclasses import dataclass
from datetime import date
import calendar


@dataclass
class CategoryBudget:
    category: str
    allocated: float
    spent: float

    @property
    def remaining(self) -> float:
        return self.allocated - self.spent

    @property
    def pct_used(self) -> float:
        return (self.spent / self.allocated) if self.allocated else 0.0

    @property
    def is_over_budget(self) -> bool:
        return self.spent > self.allocated


def days_left_in_month(today: date | None = None) -> int:
    today = today or date.today()
    last_day = calendar.monthrange(today.year, today.month)[1]
    return max(1, last_day - today.day + 1)


def safe_to_spend_today(categories: list[CategoryBudget], today: date | None = None) -> float:
    """
    Total remaining budget across all categories, divided by days left in
    the month. This is the single most important number in the app per the
    UX review ("Safe To Spend ₹840 Today, very prominently — that's what
    users care about") — it deserves to be a first-class, well-tested
    function rather than inline arithmetic scattered across screens.
    """
    total_remaining = sum(max(0.0, c.remaining) for c in categories)
    return round(total_remaining / days_left_in_month(today), 2)


def overspend_alerts(categories: list[CategoryBudget], threshold: float = 0.85) -> list[dict]:
    """Categories at or above `threshold` of their allocation — feeds
    real-time budget alert notifications (PRD Part 6)."""
    return [
        {"category": c.category, "pct_used": round(c.pct_used * 100), "spent": c.spent, "allocated": c.allocated}
        for c in categories
        if c.pct_used >= threshold
    ]


def budget_discipline_ratio(categories: list[CategoryBudget]) -> float:
    """0.0-1.0 — how well the user is staying within budget overall. Feeds
    the Money Score Engine's budget_discipline component directly, so the
    scoring logic and the budget-alerts logic derive from the same source
    of truth instead of two separate ad-hoc calculations."""
    total_allocated = sum(c.allocated for c in categories) or 1.0
    total_spent = sum(c.spent for c in categories)
    ratio = total_spent / total_allocated
    return max(0.0, 1.0 - ratio) if ratio <= 1.0 else 0.0
