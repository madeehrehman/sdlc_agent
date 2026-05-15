"""Multi-issue daemon dequeues backlog issues and runs issue-driven full SDLC."""

from __future__ import annotations

from pathlib import Path

import pytest

from sdlc_agent.daemon import (
    pick_next_dequeued_issue,
    run_sdlc_daemon,
)
from sdlc_agent.mcp.github import GitHubIssueDraft, GitHubProjectItem, FixtureGitHubProject
from sdlc_agent.runner import SDLCRunResult


def test_pick_next_dequeued_issue_prefers_lowest_number() -> None:
    items = [
        GitHubProjectItem(item_id="ISSUE_10", issue_number=10, title="x", status="Backlog"),
        GitHubProjectItem(item_id="ISSUE_3", issue_number=3, title="y", status="Backlog"),
        GitHubProjectItem(item_id="ISSUE_7", issue_number=7, title="z", status="In Development"),
    ]
    nxt = pick_next_dequeued_issue(items, dequeue_statuses=frozenset({"Backlog"}))
    assert nxt is not None
    assert nxt.issue_number == 3


def test_pick_next_dequeued_issue_respects_status_filter() -> None:
    items = [
        GitHubProjectItem(item_id="ISSUE_1", issue_number=1, title="x", status="In Review"),
    ]
    assert pick_next_dequeued_issue(items, dequeue_statuses=frozenset({"Backlog"})) is None


def test_daemon_processes_fifo_until_queue_empty(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "target"
    target.mkdir()
    cfg_path = tmp_path / "sdlc-agent.yaml"
    cfg_path.write_text(
        "target:\n"
        "  repo_url: https://github.com/o/r\n"
        "github:\n"
        "  lifecycle_client: fixture\n",
        encoding="utf-8",
    )
    env_path = tmp_path / ".env"
    env_path.write_text("OPENAI_API_KEY=sk\n", encoding="utf-8")

    gh = FixtureGitHubProject(repo_root=target)
    i1 = gh.create_issue(
        GitHubIssueDraft(title="one", body="b", acceptance_criteria=["a"]),
    )
    gh.add_issue_to_project(i1)
    i2 = gh.create_issue(
        GitHubIssueDraft(title="two", body="b", acceptance_criteria=["a"]),
    )
    gh.add_issue_to_project(i2)

    monkeypatch.setattr("sdlc_agent.daemon.build_github_project_client", lambda _cfg: gh)

    seen: list[int] = []

    def fake_run(*, issue_number: int, ticket_id: str, **_kwargs: object) -> SDLCRunResult:
        seen.append(issue_number)
        gh.update_project_status(f"ISSUE_{issue_number}", "Release Ready")
        return SDLCRunResult(
            ticket_id=ticket_id,
            mode="full",
            final_phase="DONE",
            github_issue_number=issue_number,
            github_item_id=f"ISSUE_{issue_number}",
            github_pr_number=None,
            github_pr_url=None,
            state_path=target / ".deepagent" / "state" / f"{ticket_id}.json",
            artifacts_dir=target / ".deepagent" / "artifacts" / ticket_id,
        )

    summary = run_sdlc_daemon(
        root_config_path=cfg_path,
        env_path=env_path,
        target_repo_root=target,
        run_agent=fake_run,
    )

    assert summary.stopped_reason == "queue_empty"
    assert seen == [1, 2]
    assert len(summary.results) == 2


def test_daemon_respects_max_issues(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "target"
    target.mkdir()
    cfg_path = tmp_path / "sdlc-agent.yaml"
    cfg_path.write_text(
        "target:\n"
        "  repo_url: https://github.com/o/r\n"
        "github:\n"
        "  lifecycle_client: fixture\n",
        encoding="utf-8",
    )
    env_path = tmp_path / ".env"
    env_path.write_text("OPENAI_API_KEY=sk\n", encoding="utf-8")

    gh = FixtureGitHubProject(repo_root=target)
    for _ in range(5):
        issue = gh.create_issue(
            GitHubIssueDraft(title="x", body="y", acceptance_criteria=["z"]),
        )
        gh.add_issue_to_project(issue)

    monkeypatch.setattr("sdlc_agent.daemon.build_github_project_client", lambda _cfg: gh)

    def fake_run(*, issue_number: int, ticket_id: str, **_kwargs: object) -> SDLCRunResult:
        gh.update_project_status(f"ISSUE_{issue_number}", "Release Ready")
        return SDLCRunResult(
            ticket_id=ticket_id,
            mode="full",
            final_phase="DONE",
            github_issue_number=issue_number,
            github_item_id=f"ISSUE_{issue_number}",
            github_pr_number=None,
            github_pr_url=None,
            state_path=target / "s.json",
            artifacts_dir=target / "a",
        )

    summary = run_sdlc_daemon(
        root_config_path=cfg_path,
        env_path=env_path,
        target_repo_root=target,
        max_issues=2,
        run_agent=fake_run,
    )

    assert summary.stopped_reason == "max_issues"
    assert len(summary.results) == 2
