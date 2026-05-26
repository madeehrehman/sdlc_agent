# tests/agents/test_release_graph.py
import pytest, os, subprocess
from sdlc_agent.agents.release.graph import build_release_graph
from sdlc_agent.agents.release.tools import make_release_tools
from sdlc_agent.mcp.git import LocalGitClient
from sdlc_agent.config import RootModelConfig, HitlConfig, DockerConfig


@pytest.fixture
def git_client(tmp_path):
    env = {**os.environ, "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "t@t.com",
           "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "t@t.com"}
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "--allow-empty", "-m", "init"], cwd=tmp_path,
                   check=True, capture_output=True, env=env)
    return LocalGitClient(repo_root=tmp_path)


def test_release_tools_created(git_client):
    tools = make_release_tools(git_client=git_client, docker_config=DockerConfig())
    names = [t.name for t in tools]
    assert "generate_release_summary" in names
    assert "docker_build" in names
    assert "request_human_approval" in names


def test_release_graph_compiles(git_client):
    graph = build_release_graph(git_client=git_client, model_config=RootModelConfig(),
                                hitl_config=HitlConfig(), docker_config=DockerConfig())
    assert graph is not None
