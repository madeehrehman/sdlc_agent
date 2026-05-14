"""Helpers for issue-driven SDLC runs (adopted GitHub issue → worktree → PR)."""

from __future__ import annotations

import re
from pathlib import Path

from sdlc_agent.contracts import ArtifactReturn, TaskStatus, VerificationBlock
from sdlc_agent.mcp.github import GitHubIssue


def default_worktrees_dir(memory_repo_root: Path) -> Path:
    return (memory_repo_root / ".worktrees").resolve()


def issue_branch_name(issue_number: int, title: str, *, max_slug_len: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:max_slug_len].strip("-")
    slug = slug or "issue"
    return f"sdlc/issue-{issue_number}-{slug}"


def synthetic_requirements_artifact(ticket_id: str, issue: GitHubIssue) -> ArtifactReturn:
    """Minimal requirement-analysis artifact so DeveloperTester can run without BacklogAnalyzer."""
    summary = f"{issue.title}\n\n{issue.body.strip()}"[:8000]
    ac = list(issue.acceptance_criteria)
    body: dict[str, object] = {
        "source_spec": "github-issue",
        "summary": summary,
        "github_issue_number": issue.number,
        "github_issue_url": issue.url,
        "acceptance_criteria": ac,
        "ready_for_development": True,
        "blocking_questions": [],
    }
    return ArtifactReturn(
        task_id=f"{ticket_id}-issue-adoption",
        status=TaskStatus.COMPLETED,
        artifact=body,
        verification=VerificationBlock(passed=True, self_checks=[]),
        proposed_memory=[],
    )
