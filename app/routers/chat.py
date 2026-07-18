import random

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DBSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.models.intelligence import AIConversation, AIMessage
from app.services.ai_gateway import PERSONALITIES, TEMPLATE_BANK
from app.services.ai_gateway.gateway import is_offtopic, check_and_increment_usage
from app.services.ai_gateway.personalities import OFFTOPIC_REDIRECT
from app.services.ai_gateway.orchestrator import run_orchestrated_chat
from app.schemas.api import ChatMessageBody, ChatMessageResponse, ToolCard

router = APIRouter(prefix="/chat", tags=["chat"])


@router.get("/personalities")
def list_personalities():
    return {key: {"label": v["label"]} for key, v in PERSONALITIES.items()}


@router.get("/history")
def get_history(
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Latest conversation + its messages, for rehydrating the chat screen
    on app restart instead of starting a fresh conversation every launch."""
    conversation = (
        db.query(AIConversation)
        .filter(AIConversation.user_id == user.id)
        .order_by(AIConversation.started_at.desc())
        .first()
    )
    if not conversation:
        return {"conversation_id": None, "messages": []}

    messages = (
        db.query(AIMessage)
        .filter(AIMessage.conversation_id == conversation.id)
        .order_by(AIMessage.created_at.asc())
        .limit(50)
        .all()
    )
    return {
        "conversation_id": conversation.id,
        "personality": conversation.personality,
        "messages": [
            {
                "id": m.id,
                "sender": m.sender,
                "text": m.text,
                "source": m.model_used,
                "tool_card": m.explanation,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ],
    }


@router.post("/message", response_model=ChatMessageResponse)
async def send_message(
    body: ChatMessageBody,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    personality = body.personality or user.ai_personality or "roast"

    conversation = None
    if body.conversation_id:
        conversation = (
            db.query(AIConversation)
            .filter(AIConversation.id == body.conversation_id, AIConversation.user_id == user.id)
            .first()
        )
    if not conversation:
        conversation = AIConversation(user_id=user.id, personality=personality)
        db.add(conversation)
        db.commit()
        db.refresh(conversation)

    # Snapshot recent history BEFORE storing the new user message, so the
    # LLM sees prior turns + exactly one copy of the current message.
    history_rows = (
        db.query(AIMessage)
        .filter(AIMessage.conversation_id == conversation.id)
        .order_by(AIMessage.created_at.desc())
        .limit(12)
        .all()
    )
    history = [
        {"role": "user" if m.sender == "user" else "assistant", "content": m.text}
        for m in reversed(history_rows)
    ]

    db.add(AIMessage(conversation_id=conversation.id, sender="user", text=body.text))
    db.commit()

    # Governance (scope filter + rate limit) lives HERE, in the caller --
    # per the explicit contract documented in orchestrator.py's
    # run_orchestrated_chat docstring, so there's exactly one place these
    # rules are enforced regardless of which execution path (simple vs.
    # orchestrated) ends up handling the request.
    tool_card = None
    if is_offtopic(body.text):
        text, source = OFFTOPIC_REDIRECT[personality], "blocked"
    else:
        allowed, _used, _limit = check_and_increment_usage(user.id, user.plan)
        if not allowed:
            text, source = random.choice(TEMPLATE_BANK[personality]), "capped"
        else:
            # Real multi-step orchestration (LangGraph) -- can chain
            # tools (e.g. addExpense -> checkBudgetStatus) in one turn,
            # not just a single tool call. See
            # app/services/ai_gateway/orchestrator.py.
            result = await run_orchestrated_chat(
                user_text=body.text, personality=personality, user_id=user.id, db=db, history=history
            )
            text, source = result["text"], result["source"]
            tool_card = result["tool_cards"][-1] if result["tool_cards"] else None

    ai_message = AIMessage(
        conversation_id=conversation.id,
        sender="assistant",
        text=text,
        model_used=source,
        explanation=tool_card,
    )
    db.add(ai_message)
    db.commit()

    return ChatMessageResponse(
        conversation_id=conversation.id,
        text=text,
        source=source,
        personality=personality,
        tool_card=ToolCard(**tool_card) if tool_card else None,
    )
