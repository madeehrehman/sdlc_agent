"""Phase 3 acceptance: full GitHub-native SDLC with all three real subagents."""

from __future__ import annotations

import sys
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
from sdlc_agent.sandbox import LocalSubprocessSandbox
from sdlc_agent.subagents import BacklogAnalyzer, Developer, PRReviewer


_TEST_FILE = """\
import unittest
from greet import greet


class TestGreet(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(greet("world"), "hello, world")
"""

_IMPL_FILE = """\
def greet(name: str) -> str:
    return f"hello, {name}"
"""


def _backlog_response() -> dict[str, Any]:
    return {
        "artifact": {
            "source_spec": "specs.md",
            "summary": "Add greet(name) returning a hello-world string",
            "repo_gaps": ["greet() is missing"],
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
        "proposed_memory": [],
    }


def _developer_steps() -> list[dict[str, Any]]:
    return [
        {"action": "write_test", "file_path": "test_greet.py", "content": _TEST_FILE, "rationale": "RED"},
        {"action": "run_tests", "file_path": "", "content": "", "rationale": "expect RED"},
        {"action": "write_code", "file_path": "greet.py", "content": _IMPL_FILE, "rationale": "GREEN"},
        {"action": "run_tests", "file_path": "", "content": "", "rationale": "expect GREEN"},
        {"action": "complete", "file_path": "", "content": "", "rationale": "AC covered"},
    ]


def _developer_summary() -> dict[str, Any]:
    return {
        "artifact": {
            "implementation_summary": "Implemented greet() via TDD; one test, one impl file.",
            "impl_files": ["greet.py"],
            "test_files": ["test_greet.py"],
            "iterations_used": 5,
            "final_tests_green": True,
            "acceptance_criteria_addressed": ["greet('world') returns 'hello, world'"],
        },
        "proposed_memory": [
            {
                "scope": "project_fact",
                "claim": "this project's test runner is unittest",
                "evidence": "Developer ran `python -m unittest discover` and tests passed",
                "confidence": "high",
            }
        ],
    }


def _reviewer_response() -> dict[str, Any]:
    return {
        "artifact": {
            "verdict": "approve",
            "summary": "Tiny greet() with a clean test; ship it.",
            "issues": [],
            "strengths": ["test-first", "minimal impl"],
        },
        "proposed_memory": [],
    }


def _registry(
    llm: OpenAIClient,
    github_project: FixtureGitHubProject,
    sandbox: LocalSubprocessSandbox,
    small_git_repo: dict[str, Any],
) -> dict[SubagentName, object]:
    return {
        SubagentName.BACKLOG_ANALYZER: BacklogAnalyzer(llm=llm, github=github_project),
        SubagentName.DEVELOPER: Developer(llm=llm, sandbox=sandbox, max_iterations=8),
        SubagentName.PR_REVIEWER: PRReviewer(
            llm=llm, git=LocalGitClient(repo_root=small_git_repo["repo"])
        ),
    }


def test_full_sdlc_all_three_real_subagents(
    tmp_path: Path,
    tmp_repo: Path,
    github_project: FixtureGitHubProject,
    small_git_repo: dict[str, Any],
    fake_llm_factory: Callable[[list[Any]], OpenAIClient],
) -> None:
    paths = initialize_deepagent(tmp_repo)
    llm = fake_llm_factory([_backlog_response(), *_developer_steps(), _developer_summary(), _reviewer_response()])

    sandbox_root = tmp_path / "dev_sandbox"
    sandbox_root.mkdir()
    sandbox = LocalSubprocessSandbox(
        root=sandbox_root,
        default_test_command=[sys.executable, "-m", "unittest", "discover"],
    )

    orch = Orchestrator(
        paths=paths,
        registry=_registry(llm, github_project, sandbox, small_git_repo),
        github=github_project,
    )
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
    impl_artifact = stores.load_artifact("GH-1", SDLCPhase.DEVELOPMENT)
    assert impl_artifact is not None
    assert impl_artifact.artifact["final_tests_green"] is True
    assert "greet.py" in impl_artifact.artifact["impl_files"]
    assert "test_greet.py" in impl_artifact.artifact["test_files"]
    assert impl_artifact.verification.passed is True

    facts = {f["claim"] for f in stores.read_project_facts()}
    assert "this project's test runner is unittest" in facts

    assert sandbox.file_exists("greet.py")
    assert sandbox.file_exists("test_greet.py")


def test_developer_assignment_carries_requirement_analysis(
    tmp_path: Path,
    tmp_repo: Path,
    github_project: FixtureGitHubProject,
    small_git_repo: dict[str, Any],
    fake_llm_factory: Callable[[list[Any]], OpenAIClient],
) -> None:
    paths = initialize_deepagent(tmp_repo)
    llm = fake_llm_factory([_backlog_response(), *_developer_steps(), _developer_summary(), _reviewer_response()])

    sandbox_root = tmp_path / "dev_sandbox"
    sandbox_root.mkdir()
    sandbox = LocalSubprocessSandbox(
        root=sandbox_root,
        default_test_command=[sys.executable, "-m", "unittest", "discover"],
    )

    captured_developer = Developer(llm=llm, sandbox=sandbox, max_iterations=8)
    orig_run = captured_developer.run
    last_assignment: dict[str, Any] = {}

    def capture(assignment):  # type: ignore[no-untyped-def]
        last_assignment["a"] = assignment
        return orig_run(assignment)

    captured_developer.run = capture  # type: ignore[method-assign]
    registry = _registry(llm, github_project, sandbox, small_git_repo)
    registry[SubagentName.DEVELOPER] = captured_developer

    orch = Orchestrator(paths=paths, registry=registry, github=github_project)
    orch.intake(
        "GH-1",
        ticket_inputs={
            "specs_path": "specs.md",
            "base_ref": small_git_repo["base_ref"],
            "head_ref": small_git_repo["head_ref"],
        },
    )
    orch.run_to_completion("GH-1")

    a = last_assignment["a"]
    ra = a.inputs["requirement_analysis"]
    assert ra["source_spec"] == "specs.md"
    assert "greet('world') returns 'hello, world'" in ra["issue_drafts"][0]["acceptance_criteria"]


def test_pr_reviewer_assignment_carries_requirement_analysis(
    tmp_path: Path,
    tmp_repo: Path,
    github_project: FixtureGitHubProject,
    small_git_repo: dict[str, Any],
    fake_llm_factory: Callable[[list[Any]], OpenAIClient],
) -> None:
    paths = initialize_deepagent(tmp_repo)
    llm = fake_llm_factory([_backlog_response(), *_developer_steps(), _developer_summary(), _reviewer_response()])

    sandbox_root = tmp_path / "dev_sandbox"
    sandbox_root.mkdir()
    sandbox = LocalSubprocessSandbox(
        root=sandbox_root,
        default_test_command=[sys.executable, "-m", "unittest", "discover"],
    )

    captured_reviewer = PRReviewer(
        llm=llm, git=LocalGitClient(repo_root=small_git_repo["repo"])
    )
    orig_run = captured_reviewer.run
    last_assignment: dict[str, Any] = {}

    def capture(assignment):  # type: ignore[no-untyped-def]
        last_assignment["a"] = assignment
        return orig_run(assignment)

    captured_reviewer.run = capture  # type: ignore[method-assign]
    registry = _registry(llm, github_project, sandbox, small_git_repo)
    registry[SubagentName.PR_REVIEWER] = captured_reviewer

    orch = Orchestrator(paths=paths, registry=registry, github=github_project)
    orch.intake(
        "GH-1",
        ticket_inputs={
            "specs_path": "specs.md",
            "base_ref": small_git_repo["base_ref"],
            "head_ref": small_git_repo["head_ref"],
        },
    )
    orch.run_to_completion("GH-1")

    a = last_assignment["a"]
    ra = a.inputs["requirement_analysis"]
    assert ra["source_spec"] == "specs.md"
    assert "greet('world') returns 'hello, world'" in ra["issue_drafts"][0]["acceptance_criteria"]
