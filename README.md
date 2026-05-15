# SDLC Deep Agent

A **GitHub-native, project-scoped orchestrator** that drives work from a living
`specs.md` file through backlog creation, test-first implementation, structured
PR review, and PR-gated branch promotion.

The system keeps **disk as memory**, **subagents stateless**, and **every durable
fact behind a curation gate**. It is built in Python around OpenAI structured
outputs, GitHub Issues lifecycle adapters, local `git`, a subprocess
sandbox, reusable skills, and trajectory archiving.

## Overview

This repository is the **control plane**: Python package, `sdlc-agent.yaml`, and
skills. The **target project** (for example a tictactoe app repo) is a separate
Git checkout where code, tests, git remotes, and `.deepagent/` live. Run
`sdlc-agent` from here; do not nest the target inside this repo unless you pass
`--target-repo-root` explicitly.

When you omit `--target-repo-root` and use GitHub MCP mode, the agent clones
`target.repo_url` under `<temp>/sdlc-agent-targets/<owner>_<repo>` (override with
`SDLC_TARGET_CLONE_PARENT`).

Per ticket, the orchestrator runs:

`INTAKE` → **Requirements analysis** from `specs.md` (optional skip for issue-driven runs) → gate → **Development** (DeveloperTester, TDD in sandbox or issue worktree) → gate → **PR review** → gate → `DONE`

The FSM owns phase transitions. Optionally, an **orchestrator supervisor LLM** (`orchestrator.use_llm_supervisor`) plans delegation instructions and advises gate decisions; hard rules still clamp unsafe `proceed` recommendations (see `ARCHITECTURE.md` §2, `system-design.md` §7.1).

`BacklogAnalyzer` reads `specs.md`, compares it with existing GitHub Issues,
creates issues with acceptance criteria, and returns metadata to the orchestrator.
Issue-driven **`full`** and **`daemon`** modes adopt an existing issue, implement
in a git worktree, commit/push after the development gate, and open a PR via
GitHub MCP when configured.

## Features

- Explicit SDLC FSM with `PROCEED` / `RETRY` / `BLOCKED` / `NEEDS_HUMAN` routing.
- Optional **supervisor LLM** for protocol-aware planning and gate advice (hybrid with FSM safety clamps).
- GitHub-native backlog and lifecycle: `specs.md` → GitHub Issues with `status:*` labels.
- Managed target clone (optional) or explicit `--target-repo-root`.
- Issue-driven runs: worktree + branch, commit/push, `create_pull_request` (MCP).
- Multi-issue **`daemon`** mode: dequeue Backlog issues and run issue-driven `full` in a loop.
- DeveloperTester TDD loop (tests + implementation in one subagent).
- PR Reviewer on local git diff with requirement context inlined from prior artifacts.
- Orchestrator-owned curation gate, skills under `skills/`, trajectories under `.deepagent/`.
- Reference workflow template in `.github/workflows/sdlc-promotion.yml` (control repo only; not auto-installed on targets).

## Requirements

- Python 3.11 or newer.
- Git available on `PATH`.
- Docker for live GitHub MCP mode.
- OpenAI API key for live LLM tests or live subagent runs.
- GitHub token with repo access for live GitHub MCP lifecycle integration.

## Installation

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

## Configuration

Copy `.env.example` to `.env` if you plan to run live model calls:

```powershell
Copy-Item .env.example .env
```

Useful variables:

- `OPENAI_API_KEY`: required for live OpenAI calls.
- `GITHUB_TOKEN`: required for live GitHub lifecycle integration.
- `SDLC_TARGET_CLONE_PARENT` (optional): when you omit `--target-repo-root`, MCP mode
  clones `target.repo_url` under this directory (default: ``<temp>/sdlc-agent-targets``).

The root `sdlc-agent.yaml` points the master agent at the target GitHub repo.
The target owner and repository name are derived from the repo URL by default,
and OpenAI model choices live there too. Secrets stay in `.env`:

