# Deep Agent Orchestrator — Design Spec
**Date:** 2026-05-26  
**Status:** In Progress (brainstorming)  
**Replaces:** `sdlc-deep-agent-spec.md` (v1 FSM-based architecture)

---

## Vision

A GitHub-native SDLC orchestrator inspired by Claude Code. A Primary deep agent acts as PM, BA, and Architect — it owns the full project lifecycle, creates in-depth GitHub issues, and is the only agent that can close them. Three sub-agents (Developer/Tester, PR Reviewer, Release Engineer) each run as deep agents with their own tools, memory, and Docker-isolated environments. LangGraph drives the state machine. OpenAI provides the LLM backbone.

---

## Section 1: Architecture Overview

### Agent Roster

| Agent | Role | Docker Image | Codebase Access |
|---|---|---|---|
| **Primary** | PM · BA · Architect | None (control plane) | Read specs/docs only — no code writes |
| **Developer/Tester** | Implementation + TDD | Image #1 | Full read/write + test runner |
| **PR Reviewer** | Principal engineer review | Image #2 | Read-only (diff, test reports) |
| **Release Engineer** | Deploy to production | Image #3 | Git merge + Docker deploy tools |

### Framework

- **LangGraph** `StateGraph` — Supervisor pattern. Primary is the top-level graph. Sub-agents are compiled subgraphs invoked as nodes.
- **OpenAI** — LLM backbone for all agents via LangChain's OpenAI integration.
- **GitHub MCP** — Primary's interface to GitHub (issues, labels, PRs, assignments).
- **Docker-backed tools** — Sub-agent tools (test runner, deploy, sandbox) execute inside Docker containers for isolation. The agent process stays in Python; the work happens in containers.

### Control Flow

```
Primary (supervisor graph)
  │
  ├─ creates GitHub issue + writes arch context
  ├─ invokes Developer/Tester subgraph → receives {branch, test_results}
  ├─ writes to GitHub (label: ready-for-review, assign branch)
  ├─ invokes PR Reviewer subgraph → receives {approved | rejected}
  ├─ writes to GitHub (PR approval, review comments)
  ├─ invokes Release Engineer subgraph → HITL checkpoint → receives {deployed | rejected}
  └─ closes GitHub issue, updates living memory, picks next ticket
```

### Communication Model: Hybrid

- **Control bus:** Primary directly invokes sub-agents as LangGraph subgraph calls (not GitHub polling). Handshakes are programmatic and synchronous from Primary's perspective.
- **Audit trail:** After every state change, Primary writes back to GitHub — issue labels, assignments, PR comments, deployment notes. A human can always open GitHub and understand exactly where a ticket is.

### Memory Model

- **Primary — Living Memory:** LangGraph `MemorySaver` for in-session state + a persisted `project_memory.md` on disk. Updated after every closed ticket with architecture decisions, patterns established, lessons learned, and inter-ticket dependencies. This is the architect's growing knowledge base.
- **Sub-agents — Session Memory:** Each sub-agent has its own `MemorySaver` scoped to its current task. No cross-session persistence needed for sub-agents — Primary injects all necessary context at assignment time.

### Migration from v1

| Keep | Replace | Remove |
|---|---|---|
| GitHub MCP client | Hand-rolled FSM → LangGraph StateGraph | Stateless subagent pattern |
| `LocalGitClient` (git tools) | Direct OpenAI calls → LangChain + LangGraph | `TaskAssignment` / `ArtifactReturn` contracts |
| `LocalSubprocessSandbox` | — | Curation gate |
| Skills (markdown files) | — | `OrchestratorSupervisor` (replaced by Primary agent itself) |
| `.env` / `sdlc-agent.yaml` config | — | Phase-based test suite (rewrite around new architecture) |

---

---

## Section 2: Primary Agent

### LangGraph StateGraph Nodes

| Node | Responsibility |
|---|---|
| `intake` | Reads `specs.md` or an existing GitHub issue. Determines run mode (backlog vs single-issue). Loads project memory. |
| `create_issues` | Decomposes spec into GitHub issues. Each issue gets: user story, acceptance criteria, architecture notes, coding standards from living memory. Labels `Backlog`. |
| `assign_development` | Picks next `Backlog` issue. Labels `In Progress`. Invokes Developer/Tester subgraph with full context injection (issue + arch notes + memory snapshot). |
| `assign_review` | Receives branch + test results from Developer. Labels issue `Ready for Review`. Invokes PR Reviewer subgraph with issue + branch + acceptance criteria. |
| `assign_release` | PR approved. Labels issue `Approved`. Invokes Release Engineer subgraph. Waits for HITL checkpoint result. |
| `close_issue` | Deployed. Closes GitHub issue with deployment summary comment. Updates living memory with lessons learned. |
| `handle_rejection` | PR or deploy rejected. Labels issue `Changes Requested`. Re-assigns to Developer with reviewer feedback injected. Logs to memory. |
| `next_ticket` | After close, loops back to `assign_development` for next `Backlog` issue, or exits if backlog empty. |

### Primary's Tools

All tools are GitHub-facing or memory-facing. **No code, git clone, file write, or test tools.**

