"""
AI-assisted merchant categorization — the escalation path when the static
regex rules in categorizer.py don't match. Runs in explicit batches (user
taps "AI se categories sudharo" / after an SMS import), never per-request:
one Gemini call categorizes ~50 merchant strings at once, so cost stays
negligible and the hot transaction paths stay LLM-free per the FIE's
"AI narrates, rules classify" principle. Results are persisted as
MerchantCategoryOverride rows (source='ai'), so each merchant string is
paid for at most once, ever.
"""
import json
import logging

import litellm

from app.core.config import settings
from app.services.fie.categorizer import DEFAULT_CATEGORY

logger = logging.getLogger("paisaera.ai_categorizer")

# The full category vocabulary. Keep in sync with the mobile picker
# (apps/mobile/src/constants/categories.ts).
ALLOWED_CATEGORIES = [
    "Khana",
    "Shopping",
    "Subscription",
    "Bills",
    "Ghumna",
    "Rent",
    "Health",
    "Investment",
    "Income",
    "EMI",
    "Credit Card",
    "UPI Transfer",
    "Petrol",
    "Miscellaneous",
]

_PROMPT = (
    "You categorize merchant strings from Indian bank transactions. "
    "For each input string, pick EXACTLY ONE category from this list:\n"
    f"{', '.join(ALLOWED_CATEGORIES)}\n\n"
    "Guidance: food delivery/restaurants → Khana; e-commerce → Shopping; "
    "OTT/streaming/SaaS → Subscription; utilities/recharges → Bills; "
    "cabs/trains/flights/buses → Ghumna; fuel pumps (HPCL/IOCL/BPCL/Shell) → Petrol; "
    "salary/refunds → Income; person-to-person payments → UPI Transfer; "
    "genuinely unknowable → Miscellaneous.\n\n"
    "Reply with ONLY a JSON object mapping every input string verbatim to its "
    "category. No markdown, no commentary."
)


def _resolve_api_key() -> str | None:
    if settings.AI_DEFAULT_PROVIDER == "gemini":
        return settings.GEMINI_API_KEY or None
    if settings.AI_DEFAULT_PROVIDER == "openai":
        return settings.OPENAI_API_KEY or None
    return settings.OPENROUTER_API_KEY or None


async def categorize_merchants(merchants: list[str]) -> dict[str, str]:
    """Best-effort batch categorization. Returns {merchant: category} for
    the merchants the model answered validly; silently drops the rest
    (they just stay Miscellaneous and can be retried later)."""
    if not merchants or not settings.ai_providers_configured:
        return {}

    try:
        response = await litellm.acompletion(
            model=settings.AI_DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": _PROMPT},
                {"role": "user", "content": json.dumps(merchants, ensure_ascii=False)},
            ],
            max_tokens=4000,
            temperature=0,
            api_key=_resolve_api_key(),
        )
        text = (response["choices"][0]["message"]["content"] or "").strip()
        # Tolerate a ```json fence despite the prompt.
        if text.startswith("```"):
            text = text.strip("`")
            text = text[text.index("{"):]
        raw = json.loads(text[text.index("{"): text.rindex("}") + 1])
    except Exception as e:  # noqa: BLE001 -- any parse/provider failure is non-fatal
        logger.warning(f"ai_categorizer: batch failed: {e}")
        return {}

    result: dict[str, str] = {}
    for merchant, category in raw.items():
        if merchant in merchants and category in ALLOWED_CATEGORIES and category != DEFAULT_CATEGORY:
            result[merchant] = category
    return result
