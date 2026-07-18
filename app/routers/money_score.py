from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DBSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.models.finance import Budget, BudgetCategory, Goal, Transaction
from app.models.intelligence import FinancialScore, ScoreHistory, ScoreEvent
from app.services.fie.engine import fie
from app.services.fie.budget_engine import CategoryBudget
from app.services.fie.money_score_engine import COMPONENT_WEIGHTS
from app.schemas.api import MoneyScoreResponse, ScoreHistoryPoint, ScoreComponentDetail

router = APIRouter(prefix="/money-score", tags=["money-score"])


def _load_category_budgets(db: DBSession, user_id: str) -> list[CategoryBudget]:
    budget = (
        db.query(Budget)
        .filter(Budget.user_id == user_id, Budget.status == "active")
        .order_by(Budget.created_at.desc())
        .first()
    )
    if not budget:
        return []
    rows = db.query(BudgetCategory).filter(BudgetCategory.budget_id == budget.id).all()
    return [CategoryBudget(category=r.category, allocated=float(r.allocated_amount), spent=float(r.spent_amount)) for r in rows]


@router.get("", response_model=MoneyScoreResponse)
def get_score(user: User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    categories = _load_category_budgets(db, user.id)

    thirty_days_ago = date.today() - timedelta(days=30)
    txns = db.query(Transaction).filter(Transaction.user_id == user.id, Transaction.transaction_ts >= thirty_days_ago).all()
    income = float(sum(t.amount for t in txns if t.direction == "credit"))
    expense = float(sum(t.amount for t in txns if t.direction == "debit"))

    goals = db.query(Goal).filter(Goal.user_id == user.id, Goal.status == "active").all()
    goal_ratios = [float(g.current_amount) / float(g.target_amount) for g in goals if g.target_amount]

    category_pct: dict[str, float] = {}
    total_spend = sum(c.spent for c in categories) or 1.0
    for c in categories:
        category_pct[c.category] = c.spent / total_spend

    snapshot = fie.compute_snapshot(
        categories=categories,
        total_income_30d=income,
        total_expense_30d=expense,
        goal_progress_ratios=goal_ratios,
        category_spend_pct=category_pct,
        monthly_income=float(user.monthly_income) if user.monthly_income else None,
    )

    # Persist — same read/write pattern as before, now sourced from the FIE
    record = db.query(FinancialScore).filter(FinancialScore.user_id == user.id).first()
    if not record:
        record = FinancialScore(user_id=user.id)
        db.add(record)
    record.current_score = snapshot.money_score.total_score
    record.level = snapshot.money_score.level

    db.add_all(
        ScoreEvent(user_id=user.id, component=c.component, delta=c.points, reason=c.reason)
        for c in snapshot.money_score.components
    )
    db.add(ScoreHistory(user_id=user.id, score=snapshot.money_score.total_score))
    db.commit()

    history = (
        db.query(ScoreHistory)
        .filter(ScoreHistory.user_id == user.id)
        .order_by(ScoreHistory.recorded_at.desc())
        .limit(7)
        .all()
    )

    return MoneyScoreResponse(
        current_score=record.current_score,
        level=record.level,
        history=[ScoreHistoryPoint(score=h.score, recorded_at=h.recorded_at) for h in reversed(history)],
        components=[
            ScoreComponentDetail(
                component=c.component,
                points=c.points,
                max_points=COMPONENT_WEIGHTS.get(c.component, 0),
                reason=c.reason,
            )
            for c in snapshot.money_score.components
        ],
    )
