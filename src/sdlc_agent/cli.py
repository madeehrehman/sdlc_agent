"""Command line entrypoints for the SDLC agent."""

from __future__ import annotations

import argparse
from pathlib import Path

from sdlc_agent.runner import run_sdlc_agent


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    result = run_sdlc_agent(
        root_config_path=args.config,
        env_path=args.env,
        target_repo_root=args.target_repo_root,
        ticket_id=args.ticket_id,
        mode=args.mode,
        max_steps=args.max_steps,
        base_ref=args.base_ref,
        head_ref=args.head_ref,
        release_to_main_accepted=args.release_to_main_accepted,
        session_id=args.session_id,
        issue_number=args.issue_number,
        worktrees_dir=args.worktrees_dir,
    )
    print(f"ticket_id={result.ticket_id}")
    print(f"mode={result.mode}")
    print(f"final_phase={result.final_phase}")
    if result.github_issue_number is not None:
        print(f"github_issue_number={result.github_issue_number}")
    if result.github_item_id is not None:
        print(f"github_item_id={result.github_item_id}")
    if result.github_pr_number is not None:
        print(f"github_pr_number={result.github_pr_number}")
    if result.github_pr_url is not None:
        print(f"github_pr_url={result.github_pr_url}")
    print(f"state_path={result.state_path}")
    print(f"artifacts_dir={result.artifacts_dir}")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sdlc-agent",
        description="Run the SDLC agent from the root sdlc-agent.yaml config.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("sdlc-agent.yaml"),
        help="root SDLC agent config path",
    )
    parser.add_argument(
        "--env",
        type=Path,
        default=Path(".env"),
        help=".env path containing OPENAI_API_KEY and GITHUB_TOKEN",
    )
    parser.add_argument(
        "--target-repo-root",
        type=Path,
        default=None,
        help="local target working tree path used by DeveloperTester and PRReviewer",
    )
    parser.add_argument(
        "--ticket-id",
        default=None,
        help="ticket id for persisted .deepagent state; defaults to a generated id",
    )
    parser.add_argument(
        "--mode",
        choices=["backlog", "full"],
        default="backlog",
        help="backlog creates/adopts GitHub issues; full continues through dev/review",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=20,
        help="maximum orchestrator steps before stopping",
    )
    parser.add_argument(
        "--base-ref",
        default=None,
        help="git base ref for PR review in full mode, for example develop",
    )
    parser.add_argument(
        "--head-ref",
        default=None,
        help="git head ref for PR review in full mode, defaults inside reviewer to HEAD",
    )
    parser.add_argument(
        "--release-to-main-accepted",
        action="store_true",
        help="allow DONE to close the issue instead of leaving it Release Ready",
    )
    parser.add_argument(
        "--issue-number",
        type=int,
        default=None,
        help="existing GitHub issue to adopt (full mode only); creates a worktree and opens a PR",
    )
    parser.add_argument(
        "--worktrees-dir",
        type=Path,
        default=None,
        help="directory for per-ticket git worktrees (default: <target>/.worktrees)",
    )
    parser.add_argument(
        "--session-id",
        default=None,
        help="trajectory/session id; defaults to the ticket id",
    )
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
