"""Phase 2: live GitHub MCP adapter maps tools to lifecycle protocol."""

from __future__ import annotations

import pytest

from sdlc_agent.mcp.github import GitHubIssue, GitHubIssueDraft, GitHubProjectError
from sdlc_agent.mcp.github_mcp import GitHubMCPProjectClient


class RecordingMCPToolClient:
    server_name = "github-mcp-fake"

    def __init__(self, responses: dict[tuple[str, str | None], dict]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict]] = []

    def handshake(self):
        from sdlc_agent.mcp import HandshakeResult

        return HandshakeResult(ok=True, server=self.server_name, transport="fake")

    def list_tools(self) -> list[str]:
        return ["get_file_contents", "issue_write", "projects_list", "projects_get", "projects_write"]

    def call_tool(self, name: str, arguments: dict) -> dict:
        self.calls.append((name, arguments))
        key = (name, arguments.get("method"))
        return self.responses.get(key, self.responses.get((name, None), {}))

    def close(self) -> None:
        pass


def _client(fake: RecordingMCPToolClient) -> GitHubMCPProjectClient:
    return GitHubMCPProjectClient(
        tool_client=fake,
        owner="madeehrehman",
        repository="sdlc_agent_tictactoe",
        project_name="sdlc_agent_tictactoe",
        project_number=7,
        specs_ref="main",
    )


def test_read_specs_uses_get_file_contents() -> None:
    fake = RecordingMCPToolClient(
        {
            ("get_file_contents", None): {
                "content": [
                    {
                        "type": "text",
                        "text": '{"path": "spec.md", "content": "# Spec\\nBuild tic tac toe."}',
                    }
                ]
            }
        }
    )

    spec = _client(fake).read_specs("spec.md")

    assert spec.path == "spec.md"
    assert "tic tac toe" in spec.body
    assert fake.calls == [
        (
            "get_file_contents",
            {
                "owner": "madeehrehman",
                "repo": "sdlc_agent_tictactoe",
                "path": "spec.md",
                "ref": "main",
            },
        )
    ]


def test_create_issue_renders_acceptance_criteria_and_normalizes_issue() -> None:
    fake = RecordingMCPToolClient(
        {
            ("issue_write", "create"): {
                "number": 12,
                "title": "Add board",
                "body": "Body",
                "html_url": "https://github.com/madeehrehman/sdlc_agent_tictactoe/issues/12",
                "state": "open",
                "labels": [{"name": "feature"}],
            }
        }
    )

    issue = _client(fake).create_issue(
        GitHubIssueDraft(
            title="Add board",
            body="Render a playable board.",
            acceptance_criteria=["shows 3x3 grid", "allows moves"],
            labels=["feature"],
        )
    )

    assert issue.number == 12
    assert issue.labels == ["feature"]
    assert issue.acceptance_criteria == ["shows 3x3 grid", "allows moves"]
    assert fake.calls[0][0] == "issue_write"
    assert fake.calls[0][1]["method"] == "create"
    assert "## Acceptance Criteria" in fake.calls[0][1]["body"]


def test_create_issue_derives_number_from_url_when_mcp_omits_number() -> None:
    fake = RecordingMCPToolClient(
        {
            ("issue_write", "create"): {
                "id": "4449631857",
                "url": "https://github.com/madeehrehman/sdlc_agent_tictactoe/issues/17",
            }
        }
    )

    issue = _client(fake).create_issue(
        GitHubIssueDraft(
            title="Live-shaped issue",
            body="Body",
            acceptance_criteria=["AC"],
            labels=["sdlc-agent-live-test"],
        )
    )

    assert issue.number == 17
    assert issue.title == "Live-shaped issue"
    assert issue.labels == ["sdlc-agent-live-test"]


def test_add_issue_to_project_adds_item_and_sets_status() -> None:
    fake = RecordingMCPToolClient(
        {
            ("projects_write", "add_project_item"): {"item_id": 123, "title": "Add board"},
            ("projects_list", "list_project_fields"): {
                "fields": [
                    {
                        "id": 99,
                        "name": "Status",
                        "options": [
                            {"id": "opt_backlog", "name": "Backlog"},
                            {"id": "opt_ready", "name": "Ready"},
                        ],
                    }
                ]
            },
            ("projects_write", "update_project_item"): {"item_id": 123, "status": "Ready"},
        }
    )
    issue = GitHubIssue(
        number=12,
        title="Add board",
        body="Render a playable board.",
        url="https://github.com/madeehrehman/sdlc_agent_tictactoe/issues/12",
        acceptance_criteria=["shows 3x3 grid"],
    )
    fake.calls.clear()

    item = _client(fake).add_issue_to_project(issue, status="Ready")

    assert item.item_id == "123"
    assert item.status == "Ready"
    assert (
        "projects_write",
        {
            "method": "add_project_item",
            "owner": "madeehrehman",
                "owner_type": "user",
            "project_number": 7,
            "item_owner": "madeehrehman",
            "item_repo": "sdlc_agent_tictactoe",
            "item_type": "issue",
            "issue_number": 12,
        },
    ) in fake.calls
    assert fake.calls[-1][1]["updated_field"] == {
        "id": 99,
        "value": "opt_ready",
    }
    assert fake.calls[-1][1]["item_id"] == 123


