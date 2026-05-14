"""Runtime assembly for live SDLC agent runs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from sdlc_agent.config import DeepAgentConfig, RootAgentConfig, load_root_agent_config
from sdlc_agent.contracts import SubagentName
from sdlc_agent.llm.factory import build_role_openai_clients
from sdlc_agent.mcp.factory import build_github_project_client
from sdlc_agent.mcp.git import LocalGitClient
from sdlc_agent.mcp.github import GitHubProjectClient
from sdlc_agent.memory.paths import DeepAgentPaths
from sdlc_agent.memory.trajectories import TrajectoryRecorder
from sdlc_agent.orchestrator.dispatcher import Orchestrator, SubagentRegistry
from sdlc_agent.sandbox import LocalSubprocessSandbox
from sdlc_agent.skills import SkillLoader
from sdlc_agent.subagents import BacklogAnalyzer, DeveloperTester, PRReviewer


@dataclass
class SDLCRuntime:
    root_config: RootAgentConfig
    config: DeepAgentConfig
    paths: DeepAgentPaths
    github: GitHubProjectClient
    llm_clients: dict[SubagentName | str, Any]
    registry: SubagentRegistry
    orchestrator: Orchestrator

    def close(self) -> None:
        close = getattr(self.github, "close", None)
        if callable(close):
            close()


def build_sdlc_runtime(
    *,
    root_config_path: Path = Path("sdlc-agent.yaml"),
    env_path: Path = Path(".env"),
    target_repo_root: Path | None = None,
    session_id: str = "runtime",
    github_client_factory: Callable[..., GitHubProjectClient] = build_github_project_client,
    openai_client_factory: Callable[..., Any] | None = None,
) -> SDLCRuntime:
    """Load root config and assemble live clients, subagents, and orchestrator."""
    root_config = load_root_agent_config(root_config_path, env_path=env_path)
    repo_root = (target_repo_root or Path(root_config.target.repository or ".")).resolve()
    repo_root.mkdir(parents=True, exist_ok=True)

    config = root_config.to_deepagent_config(repo_root)
    paths = DeepAgentPaths(repo_root=repo_root)
    paths.root.mkdir(parents=True, exist_ok=True)
    config.to_yaml(paths.config_yaml)

    github = github_client_factory(config)
    try:
        llm_clients = build_role_openai_clients(
            config.model,
            client_factory=openai_client_factory or _default_openai_client_factory,
        )
        skills = SkillLoader()
        recorder = TrajectoryRecorder(paths, session_id=session_id)
        sandbox = LocalSubprocessSandbox(root=repo_root)

        registry: SubagentRegistry = {
            SubagentName.BACKLOG_ANALYZER: BacklogAnalyzer(
                llm=llm_clients[SubagentName.BACKLOG_ANALYZER],
                github=github,
                skills=skills,
                recorder=recorder,
            ),
            SubagentName.DEVELOPER: DeveloperTester(
                llm=llm_clients[SubagentName.DEVELOPER],
                sandbox=sandbox,
                skills=skills,
                recorder=recorder,
            ),
            SubagentName.PR_REVIEWER: PRReviewer(
                llm=llm_clients[SubagentName.PR_REVIEWER],
                git=LocalGitClient(repo_root=repo_root),
                skills=skills,
                recorder=recorder,
            ),
        }
        orchestrator = Orchestrator(
            paths=paths,
            registry=registry,
            gates=config.gates,
            session_id=session_id,
            github=github,
        )
    except Exception:
        close = getattr(github, "close", None)
        if callable(close):
            close()
        raise
    return SDLCRuntime(
        root_config=root_config,
        config=config,
        paths=paths,
        github=github,
        llm_clients=llm_clients,
        registry=registry,
        orchestrator=orchestrator,
    )


def _default_openai_client_factory(**kwargs: Any) -> Any:
    from sdlc_agent.llm import OpenAIClient

    return OpenAIClient(**kwargs)