- `read_spec_file` — reads the project spec document
- `create_github_issue` — creates issue with full story + acceptance criteria
- `update_issue_label` — drives the workflow state visible in GitHub
- `assign_issue` — assigns issue to the relevant sub-agent session
- `add_issue_comment` — audit trail: every handshake gets a comment
- `close_github_issue` — only Primary can call this
- `list_open_issues` — backlog enumeration
- `read_project_memory` / `write_project_memory` — living memory access

### Living Memory Structure (`project_memory.md`)

Persisted to disk across sessions. Injected as context into every sub-agent assignment.

```
architecture_decisions[]   — why key tech choices were made
coding_standards{}         — language, patterns, naming conventions, test requirements
lessons_learned[]          — what went wrong/right per closed ticket
component_map{}            — what files/modules own what domain
open_risks[]               — known technical debt or deferred decisions
```

### Graph State Shape

```python
class PrimaryState(TypedDict):
    current_issue: Issue | None
    phase: str                    # intake | dev | review | release | done
    dev_result: DevResult | None
    review_result: ReviewResult | None
    release_result: ReleaseResult | None
    memory_snapshot: dict
    retry_count: int
    messages: list[BaseMessage]
```

### Constraint

Primary never calls git, writes files to the codebase, or runs tests. All code interaction is delegated to sub-agents via subgraph invocation.

---

---

## Section 3: Sub-Agents

All sub-agents are LangGraph `StateGraph` subgraphs invoked by Primary. Each has session-scoped memory (context injected by Primary at assignment time). Each runs its tools inside a Docker container for isolation.

---

### Developer / Tester — Docker Image #1 (full dev toolchain)

**Purpose:** Takes an issue, runs a TDD loop, writes code + tests, commits to a feature branch, reports branch + test results back to Primary.

#### Graph Nodes

| Node | Responsibility |
|---|---|
| `setup_environment` | Clone/checkout target repo into Docker container. Install deps. Verify clean state. |
| `plan_implementation` | Read issue + arch context. Plan: what files to create/modify, what tests are needed, what the contract looks like. |
| `write_tests_first` | Write unit + integration tests per acceptance criteria. Tests must fail at this point (red). |
| `implement` | Write implementation code. Run tests in sandbox. Iterate until green. Fix lint + type errors. |
| `commit_and_report` | Commit to feature branch. Push. Report branch name + test results to Primary. |

#### Tools
- `read_file` / `write_file` — full codebase read/write
- `run_tests` — sandboxed inside Docker container
- `git_branch` / `git_commit` / `git_push`
- `install_dependencies`
- `search_codebase` — grep / AST search
- `run_shell_command` — Docker-contained, no host access

#### Memory
Session-scoped. Injected at start: issue + acceptance criteria + arch context + memory snapshot from Primary. Fresh Docker container per issue — no state bleeds between tickets.

---

### PR Reviewer — Docker Image #2 (read-only env)

**Purpose:** Receives issue + branch from Primary. Verifies every SDLC gate. Approves or rejects with actionable feedback. Never edits code.

#### Graph Nodes

| Node | Responsibility |
|---|---|
| `load_context` | Checkout the feature branch. Read issue, acceptance criteria, and Primary's arch context. |
| `read_diff` | Read the full PR diff. Map changed files to acceptance criteria. Identify untested paths. |
| `verify_tests` | Read test report + coverage. Verify unit tests exist for all new code. Verify integration tests cover the full acceptance criteria flow. |
| `verify_standards` | Check coding standards, naming, structure, security anti-patterns, no hardcoded secrets. |
| `approve_or_reject` | All gates pass → approve PR + post summary comment. Any gate fails → reject with specific, actionable feedback per criterion. |

#### Tools
- `read_pr_diff`
- `read_test_report` / `read_coverage`
- `read_file` (no write)
- `github_approve_pr`
- `github_request_changes`
- `github_add_review_comment`

#### Constraints
Strictly read-only — no file writes, no git push, no code edits. Rejection feedback must be specific and actionable per failing criterion, not vague.

#### Memory
Session-scoped. Receives: issue + acceptance criteria + coding standards + component map from Primary's living memory. Primary absorbs review lessons via its own memory update after each ticket.

---

### Release Engineer — Docker Image #3 (deploy toolchain)

**Purpose:** Simpler agent. Takes an approved branch. Verifies the build is clean. Presents a release summary to a human. Deploys only after human approval.

#### Graph Nodes

| Node | Responsibility |
|---|---|
| `prepare_release` | Checkout approved branch. Merge into main (or release branch). Tag the release. |
| `build_and_verify` | Build the production Docker image. Run smoke tests inside the container. Verify it starts clean. |
| `present_to_human` | Produce release summary: what changed, diff stats, test results, image size, smoke test output. |
| `await_approval` **(INTERRUPT)** | LangGraph interrupt checkpoint. Execution pauses. Human reviews summary and responds: approve or reject. |
| `deploy` / `rollback` | Approved → push image, deploy container, confirm running. Rejected → report reason to Primary, issue stays open. |

#### Tools
- `git_merge` / `git_tag`
- `docker_build`
- `run_smoke_tests`
- `docker_deploy`
- `generate_release_summary`
- `interrupt` — LangGraph HITL checkpoint

#### Constraints
No auto-deploy ever. Human gate is a hard stop. Release engineer is intentionally the simplest agent — focused, not smart.

#### Memory
Session-scoped. Receives: approved branch + issue summary + deployment target config from Primary.

---

*Section 4: Project structure, config, Docker setup, migration plan (to be written)*
