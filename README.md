# SDLC Deep Agent

A **GitHub-native, LangGraph-based multi-agent SDLC orchestrator** inspired by Claude Code.

A Primary deep agent acts as PM, Business Analyst, and Architect — it owns the full project lifecycle, maintains a living memory of the project, creates in-depth GitHub issues, and is the **only** agent that can close them. Three sub-agents (Developer/Tester, PR Reviewer, Release Engineer) each run as deep LangGraph agents with their own tools and Docker-isolated environments.

---

## Architecture

```
Primary Agent (StateGraph supervisor)
  │
  ├─ reads specs.md → creates in-depth GitHub issues (acceptance criteria, arch notes)
  ├─ invokes Developer/Tester subgraph  → receives {branch, test_results}
  ├─ invokes PR Reviewer subgraph       → receives {approved | rejected}
  ├─ invokes Release Engineer subgraph  → HITL checkpoint → receives {deployed | rejected}
  └─ closes GitHub issue, updates living memory, picks next ticket
```

| Agent | Role | Docker | Codebase Access |
|---|---|---|---|
| **Primary** | PM · BA · Architect | Control plane (no container) | Specs + docs only — never writes code |
| **Developer/Tester** | TDD implementation | `sdlc-developer` | Full read/write + test runner |
| **PR Reviewer** | Principal engineer review | `sdlc-reviewer` | Read-only (diff, coverage, test reports) |
| **Release Engineer** | Deploy to production | `sdlc-release` (Docker-in-Docker) | Git merge + Docker deploy tools |

Every significant state change is written back to GitHub (labels, comments, PR actions). A human can always open GitHub and see exactly where a ticket stands.

---

## Features

- **LangGraph StateGraph** — Primary is the supervisor graph; sub-agents are compiled subgraphs invoked as nodes.
- **Living Memory** — `project_memory.md` grows with every closed ticket: architecture decisions, coding standards, lessons learned, component map, open risks. Injected as context into every sub-agent assignment.
- **GitHub-native SDLC** — `specs.md` → issues → `Backlog` → `In Progress` → `Ready for Review` → `Approved` → closed. Full audit trail in GitHub comments.
- **TDD loop** — Developer/Tester writes tests first (red → green), never the other way.
- **Docker isolation** — each sub-agent's tools execute inside its own container; the Python orchestration process stays on the host.
- **Human-in-the-loop** — Release Engineer has a hard `interrupt` checkpoint before any production deploy.
- **Retry policy** — rejected PRs re-assign to Developer with reviewer feedback; max retries configurable, then issue labeled `Blocked`.
- **backlog / run / daemon** CLI modes.

---

## Requirements

- Python 3.11 or newer
- Git on `PATH`
- Docker (for sub-agent containers and GitHub MCP mode)
- OpenAI API key
- GitHub token with repo/issues/pull_requests access

---

## Installation

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

---

## Configuration

Copy `.env.example` to `.env`:

```powershell
Copy-Item .env.example .env
```

Set these variables:

| Variable | Purpose |
|---|---|
| `OPENAI_API_KEY` | Required for all LLM calls |
| `GITHUB_TOKEN` | Required for live GitHub issues / PRs |

`sdlc-agent.yaml` controls everything else:

```yaml
target:
  repo_url: https://github.com/owner/repo

model:
  default: gpt-4o
  temperature: 0

docker:
  developer_image: sdlc-developer:latest
  reviewer_image: sdlc-reviewer:latest
  release_image: sdlc-release:latest

memory:
  project_memory_path: .deepagent/memory.md

hitl:
  require_release_approval: true
  max_retries: 3
```

---

## Quick Start

### 1. Seed the backlog

Reads `specs.md` from the target repo, decomposes it into in-depth GitHub issues (user stories, acceptance criteria, arch notes), labels them `Backlog`:

```powershell
sdlc-agent --config sdlc-agent.yaml --target ..\my_repo backlog
```

### 2. Run one issue end-to-end

Picks up issue `#5`, invokes Developer → Reviewer → Release Engineer with the HITL gate before deploy:

```powershell
sdlc-agent --config sdlc-agent.yaml --target ..\my_repo run --issue 5
```

Omit `--issue` to auto-pick the next `Backlog` issue.

### 3. Drain the backlog

Loops until `Backlog` is empty:

```powershell
sdlc-agent --config sdlc-agent.yaml --target ..\my_repo daemon
```

Add `--docker` to run sub-agent tools inside their Docker containers (default is local subprocess fallback for development):

```powershell
sdlc-agent --target ..\my_repo --docker run --issue 5
```

---

## Repository Layout

```
sdlc_agent/
├── src/sdlc_agent/
│   ├── agents/
│   │   ├── primary/
│   │   │   ├── graph.py        # Primary StateGraph definition
│   │   │   ├── nodes.py        # intake, create_issues, assign_*, close_issue, handle_rejection
│   │   │   ├── memory.py       # Living memory read/write (project_memory.md)
│   │   │   └── tools.py        # GitHub + memory tools only
│   │   ├── developer/
│   │   │   ├── graph.py        # TDD loop ReAct graph
│   │   │   └── tools.py        # file I/O, test runner, git, shell (all Docker-backed)
│   │   ├── reviewer/
│   │   │   ├── graph.py        # Review loop ReAct graph
│   │   │   └── tools.py        # read-only: diff, coverage, PR approval
│   │   ├── release/
│   │   │   ├── graph.py        # Deploy loop with HITL interrupt
│   │   │   └── tools.py        # docker build/deploy, smoke tests, git merge/tag
│   │   └── runtime.py          # build_runtime() — single assembly entry point
│   ├── state/
│   │   └── schemas.py          # PrimaryState, DevResult, ReviewResult, ReleaseResult
│   ├── docker/
│   │   └── sandbox.py          # DockerSandbox (falls back to subprocess without Docker)
│   ├── mcp/                    # GitHub MCP client + FixtureGitHubProject
│   ├── sandbox/                # LocalSubprocessSandbox base
│   ├── skills/                 # Markdown skills injected into agent system prompts
│   ├── config.py               # RootAgentConfig (yaml + .env)
│   └── cli.py                  # sdlc-agent entrypoint
├── docker/
│   ├── Dockerfile.developer    # Python 3.11 + git + pytest + lint
│   ├── Dockerfile.reviewer     # Python 3.11 + git + pytest-cov (read-only mount)
│   ├── Dockerfile.release      # Docker-in-Docker + git + deploy tools
│   └── docker-compose.yml
├── tests/
├── sdlc-agent.yaml
├── langgraph.json              # LangGraph project manifest
├── ARCHITECTURE.md
└── system-design.md            # Mermaid diagrams
```

---

## Project Memory

`.deepagent/` lives in the **target checkout** (not the control-plane repo):

| File | Content |
|---|---|
| `memory.md` | Primary agent's living memory: arch decisions, coding standards, lessons learned, component map, open risks |

The living memory is injected as context into every sub-agent assignment and updated after every closed ticket.

---

## Running Tests

```powershell
pytest tests/ -v
```

All tests use local stubs — no live OpenAI or GitHub calls required.

---

## Related Reading

| Document | Purpose |
|---|---|
| `ARCHITECTURE.md` | Design decisions and trade-offs |
| `system-design.md` | Mermaid diagrams of the v2 system |
| `docs/superpowers/specs/2026-05-26-deep-agent-orchestrator-design.md` | Full design specification |
| `docs/superpowers/plans/2026-05-26-deep-agent-orchestrator.md` | Implementation plan |
