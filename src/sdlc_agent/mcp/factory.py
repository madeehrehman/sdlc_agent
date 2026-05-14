"""Factories for lifecycle clients selected by SDLC agent config."""

from __future__ import annotations

import os
from contextlib import suppress
from pathlib import Path
from typing import Callable

from sdlc_agent.config import DeepAgentConfig
from sdlc_agent.mcp.github import FixtureGitHubProject, GitHubProjectClient, GitHubProjectError
from sdlc_agent.mcp.github_mcp import GitHubMCPProjectClient
from sdlc_agent.mcp.stdio import (
    MCPStdioToolClient,
    MCPToolClient,
    StdioServerLaunch,
    build_github_mcp_server_parameters,
)


REQUIRED_GITHUB_MCP_TOOLS = {
    "get_file_contents",
    "issue_write",
    "issue_read",
    "projects_list",
    "projects_get",
    "projects_write",
}


def build_github_project_client(
    config: DeepAgentConfig,
    *,
    github_token: str | None = None,
    tool_client_factory: Callable[[StdioServerLaunch], MCPToolClient] | None = None,
) -> GitHubProjectClient:
    """Build the configured GitHub lifecycle client.

    Fixture mode is credential-free. MCP mode requires a token because it will
    launch the official GitHub MCP server with write-capable issue/project tools.
    """
    github = config.github
    if github.lifecycle_client == "fixture":
        return FixtureGitHubProject(
            repo_root=Path(config.project.repo_root),
            project_name=github.project_name,
            owner=github.owner or "local",
            repository=github.repository,
        )

    token = github_token or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise GitHubProjectError("GITHUB_TOKEN is required for GitHub MCP lifecycle mode")
    if not github.owner:
        raise GitHubProjectError("github.owner is required for GitHub MCP lifecycle mode")

    launch = build_github_mcp_server_parameters(token=token, config=github.mcp)
    factory = tool_client_factory or (
        lambda stdio_launch: MCPStdioToolClient(
            server_name="github-mcp",
            launch=stdio_launch,
            timeout_seconds=github.mcp.timeout_seconds,
        )
    )
    tool_client = factory(launch)
    try:
        missing = REQUIRED_GITHUB_MCP_TOOLS.difference(tool_client.list_tools())
    except Exception as e:
        with suppress(Exception):
            tool_client.close()
        raise GitHubProjectError(str(e)) from e
    if missing:
        with suppress(Exception):
            tool_client.close()
        raise GitHubProjectError(
            "missing required GitHub MCP tools: " + ", ".join(sorted(missing))
        )

    return GitHubMCPProjectClient(
        tool_client=tool_client,
        owner=github.owner,
        repository=github.repository,
        project_name=github.project_name,
        project_number=github.mcp.project_number,
        specs_ref=github.main_branch,
        owner_type=github.mcp.owner_type,
        status_field_name=github.mcp.status_field_name,
    )
