"""
Pydantic schemas — the actual OpenAPI contract. Previously several routers
defined their request/response models inline; moving them here means
`openapi-typescript` generates a stable, well-named set of TypeScript
types instead of anonymous inline schemas, and the mobile app's
src/types/index.ts can eventually be deleted in favor of the generated
file (see scripts/generate_openapi.py and the mobile repo's
package.json "generate:types" script).
"""
from datetime import datetime, date
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, Field, ConfigDict
from pydantic.alias_generators import to_camel


class CamelResponseModel(BaseModel):
    """
    Base for every *Response* schema. Serializes fields as camelCase on the
    wire (e.g. `target_amount` -> `targetAmount`), matching the mobile
    app's hand-written TS types in src/types/index.ts — this is exactly
    the kind of backend/mobile drift the OpenAPI generation pipeline
    (scripts/generate_openapi.py) exists to catch; this fix was made after
    actually regenerating types and comparing them against src/types/index.ts,
    not assumed.

    Request bodies (Create/Update/Body schemas) deliberately stay
    snake_case — they match what app/services/api/*.ts already sends, and
    changing that side isn't necessary.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)
class RequestOTPBody(BaseModel):
    mobile_number: str = Field(..., pattern=r"^\+?\d{10,15}$")


class VerifyOTPBody(BaseModel):
    mobile_number: str
    code: str
    device_id: Optional[str] = None
    device_name: Optional[str] = None


class OTPVerifyResponse(CamelResponseModel):
    access_token: str
    refresh_token: str
    is_new_user: bool
    user_id: str
    onboarding_completed: bool


# ---------- Chat ----------
Personality = Literal["roast", "mom", "friend", "ca", "motivator", "coach"]
MessageSource = Literal["llm", "template", "blocked", "capped"]


class ChatMessageBody(BaseModel):
    text: str
    personality: Optional[Personality] = None
    conversation_id: Optional[str] = None


class ToolCard(CamelResponseModel):
    type: str
    data: dict


class ChatMessageResponse(CamelResponseModel):
    conversation_id: str
    text: str
    source: MessageSource
    personality: Personality
    tool_card: Optional[ToolCard] = None


# ---------- Transactions ----------
TransactionSource = Literal["manual", "quick_add", "chat_parsed", "sms_parsed", "voice_parsed"]
TransactionDirection = Literal["debit", "credit"]


class TransactionCreate(BaseModel):
    merchant_name: str
    amount: Decimal
    category: Optional[str] = None
    direction: TransactionDirection = "debit"
    source: TransactionSource = "manual"


class TransactionResponse(CamelResponseModel):
    id: str
    # None happens legitimately: SMS-imported rows where the parser could
    # extract amount/direction but no recognizable merchant string.
    merchant_name: Optional[str] = None
    amount: Decimal
    direction: TransactionDirection
    category: Optional[str] = None
    source: TransactionSource
    transaction_ts: datetime

    class Config:
        from_attributes = True


class VoiceEntryBody(BaseModel):
    transcript: str


# ---------- Goals ----------
GoalStatus = Literal["active", "completed", "abandoned"]


class GoalCreate(BaseModel):
    name: str
    emoji: Optional[str] = None
    target_amount: Decimal
    target_date: Optional[date] = None


class GoalUpdate(BaseModel):
    current_amount: Optional[Decimal] = None
    status: Optional[GoalStatus] = None


class GoalResponse(CamelResponseModel):
    id: str
    name: str
    emoji: Optional[str] = None
    target_amount: Decimal
    current_amount: Decimal
    target_date: Optional[date] = None
    status: GoalStatus

    class Config:
        from_attributes = True


# ---------- Money Score / Money DNA ----------
class ScoreHistoryPoint(CamelResponseModel):
    score: int
    recorded_at: datetime


class ScoreComponentDetail(CamelResponseModel):
    component: str
    points: int
    max_points: int
    reason: str


class MoneyScoreResponse(CamelResponseModel):
    current_score: int
    level: str
    history: list[ScoreHistoryPoint]
    components: list[ScoreComponentDetail]


class MoneyDNABreakdownItem(CamelResponseModel):
    label: str
    pct: int


class MoneyDNAResponse(CamelResponseModel):
    archetype: str
    breakdown: list[MoneyDNABreakdownItem]
