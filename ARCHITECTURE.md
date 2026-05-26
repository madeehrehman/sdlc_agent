# SDLC Deep Agent v2 — Architecture Decisions

This document records the load-bearing decisions in the v2 LangGraph-based multi-agent SDLC orchestrator. Each section names the decision, explains why it is load-bearing, and documents the alternative that was rejected.

The defensible spine in one sentence:

> **One Primary agent owns the project lifecycle and living memory. Three deep sub-agents execute in Docker-isolated environments. LangGraph StateGraph drives all state transitions. GitHub is the audit trail. Human approval gates the only irreversible action.**

---

## 1. One Primary agent as PM + BA + Architect (depth = 1)

**Decision.** A single Primary agent owns the long-horizon plan, creates GitHub issues, manages all workflow routing, and is the only agent that can close issues. Sub-agents execute one task and return a result. Sub-agents cannot spawn sub-agents. Recursion depth is fixed at 1.

**Why this is load-bearing.** Multi-agent systems fail in two recurring shapes: (a) two agents racing to mutate the same state, and (b) delegation chains that no longer terminate. Fixing recursion at 1 and concentrating state authority in the Primary removes both failure modes by construction. Merging PM + BA + Architect into one agent also avoids the "telephone game" failure where a PM describes requirements to a BA who re-describes them to an Architect — each handoff losing fidelity.

**Alternative rejected.** Separate PM, BA, and Architect agents. Rejected because each handoff introduces interpretation loss, and the Primary's value is precisely its unified, unbiased view of the full project — no single-role perspective can create that.

---

## 2. Primary owns exactly two things: SDLC workflow + living memory

**Decision.** The Primary agent owns (a) the SDLC state machine (which issue is in which phase, who has it, what the retry count is) and (b) the project's living memory (architecture decisions, coding standards, lessons learned, component map, open risks). Everything else — writing code, reviewing diffs, deploying containers — is delegated to sub-agents via subgraph invocation.

**Constraint.** The Primary never calls git, writes source files, runs tests, or inspects code. Any action that touches the codebase goes through a sub-agent.

**Why.** Both are single-owner problems. "What phase is this issue in?" must have exactly one answer. "What are the project's coding standards?" must have one authoritative source. Distributing either across multiple agents creates inconsistency by construction.

---

## 3. Sub-agents are deep in capability, session-scoped in memory

**Decision.** Each sub-agent is a fully capable LangGraph ReAct agent with its own toolset. But memory is session-scoped: the Primary injects all necessary context (issue, acceptance criteria, architecture notes, living memory snapshot) at assignment time. Sub-agents do not read `.deepagent/` directly.

**Why.** Stateless-with-injection gives sub-agents the long-horizon context they need without granting them write access to shared state. "Discover your own context" inverts least-privilege: it creates strong pressure for sub-agents to also write back, which corrupts the shared memory. Pushing all memory reads and writes up to the Primary keeps the gate honest.

**Concretely:** `build_primary_graph` passes the living memory snapshot as part of the subgraph invocation payload. Sub-agents receive context; they do not query it.

---

## 4. Developer/Tester runs a TDD loop (test-first, not test-after)

**Decision.** The Developer/Tester sub-agent uses a strict TDD loop: write failing tests first (RED) → write minimal implementation → run tests (GREEN) → iterate. The same agent writes both code and tests.

**The case for splitting** (rejected) was that an independent adversarial Tester finds bugs the author is blind to. That value is preserved elsewhere: the PR Reviewer never wrote the code and reviews it independently. The case **for merging** — which won — is that TDD enforces testability *by construction*. Code shaped by tests that exercise it has better contracts and fewer hidden assumptions than code with tests bolted on afterward.

**Gate condition.** The Developer/Tester's result is only considered successful if both the implementation and the tests exist and pass. There is no separate "test phase" gate — incomplete test coverage is a RETRY signal, not a new phase.

---

## 5. LangGraph StateGraph for Primary, ReAct for sub-agents

**Decision.** The Primary uses an explicit `StateGraph` with named nodes (`intake`, `create_issues`, `assign_development`, `assign_review`, `assign_release`, `close_issue`, `handle_rejection`, `next_ticket`). Sub-agents use `create_react_agent` — they reason and act freely within their tool set.

**Why.** The Primary's workflow is a well-defined state machine with known transitions and explicit routing logic. An explicit graph makes that visible, testable, and auditable. Sub-agents, by contrast, need judgment within their task: the Developer decides how to structure files, the Reviewer decides which coverage gaps are blocking — a ReAct loop fits this better than a hard-coded node sequence.

**Supervisor pattern.** Primary invokes sub-agent subgraphs synchronously as nodes in its own graph. From Primary's perspective, each sub-agent is a single node that returns a typed result (`DevResult`, `ReviewResult`, `ReleaseResult`).

---

## 6. GitHub as the audit trail, not the communication bus

**Decision.** Primary invokes sub-agents via direct LangGraph subgraph calls (programmatic, synchronous). GitHub is written to *after* each state change — issue labels, assignment comments, PR reviews, deployment notes — but is not polled for routing signals.

**Why.** Polling GitHub for routing decisions introduces latency, requires network access at every routing step, and creates brittle coupling to GitHub label state. Direct subgraph invocation is fast, reliable, and testable without GitHub. The GitHub writes are the audit trail a human reads; they do not drive the machine.

**Result.** A human can open GitHub at any moment and read exactly what phase a ticket is in and what happened at each handoff. The agent never waits on GitHub to proceed.

---

## 7. Docker isolation for all sub-agents

