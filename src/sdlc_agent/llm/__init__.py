"""LLM client wrappers. Only OpenAI/ChatGPT is wired in Phase 0."""

from sdlc_agent.llm.factory import (
    ORCHESTRATOR_ROLE,
    build_role_openai_clients,
    model_for_role,
)
from sdlc_agent.llm.openai_client import OpenAIClient

__all__ = [
    "ORCHESTRATOR_ROLE",
    "OpenAIClient",
    "build_role_openai_clients",
    "model_for_role",
]
