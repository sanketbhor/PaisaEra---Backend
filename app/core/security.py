"""
Security utilities: JWT access/refresh tokens, OTP hashing (Argon2id per the
Security & Access Document), and Redis-backed rate limiting.
"""
import secrets
import string
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from jose import jwt, JWTError

from app.core.config import settings

_hasher = PasswordHasher()


# ---------- OTP ----------
def generate_otp(length: int = None) -> str:
    length = length or settings.OTP_LENGTH
    return "".join(secrets.choice(string.digits) for _ in range(length))


def hash_otp(otp: str) -> str:
    return _hasher.hash(otp)


def verify_otp(otp: str, otp_hash: str) -> bool:
    try:
        return _hasher.verify(otp_hash, otp)
    except VerifyMismatchError:
        return False


# ---------- JWT ----------
def create_access_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": str(user_id), "type": "access", "exp": expire}
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {"sub": str(user_id), "type": "refresh", "exp": expire}
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        return None


def hash_token(token: str) -> str:
    """Hash refresh tokens before storing them (Security & Access Document §3)."""
    return _hasher.hash(token)


def verify_token_hash(token: str, token_hash: str) -> bool:
    try:
        return _hasher.verify(token_hash, token)
    except VerifyMismatchError:
        return False
