"""Phase 0: OpenAI clients are routed by configured agent role."""

from __future__ import annotations

from sdlc_agent.config import ModelConfig, RoleModelConfig
from sdlc_agent.contracts import SubagentName
from sdlc_agent.llm.factory import build_role_openai_clients, model_for_role


def test_model_for_role_uses_configured_role_models() -> None:
    config = ModelConfig(
        name="gpt-4o-mini",
        roles=RoleModelConfig(
            orchestrator="gpt-4.1",
            backlog_analyzer="gpt-4.1-backlog",
            developer="gpt-4.1-developer",
            pr_reviewer="gpt-4.1-reviewer",
        ),
    )

    assert model_for_role(config, "orchestrator") == "gpt-4.1"
    assert model_for_role(config, SubagentName.BACKLOG_ANALYZER) == "gpt-4.1-backlog"
    assert model_for_role(config, SubagentName.DEVELOPER) == "gpt-4.1-developer"
    assert model_for_role(config, SubagentName.PR_REVIEWER) == "gpt-4.1-reviewer"


def test_model_for_unknown_role_falls_back_to_default_model() -> None:
    assert model_for_role(ModelConfig(name="gpt-4o-mini"), "unknown") == "gpt-4o-mini"


def test_build_role_openai_clients_passes_explicit_models_and_api_key() -> None:
    created: list[dict] = []

    class FakeOpenAIClient:
        def __init__(self, **kwargs) -> None:
            self.model = kwargs["model"]
            created.append(kwargs)

    config = ModelConfig(
        name="gpt-default",
        temperature=0.2,
        roles=RoleModelConfig(
            orchestrator="gpt-orchestrator",
            backlog_analyzer="gpt-backlog",
            developer="gpt-developer",
            pr_reviewer="gpt-reviewer",
        ),
    )

    clients = build_role_openai_clients(
        config,
        api_key="sk-test",
        client_factory=FakeOpenAIClient,
    )

    assert clients["orchestrator"].model == "gpt-orchestrator"
    assert clients[SubagentName.BACKLOG_ANALYZER].model == "gpt-backlog"
    assert clients[SubagentName.DEVELOPER].model == "gpt-developer"
    assert clients[SubagentName.PR_REVIEWER].model == "gpt-reviewer"
    assert {entry["api_key"] for entry in created} == {"sk-test"}
    assert {entry["temperature"] for entry in created} == {0.2}
