"""Operator-facing runner for live SDLC agent workflows."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

from sdlc_agent.orchestrator import SDLCPhase, TicketState
from sdlc_agent.orchestrator.dispatcher import OrchestratorError
from sdlc_agent.runtime import SDLCRuntime, build_sdlc_runtime


RunMode = Literal["backlog", "full"]


@dataclass(frozen=True)
class SDLCRunResult:
    ticket_id: str
    mode: RunMode
    final_phase: str
    github_issue_number: int | None
    github_item_id: str | None
    state_path: Path
    artifacts_dir: Path


def run_sdlc_agent(
    *,
    root_config_path: Path = Path("sdlc-agent.yaml"),
    env_path: Path = Path(".env"),
    target_repo_root: Path | None = None,
    ticket_id: str | None = None,
    mode: RunMode = "backlog",
    max_steps: int = 20,
    base_ref: str | None = None,
    head_ref: str | None = None,
    release_to_main_accepted: bool = False,
    session_id: str | None = None,
    build_runtime: Callable[..., SDLCRuntime] = build_sdlc_runtime,
) -> SDLCRunResult:
    """Build runtime clients and execute an SDLC workflow.

    ``backlog`` mode stops after the requirements gate has created/adopted the
    first GitHub issue, leaving the ticket positioned at DEVELOPMENT. ``full``
    mode continues through DeveloperTester and PRReviewer using the configured
    local target working tree.
    """
    resolved_ticket_id = ticket_id or f"SDLC-{uuid.uuid4().hex[:8]}"
    runtime = build_runtime(
        root_config_path=root_config_path,
        env_path=env_path,
        target_repo_root=target_repo_root,
        session_id=session_id or resolved_ticket_id,
    )
    try:
        ticket_inputs = _ticket_inputs(
            runtime,
            base_ref=base_ref,
            head_ref=head_ref,
            release_to_main_accepted=release_to_main_accepted,
        )
        runtime.orchestrator.intake(resolved_ticket_id, ticket_inputs=ticket_inputs)
        if mode == "backlog":
            state = _run_until_phase(
                runtime,
                resolved_ticket_id,
                stop_phase=SDLCPhase.DEVELOPMENT,
                max_steps=max_steps,
            )
        elif mode == "full":
            state = runtime.orchestrator.run_to_completion(
                resolved_ticket_id,
                max_steps=max_steps,
            )
        else:
            raise ValueError(f"unknown run mode: {mode}")
        return _result(runtime, state, mode)
    finally:
        runtime.close()


def _ticket_inputs(
    runtime: SDLCRuntime,
    *,
    base_ref: str | None,
    head_ref: str | None,
    release_to_main_accepted: bool,
) -> dict[str, object]:
    inputs: dict[str, object] = {"specs_path": runtime.config.github.specs_path}
    if base_ref:
        inputs["base_ref"] = base_ref
    if head_ref:
        inputs["head_ref"] = head_ref
    if release_to_main_accepted:
        inputs["release_to_main_accepted"] = True
    return inputs


def _run_until_phase(
    runtime: SDLCRuntime,
    ticket_id: str,
    *,
    stop_phase: SDLCPhase,
    max_steps: int,
) -> TicketState:
    state: TicketState | None = None
    for _ in range(max_steps):
        state = runtime.orchestrator.advance(ticket_id)
        if state.current_phase is stop_phase or state.is_terminal:
            return state
    final_phase = state.current_phase.value if state else "unknown"
    raise OrchestratorError(
        f"ticket {ticket_id} did not reach {stop_phase.value} within {max_steps} "
        f"steps; final phase was {final_phase}"
    )


def _result(runtime: SDLCRuntime, state: TicketState, mode: RunMode) -> SDLCRunResult:
    return SDLCRunResult(
        ticket_id=state.ticket_id,
        mode=mode,
        final_phase=state.current_phase.value,
        github_issue_number=_maybe_int(state.ticket_inputs.get("github_issue_number")),
        github_item_id=_maybe_str(state.ticket_inputs.get("github_project_item_id")),
        state_path=runtime.paths.state_file(state.ticket_id),
        artifacts_dir=runtime.paths.ticket_artifacts_dir(state.ticket_id),
    )


def _maybe_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _maybe_str(value: object) -> str | None:
    return str(value) if value is not None else None
