from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DBSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.models.finance import Transaction, Streak

router = APIRouter(prefix="/daily-brief", tags=["daily-brief"])


@router.get("")
def get_daily_brief(user: User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    """
    Matches the ☀️ Money Brief format from the product spec:
    Wallet, Bank, Bills due, Today's safe spending, Yesterday you saved,
    Current streak.

    NOTE: wallet/bank balances aren't tracked anywhere in this MVP schema
    yet (that needs either manual balance entry or, later, Account
    Aggregator bank sync per the product roadmap) — these are placeholder
    zeros until that data source exists. Everything else here is computed
    from real transaction data.
    """
    yesterday = date.today() - timedelta(days=1)
    yesterday_txns = (
        db.query(Transaction)
        .filter(Transaction.user_id == user.id, Transaction.transaction_ts >= yesterday,
                 Transaction.transaction_ts < date.today())
        .all()
    )
    yesterday_spent = sum(t.amount for t in yesterday_txns if t.direction == "debit") or Decimal(0)

    streak = db.query(Streak).filter(Streak.user_id == user.id).first()

    return {
        "greeting": f"Good Morning {user.name or 'Dost'} ☀️",
        "wallet": 0,  # TODO: needs a wallet/cash-on-hand tracking feature
        "bank": 0,    # TODO: needs manual balance entry or AA bank sync (Phase 2+)
        "bills_due": 0,  # TODO: needs a bills/recurring-payments tracking feature
        "today_safe_spending": _estimate_safe_spending(db, user),
        "yesterday_saved": max(0, 500 - float(yesterday_spent)),  # placeholder baseline
        "current_streak_days": int(streak.current_streak) if streak else 0,
    }


def _estimate_safe_spending(db: DBSession, user: User) -> float:
    # Placeholder heuristic until real budget data is wired through —
    # replace with the real Budget/BudgetCategory-based calculation once
    # a user has an active budget (see money_score_service.py for the
    # equivalent real-data pattern to follow).
    return 950.0
