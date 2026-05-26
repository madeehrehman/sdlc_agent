"""Read-only tools for the PR Reviewer agent. No writes, no pushes."""
from __future__ import annotations
from pathlib import Path
from langchain_core.tools import tool
from sdlc_agent.mcp.git import LocalGitClient
from sdlc_agent.mcp.github import GitHubProjectClient


def make_reviewer_tools(git_client: LocalGitClient, github: GitHubProjectClient, repo_root: Path) -> list:

    @tool
    def read_pr_diff(base_ref: str = "main", head_ref: str = "HEAD") -> str:
        """Read the full unified diff of the PR branch against a base ref."""
        return git_client.diff(base_ref, head_ref)

    @tool
    def list_changed_files(base_ref: str = "main", head_ref: str = "HEAD") -> list[str]:
        """List all files changed in the PR branch."""
        return git_client.files_changed(base_ref, head_ref)

    @tool
    def read_file_readonly(relative_path: str) -> str:
        """Read a file from the codebase. Read-only — no writes allowed."""
        target = (repo_root / relative_path).resolve()
        try:
            target.relative_to(repo_root)
        except ValueError:
            return f"ERROR: path escapes repo: {relative_path}"
        if not target.is_file():
            return f"ERROR: file not found: {relative_path}"
        return target.read_text(encoding="utf-8")

    @tool
    def read_test_report(report_path: str = "test-report.txt") -> str:
        """Read a saved test report file from the repo root."""
        target = repo_root / report_path
        if not target.exists():
            return "No test report found. Ask developer to re-run tests with output capture."
        return target.read_text(encoding="utf-8")

    @tool
    def github_approve_pr(pr_number: int, summary: str) -> dict:
        """Approve a GitHub pull request with a review summary comment."""
        return {"approved": True, "pr_number": pr_number, "summary": summary}

    @tool
    def github_request_changes(pr_number: int, feedback: str) -> dict:
        """Request changes on a PR with specific, actionable feedback."""
        return {"approved": False, "pr_number": pr_number, "feedback": feedback}

    @tool
    def github_add_review_comment(pr_number: int, file_path: str, line: int, comment: str) -> dict:
        """Add an inline review comment on a specific file and line."""
        return {"commented": True, "pr_number": pr_number, "file": file_path, "line": line}

    return [read_pr_diff, list_changed_files, read_file_readonly, read_test_report,
            github_approve_pr, github_request_changes, github_add_review_comment]
