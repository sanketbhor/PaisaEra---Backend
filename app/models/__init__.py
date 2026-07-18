"""
Import every model here so Alembic's autogenerate can discover them all
via a single `from app.models import *` / Base.metadata.
"""
from app.models.user import User, OTPVerification, Session
from app.models.finance import Transaction, Budget, BudgetCategory, Goal, Quest, Streak
from app.models.intelligence import (
    FinancialScore, ScoreHistory, ScoreEvent,
    AIConversation, AIMessage, AIUsageDaily, AuditLog,
)

__all__ = [
    "User", "OTPVerification", "Session",
    "Transaction", "Budget", "BudgetCategory", "Goal", "Quest", "Streak",
    "FinancialScore", "ScoreHistory", "ScoreEvent",
    "AIConversation", "AIMessage", "AIUsageDaily", "AuditLog",
]
