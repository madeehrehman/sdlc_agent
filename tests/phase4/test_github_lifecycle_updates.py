"""Phase 4: orchestrator mirrors SDLC progress into GitHub Issues."""

from __future__ import annotations

from pathlib import Path

from sdlc_agent.contracts import SubagentName
from sdlc_agent.mcp.github import FixtureGitHubProject, GitHubIssueDraft
from sdlc_agent.memory import initialize_deepagent
from sdlc_agent.orchestrator import SDLCPhase
from sdlc_agent.orchestrator.dispatcher import Orchestrator
from sdlc_agent.subagents.mocks import CannedSubagent, canned_successful_artifact


def _registry(
    *,
    created_issues: list[dict] | None = None,
) -> dict[SubagentName, CannedSubagent]:
    return {
        SubagentName.BACKLOG_ANALYZER: CannedSubagent(
            name=SubagentName.BACKLOG_ANALYZER,
            artifact_kwargs=canned_successful_artifact(
                artifact={"source_spec": "specs.md", "created_issues": created_issues or []}
            ),
        ),
        SubagentName.DEVELOPER: CannedSubagent(
            name=SubagentName.DEVELOPER,
            artifact_kwargs=canned_successful_artifact(
                artifact={"implementation_summary": "...", "test_files": ["test_app.py"]}
            ),
        ),
        SubagentName.PR_REVIEWER: CannedSubagent(
            name=SubagentName.PR_REVIEWER,
            artifact_kwargs=canned_successful_artifact(
                artifact={"verdict": "approve", "summary": "ok", "issues": []}
            ),
        ),
    }


def test_orchestrator_updates_project_item_after_release_ready(tmp_repo: Path) -> None:
    paths = initialize_deepagent(tmp_repo)
    github = FixtureGitHubProject(repo_root=tmp_repo)
    issue = github.create_issue(
        GitHubIssueDraft(title="Build first slice", body="Body", acceptance_criteria=["AC"])
    )
    item = github.add_issue_to_project(issue, status="Backlog")

    orch = Orchestrator(paths=paths, registry=_registry(), github=github)
    orch.intake(
        "GH-1",
        ticket_inputs={
            "github_issue_number": issue.number,
            "github_project_item_id": item.item_id,
        },
    )
    final = orch.run_to_completion("GH-1")

    assert final.current_phase is SDLCPhase.DONE
    assert github.get_project_item(item.item_id).status == "Release Ready"
    assert github.get_issue(issue.number).state == "open"


def test_orchestrator_closes_issue_only_after_release_to_main_acceptance(
    tmp_repo: Path,
) -> None:
    paths = initialize_deepagent(tmp_repo)
    github = FixtureGitHubProject(repo_root=tmp_repo)
    issue = github.create_issue(
        GitHubIssueDraft(title="Build first slice", body="Body", acceptance_criteria=["AC"])
    )
    item = github.add_issue_to_project(issue, status="Backlog")

    orch = Orchestrator(paths=paths, registry=_registry(), github=github)
    orch.intake(
        "GH-1",
        ticket_inputs={
            "github_issue_number": issue.number,
            "github_project_item_id": item.item_id,
            "release_to_main_accepted": True,
        },
    )
    final = orch.run_to_completion("GH-1")

    assert final.current_phase is SDLCPhase.DONE
    assert github.get_project_item(item.item_id).status == "Done"
    assert github.get_issue(issue.number).state == "closed"


def test_orchestrator_adopts_backlog_created_github_issue(tmp_repo: Path) -> None:
    paths = initialize_deepagent(tmp_repo)
    github = FixtureGitHubProject(repo_root=tmp_repo)
    issue = github.create_issue(
        GitHubIssueDraft(title="Build first slice", body="Body", acceptance_criteria=["AC"])
    )
    item = github.add_issue_to_project(issue, status="Backlog")

    registry = _registry(
        created_issues=[
            {
                "number": issue.number,
                "project_item_id": item.item_id,
                "acceptance_criteria": ["AC"],
            }
        ]
    )
    orch = Orchestrator(paths=paths, registry=registry, github=github)
    final = orch.run_to_completion("GH-1")

    assert final.ticket_inputs["github_issue_number"] == issue.number
    assert final.ticket_inputs["github_project_item_id"] == item.item_id
    assert github.get_project_item(item.item_id).status == "Release Ready"
