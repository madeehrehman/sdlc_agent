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

*Section 2: Primary Agent — internal graph, tools, memory model (to be written)*  
*Section 3: Sub-agents — Developer/Tester, PR Reviewer, Release Engineer (to be written)*  
*Section 4: Project structure, config, Docker setup, migration plan (to be written)*
