"""Phase 5: operator runner starts the live SDLC workflow."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from sdlc_agent.orchestrator import SDLCPhase, TicketState
from sdlc_agent.runner import run_sdlc_agent


class FakeOrchestrator:
    def __init__(self) -> None:
        self.intakes: list[tuple[str, dict[str, object]]] = []
        self.advanced: list[str] = []
        self.full_runs: list[tuple[str, int]] = []
        self._phase_queue = [
            SDLCPhase.REQUIREMENTS_GATE,
            SDLCPhase.DEVELOPMENT,
        ]

    def intake(self, ticket_id: str, *, ticket_inputs: dict[str, object] | None = None):
        self.intakes.append((ticket_id, dict(ticket_inputs or {})))
        return TicketState(
            ticket_id=ticket_id,
            current_phase=SDLCPhase.REQUIREMENTS_ANALYSIS,
            ticket_inputs=dict(ticket_inputs or {}),
        )

    def advance(self, ticket_id: str) -> TicketState:
        self.advanced.append(ticket_id)
        phase = self._phase_queue.pop(0)
        return TicketState(
            ticket_id=ticket_id,
            current_phase=phase,
            ticket_inputs={
                "github_issue_number": 7,
                "github_project_item_id": "ISSUE_7",
            },
        )

    def run_to_completion(self, ticket_id: str, *, max_steps: int) -> TicketState:
        self.full_runs.append((ticket_id, max_steps))
        return TicketState(
            ticket_id=ticket_id,
            current_phase=SDLCPhase.DONE,
            ticket_inputs={
                "github_issue_number": 8,
                "github_project_item_id": "ISSUE_8",
                "release_to_main_accepted": True,
            },
        )


class FakeRuntime:
    def __init__(self, tmp_path: Path) -> None:
        from sdlc_agent.memory.paths import DeepAgentPaths

        self.config = SimpleNamespace(github=SimpleNamespace(specs_path="specs.md"))
        self.paths = DeepAgentPaths(repo_root=tmp_path)
        self.orchestrator = FakeOrchestrator()
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_backlog_mode_runs_until_development_and_closes_runtime(tmp_path: Path) -> None:
    runtime = FakeRuntime(tmp_path)

    result = run_sdlc_agent(
        ticket_id="RUN-1",
        mode="backlog",
        max_steps=5,
        build_runtime=lambda **_kwargs: runtime,
    )

    assert runtime.orchestrator.intakes == [("RUN-1", {"specs_path": "specs.md"})]
    assert runtime.orchestrator.advanced == ["RUN-1", "RUN-1"]
    assert runtime.orchestrator.full_runs == []
    assert runtime.closed is True
    assert result.final_phase == "DEVELOPMENT"
    assert result.github_issue_number == 7
    assert result.github_item_id == "ISSUE_7"
    assert result.state_path == tmp_path / ".deepagent" / "state" / "RUN-1.json"


def test_full_mode_passes_git_refs_and_release_flag(tmp_path: Path) -> None:
    runtime = FakeRuntime(tmp_path)

    result = run_sdlc_agent(
        ticket_id="RUN-2",
        mode="full",
        max_steps=12,
        base_ref="develop",
        head_ref="HEAD",
        release_to_main_accepted=True,
        build_runtime=lambda **_kwargs: runtime,
    )

    assert runtime.orchestrator.intakes == [
        (
            "RUN-2",
            {
                "specs_path": "specs.md",
                "base_ref": "develop",
                "head_ref": "HEAD",
                "release_to_main_accepted": True,
            },
        )
    ]
    assert runtime.orchestrator.full_runs == [("RUN-2", 12)]
    assert runtime.closed is True
    assert result.final_phase == "DONE"
    assert result.github_issue_number == 8
