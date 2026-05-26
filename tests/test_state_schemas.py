from sdlc_agent.state.schemas import (
    PrimaryState,
    DevResult,
    ReviewResult,
    ReleaseResult,
    IssueContext,
)
from langchain_core.messages import HumanMessage


def test_primary_state_shape():
    state: PrimaryState = {
        "current_issue": None,
        "phase": "intake",
        "dev_result": None,
        "review_result": None,
        "release_result": None,
        "memory_snapshot": {},
        "retry_count": 0,
        "messages": [HumanMessage(content="start")],
    }
    assert state["phase"] == "intake"
    assert state["retry_count"] == 0


def test_dev_result_shape():
    result: DevResult = {
        "branch": "feature/issue-1",
        "test_results": {"passed": 5, "failed": 0},
        "commit_sha": "abc123",
        "success": True,
    }
    assert result["success"] is True


def test_review_result_shape():
    result: ReviewResult = {
        "approved": True,
        "feedback": "All criteria met.",
        "pr_url": "https://github.com/owner/repo/pull/1",
    }
    assert result["approved"] is True


def test_release_result_shape():
    result: ReleaseResult = {
        "deployed": False,
        "deployment_url": "",
        "reason": "Human rejected.",
    }
    assert result["deployed"] is False


def test_issue_context_shape():
    ctx: IssueContext = {
        "number": 1,
        "title": "Add login",
        "body": "As a user...",
        "url": "https://github.com/owner/repo/issues/1",
        "acceptance_criteria": ["User can log in with email"],
    }
    assert ctx["number"] == 1
