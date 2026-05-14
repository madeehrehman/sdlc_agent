"""Phase 5: GitHub Actions promotion workflow exists for GitHub-native SDLC."""

from __future__ import annotations

from pathlib import Path


def test_pr_gated_promotion_workflow_defines_develop_release_main_flow() -> None:
    workflow = Path(".github/workflows/sdlc-promotion.yml")

    body = workflow.read_text(encoding="utf-8")

    assert "feature-to-develop" in body
    assert "develop-to-release" in body
    assert "release-to-main" in body
    assert "container-smoke" in body
    assert "docker build" in body
    assert "pull_request" in body
    assert "python -m pytest" in body
