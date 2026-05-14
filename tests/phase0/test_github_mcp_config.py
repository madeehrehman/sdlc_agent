"""Phase 0: GitHub MCP runtime config stays non-secret and derivable."""

from __future__ import annotations

from pathlib import Path

import yaml

from sdlc_agent.config import RootAgentConfig


def test_root_config_defaults_github_mcp_runtime_fields(tmp_path: Path) -> None:
    cfg = RootAgentConfig.from_yaml(
        tmp_path / "missing.yaml",
        data={
            "target": {
                "repo_url": "https://github.com/madeehrehman/sdlc_agent_tictactoe",
            }
        },
    )

    assert cfg.github.lifecycle_client == "mcp"
    assert cfg.github.mcp.docker_image == "ghcr.io/github/github-mcp-server"
    assert cfg.github.mcp.toolsets == ["repos", "issues", "projects"]
    assert cfg.github.mcp.owner_type == "user"
    assert cfg.github.mcp.status_field_name == "Status"
    assert cfg.github.mcp.timeout_seconds == 30.0


def test_deepagent_config_preserves_github_mcp_runtime_fields(tmp_path: Path) -> None:
    cfg = RootAgentConfig.from_yaml(
        tmp_path / "missing.yaml",
        data={
            "target": {
                "repo_url": "https://github.com/madeehrehman/sdlc_agent_tictactoe",
            },
            "github": {
                "mcp": {
                    "docker_image": "ghcr.io/custom/github-mcp-server:test",
                    "toolsets": ["repos", "issues", "projects"],
                    "project_number": 7,
                    "status_field_name": "Workflow Status",
                    "timeout_seconds": 45,
                }
            },
        },
    )
    target_repo = tmp_path / "target"
    target_repo.mkdir()

    deepagent = cfg.to_deepagent_config(target_repo)

    assert deepagent.github.lifecycle_client == "mcp"
    assert deepagent.github.mcp.docker_image == "ghcr.io/custom/github-mcp-server:test"
    assert deepagent.github.mcp.project_number == 7
    assert deepagent.github.mcp.status_field_name == "Workflow Status"
    assert deepagent.github.mcp.timeout_seconds == 45.0


def test_github_token_is_not_persisted_to_deepagent_yaml(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "secret-token")
    cfg = RootAgentConfig.from_yaml(
        tmp_path / "missing.yaml",
        data={
            "target": {
                "repo_url": "https://github.com/madeehrehman/sdlc_agent_tictactoe",
            }
        },
    )
    target_repo = tmp_path / "target"
    target_repo.mkdir()
    out_path = tmp_path / "config.yaml"

    cfg.to_deepagent_config(target_repo).to_yaml(out_path)
    data = yaml.safe_load(out_path.read_text(encoding="utf-8"))

    assert "GITHUB_TOKEN" not in out_path.read_text(encoding="utf-8")
    assert "secret-token" not in out_path.read_text(encoding="utf-8")
    assert "token" not in data["github"]
