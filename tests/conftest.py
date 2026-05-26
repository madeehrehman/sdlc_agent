"""Shared pytest fixtures + the `live` marker plumbing."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from dotenv import load_dotenv

from sdlc_agent.mcp.github import FixtureGitHubProject


load_dotenv()


# ----------------------------------------------------------------- live opt-in
def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-live",
        action="store_true",
        default=False,
        help="run tests marked `live` (hits the real OpenAI API)",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    for item in items:
        if "github_live" in item.keywords:
            if not config.getoption("--run-live"):
                item.add_marker(pytest.mark.skip(reason="GitHub MCP live tests opt-in via --run-live"))
            elif not os.environ.get("GITHUB_TOKEN"):
                item.add_marker(pytest.mark.skip(reason="GITHUB_TOKEN missing for GitHub MCP live test"))
            elif shutil.which("docker") is None:
                item.add_marker(pytest.mark.skip(reason="Docker missing for GitHub MCP live test"))
            continue
        if "live" in item.keywords:
            if not config.getoption("--run-live"):
                item.add_marker(pytest.mark.skip(reason="live tests opt-in via --run-live + OPENAI_API_KEY"))
            elif not os.environ.get("OPENAI_API_KEY"):
                item.add_marker(pytest.mark.skip(reason="--run-live set but OPENAI_API_KEY missing"))


# ---------------------------------------------------------------- common dirs
@pytest.fixture()
def tmp_repo(tmp_path: Path) -> Path:
    """A throwaway 'target repo' directory the agent can initialize into."""
    repo = tmp_path / "target_repo"
    repo.mkdir()
    return repo


@pytest.fixture()
def github_project(tmp_repo: Path) -> FixtureGitHubProject:
    """A fixture-backed GitHub Issues client with a living specs.md."""
    (tmp_repo / "specs.md").write_text(
        "# Product spec\n\n"
        "## Greeting utility\n"
        "The project needs greet(name) returning a hello-world string.\n",
        encoding="utf-8",
    )
    return FixtureGitHubProject(repo_root=tmp_repo)


# -------------------------------------------------------------- git fixtures
def _git(*args: str, cwd: Path) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


@pytest.fixture()
def small_git_repo(tmp_path: Path) -> dict[str, Any]:
    """Create a small two-commit git repo and return refs/paths the tests need.

    layout::

        repo/
          README.md           (added in base commit)
          src/feature.py      (added in head commit)
    """
    repo = tmp_path / "sample_repo"
    repo.mkdir()
    _git("init", "-q", "-b", "main", cwd=repo)
    _git("config", "user.email", "test@example.com", cwd=repo)
    _git("config", "user.name", "Test User", cwd=repo)
    _git("config", "commit.gpgsign", "false", cwd=repo)

    (repo / "README.md").write_text("# Sample\n", encoding="utf-8")
    _git("add", "README.md", cwd=repo)
    _git("commit", "-q", "-m", "base: initial commit", cwd=repo)
    _git("tag", "base", cwd=repo)

    _git("checkout", "-q", "-b", "feat/sample", cwd=repo)
    src = repo / "src"
    src.mkdir()
    (src / "feature.py").write_text(
        "def greet(name: str) -> str:\n"
        "    return f'hello, {name}'\n",
        encoding="utf-8",
    )
    _git("add", "src/feature.py", cwd=repo)
    _git("commit", "-q", "-m", "feat: add greet()", cwd=repo)

    return {"repo": repo, "base_ref": "base", "head_ref": "HEAD"}
