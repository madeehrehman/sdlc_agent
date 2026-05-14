"""Phase 0: local lifecycle stub clients handshake cleanly (no external infra)."""

from __future__ import annotations

from sdlc_agent.mcp import GitHubProjectStub, GitMCPStub, HandshakeResult, MCPClient


def test_git_stub_handshake() -> None:
    result = GitMCPStub().handshake()
    assert isinstance(result, HandshakeResult)
    assert result.ok is True
    assert result.server == "git-mcp-stub"


def test_github_project_stub_handshake() -> None:
    result = GitHubProjectStub().handshake()
    assert result.ok is True
    assert result.server == "github-project-stub"


def test_stubs_satisfy_protocol() -> None:
    assert isinstance(GitMCPStub(), MCPClient)
    assert isinstance(GitHubProjectStub(), MCPClient)
