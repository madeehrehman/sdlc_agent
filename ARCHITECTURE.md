# SDLC Deep Agent — Architecture Decisions

This document is the "here's the tradeoff I considered, here's why it broke
this way" companion to the spec (`sdlc-deep-agent-spec.md`). It documents
the load-bearing decisions and the alternatives I rejected at each branch.

The defensible spine, in one line:

> **Disk is memory, context is the working set, retrieval is the bridge.
> There is exactly one orchestrator because exactly one component must own
> the SDLC state machine *and* the memory curation gate. Subagents are
> stateless workers with least-privilege tool scopes; their assignments are
> made stateful by injection. Recursion depth is fixed at one. Persistent
> project knowledge compounds across sessions as curated artifacts on disk,
> never as replayed trajectories, and never rots, because every durable
> write passes an orchestrator-owned promotion gate that distinguishes
> observation from fact.**

What follows are the seven decisions that spine actually produces.

---

## 1. One orchestrator, specialized subagents (recursion depth = 1)

**Decision.** Exactly one agent (the Orchestrator) owns the long-horizon
plan. Subagents are deep in *capability* (sandbox, filesystem write, LLM
access) but short-horizon — one task in, one verified artifact out, return.
Subagents cannot spawn subagents.

**Why this is load-bearing.** Multi-agent systems fail at two recurring
shapes: (a) two agents racing to mutate the same state, and (b) recursion
chains that no longer terminate because each level's "I'll just delegate"
hides the actual decision boundary. Fixing recursion at 1 and concentrating
state authority in one component removes both failure modes by construction.

**Alternative I considered.** A two-tier orchestrator (a "session" agent
above a "ticket" agent) for parallel multi-ticket work. **Rejected** for
this scope — the existing FSM is per-ticket, and parallel multi-ticket is a
queue-scheduling problem above this layer, not an agent-architecture one.
Once the multi-ticket layer exists, it sits *above* the Orchestrator with
no change to anything below.

---

## 2. The orchestrator owns two things, and only those two

**Decision.** The Orchestrator owns (a) the SDLC state machine and (b) the
memory curation gate. Everything else — code edits, diff analysis, ticket
parsing — lives in subagents.

**Why.** Both are single-owner problems. The FSM is single-owner because
"what phase is this ticket in?" must have exactly one answer. The curation
gate is single-owner because "should this become a durable fact?" must
have exactly one decider; if every subagent could promote its own
proposals, durable memory would drift toward whichever subagent talked
most.

**Concretely.** See `src/sdlc_agent/orchestrator/state_machine.py` (FSM)
and `src/sdlc_agent/orchestrator/curation.py` (gate). The dispatcher
(`dispatcher.py`) is glue: it pulls from the FSM, dispatches to a subagent
in the registry, runs returned proposals through the gate, then transitions.

**Supervisor LLM (hybrid).** When `orchestrator.use_llm_supervisor` is true in
`sdlc-agent.yaml`, an `OrchestratorSupervisor` (`supervisor.py`) uses the
`orchestrator` model role to (1) plan delegation instructions before each
subagent call and (2) advise gate decisions. The FSM still owns transitions:
supervisor recommendations cannot `proceed` when default gate logic would
`block` or `needs_human`, or when `verification.passed` is false. HITL gates
remain human-only. Protocol text lives in `skills/orchestrator-supervisor.md`
and `orchestrator/prompts.py`.

---

## 3. Subagents are stateless; assignments are stateful by injection

**Decision.** Subagents own no files, persist nothing, and hold no memory
across tasks. The Orchestrator decides what slice of project memory is
relevant for *this* task and injects it into the `TaskAssignment`
(`injected_context.project_facts`, `injected_context.subagent_lore`, and —
crucially — the content of prior-phase artifacts inlined into `inputs`).

**Why.** Stateless subagents are testable, swappable, and parallel-safe.
"Stateful by injection" gives them the long-horizon context they need
without granting them write access to anything. The PR Reviewer doesn't
need filesystem access to `.deepagent/`; it needs the relevant project
facts and the diff — both arrive in the assignment.

**Alternative I considered.** Granting subagents read access to
`.deepagent/` so they could "pull what they need." **Rejected** because
that inverts least-privilege: the security story collapses when subagents
discover memory rather than receive curated slices, and the path
"discover → use → propose" creates strong pressure for subagents to
*write* back. Pushing all discovery up to the Orchestrator keeps the
gate honest.

---

## 4. Merge code + test generation into one Developer (test-first)

**Decision.** The Developer is a single subagent running a TDD loop:
write a failing test → run tests (RED) → write minimal code → run tests
(GREEN) → iterate per acceptance criterion. The same loop that writes the
code writes its tests.

