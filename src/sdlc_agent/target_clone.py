"""Resolve the local working tree for a target repo (explicit path or managed clone)."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from sdlc_agent.config import RootAgentConfig, parse_github_repo_url


def default_clone_parent() -> Path:
    """Parent directory for auto-managed target clones.

    Override with env ``SDLC_TARGET_CLONE_PARENT`` (absolute or user-relative path).
    Default: ``<tempdir>/sdlc-agent-targets``.
    """
    raw = os.environ.get("SDLC_TARGET_CLONE_PARENT")
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path(tempfile.gettempdir()) / "sdlc-agent-targets").resolve()


def clone_if_needed(*, repo_url: str, dest: Path) -> None:
    """Clone ``repo_url`` into ``dest`` when ``dest`` is not already a git work tree."""
    git = shutil.which("git")
    if not git:
        raise RuntimeError(
            "git is required on PATH to clone the target repository when "
            "--target-repo-root is omitted (set SDLC_TARGET_CLONE_PARENT or pass "
            "--target-repo-root explicitly)."
        )
    git_link = dest / ".git"
    if dest.exists():
        if git_link.exists():
            return
        raise RuntimeError(
            f"target clone directory exists but is not a git repository: {dest}. "
            "Remove it or pass --target-repo-root to a different path."
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            [git, "clone", "--depth", "1", repo_url, str(dest)],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        detail = (e.stderr or e.stdout or "").strip()
        raise RuntimeError(
            f"git clone failed for {repo_url!r} into {dest}: {detail or e}"
        ) from e


def resolve_target_workdir(
    root_config: RootAgentConfig,
    *,
    explicit_root: Path | None,
) -> Path:
    """Resolve the local directory that holds the target checkout and ``.deepagent/``.

    * If ``explicit_root`` is set, that path is created and returned (no clone).
    * If omitted and ``github.lifecycle_client`` is ``mcp``, clone ``target.repo_url``
      under :func:`default_clone_parent` using ``<owner>_<repository>`` as the folder name.
    * If omitted and lifecycle is ``fixture``, create the same folder name but do not
      clone (tests and demos typically pass ``--target-repo-root`` explicitly).
    """
    if explicit_root is not None:
        p = explicit_root.expanduser().resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p

    parsed = parse_github_repo_url(root_config.target.repo_url)
    owner = root_config.target.owner or parsed.owner
    repository = root_config.target.repository or parsed.repository
    dest = default_clone_parent() / f"{owner}_{repository}"

    if root_config.github.lifecycle_client == "mcp":
        clone_if_needed(repo_url=root_config.target.repo_url, dest=dest)
    else:
        dest.mkdir(parents=True, exist_ok=True)
    return dest.resolve()