```yaml
target:
  repo_url: https://github.com/madeehrehman/sdlc_agent_tictactoe
  specs_path: specs.md
github:
  lifecycle_client: mcp
  mcp:
    toolsets:
      - repos
      - issues
      - pull_requests   # required for automated PR creation

# Optional: LLM supervisor plans delegation and advises gates (FSM still authoritative)
# orchestrator:
#   use_llm_supervisor: true
```

Uses `model.roles.orchestrator` when the supervisor is enabled. Protocol skill: `skills/orchestrator-supervisor.md`.

`.deepagent/config.yaml` stores the derived target repo metadata, model
settings, GitHub issue lifecycle settings, and gate options **inside the local
target checkout** (the clone you pass with `--target-repo-root`, or the managed
clone under your temp directory when that flag is omitted in MCP mode).

For live GitHub lifecycle mode, `github.lifecycle_client: mcp` launches the
official GitHub MCP server over stdio/Docker with the configured non-secret
settings:

```powershell
docker run -i --rm `
  -e GITHUB_PERSONAL_ACCESS_TOKEN `
  -e GITHUB_TOOLSETS `
  ghcr.io/github/github-mcp-server
```

The agent passes `GITHUB_TOKEN` from `.env` as `GITHUB_PERSONAL_ACCESS_TOKEN`
and defaults `GITHUB_TOOLSETS` to `repos,issues,pull_requests` (the `pull_requests`
toolset is required for automated PR creation from the agent).

## Quick Start

From the **sdlc_agent** repo (with `.env` and `sdlc-agent.yaml` configured):

```powershell
python -m pytest
python scripts\demo.py
python -m pytest --run-live -m live
python -m pytest --run-live -m github_live
```

### Recommended path for a target repo (e.g. tictactoe)

**1. Seed backlog** (reads `specs.md` via MCP, creates/adopts issues, stops at development):

```powershell
sdlc-agent --mode backlog --ticket-id TTT-SEED
```

**2. Implement one issue end-to-end** (worktree, commit, push, open PR — preferred for real delivery):

```powershell
sdlc-agent --mode full --issue-number 5 --base-ref develop
```

Omit `--target-repo-root` to use the managed clone under `%TEMP%\sdlc-agent-targets\`.
The target clone must already have branch `develop` (or your `--base-ref`); the agent
does not create promotion branches for you.

**3. Drain the backlog** (optional):

```powershell
sdlc-agent --mode daemon --base-ref develop --max-issues 10
```

### Other modes

**Ticket-only full** (requirements → dev → review on a ticket; no auto commit/PR):

```powershell
sdlc-agent --mode full `
  --ticket-id TTT-SEED `
  --base-ref develop `
  --head-ref HEAD
```

Use an explicit clone if you prefer:

```powershell
sdlc-agent --mode full `
  --target-repo-root D:\work\sdlc_agent_tictactoe `
  --ticket-id TTT-SEED `
  --base-ref develop
```

### Issue-driven full run (worktree + PR)

For an **existing** GitHub issue, `full` mode can skip backlog analysis, create a
dedicated git **worktree** and branch from your base branch (default `develop` from
config), run development + review in that sandbox, **commit and push** after the
development gate passes, then **open a PR** into the base branch via GitHub MCP
`create_pull_request`. The local clone must already contain the base branch; the
runner does **not** create `develop` / `release` / `main` for you.

```powershell
sdlc-agent --mode full `
  --target-repo-root ..\my_clone `
  --issue-number 5 `
  --base-ref develop
```

Optional: `--worktrees-dir` to override the default `<target>/.worktrees/` parent
directory for per-ticket worktrees. Release/main promotion and Actions are still
out of scope for this path; the issue stays open with lifecycle labels through
`DONE` (e.g. Release Ready unless `--release-to-main-accepted`).

`full` mode without `--issue-number` runs the usual backlog-driven path for a ticket.

### Multi-issue daemon

