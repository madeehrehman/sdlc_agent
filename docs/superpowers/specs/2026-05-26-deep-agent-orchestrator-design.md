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

*Section 3: Sub-agents — Developer/Tester, PR Reviewer, Release Engineer (to be written)*  
*Section 4: Project structure, config, Docker setup, migration plan (to be written)*
