"""Issue-driven adoption helpers."""

from __future__ import annotations

from sdlc_agent.issue_workflow import issue_branch_name, synthetic_requirements_artifact
from sdlc_agent.mcp.github import GitHubIssue, parse_acceptance_criteria_from_issue_body


def test_parse_acceptance_criteria_from_issue_body() -> None:
    body = """Intro line

## Acceptance Criteria

- [ ] First thing
- [x] Done thing
- Plain bullet
"""
    assert parse_acceptance_criteria_from_issue_body(body) == [
        "First thing",
        "Done thing",
        "Plain bullet",
    ]


def test_issue_branch_name_slug() -> None:
    assert issue_branch_name(5, "Hello World!") == "sdlc/issue-5-hello-world"


def test_synthetic_requirements_artifact_carries_issue() -> None:
    issue = GitHubIssue(
        number=12,
        title="Add widget",
        body="Details here.\n\n## Acceptance Criteria\n\n- [ ] Works",
        url="https://github.com/o/r/issues/12",
        acceptance_criteria=["Works"],
    )
    art = synthetic_requirements_artifact("T-1", issue)
    assert art.verification.passed is True
    assert art.artifact["github_issue_number"] == 12
    assert art.artifact["acceptance_criteria"] == ["Works"]
