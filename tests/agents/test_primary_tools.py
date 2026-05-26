import pytest
from pathlib import Path
from sdlc_agent.agents.primary.memory import ProjectMemory
from sdlc_agent.agents.primary.tools import make_primary_tools
from sdlc_agent.mcp.github import FixtureGitHubProject


@pytest.fixture
def tmp_memory(tmp_path):
    return ProjectMemory(path=tmp_path / "memory.md")


@pytest.fixture
def github_client(tmp_path):
    (tmp_path / "specs.md").write_text("# Spec\n- Build login")
    return FixtureGitHubProject(repo_root=tmp_path)


def test_memory_read_write(tmp_memory):
    tmp_memory.write({"architecture_decisions": ["Use FastAPI"], "coding_standards": {}})
    data = tmp_memory.read()
    assert data["architecture_decisions"] == ["Use FastAPI"]


def test_memory_update_merges(tmp_memory):
    tmp_memory.write({"architecture_decisions": ["Use FastAPI"], "lessons_learned": []})
    tmp_memory.update({"lessons_learned": ["Always write tests first"]})
    data = tmp_memory.read()
    assert "Always write tests first" in data["lessons_learned"]
    assert "Use FastAPI" in data["architecture_decisions"]


def test_make_primary_tools_returns_list(github_client, tmp_memory):
    tools = make_primary_tools(github=github_client, memory=tmp_memory)
    tool_names = [t.name for t in tools]
    assert "create_github_issue" in tool_names
    assert "close_github_issue" in tool_names
    assert "update_issue_label" in tool_names
    assert "read_project_memory" in tool_names
    assert "write_project_memory" in tool_names


def test_create_issue_tool(github_client, tmp_memory):
    tools = make_primary_tools(github=github_client, memory=tmp_memory)
    create_tool = next(t for t in tools if t.name == "create_github_issue")
    result = create_tool.invoke({
        "title": "Add login endpoint",
        "body": "As a user, I want to log in",
        "acceptance_criteria": ["Returns 200 on valid credentials"],
        "labels": ["Backlog"],
    })
    assert result["number"] == 1
    assert "github.com" in result["url"]
