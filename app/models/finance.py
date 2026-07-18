import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, Numeric, Boolean, DateTime, Enum, ForeignKey, ARRAY, Date
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


def _uuid():
    return str(uuid.uuid4())


def _now():
    return datetime.now(timezone.utc)


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False, index=True)
    merchant_name = Column(String, nullable=True)
    amount = Column(Numeric(12, 2), nullable=False)
    direction = Column(Enum("debit", "credit", name="txn_direction_enum"), default="debit")
    category = Column(String, nullable=True)
    tags = Column(ARRAY(String), default=list)
    payment_method = Column(
        Enum("upi", "card", "cash", "netbanking", "other", name="payment_method_enum"),
        nullable=True,
    )
    # Matches the capture methods requested: SMS parsing, voice entry, manual entry (backup)
    source = Column(
        Enum("manual", "quick_add", "chat_parsed", "sms_parsed", "voice_parsed", name="txn_source_enum"),
        default="manual",
    )
    is_recurring = Column(Boolean, default=False)
    is_duplicate_flagged = Column(Boolean, default=False)
    transaction_ts = Column(DateTime(timezone=True), default=_now)
    created_at = Column(DateTime(timezone=True), default=_now)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now)

    user = relationship("User", back_populates="transactions")


class Budget(Base):
    __tablename__ = "budgets"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    period = Column(Enum("monthly", "weekly", name="budget_period_enum"), default="monthly")
    total_amount = Column(Numeric(12, 2), nullable=False)
    created_via = Column(Enum("manual", "ai_planner", name="budget_created_via_enum"), default="manual")
    status = Column(Enum("active", "archived", name="budget_status_enum"), default="active")
    created_at = Column(DateTime(timezone=True), default=_now)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now)


class BudgetCategory(Base):
    __tablename__ = "budget_categories"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    budget_id = Column(UUID(as_uuid=False), ForeignKey("budgets.id"), nullable=False)
    category = Column(String, nullable=False)
    allocated_amount = Column(Numeric(12, 2), nullable=False)
    spent_amount = Column(Numeric(12, 2), default=0)


class Goal(Base):
    __tablename__ = "goals"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    emoji = Column(String, nullable=True)
    target_amount = Column(Numeric(12, 2), nullable=False)
    current_amount = Column(Numeric(12, 2), default=0)
    target_date = Column(Date, nullable=True)
    status = Column(Enum("active", "completed", "abandoned", name="goal_status_enum"), default="active")
    created_at = Column(DateTime(timezone=True), default=_now)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now)


class Quest(Base):
    __tablename__ = "quests"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    type = Column(Enum("daily", "weekly", "monthly", name="quest_type_enum"), default="daily")
    description = Column(String, nullable=False)
    xp_reward = Column(Numeric(6, 0), default=10)
    status = Column(Enum("active", "completed", "expired", name="quest_status_enum"), default="active")
    assigned_date = Column(Date, default=lambda: datetime.now(timezone.utc).date())
    completed_at = Column(DateTime(timezone=True), nullable=True)


class Streak(Base):
    __tablename__ = "streaks"

    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), primary_key=True)
    current_streak = Column(Numeric(6, 0), default=0)
    longest_streak = Column(Numeric(6, 0), default=0)
    last_activity_date = Column(Date, nullable=True)
