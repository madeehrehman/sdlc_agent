"""Phase 2 acceptance: orchestrator drives real GitHub-native subagents."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from sdlc_agent.contracts import SubagentName
from sdlc_agent.llm.openai_client import OpenAIClient
from sdlc_agent.mcp.git import LocalGitClient
from sdlc_agent.mcp.github import FixtureGitHubProject
from sdlc_agent.memory import initialize_deepagent
from sdlc_agent.memory.stores import MemoryStores
from sdlc_agent.orchestrator import SDLCPhase
from sdlc_agent.orchestrator.dispatcher import Orchestrator
from sdlc_agent.subagents import (
    BacklogAnalyzer,
    CannedSubagent,
    PRReviewer,
    canned_successful_artifact,
)


def _backlog_response() -> dict[str, Any]:
    return {
        "artifact": {
            "source_spec": "specs.md",
            "summary": "Create a greet utility from specs.md",
            "repo_gaps": ["greet() is not implemented"],
            "issue_drafts": [
                {
                    "title": "Add greet utility",
                    "body": "Implement greet(name).",
                    "acceptance_criteria": ["greet('world') returns 'hello, world'"],
                    "labels": ["feature"],
                }
            ],
            "blocking_questions": [],
            "ready_for_development": True,
            "notes": "ready",
        },
        "proposed_memory": [
            {
                "scope": "project_fact",
                "claim": "target projects start from specs.md",
                "evidence": "BacklogAnalyzer read specs.md and created GitHub issues",
                "confidence": "high",
            }
        ],
    }


def _reviewer_response() -> dict[str, Any]:
    return {
        "artifact": {
            "verdict": "approve",
            "summary": "Small, well-scoped change. Tests included.",
            "issues": [],
            "strengths": ["clean signature", "good error handling"],
        },
        "proposed_memory": [
            {
                "scope": "subagent_lore",
                "claim": "team prefers explicit return types on public functions",
                "evidence": "approved this PR which uses explicit return type",
                "confidence": "medium",
            }
        ],
    }


def test_full_lifecycle_with_real_subagents(
    tmp_repo: Path,
    github_project: FixtureGitHubProject,
    small_git_repo: dict[str, Any],
    fake_llm_factory: Callable[[list[Any]], OpenAIClient],
) -> None:
    paths = initialize_deepagent(tmp_repo)
    llm = fake_llm_factory([_backlog_response(), _reviewer_response()])

    backlog = BacklogAnalyzer(llm=llm, github=github_project)
    reviewer = PRReviewer(llm=llm, git=LocalGitClient(repo_root=small_git_repo["repo"]))
    developer = CannedSubagent(
        name=SubagentName.DEVELOPER,
        artifact_kwargs=canned_successful_artifact(
            artifact={"implementation_summary": "...", "tests": ["t1"]}
        ),
    )
    registry = {
        SubagentName.BACKLOG_ANALYZER: backlog,
        SubagentName.DEVELOPER: developer,
        SubagentName.PR_REVIEWER: reviewer,
    }

    orch = Orchestrator(paths=paths, registry=registry, github=github_project)
    orch.intake(
        "GH-1",
        ticket_inputs={
            "specs_path": "specs.md",
            "base_ref": small_git_repo["base_ref"],
            "head_ref": small_git_repo["head_ref"],
        },
    )
    final = orch.run_to_completion("GH-1")

    assert final.current_phase is SDLCPhase.DONE

    stores = MemoryStores(paths)
    facts = {f["claim"] for f in stores.read_project_facts()}
    assert "target projects start from specs.md" in facts

    backlog_artifact = stores.load_artifact("GH-1", SDLCPhase.REQUIREMENTS_ANALYSIS)
    assert backlog_artifact is not None
    assert backlog_artifact.artifact["created_issues"][0]["project_item_id"] == "ISSUE_1"
    assert paths.ticket_artifacts_dir("GH-1").joinpath("review.json").is_file()
