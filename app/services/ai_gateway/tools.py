"""
Tool Registry — formalizes what the review called out directly: instead of
the AI Gateway returning free-form text that the client then regex-matches
(the `inferToolCard` hack in the mobile app's useAIStore.ts), the LLM is
given a set of callable tools with JSON-schema arguments and decides
whether to call one, using LiteLLM's OpenAI-compatible function-calling
interface.

Each tool's `handler` takes (user_id, db, **arguments) and returns a plain
dict — which becomes the `tool_card` payload sent to the client, replacing
regex-inferred cards with actually-structured data.
"""
from dataclasses import dataclass
from typing import Callable

from sqlalchemy.orm import Session as DBSession

from app.models.finance import Transaction, Goal
from app.services.fie.categorizer import categorize
from app.services.fie.budget_engine import CategoryBudget, safe_to_spend_today


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict  # JSON schema, passed straight through to the provider
    handler: Callable[..., dict]


def _handle_add_expense(user_id: str, db: DBSession, amount: float, category: str | None = None, merchant: str | None = None) -> dict:
    merchant = merchant or "Chat Entry"
    resolved_category = category or categorize(merchant)
    txn = Transaction(user_id=user_id, merchant_name=merchant, amount=amount, category=resolved_category, source="chat_parsed")
    db.add(txn)
    db.commit()
    db.refresh(txn)
    return {
        "type": "transaction",
        "data": {
            "id": txn.id,
            "merchant": txn.merchant_name,
            "amount": float(txn.amount),
            "category": txn.category,
        },
    }


def _handle_update_goal(user_id: str, db: DBSession, goal_id: str, current_amount: float) -> dict:
    goal = db.query(Goal).filter(Goal.id == goal_id, Goal.user_id == user_id).first()
    if not goal:
        return {"type": "error", "data": {"message": "Goal nahi mila"}}
    goal.current_amount = current_amount
    db.commit()
    db.refresh(goal)
    return {
        "type": "goal",
        "data": {
            "id": goal.id,
            "name": goal.name,
            "currentAmount": float(goal.current_amount),
            "targetAmount": float(goal.target_amount),
        },
    }


def _handle_calculate_savings(user_id: str, db: DBSession, habit: str, weekly_estimate: float = 730) -> dict:
    annual_impact = weekly_estimate * 52
    return {
        "type": "whatIf",
        "data": {"habit": habit, "annualImpact": annual_impact},
    }


def _handle_forecast_cashflow(user_id: str, db: DBSession, months_ahead: int = 1) -> dict:
    # Simple linear projection off the last 30 days — a real forecast
    # model (seasonality, recurring-bill awareness) is future work; this
    # is deliberately the simplest honest version rather than a fake
    # sophisticated-looking number.
    from datetime import date, timedelta

    thirty_days_ago = date.today() - timedelta(days=30)
    recent = db.query(Transaction).filter(Transaction.user_id == user_id, Transaction.transaction_ts >= thirty_days_ago).all()
    net_30d = sum((t.amount if t.direction == "credit" else -t.amount) for t in recent)
    projected = float(net_30d) * months_ahead
    return {"type": "forecast", "data": {"months_ahead": months_ahead, "projected_net_change": projected}}


def _handle_check_budget_status(user_id: str, db: DBSession, category: str | None = None) -> dict:
    """
    Real chaining use case: "swiggy pe 350 kharch hue, budget ke andar hoon?"
    needs addExpense THEN this tool in the same turn -- exactly what
    orchestrator.py's multi-step graph exists for, as opposed to the
    single-tool-call pattern in gateway.py's generate_response().
    """
    from app.services.fie.budget_engine import CategoryBudget, overspend_alerts
    from app.models.finance import Budget, BudgetCategory

    budget = (
        db.query(Budget)
        .filter(Budget.user_id == user_id, Budget.status == "active")
        .order_by(Budget.created_at.desc())
        .first()
    )
    if not budget:
        return {"type": "error", "data": {"message": "Koi active budget nahi mila"}}

    rows = db.query(BudgetCategory).filter(BudgetCategory.budget_id == budget.id).all()
    categories = [
        CategoryBudget(category=r.category, allocated=float(r.allocated_amount), spent=float(r.spent_amount))
        for r in rows
        if not category or r.category == category
    ]
    alerts = overspend_alerts(categories, threshold=0.85)

    return {
        "type": "budgetStatus",
        "data": {
            "over_budget_categories": alerts,
            "is_over_any_budget": len(alerts) > 0,
        },
    }


TOOL_REGISTRY: dict[str, Tool] = {
    "addExpense": Tool(
        name="addExpense",
        description="Log a new expense transaction for the user.",
        parameters={
            "type": "object",
            "properties": {
                "amount": {"type": "number", "description": "Amount spent in INR"},
                "category": {"type": "string", "description": "Category, e.g. Khana, Shopping. Optional — auto-categorized from merchant if omitted."},
                "merchant": {"type": "string", "description": "Merchant name, e.g. Swiggy"},
            },
            "required": ["amount"],
        },
        handler=_handle_add_expense,
    ),
    "updateGoal": Tool(
        name="updateGoal",
        description="Update the current saved amount for one of the user's goals.",
        parameters={
            "type": "object",
            "properties": {
                "goal_id": {"type": "string"},
                "current_amount": {"type": "number"},
            },
            "required": ["goal_id", "current_amount"],
        },
        handler=_handle_update_goal,
    ),
    "calculateSavings": Tool(
        name="calculateSavings",
        description="Calculate the annual savings impact of stopping or reducing a spending habit (What-If Simulator).",
        parameters={
            "type": "object",
            "properties": {
                "habit": {"type": "string", "description": "e.g. 'ordering Swiggy'"},
                "weekly_estimate": {"type": "number", "description": "Estimated weekly spend on this habit in INR"},
            },
            "required": ["habit"],
        },
        handler=_handle_calculate_savings,
    ),
    "forecastCashflow": Tool(
        name="forecastCashflow",
        description="Project net cashflow change over the coming months based on recent spending trend.",
        parameters={
            "type": "object",
            "properties": {"months_ahead": {"type": "integer", "default": 1}},
            "required": [],
        },
        handler=_handle_forecast_cashflow,
    ),
    "checkBudgetStatus": Tool(
        name="checkBudgetStatus",
        description="Check whether the user is currently over budget, overall or in a specific category. Call this after logging an expense if the user asks whether they're within budget.",
        parameters={
            "type": "object",
            "properties": {"category": {"type": "string", "description": "Optional -- check one category only, e.g. Khana"}},
            "required": [],
        },
        handler=_handle_check_budget_status,
    ),
    # createBudget is intentionally not implemented yet — needs a
    # /budgets POST endpoint with proper category-allocation validation
    # first (see app/routers — no budgets router exists yet). Registering
    # a tool whose handler doesn't fully exist would let the LLM "succeed"
    # at something the backend can't actually do yet.
}


def get_tool_schemas_for_provider() -> list[dict]:
    """OpenAI-compatible tool schema list, as LiteLLM expects for the
    `tools` parameter on chat completion calls."""
    return [
        {
            "type": "function",
            "function": {"name": t.name, "description": t.description, "parameters": t.parameters},
        }
        for t in TOOL_REGISTRY.values()
    ]


def execute_tool(name: str, user_id: str, db: DBSession, arguments: dict) -> dict:
    tool = TOOL_REGISTRY.get(name)
    if not tool:
        return {"type": "error", "data": {"message": f"Unknown tool: {name}"}}
    return tool.handler(user_id, db, **arguments)
