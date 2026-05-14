"""Phase 2: GitHub-native project client behaves like the lifecycle surface."""

from __future__ import annotations

from pathlib import Path

import pytest

from sdlc_agent.mcp.github import (
    FixtureGitHubProject,
    GitHubIssueDraft,
    GitHubProjectError,
)


def test_handshake_ok_when_specs_exists(tmp_repo: Path) -> None:
    (tmp_repo / "specs.md").write_text("# Product spec\n", encoding="utf-8")

    result = FixtureGitHubProject(repo_root=tmp_repo).handshake()

    assert result.ok is True
    assert result.server == "github-project-fixture"


def test_read_specs_uses_target_repo_specs_md(tmp_repo: Path) -> None:
    (tmp_repo / "specs.md").write_text("# Vision\nShip a CLI.\n", encoding="utf-8")
    client = FixtureGitHubProject(repo_root=tmp_repo)

    spec = client.read_specs()

    assert spec.path == "specs.md"
    assert "Ship a CLI" in spec.body


def test_read_specs_rejects_path_escape(tmp_repo: Path) -> None:
    client = FixtureGitHubProject(repo_root=tmp_repo)

    with pytest.raises(GitHubProjectError):
        client.read_specs("../outside.md")


def test_create_issue_and_add_to_project_round_trip(tmp_repo: Path) -> None:
    client = FixtureGitHubProject(repo_root=tmp_repo)
    draft = GitHubIssueDraft(
        title="Add login rate limits",
        body="Protect /api/login from brute-force attempts.",
        acceptance_criteria=["429 after threshold", "limit configurable"],
        labels=["security"],
    )

    issue = client.create_issue(draft)
    item = client.add_issue_to_project(issue, status="Ready")

    assert issue.number == 1
    assert issue.url.endswith("/issues/1")
    assert item.issue_number == issue.number
    assert item.status == "Ready"
    assert item.acceptance_criteria == draft.acceptance_criteria


def test_project_status_and_issue_close(tmp_repo: Path) -> None:
    client = FixtureGitHubProject(repo_root=tmp_repo)
    issue = client.create_issue(
        GitHubIssueDraft(title="Task", body="Body", acceptance_criteria=["AC"])
    )
    item = client.add_issue_to_project(issue)

    updated = client.update_project_status(item.item_id, "Done")
    closed = client.close_issue(issue.number)

    assert updated.status == "Done"
    assert closed.state == "closed"
