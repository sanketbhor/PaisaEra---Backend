import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, Numeric, Integer, DateTime, Enum, ForeignKey, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


def _uuid():
    return str(uuid.uuid4())


def _now():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    mobile_number = Column(String, unique=True, nullable=False, index=True)
    google_id = Column(String, unique=True, nullable=True)
    name = Column(String, nullable=True)
    language = Column(String, default="hi_en")  # Hinglish is the default and only supported UI language for now
    ai_personality = Column(
        Enum("roast", "mom", "friend", "ca", "motivator", "coach", name="ai_personality_enum"),
        default="roast",
    )
    monthly_income = Column(Numeric(12, 2), nullable=True)
    income_type = Column(
        Enum("salaried", "freelance", "business", "student", name="income_type_enum"),
        nullable=True,
    )
    pay_day = Column(Integer, nullable=True)  # 1-31, null = irregular income
    fixed_commitments = Column(Numeric(12, 2), nullable=True)  # rent + EMIs; income minus this = real disposable
    plan = Column(Enum("free", "pro", name="plan_enum"), default="free")
    onboarding_completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now)

    transactions = relationship("Transaction", back_populates="user")
    sessions = relationship("Session", back_populates="user")


class OTPVerification(Base):
    __tablename__ = "otp_verifications"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    mobile_number = Column(String, nullable=False, index=True)
    otp_hash = Column(String, nullable=False)
    attempt_count = Column(Integer, default=0)
    resend_count = Column(Integer, default=0)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    verified_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now)


class Session(Base):
    __tablename__ = "sessions"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    refresh_token_hash = Column(String, nullable=False)
    device_id = Column(String, nullable=True)
    device_name = Column(String, nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now)

    user = relationship("User", back_populates="sessions")
