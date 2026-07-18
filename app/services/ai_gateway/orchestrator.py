"""
AI Orchestrator — real multi-step tool-call chaining via LangGraph, per
the original tech stack's promise (1_Product_Vision.md / 4_tech_stack.md
named LangGraph explicitly). This supersedes the two-turn "call -> execute
-> confirm" pattern in gateway.py's generate_response() for requests that
may need to CHAIN tools -- e.g. "swiggy pe 350 kharch hue, aur bata do
kya main budget ke andar hoon" needs addExpense THEN a budget check, not
just one tool call.

generate_response() in gateway.py remains the fast path for simple
single-turn chat (still used for the common case: plain conversation,
single expense log) since it's cheaper (fewer LLM round-trips) and
simpler to reason about. This orchestrator is the escalation path when
the model itself decides multiple tool calls are needed -- LangGraph's
loop handles that decision, not a hardcoded rule about which requests
"need" orchestration.

Graph shape:

    ┌──────┐  no tool call   ┌──────────┐
    │ think ├────────────────▶ respond  ├──▶ END
    └───┬──┘                 └──────────┘
        │ tool call
        ▼
  ┌─────────────┐
  │ execute_tool │──▶ back to think (loop, capped at MAX_ITERATIONS)
  └─────────────┘
"""
import json
import logging
from typing import Annotated, TypedDict

import litellm
from langgraph.graph import StateGraph, END
from sqlalchemy.orm import Session as DBSession

from app.core.config import settings
from app.services.ai_gateway.personalities import PERSONALITIES
from app.services.ai_gateway.tools import get_tool_schemas_for_provider, execute_tool
from app.services.ai_gateway.gateway import build_system_prompt, _resolve_model, _resolve_api_key

logger = logging.getLogger("paisaera.orchestrator")

MAX_ITERATIONS = 3  # hard cap -- prevents a runaway tool-call loop from
                     # burning provider spend or looping forever if the
                     # model keeps calling tools without ever responding.
MAX_TOOL_RETRIES = 1  # a failed tool call gets one retry with the error
                       # fed back to the model, then the graph gives up
                       # and asks the model to respond with what it has.


def _add_messages(left: list, right: list) -> list:
    return left + right


class OrchestratorState(TypedDict):
    messages: Annotated[list[dict], _add_messages]
    user_id: str
    personality: str
    iterations: int
    tool_cards: list[dict]
    final_text: str | None
    db: DBSession  # not serialized/logged -- see _redact_state_for_logging


def _redact_state_for_logging(state: OrchestratorState) -> dict:
    """DB sessions and full message history aren't safe/useful to log
    verbatim -- this is what actually gets written to the logger."""
    return {
        "user_id": state["user_id"],
        "personality": state["personality"],
        "iterations": state["iterations"],
        "tool_cards_so_far": len(state["tool_cards"]),
    }


async def _think_node(state: OrchestratorState) -> dict:
    logger.info(f"orchestrator: think (iteration {state['iterations']}) {_redact_state_for_logging(state)}")

    if state["iterations"] >= MAX_ITERATIONS:
        # Force a response rather than looping again -- the model gets
        # told explicitly why, so its final answer acknowledges the cutoff
        # instead of silently truncating mid-thought.
        return {
            "messages": [
                {"role": "system", "content": "Tool call limit reached. Ab jo pata hai usi se short jawab do."}
            ]
        }

    response = await litellm.acompletion(
        model=_resolve_model(),
        messages=state["messages"],
        tools=get_tool_schemas_for_provider(),
        max_tokens=settings.AI_MAX_RESPONSE_TOKENS,
        api_key=_resolve_api_key(),
    )
    message = response["choices"][0]["message"]

    new_message = {"role": "assistant", "content": message.get("content")}
    if message.get("tool_calls"):
        new_message["tool_calls"] = message["tool_calls"]

    return {"messages": [new_message], "iterations": state["iterations"] + 1}


def _has_pending_tool_call(state: OrchestratorState) -> str:
    last = state["messages"][-1]
    if last.get("role") == "assistant" and last.get("tool_calls"):
        return "execute_tool"
    return "respond"


