"""GitHub-native lifecycle clients.

The first implementation is an in-memory/fixture client used by tests and demos.
It models the surface the orchestrator and subagents need from GitHub Issues
without requiring network access. A live GitHub implementation can replace this
class behind the same method surface.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from sdlc_agent.mcp.client import HandshakeResult


class GitHubProjectError(RuntimeError):
    """Base for GitHub lifecycle client failures."""


_ACCEPTANCE_CRITERIA_HEADER = re.compile(r"(?im)^##\s+Acceptance Criteria\s*$")


def parse_acceptance_criteria_from_issue_body(body: str) -> list[str]:
    """Extract checklist lines under ``## Acceptance Criteria`` from an issue body."""
    match = _ACCEPTANCE_CRITERIA_HEADER.search(body)
    if not match:
        return []
    section = body[match.end() :]
    next_h2 = re.search(r"(?im)^##\s+\S", section)
    if next_h2:
        section = section[: next_h2.start()]
    items: list[str] = []
    for raw in section.splitlines():
        line = raw.strip()
        if not line.startswith("-"):
            continue
        text = line[1:].strip()
        text = re.sub(r"^\[[ xX]\]\s*", "", text)
        if text:
            items.append(text)
    return items


def issue_number_from_project_item_id(item_id: str) -> int:
    match = re.fullmatch(r"ISSUE_(\d+)", item_id)
    if not match:
        raise GitHubProjectError(f"issue item id expected in form ISSUE_<number>: {item_id!r}")
    return int(match.group(1))


class GitHubSpecDocument(BaseModel):
    path: str
    body: str


class GitHubIssueDraft(BaseModel):
    title: str
    body: str
    acceptance_criteria: list[str] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)


class GitHubIssue(BaseModel):
    number: int
    title: str
    body: str
    url: str
    state: str = "open"
    labels: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)


class GitHubPullRequest(BaseModel):
    number: int
    title: str
    url: str
    state: str = "open"
    draft: bool = False


class GitHubProjectItem(BaseModel):
    item_id: str
    issue_number: int
    title: str
    status: str = "Backlog"
    acceptance_criteria: list[str] = Field(default_factory=list)


@runtime_checkable
class GitHubProjectClient(Protocol):
    server_name: str

    def handshake(self) -> HandshakeResult: ...
    def read_specs(self, relative_path: str = "specs.md") -> GitHubSpecDocument: ...
    def list_project_items(self) -> list[GitHubProjectItem]: ...
    def create_issue(self, draft: GitHubIssueDraft | dict) -> GitHubIssue: ...
    def get_issue(self, number: int) -> GitHubIssue: ...
    def add_issue_to_project(
        self, issue: GitHubIssue, *, status: str = "Backlog"
    ) -> GitHubProjectItem: ...
    def get_project_item(self, item_id: str) -> GitHubProjectItem: ...
    def update_project_status(self, item_id: str, status: str) -> GitHubProjectItem: ...
    def close_issue(self, number: int) -> GitHubIssue: ...
    def create_pull_request(
        self,
        *,
        title: str,
        body: str = "",
        head: str,
        base: str,
        draft: bool = False,
    ) -> GitHubPullRequest: ...


@dataclass
class GitHubProjectStub:
    """Phase-0 handshake stub for GitHub issue lifecycle."""

    server_name: str = "github-project-stub"

    def handshake(self) -> HandshakeResult:
        return HandshakeResult(
            ok=True,
            server=self.server_name,
            transport="in-process",
            detail="stub GitHub issue lifecycle client",
        )


