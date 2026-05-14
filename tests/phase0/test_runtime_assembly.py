"""Phase 0: root startup config assembles runtime clients and orchestrator."""

from __future__ import annotations

from pathlib import Path

from sdlc_agent.contracts import SubagentName
from sdlc_agent.mcp.github import FixtureGitHubProject
from sdlc_agent.runtime import build_sdlc_runtime
from sdlc_agent.subagents import BacklogAnalyzer, DeveloperTester, PRReviewer


class FakeOpenAIClient:
    def __init__(self, **kwargs) -> None:
        self.model = kwargs["model"]
        self.api_key = kwargs["api_key"]
        self.temperature = kwargs["temperature"]


def test_build_sdlc_runtime_persists_target_config_and_wires_registry(tmp_path: Path) -> None:
    target_repo = tmp_path / "target"
    target_repo.mkdir()
    cfg_path = tmp_path / "sdlc-agent.yaml"
    env_path = tmp_path / ".env"
    env_path.write_text("OPENAI_API_KEY=sk-runtime\n", encoding="utf-8")
    cfg_path.write_text(
        "target:\n"
        "  repo_url: https://github.com/madeehrehman/sdlc_agent_tictactoe\n"
        "  specs_path: spec.md\n"
        "github:\n"
        "  lifecycle_client: fixture\n"
        "model:\n"
        "  default: gpt-default\n"
        "  roles:\n"
        "    orchestrator: gpt-orchestrator\n"
        "    backlog_analyzer: gpt-backlog\n"
        "    developer: gpt-developer\n"
        "    pr_reviewer: gpt-reviewer\n",
        encoding="utf-8",
    )

    runtime = build_sdlc_runtime(
        root_config_path=cfg_path,
        env_path=env_path,
        target_repo_root=target_repo,
        openai_client_factory=FakeOpenAIClient,
    )

    assert runtime.paths.config_yaml.is_file()
    assert runtime.config.github.lifecycle_client == "fixture"
    assert isinstance(runtime.github, FixtureGitHubProject)
    assert isinstance(runtime.registry[SubagentName.BACKLOG_ANALYZER], BacklogAnalyzer)
    assert isinstance(runtime.registry[SubagentName.DEVELOPER], DeveloperTester)
    assert isinstance(runtime.registry[SubagentName.PR_REVIEWER], PRReviewer)
    assert runtime.registry[SubagentName.BACKLOG_ANALYZER].llm.model == "gpt-backlog"
    assert runtime.registry[SubagentName.DEVELOPER].llm.model == "gpt-developer"
    assert runtime.registry[SubagentName.PR_REVIEWER].llm.model == "gpt-reviewer"
    assert runtime.llm_clients["orchestrator"].model == "gpt-orchestrator"
    assert runtime.orchestrator.github is runtime.github


def test_build_sdlc_runtime_closes_github_client_if_later_assembly_fails(
    tmp_path: Path,
) -> None:
    target_repo = tmp_path / "target"
    target_repo.mkdir()
    cfg_path = tmp_path / "sdlc-agent.yaml"
    env_path = tmp_path / ".env"
    env_path.write_text("OPENAI_API_KEY=sk-runtime\n", encoding="utf-8")
    cfg_path.write_text(
        "target:\n"
        "  repo_url: https://github.com/madeehrehman/sdlc_agent_tictactoe\n"
        "github:\n"
        "  lifecycle_client: fixture\n",
        encoding="utf-8",
    )

    class ClosableGitHub(FixtureGitHubProject):
        closed = False

        def close(self) -> None:
            self.closed = True

    github = ClosableGitHub(repo_root=target_repo)

    def failing_openai_factory(**_kwargs):
        raise RuntimeError("openai unavailable")

    import pytest

    with pytest.raises(RuntimeError, match="openai unavailable"):
        build_sdlc_runtime(
            root_config_path=cfg_path,
            env_path=env_path,
            target_repo_root=target_repo,
            github_client_factory=lambda _config: github,
            openai_client_factory=failing_openai_factory,
        )

    assert github.closed is True
