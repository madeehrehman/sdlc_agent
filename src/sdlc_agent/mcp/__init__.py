"""Lifecycle client abstractions + stub / fixture / local implementations."""

from sdlc_agent.mcp.client import HandshakeResult, MCPClient
from sdlc_agent.mcp.factory import REQUIRED_GITHUB_MCP_TOOLS, build_github_project_client
from sdlc_agent.mcp.git import GitMCPStub, GitMCPError, LocalGitClient
from sdlc_agent.mcp.github import (
    FixtureGitHubProject,
    GitHubIssue,
    GitHubIssueDraft,
    GitHubProjectClient,
    GitHubProjectError,
    GitHubProjectItem,
    GitHubProjectStub,
    GitHubSpecDocument,
)
from sdlc_agent.mcp.github_mcp import GitHubMCPProjectClient
from sdlc_agent.mcp.stdio import (
    MCPStdioToolClient,
    MCPToolClient,
    StdioServerLaunch,
    build_github_mcp_server_parameters,
)

__all__ = [
    "FixtureGitHubProject",
    "GitHubIssue",
    "GitHubIssueDraft",
    "GitHubMCPProjectClient",
    "GitHubProjectClient",
    "GitHubProjectError",
    "GitHubProjectItem",
    "GitHubProjectStub",
    "GitHubSpecDocument",
    "GitMCPError",
    "GitMCPStub",
    "HandshakeResult",
    "LocalGitClient",
    "MCPClient",
    "MCPStdioToolClient",
    "MCPToolClient",
    "REQUIRED_GITHUB_MCP_TOOLS",
    "StdioServerLaunch",
    "build_github_mcp_server_parameters",
    "build_github_project_client",
]
