"""Live GitHub Issues lifecycle adapter backed by GitHub MCP tools."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from sdlc_agent.mcp.client import HandshakeResult
from sdlc_agent.mcp.github import (
    GitHubIssue,
    GitHubIssueDraft,
    GitHubProjectError,
    GitHubProjectItem,
    GitHubSpecDocument,
)
from sdlc_agent.mcp.stdio import MCPToolClient


@dataclass
class GitHubMCPProjectClient:
    """GitHub issue lifecycle client implemented with official GitHub MCP tools.

    The class keeps the existing protocol method names for orchestrator
    compatibility, but live state is stored directly on GitHub Issues. Status is
    represented with exactly one ``status:<slug>`` label per issue.
    """

    tool_client: MCPToolClient
    owner: str
    repository: str
    project_name: str
    specs_ref: str | None = None
    server_name: str = "github-mcp-issues"

    def handshake(self) -> HandshakeResult:
        return self.tool_client.handshake()

    def read_specs(self, relative_path: str = "specs.md") -> GitHubSpecDocument:
        args: dict[str, Any] = {
            "owner": self.owner,
            "repo": self.repository,
            "path": relative_path,
        }
        if self.specs_ref:
            args["ref"] = self.specs_ref
        payload = self.tool_client.call_tool("get_file_contents", args)
        data = _unwrap(payload)
        body = data.get("content") or data.get("text") or data.get("body")
        if body is None:
            raise GitHubProjectError(f"spec content missing from MCP response: {payload!r}")
        return GitHubSpecDocument(path=data.get("path", relative_path), body=str(body))

    def list_project_items(self) -> list[GitHubProjectItem]:
        all_items: list[GitHubProjectItem] = []
        after: str | None = None
        while True:
            args: dict[str, Any] = {
                "owner": self.owner,
                "repo": self.repository,
                "state": "open",
                "perPage": 100,
            }
            if after:
                args["after"] = after
            payload = self.tool_client.call_tool("list_issues", args)
            data = _unwrap(payload)
            raw_issues = data.get("issues") or data.get("items") or data.get("nodes") or []
            all_items.extend(_issue_to_lifecycle_item(_normalize_issue(issue)) for issue in raw_issues)
            page_info = data.get("pageInfo") or data.get("page_info") or {}
            if not page_info.get("hasNextPage"):
                return all_items
            after = page_info.get("endCursor")
            if not after:
                return all_items

    def create_issue(self, draft: GitHubIssueDraft | dict) -> GitHubIssue:
        parsed = GitHubIssueDraft.model_validate(draft)
        body = _render_issue_body(parsed)
        payload = self.tool_client.call_tool(
            "issue_write",
            {
                "method": "create",
                "owner": self.owner,
                "repo": self.repository,
                "title": parsed.title,
                "body": body,
                "labels": list(parsed.labels),
            },
        )
        return _normalize_issue(
            _unwrap(payload),
            fallback_title=parsed.title,
            fallback_body=body,
            fallback_labels=list(parsed.labels),
            acceptance_criteria=list(parsed.acceptance_criteria),
        )

    def get_issue(self, number: int) -> GitHubIssue:
        payload = self.tool_client.call_tool(
            "issue_read",
            {
                "method": "get",
                "owner": self.owner,
                "repo": self.repository,
                "issue_number": number,
            },
        )
        return _normalize_issue(_unwrap(payload))

    def add_issue_to_project(
        self, issue: GitHubIssue, *, status: str = "Backlog"
    ) -> GitHubProjectItem:
        return self.update_project_status(f"ISSUE_{issue.number}", status)

    def get_project_item(self, item_id: str) -> GitHubProjectItem:
        return _issue_to_lifecycle_item(self.get_issue(_issue_number_from_item_id(item_id)))

    def update_project_status(self, item_id: str, status: str) -> GitHubProjectItem:
        issue_number = _issue_number_from_item_id(item_id)
        current = self.get_issue(issue_number)
        labels = _labels_without_status(current.labels)
        labels.append(_status_label(status))
        payload = self.tool_client.call_tool(
            "issue_write",
            {
                "method": "update",
                "owner": self.owner,
                "repo": self.repository,
                "issue_number": issue_number,
                "labels": labels,
            },
        )
        return _issue_to_lifecycle_item(
            _normalize_issue(
                _unwrap(payload),
                fallback_title=current.title,
                fallback_body=current.body,
                fallback_labels=labels,
                acceptance_criteria=current.acceptance_criteria,
            )
        )

    def close_issue(self, number: int) -> GitHubIssue:
        payload = self.tool_client.call_tool(
            "issue_write",
            {
                "method": "update",
                "owner": self.owner,
                "repo": self.repository,
                "issue_number": number,
                "state": "closed",
            },
        )
        return _normalize_issue(_unwrap(payload), fallback_state="closed")

    def close(self) -> None:
        self.tool_client.close()

    def validate_project_statuses(self, statuses: list[str]) -> None:
        for status in statuses:
            if not status or not status.strip():
                raise GitHubProjectError("empty issue lifecycle status")


def _unwrap(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("isError") is True:
        raise GitHubProjectError(_content_text(payload) or "GitHub MCP tool returned an error")
    if "content" in payload:
        text = _content_text(payload)
        if text:
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                return {"text": text}
            if isinstance(parsed, dict):
                return parsed
            return {"result": parsed}
    if "structuredContent" in payload and isinstance(payload["structuredContent"], dict):
        return payload["structuredContent"]
    if "structured_content" in payload and isinstance(payload["structured_content"], dict):
        return payload["structured_content"]
    if "data" in payload and isinstance(payload["data"], dict):
        return payload["data"]
    if "result" in payload and isinstance(payload["result"], dict):
        return payload["result"]
    return payload


def _content_text(payload: dict[str, Any]) -> str:
    content = payload.get("content")
    if isinstance(content, list):
        parts = [
            str(item.get("text"))
            for item in content
            if isinstance(item, dict) and item.get("text") is not None
        ]
        return "\n".join(parts)
    if isinstance(content, str):
        return content
    return ""


def _normalize_issue(
    data: dict[str, Any],
    *,
    fallback_title: str = "",
    fallback_body: str | None = None,
    fallback_labels: list[str] | None = None,
    fallback_state: str = "open",
    acceptance_criteria: list[str] | None = None,
) -> GitHubIssue:
    labels = data.get("labels") or fallback_labels or []
    normalized_labels = [
        str(label.get("name")) if isinstance(label, dict) else str(label)
        for label in labels
    ]
    url = str(data.get("url") or data.get("html_url") or "")
    number = data.get("number") or _issue_number_from_url(url)
    if number is None:
        raise GitHubProjectError(f"issue number missing from MCP response: {data!r}")
    return GitHubIssue(
        number=int(number),
        title=str(data.get("title") or fallback_title),
        body=str(data.get("body") or fallback_body or ""),
        url=url,
        state=str(data.get("state") or fallback_state),
        labels=normalized_labels,
        acceptance_criteria=list(acceptance_criteria or data.get("acceptance_criteria") or []),
    )


def _issue_to_lifecycle_item(issue: GitHubIssue) -> GitHubProjectItem:
    return GitHubProjectItem(
        item_id=f"ISSUE_{issue.number}",
        issue_number=issue.number,
        title=issue.title,
        status=_status_from_labels(issue.labels),
        acceptance_criteria=list(issue.acceptance_criteria),
    )


def _issue_number_from_url(url: str) -> int | None:
    match = re.search(r"/issues/(\d+)(?:$|[?#])", url)
    return int(match.group(1)) if match else None


def _issue_number_from_item_id(item_id: str) -> int:
    match = re.fullmatch(r"ISSUE_(\d+)", item_id)
    if not match:
        raise GitHubProjectError(f"issue item id expected in form ISSUE_<number>: {item_id!r}")
    return int(match.group(1))


def _status_label(status: str) -> str:
    if not status or not status.strip():
        raise GitHubProjectError("empty issue lifecycle status")
    slug = re.sub(r"[^a-z0-9]+", "-", status.lower()).strip("-")
    return f"status:{slug}"


def _status_from_labels(labels: list[str]) -> str:
    for label in labels:
        if label.startswith("status:"):
            slug = label.removeprefix("status:")
            return " ".join(part.capitalize() for part in slug.split("-") if part)
    return "Backlog"


def _labels_without_status(labels: list[str]) -> list[str]:
    return [label for label in labels if not label.startswith("status:")]


def _render_issue_body(draft: GitHubIssueDraft) -> str:
    ac = "\n".join(f"- [ ] {item}" for item in draft.acceptance_criteria)
    if not ac:
        ac = "- [ ] Acceptance criteria missing"
    return f"{draft.body.strip()}\n\n## Acceptance Criteria\n{ac}\n"
