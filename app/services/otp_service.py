"""
OTP send/verify logic with a pluggable SMS provider.

Swap the provider by setting SMS_PROVIDER in .env — 'console' (default, logs
to stdout for local dev), 'msg91', or 'twilio'. The msg91/twilio classes are
stubbed with clear TODOs since they need real account credentials you'll add
later.
"""
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session as DBSession

from app.core.config import settings
from app.core.security import generate_otp, hash_otp, verify_otp as _verify_otp_hash
from app.models.user import OTPVerification


class SMSProvider(ABC):
    @abstractmethod
    def send(self, mobile_number: str, otp: str) -> bool:
        ...


class ConsoleSMSProvider(SMSProvider):
    """Local dev provider — just logs the OTP instead of sending a real SMS."""

    def send(self, mobile_number: str, otp: str) -> bool:
        print(f"[ConsoleSMSProvider] OTP for {mobile_number}: {otp}")
        return True


class MSG91Provider(SMSProvider):
    """
    TODO: implement once you have an MSG91 account.
    See https://docs.msg91.com/ for the OTP API. Read the API key from
    settings.MSG91_API_KEY and sender ID from settings.MSG91_SENDER_ID.
    """

    def send(self, mobile_number: str, otp: str) -> bool:
        raise NotImplementedError(
            "MSG91Provider is a stub. Fill in the real API call using "
            "settings.MSG91_API_KEY once you have credentials."
        )


class TwilioProvider(SMSProvider):
    """
    TODO: implement once you have a Twilio account.
    See https://www.twilio.com/docs/sms for the send-SMS API. Read
    settings.TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_FROM_NUMBER.
    """

    def send(self, mobile_number: str, otp: str) -> bool:
        raise NotImplementedError(
            "TwilioProvider is a stub. Fill in the real API call using "
            "settings.TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN once you have credentials."
        )


def get_sms_provider() -> SMSProvider:
    if settings.SMS_PROVIDER == "msg91":
        return MSG91Provider()
    if settings.SMS_PROVIDER == "twilio":
        return TwilioProvider()
    return ConsoleSMSProvider()


def request_otp(db: DBSession, mobile_number: str) -> dict:
    """
    Creates an OTP record and sends it via the configured provider.
    Enforces the resend-count and rate-limit rules from the PRD's Auth module.
    """
    recent_count = (
        db.query(OTPVerification)
        .filter(
            OTPVerification.mobile_number == mobile_number,
            OTPVerification.created_at > datetime.now(timezone.utc) - timedelta(hours=1),
        )
        .count()
    )
    if recent_count >= settings.OTP_RATE_LIMIT_PER_HOUR:
        return {"success": False, "reason": "rate_limited"}

    otp = generate_otp(settings.OTP_LENGTH)
    record = OTPVerification(
        mobile_number=mobile_number,
        otp_hash=hash_otp(otp),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=settings.OTP_EXPIRE_MINUTES),
    )
    db.add(record)
    db.commit()

    provider = get_sms_provider()
    sent = provider.send(mobile_number, otp)
    return {"success": sent, "otp_id": record.id}


def verify_otp_code(db: DBSession, mobile_number: str, code: str) -> dict:
    record = (
        db.query(OTPVerification)
        .filter(OTPVerification.mobile_number == mobile_number, OTPVerification.verified_at.is_(None))
        .order_by(OTPVerification.created_at.desc())
        .first()
    )
    if not record:
        return {"success": False, "reason": "not_found"}
    if record.expires_at < datetime.now(timezone.utc):
        return {"success": False, "reason": "expired"}
    if record.attempt_count >= settings.OTP_MAX_ATTEMPTS:
        return {"success": False, "reason": "too_many_attempts"}

    record.attempt_count += 1
    if not _verify_otp_hash(code, record.otp_hash):
        db.commit()
        return {"success": False, "reason": "invalid"}

    record.verified_at = datetime.now(timezone.utc)
    db.commit()
    return {"success": True}
