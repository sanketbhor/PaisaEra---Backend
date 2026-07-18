"""
Tests for the LangGraph orchestrator. LLM calls are mocked -- these tests
verify the GRAPH LOGIC (does it loop correctly, does it stop at the
iteration cap, does it call the right tool) rather than real model
behavior, which would need a live API key and isn't appropriate for a
unit test. Real end-to-end behavior with an actual provider is something
to verify manually against a staging API key before launch, not something
this suite claims to cover.
"""
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from app.services.ai_gateway.orchestrator import (
    compiled_orchestrator,
    MAX_ITERATIONS,
    _has_pending_tool_call,
)


def _mock_llm_response(content=None, tool_calls=None):
    """Builds a fake litellm.acompletion() return shape."""
    message = {"content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {"choices": [{"message": message}]}


def _mock_tool_call(call_id: str, name: str, arguments: dict):
    import json

    return {"id": call_id, "function": {"name": name, "arguments": json.dumps(arguments)}}


class TestRoutingLogic:
    def test_routes_to_execute_tool_when_tool_call_present(self):
        state = {
            "messages": [
                {"role": "assistant", "content": None, "tool_calls": [_mock_tool_call("1", "addExpense", {"amount": 100})]}
            ]
        }
        assert _has_pending_tool_call(state) == "execute_tool"

    def test_routes_to_respond_when_no_tool_call(self):
        state = {"messages": [{"role": "assistant", "content": "Noted!", "tool_calls": None}]}
        assert _has_pending_tool_call(state) == "respond"

    def test_routes_to_respond_when_tool_calls_is_empty_list(self):
        state = {"messages": [{"role": "assistant", "content": "Done", "tool_calls": []}]}
        assert _has_pending_tool_call(state) == "respond"


class TestOrchestratorSingleTurn:
    @pytest.mark.asyncio
    async def test_simple_response_no_tool_call(self):
        """User asks a plain question, model answers directly -- no tool
        call, graph should go think -> respond -> END in one LLM call."""
        with patch("app.services.ai_gateway.orchestrator.litellm.acompletion", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = _mock_llm_response(content="Bhai, thoda bacha le!")

            result = await compiled_orchestrator.ainvoke(
                {
                    "messages": [{"role": "user", "content": "kya main bach raha hoon?"}],
                    "user_id": "test-user",
                    "personality": "roast",
                    "iterations": 0,
                    "tool_cards": [],
                    "final_text": None,
                    "db": MagicMock(),
                }
            )

            assert result["final_text"] == "Bhai, thoda bacha le!"
            assert mock_llm.call_count == 1  # only the think node called the LLM


class TestOrchestratorToolChaining:
    @pytest.mark.asyncio
    async def test_chains_two_tool_calls_across_iterations(self):
        """The core capability this orchestrator exists for: model calls
        addExpense, sees the result, decides to also call
        checkBudgetStatus, THEN responds -- two tool executions in one
        conversational turn."""
        call_sequence = [
            # Iteration 1: model wants to log the expense
            _mock_llm_response(tool_calls=[_mock_tool_call("call1", "addExpense", {"amount": 350, "merchant": "Swiggy"})]),
            # Iteration 2: model, having seen the expense was logged, checks budget
            _mock_llm_response(tool_calls=[_mock_tool_call("call2", "checkBudgetStatus", {})]),
            # Iteration 3: model has both results, responds in plain text
            _mock_llm_response(content="Logged! Aur tu abhi budget ke andar hai."),
        ]

        with patch("app.services.ai_gateway.orchestrator.litellm.acompletion", new_callable=AsyncMock) as mock_llm, \
             patch("app.services.ai_gateway.orchestrator.execute_tool") as mock_execute_tool:
            mock_llm.side_effect = call_sequence
            mock_execute_tool.side_effect = [
                {"type": "transaction", "data": {"merchant": "Swiggy", "amount": 350}},
                {"type": "budgetStatus", "data": {"is_over_any_budget": False}},
            ]

            result = await compiled_orchestrator.ainvoke(
                {
                    "messages": [{"role": "user", "content": "swiggy pe 350 kharch hue, budget ke andar hoon?"}],
                    "user_id": "test-user",
                    "personality": "roast",
                    "iterations": 0,
                    "tool_cards": [],
                    "final_text": None,
                    "db": MagicMock(),
                }
            )

            assert mock_execute_tool.call_count == 2
            assert len(result["tool_cards"]) == 2
            assert result["tool_cards"][0]["type"] == "transaction"
            assert result["tool_cards"][1]["type"] == "budgetStatus"
            assert "Logged" in result["final_text"]

    @pytest.mark.asyncio
    async def test_tool_failure_is_caught_not_raised(self):
        """A tool handler raising an exception should not crash the graph
        -- it should be captured as an error tool_card and the model
        given a chance to respond anyway."""
        with patch("app.services.ai_gateway.orchestrator.litellm.acompletion", new_callable=AsyncMock) as mock_llm, \
             patch("app.services.ai_gateway.orchestrator.execute_tool") as mock_execute_tool:
            mock_llm.side_effect = [
                _mock_llm_response(tool_calls=[_mock_tool_call("call1", "addExpense", {"amount": 100})]),
                _mock_llm_response(content="Kuch gadbad ho gayi, par main try kar raha hoon."),
            ]
            mock_execute_tool.side_effect = Exception("DB connection lost")

            result = await compiled_orchestrator.ainvoke(
                {
                    "messages": [{"role": "user", "content": "100 rupaye kharch hue"}],
                    "user_id": "test-user",
                    "personality": "roast",
                    "iterations": 0,
                    "tool_cards": [],
                    "final_text": None,
                    "db": MagicMock(),
                }
            )

            # Graph completed without raising, error surfaced as a tool_card
            assert result["tool_cards"][0]["type"] == "error"
            assert result["final_text"]


class TestIterationCap:
    @pytest.mark.asyncio
    async def test_stops_at_max_iterations_even_if_model_keeps_calling_tools(self):
        """Guards against a runaway loop -- if the model NEVER stops
        requesting tool calls, the graph must still terminate rather than
        looping forever or burning unbounded provider spend."""
        # Model always wants to call a tool, no matter what
        always_tool_call = _mock_llm_response(tool_calls=[_mock_tool_call("callX", "calculateSavings", {"habit": "swiggy"})])

        with patch("app.services.ai_gateway.orchestrator.litellm.acompletion", new_callable=AsyncMock) as mock_llm, \
             patch("app.services.ai_gateway.orchestrator.execute_tool") as mock_execute_tool:
            mock_llm.return_value = always_tool_call
            mock_execute_tool.return_value = {"type": "whatIf", "data": {"annualImpact": 1000}}

            result = await compiled_orchestrator.ainvoke(
                {
                    "messages": [{"role": "user", "content": "keep calling tools forever"}],
                    "user_id": "test-user",
                    "personality": "roast",
                    "iterations": 0,
                    "tool_cards": [],
                    "final_text": None,
                    "db": MagicMock(),
                },
                config={"recursion_limit": 50},  # generous graph-level cap; MAX_ITERATIONS should bite first
            )

            # The think node itself refuses to call the LLM again past
            # MAX_ITERATIONS -- verify we never exceeded it.
            assert result["iterations"] <= MAX_ITERATIONS
            assert result["final_text"] is not None  # graph terminated with an answer, not a crash
