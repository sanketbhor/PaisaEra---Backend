from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.models.finance import Budget, BudgetCategory, Goal
from app.models.intelligence import AuditLog

router = APIRouter(prefix="/users", tags=["users"])


class OnboardingGoal(BaseModel):
    name: str
    emoji: str | None = None
    target_amount: Decimal


class OnboardingBody(BaseModel):
    name: str
    monthly_income: Decimal
    income_type: str | None = Field(None, pattern="^(salaried|freelance|business|student)$")
    pay_day: int | None = Field(None, ge=1, le=31)
    fixed_commitments: Decimal | None = None
    categories: list[str] = []
    goal: OnboardingGoal | None = None


class ProfileUpdateBody(BaseModel):
    name: str | None = None
    monthly_income: Decimal | None = None
    income_type: str | None = Field(None, pattern="^(salaried|freelance|business|student)$")
    pay_day: int | None = Field(None, ge=1, le=31)
    fixed_commitments: Decimal | None = None
    ai_personality: str | None = Field(None, pattern="^(roast|mom|friend|ca|motivator|coach)$")


def _profile_dict(user: User) -> dict:
    return {
        "id": user.id,
        "mobile_number": user.mobile_number,
        "name": user.name,
        "monthly_income": user.monthly_income,
        "income_type": user.income_type,
        "pay_day": user.pay_day,
        "fixed_commitments": user.fixed_commitments,
        "ai_personality": user.ai_personality,
        "plan": user.plan,
        "onboarding_completed": user.onboarding_completed_at is not None,
    }


@router.get("/me")
def get_me(user: User = Depends(get_current_user)):
    return _profile_dict(user)


@router.patch("/me")
def update_me(body: ProfileUpdateBody, user: User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(user, field, value)
    db.add(AuditLog(user_id=user.id, event_type="profile_change", event_metadata={"fields": list(body.model_dump(exclude_unset=True).keys())}))
    db.commit()
    db.refresh(user)
    return _profile_dict(user)


@router.post("/me/onboarding")
def complete_onboarding(body: OnboardingBody, user: User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    """One-shot onboarding submit: profile fields + seeded budget categories
    + first savings goal, then mark onboarding complete. Idempotent-ish:
    re-running updates the profile but won't duplicate the budget or goal."""
    user.name = body.name
    user.monthly_income = body.monthly_income
    user.income_type = body.income_type
    user.pay_day = body.pay_day
    user.fixed_commitments = body.fixed_commitments

    # Seed a monthly budget from the disposable income, with the user's
    # chosen categories (unallocated — the AI planner / user fills amounts
    # in later). Skipped if they already have an active budget.
    if body.categories:
        has_budget = db.query(Budget).filter(Budget.user_id == user.id, Budget.status == "active").first()
        if not has_budget:
            disposable = body.monthly_income - (body.fixed_commitments or Decimal("0"))
            budget = Budget(
                user_id=user.id,
                period="monthly",
                total_amount=max(disposable, Decimal("0")),
                created_via="manual",
            )
            db.add(budget)
            db.flush()  # need budget.id for the category rows
            for cat in body.categories[:12]:
                db.add(BudgetCategory(budget_id=budget.id, category=cat, allocated_amount=Decimal("0")))

    if body.goal and not db.query(Goal).filter(Goal.user_id == user.id, Goal.status == "active").first():
        db.add(Goal(
            user_id=user.id,
            name=body.goal.name,
            emoji=body.goal.emoji,
            target_amount=body.goal.target_amount,
        ))

    user.onboarding_completed_at = datetime.now(timezone.utc)
    db.add(AuditLog(user_id=user.id, event_type="profile_change", event_metadata={"source": "onboarding"}))
    db.commit()
    db.refresh(user)
    return _profile_dict(user)
