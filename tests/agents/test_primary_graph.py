# tests/agents/test_primary_graph.py
import pytest
from sdlc_agent.agents.primary.graph import build_primary_graph
from sdlc_agent.agents.primary.memory import ProjectMemory
from sdlc_agent.mcp.github import FixtureGitHubProject
from sdlc_agent.config import HitlConfig, RootModelConfig


@pytest.fixture
def github_client(tmp_path):
    (tmp_path / "specs.md").write_text("# Spec\n- Build a login feature")
    return FixtureGitHubProject(repo_root=tmp_path)


@pytest.fixture
def memory(tmp_path):
    return ProjectMemory(path=tmp_path / "memory.md")


def test_primary_graph_compiles(github_client, memory):
    graph = build_primary_graph(
        github=github_client,
        memory=memory,
        model_config=RootModelConfig(),
        hitl_config=HitlConfig(),
        developer_subgraph=None,
        reviewer_subgraph=None,
        release_subgraph=None,
    )
    assert graph is not None


def test_primary_graph_has_expected_nodes(github_client, memory):
    graph = build_primary_graph(
        github=github_client,
        memory=memory,
        model_config=RootModelConfig(),
        hitl_config=HitlConfig(),
        developer_subgraph=None,
        reviewer_subgraph=None,
        release_subgraph=None,
    )
    node_names = set(graph.get_graph().nodes.keys())
    for expected in ["intake", "create_issues", "assign_development",
                     "assign_review", "assign_release", "close_issue", "handle_rejection"]:
        assert expected in node_names, f"missing node: {expected}"
