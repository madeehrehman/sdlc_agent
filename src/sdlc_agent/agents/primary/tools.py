"""GitHub + memory tools for the Primary agent.

No code, git clone, or test tools here. Primary only touches GitHub and memory.
"""
from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from sdlc_agent.agents.primary.memory import ProjectMemory
from sdlc_agent.mcp.github import GitHubIssueDraft, GitHubProjectClient


def make_primary_tools(
    github: GitHubProjectClient,
    memory: ProjectMemory,
) -> list:
    """Return LangChain tools bound to the provided GitHub client and memory."""

    @tool
    def create_github_issue(
        title: str,
        body: str,
        acceptance_criteria: list[str],
        labels: list[str],
    ) -> dict:
        """Create a GitHub issue with a user story, acceptance criteria, and labels."""
        draft = GitHubIssueDraft(
            title=title,
            body=body,
            acceptance_criteria=acceptance_criteria,
            labels=labels,
        )
        issue = github.create_issue(draft)
        github.add_issue_to_project(issue, status="Backlog")
        return {"number": issue.number, "url": issue.url, "title": issue.title}

    @tool
    def update_issue_label(issue_number: int, status: str) -> dict:
        """Update the project status label of a GitHub issue (e.g. 'In Progress', 'Ready for Review')."""
        item_id = f"ISSUE_{issue_number}"
        item = github.update_project_status(item_id, status)
        return {"item_id": item.item_id, "status": item.status}

    @tool
    def add_issue_comment(issue_number: int, comment: str) -> dict:
        """Add an audit comment to a GitHub issue."""
        return {"issue_number": issue_number, "comment_preview": comment[:80]}

    @tool
    def close_github_issue(issue_number: int, closing_comment: str) -> dict:
        """Close a GitHub issue. Only Primary may call this tool."""
        github.close_issue(issue_number)
        return {"closed": True, "issue_number": issue_number}

    @tool
    def list_open_issues(status_filter: str = "Backlog") -> list[dict]:
        """List open project items matching a status filter (e.g. 'Backlog', 'In Progress')."""
        items = github.list_project_items()
        return [
            {"item_id": i.item_id, "issue_number": i.issue_number, "title": i.title, "status": i.status}
            for i in items
            if i.status == status_filter
        ]

    @tool
    def read_spec_file(relative_path: str = "specs.md") -> str:
        """Read the project spec document from the target repository."""
        doc = github.read_specs(relative_path)
        return doc.body

    @tool
    def read_project_memory() -> dict:
        """Read the Primary agent's living memory (architecture decisions, standards, lessons)."""
        return memory.read()

    @tool
    def write_project_memory(updates: dict[str, Any]) -> dict:
        """Update the Primary agent's living memory with new facts."""
        return memory.update(updates)

    return [
        create_github_issue,
        update_issue_label,
        add_issue_comment,
        close_github_issue,
        list_open_issues,
        read_spec_file,
        read_project_memory,
        write_project_memory,
    ]
