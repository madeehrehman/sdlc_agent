"""Phase 0: GitHub lifecycle client factory chooses fixture or MCP."""

from __future__ import annotations

from pathlib import Path

import pytest

from sdlc_agent.config import DeepAgentConfig, GitHubConfig, ProjectConfig
from sdlc_agent.mcp.factory import build_github_project_client
from sdlc_agent.mcp.github import FixtureGitHubProject, GitHubProjectError
from sdlc_agent.mcp.github_mcp import GitHubMCPProjectClient


class FakeToolClient:
    server_name = "fake-github-mcp"

    def __init__(self, tools: list[str]) -> None:
        self.tools = tools
        self.closed = False

    def handshake(self):
        from sdlc_agent.mcp import HandshakeResult

        return HandshakeResult(ok=True, server=self.server_name, transport="fake")

    def list_tools(self) -> list[str]:
        return self.tools

    def call_tool(self, name: str, arguments: dict) -> dict:
        return {}

    def close(self) -> None:
        self.closed = True


def test_factory_builds_fixture_without_github_token(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    cfg = DeepAgentConfig(
        project=ProjectConfig(name="target", repo_root=tmp_path),
        github=GitHubConfig(
            repository="target",
            lifecycle_client="fixture",
            owner="madeehrehman",
            project_name="target",
        ),
    )

    client = build_github_project_client(cfg)

    assert isinstance(client, FixtureGitHubProject)
    assert client.repo_root == tmp_path.resolve()
    assert client.owner == "madeehrehman"
    assert client.project_name == "target"


def test_factory_requires_github_token_for_mcp(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    cfg = DeepAgentConfig(
        project=ProjectConfig(name="target", repo_root=tmp_path),
        github=GitHubConfig(
            repository="target",
            owner="madeehrehman",
            lifecycle_client="mcp",
        ),
    )

    with pytest.raises(GitHubProjectError, match="GITHUB_TOKEN"):
        build_github_project_client(cfg)


def test_factory_builds_mcp_client_and_validates_tools(tmp_path: Path) -> None:
    captured = {}

    def tool_client_factory(launch):
        captured["launch"] = launch
        return FakeToolClient(
            ["get_file_contents", "issue_write", "issue_read", "list_issues"]
        )

    cfg = DeepAgentConfig(
        project=ProjectConfig(name="target", repo_root=tmp_path),
        github=GitHubConfig(
            repository="target",
            owner="madeehrehman",
            project_name="target",
            lifecycle_client="mcp",
        ),
    )

    client = build_github_project_client(
        cfg,
        github_token="secret-token",
        tool_client_factory=tool_client_factory,
    )

    assert isinstance(client, GitHubMCPProjectClient)
    assert captured["launch"].env["GITHUB_PERSONAL_ACCESS_TOKEN"] == "secret-token"
    assert captured["launch"].env["GITHUB_TOOLSETS"] == "repos,issues"


def test_factory_closes_mcp_tool_client_when_required_tools_missing(tmp_path: Path) -> None:
    fake_tool_client = FakeToolClient(["get_file_contents"])

    cfg = DeepAgentConfig(
        project=ProjectConfig(name="target", repo_root=tmp_path),
        github=GitHubConfig(
            repository="target",
            owner="madeehrehman",
            lifecycle_client="mcp",
        ),
    )

    with pytest.raises(GitHubProjectError, match="missing required GitHub MCP tools"):
        build_github_project_client(
            cfg,
            github_token="secret-token",
            tool_client_factory=lambda _launch: fake_tool_client,
        )

    assert fake_tool_client.closed is True


def test_factory_closes_mcp_tool_client_when_tool_validation_errors(tmp_path: Path) -> None:
    class FailingToolClient(FakeToolClient):
        def list_tools(self) -> list[str]:
            raise RuntimeError("docker failed")

    fake_tool_client = FailingToolClient([])
    cfg = DeepAgentConfig(
        project=ProjectConfig(name="target", repo_root=tmp_path),
        github=GitHubConfig(
            repository="target",
            owner="madeehrehman",
            lifecycle_client="mcp",
        ),
    )

    with pytest.raises(GitHubProjectError, match="docker failed"):
        build_github_project_client(
            cfg,
            github_token="secret-token",
            tool_client_factory=lambda _launch: fake_tool_client,
        )

    assert fake_tool_client.closed is True