`daemon` mode repeatedly picks the **lowest-numbered** open issue whose lifecycle
status is **Backlog** (or statuses from `--daemon-dequeue-status`), then runs the
same **issue-driven** `full` pipeline as `--issue-number`. Stops when the queue is
empty or after `--max-issues` starts. Needs `GITHUB_TOKEN`, Docker (MCP), and
`pull_requests` in MCP toolsets for PR creation.

```powershell
sdlc-agent --mode daemon --base-ref develop --max-issues 10
```

Use `--daemon-continue-on-error` to keep draining after a failed issue; optional
`--daemon-sleep-seconds` adds a pause between attempts.

Live OpenAI tests are skipped unless `--run-live` and `OPENAI_API_KEY` are
present. Live GitHub MCP tests also require `GITHUB_TOKEN`, Docker, and
`sdlc-agent.yaml`; they can create, status-label, and close a test issue labeled
`sdlc-agent-live-test` in the configured target repo.

## Repository Layout

| Path | Role |
|------|------|
| `sdlc-agent.yaml` | Control-plane config: target repo URL, models, GitHub MCP |
| `src/sdlc_agent/contracts/` | `TaskAssignment` and `ArtifactReturn` |
| `src/sdlc_agent/orchestrator/` | FSM, dispatcher (+ `OrchestratorHooks`), `OrchestratorSupervisor`, curation, HITL |
| `src/sdlc_agent/memory/` | `.deepagent/` paths, stores, trajectories |
| `src/sdlc_agent/mcp/` | GitHub fixture + MCP, stdio transport, `LocalGitClient` |
| `src/sdlc_agent/target_clone.py` | Managed clone under temp (or `SDLC_TARGET_CLONE_PARENT`) |
| `src/sdlc_agent/runner.py` | Single-run operator (`backlog` / `full` / issue-driven) |
| `src/sdlc_agent/daemon.py` | Multi-issue dequeue supervisor |
| `src/sdlc_agent/issue_workflow.py` | Issue adoption helpers, synthetic requirements artifact |
| `src/sdlc_agent/runtime.py` | Assemble clients, registry, orchestrator |
| `src/sdlc_agent/cli.py` | `sdlc-agent` entrypoint |
| `src/sdlc_agent/subagents/` | BacklogAnalyzer, DeveloperTester, PRReviewer |
| `skills/` | Shared markdown skills (incl. `orchestrator-supervisor.md` when LLM supervisor on) |
| `scripts/demo.py` | Fixture demo without MCP clone |
| `ARCHITECTURE.md` | Tradeoffs and extension seams |
| `system-design.md` | Mermaid diagrams for current system |
| `.github/workflows/sdlc-promotion.yml` | Reference PR gates (not pushed to targets by agent) |
| `tests/phase0` … `phase5` | Phase-aligned pytest suite |

## Project Memory

`.deepagent/` is created in the **target checkout** (not in the control-plane repo):

- `config.yaml`: repo, model, GitHub, and gate configuration.
- `project_memory.json`: curated project facts.
- `subagent_lore/*.json`: role-specific durable lore.
- `episodic/log.jsonl`: append-only audit events with `session_id`.
- `artifacts/<ticket-id>/`: persisted subagent artifacts.
- `state/<ticket-id>.json`: resumable FSM state.
- `trajectories/<session-id>/<task-id>.jsonl`: cold LLM prompt/response traces.

## Extending

- **GitHub:** `GitHubProjectClient` — `FixtureGitHubProject` (tests) or `GitHubMCPProjectClient` (live Issues + PRs).
- **Git:** `LocalGitClient` — diff for review; worktree/commit/push in issue-driven runner hooks.
- **Sandbox:** `LocalSubprocessSandbox` today; `DockerSandbox` can implement the same protocol.

**Not built yet** (see `ARCHITECTURE.md`): waiting on target-repo CI/Actions before closing or dequeuing the next issue; auto-installing workflows on the target; automated `develop` → `release` → `main` promotion; configurable per-target test command in YAML.

Diagrams: `system-design.md`. Design tradeoffs: `ARCHITECTURE.md`. Full contracts: `sdlc-deep-agent-spec.md`.
