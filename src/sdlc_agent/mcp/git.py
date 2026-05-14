"""git MCP clients.

Two implementations:

* :class:`GitMCPStub`   — Phase 0 in-process handshake stub.
* :class:`LocalGitClient` — Phase 2 client that shells out to local ``git``
  against a real repo on disk. Used by the PR Reviewer to fetch diffs.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from sdlc_agent.mcp.client import HandshakeResult


class GitMCPError(RuntimeError):
    pass


@dataclass
class GitMCPStub:
    """In-process stand-in. Used by Phase 0 handshake test."""

    server_name: str = "git-mcp-stub"

    def handshake(self) -> HandshakeResult:
        return HandshakeResult(
            ok=True,
            server=self.server_name,
            transport="in-process",
            detail="stub git MCP",
        )


@dataclass
class LocalGitClient:
    """Wraps local ``git`` for the PR Reviewer.

    Method surface is intentionally minimal: ``handshake`` proves git is on PATH
    and the repo is a git working tree; ``diff`` returns a unified diff suitable
    for review; ``files_changed`` returns the file list.
    """

    repo_root: Path
    git_executable: str = "git"
    server_name: str = "git-local"

    def handshake(self) -> HandshakeResult:
        if shutil.which(self.git_executable) is None:
            return HandshakeResult(
                ok=False,
                server=self.server_name,
                transport="subprocess",
                detail=f"`{self.git_executable}` not on PATH",
            )
        if not (self.repo_root / ".git").exists():
            return HandshakeResult(
                ok=False,
                server=self.server_name,
                transport="subprocess",
                detail=f"not a git repo: {self.repo_root}",
            )
        return HandshakeResult(
            ok=True,
            server=self.server_name,
            transport="subprocess",
            detail=f"git rooted at {self.repo_root}",
        )

    def diff(self, base_ref: str, head_ref: str = "HEAD") -> str:
        return self._run("diff", f"{base_ref}..{head_ref}", "--unified=3")

    def files_changed(self, base_ref: str, head_ref: str = "HEAD") -> list[str]:
        out = self._run("diff", "--name-only", f"{base_ref}..{head_ref}")
        return [line for line in out.splitlines() if line]

    def show_commit(self, ref: str = "HEAD") -> str:
        return self._run("show", "--stat", "--format=fuller", ref)

    def current_branch(self) -> str:
        return self._run("rev-parse", "--abbrev-ref", "HEAD").strip()

    def ref_exists(self, ref: str) -> bool:
        try:
            self._run("rev-parse", "--verify", f"{ref}^{{commit}}")
        except GitMCPError:
            return False
        return True

    def add_worktree(self, path: Path, *, new_branch: str, start_ref: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._run("worktree", "add", str(path), "-b", new_branch, start_ref)

    def remove_worktree(self, path: Path, *, force: bool = True) -> None:
        args: list[str] = ["worktree", "remove", str(path)]
        if force:
            args.append("--force")
        self._run(*args)

    def has_uncommitted_changes(self) -> bool:
        return bool(self._run("status", "--porcelain").strip())

    def commit_all(self, message: str) -> bool:
        """Stage and commit all changes. Returns False if there was nothing to commit."""
        if not self.has_uncommitted_changes():
            return False
        self._run("add", "-A")
        self._run(
            "-c",
            "user.email=sdlc-agent@local",
            "-c",
            "user.name=sdlc-agent",
            "commit",
            "-m",
            message,
        )
        return True

    def push_branch(self, branch: str | None = None, *, remote: str = "origin") -> None:
        b = branch or self.current_branch()
        self._run("push", "-u", remote, b)

    # ------------------------------------------------------------- internal
    def _run(self, *args: str) -> str:
        try:
            result = subprocess.run(
                [self.git_executable, *args],
                cwd=self.repo_root,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except FileNotFoundError as e:
            raise GitMCPError(f"git executable not found: {self.git_executable}") from e
        except subprocess.CalledProcessError as e:
            raise GitMCPError(
                f"git {' '.join(args)} failed (exit {e.returncode}): {e.stderr.strip()}"
            ) from e
        return result.stdout
