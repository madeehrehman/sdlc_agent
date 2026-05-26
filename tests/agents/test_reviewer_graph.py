# tests/agents/test_reviewer_graph.py
import pytest, os, subprocess
from sdlc_agent.agents.reviewer.graph import build_reviewer_graph
from sdlc_agent.agents.reviewer.tools import make_reviewer_tools
from sdlc_agent.mcp.git import LocalGitClient
from sdlc_agent.mcp.github import FixtureGitHubProject
from sdlc_agent.config import RootModelConfig


@pytest.fixture
def git_client(tmp_path):
    env = {**os.environ, "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "t@t.com",
           "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "t@t.com"}
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "--allow-empty", "-m", "init"], cwd=tmp_path,
                   check=True, capture_output=True, env=env)
    return LocalGitClient(repo_root=tmp_path)


@pytest.fixture
def github_client(tmp_path):
    return FixtureGitHubProject(repo_root=tmp_path)


def test_reviewer_tools_created(git_client, github_client, tmp_path):
    tools = make_reviewer_tools(git_client=git_client, github=github_client, repo_root=tmp_path)
    names = [t.name for t in tools]
    assert "read_pr_diff" in names
    assert "read_file_readonly" in names
    assert "github_approve_pr" in names
    assert "github_request_changes" in names


def test_reviewer_graph_compiles(git_client, github_client, tmp_path):
    graph = build_reviewer_graph(git_client=git_client, github=github_client,
                                 repo_root=tmp_path, model_config=RootModelConfig())
    assert graph is not None
