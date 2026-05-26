"""Typed state shapes shared across all LangGraph agents."""
from __future__ import annotations

from typing import Annotated, Optional
from typing_extensions import TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class IssueContext(TypedDict):
    """Minimal snapshot of a GitHub issue passed between agents."""
    number: int
    title: str
    body: str
    url: str
    acceptance_criteria: list[str]


class DevResult(TypedDict):
    """Outcome reported by the Developer/Tester subgraph."""
    branch: str
    test_results: dict
    commit_sha: str
    success: bool


class ReviewResult(TypedDict):
    """Outcome reported by the PR Reviewer subgraph."""
    approved: bool
    feedback: str
    pr_url: str


class ReleaseResult(TypedDict):
    """Outcome reported by the Release Engineer subgraph."""
    deployed: bool
    deployment_url: str
    reason: str


class PrimaryState(TypedDict):
    """Full state of the Primary supervisor graph."""
    current_issue: Optional[IssueContext]
    phase: str  # intake | dev | review | release | done
    dev_result: Optional[DevResult]
    review_result: Optional[ReviewResult]
    release_result: Optional[ReleaseResult]
    memory_snapshot: dict
    retry_count: int
    messages: Annotated[list[BaseMessage], add_messages]
