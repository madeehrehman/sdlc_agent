# SDLC Deep Agent

A **GitHub-native, project-scoped orchestrator** that drives work from a living
`specs.md` file through backlog creation, test-first implementation, structured
PR review, and PR-gated branch promotion.

The system keeps **disk as memory**, **subagents stateless**, and **every durable
fact behind a curation gate**. It is built in Python around OpenAI structured
outputs, GitHub Issues/Projects lifecycle adapters, local `git`, a subprocess
sandbox, reusable skills, and trajectory archiving.

## Overview

The agent attaches to a target GitHub repository, initializes `.deepagent/`, and
runs work through:

`INTAKE` -> **Requirements analysis** from `specs.md` -> gate -> **Development**
(DeveloperTester, TDD in a sandbox) -> gate -> **PR review** -> gate -> `DONE`

`BacklogAnalyzer` reads `specs.md`, compares it with existing GitHub Project
items, creates GitHub Issues with full acceptance criteria, and returns the
created issue metadata to the orchestrator. The orchestrator can then run a
selected issue through implementation, review, project-state updates, and issue
closure.

## Features

- Explicit SDLC FSM with `PROCEED` / `RETRY` / `BLOCKED` / `NEEDS_HUMAN` routing.
- GitHub-native backlog and lifecycle: `specs.md` -> GitHub Issues -> GitHub Project states.
- DeveloperTester loop that writes tests and implementation together.
- PR Reviewer that receives requirement analysis, implementation summary, and git diff.
- PR-gated GitHub Actions promotion from `develop` to `release` to `main`.
- Container smoke verification in Actions when a target project has a `Dockerfile`.
- Orchestrator-owned curation gate for durable project memory and subagent lore.
- Skills loaded from `skills/*.md` and raw LLM trajectories archived under `.deepagent/trajectories/`.

## Requirements

- Python 3.11 or newer.
- Git available on `PATH`.
- OpenAI API key only for live LLM tests or live subagent runs.
- GitHub token only for a future live GitHub client; tests and demo use fixture clients.

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

The root `sdlc-agent.yaml` points the master agent at the target GitHub repo.
The target owner, repository name, and GitHub Project name are derived from the
repo URL by default, and OpenAI model choices live there too. Secrets stay in
`.env`:

```yaml
target:
  repo_url: https://github.com/madeehrehman/sdlc_agent_tictactoe
  specs_path: spec.md
```

`.deepagent/config.yaml` stores the derived target repo metadata, model
settings, GitHub project settings, and gate options inside the target repo.

## Quick Start

```powershell
python -m pytest
python scripts\demo.py
python -m pytest --run-live -m live
```

Live tests are skipped unless `--run-live` and required credentials are present.

## Repository Layout

- `src/sdlc_agent/contracts/`: assignment and artifact contracts.
- `src/sdlc_agent/orchestrator/`: FSM, dispatcher, curation, HITL.
- `src/sdlc_agent/memory/`: `.deepagent/` paths, stores, trajectories.
- `src/sdlc_agent/mcp/github.py`: fixture GitHub Issues/Projects lifecycle client.
- `src/sdlc_agent/mcp/git.py`: local git diff client.
- `src/sdlc_agent/subagents/`: BacklogAnalyzer, DeveloperTester, PRReviewer.
- `skills/`: reusable markdown skills.
- `scripts/demo.py`: deterministic GitHub-native demo using canned LLM responses.
- `.github/workflows/sdlc-promotion.yml`: PR-gated promotion checks.
- `tests/phase0` ... `tests/phase5`: phase-aligned pytest suite.

## Project Memory

`.deepagent/` is created in a target repo:

- `config.yaml`: repo, model, GitHub, and gate configuration.
- `project_memory.json`: curated project facts.
- `subagent_lore/*.json`: role-specific durable lore.
- `episodic/log.jsonl`: append-only audit events with `session_id`.
- `artifacts/<ticket-id>/`: persisted subagent artifacts.
- `state/<ticket-id>.json`: resumable FSM state.
- `trajectories/<session-id>/<task-id>.jsonl`: cold LLM prompt/response traces.

## Extending

The first GitHub client is fixture-backed and deterministic. A live GitHub
implementation should satisfy the same surface as `FixtureGitHubProject`:
read `specs.md`, create issues, add/update Project items, and close issues.

Future deployment providers can sit behind the current GitHub Actions smoke-test
boundary. The first implementation only builds and runs a container in Actions
when a `Dockerfile` exists.
