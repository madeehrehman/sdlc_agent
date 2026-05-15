"""Target clone resolution (managed temp clone vs explicit --target-repo-root)."""

from __future__ import annotations

from pathlib import Path
from subprocess import CompletedProcess

import pytest

from sdlc_agent.config import RootAgentConfig
from sdlc_agent.target_clone import clone_if_needed, default_clone_parent, resolve_target_workdir


def test_resolve_explicit_root_creates_dir(tmp_path: Path) -> None:
    cfg = RootAgentConfig.model_validate(
        {
            "target": {"repo_url": "https://github.com/o/r"},
            "github": {"lifecycle_client": "fixture"},
        }
    )
    explicit = tmp_path / "my-clone"
    out = resolve_target_workdir(cfg, explicit_root=explicit)
    assert out == explicit.resolve()
    assert out.is_dir()


def test_resolve_fixture_implicit_uses_clone_parent(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SDLC_TARGET_CLONE_PARENT", str(tmp_path / "clones"))
    cfg = RootAgentConfig.model_validate(
        {
            "target": {"repo_url": "https://github.com/acme/widget"},
            "github": {"lifecycle_client": "fixture"},
        }
    )
    out = resolve_target_workdir(cfg, explicit_root=None)
    assert out == (tmp_path / "clones" / "acme_widget").resolve()
    assert out.is_dir()


def test_default_clone_parent_respects_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SDLC_TARGET_CLONE_PARENT", str(tmp_path / "from-env"))
    assert default_clone_parent() == (tmp_path / "from-env").resolve()


def test_clone_if_needed_skips_when_dot_git_exists(tmp_path: Path, monkeypatch) -> None:
    dest = tmp_path / "existing"
    dest.mkdir()
    (dest / ".git").mkdir()
    calls: list[list[str]] = []

    def capture(cmd: list[str], **_kwargs: object) -> object:
        calls.append(list(cmd))
        return object()

    monkeypatch.setattr("sdlc_agent.target_clone.subprocess.run", capture)
    monkeypatch.setattr("sdlc_agent.target_clone.shutil.which", lambda _g: "git")
    clone_if_needed(repo_url="https://github.com/x/y", dest=dest)
    assert calls == []


def test_clone_if_needed_runs_git_once(tmp_path: Path, monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_kwargs: object) -> CompletedProcess:
        calls.append(list(cmd))
        dest = Path(cmd[-1])
        dest.mkdir(parents=True)
        (dest / ".git").mkdir()
        return CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr("sdlc_agent.target_clone.subprocess.run", fake_run)
    monkeypatch.setattr("sdlc_agent.target_clone.shutil.which", lambda _g: "git")
    dest = tmp_path / "fresh"
    clone_if_needed(repo_url="https://github.com/a/b", dest=dest)
    assert len(calls) == 1
    assert calls[0][:3] == ["git", "clone", "--depth"]
    clone_if_needed(repo_url="https://github.com/a/b", dest=dest)
    assert len(calls) == 1
