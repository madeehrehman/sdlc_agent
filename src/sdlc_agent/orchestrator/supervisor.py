"""LLM supervisor for the orchestrator: plan delegation and advise gates."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sdlc_agent.contracts import ArtifactReturn, SubagentName
from sdlc_agent.llm import OpenAIClient
from sdlc_agent.memory.trajectories import TrajectoryRecorder
from sdlc_agent.orchestrator.prompts import ORCHESTRATOR_SUPERVISOR_SYSTEM_PROMPT
from sdlc_agent.orchestrator.state_machine import SDLCPhase, TicketState, GateDecision
from sdlc_agent.skills import SkillLoader, assemble_system_prompt
from sdlc_agent.subagents.base import call_llm_with_schema


DEFAULT_SUPERVISOR_SKILLS: tuple[str, ...] = ("orchestrator-supervisor",)


_DELEGATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "task_instructions": {
            "type": "string",
            "description": "Clear instructions for the subagent this step",
        },
        "rationale": {"type": "string"},
        "focus_points": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["task_instructions", "rationale"],
    "additionalProperties": False,
}


_GATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "decision": {
            "type": "string",
            "enum": ["proceed", "retry", "blocked", "needs_human"],
        },
        "rationale": {"type": "string"},
        "retry_guidance": {"type": "string"},
    },
    "required": ["decision", "rationale"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class DelegationPlan:
    task_instructions: str
    rationale: str
    focus_points: tuple[str, ...] = ()


@dataclass(frozen=True)
class GateAdvice:
    decision: GateDecision
    rationale: str
    retry_guidance: str = ""


class OrchestratorSupervisor:
    """Supervisor LLM: knows SDLC protocol; plans work and advises gates."""

    def __init__(
        self,
        llm: OpenAIClient,
        *,
        skills: SkillLoader | None = None,
        recorder: TrajectoryRecorder | None = None,
    ) -> None:
        self.llm = llm
        self.skills = skills
        self.recorder = recorder

    def plan_delegation(
        self,
        *,
        state: TicketState,
        phase: SDLCPhase,
        subagent: SubagentName,
        attempt: int,
        context_summary: str,
    ) -> DelegationPlan:
        user = self._delegation_user_prompt(
            state=state,
            phase=phase,
            subagent=subagent,
            attempt=attempt,
            context_summary=context_summary,
        )
        data = call_llm_with_schema(
            self.llm,
            system=self._system_prompt(),
            user=user,
            schema_name="orchestrator_delegation",
            schema=_DELEGATION_SCHEMA,
            recorder=self.recorder,
            task_id=f"{state.ticket_id}-supervisor-delegation",
            kind="orchestrator.delegation",
            metadata={"phase": phase.value, "subagent": subagent.value, "attempt": attempt},
        )
        focus = data.get("focus_points") or []
        return DelegationPlan(
            task_instructions=str(data.get("task_instructions") or ""),
            rationale=str(data.get("rationale") or ""),
            focus_points=tuple(str(p) for p in focus if p),
        )

    def advise_gate(
        self,
        *,
        state: TicketState,
        gate: SDLCPhase,
        artifact: ArtifactReturn,
        attempts_in_phase: int,
        max_attempts: int,
    ) -> GateAdvice:
        user = self._gate_user_prompt(
            state=state,
            gate=gate,
            artifact=artifact,
            attempts_in_phase=attempts_in_phase,
            max_attempts=max_attempts,
        )
        data = call_llm_with_schema(
            self.llm,
            system=self._system_prompt(),
            user=user,
            schema_name="orchestrator_gate",
            schema=_GATE_SCHEMA,
            recorder=self.recorder,
            task_id=f"{state.ticket_id}-supervisor-gate",
            kind="orchestrator.gate",
            metadata={"gate": gate.value, "attempts": attempts_in_phase},
        )
        raw = str(data.get("decision") or "needs_human")
        try:
            decision = GateDecision(raw)
        except ValueError:
            decision = GateDecision.NEEDS_HUMAN
        return GateAdvice(
            decision=decision,
            rationale=str(data.get("rationale") or ""),
            retry_guidance=str(data.get("retry_guidance") or ""),
        )

    def _system_prompt(self) -> str:
        return assemble_system_prompt(
            ORCHESTRATOR_SUPERVISOR_SYSTEM_PROMPT,
            loader=self.skills,
            skill_names=list(DEFAULT_SUPERVISOR_SKILLS),
        )

    @staticmethod
    def _delegation_user_prompt(
        *,
        state: TicketState,
        phase: SDLCPhase,
        subagent: SubagentName,
        attempt: int,
        context_summary: str,
    ) -> str:
        inputs = json.dumps(state.ticket_inputs, indent=2, default=str)
        return f"""\
Plan delegation for the next subagent invocation.

Ticket: {state.ticket_id}
Current phase: {phase.value}
Subagent: {subagent.value}
Attempt: {attempt}
Ticket inputs (metadata):
{inputs}

Context (artifacts, facts, prior steps):
{context_summary}

Produce task_instructions the subagent must follow. Be specific to acceptance
criteria and the real product scope — not generic math drills.
"""

    @staticmethod
    def _gate_user_prompt(
        *,
        state: TicketState,
        gate: SDLCPhase,
        artifact: ArtifactReturn,
        attempts_in_phase: int,
        max_attempts: int,
    ) -> str:
        body = json.dumps(artifact.model_dump(mode="json"), indent=2, default=str)
        return f"""\
Recommend a gate decision for this checkpoint.

Ticket: {state.ticket_id}
Gate: {gate.value}
Attempts in this work phase: {attempts_in_phase} (max {max_attempts})

Subagent artifact and verification:
{body}

Rules:
- If verification.passed is false or status is needs_human, do not recommend proceed.
- If attempts_in_phase >= max_attempts and work still fails, prefer blocked over retry.
- retry_guidance should be actionable if you recommend retry.
"""
