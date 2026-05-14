"""Opt-in live GitHub MCP smoke tests.

These tests intentionally mutate GitHub only when run with:

    python -m pytest --run-live -m "github_live"

They require OPENAI_API_KEY because `live` tests are globally gated that way,
plus GITHUB_TOKEN, Docker, and a root sdlc-agent.yaml.
"""

from __future__ import annotations

import shutil
import os
import uuid
from pathlib import Path

import pytest

from sdlc_agent.config import RootAgentConfig
from sdlc_agent.mcp.factory import build_github_project_client
from sdlc_agent.mcp.github import GitHubIssueDraft
from sdlc_agent.mcp.github_mcp import GitHubMCPProjectClient


def _live_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> GitHubMCPProjectClient:
    root_cfg_path = Path("sdlc-agent.yaml")
    if not root_cfg_path.is_file():
        pytest.skip("sdlc-agent.yaml is required for GitHub MCP live tests")
    if shutil.which("docker") is None:
        pytest.skip("Docker is required for GitHub MCP live tests")
    if not os.environ.get("GITHUB_TOKEN"):
        pytest.skip("GITHUB_TOKEN is required for GitHub MCP live tests")
    monkeypatch.setenv("GITHUB_LIVE_TEST", "1")
    cfg = RootAgentConfig.from_yaml(root_cfg_path).to_deepagent_config(tmp_path)
    client = build_github_project_client(cfg)
    if not isinstance(client, GitHubMCPProjectClient):
        pytest.skip("root config is not using GitHub MCP lifecycle mode")
    return client


@pytest.mark.live
@pytest.mark.github_live
def test_live_github_mcp_reads_specs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _live_client(tmp_path, monkeypatch)
    try:
        spec = client.read_specs("spec.md")
    finally:
        client.close()

    assert spec.path.endswith("spec.md")
    assert spec.body.strip()


@pytest.mark.live
@pytest.mark.github_live
def test_live_github_mcp_issue_project_round_trip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _live_client(tmp_path, monkeypatch)
    unique = uuid.uuid4().hex[:8]
    issue_number: int | None = None
    try:
        issue = client.create_issue(
            GitHubIssueDraft(
                title=f"SDLC agent live test {unique}",
                body="Created by an opt-in live GitHub MCP smoke test.",
                acceptance_criteria=["Issue can be created, added to project, and closed"],
                labels=["sdlc-agent-live-test"],
            )
        )
        issue_number = issue.number
        item = client.add_issue_to_project(issue, status="Backlog")
        assert item.issue_number == issue.number
        closed = client.close_issue(issue.number)
        issue_number = None
        assert closed.state == "closed"
    finally:
        if issue_number is not None:
            client.close_issue(issue_number)
        client.close()
