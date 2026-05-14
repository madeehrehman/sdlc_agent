"""Live OpenAI smoke tests. Skipped unless `--run-live` AND OPENAI_API_KEY is set.

These exist so you can sanity-check that the real model returns a schema-valid
response for each subagent on a representative input.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from sdlc_agent.contracts import (
    Constraints,
    InjectedContext,
    SubagentName,
    TaskAssignment,
)
from sdlc_agent.llm import OpenAIClient
from sdlc_agent.mcp.git import LocalGitClient
from sdlc_agent.mcp.github import FixtureGitHubProject
from sdlc_agent.subagents import BacklogAnalyzer, PRReviewer


def _live_client() -> OpenAIClient:
    return OpenAIClient(
        model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        api_key=os.environ["OPENAI_API_KEY"],
    )


@pytest.mark.live
def test_live_backlog_analyzer_against_specs_md(tmp_repo: Path) -> None:
    (tmp_repo / "specs.md").write_text(
        "# Product spec\n\nAdd a greet(name) helper returning hello text.\n",
        encoding="utf-8",
    )
    analyzer = BacklogAnalyzer(llm=_live_client(), github=FixtureGitHubProject(tmp_repo))
    out = analyzer.run(
        TaskAssignment(
            task_id="live-1",
            ticket_id="GH-1",
            subagent=SubagentName.BACKLOG_ANALYZER,
            task="live: analyze",
            inputs={"specs_path": "specs.md"},
            injected_context=InjectedContext(project_facts=["repo uses GitHub Projects"]),
            constraints=Constraints(),
        )
    )
    assert out.artifact["source_spec"] == "specs.md"
    assert out.artifact["issue_drafts"]


@pytest.mark.live
def test_live_pr_reviewer_against_local_diff(small_git_repo: dict) -> None:
    reviewer = PRReviewer(
        llm=_live_client(), git=LocalGitClient(repo_root=small_git_repo["repo"])
    )
    out = reviewer.run(
        TaskAssignment(
            task_id="live-2",
            ticket_id="TICKET-12",
            subagent=SubagentName.PR_REVIEWER,
            task="live: review",
            inputs={"base_ref": small_git_repo["base_ref"], "head_ref": "HEAD"},
            injected_context=InjectedContext(),
            constraints=Constraints(),
        )
    )
    assert out.artifact["verdict"] in {"approve", "request_changes", "comment"}
    assert out.artifact["summary"]