**Decision.** Each sub-agent's tools execute inside a dedicated Docker container. The Python orchestration process runs on the host; it passes commands to containers via `DockerSandbox`. Three images: `sdlc-developer` (full dev toolchain), `sdlc-reviewer` (read-only, pytest-cov), `sdlc-release` (Docker-in-Docker for deploy).

**Why.** Code execution, testing, and deployment are inherently side-effectful. Isolating them in containers prevents cross-ticket contamination, ensures reproducible environments, and bounds the blast radius of any sub-agent mistake to its own ephemeral container.

**Developer fallback.** `DockerSandbox` falls back to `LocalSubprocessSandbox` when `use_docker=False` (set at runtime by the `--docker` flag). This lets the entire system run without Docker for local development and CI tests.

---

## 8. Living memory compounds; session memory is ephemeral

**Decision.** Primary maintains a persisted `project_memory.md` that grows after every closed ticket. Sub-agents have session-only `MemorySaver` checkpointers — their memory is wiped when the task ends.

**Memory structure (Primary's `project_memory.md`):**

```
architecture_decisions[]   — why key tech choices were made
coding_standards{}         — language, patterns, naming conventions, test requirements
lessons_learned[]          — what went wrong/right per closed ticket
component_map{}            — what files/modules own what domain
open_risks[]               — known technical debt or deferred decisions
```

**Why this is the heart of the system.** Without growing memory, each ticket starts cold. With unfiltered memory, every run grows the store with near-duplicates and hallucinated facts. Primary-owned, post-ticket memory updates with a structured schema gives compounding knowledge without noise accumulation.

**Alternative rejected.** Vector store with semantic retrieval over everything. Rejected because the operative bottleneck is write hygiene (what becomes a durable fact), not retrieval cardinality. The store is small enough to inject entirely. When it outgrows that, retrieval can be added underneath without changing the schema.

---

## 9. Human-in-the-loop at exactly one point: Release

**Decision.** The Release Engineer sub-agent has a single mandatory `interrupt` checkpoint before any deploy. Execution pauses; a human reviews the release summary (what changed, test results, image size, smoke test output) and approves or rejects. No other agent gate requires human approval.

**Why.** Production deploy is the only truly irreversible action in the system. Every other gate (dev, review) can be retried or rolled back. Making HITL mandatory at exactly one point keeps the system maximally autonomous while protecting the one action where autonomy is unsafe.

**Implementation.** LangGraph's `interrupt` function pauses the graph. The HITL configuration in `sdlc-agent.yaml` (`hitl.require_release_approval: true`) enables this checkpoint. The interrupt is hard-coded in the release graph — it cannot be configured away.

---

## 10. Control plane vs target workspace

**Decision.** The `sdlc_agent` repository is the **control plane**: `sdlc-agent.yaml`, skills, the Python package, Docker images. The **target repository** is where code, tests, and `.deepagent/` live. The two are always separate checkouts.

**Memory anchor.** `.deepagent/memory.md` lives in the **target checkout**, not the control repo. One control plane can drive many target repos over time.

**Why.** Separating control plane from target workspace matches how CI and humans work: one orchestrator config drives many repos, and the agent mutates a real git working tree that pushes to `origin`.

---

## 11. Skills are shared, static-per-role infrastructure

**Decision.** `skills/*.md` are versioned, project-agnostic units of know-how (`tdd-discipline.md`, `pr-review-rubric.md`, `requirement-ambiguity-checklist.md`). Each sub-agent declares which skills it loads; the `SkillLoader` prepends them to the system prompt.

**Why.** Skills are doctrine, not knowledge. Doctrine is named, versioned, and explicit — not retrieved by semantic similarity. The cardinality is tiny (< 10 files) and the value of reading "tdd-discipline" at the Developer's prompt boundary outweighs any flexibility from vector retrieval.

---

## What is intentionally not built

These are deferrals, not architectural gaps. Each can be added without changing any existing component contract.

- **Waiting on GitHub Actions / CI.** PRs may trigger workflows in the target repo; the agent does not poll check runs before closing an issue or picking the next ticket.
- **Automated branch promotion.** `develop → release → main` merge automation is out of scope. The Release Engineer deploys; it does not manage promotion branches.
- **Parallel multi-ticket processing.** The daemon processes issues sequentially (FIFO by issue number). Parallel processing is a queue-scheduling problem above the Primary — it would sit above `build_runtime()` without changing any agent.
- **Target repo bootstrap.** The agent does not scaffold `.github/workflows/` or branch protection into the target.
- **Per-target configurable test command.** Developer/Tester defaults to `pytest`. A `tests.command` key in `sdlc-agent.yaml` is an additive config seam.
- **Rich CLI.** `backlog / run / daemon` cover the current operator surface. `init | status | resume` are additive.

---

## How to read the codebase

Start at the seams:

1. `src/sdlc_agent/state/schemas.py` — `PrimaryState` and the three result types are the only messages crossing the Primary/sub-agent boundary.
2. `src/sdlc_agent/agents/primary/graph.py` — the Primary StateGraph. Routing logic lives here.
3. `src/sdlc_agent/agents/primary/nodes.py` — the 8 node implementations.
4. `src/sdlc_agent/agents/primary/memory.py` — living memory read/write/update.
5. `src/sdlc_agent/agents/developer/graph.py` — Developer/Tester ReAct graph.
6. `src/sdlc_agent/agents/reviewer/graph.py` — PR Reviewer ReAct graph.
7. `src/sdlc_agent/agents/release/graph.py` — Release Engineer graph with HITL interrupt.
8. `src/sdlc_agent/agents/runtime.py` — `build_runtime()`: single assembly entry point.
9. `src/sdlc_agent/docker/sandbox.py` — `DockerSandbox` with local fallback.
10. `src/sdlc_agent/cli.py` — `sdlc-agent backlog | run | daemon` entrypoint.
