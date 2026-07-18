import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, Integer, DateTime, Enum, ForeignKey, JSON, Date, Text, Boolean
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


def _uuid():
    return str(uuid.uuid4())


def _now():
    return datetime.now(timezone.utc)


# ---------- Financial Intelligence Engine / Money Score — table names match
# the PaisaEra Backend Schemas Document / PRD Part 8 exactly ----------

class FinancialScore(Base):
    __tablename__ = "financial_scores"

    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), primary_key=True)
    current_score = Column(Integer, default=650)
    level = Column(String, default="Money Starter")
    last_computed_at = Column(DateTime(timezone=True), default=_now)


class ScoreHistory(Base):
    __tablename__ = "score_history"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False, index=True)
    score = Column(Integer, nullable=False)
    recorded_at = Column(DateTime(timezone=True), default=_now)


class ScoreEvent(Base):
    __tablename__ = "score_events"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    component = Column(
        Enum(
            "budget_discipline", "savings_behaviour", "expense_behaviour", "goal_achievement",
            "money_habits", "income_stability", "financial_awareness", "financial_safety",
            name="score_component_enum",
        ),
        nullable=False,
    )
    delta = Column(Integer, nullable=False)
    reason = Column(String, nullable=False)  # required — Explainable AI, never optional
    created_at = Column(DateTime(timezone=True), default=_now)


class AIConversation(Base):
    __tablename__ = "ai_conversations"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    personality = Column(
        Enum("roast", "mom", "friend", "ca", "motivator", "coach", name="conv_personality_enum")
    )
    started_at = Column(DateTime(timezone=True), default=_now)


class AIMessage(Base):
    __tablename__ = "ai_messages"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    conversation_id = Column(UUID(as_uuid=False), ForeignKey("ai_conversations.id"), nullable=False)
    sender = Column(Enum("user", "assistant", name="ai_sender_enum"), nullable=False)
    text = Column(Text, nullable=False)
    model_used = Column(String, nullable=True)
    explanation = Column(JSON, nullable=True)  # reason/confidence/supporting_factors — Explainable AI
    created_at = Column(DateTime(timezone=True), default=_now)


class AIUsageDaily(Base):
    __tablename__ = "ai_usage_daily"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False, index=True)
    usage_date = Column(Date, default=lambda: datetime.now(timezone.utc).date())
    message_count = Column(Integer, default=0)
    tokens_input = Column(Integer, default=0)
    tokens_output = Column(Integer, default=0)
    blocked_offtopic_count = Column(Integer, default=0)
    capped_count = Column(Integer, default=0)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=True)
    event_type = Column(
        Enum(
            "otp_sent", "otp_verified", "otp_failed", "token_refreshed", "profile_change", "budget_change",
            "goal_change", "ai_memory_change", "permission_change", "subscription_change",
            "data_export", "account_delete",
            name="audit_event_enum",
        ),
        nullable=False,
    )
    event_metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now)
    # Append-only by convention — no update/delete exposed via the API layer.
