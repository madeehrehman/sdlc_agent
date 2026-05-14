"""Synchronous facade for stdio MCP tool clients."""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from sdlc_agent.config import GitHubMCPRuntimeConfig
from sdlc_agent.mcp.client import HandshakeResult


class MCPToolClient(Protocol):
    server_name: str

    def handshake(self) -> HandshakeResult: ...
    def list_tools(self) -> list[str]: ...
    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class StdioServerLaunch:
    """Serializable stdio server launch settings."""

    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None


def build_github_mcp_server_parameters(
    *,
    token: str,
    config: GitHubMCPRuntimeConfig,
) -> StdioServerLaunch:
    """Build Docker stdio launch parameters for the official GitHub MCP server."""
    return StdioServerLaunch(
        command="docker",
        args=[
            "run",
            "-i",
            "--rm",
            "-e",
            "GITHUB_PERSONAL_ACCESS_TOKEN",
            "-e",
            "GITHUB_TOOLSETS",
            config.docker_image,
        ],
        env={
            "GITHUB_PERSONAL_ACCESS_TOKEN": token,
            "GITHUB_TOOLSETS": ",".join(config.toolsets),
        },
    )


class MCPStdioToolClient:
    """Sync wrapper around an async stdio MCP session.

    The rest of the SDLC agent is synchronous today. This facade owns a small
    event loop and keeps one initialized MCP session open until ``close()``.
    """

    def __init__(
        self,
        *,
        server_name: str,
        launch: StdioServerLaunch | None = None,
        session_factory: Callable[[], Any] | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        if launch is None and session_factory is None:
            raise ValueError("launch or session_factory is required")
        self.server_name = server_name
        self._launch = launch
        self._session_factory = session_factory
        self._timeout_seconds = timeout_seconds
        self._loop = asyncio.new_event_loop()
        self._stack: AsyncExitStack | None = None
        self._session: Any | None = None
        self._tools: list[str] | None = None

    def handshake(self) -> HandshakeResult:
        try:
            self._run(self._ensure_started())
        except Exception as e:  # pragma: no cover - exercised by live failures
            self._close_after_failed_start()
            detail = "operation timed out" if isinstance(e, TimeoutError) else str(e)
            return HandshakeResult(
                ok=False,
                server=self.server_name,
                transport="stdio",
                detail=detail,
            )
        return HandshakeResult(
            ok=True,
            server=self.server_name,
            transport="stdio",
            detail="initialized stdio MCP session",
        )

    def list_tools(self) -> list[str]:
        if self._tools is None:
            result = self._run(self._list_tools())
            self._tools = _tool_names(result)
        return list(self._tools)

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = self._run(self._call_tool(name, arguments))
        return _as_dict(result)

    def close(self) -> None:
        if self._stack is not None:
            self._run(self._stack.aclose())
            self._stack = None
            self._session = None
        if not self._loop.is_closed():
            self._loop.close()

    def _run(self, coro: Any) -> Any:
        if self._loop.is_closed():
            raise RuntimeError("MCP stdio client is closed")
        return self._loop.run_until_complete(
            asyncio.wait_for(coro, timeout=self._timeout_seconds)
        )

    def _close_after_failed_start(self) -> None:
        if self._stack is not None:
            try:
                self._loop.run_until_complete(self._stack.aclose())
            finally:
                self._stack = None
                self._session = None

    async def _ensure_started(self) -> None:
        if self._session is not None:
            return
        self._stack = AsyncExitStack()
        self._session = await self._stack.enter_async_context(self._make_session())
        await self._session.initialize()

    async def _list_tools(self) -> Any:
        await self._ensure_started()
        return await self._session.list_tools()

    async def _call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        await self._ensure_started()
        return await self._session.call_tool(name, arguments)

    def _make_session(self) -> Any:
        if self._session_factory is not None:
            return self._session_factory()
        if self._launch is None:
            raise RuntimeError("missing stdio server launch settings")
        return _default_session_factory(self._launch)


def _default_session_factory(launch: StdioServerLaunch) -> Any:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=launch.command,
        args=launch.args,
        env=launch.env,
        cwd=launch.cwd,
    )

    async def _session_context():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                yield session

    return asynccontextmanager(_session_context)()


def _tool_names(result: Any) -> list[str]:
    tools = result.get("tools", result) if isinstance(result, dict) else getattr(result, "tools", result)
    return [tool.get("name", "") if isinstance(tool, dict) else tool.name for tool in tools]


def _as_dict(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return result
    if hasattr(result, "model_dump"):
        return result.model_dump(mode="json")
    if hasattr(result, "__dict__"):
        return dict(result.__dict__)
    return {"result": result}
