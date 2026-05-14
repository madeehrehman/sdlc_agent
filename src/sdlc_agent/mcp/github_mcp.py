"""Live GitHub Issues/Projects lifecycle adapter backed by GitHub MCP tools."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
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
class _StatusField:
    field_id: str
    options_by_name: dict[str, str | int]


@dataclass
class GitHubMCPProjectClient:
    """GitHub Project lifecycle client implemented with official GitHub MCP tools."""

    tool_client: MCPToolClient
    owner: str
    repository: str
    project_name: str
    project_number: int | None = None
    specs_ref: str | None = None
    status_field_name: str = "Status"
    server_name: str = "github-mcp-project"
    _status_field: _StatusField | None = field(default=None, init=False, repr=False)

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
        project_number = self._project_number()
        status_field = self._status_field_metadata()
        all_items: list[GitHubProjectItem] = []
        after: str | None = None
        while True:
            args: dict[str, Any] = {
                "method": "list_project_items",
                "owner": self.owner,
                "project_number": project_number,
                "fields": [status_field.field_id],
                "per_page": 50,
            }
            if after:
                args["after"] = after
            payload = self.tool_client.call_tool("projects_list", args)
            data = _unwrap(payload)
            raw_items = data.get("items") or data.get("project_items") or data.get("nodes") or []
            all_items.extend(self._normalize_project_item(item) for item in raw_items)
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
            fallback_body=body,
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
        project_number = self._project_number()
        self._status_option_id(status)
        payload = self.tool_client.call_tool(
            "projects_write",
            {
                "method": "add_project_item",
                "owner": self.owner,
                "project_number": project_number,
                "item_owner": self.owner,
                "item_repo": self.repository,
                "item_type": "issue",
                "issue_number": issue.number,
            },
        )
        data = _unwrap(payload)
        item_id = data.get("item_id") or data.get("database_id") or data.get("number")
        if item_id is None or not _is_numeric_id(item_id):
            item_id = self._project_item_id_for_issue(issue.number)
        if item_id is None:
            raise GitHubProjectError(
                f"numeric project item id missing from MCP response: {payload!r}"
            )
        update_item_id = _coerce_numeric_id(item_id, "project item id")
        self.update_project_status(str(update_item_id), status)
        return GitHubProjectItem(
            item_id=str(update_item_id),
            issue_number=issue.number,
            title=issue.title,
            status=status,
            acceptance_criteria=list(issue.acceptance_criteria),
        )

    def get_project_item(self, item_id: str) -> GitHubProjectItem:
        payload = self.tool_client.call_tool(
            "projects_get",
            {
                "method": "get_project_item",
                "owner": self.owner,
                "project_number": self._project_number(),
                "item_id": _coerce_numeric_id(item_id, "project item id"),
            },
        )
        return self._normalize_project_item(_unwrap(payload))

    def update_project_status(self, item_id: str, status: str) -> GitHubProjectItem:
        project_number = self._project_number()
        status_field = self._status_field_metadata()
        option_id = self._status_option_id(status)
        payload = self.tool_client.call_tool(
            "projects_write",
            {
                "method": "update_project_item",
                "owner": self.owner,
                "project_number": project_number,
                "item_id": _coerce_numeric_id(item_id, "project item id"),
                "updated_field": {
                    "id": _preserve_numeric_id(status_field.field_id),
                    "value": option_id,
                },
            },
        )
        data = _unwrap(payload)
        return GitHubProjectItem(
            item_id=str(data.get("item_id") or data.get("id") or item_id),
            issue_number=int(data.get("issue_number") or 0),
            title=str(data.get("title") or ""),
            status=str(data.get("status") or status),
            acceptance_criteria=list(data.get("acceptance_criteria") or []),
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
        return _normalize_issue(_unwrap(payload))

    def close(self) -> None:
        self.tool_client.close()

    def validate_project_statuses(self, statuses: list[str]) -> None:
        for status in statuses:
            self._status_option_id(status)

    def _project_number(self) -> int:
        if self.project_number is not None:
            return self.project_number
        payload = self.tool_client.call_tool(
            "projects_list",
            {
                "method": "list_projects",
                "owner": self.owner,
                "query": self.project_name,
            },
        )
        data = _unwrap(payload)
        projects = data.get("projects") or data.get("items") or data.get("nodes") or []
        for project in projects:
            title = project.get("title") or project.get("name")
            if title == self.project_name:
                self.project_number = int(project["number"])
                return self.project_number
        raise GitHubProjectError(f"GitHub Project not found: {self.project_name}")

    def _status_field_metadata(self) -> _StatusField:
        if self._status_field is not None:
            return self._status_field
        payload = self.tool_client.call_tool(
            "projects_list",
            {
                "method": "list_project_fields",
                "owner": self.owner,
                "project_number": self._project_number(),
            },
        )
        data = _unwrap(payload)
        fields = data.get("fields") or data.get("items") or data.get("nodes") or []
        for field_data in fields:
            if field_data.get("name") != self.status_field_name:
                continue
            options = {
                str(option["name"]): _preserve_numeric_id(option["id"])
                for option in field_data.get("options", [])
                if "name" in option and "id" in option
            }
            self._status_field = _StatusField(
                field_id=str(field_data["id"]),
                options_by_name=options,
            )
            return self._status_field
        raise GitHubProjectError(f"project field not found: {self.status_field_name}")

    def _status_option_id(self, status: str) -> str | int:
        status_field = self._status_field_metadata()
        option_id = status_field.options_by_name.get(status)
        if option_id is None:
            known = ", ".join(sorted(status_field.options_by_name)) or "(none)"
            raise GitHubProjectError(f"unknown project status {status!r}; known: {known}")
        return option_id

    def _project_item_id_for_issue(self, issue_number: int) -> int | None:
        for item in self.list_project_items():
            if item.issue_number == issue_number and _is_numeric_id(item.item_id):
                return _coerce_numeric_id(item.item_id, "project item id")
        return None

    def _normalize_project_item(self, item: dict[str, Any]) -> GitHubProjectItem:
        issue = item.get("issue") or item.get("content") or {}
        issue_number = item.get("issue_number") or issue.get("number") or 0
        return GitHubProjectItem(
            item_id=str(item.get("item_id") or item.get("id")),
            issue_number=int(issue_number),
            title=str(item.get("title") or issue.get("title") or ""),
            status=str(item.get("status") or _field_value(item, self.status_field_name) or ""),
            acceptance_criteria=list(item.get("acceptance_criteria") or []),
        )


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


def _preserve_numeric_id(value: Any) -> str | int:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return str(value)


def _is_numeric_id(value: Any) -> bool:
    return isinstance(value, int) or (isinstance(value, str) and value.isdigit())


def _coerce_numeric_id(value: Any, label: str) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    raise GitHubProjectError(f"{label} must be numeric for GitHub MCP: {value!r}")


def _normalize_issue(
    data: dict[str, Any],
    *,
    fallback_body: str | None = None,
    acceptance_criteria: list[str] | None = None,
) -> GitHubIssue:
    labels = data.get("labels") or []
    normalized_labels = [
        str(label.get("name")) if isinstance(label, dict) else str(label)
        for label in labels
    ]
    return GitHubIssue(
        number=int(data["number"]),
        title=str(data.get("title") or ""),
        body=str(data.get("body") or fallback_body or ""),
        url=str(data.get("url") or data.get("html_url") or ""),
        state=str(data.get("state") or "open"),
        labels=normalized_labels,
        acceptance_criteria=list(acceptance_criteria or data.get("acceptance_criteria") or []),
    )


def _render_issue_body(draft: GitHubIssueDraft) -> str:
    ac = "\n".join(f"- [ ] {item}" for item in draft.acceptance_criteria)
    if not ac:
        ac = "- [ ] Acceptance criteria missing"
    return f"{draft.body.strip()}\n\n## Acceptance Criteria\n{ac}\n"


def _field_value(item: dict[str, Any], field_name: str) -> str | None:
    fields = item.get("fields") or item.get("field_values") or []
    for field in fields:
        if field.get("name") == field_name:
            return field.get("value") or field.get("text") or field.get("name")
    return None
