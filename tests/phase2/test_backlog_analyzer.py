"""Phase 2: Backlog Analyzer turns specs.md gaps into GitHub issues."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import pytest
from pydantic import ValidationError

from sdlc_agent.contracts import (
    Constraints,
    InjectedContext,
    SubagentName,
    TaskAssignment,
    TaskStatus,
)
from sdlc_agent.llm.openai_client import OpenAIClient
from sdlc_agent.mcp.github import FixtureGitHubProject
from sdlc_agent.subagents import BacklogAnalyzer


def _assignment(
    ticket_id: str = "BACKLOG-SEED",
    *,
    project_facts: list[str] | None = None,
) -> TaskAssignment:
    return TaskAssignment(
        task_id="task-1",
        ticket_id=ticket_id,
        subagent=SubagentName.BACKLOG_ANALYZER,
        task="Analyze specs.md backlog and create GitHub issues",
        inputs={"phase": "REQUIREMENTS_ANALYSIS", "attempt": 1, "specs_path": "specs.md"},
        injected_context=InjectedContext(project_facts=project_facts or []),
        constraints=Constraints(),
    )


def _write_specs(repo: Path) -> None:
    (repo / "specs.md").write_text(
        "# Product spec\n\n"
        "## Login protection\n"
        "The system must rate-limit repeated login attempts by IP.\n",
        encoding="utf-8",
    )


def _canned_response(
    *,
    source_spec: str = "specs.md",
    issue_drafts: list[dict[str, Any]] | None = None,
    blocking_questions: list[str] | None = None,
    proposed_memory: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "artifact": {
            "source_spec": source_spec,
            "summary": "specs.md calls for login rate limiting",
            "repo_gaps": ["no implementation exists for login rate limiting"],
            "issue_drafts": issue_drafts
            if issue_drafts is not None
            else [
                {
                    "title": "Add login rate limiting",
                    "body": "Implement per-IP rate limiting for repeated login attempts.",
                    "acceptance_criteria": [
                        "HTTP 429 returned after threshold",
                        "limit configurable per environment",
                    ],
                    "labels": ["security"],
                }
            ],
            "blocking_questions": blocking_questions or [],
            "ready_for_development": not blocking_questions,
            "notes": "mocked",
        },
        "proposed_memory": proposed_memory or [],
    }


def test_backlog_analyzer_creates_github_issue_with_acceptance_criteria(
    tmp_repo: Path,
    fake_llm_factory: Callable[[list[Any]], OpenAIClient],
) -> None:
    _write_specs(tmp_repo)
    llm = fake_llm_factory([_canned_response()])
    github = FixtureGitHubProject(repo_root=tmp_repo)
    analyzer = BacklogAnalyzer(llm=llm, github=github)

    out = analyzer.run(_assignment())

    assert out.status is TaskStatus.COMPLETED
    assert out.verification.passed is True
    assert out.artifact["source_spec"] == "specs.md"
    assert out.artifact["created_issues"][0]["number"] == 1
    assert out.artifact["created_issues"][0]["acceptance_criteria"]
    assert github.list_project_items()[0].status == "Backlog"


def test_missing_acceptance_criteria_fails_self_check(
    tmp_repo: Path,
    fake_llm_factory: Callable[[list[Any]], OpenAIClient],
) -> None:
    _write_specs(tmp_repo)
    response = _canned_response(
        issue_drafts=[
            {
                "title": "Add login rate limiting",
                "body": "Implement rate limits.",
                "acceptance_criteria": [],
                "labels": ["security"],
            }
        ]
    )
    llm = fake_llm_factory([response])
    analyzer = BacklogAnalyzer(llm=llm, github=FixtureGitHubProject(repo_root=tmp_repo))

    out = analyzer.run(_assignment())

    assert out.verification.passed is False
    assert out.status is TaskStatus.NEEDS_HUMAN
    assert analyzer.github.list_project_items() == []


def test_invalid_later_issue_draft_does_not_partially_create_github_issues(
    tmp_repo: Path,
    fake_llm_factory: Callable[[list[Any]], OpenAIClient],
) -> None:
    _write_specs(tmp_repo)
    response = _canned_response(
        issue_drafts=[
            {
                "title": "Valid first issue",
                "body": "Implement first gap.",
                "acceptance_criteria": ["AC"],
                "labels": [],
            },
            {
                "body": "Missing title should fail validation.",
                "acceptance_criteria": ["AC"],
                "labels": [],
            },
        ]
    )
    llm = fake_llm_factory([response])
    analyzer = BacklogAnalyzer(llm=llm, github=FixtureGitHubProject(repo_root=tmp_repo))

    with pytest.raises(ValidationError):
        analyzer.run(_assignment())

    assert analyzer.github.list_project_items() == []


def test_project_status_preflight_runs_before_creating_github_issues(
    tmp_repo: Path,
    fake_llm_factory: Callable[[list[Any]], OpenAIClient],
) -> None:
    _write_specs(tmp_repo)

    class PreflightFailingGitHub(FixtureGitHubProject):
        def validate_project_statuses(self, statuses: list[str]) -> None:
            raise RuntimeError(f"missing statuses: {statuses}")

    github = PreflightFailingGitHub(repo_root=tmp_repo)
    analyzer = BacklogAnalyzer(llm=fake_llm_factory([_canned_response()]), github=github)

    with pytest.raises(RuntimeError, match="missing statuses"):
        analyzer.run(_assignment())

    assert github.list_project_items() == []


def test_prompt_includes_specs_context_existing_project_and_memory(
    tmp_repo: Path,
    fake_llm_factory: Callable[[list[Any]], OpenAIClient],
) -> None:
    _write_specs(tmp_repo)
    github = FixtureGitHubProject(repo_root=tmp_repo)
    issue = github.create_issue(
        {
            "title": "Existing issue",
            "body": "Already tracked.",
            "acceptance_criteria": ["already has AC"],
            "labels": ["tracked"],
        }
    )
    github.add_issue_to_project(issue, status="In Progress")
    llm = fake_llm_factory([_canned_response()])
    analyzer = BacklogAnalyzer(llm=llm, github=github)

    analyzer.run(_assignment(project_facts=["repo uses GitHub Issues"]))

    last_call = llm._client.chat.completions.calls[-1]  # type: ignore[attr-defined]
    user_msg = last_call["messages"][1]["content"]
    assert "repo uses GitHub Issues" in user_msg
    assert "Login protection" in user_msg
    assert "Existing issue" in user_msg
    assert last_call["response_format"]["type"] == "json_schema"
