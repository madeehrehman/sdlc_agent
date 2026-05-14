"""Lifecycle client abstractions + stub / fixture / local implementations."""

from sdlc_agent.mcp.client import HandshakeResult, MCPClient
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

__all__ = [
    "FixtureGitHubProject",
    "GitHubIssue",
    "GitHubIssueDraft",
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
]
