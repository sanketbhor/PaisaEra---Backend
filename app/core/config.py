"""
Central configuration, loaded from environment variables (see .env.example).
Nothing here is hardcoded — every real credential comes from the environment.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    APP_NAME: str = "PaisaEra"
    APP_ENV: str = "development"
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"

    # Database
    DATABASE_URL: str = "postgresql+psycopg2://paisaera:paisaera@localhost:5432/paisaera"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Auth
    JWT_SECRET_KEY: str = "dev-only-insecure-secret-change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # OTP — defaults match the PaisaEra PRD's Auth module spec exactly
    OTP_LENGTH: int = 6
    OTP_EXPIRE_MINUTES: int = 5
    OTP_MAX_ATTEMPTS: int = 5
    OTP_RESEND_COOLDOWN_SECONDS: int = 30
    OTP_MAX_RESENDS: int = 5
    OTP_RATE_LIMIT_PER_HOUR: int = 5

    # SMS provider
    SMS_PROVIDER: str = "console"
    MSG91_API_KEY: str = ""
    MSG91_SENDER_ID: str = ""
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_FROM_NUMBER: str = ""

    # Google Sign-In
    GOOGLE_CLIENT_ID: str = ""

    # AI providers
    OPENAI_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    OPENROUTER_API_KEY: str = ""
    AI_DEFAULT_PROVIDER: str = "openai"
    AI_DEFAULT_MODEL: str = "gpt-4o-mini"

    # AI Gateway limits
    AI_FREE_TIER_DAILY_LIMIT: int = 30
    AI_PRO_TIER_DAILY_LIMIT: int = 100
    AI_MAX_RESPONSE_TOKENS: int = 150

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # Payments (not yet wired — see README)
    RAZORPAY_KEY_ID: str = ""
    RAZORPAY_KEY_SECRET: str = ""

    # CORS
    CORS_ORIGINS: str = "http://localhost:19006,http://localhost:3000"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def ai_providers_configured(self) -> bool:
        return bool(self.OPENAI_API_KEY or self.GEMINI_API_KEY or self.OPENROUTER_API_KEY)


settings = Settings()
