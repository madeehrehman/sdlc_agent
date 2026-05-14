"""Local git client worktree helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from sdlc_agent.mcp.git import GitMCPError, LocalGitClient


def _init_repo_with_develop(repo: Path) -> None:
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "sdlc@test"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "sdlc"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "branch", "-M", "develop"], cwd=repo, check=True, capture_output=True)


@pytest.mark.skipif(
    subprocess.run(["git", "--version"], capture_output=True).returncode != 0,
    reason="git not available",
)
def test_ref_exists_and_worktree_add_remove(tmp_path: Path) -> None:
    repo = tmp_path / "main"
    repo.mkdir()
    _init_repo_with_develop(repo)
    git = LocalGitClient(repo_root=repo)
    assert git.ref_exists("develop") is True
    assert git.ref_exists("nonexistent-branch-xyz") is False

    wt = tmp_path / "wt"
    git.add_worktree(wt, new_branch="feature-wt", start_ref="develop")
    assert (wt / "README.md").is_file()
    w_git = LocalGitClient(repo_root=wt)
    assert w_git.current_branch() == "feature-wt"
    (wt / "foo.txt").write_text("x", encoding="utf-8")
    assert w_git.commit_all("add foo") is True
    assert "foo.txt" in w_git.show_commit()

    git.remove_worktree(wt)
    assert not wt.exists()


def test_commit_all_returns_false_when_clean(tmp_path: Path) -> None:
    repo = tmp_path / "r2"
    repo.mkdir()
    _init_repo_with_develop(repo)
    git = LocalGitClient(repo_root=repo)
    assert git.commit_all("nothing") is False


def test_push_branch_requires_remote(tmp_path: Path) -> None:
    repo = tmp_path / "r3"
    repo.mkdir()
    _init_repo_with_develop(repo)
    git = LocalGitClient(repo_root=repo)
    with pytest.raises(GitMCPError, match="push"):
        git.push_branch()