**The case for splitting** (what I rejected) was that an independent
adversarial Tester finds bugs the author is blind to. That's a real value,
but it's already preserved elsewhere: the PR Reviewer never wrote the
code and reviews independently. The case *for merging* — which won — is
that TDD enforces testability **by construction**. When code and tests
come out of separate subagents, tests get bolted onto whatever shape the
code already has. When the same loop produces both, the code is shaped
by the tests that exercise it.

**Operationally.** This is why `DEVELOPMENT_GATE` is a single gate
checking *both* code and tests — there's no separate test phase. The gate
condition "tests exist for new code" is itself a routing rule: if the
Developer returns code without tests, the gate fails and routes to RETRY,
not to a fictional missing-tester phase.

---

## 5. Every gate is a router, not a boolean

**Decision.** Each SDLC gate (`REQUIREMENTS_GATE`, `DEVELOPMENT_GATE`,
`REVIEW_GATE`) emits one of four decisions: `PROCEED`, `RETRY`,
`BLOCKED`, `NEEDS_HUMAN`. The next state is determined purely by `(gate,
decision)` (`next_phase_for_decision` in `state_machine.py`); routing has
no hidden global state.

**Why.** Pass/fail loses irrecoverable information. A failed gate that
can plausibly be retried with an enriched assignment (e.g. "ambiguities
remain") is operationally different from one that warrants escalation
("the diff deletes a tested behavior") or termination ("max retries
exceeded"). The 4-route model preserves that distinction in code; the
2-route model would force it into prompts or comments where it rots.

**Human-in-the-loop fits cleanly here.** When a gate is configured for
HITL approval, the gate emits `NEEDS_HUMAN`, and a separate `GateApprover`
protocol (default: `HaltForHuman`) decides what to do next. The FSM never
short-circuits on the approver's behalf, which is what lets us swap
`HaltForHuman` for `AutoApprove` (CI), `AutoReject` (audit smoke), or
`ScriptedApprover` (tests) without touching the dispatcher.

---

## 6. Memory has three stores with three lifetimes; curation is gated

**Decision.** `.deepagent/` separates:

| Store                              | Lifetime          | Loaded                                            |
|-----------------------------------|-------------------|---------------------------------------------------|
| `state/<ticket-id>.json`          | per ticket run    | on resume                                         |
| `project_memory.json` + `subagent_lore/` | across sessions   | every session, injected into every assignment     |
| `episodic/log.jsonl`              | append-only audit | queried for "have we seen this before?"           |
| `trajectories/<session>/`         | cold storage      | never auto-loaded; retrievable by ID              |

**Curation.** Subagents *propose* durable facts via `proposed_memory[]`
in their `ArtifactReturn`. The orchestrator's `CurationGate` is the **sole
writer**. The rules:

- Empty evidence → rejected.
- `confidence: high` + evidence → promoted on first sighting.
- `confidence: medium|low` → recorded as "pending" until a prior sighting
  in the episodic log corroborates the same normalized claim, at which
  point it is promoted.
- Duplicate of an already-promoted claim → corroboration counter bumped,
  evidence/sources accumulated, no duplicate entry.

**Why this is the heart of the system.** Without a gate, "the agent
learned something" decays into either prompt rot (the model hallucinated a
fact, wrote it, now reads it back as ground truth) or a write-amplification
spiral (every run grows the store with near-duplicates). Memory that
compounds requires that durable writes pass an orchestrator-owned filter
distinguishing *observation* from *fact*. Without that filter you do not
have memory; you have noise.

**Alternative I considered.** A "vector store everything, retrieve by
similarity" approach. **Rejected** because it solves a different problem
— retrieval over a large corpus — and the operative bottleneck here is
*write hygiene*, not retrieval cardinality. The store is small (curated
facts only) and is loaded entirely into every assignment. When it grows
past that threshold, retrieval can be swapped underneath without changing
the gate.

---

## 7. Skills are shared infrastructure; trajectories are cold storage

**Decision.** Skills (`skills/*.md`) are versioned, project-agnostic units
of know-how — `tdd-discipline`, `pr-review-rubric`,
`requirement-ambiguity-checklist`. They live in the *system* repo, are
loaded lazily by a shared `SkillLoader`, and are prepended to each
subagent's system prompt under a clearly-marked section.

Skill resolution is **static per-role** in this build: each subagent
class declares `DEFAULT_SKILLS: tuple[str, ...]`. This is the minimum
viable plumbing; the spec contemplates skills being "named in or resolved
from the task assignment," which is an additive change — add a
`skills: list[str]` field to `TaskAssignment` and resolve dynamically when
the orchestrator should override.

**Trajectories** (`.deepagent/trajectories/<session>/<task>.jsonl`) capture
every LLM prompt+response for cold-storage debugging. The episodic log
records *that* a dispatch happened, with a `task_id`; the trajectory file
records *why* the LLM said what it said. Trajectories are append-only
JSONL, one file per task, never auto-loaded — they exist for debugging,
not for replay.

**Alternative I considered for skills.** Pulling skills via retrieval over
a vector index. **Rejected** for this scope because the cardinality is
tiny (≤ 10 skills, ≤ 100 lines each) and the value of explicit, named,
versioned skills outweighs any flexibility from semantic search. Skills
are doctrine, not knowledge; doctrine is named.

---

## Live integration boundary

The GitHub lifecycle seam has two implementations. `FixtureGitHubProject` is the
deterministic test/demo adapter; `GitHubMCPProjectClient` uses the official GitHub
MCP server over stdio/Docker for live Issues and pull requests. The orchestrator
and subagents depend only on `GitHubProjectClient`, so live mode is selected by
`github.lifecycle_client` and `build_github_project_client` without changing
workflow code.

MCP mode requires toolsets `repos`, `issues`, and `pull_requests` (factory
validates `create_pull_request`). Issue lifecycle status is modeled as a single
`status:<slug>` label per issue; `update_project_status` rewrites that label via
`issue_write`.

OpenAI is intentionally not routed through MCP. Root `sdlc-agent.yaml` and the
derived `.deepagent/config.yaml` in the **target checkout** carry per-role model
choices; `build_sdlc_runtime` creates OpenAI clients for Backlog Analyzer,
DeveloperTester, and PR Reviewer. Secrets stay in `.env` on the control machine.

`LocalGitClient` shells out to local `git` for PR Reviewer diffs and for runner-
owned worktree/commit/push on issue-driven runs. It is not a hosted git MCP
service.

---

## 8. Control plane vs target workspace

**Decision.** The **sdlc_agent** repository is the control plane: `sdlc-agent.yaml`,
skills, and the Python package. The **target repository** (for example tictactoe)
is where code, tests, `.deepagent/`, and git remotes live. The operator runs
`sdlc-agent` from the control repo; the agent never nests the target inside the
control repo by default.

**Target checkout resolution** (`target_clone.py`):

| Input | Behavior |
|-------|----------|
| `--target-repo-root` set | Use that directory (created if missing). No auto-clone. |
| Omitted + `lifecycle_client: mcp` | `git clone --depth 1` of `target.repo_url` into `<temp>/sdlc-agent-targets/<owner>_<repo>` (override parent with `SDLC_TARGET_CLONE_PARENT`). Reuses existing clone if `.git` is present. |
| Omitted + `fixture` | Creates the same path layout without cloning (tests pass explicit paths). |

**Memory anchor.** `DeepAgentPaths` and `.deepagent/` are always rooted at the
**target checkout** (clone root), not at the control repo. Trajectories, state,
artifacts, and episodic logs for a ticket live beside the target's source tree.

**Why.** Separating control plane from target workspace matches how CI and humans
work: one orchestrator config drives many repos, and the agent mutates a real git
working tree that can push to `origin`.

---

## 9. Operator entrypoints: runner, runtime, daemon

Three layers sit above the orchestrator:

1. **`build_sdlc_runtime`** (`runtime.py`) — loads root config, resolves target
   checkout, writes derived `.deepagent/config.yaml`, builds GitHub client,
   role-routed LLM clients, subagent registry, and `Orchestrator`. Optional
   `worktree_root` points DeveloperTester sandbox and PR Reviewer `LocalGitClient`
   at a per-issue worktree while memory stays on the clone root.

2. **`run_sdlc_agent`** (`runner.py`) — one ticket run. CLI modes:
   - **`backlog`** — FSM through requirements; stops at `DEVELOPMENT` after
     backlog gate adopts/creates GitHub issue metadata on the ticket.
   - **`full`** — `run_to_completion` on the ticket. Without `--issue-number`,
     runs requirements → development → review on the checkout (or worktree if
     wired). With **`--issue-number`**, issue-driven path (below).
   - **`daemon`** — implemented in `daemon.py`, not a separate FSM: repeatedly
     dequeues lowest-numbered open issue whose lifecycle status is in the queue
     (default `Backlog`) and calls `run_sdlc_agent(..., mode="full", issue_number=…)`.

3. **`sdlc-agent` CLI** (`cli.py`) — parses flags and prints `SDLCRunResult` or
   `DaemonSummary` (issue count, `stopped_reason`).

---

## 10. Issue-driven full runs (worktree, commit, PR)

**Decision.** When `issue_number` is set, the runner adopts an existing GitHub
issue instead of re-running Backlog Analyzer for scope. This is the primary path
for “implement issue N in the target repo and open a PR.”

**Flow.**

1. `get_issue(n)` via GitHub client; set `github_issue_number`, `github_project_item_id`
   (`ISSUE_<n>`), `skip_requirements_analysis`, and `git_work_branch` on ticket inputs.
2. `update_project_status` → **In Development**.
3. Validate `base_ref` (default `develop` from config) exists locally; **do not**
   auto-create promotion branches (`develop` / `release` / `main`).
4. `LocalGitClient.add_worktree` under `<target>/.worktrees/<ticket-id>/` (or
   `--worktrees-dir`) with branch `sdlc/issue-<n>-<slug>`.
5. Seed `requirement_analysis` artifact from issue body + parsed acceptance criteria
   (`issue_workflow.synthetic_requirements_artifact`).
6. `intake` jumps to `DEVELOPMENT` when `skip_requirements_analysis` is set.
7. Subagents run with sandbox/git rooted at the **worktree**.
8. **`OrchestratorHooks`** (dispatcher):
   - After **DEVELOPMENT_GATE** `PROCEED`: commit all changes in worktree (if any),
     `push_branch` to `origin`.
   - After **REVIEW_GATE** `PROCEED`: `create_pull_request` via MCP; store
     `github_pr_number` / `github_pr_url` on ticket inputs.
9. Worktree removed in `finally`; GitHub client closed.

**Contrast with ticket-only `full`.** `full` without `--issue-number` does **not**
install commit/push/PR hooks. It is the classic backlog-ticket path (requirements
artifact from Backlog Analyzer). Uncommitted edits may remain in the checkout;
`NEEDS_HUMAN` is common when DeveloperTester verification fails (for example test
runner layout).

**GitHub sync on phase transitions** (existing): `_sync_github_lifecycle` maps
phases to status labels (In Development, In Review, Release Ready / Done, etc.).
Closing the issue on `DONE` only when `release_to_main_accepted` is set on inputs.

---

## What is intentionally not built

These are deferrals, not architectural gaps — they swap implementations or add
layers **above** the existing orchestrator without changing subagent contracts.

- **Waiting on GitHub Actions / CI.** PRs may trigger workflows in the target
  repo, but the agent does not poll check runs or block on Actions success before
  closing an issue or dequeuing the next one.
- **Target repo bootstrap.** The agent does not copy `.github/workflows/` or
  scaffold branch protection into the target; promotion gates in the **sdlc_agent**
  repo are a reference template only until committed on the target.
- **Automated `develop` → `release` → `main` promotion.** Branch validation exists;
  creating missing promotion branches and merge automation are out of scope.
- **Configurable sandbox test command in YAML.** DeveloperTester uses
  `LocalSubprocessSandbox` default `unittest discover`; pytest/npm targets need
  a config seam or project layout that matches the default.
- **Docker sandbox for the Developer.** `DockerSandbox` can implement the same
  `Sandbox` protocol as `LocalSubprocessSandbox`.
- **LangGraph supervisor wrapper.** Per-transition `save_ticket_state` already
  provides resume durability.
- **Rich CLI** (`init|status|resume`). `backlog` / `full` / `daemon` cover the
  current operator surface.
- **Per-task skill resolution.** Static `DEFAULT_SKILLS` per subagent class today;
  `TaskAssignment.skills` is an additive extension.

---

## How to read the codebase

Start at the seams, not the implementations:

1. `src/sdlc_agent/contracts/` — `TaskAssignment` and `ArtifactReturn` are the
   only two messages crossing the orchestrator/subagent boundary.
2. `src/sdlc_agent/orchestrator/state_machine.py` — pure FSM; `skip_requirements_analysis`
   is honored in `dispatcher.intake` (jump to `DEVELOPMENT`).
3. `src/sdlc_agent/orchestrator/dispatcher.py` — dispatch → curation → gate →
   transition → persist; optional supervisor enrichment; `OrchestratorHooks` after
   dev/review gates; GitHub lifecycle sync.
3b. `src/sdlc_agent/orchestrator/supervisor.py` — LLM delegation planning and gate
   advice when `orchestrator.use_llm_supervisor` is enabled (`runtime.py` wires the
   `orchestrator` model role).
4. `src/sdlc_agent/runner.py` — operator single-run orchestration, issue worktrees, hooks.
5. `src/sdlc_agent/daemon.py` — multi-issue dequeue loop over `list_project_items`.
6. `src/sdlc_agent/target_clone.py` — managed clone outside the control repo.
7. `src/sdlc_agent/runtime.py` — assembly of clients, registry, orchestrator.
8. `src/sdlc_agent/mcp/github_mcp.py` — live Issues + `create_pull_request`.
9. `src/sdlc_agent/mcp/git.py` — local git, worktrees, commit, push.
10. `src/sdlc_agent/subagents/` — stateless workers (prompt + self-checks).
11. `scripts/demo.py` — deterministic fixture demo without MCP clone.
