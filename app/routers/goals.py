from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.models.finance import Goal
from app.schemas.api import GoalCreate, GoalUpdate, GoalResponse

router = APIRouter(prefix="/goals", tags=["goals"])


@router.get("", response_model=list[GoalResponse])
def list_goals(user: User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    return db.query(Goal).filter(Goal.user_id == user.id).order_by(Goal.created_at.desc()).all()


@router.post("", response_model=GoalResponse)
def create_goal(body: GoalCreate, user: User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    goal = Goal(
        user_id=user.id,
        name=body.name,
        emoji=body.emoji,
        target_amount=body.target_amount,
        target_date=body.target_date,
    )
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return goal


@router.put("/{goal_id}", response_model=GoalResponse)
def update_goal(goal_id: str, body: GoalUpdate, user: User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    goal = db.query(Goal).filter(Goal.id == goal_id, Goal.user_id == user.id).first()
    if not goal:
        raise HTTPException(status_code=404, detail="Goal nahi mila")
    if body.current_amount is not None:
        goal.current_amount = body.current_amount
    if body.status is not None:
        goal.status = body.status
    db.commit()
    db.refresh(goal)
    return goal
