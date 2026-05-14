"""Phase 0: sync wrapper for stdio MCP tool clients."""

from __future__ import annotations

from contextlib import asynccontextmanager
import asyncio

from sdlc_agent.config import GitHubMCPRuntimeConfig
from sdlc_agent.mcp.stdio import (
    MCPStdioToolClient,
    build_github_mcp_server_parameters,
)


def test_build_github_mcp_server_parameters_uses_docker_and_non_secret_config() -> None:
    params = build_github_mcp_server_parameters(
        token="ghp_secret",
        config=GitHubMCPRuntimeConfig(
            docker_image="ghcr.io/custom/github-mcp-server:test",
            toolsets=["repos", "issues"],
        ),
    )

    assert params.command == "docker"
    assert params.args == [
        "run",
        "-i",
        "--rm",
        "-e",
        "GITHUB_PERSONAL_ACCESS_TOKEN",
        "-e",
        "GITHUB_TOOLSETS",
        "ghcr.io/custom/github-mcp-server:test",
    ]
    assert params.env["GITHUB_PERSONAL_ACCESS_TOKEN"] == "ghp_secret"
    assert params.env["GITHUB_TOOLSETS"] == "repos,issues"


class _FakeTool:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeToolList:
    def __init__(self, names: list[str]) -> None:
        self.tools = [_FakeTool(name) for name in names]


class _FakeSession:
    def __init__(self) -> None:
        self.initialized = False
        self.calls: list[tuple[str, dict]] = []

    async def initialize(self) -> None:
        self.initialized = True

    async def list_tools(self) -> _FakeToolList:
        return _FakeToolList(["issue_write", "issue_read", "list_issues"])

    async def call_tool(self, name: str, arguments: dict) -> dict:
        self.calls.append((name, arguments))
        return {"tool": name, "arguments": arguments, "ok": True}


def test_stdio_tool_client_handshakes_lists_tools_and_calls_tool() -> None:
    session = _FakeSession()

    @asynccontextmanager
    async def session_factory():
        yield session

    client = MCPStdioToolClient(
        server_name="github-mcp",
        session_factory=session_factory,
    )

    handshake = client.handshake()
    tools = client.list_tools()
    result = client.call_tool("issue_write", {"method": "create"})
    client.close()

    assert handshake.ok is True
    assert handshake.server == "github-mcp"
    assert handshake.transport == "stdio"
    assert session.initialized is True
    assert tools == ["issue_write", "issue_read", "list_issues"]
    assert result == {
        "tool": "issue_write",
        "arguments": {"method": "create"},
        "ok": True,
    }


def test_stdio_tool_client_caches_listed_tools() -> None:
    session = _FakeSession()
    list_calls = 0

    async def counted_list_tools() -> _FakeToolList:
        nonlocal list_calls
        list_calls += 1
        return _FakeToolList(["issue_write"])

    session.list_tools = counted_list_tools  # type: ignore[method-assign]

    @asynccontextmanager
    async def session_factory():
        yield session

    client = MCPStdioToolClient(
        server_name="github-mcp",
        session_factory=session_factory,
    )

    assert client.list_tools() == ["issue_write"]
    assert client.list_tools() == ["issue_write"]
    client.close()

    assert list_calls == 1


def test_stdio_tool_client_applies_timeout_to_operations() -> None:
    @asynccontextmanager
    async def session_factory():
        await asyncio.sleep(0.05)
        yield _FakeSession()

    client = MCPStdioToolClient(
        server_name="github-mcp",
        session_factory=session_factory,
        timeout_seconds=0.001,
    )

    handshake = client.handshake()

    assert handshake.ok is False
    assert "timed out" in handshake.detail.lower()