async def _execute_tool_node(state: OrchestratorState) -> dict:
    last = state["messages"][-1]
    tool_calls = last.get("tool_calls", [])
    new_messages = []
    tool_cards = []

    for call in tool_calls:
        tool_name = call["function"]["name"]
        try:
            arguments = json.loads(call["function"]["arguments"])
        except json.JSONDecodeError:
            arguments = {}

        result = None
        last_error = None
        for attempt in range(MAX_TOOL_RETRIES + 1):
            try:
                result = execute_tool(tool_name, state["user_id"], state["db"], arguments)
                break
            except Exception as e:  # noqa: BLE001 -- tool handlers can raise anything
                last_error = e
                logger.warning(f"orchestrator: tool {tool_name} failed (attempt {attempt + 1}): {e}")

        if result is None:
            result = {"type": "error", "data": {"message": f"{tool_name} failed: {last_error}"}}

        tool_cards.append(result)
        new_messages.append(
            {"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result)}
        )

    return {"messages": new_messages, "tool_cards": state["tool_cards"] + tool_cards}


async def _respond_node(state: OrchestratorState) -> dict:
    last = state["messages"][-1]
    # If the last message is already a plain assistant response with no
    # pending tool call, use it directly rather than spending another
    # provider call restating the same thing.
    if last.get("role") == "assistant" and last.get("content") and not last.get("tool_calls"):
        return {"final_text": last["content"].strip()}

    response = await litellm.acompletion(
        model=_resolve_model(),
        messages=state["messages"],
        max_tokens=settings.AI_MAX_RESPONSE_TOKENS,
        api_key=_resolve_api_key(),
    )
    text = response["choices"][0]["message"]["content"]
    return {"final_text": (text or "Ho gaya! ✅").strip()}


_graph = StateGraph(OrchestratorState)
_graph.add_node("think", _think_node)
_graph.add_node("execute_tool", _execute_tool_node)
_graph.add_node("respond", _respond_node)
_graph.set_entry_point("think")
_graph.add_conditional_edges("think", _has_pending_tool_call, {"execute_tool": "execute_tool", "respond": "respond"})
_graph.add_edge("execute_tool", "think")
_graph.add_edge("respond", END)

compiled_orchestrator = _graph.compile()


async def run_orchestrated_chat(
    user_text: str,
    personality: str,
    user_id: str,
    db: DBSession,
    history: list[dict] | None = None,
) -> dict:
    """
    Public entry point -- use this instead of gateway.generate_response()
    when a request might need multiple chained tool calls. Same governance
    (scope filter, rate limit) should be applied by the CALLER before
    invoking this, exactly as chat.py already does before calling
    generate_response() -- this function intentionally does not duplicate
    that logic, to keep one source of truth for the governance rules.
    """
    personality = personality if personality in PERSONALITIES else "roast"

    # Same no-provider fallback as gateway.generate_response(): without an
    # AI key the graph's "think" node would crash inside litellm, so answer
    # from the static template bank instead of 500ing.
    if not settings.ai_providers_configured:
        import random

        from app.services.ai_gateway.personalities import TEMPLATE_BANK

        return {
            "text": random.choice(TEMPLATE_BANK[personality]),
            "source": "template",
            "personality": personality,
            "tool_cards": [],
            "iterations_used": 0,
        }

    system_prompt = build_system_prompt(personality)

    initial_state: OrchestratorState = {
        "messages": [
            {"role": "system", "content": system_prompt},
            # Prior turns of this conversation (chronological), so the model
            # remembers what the user already told it. Tool-call structures
            # aren't replayed -- history is plain user/assistant text.
            *(history or []),
            {"role": "user", "content": user_text},
        ],
        "user_id": user_id,
        "personality": personality,
        "iterations": 0,
        "tool_cards": [],
        "final_text": None,
        "db": db,
    }

    final_state = await compiled_orchestrator.ainvoke(initial_state)

    return {
        "text": final_state["final_text"] or "Ho gaya! ✅",
        "source": "llm",
        "personality": personality,
        "tool_cards": final_state["tool_cards"],  # note: plural -- multiple tools may have run
        "iterations_used": final_state["iterations"],
    }
