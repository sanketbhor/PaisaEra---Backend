"""
Categorizer — first stage of the Financial Intelligence Engine pipeline:

    Transaction → Categorizer → Budget Engine → Money Score Engine →
    Money DNA Engine → Recommendation Engine → AI Response

Rule-based merchant → category matching. Deliberately NOT an LLM call —
categorization runs on every single transaction (potentially dozens per
user per day), so it must be fast and free. Reserve the AI Gateway for
narration, not classification, per the TRD's hallucination-prevention
principle applied consistently across the whole engine.
"""
import re

# Ordered so more specific patterns are checked before generic ones.
MERCHANT_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"swiggy|zomato|dominos|mcdonald|kfc|behrouz|faasos", re.I), "Khana"),
    (re.compile(r"amazon|flipkart|myntra|ajio|nykaa", re.I), "Shopping"),
    (re.compile(r"netflix|spotify|hotstar|prime video|youtube premium|sonyliv", re.I), "Entertainment"),
    (re.compile(r"electricity|water bill|gas bill|broadband|wifi|airtel|jio|vodafone", re.I), "Bills"),
    (re.compile(r"uber|ola|rapido|irctc|indigo|redbus", re.I), "Ghumna"),
    (re.compile(r"rent|landlord|housing", re.I), "Rent"),
    (re.compile(r"apollo|pharmacy|hospital|clinic|1mg|pharmeasy", re.I), "Health"),
    (re.compile(r"zerodha|groww|upstox|mutual fund|sip|nps", re.I), "Investment"),
    (re.compile(r"salary|payroll", re.I), "Income"),
]

DEFAULT_CATEGORY = "Aur Kuch"


def categorize(merchant_name: str) -> str:
    """Best-effort rule-based category for a merchant name."""
    if not merchant_name:
        return DEFAULT_CATEGORY
    for pattern, category in MERCHANT_RULES:
        if pattern.search(merchant_name):
            return category
    return DEFAULT_CATEGORY


def is_recurring_candidate(merchant_name: str) -> bool:
    """
    Cheap heuristic for flagging likely-recurring merchants (subscriptions,
    bills) so the Subscription Audit feature has something to show even
    before a proper recurrence-detection job (comparing transaction history
    over time) is built. That real version belongs here too, once there's
    enough transaction history per user to detect actual monthly cadence —
    flagged rather than faked.
    """
    return bool(re.search(r"netflix|spotify|hotstar|prime|electricity|broadband|rent|sip", merchant_name, re.I))
