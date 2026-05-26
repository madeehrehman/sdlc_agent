"""Assembles the full multi-agent runtime from config.

Call build_runtime() to get a compiled Primary graph with all sub-agent
subgraphs wired in. Single entry point for both CLI and tests.
"""
from __future__ import annotations

from pathlib import Path

from sdlc_agent.agents.developer.graph import build_developer_graph
from sdlc_agent.agents.primary.graph import build_primary_graph
from sdlc_agent.agents.primary.memory import ProjectMemory
from sdlc_agent.agents.release.graph import build_release_graph
from sdlc_agent.agents.reviewer.graph import build_reviewer_graph
from sdlc_agent.config import RootAgentConfig
from sdlc_agent.docker.sandbox import DockerSandbox
from sdlc_agent.mcp.git import LocalGitClient
from sdlc_agent.mcp.github import FixtureGitHubProject


def build_runtime(
    config: RootAgentConfig,
    target_repo_root: Path,
    use_docker: bool = True,
):
    """Build and return the compiled Primary graph with all sub-agents wired in."""
    memory = ProjectMemory(path=target_repo_root / config.memory.project_memory_path)

    github = FixtureGitHubProject(
        repo_root=target_repo_root,
        owner=config.target.owner or "local",
        repository=config.target.repository or target_repo_root.name,
    )

    git_client = LocalGitClient(repo_root=target_repo_root)

    developer_sandbox = DockerSandbox(
        root=target_repo_root,
        image=config.docker.developer_image,
        use_docker=use_docker,
    )

    developer_graph = build_developer_graph(
        sandbox=developer_sandbox,
        git_client=git_client,
        model_config=config.model,
    )

    reviewer_graph = build_reviewer_graph(
        git_client=git_client,
        github=github,
        repo_root=target_repo_root,
        model_config=config.model,
    )

    release_graph = build_release_graph(
        git_client=git_client,
        model_config=config.model,
        hitl_config=config.hitl,
        docker_config=config.docker,
    )

    primary_graph = build_primary_graph(
        github=github,
        memory=memory,
        model_config=config.model,
        hitl_config=config.hitl,
        developer_subgraph=developer_graph,
        reviewer_subgraph=reviewer_graph,
        release_subgraph=release_graph,
    )

    return primary_graph
