"""Public surface of the AI Gateway package — routers import from here."""
from app.services.ai_gateway.gateway import generate_response, build_system_prompt, is_offtopic
from app.services.ai_gateway.personalities import PERSONALITIES, TEMPLATE_BANK
from app.services.ai_gateway.tools import TOOL_REGISTRY, execute_tool, get_tool_schemas_for_provider
from app.services.ai_gateway.orchestrator import run_orchestrated_chat

__all__ = [
    "generate_response", "build_system_prompt", "is_offtopic",
    "PERSONALITIES", "TEMPLATE_BANK",
    "TOOL_REGISTRY", "execute_tool", "get_tool_schemas_for_provider",
    "run_orchestrated_chat",
]
