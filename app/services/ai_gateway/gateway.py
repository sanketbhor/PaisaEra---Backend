"""
AI Gateway — main orchestration, now with formalized tool calling.

Same 3-layer governance model as before (scope pre-filter → system prompt →
rate limit), plus a fourth capability: the LLM can call into TOOL_REGISTRY
(app/services/ai_gateway/tools.py) instead of the client having to
regex-guess intent from free text. This directly replaces the
`inferToolCard` hack that was flagged as a placeholder in the mobile app's
useAIStore.ts — the mobile side should now trust `tool_card` in the API
response directly rather than pattern-matching response text itself.
"""
import re
import json
from datetime import date
from typing import Optional

import redis
import litellm
from sqlalchemy.orm import Session as DBSession

from app.core.config import settings
from app.services.ai_gateway.personalities import PERSONALITIES, TEMPLATE_BANK, OFFTOPIC_REDIRECT
from app.services.ai_gateway.tools import get_tool_schemas_for_provider, execute_tool

_redis = redis.from_url(settings.REDIS_URL, decode_responses=True)

_OFFTOPIC_PATTERNS = [
    r"\bwrite (a |some )?code\b", r"\bpython script\b", r"\bfunction\b.*\breturn\b",
    r"\bgenerate (an? )?image\b", r"\bdraw\b.*\bpicture\b",
    r"\bhomework\b", r"\bessay\b", r"\bpoem\b", r"\bsong lyrics\b",
    r"\bcapital of\b", r"\bwho (won|is the president)\b",
]


def is_offtopic(text: str) -> bool:
    lowered = text.lower()
    return any(re.search(p, lowered) for p in _OFFTOPIC_PATTERNS)


def _usage_key(user_id: str, day: date) -> str:
    return f"ai_usage:{user_id}:{day.isoformat()}"


def check_and_increment_usage(user_id: str, plan: str) -> tuple[bool, int, int]:
    limit = settings.AI_PRO_TIER_DAILY_LIMIT if plan == "pro" else settings.AI_FREE_TIER_DAILY_LIMIT
    key = _usage_key(user_id, date.today())
    try:
        current = int(_redis.get(key) or 0)
        if current >= limit:
            return False, current, limit
        pipe = _redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, 60 * 60 * 26)
        pipe.execute()
        return True, current + 1, limit
    except redis.exceptions.ConnectionError:
        # Redis down: fail open in dev (no local Redis is a supported dev
        # setup), fail closed in production where the quota must hold.
        if settings.APP_ENV == "development":
            return True, 0, limit
        raise


def build_system_prompt(personality: str) -> str:
    spec = PERSONALITIES.get(personality, PERSONALITIES["roast"])["spec"]
    return (
        "Tum PaisaEra ke AI financial companion ho, ek Indian user ke liye. "
        "HAMESHA sirf Hinglish (Hindi + English mix) mein jawab do — kabhi bhi pure "
        "English mein mat likho. 30 shabdon se kam mein, plain text (no markdown). "
        f"{spec} "
        "Sirf personal finance topics pe baat karo: kharcha, budget, saving, goals, debt, "
        "financial education. Agar user kisi action ka zikar kare (expense log karna, goal "
        "update karna, savings calculate karna), available tools use karo instead of sirf text mein jawab dena. "
        "Agar koi unrelated cheez pooche, politely finance pe wapas le aao, ek line mein, apni voice mein."
    )


def _resolve_model() -> str:
    return settings.AI_DEFAULT_MODEL


def _resolve_api_key() -> Optional[str]:
    provider = settings.AI_DEFAULT_PROVIDER
    if provider == "openai":
        return settings.OPENAI_API_KEY or None
    if provider == "gemini":
        return settings.GEMINI_API_KEY or None
    if provider == "openrouter":
        return settings.OPENROUTER_API_KEY or None
    return None


async def generate_response(
    user_text: str,
    personality: str,
    user_id: str,
    db: DBSession,
    plan: str = "free",
) -> dict:
    """
    Returns:
      { "text": str, "source": "llm"|"template"|"blocked"|"capped",
        "personality": str, "tool_card": dict|None }

    `db` is now required — tool execution needs a session to write
    expenses/update goals. Every call site (chat router) must pass one.
    """
    personality = personality if personality in PERSONALITIES else "roast"

    if is_offtopic(user_text):
        return {"text": OFFTOPIC_REDIRECT[personality], "source": "blocked", "personality": personality, "tool_card": None}

    allowed, used, limit = check_and_increment_usage(user_id, plan)
    if not allowed:
        import random
        return {
            "text": random.choice(TEMPLATE_BANK[personality]),
            "source": "capped",
            "personality": personality,
            "tool_card": None,
            "usage": {"used": used, "limit": limit},
        }

    if not settings.ai_providers_configured:
        import random
        return {"text": random.choice(TEMPLATE_BANK[personality]), "source": "template", "personality": personality, "tool_card": None}

    try:
        system_prompt = build_system_prompt(personality)
        response = await litellm.acompletion(
            model=_resolve_model(),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            tools=get_tool_schemas_for_provider(),
            max_tokens=settings.AI_MAX_RESPONSE_TOKENS,
            api_key=_resolve_api_key(),
        )
        message = response["choices"][0]["message"]
        tool_calls = message.get("tool_calls")

        tool_card = None
        if tool_calls:
            # Execute the first tool call — multi-tool-call turns are a
            # possible future extension, kept single for now for
            # simplicity and predictability of the response shape.
            call = tool_calls[0]
            tool_name = call["function"]["name"]
            arguments = json.loads(call["function"]["arguments"])
            tool_card = execute_tool(tool_name, user_id, db, arguments)

            # Ask the model for a short natural-language confirmation of
            # what it just did, so the chat still reads like a
            # conversation rather than a bare JSON blob.
            follow_up = await litellm.acompletion(
                model=_resolve_model(),
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_text},
                    {"role": "assistant", "content": None, "tool_calls": tool_calls},
                    {"role": "tool", "tool_call_id": call["id"], "content": json.dumps(tool_card)},
                ],
                max_tokens=settings.AI_MAX_RESPONSE_TOKENS,
                api_key=_resolve_api_key(),
            )
            text = follow_up["choices"][0]["message"]["content"].strip()
        else:
            text = (message.get("content") or "").strip()

        if not text and not tool_card:
            raise ValueError("empty response")

        return {
            "text": text or "Ho gaya! ✅",
            "source": "llm",
            "personality": personality,
            "tool_card": tool_card,
        }
    except Exception:
        import random
        return {
            "text": random.choice(TEMPLATE_BANK[personality]),
            "source": "template",
            "personality": personality,
            "tool_card": None,
        }
