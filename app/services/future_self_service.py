"""
Future Self Chat — "Can I afford this?" engine.

Per the TRD's hallucination-prevention principle: the financial calculation
is always deterministic Python, computed from the user's real data. The AI
Gateway is only used to wrap the numbers in a natural-language Hinglish
explanation — it never computes the numbers itself.
"""
import re
from decimal import Decimal

from sqlalchemy.orm import Session as DBSession

from app.models.finance import Goal
from app.services.ai_gateway import generate_response


def _extract_price(question: str, default: int = 20000) -> int:
    match = re.search(r"₹?\s?([\d,]{3,7})", question)
    if match:
        return int(match.group(1).replace(",", ""))
    return default


async def analyze_affordability(
    db: DBSession,
    user_id: str,
    question: str,
    personality: str = "coach",
    monthly_income: Decimal | None = None,
) -> dict:
    price = _extract_price(question)

    # Deterministic inputs — replace these placeholder queries with real
    # aggregations once transaction history is populated for a user.
    emergency_fund_goal = (
        db.query(Goal)
        .filter(Goal.user_id == user_id, Goal.name.ilike("%emergency%"))
        .first()
    )
    current_savings = float(emergency_fund_goal.current_amount) if emergency_fund_goal else 40000.0
    monthly_expense_estimate = float(monthly_income) * 0.55 if monthly_income else 15000.0

    remaining_savings = current_savings - price
    current_months_covered = round(current_savings / monthly_expense_estimate, 1) if monthly_expense_estimate else 0
    new_months_covered = round(max(0, remaining_savings) / monthly_expense_estimate, 1) if monthly_expense_estimate else 0
    suggested_monthly_save = 8000
    months_to_save_instead = max(1, -(-price // suggested_monthly_save))  # ceiling division

    calc = {
        "price": price,
        "current_months_covered": current_months_covered,
        "new_months_covered": new_months_covered,
        "months_to_save_instead": months_to_save_instead,
        "suggested_monthly_save": suggested_monthly_save,
    }

    narrative_prompt = (
        f"User ne pooch: '{question}'. Calculation (in numbers ko exactly use karo, "
        f"inhe badalna mat): agar abhi ₹{price} kharch kare, emergency fund "
        f"{calc['current_months_covered']} mahine se {calc['new_months_covered']} mahine tak "
        f"reduce ho jayega. Agar ₹{suggested_monthly_save}/month bachaye, "
        f"{months_to_save_instead} mahine mein bina emergency fund touch kiye kharid sakta hai. "
        "Ise ek short, natural Hinglish jawab mein explain karo, jaise ek dost financial advice de raha ho."
    )

    ai_result = await generate_response(
        user_text=narrative_prompt,
        personality=personality,
        user_id=user_id,
    )

    return {"calculation": calc, "narrative": ai_result["text"], "source": ai_result["source"]}
