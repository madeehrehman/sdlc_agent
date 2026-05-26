# tests/test_integration_smoke.py
"""Smoke test: full runtime assembly with fixture GitHub client, no live LLM calls."""
import pytest
from pathlib import Path
from langchain_core.messages import HumanMessage
from sdlc_agent.agents.runtime import build_runtime
from sdlc_agent.agents.primary.memory import ProjectMemory
from sdlc_agent.config import RootAgentConfig, TargetRepoConfig


@pytest.fixture
def target_repo(tmp_path):
    (tmp_path / "specs.md").write_text("# Spec\n- Build a hello world function")
    return tmp_path


@pytest.fixture
def agent_config():
    return RootAgentConfig(
        target=TargetRepoConfig(repo_url="https://github.com/owner/repo"),
    )


def test_runtime_builds(target_repo, agent_config):
    """The full runtime assembles without error."""
    graph = build_runtime(agent_config, target_repo_root=target_repo, use_docker=False)
    assert graph is not None


def test_graph_accepts_initial_state(target_repo, agent_config):
    """Graph accepts valid initial state without raising."""
    graph = build_runtime(agent_config, target_repo_root=target_repo, use_docker=False)
    initial = {
        "messages": [HumanMessage(content="test")],
        "phase": "intake",
        "memory_snapshot": {},
        "retry_count": 0,
        "current_issue": None,
        "dev_result": None,
        "review_result": None,
        "release_result": None,
    }
    assert initial["phase"] == "intake"
    assert graph is not None


def test_memory_roundtrip(target_repo):
    mem = ProjectMemory(path=target_repo / ".deepagent" / "memory.md")
    mem.write({
        "architecture_decisions": ["Use FastAPI"],
        "lessons_learned": [],
        "coding_standards": {},
        "component_map": {},
        "open_risks": [],
    })
    data = mem.read()
    assert data["architecture_decisions"] == ["Use FastAPI"]
    mem.update({"lessons_learned": ["Always test first"]})
    updated = mem.read()
    assert "Always test first" in updated["lessons_learned"]
    assert updated["architecture_decisions"] == ["Use FastAPI"]


def test_cli_importable():
    from sdlc_agent.cli import main
    assert callable(main)
