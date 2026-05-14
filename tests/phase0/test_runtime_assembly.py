"""Phase 0: root startup config assembles runtime clients and orchestrator."""

from __future__ import annotations

import subprocess
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


def _git_init_with_develop(repo: Path) -> None:
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "sdlc@test"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "sdlc"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "branch", "-M", "develop"], cwd=repo, check=True, capture_output=True)


def test_build_sdlc_runtime_uses_worktree_root_for_sandbox_and_reviewer_git(
    tmp_path: Path,
) -> None:
    subprocess.run(["git", "--version"], check=True, capture_output=True)
    target_repo = tmp_path / "target"
    target_repo.mkdir()
    _git_init_with_develop(target_repo)

    from sdlc_agent.mcp.git import LocalGitClient

    wt = tmp_path / "wt"
    LocalGitClient(target_repo).add_worktree(wt, new_branch="b-runtime", start_ref="develop")

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

    runtime = build_sdlc_runtime(
        root_config_path=cfg_path,
        env_path=env_path,
        target_repo_root=target_repo,
        worktree_root=wt,
        openai_client_factory=FakeOpenAIClient,
    )

    assert runtime.paths.repo_root == target_repo.resolve()
    assert runtime.registry[SubagentName.DEVELOPER].sandbox.root == wt.resolve()
    assert runtime.registry[SubagentName.PR_REVIEWER].git.repo_root == wt.resolve()
    runtime.close()


def test_injected_github_client_is_not_closed_by_runtime_close(tmp_path: Path) -> None:
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

    gh = ClosableGitHub(repo_root=target_repo)

    runtime = build_sdlc_runtime(
        root_config_path=cfg_path,
        env_path=env_path,
        target_repo_root=target_repo,
        github=gh,
        openai_client_factory=FakeOpenAIClient,
    )
    runtime.close()
    assert gh.closed is False
    gh.close()
    assert gh.closed is True
