"""CLI entrypoint for sdlc-agent.

Commands:
  sdlc-agent backlog   -- read specs.md and create GitHub issues
  sdlc-agent run       -- run a single issue end-to-end
  sdlc-agent daemon    -- drain Backlog issues in a loop
"""
from __future__ import annotations

import argparse
import uuid
from pathlib import Path

from langchain_core.messages import HumanMessage

from sdlc_agent.agents.runtime import build_runtime
from sdlc_agent.config import load_root_agent_config


def cmd_backlog(args) -> None:
    config = load_root_agent_config(Path(args.config))
    target = Path(args.target)
    graph = build_runtime(config, target_repo_root=target, use_docker=args.docker)
    thread_id = str(uuid.uuid4())
    cfg = {"configurable": {"thread_id": thread_id}}
    initial = {
        "messages": [HumanMessage(content="Run backlog mode: read specs and create GitHub issues only.")],
        "phase": "intake",
        "memory_snapshot": {},
        "retry_count": 0,
        "current_issue": None,
        "dev_result": None,
        "review_result": None,
        "release_result": None,
    }
    for chunk in graph.stream(initial, cfg, stream_mode="values"):
        phase = chunk.get("phase", "")
        msgs = chunk.get("messages", [])
        if msgs:
            last = msgs[-1]
            content = getattr(last, "content", str(last))
            print(f"[{phase}] {str(content)[:120]}")


def cmd_run(args) -> None:
    config = load_root_agent_config(Path(args.config))
    target = Path(args.target)
    graph = build_runtime(config, target_repo_root=target, use_docker=args.docker)
    thread_id = str(uuid.uuid4())
    cfg = {"configurable": {"thread_id": thread_id}}
    issue_str = f"issue #{args.issue}" if args.issue else "next Backlog issue"
    initial = {
        "messages": [HumanMessage(content=f"Run full SDLC for {issue_str}.")],
        "phase": "intake",
        "memory_snapshot": {},
        "retry_count": 0,
        "current_issue": None,
        "dev_result": None,
        "review_result": None,
        "release_result": None,
    }
    for chunk in graph.stream(initial, cfg, stream_mode="values"):
        phase = chunk.get("phase", "")
        msgs = chunk.get("messages", [])
        if msgs:
            last = msgs[-1]
            content = getattr(last, "content", str(last))
            print(f"[{phase}] {str(content)[:120]}")


def cmd_daemon(args) -> None:
    print("Daemon mode: processing Backlog issues until empty...")
    while True:
        try:
            cmd_run(args)
        except StopIteration:
            print("Backlog empty. Daemon exiting.")
            break
        except KeyboardInterrupt:
            print("Interrupted.")
            break


def main() -> None:
    parser = argparse.ArgumentParser(prog="sdlc-agent")
    parser.add_argument("--config", default="sdlc-agent.yaml")
    parser.add_argument("--target", default=".", help="Path to target repo root")
    parser.add_argument("--docker", action="store_true", default=False)

    sub = parser.add_subparsers(dest="command", required=True)

    bp = sub.add_parser("backlog", help="Read specs and seed GitHub backlog")
    bp.set_defaults(func=cmd_backlog)

    rp = sub.add_parser("run", help="Run SDLC for one issue")
    rp.add_argument("--issue", type=int, default=None)
    rp.set_defaults(func=cmd_run)

    dp = sub.add_parser("daemon", help="Drain Backlog issues in a loop")
    dp.set_defaults(func=cmd_daemon)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
