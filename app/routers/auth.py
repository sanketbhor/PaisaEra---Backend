from datetime import datetime, timedelta, timezone

import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session as DBSession

from app.core.database import get_db
from app.core.security import create_access_token, create_refresh_token, decode_token, hash_token, verify_token_hash
from app.models.user import User, Session as UserSession
from app.models.intelligence import AuditLog
from app.services.otp_service import request_otp, verify_otp_code
from app.core.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])


def _normalize_indian_mobile(value: str) -> str:
    """Server-side canonical form: exactly 10 digits starting 6-9.
    Tolerates '+91 98765 43210' style input but rejects anything that
    isn't a plausible Indian mobile — the client validates too, but the
    API must not trust the client."""
    digits = re.sub(r"\D", "", value)
    if len(digits) > 10 and digits.startswith("91"):
        digits = digits[2:]
    digits = digits.lstrip("0")
    if not re.fullmatch(r"[6-9]\d{9}", digits):
        raise ValueError("Sahi Indian mobile number daalo")
    return digits


class RequestOTPBody(BaseModel):
    mobile_number: str

    @field_validator("mobile_number")
    @classmethod
    def _validate_mobile(cls, v: str) -> str:
        return _normalize_indian_mobile(v)


class RefreshBody(BaseModel):
    refresh_token: str


class VerifyOTPBody(BaseModel):
    mobile_number: str
    code: str = Field(..., pattern=r"^\d{4,8}$")
    device_id: str | None = None
    device_name: str | None = None

    @field_validator("mobile_number")
    @classmethod
    def _validate_mobile(cls, v: str) -> str:
        return _normalize_indian_mobile(v)


@router.post("/otp/request")
def request_otp_endpoint(body: RequestOTPBody, db: DBSession = Depends(get_db)):
    result = request_otp(db, body.mobile_number)
    db.add(AuditLog(event_type="otp_sent", event_metadata={"mobile_number": body.mobile_number, "success": result["success"]}))
    db.commit()
    if not result["success"]:
        raise HTTPException(status_code=429, detail="Bahut zyada OTP request ho gayi. Thodi der baad try karo.")
    return {"message": "OTP bhej diya gaya"}


@router.post("/otp/verify")
def verify_otp_endpoint(body: VerifyOTPBody, db: DBSession = Depends(get_db)):
    result = verify_otp_code(db, body.mobile_number, body.code)

    event_type = "otp_verified" if result["success"] else "otp_failed"
    db.add(AuditLog(event_type=event_type, event_metadata={"mobile_number": body.mobile_number, "reason": result.get("reason")}))
    db.commit()

    if not result["success"]:
        reasons = {
            "not_found": "OTP nahi mila, naya request karo",
            "expired": "OTP expire ho gaya, naya request karo",
            "too_many_attempts": "Bahut zyada galat attempts ho gaye",
            "invalid": "Galat OTP",
        }
        raise HTTPException(status_code=400, detail=reasons.get(result["reason"], "OTP verify nahi ho paaya"))

    user = db.query(User).filter(User.mobile_number == body.mobile_number).first()
    is_new_user = user is None
    if not user:
        user = User(mobile_number=body.mobile_number)
        db.add(user)
        db.commit()
        db.refresh(user)

    access_token = create_access_token(user.id)
    refresh_token = create_refresh_token(user.id)

    session = UserSession(
        user_id=user.id,
        refresh_token_hash=hash_token(refresh_token),
        device_id=body.device_id,
        device_name=body.device_name,
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )
    db.add(session)
    db.commit()

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "is_new_user": is_new_user,
        "user_id": user.id,
        "onboarding_completed": user.onboarding_completed_at is not None,
    }


@router.post("/refresh")
def refresh_endpoint(body: RefreshBody, db: DBSession = Depends(get_db)):
    payload = decode_token(body.refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Session expire ho gaya, dobara login karo")

    now = datetime.now(timezone.utc)
    # Hashes are salted (argon2), so the session can't be looked up by hash
    # directly -- fetch this user's live sessions and verify against each.
    sessions = (
        db.query(UserSession)
        .filter(
            UserSession.user_id == payload["sub"],
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > now,
        )
        .all()
    )
    session = next((s for s in sessions if verify_token_hash(body.refresh_token, s.refresh_token_hash)), None)
    if not session:
        raise HTTPException(status_code=401, detail="Session expire ho gaya, dobara login karo")

    # Rotate: the presented refresh token is single-use. The session row is
    # kept (device identity, audit trail) and re-keyed to the new token.
    new_refresh_token = create_refresh_token(payload["sub"])
    session.refresh_token_hash = hash_token(new_refresh_token)
    session.expires_at = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    db.add(AuditLog(event_type="token_refreshed", event_metadata={"session_id": session.id}))
    db.commit()

    return {
        "access_token": create_access_token(payload["sub"]),
        "refresh_token": new_refresh_token,
    }
