# tests/agents/test_developer_graph.py
import pytest, os, subprocess
from sdlc_agent.agents.developer.graph import build_developer_graph
from sdlc_agent.agents.developer.tools import make_developer_tools
from sdlc_agent.sandbox.local import LocalSubprocessSandbox
from sdlc_agent.mcp.git import LocalGitClient
from sdlc_agent.config import RootModelConfig


@pytest.fixture
def sandbox(tmp_path):
    return LocalSubprocessSandbox(root=tmp_path)


@pytest.fixture
def git_client(tmp_path):
    env = {**os.environ, "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@test.com",
           "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@test.com"}
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "--allow-empty", "-m", "init"],
                   cwd=tmp_path, check=True, capture_output=True, env=env)
    return LocalGitClient(repo_root=tmp_path)


def test_developer_tools_created(sandbox, git_client):
    tools = make_developer_tools(sandbox=sandbox, git_client=git_client)
    tool_names = [t.name for t in tools]
    assert "read_file" in tool_names
    assert "write_file" in tool_names
    assert "run_tests" in tool_names
    assert "search_codebase" in tool_names


def test_developer_graph_compiles(sandbox, git_client):
    graph = build_developer_graph(sandbox=sandbox, git_client=git_client, model_config=RootModelConfig())
    assert graph is not None


def test_write_read_file_tool(sandbox, git_client):
    tools = make_developer_tools(sandbox=sandbox, git_client=git_client)
    write = next(t for t in tools if t.name == "write_file")
    read = next(t for t in tools if t.name == "read_file")
    write.invoke({"relative_path": "src/hello.py", "content": "def hello(): return 42"})
    result = read.invoke({"relative_path": "src/hello.py"})
    assert "hello" in result
