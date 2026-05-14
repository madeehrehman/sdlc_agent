"""Config schema + loader for `.deepagent/config.yaml` (spec §5.1)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, model_validator


class ProjectConfig(BaseModel):
    """Identifies the target repository the agent attaches to."""

    name: str
    repo_root: Path = Field(default=Path("."))


class RoleModelConfig(BaseModel):
    """Per-agent OpenAI model routing for live runs."""

    orchestrator: str = "gpt-4.1"
    backlog_analyzer: str = "gpt-4.1"
    developer: str = "gpt-4.1"
    pr_reviewer: str = "gpt-4.1"


class ModelConfig(BaseModel):
    """LLM model selection for the target repo runtime."""

    provider: Literal["openai"] = "openai"
    name: str = "gpt-4o-mini"
    temperature: float = 0.0
    roles: RoleModelConfig = Field(default_factory=RoleModelConfig)


class RootModelConfig(BaseModel):
    """Root control-plane model config.

    Secrets are intentionally excluded; OPENAI_API_KEY remains in environment.
    """

    provider: Literal["openai"] = "openai"
    default: str = "gpt-4o-mini"
    temperature: float = 0.0
    roles: RoleModelConfig = Field(default_factory=RoleModelConfig)


class MCPEndpointConfig(BaseModel):
    """A single MCP server endpoint. `stub` means use the in-process stub."""

    type: Literal["stub", "http"] = "stub"
    url: str | None = None


class MCPConfig(BaseModel):
    git: MCPEndpointConfig = Field(default_factory=MCPEndpointConfig)


class GitHubConfig(BaseModel):
    """GitHub repo/project settings for the target repository lifecycle."""

    repo_url: str | None = None
    owner: str | None = None
    repository: str
    project_name: str = "SDLC"
    specs_path: str = "specs.md"
    develop_branch: str = "develop"
    release_branch: str = "release"
    main_branch: str = "main"
    lifecycle_client: Literal["fixture", "mcp"] = "fixture"


class GateConfig(BaseModel):
    """Per spec §4 + §11 Phase 4: human-in-the-loop is opt-in per gate."""

    hitl_requirements_gate: bool = False
    hitl_review_gate: bool = False


class DeepAgentConfig(BaseModel):
    """Top-level config persisted at `.deepagent/config.yaml`."""

    project: ProjectConfig
    model: ModelConfig = Field(default_factory=ModelConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    github: GitHubConfig
    gates: GateConfig = Field(default_factory=GateConfig)

    @classmethod
    def from_yaml(cls, path: Path) -> "DeepAgentConfig":
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls.model_validate(data)

    def to_yaml(self, path: Path) -> None:
        data = self.model_dump(mode="json")
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    @classmethod
    def default_for_repo(cls, repo_root: Path, project_name: str | None = None) -> "DeepAgentConfig":
        return cls(
            project=ProjectConfig(
                name=project_name or repo_root.resolve().name,
                repo_root=repo_root.resolve(),
            ),
            github=GitHubConfig(repository=repo_root.resolve().name),
        )


class ParsedGitHubRepo(BaseModel):
    owner: str
    repository: str


def parse_github_repo_url(repo_url: str) -> ParsedGitHubRepo:
    """Parse ``https://github.com/<owner>/<repo>[.git]`` into owner/repo."""
    parsed = urlparse(repo_url)
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() != "github.com":
        raise ValueError(f"unsupported GitHub repo URL: {repo_url!r}")
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) != 2:
        raise ValueError(f"expected GitHub repo URL with owner/repo: {repo_url!r}")
    repo = parts[1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not parts[0] or not repo:
        raise ValueError(f"expected GitHub repo URL with owner/repo: {repo_url!r}")
    return ParsedGitHubRepo(owner=parts[0], repository=repo)


class TargetRepoConfig(BaseModel):
    """Root config for the target project the master agent should operate on."""

    repo_url: str
    specs_path: str = "specs.md"
    owner: str | None = None
    repository: str | None = None
    project_name: str | None = None

    @model_validator(mode="after")
    def derive_from_repo_url(self) -> "TargetRepoConfig":
        parsed = parse_github_repo_url(self.repo_url)
        if self.owner is None:
            self.owner = parsed.owner
        if self.repository is None:
            self.repository = parsed.repository
        if self.project_name is None:
            self.project_name = self.repository
        return self


class RootGitHubRuntimeConfig(BaseModel):
    """Non-secret GitHub runtime behavior for root SDLC agent runs."""

    lifecycle_client: Literal["fixture", "mcp"] = "mcp"
    project_name_from_repo: bool = True
    develop_branch: str = "develop"
    release_branch: str = "release"
    main_branch: str = "main"


class RootAgentConfig(BaseModel):
    """Root-level SDLC master config loaded from ``sdlc-agent.yaml``."""

    target: TargetRepoConfig
    github: RootGitHubRuntimeConfig = Field(default_factory=RootGitHubRuntimeConfig)
    model: RootModelConfig = Field(default_factory=RootModelConfig)

    @classmethod
    def from_yaml(
        cls,
        path: Path,
        *,
        data: dict | None = None,
    ) -> "RootAgentConfig":
        payload = data if data is not None else yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls.model_validate(payload or {})

    def to_deepagent_config(self, repo_root: Path) -> DeepAgentConfig:
        repository = self.target.repository or parse_github_repo_url(self.target.repo_url).repository
        owner = self.target.owner or parse_github_repo_url(self.target.repo_url).owner
        explicit_project_name = "project_name" in self.target.model_fields_set
        if explicit_project_name:
            project_name = self.target.project_name or repository
        elif self.github.project_name_from_repo:
            project_name = repository
        else:
            project_name = self.target.project_name or repository
        return DeepAgentConfig(
            project=ProjectConfig(name=repository, repo_root=repo_root.resolve()),
            model=ModelConfig(
                provider=self.model.provider,
                name=self.model.default,
                temperature=self.model.temperature,
                roles=self.model.roles,
            ),
            github=GitHubConfig(
                repo_url=self.target.repo_url,
                owner=owner,
                repository=repository,
                project_name=project_name,
                specs_path=self.target.specs_path,
                develop_branch=self.github.develop_branch,
                release_branch=self.github.release_branch,
                main_branch=self.github.main_branch,
                lifecycle_client=self.github.lifecycle_client,
            ),
        )


def load_root_agent_config(
    path: Path = Path("sdlc-agent.yaml"),
    *,
    env_path: Path = Path(".env"),
) -> RootAgentConfig:
    """Load secrets from ``.env`` first, then parse root ``sdlc-agent.yaml``."""
    load_dotenv(env_path, override=False)
    return RootAgentConfig.from_yaml(path)