def test_project_number_can_be_discovered_by_project_name() -> None:
    fake = RecordingMCPToolClient(
        {
            ("projects_list", "list_projects"): {
                "projects": [
                    {"number": 7, "title": "sdlc_agent_tictactoe"},
                ]
            },
            ("projects_list", "list_project_fields"): {
                "fields": [
                    {
                        "id": 99,
                        "name": "Status",
                        "options": [{"id": "opt_backlog", "name": "Backlog"}],
                    }
                ]
            },
            ("projects_list", "list_project_items"): {"items": []},
        }
    )
    client = GitHubMCPProjectClient(
        tool_client=fake,
        owner="madeehrehman",
        repository="sdlc_agent_tictactoe",
        project_name="sdlc_agent_tictactoe",
    )

    assert client.list_project_items() == []
    assert fake.calls[0] == (
        "projects_list",
        {
            "method": "list_projects",
            "owner": "madeehrehman",
                "owner_type": "user",
            "query": "sdlc_agent_tictactoe",
        },
    )
    assert fake.calls[-1] == (
        "projects_list",
        {
            "method": "list_project_items",
            "owner": "madeehrehman",
            "owner_type": "user",
            "project_number": 7,
            "fields": ["99"],
            "per_page": 50,
        },
    )


def test_update_status_rejects_unknown_status_option() -> None:
    fake = RecordingMCPToolClient(
        {
            ("projects_list", "list_project_fields"): {
                "fields": [
                    {
                        "id": "PVTSSF_status",
                        "name": "Status",
                        "options": [{"id": "opt_ready", "name": "Ready"}],
                    }
                ]
            }
        }
    )

    with pytest.raises(GitHubProjectError, match="unknown project status"):
        _client(fake).update_project_status("PVTI_12", "Blocked")


def test_mcp_error_envelope_raises_github_project_error() -> None:
    fake = RecordingMCPToolClient(
        {
            ("get_file_contents", None): {
                "isError": True,
                "content": [{"type": "text", "text": "Bad credentials"}],
            }
        }
    )

    with pytest.raises(GitHubProjectError, match="Bad credentials"):
        _client(fake).read_specs("spec.md")


def test_add_issue_to_project_preflights_status_before_mutating() -> None:
    fake = RecordingMCPToolClient(
        {
            ("projects_list", "list_project_fields"): {
                "fields": [
                    {
                        "id": 99,
                        "name": "Status",
                        "options": [{"id": "opt_ready", "name": "Ready"}],
                    }
                ]
            }
        }
    )
    issue = GitHubIssue(
        number=12,
        title="Add board",
        body="Body",
        url="https://github.com/madeehrehman/sdlc_agent_tictactoe/issues/12",
    )

    with pytest.raises(GitHubProjectError, match="unknown project status"):
        _client(fake).add_issue_to_project(issue, status="Backlog")

    assert all(call[0] != "projects_write" for call in fake.calls)


def test_add_issue_to_project_recovers_numeric_item_id_from_project_listing() -> None:
    fake = RecordingMCPToolClient(
        {
            ("projects_list", "list_project_fields"): {
                "fields": [
                    {
                        "id": 99,
                        "name": "Status",
                        "options": [{"id": "opt_backlog", "name": "Backlog"}],
                    }
                ]
            },
            ("projects_write", "add_project_item"): {"id": "PVTI_graphql_node"},
            ("projects_list", "list_project_items"): {
                "items": [
                    {
                        "item_id": 123,
                        "issue_number": 12,
                        "title": "Add board",
                        "status": "Backlog",
                    }
                ]
            },
            ("projects_write", "update_project_item"): {"item_id": 123, "status": "Backlog"},
        }
    )
    issue = GitHubIssue(
        number=12,
        title="Add board",
        body="Body",
        url="https://github.com/madeehrehman/sdlc_agent_tictactoe/issues/12",
    )

    item = _client(fake).add_issue_to_project(issue)

    assert item.item_id == "123"
    assert fake.calls[-1][1]["item_id"] == 123


def test_list_project_items_follows_next_cursor() -> None:
    class PagingMCPToolClient(RecordingMCPToolClient):
        def call_tool(self, name: str, arguments: dict) -> dict:
            self.calls.append((name, arguments))
            if arguments.get("method") == "list_project_fields":
                return {
                    "fields": [
                        {
                            "id": 99,
                            "name": "Status",
                            "options": [{"id": "opt_backlog", "name": "Backlog"}],
                        }
                    ]
                }
            if arguments.get("method") == "list_project_items" and "after" not in arguments:
                return {
                    "items": [{"item_id": 101, "issue_number": 1, "title": "One"}],
                    "pageInfo": {"hasNextPage": True, "endCursor": "cursor-1"},
                }
            if arguments.get("method") == "list_project_items":
                return {
                    "items": [{"item_id": 102, "issue_number": 2, "title": "Two"}],
                    "pageInfo": {"hasNextPage": False},
                }
            return {}

    fake = PagingMCPToolClient({})

    items = _client(fake).list_project_items()

    assert [item.issue_number for item in items] == [1, 2]
    assert fake.calls[-1][1]["after"] == "cursor-1"


def test_close_issue_updates_issue_state() -> None:
    fake = RecordingMCPToolClient(
        {
            ("issue_write", "update"): {
                "number": 12,
                "title": "Add board",
                "body": "Body",
                "html_url": "https://github.com/madeehrehman/sdlc_agent_tictactoe/issues/12",
                "state": "closed",
            }
        }
    )

    issue = _client(fake).close_issue(12)

    assert issue.state == "closed"
    assert fake.calls == [
        (
            "issue_write",
            {
                "method": "update",
                "owner": "madeehrehman",
                "repo": "sdlc_agent_tictactoe",
                "issue_number": 12,
                "state": "closed",
            },
        )
    ]
