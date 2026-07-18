from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DBSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.models.finance import Budget, BudgetCategory, Transaction
from app.services.fie.engine import fie
from app.services.fie.budget_engine import CategoryBudget
from app.schemas.api import MoneyDNAResponse, MoneyDNABreakdownItem

router = APIRouter(prefix="/money-dna", tags=["money-dna"])


@router.get("", response_model=MoneyDNAResponse)
def get_money_dna(user: User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    """
    Per the Moat Strategy doc, Money DNA evolves monthly — this endpoint
    computes on-demand for now (fine at current scale), but should move to
    a Celery monthly batch job (see app/workers/celery_app.py) writing to
    a `money_dna_profiles` table once there's enough traffic that
    recomputing per-request becomes wasteful. Flagged rather than
    prematurely built.
    """
    budget = (
        db.query(Budget)
        .filter(Budget.user_id == user.id, Budget.status == "active")
        .order_by(Budget.created_at.desc())
        .first()
    )
    categories: list[CategoryBudget] = []
    if budget:
        rows = db.query(BudgetCategory).filter(BudgetCategory.budget_id == budget.id).all()
        categories = [CategoryBudget(category=r.category, allocated=float(r.allocated_amount), spent=float(r.spent_amount)) for r in rows]

    total_spend = sum(c.spent for c in categories) or 1.0
    category_pct = {c.category: c.spent / total_spend for c in categories}

    thirty_days_ago = date.today() - timedelta(days=30)
    txns = db.query(Transaction).filter(Transaction.user_id == user.id, Transaction.transaction_ts >= thirty_days_ago).all()
    income = float(sum(t.amount for t in txns if t.direction == "credit"))
    expense = float(sum(t.amount for t in txns if t.direction == "debit"))
    savings_rate = max(0.0, (income - expense) / income) if income else 0.0

    from app.services.fie.money_dna_engine import classify_money_dna

    result = classify_money_dna(category_pct, savings_rate)

    return MoneyDNAResponse(
        archetype=result.primary_archetype,
        breakdown=[MoneyDNABreakdownItem(**b) for b in result.breakdown],
    )
