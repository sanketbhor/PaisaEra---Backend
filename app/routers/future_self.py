from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.services.future_self_service import analyze_affordability

router = APIRouter(prefix="/future-self", tags=["future-self"])


class FutureSelfQuestion(BaseModel):
    question: str


@router.post("/ask")
async def ask_future_self(
    body: FutureSelfQuestion,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    return await analyze_affordability(
        db=db,
        user_id=user.id,
        question=body.question,
        personality=user.ai_personality or "coach",
        monthly_income=user.monthly_income,
    )
