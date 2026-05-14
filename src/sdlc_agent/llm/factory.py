"""Role-based OpenAI client construction."""

from __future__ import annotations

import os
from typing import Any, Callable

from sdlc_agent.config import ModelConfig
from sdlc_agent.contracts import SubagentName
from sdlc_agent.llm.openai_client import OpenAIClient


ORCHESTRATOR_ROLE = "orchestrator"


def model_for_role(config: ModelConfig, role: SubagentName | str) -> str:
    role_name = str(role)
    if role_name == ORCHESTRATOR_ROLE:
        return config.roles.orchestrator
    if role_name == SubagentName.BACKLOG_ANALYZER:
        return config.roles.backlog_analyzer
    if role_name == SubagentName.DEVELOPER:
        return config.roles.developer
    if role_name == SubagentName.PR_REVIEWER:
        return config.roles.pr_reviewer
    return config.name


def build_role_openai_clients(
    config: ModelConfig,
    *,
    api_key: str | None = None,
    client_factory: Callable[..., Any] = OpenAIClient,
) -> dict[SubagentName | str, Any]:
    resolved_key = api_key or os.environ.get("OPENAI_API_KEY")
    roles: list[SubagentName | str] = [
        ORCHESTRATOR_ROLE,
        SubagentName.BACKLOG_ANALYZER,
        SubagentName.DEVELOPER,
        SubagentName.PR_REVIEWER,
    ]
    return {
        role: client_factory(
            model=model_for_role(config, role),
            api_key=resolved_key,
            temperature=config.temperature,
        )
        for role in roles
    }
