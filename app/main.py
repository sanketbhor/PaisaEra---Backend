from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.logging_config import setup_logging, request_logging_middleware
from app.routers import auth, chat, transactions, daily_brief, future_self, money_score, goals, money_dna, privacy, users

setup_logging()

app = FastAPI(
    title=settings.APP_NAME,
    description="AI-first personal finance backend — Hinglish-only AI companion.",
    version="0.2.0",
)

app.middleware("http")(request_logging_middleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix=settings.API_V1_PREFIX)
app.include_router(chat.router, prefix=settings.API_V1_PREFIX)
app.include_router(transactions.router, prefix=settings.API_V1_PREFIX)
app.include_router(daily_brief.router, prefix=settings.API_V1_PREFIX)
app.include_router(future_self.router, prefix=settings.API_V1_PREFIX)
app.include_router(money_score.router, prefix=settings.API_V1_PREFIX)
app.include_router(money_dna.router, prefix=settings.API_V1_PREFIX)
app.include_router(goals.router, prefix=settings.API_V1_PREFIX)
app.include_router(privacy.router, prefix=settings.API_V1_PREFIX)
app.include_router(users.router, prefix=settings.API_V1_PREFIX)


@app.get("/")
def root():
    return {
        "app": settings.APP_NAME,
        "status": "running",
        "ai_providers_configured": settings.ai_providers_configured,
        "docs": "/docs",
    }


@app.get("/health")
def health():
    return {"status": "ok"}
