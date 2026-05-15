"""Multi-issue supervisor: dequeue backlog lifecycle issues and run full issue-driven SDLC."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from sdlc_agent.config import load_root_agent_config
from sdlc_agent.mcp.factory import build_github_project_client
from sdlc_agent.mcp.github import GitHubProjectItem
from sdlc_agent.runner import SDLCRunResult, run_sdlc_agent
from sdlc_agent.runtime import SDLCRuntime, build_sdlc_runtime
from sdlc_agent.target_clone import resolve_target_workdir


DEFAULT_DEQUEUE_STATUSES: frozenset[str] = frozenset({"Backlog"})


def pick_next_dequeued_issue(
    items: list[GitHubProjectItem],
    *,
    dequeue_statuses: frozenset[str],
) -> GitHubProjectItem | None:
    """Return the lowest issue number among items whose lifecycle ``status`` is queued."""
    candidates = [i for i in items if i.status in dequeue_statuses]
    if not candidates:
        return None
    candidates.sort(key=lambda i: i.issue_number)
    return candidates[0]


@dataclass(frozen=True)
class DaemonSummary:
    """Outcome of a daemon session (one or more issue-driven full runs).

    ``stopped_reason`` is ``queue_empty`` when no queued issues remained, or
    ``max_issues`` when the cap on started issues was reached.
    """

    results: tuple[SDLCRunResult, ...]
    stopped_reason: str


def run_sdlc_daemon(
    *,
    root_config_path: Path = Path("sdlc-agent.yaml"),
    env_path: Path = Path(".env"),
    target_repo_root: Path | None = None,
    dequeue_statuses: frozenset[str] | None = None,
    max_issues: int | None = None,
    max_steps: int = 20,
    base_ref: str | None = None,
    head_ref: str | None = None,
    release_to_main_accepted: bool = False,
    worktrees_dir: Path | None = None,
    continue_on_error: bool = False,
    sleep_seconds_between_issues: float = 0.0,
    run_agent: Callable[..., SDLCRunResult] = run_sdlc_agent,
    build_runtime: Callable[..., SDLCRuntime] = build_sdlc_runtime,
) -> DaemonSummary:
    """Run issue-driven ``full`` SDLC repeatedly until the queue is empty or capped.

    Each iteration lists GitHub project items (open issues + lifecycle status),
    picks the **lowest issue number** whose status is in ``dequeue_statuses``
    (default: ``{"Backlog"}`` only), then runs :func:`run_sdlc_agent` with
    ``mode="full"`` and that ``issue_number``. Successful runs move issues out of
    Backlog via existing lifecycle updates, so they are not picked again.

    ``target_repo_root`` selects the local checkout; when omitted, the same managed
    clone directory as :func:`sdlc_agent.runner.run_sdlc_agent` is used.

    ``max_issues`` caps how many issues are **started** (including failures when
    ``continue_on_error`` is true).
    """
    root_config = load_root_agent_config(root_config_path, env_path=env_path)
    memory_root = resolve_target_workdir(root_config, explicit_root=target_repo_root)
    statuses = dequeue_statuses or DEFAULT_DEQUEUE_STATUSES

    da_config = root_config.to_deepagent_config(memory_root)

    results: list[SDLCRunResult] = []
    started = 0

    while max_issues is None or started < max_issues:
        gh = build_github_project_client(da_config)
        try:
            nxt = pick_next_dequeued_issue(gh.list_project_items(), dequeue_statuses=statuses)
        finally:
            close = getattr(gh, "close", None)
            if callable(close):
                close()

        if nxt is None:
            return DaemonSummary(results=tuple(results), stopped_reason="queue_empty")

        started += 1
        ticket_id = f"DAEMON-ISSUE-{nxt.issue_number}-{uuid.uuid4().hex[:6]}"
        try:
            results.append(
                run_agent(
                    root_config_path=root_config_path,
                    env_path=env_path,
                    target_repo_root=memory_root,
                    ticket_id=ticket_id,
                    mode="full",
                    max_steps=max_steps,
                    base_ref=base_ref,
                    head_ref=head_ref,
                    release_to_main_accepted=release_to_main_accepted,
                    issue_number=nxt.issue_number,
                    worktrees_dir=worktrees_dir,
                    build_runtime=build_runtime,
                )
            )
        except Exception as exc:
            if not continue_on_error:
                raise
            print(
                f"daemon: issue #{nxt.issue_number} ({ticket_id}) failed: {exc}",
                flush=True,
            )
        if sleep_seconds_between_issues > 0:
            time.sleep(sleep_seconds_between_issues)

    return DaemonSummary(results=tuple(results), stopped_reason="max_issues")