@dataclass
class FixtureGitHubProject:
    """In-memory GitHub Issues lifecycle client rooted at a target repository."""

    repo_root: Path
    project_name: str = "SDLC"
    owner: str = "local"
    repository: str | None = None
    server_name: str = "github-project-fixture"
    _issues: dict[int, GitHubIssue] = field(default_factory=dict, init=False, repr=False)
    _items: dict[str, GitHubProjectItem] = field(default_factory=dict, init=False, repr=False)
    _pull_requests: dict[int, GitHubPullRequest] = field(default_factory=dict, init=False, repr=False)
    _next_issue_number: int = field(default=1, init=False, repr=False)
    _next_pr_number: int = field(default=1, init=False, repr=False)

    def __post_init__(self) -> None:
        self.repo_root = self.repo_root.resolve()
        if self.repository is None:
            self.repository = self.repo_root.name

    def handshake(self) -> HandshakeResult:
        ok = self.repo_root.is_dir()
        detail = f"github issues for {self.owner}/{self.repository}"
        if not ok:
            detail = f"target repo missing: {self.repo_root}"
        return HandshakeResult(
            ok=ok,
            server=self.server_name,
            transport="fixture",
            detail=detail,
        )

    def read_specs(self, relative_path: str = "specs.md") -> GitHubSpecDocument:
        path = self._resolve_within_repo(relative_path)
        if not path.is_file():
            raise GitHubProjectError(f"spec file not found: {relative_path}")
        return GitHubSpecDocument(
            path=path.relative_to(self.repo_root).as_posix(),
            body=path.read_text(encoding="utf-8"),
        )

    def list_project_items(self) -> list[GitHubProjectItem]:
        return sorted(self._items.values(), key=lambda item: item.item_id)

    def create_issue(self, draft: GitHubIssueDraft | dict) -> GitHubIssue:
        parsed = GitHubIssueDraft.model_validate(draft)
        number = self._next_issue_number
        self._next_issue_number += 1
        issue = GitHubIssue(
            number=number,
            title=parsed.title,
            body=self._render_issue_body(parsed),
            url=f"https://github.com/{self.owner}/{self.repository}/issues/{number}",
            labels=list(parsed.labels),
            acceptance_criteria=list(parsed.acceptance_criteria),
        )
        self._issues[number] = issue
        return issue

    def get_issue(self, number: int) -> GitHubIssue:
        try:
            return self._issues[number]
        except KeyError as e:
            raise GitHubProjectError(f"issue not found: {number}") from e

    def add_issue_to_project(
        self, issue: GitHubIssue, *, status: str = "Backlog"
    ) -> GitHubProjectItem:
        item_id = f"ISSUE_{issue.number}"
        item = GitHubProjectItem(
            item_id=item_id,
            issue_number=issue.number,
            title=issue.title,
            status=status,
            acceptance_criteria=list(issue.acceptance_criteria),
        )
        self._items[item_id] = item
        return item

    def get_project_item(self, item_id: str) -> GitHubProjectItem:
        try:
            return self._items[item_id]
        except KeyError as e:
            raise GitHubProjectError(f"project item not found: {item_id}") from e

    def update_project_status(self, item_id: str, status: str) -> GitHubProjectItem:
        item = self._get_or_create_project_item(item_id)
        updated = item.model_copy(update={"status": status})
        self._items[item_id] = updated
        return updated

    def validate_project_statuses(self, statuses: list[str]) -> None:
        for status in statuses:
            if not status or not status.strip():
                raise GitHubProjectError("empty issue lifecycle status")

    def close_issue(self, number: int) -> GitHubIssue:
        issue = self.get_issue(number)
        closed = issue.model_copy(update={"state": "closed"})
        self._issues[number] = closed
        return closed

    def create_pull_request(
        self,
        *,
        title: str,
        body: str = "",
        head: str,
        base: str,
        draft: bool = False,
    ) -> GitHubPullRequest:
        number = self._next_pr_number
        self._next_pr_number += 1
        repo = self.repository or self.repo_root.name
        pr = GitHubPullRequest(
            number=number,
            title=title,
            url=f"https://github.com/{self.owner}/{repo}/pull/{number}",
            draft=draft,
        )
        self._pull_requests[number] = pr
        _ = body, head, base  # fixture ignores merge metadata
        return pr

    def _get_or_create_project_item(self, item_id: str) -> GitHubProjectItem:
        if item_id in self._items:
            return self._items[item_id]
        issue_number = issue_number_from_project_item_id(item_id)
        issue = self.get_issue(issue_number)
        ac = list(issue.acceptance_criteria) or parse_acceptance_criteria_from_issue_body(
            issue.body
        )
        item = GitHubProjectItem(
            item_id=item_id,
            issue_number=issue.number,
            title=issue.title,
            status="Backlog",
            acceptance_criteria=ac,
        )
        self._items[item_id] = item
        return item

    def _resolve_within_repo(self, relative_path: str) -> Path:
        if not relative_path:
            raise GitHubProjectError("empty spec path")
        candidate = (self.repo_root / relative_path).resolve()
        try:
            candidate.relative_to(self.repo_root)
        except ValueError as e:
            raise GitHubProjectError(f"path escapes target repo: {relative_path}") from e
        return candidate

    @staticmethod
    def _render_issue_body(draft: GitHubIssueDraft) -> str:
        ac = "\n".join(f"- [ ] {item}" for item in draft.acceptance_criteria)
        if not ac:
            ac = "- [ ] Acceptance criteria missing"
        return f"{draft.body.strip()}\n\n## Acceptance Criteria\n{ac}\n"
