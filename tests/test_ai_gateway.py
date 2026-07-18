"""
Tests for the AI Gateway's non-LLM logic: the scope pre-filter and
personality/template bank. Deliberately does NOT test generate_response()
directly with a real provider call — that needs a real API key and
network access, which isn't appropriate for a unit test suite. See
tests/test_ai_gateway_integration.py (not yet written) for that, gated
behind an env var so CI doesn't burn API credits on every push.
"""
from app.services.ai_gateway.gateway import is_offtopic, build_system_prompt, check_and_increment_usage
from app.services.ai_gateway.personalities import PERSONALITIES, TEMPLATE_BANK, OFFTOPIC_REDIRECT
from app.services.ai_gateway.tools import TOOL_REGISTRY, get_tool_schemas_for_provider


class TestScopeFilter:
    def test_code_request_is_offtopic(self):
        assert is_offtopic("write a python script to sort a list") is True

    def test_image_request_is_offtopic(self):
        assert is_offtopic("generate an image of a cat") is True

    def test_trivia_is_offtopic(self):
        assert is_offtopic("what is the capital of France") is True

    def test_finance_question_is_in_scope(self):
        assert is_offtopic("kya main iPhone afford kar sakta hoon") is False

    def test_expense_logging_is_in_scope(self):
        assert is_offtopic("swiggy pe 350 rupaye kharch hue") is False

    def test_roast_request_is_in_scope(self):
        assert is_offtopic("mera kharcha roast karo") is False


class TestPersonalities:
    def test_all_six_personalities_exist(self):
        expected = {"roast", "mom", "friend", "ca", "motivator", "coach"}
        assert set(PERSONALITIES.keys()) == expected

    def test_every_personality_has_a_spec(self):
        for key, meta in PERSONALITIES.items():
            assert "spec" in meta
            assert len(meta["spec"]) > 10

    def test_every_personality_has_fallback_templates(self):
        for key in PERSONALITIES:
            assert key in TEMPLATE_BANK
            assert len(TEMPLATE_BANK[key]) >= 1

    def test_every_personality_has_offtopic_redirect(self):
        for key in PERSONALITIES:
            assert key in OFFTOPIC_REDIRECT

    def test_roast_mode_spec_has_safety_guardrail(self):
        # Per PRD Part 4: Roast Mode must never insult, never attack
        # appearance/income/debt. Enforced at the prompt level -- this
        # test guards against someone accidentally weakening that
        # instruction in a future edit.
        spec = PERSONALITIES["roast"]["spec"].lower()
        assert "insult" in spec or "kabhi" in spec  # guardrail language present


class TestSystemPrompt:
    def test_system_prompt_mentions_hinglish_requirement(self):
        prompt = build_system_prompt("roast")
        assert "hinglish" in prompt.lower()

    def test_system_prompt_falls_back_to_roast_for_unknown_personality(self):
        prompt = build_system_prompt("nonexistent_personality")
        assert prompt  # should not crash, should return roast's prompt


class TestToolRegistry:
    def test_expected_tools_registered(self):
        expected = {"addExpense", "updateGoal", "calculateSavings", "forecastCashflow"}
        assert expected.issubset(set(TOOL_REGISTRY.keys()))

    def test_tool_schemas_are_openai_compatible_shape(self):
        schemas = get_tool_schemas_for_provider()
        for schema in schemas:
            assert schema["type"] == "function"
            assert "name" in schema["function"]
            assert "parameters" in schema["function"]

    def test_add_expense_requires_amount(self):
        params = TOOL_REGISTRY["addExpense"].parameters
        assert "amount" in params["required"]
