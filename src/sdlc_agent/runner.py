"""Operator-facing runner for live SDLC agent workflows."""

from __future__ import annotations

import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

from sdlc_agent.config import load_root_agent_config
from sdlc_agent.issue_workflow import (
    default_worktrees_dir,
    issue_branch_name,
    synthetic_requirements_artifact,
)
from sdlc_agent.mcp.factory import build_github_project_client
from sdlc_agent.mcp.git import LocalGitClient
from sdlc_agent.orchestrator import SDLCPhase, TicketState
from sdlc_agent.orchestrator.dispatcher import OrchestratorError, OrchestratorHooks
from sdlc_agent.runtime import SDLCRuntime, build_sdlc_runtime


RunMode = Literal["backlog", "full"]


@dataclass(frozen=True)
class SDLCRunResult:
    ticket_id: str
    mode: RunMode
    final_phase: str
    github_issue_number: int | None
    github_item_id: str | None
    github_pr_number: int | None
    github_pr_url: str | None
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
    issue_number: int | None = None,
    worktrees_dir: Path | None = None,
    build_runtime: Callable[..., SDLCRuntime] = build_sdlc_runtime,
) -> SDLCRunResult:
    """Build runtime clients and execute an SDLC workflow.

    ``backlog`` mode stops after the requirements gate has created/adopted the
    first GitHub issue, leaving the ticket positioned at DEVELOPMENT. ``full``
    mode continues through DeveloperTester and PRReviewer using the configured
    local target working tree.

    When ``issue_number`` is set (``full`` mode only), the runner adopts that
    GitHub issue, creates a git worktree + branch from ``base_ref`` (defaulting
    to ``develop`` from config), seeds a synthetic requirements artifact, and
    wires hooks to commit/push after the development gate and open a PR after the
    review gate.
    """
    resolved_ticket_id = ticket_id or f"SDLC-{uuid.uuid4().hex[:8]}"
    root_config = load_root_agent_config(root_config_path, env_path=env_path)
    memory_root = (target_repo_root or Path(root_config.target.repository or ".")).resolve()
    memory_root.mkdir(parents=True, exist_ok=True)
    da_config = root_config.to_deepagent_config(memory_root)

    github_external = None
    worktree_path: Path | None = None
    git_main: LocalGitClient | None = None
    hooks: OrchestratorHooks | None = None
    branch_name = ""
    effective_base = base_ref
    issue_obj = None

    if issue_number is not None:
        if mode != "full":
            raise ValueError("issue_number is only supported when mode is 'full'")
        github_external = build_github_project_client(da_config)
        issue_obj = github_external.get_issue(issue_number)
        effective_base = base_ref or da_config.github.develop_branch
        branch_name = issue_branch_name(issue_number, issue_obj.title)
        wt_root = (worktrees_dir or default_worktrees_dir(memory_root)).resolve()
        wt_root.mkdir(parents=True, exist_ok=True)
        worktree_path = (wt_root / resolved_ticket_id).resolve()

        git_main = LocalGitClient(repo_root=memory_root)
        if not git_main.ref_exists(effective_base):
            close = getattr(github_external, "close", None)
            if callable(close):
                close()
            github_external = None
            raise OrchestratorError(
                f"git base ref {effective_base!r} does not exist in {memory_root}; "
                "refusing to auto-create promotion branches."
            )

        if worktree_path.exists():
            try:
                gitdir = worktree_path / ".git"
                if gitdir.exists():
                    git_main.remove_worktree(worktree_path)
                else:
                    shutil.rmtree(worktree_path)
            except Exception:
                pass

        git_main.add_worktree(worktree_path, new_branch=branch_name, start_ref=effective_base)
        github_external.update_project_status(f"ISSUE_{issue_number}", "In Development")

        def after_development_gate_proceed(state: TicketState) -> None:
            assert worktree_path is not None
            git_w = LocalGitClient(repo_root=worktree_path)
            msg = f"chore(sdlc): complete development for issue #{issue_number}"
            if git_w.commit_all(msg):
                git_w.push_branch()

        def after_review_gate_proceed(state: TicketState) -> None:
            if state.ticket_inputs.get("github_pr_number"):
                return
            assert github_external is not None
            assert issue_obj is not None
            head = str(state.ticket_inputs.get("git_work_branch") or branch_name)
            base = str(state.ticket_inputs.get("base_ref") or effective_base)
            pr = github_external.create_pull_request(
                title=f"{issue_obj.title} (#{issue_number})",
                body=f"Closes #{issue_number}\n\n{issue_obj.url}",
                head=head,
                base=base,
            )
            state.ticket_inputs["github_pr_number"] = pr.number
            state.ticket_inputs["github_pr_url"] = pr.url

        hooks = OrchestratorHooks(
            after_development_gate_proceed=after_development_gate_proceed,
            after_review_gate_proceed=after_review_gate_proceed,
        )

    runtime: SDLCRuntime | None = None
    try:
        runtime = build_runtime(
            root_config_path=root_config_path,
            env_path=env_path,
            target_repo_root=memory_root,
            worktree_root=worktree_path,
            session_id=session_id or resolved_ticket_id,
            github=github_external,
            orchestrator_hooks=hooks,
        )
        ticket_inputs: dict[str, object] = _ticket_inputs(
            runtime,
            base_ref=effective_base if issue_number is not None else base_ref,
            head_ref=(head_ref or "HEAD") if issue_number is not None else head_ref,
            release_to_main_accepted=release_to_main_accepted,
        )
        if issue_number is not None:
            ticket_inputs.update(
                {
                    "skip_requirements_analysis": True,
                    "github_issue_number": issue_number,
                    "github_project_item_id": f"ISSUE_{issue_number}",
                    "git_work_branch": branch_name,
                }
            )
        if issue_obj is not None:
            runtime.orchestrator.memory.save_artifact(
                resolved_ticket_id,
                SDLCPhase.REQUIREMENTS_ANALYSIS,
                synthetic_requirements_artifact(resolved_ticket_id, issue_obj),
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
        if runtime is not None:
            runtime.close()
        if github_external is not None:
            close = getattr(github_external, "close", None)
            if callable(close):
                close()
        if git_main is not None and worktree_path is not None:
            try:
                if worktree_path.exists() and (worktree_path / ".git").exists():
                    git_main.remove_worktree(worktree_path)
            except Exception:
                pass


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
        github_pr_number=_maybe_int(state.ticket_inputs.get("github_pr_number")),
        github_pr_url=_maybe_str(state.ticket_inputs.get("github_pr_url")),
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
