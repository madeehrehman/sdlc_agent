"""Phase 2: live GitHub MCP adapter uses issues as lifecycle store."""

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
        return ["get_file_contents", "issue_write", "issue_read", "list_issues"]

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
        project_name="unused",
        specs_ref="main",
    )


def test_read_specs_uses_get_file_contents() -> None:
    fake = RecordingMCPToolClient(
        {
            ("get_file_contents", None): {
                "content": [
                    {
                        "type": "text",
                        "text": '{"path": "specs.md", "content": "# Spec\\nBuild tic tac toe."}',
                    }
                ]
            }
        }
    )

    spec = _client(fake).read_specs("specs.md")

    assert spec.path == "specs.md"
    assert "tic tac toe" in spec.body
    assert fake.calls == [
        (
            "get_file_contents",
            {
                "owner": "madeehrehman",
                "repo": "sdlc_agent_tictactoe",
                "path": "specs.md",
                "ref": "main",
            },
        )
    ]


def test_read_specs_extracts_resource_text_from_live_mcp_shape() -> None:
    fake = RecordingMCPToolClient(
        {
            ("get_file_contents", None): {
                "content": [
                    {
                        "type": "text",
                        "text": "successfully downloaded text file (SHA: abc123)",
                    },
                    {
                        "type": "resource",
                        "resource": {
                            "mimeType": "text/plain; charset=utf-8",
                            "text": "# Tic-Tac-Toe\n\nBuild a browser game.",
                        },
                    },
                ],
                "isError": False,
            }
        }
    )

    spec = _client(fake).read_specs("specs.md")

    assert spec.path == "specs.md"
    assert spec.body.startswith("# Tic-Tac-Toe")
    assert "successfully downloaded" not in spec.body


def test_create_issue_renders_acceptance_criteria_and_normalizes_live_shape() -> None:
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
    assert "## Acceptance Criteria" in fake.calls[0][1]["body"]


def test_list_project_items_lists_repo_issues_as_lifecycle_items() -> None:
    fake = RecordingMCPToolClient(
        {
            ("list_issues", None): {
                "issues": [
                    {
                        "number": 12,
                        "title": "Add board",
                        "body": "Body",
                        "url": "https://github.com/madeehrehman/sdlc_agent_tictactoe/issues/12",
                        "labels": [{"name": "status:backlog"}, {"name": "feature"}],
                    }
                ]
            }
        }
    )

    items = _client(fake).list_project_items()

    assert len(items) == 1
    assert items[0].item_id == "ISSUE_12"
    assert items[0].issue_number == 12
    assert items[0].status == "Backlog"
    assert fake.calls == [
        (
            "list_issues",
            {
                "owner": "madeehrehman",
                "repo": "sdlc_agent_tictactoe",
                "state": "open",
                "perPage": 100,
            },
        )
    ]


def test_add_issue_to_project_applies_status_label_without_project_api() -> None:
    fake = RecordingMCPToolClient(
        {
            ("issue_read", "get"): {
                "number": 12,
                "title": "Add board",
                "body": "Body",
                "url": "https://github.com/madeehrehman/sdlc_agent_tictactoe/issues/12",
                "labels": [{"name": "feature"}],
            },
            ("issue_write", "update"): {
                "number": 12,
                "title": "Add board",
                "body": "Body",
                "url": "https://github.com/madeehrehman/sdlc_agent_tictactoe/issues/12",
                "labels": [{"name": "feature"}, {"name": "status:ready"}],
            },
        }
    )
    issue = GitHubIssue(
        number=12,
        title="Add board",
        body="Body",
        url="https://github.com/madeehrehman/sdlc_agent_tictactoe/issues/12",
        labels=["feature"],
        acceptance_criteria=["AC"],
    )

    item = _client(fake).add_issue_to_project(issue, status="Ready")

    assert item.item_id == "ISSUE_12"
    assert item.status == "Ready"
    assert all(not call[0].startswith("projects_") for call in fake.calls)
    assert fake.calls[-1] == (
        "issue_write",
        {
            "method": "update",
            "owner": "madeehrehman",
            "repo": "sdlc_agent_tictactoe",
            "issue_number": 12,
            "labels": ["feature", "status:ready"],
        },
    )


def test_update_project_status_replaces_prior_status_label() -> None:
    fake = RecordingMCPToolClient(
        {
            ("issue_read", "get"): {
                "number": 12,
                "title": "Add board",
                "body": "Body",
                "url": "https://github.com/madeehrehman/sdlc_agent_tictactoe/issues/12",
                "labels": [{"name": "feature"}, {"name": "status:backlog"}],
            },
            ("issue_write", "update"): {
                "number": 12,
                "title": "Add board",
                "body": "Body",
                "url": "https://github.com/madeehrehman/sdlc_agent_tictactoe/issues/12",
                "labels": [{"name": "feature"}, {"name": "status:release-ready"}],
            },
        }
    )

    item = _client(fake).update_project_status("ISSUE_12", "Release Ready")

    assert item.status == "Release Ready"
    assert fake.calls[-1][1]["labels"] == ["feature", "status:release-ready"]


def test_update_project_status_rejects_non_issue_item_id() -> None:
    with pytest.raises(GitHubProjectError, match="issue item id"):
        _client(RecordingMCPToolClient({})).update_project_status("PVTI_12", "Done")


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
        _client(fake).read_specs("specs.md")


def test_close_issue_updates_issue_state() -> None:
    fake = RecordingMCPToolClient(
        {
            ("issue_write", "update"): {
                "id": "4449631857",
                "url": "https://github.com/madeehrehman/sdlc_agent_tictactoe/issues/12",
            }
        }
    )

    issue = _client(fake).close_issue(12)

    assert issue.number == 12
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
