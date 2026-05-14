"""Phase 0: root SDLC agent config drives target repo selection."""

from __future__ import annotations

import os
from pathlib import Path

from sdlc_agent.config import (
    RootAgentConfig,
    load_root_agent_config,
    parse_github_repo_url,
)


def test_parse_github_repo_url_derives_owner_and_repository() -> None:
    parsed = parse_github_repo_url(
        "https://github.com/madeehrehman/sdlc_agent_tictactoe"
    )

    assert parsed.owner == "madeehrehman"
    assert parsed.repository == "sdlc_agent_tictactoe"


def test_parse_github_repo_url_accepts_dot_git_suffix() -> None:
    parsed = parse_github_repo_url(
        "https://github.com/madeehrehman/sdlc_agent_tictactoe.git"
    )

    assert parsed.owner == "madeehrehman"
    assert parsed.repository == "sdlc_agent_tictactoe"


def test_root_agent_config_loads_minimal_yaml_and_derives_project_name(
    tmp_path: Path,
) -> None:
    cfg_path = tmp_path / "sdlc-agent.yaml"
    cfg_path.write_text(
        "target:\n"
        "  repo_url: https://github.com/madeehrehman/sdlc_agent_tictactoe\n"
        "  specs_path: spec.md\n",
        encoding="utf-8",
    )

    cfg = RootAgentConfig.from_yaml(cfg_path)

    assert cfg.target.repo_url == "https://github.com/madeehrehman/sdlc_agent_tictactoe"
    assert cfg.target.owner == "madeehrehman"
    assert cfg.target.repository == "sdlc_agent_tictactoe"
    assert cfg.target.project_name == "sdlc_agent_tictactoe"
    assert cfg.target.specs_path == "spec.md"
    assert cfg.github.lifecycle_client == "mcp"
    assert cfg.model.roles.developer == "gpt-4.1"


def test_root_agent_config_can_create_target_deepagent_config(tmp_path: Path) -> None:
    cfg = RootAgentConfig.from_yaml(
        tmp_path / "missing.yaml",
        data={
            "target": {
                "repo_url": "https://github.com/madeehrehman/sdlc_agent_tictactoe",
                "specs_path": "spec.md",
            }
        },
    )
    target_repo = tmp_path / "target"
    target_repo.mkdir()

    deepagent = cfg.to_deepagent_config(target_repo)

    assert deepagent.project.repo_root == target_repo.resolve()
    assert deepagent.github.repo_url == cfg.target.repo_url
    assert deepagent.github.owner == "madeehrehman"
    assert deepagent.github.repository == "sdlc_agent_tictactoe"
    assert deepagent.github.project_name == "sdlc_agent_tictactoe"
    assert deepagent.github.specs_path == "spec.md"


def test_target_project_name_override_wins_over_repo_default(tmp_path: Path) -> None:
    cfg = RootAgentConfig.from_yaml(
        tmp_path / "missing.yaml",
        data={
            "target": {
                "repo_url": "https://github.com/madeehrehman/sdlc_agent_tictactoe",
                "project_name": "custom-project-board",
            }
        },
    )
    target_repo = tmp_path / "target"
    target_repo.mkdir()

    deepagent = cfg.to_deepagent_config(target_repo)

    assert deepagent.github.project_name == "custom-project-board"


def test_root_model_roles_are_preserved_in_target_config(tmp_path: Path) -> None:
    cfg = RootAgentConfig.from_yaml(
        tmp_path / "missing.yaml",
        data={
            "target": {
                "repo_url": "https://github.com/madeehrehman/sdlc_agent_tictactoe",
            },
            "model": {
                "default": "gpt-4o-mini",
                "roles": {
                    "orchestrator": "gpt-4.1",
                    "backlog_analyzer": "gpt-4.1",
                    "developer": "gpt-4.1",
                    "pr_reviewer": "gpt-4.1",
                },
            },
        },
    )
    target_repo = tmp_path / "target"
    target_repo.mkdir()

    deepagent = cfg.to_deepagent_config(target_repo)

    assert deepagent.model.name == "gpt-4o-mini"
    assert deepagent.model.roles.orchestrator == "gpt-4.1"
    assert deepagent.model.roles.backlog_analyzer == "gpt-4.1"
    assert deepagent.model.roles.developer == "gpt-4.1"
    assert deepagent.model.roles.pr_reviewer == "gpt-4.1"


def test_load_root_agent_config_loads_env_before_yaml(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    cfg_path = tmp_path / "sdlc-agent.yaml"
    env_path = tmp_path / ".env"
    cfg_path.write_text(
        "target:\n"
        "  repo_url: https://github.com/madeehrehman/sdlc_agent_tictactoe\n",
        encoding="utf-8",
    )
    env_path.write_text("GITHUB_TOKEN=token-from-env-file\n", encoding="utf-8")

    cfg = load_root_agent_config(cfg_path, env_path=env_path)

    assert cfg.target.repository == "sdlc_agent_tictactoe"
    assert os.environ["GITHUB_TOKEN"] == "token-from-env-file"
