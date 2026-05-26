from pathlib import Path
import textwrap
from sdlc_agent.config import load_root_agent_config, DockerConfig, MemoryConfig, HitlConfig


def test_docker_config_defaults():
    cfg = DockerConfig()
    assert cfg.developer_image == "sdlc-developer:latest"
    assert cfg.reviewer_image == "sdlc-reviewer:latest"
    assert cfg.release_image == "sdlc-release:latest"


def test_memory_config_defaults():
    cfg = MemoryConfig()
    assert cfg.project_memory_path == ".deepagent/memory.md"


def test_hitl_config_defaults():
    cfg = HitlConfig()
    assert cfg.require_release_approval is True
    assert cfg.max_retries == 3


def test_load_config_with_new_keys(tmp_path):
    yaml_text = textwrap.dedent("""
        target:
          repo_url: https://github.com/owner/repo
        docker:
          developer_image: my-dev:v2
        hitl:
          max_retries: 5
    """)
    cfg_file = tmp_path / "sdlc-agent.yaml"
    cfg_file.write_text(yaml_text)
    cfg = load_root_agent_config(cfg_file)
    assert cfg.docker.developer_image == "my-dev:v2"
    assert cfg.hitl.max_retries == 5
    assert cfg.memory.project_memory_path == ".deepagent/memory.md"
