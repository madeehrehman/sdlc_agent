"""Orchestrator LLM supervisor: delegation enrichment and gated safety clamp."""

from __future__ import annotations

from pathlib import Path

from sdlc_agent.config import OrchestratorConfig
from sdlc_agent.contracts import SubagentName
from sdlc_agent.memory import initialize_deepagent
from sdlc_agent.orchestrator import SDLCPhase
from sdlc_agent.orchestrator.dispatcher import Orchestrator
from sdlc_agent.orchestrator.state_machine import GateDecision
from sdlc_agent.orchestrator.supervisor import DelegationPlan, GateAdvice, OrchestratorSupervisor
from sdlc_agent.subagents.mocks import (
    CannedSubagent,
    canned_failing_artifact,
    canned_successful_artifact,
)


class StubSupervisor:
    def __init__(
        self,
        *,
        delegation: DelegationPlan | None = None,
        gate: GateAdvice | None = None,
    ) -> None:
        self.delegation = delegation or DelegationPlan(
            task_instructions="Focus only on acceptance criteria in the issue body.",
            rationale="scope pin",
        )
        self.gate = gate or GateAdvice(
            decision=GateDecision.PROCEED,
            rationale="supervisor says proceed",
        )

    def plan_delegation(self, **kwargs: object) -> DelegationPlan:
        return self.delegation

    def advise_gate(self, **kwargs: object) -> GateAdvice:
        return self.gate


def _ok_registry() -> dict[SubagentName, CannedSubagent]:
    return {
        SubagentName.BACKLOG_ANALYZER: CannedSubagent(
            name=SubagentName.BACKLOG_ANALYZER,
            artifact_kwargs=canned_successful_artifact(artifact={"acceptance_criteria": ["ac1"]}),
        ),
        SubagentName.DEVELOPER: CannedSubagent(
            name=SubagentName.DEVELOPER,
            artifact_kwargs=canned_successful_artifact(
                artifact={"implementation_summary": "...", "tests": ["t1"]}
            ),
        ),
        SubagentName.PR_REVIEWER: CannedSubagent(
            name=SubagentName.PR_REVIEWER,
            artifact_kwargs=canned_successful_artifact(artifact={"verdict": "approve"}),
        ),
    }


def test_supervisor_enriches_delegation_task(tmp_repo: Path) -> None:
    paths = initialize_deepagent(tmp_repo)
    dev = CannedSubagent(
        name=SubagentName.DEVELOPER,
        artifact_kwargs=canned_successful_artifact(artifact={"implementation_summary": "x"}),
    )
    registry = _ok_registry()
    registry[SubagentName.DEVELOPER] = dev
    orch = Orchestrator(
        paths=paths,
        registry=registry,
        orchestrator_config=OrchestratorConfig(use_llm_supervisor=True),
        supervisor=StubSupervisor(),
    )

    orch.intake("TICKET-SUP", ticket_inputs={"skip_requirements_analysis": True})
    orch.run_to_completion("TICKET-SUP")

    assert dev.last_assignment is not None
    assert "Supervisor instructions:" in dev.last_assignment.task
    assert "acceptance criteria" in dev.last_assignment.task


def test_supervisor_cannot_override_failed_verification(tmp_repo: Path) -> None:
    paths = initialize_deepagent(tmp_repo)
    registry = _ok_registry()
    registry[SubagentName.DEVELOPER] = CannedSubagent(
        name=SubagentName.DEVELOPER,
        artifact_kwargs=canned_failing_artifact("tests failed"),
    )
    orch = Orchestrator(
        paths=paths,
        registry=registry,
        orchestrator_config=OrchestratorConfig(use_llm_supervisor=True),
        supervisor=StubSupervisor(
            gate=GateAdvice(decision=GateDecision.PROCEED, rationale="ignore failure"),
        ),
        max_attempts_per_phase=1,
    )

    orch.intake("TICKET-FAIL", ticket_inputs={"skip_requirements_analysis": True})
    final = orch.run_to_completion("TICKET-FAIL")

    assert final.current_phase is SDLCPhase.BLOCKED


def test_root_config_loads_orchestrator_supervisor_flag(tmp_path: Path) -> None:
    from sdlc_agent.config import RootAgentConfig

    cfg = RootAgentConfig.model_validate(
        {
            "target": {
                "repo_url": "https://github.com/o/r",
                "specs_path": "spec.md",
            },
            "orchestrator": {"use_llm_supervisor": True},
        }
    )
    assert cfg.orchestrator.use_llm_supervisor is True


def test_runtime_wires_supervisor_when_enabled(tmp_path: Path) -> None:
    from sdlc_agent.runtime import build_sdlc_runtime

    target_repo = tmp_path / "target"
    target_repo.mkdir()
    cfg_path = tmp_path / "sdlc-agent.yaml"
    env_path = tmp_path / ".env"
    env_path.write_text("OPENAI_API_KEY=sk-test\n", encoding="utf-8")
    cfg_path.write_text(
        "target:\n"
        "  repo_url: https://github.com/o/r\n"
        "  specs_path: spec.md\n"
        "github:\n"
        "  lifecycle_client: fixture\n"
        "orchestrator:\n"
        "  use_llm_supervisor: true\n",
        encoding="utf-8",
    )

    class FakeOpenAIClient:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

    runtime = build_sdlc_runtime(
        root_config_path=cfg_path,
        env_path=env_path,
        target_repo_root=target_repo,
        openai_client_factory=FakeOpenAIClient,
    )
    try:
        assert runtime.config.orchestrator.use_llm_supervisor is True
        assert runtime.orchestrator.supervisor is not None
        assert isinstance(runtime.orchestrator.supervisor, OrchestratorSupervisor)
    finally:
        runtime.close()
