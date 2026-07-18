"""
Celery app for scheduled/async jobs — Money Score recompute, Daily Brief
pre-generation, etc.

Run the worker and beat scheduler as separate processes:
    celery -A app.workers.celery_app worker --loglevel=info
    celery -A app.workers.celery_app beat --loglevel=info

(Both are commented out in docker-compose.yml until you're ready to use them.)
"""
from celery import Celery
from celery.schedules import crontab

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.user import User
from app.services.money_score_service import recompute_score

celery_app = Celery(
    "paisaera",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.beat_schedule = {
    "recompute-money-scores-nightly": {
        "task": "app.workers.celery_app.recompute_all_scores",
        "schedule": crontab(hour=2, minute=0),  # 2 AM daily
    },
}


@celery_app.task
def recompute_all_scores():
    """Nightly batch recompute for every user — mirrors the TRD's guidance
    that Money Score is a scheduled/batch process, not per-request."""
    db = SessionLocal()
    try:
        user_ids = [row[0] for row in db.query(User.id).all()]
        for uid in user_ids:
            recompute_score(db, uid)
        return {"recomputed": len(user_ids)}
    finally:
        db.close()


@celery_app.task
def send_daily_brief_push(user_id: str):
    """
    TODO: wire this to Expo Push Notifications (per the tech stack — mobile
    is Expo-based) once the mobile app registers push tokens. This task
    should be scheduled per-user around their typical morning check-in time.
    """
    raise NotImplementedError("Wire this to Expo Push Notifications once push tokens are collected.")
