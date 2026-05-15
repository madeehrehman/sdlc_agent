# SDLC Deep Agent — Build Specification

> **How to use this document.** This is both a design spec and an IDE build prompt. Paste it whole into your coding agent as the anchoring context, then drive the build phase by phase (Section 11). Each phase is independently testable. The architecture is fixed; the tech stack in Section 9 separates *recommended* swaps from the *reference implementation* in this repo.

> **Implementation alignment (reference repo).** Sections 1–8 and 13 describe the **architecture** (load-bearing invariants). Sections 9–11 document how the **current Python package** (`sdlc_agent`) realizes it: vanilla FSM orchestration (not LangGraph), OpenAI structured outputs, GitHub Issues + PRs via fixture or GitHub MCP (stdio/Docker), `LocalGitClient` for diff/worktree/commit/push, `LocalSubprocessSandbox` for DeveloperTester, skills under `skills/`, trajectories under `.deepagent/trajectories/<session-id>/`, operator layers (`runner.py`, `daemon.py`, `target_clone.py`, `cli.py`), and issue-driven full runs (worktree, commit/push, `create_pull_request`). The **control repo** holds `sdlc-agent.yaml`; the **target checkout** (managed clone or `--target-repo-root`) holds code and `.deepagent/`. See `README.md`, `ARCHITECTURE.md`, and `system-design.md`.

---

## 1. Context & Goal

Build a **project-scoped, multi-agent system that runs the software development lifecycle** for a given repository — analogous to Claude Code, but structured as one orchestrator owning an explicit SDLC state machine, delegating to specialized stateless subagents.

The system attaches to any project repo, maintains a project-local memory folder (`.deepagent/`), and persists curated knowledge across sessions so it compounds rather than restarting cold each run.

**Origin:** technical assessment for an Accenture tech-lead role. See Section 12 for what to actually build for the deliverable versus what to architect for.

---

## 2. Core Architecture Principles

These are load-bearing. Every component decision traces back to one of them.

1. **One orchestrator, specialized subagents.** The orchestrator is the only agent with a long-horizon plan and authority over workflow state. Subagents are deep in *capability* (sandbox, filesystem, skills, internal planning scratchpad) but short-horizon — one task, one verified artifact, return.
2. **Recursion depth = 1.** The orchestrator delegates; subagents execute; nobody delegates further. Subagents cannot spawn subagents. This is a named reliability property.
3. **Disk is memory, context is the working set, retrieval is the bridge.** "Know everything about the project" means "can reach anything on disk," not "currently holding everything in context." Never replay raw trajectories into context.
4. **The orchestrator owns two things: the SDLC state machine and the memory curation gate.** Both are single-owner by design.
5. **Subagents are stateless workers, but their task assignments are stateful.** The orchestrator makes them stateful by *injecting* the relevant slice of project memory into each assignment. Subagents own nothing, write nothing, persist nothing.
6. **Memory writes are gated like code.** Subagents *propose* durable facts; the orchestrator decides what gets promoted. Distinguish *observation* ("this test failed this run") from *durable fact* ("this test is flaky").
7. **Least privilege per subagent.** Tools, MCP servers, and filesystem scope are granted per subagent role, not globally.

---

## 3. System Components

### 3.1 Orchestrator (the deep agent)

Owns:
- The **SDLC state machine** (Section 4) — the single source of truth for "what phase is this ticket in."
- The **planning tool** — long-horizon plan across SDLC phases.
- **Project memory** on the filesystem — read and write authority (Section 5).
- **Memory curation** — the promotion gate from proposed → durable.
- **Human-in-the-loop gates** — pausing for approval at defined checkpoints.
- **GitHub Issues** (issue lifecycle) and coordination with **local git** (via runner hooks on issue-driven paths: worktree, commit, push, open PR).

Does NOT: write code, generate tests, or review PRs directly. It dispatches and gates. Commit/push and `create_pull_request` are **runner-owned hooks** after development/review gates when `issue_number` is set — not separate subagents.

### 3.2 Subagents

Each is a stateless worker: receives a stateful task assignment (Section 6), does one job, self-verifies, returns a structured artifact plus optional proposed-memory entries.

| Subagent | Job | Tools / MCP | Filesystem | 
|---|---|---|---|
| **Backlog Analyzer** | Read `specs.md`, identify missing work, create GitHub Issues with acceptance criteria, and output structured requirement analysis. | GitHub Issues (read/write) | read `specs.md` |
| **Developer** | Implement against the requirement analysis **test-first**: every unit of code is written with its corresponding test in the same TDD loop (failing test → code → pass → iterate). Returns implementation + test suite, all tests green. | Sandbox (execute) | read all, write working tree + test dirs |
| **PR Reviewer** | Analyze the diff, produce structured review against a rubric. Independent eyes — did not write the code. | git MCP (read diff, post review) | read-only |

Each subagent has an **internal planning scratchpad** for its one task — ephemeral, dies with the task.

Each subagent has **per-subagent lore** (e.g. the PR reviewer's "recurring issues in this repo"). This lore lives in the orchestrator's filesystem store as a memory category and is *injected* when that subagent is dispatched — the subagent does not own a file.

---

## 4. The SDLC State Machine

Owned by the orchestrator. Each phase ends at a **gate** where the orchestrator decides: **proceed / retry / escalate to human**.

```
INTAKE
  └─> REQUIREMENTS_ANALYSIS        (dispatch: Backlog Analyzer)
  │     OR skip when issue-driven: INTAKE ──> DEVELOPMENT (synthetic requirement artifact from GitHub issue)
        └─> REQUIREMENTS_GATE      unambiguous? acceptance criteria present?
                                   [optional human approval]
              └─> DEVELOPMENT      (dispatch: Developer — TDD: code + tests together)
                    └─> DEVELOPMENT_GATE   compiles? tests exist for new code?
                                           tests green? coverage acceptable?
                          └─> PR_REVIEW    (dispatch: PR Reviewer)
                                └─> REVIEW_GATE   verdict?
                                                  [human approval]
                                      └─> DONE

Any gate may route to:  RETRY (same phase, enriched assignment)
                        BLOCKED (record reason, halt)
                        NEEDS_HUMAN (escalate with context)
```

Because the Developer works test-first, there is no separate test phase or test gate — `DEVELOPMENT_GATE` verifies code *and* tests as one check. Tests existing for new code is itself a gate condition: if the Developer returns code without corresponding tests, the gate fails and routes to RETRY.

**Gate logic is the orchestrator's intelligence.** A gate is not a pass/fail boolean — it reads the returned artifact's `verification` block, checks it against project memory, and decides. On RETRY, the next assignment is enriched with what failed and why.

State is persisted to `.deepagent/state/<ticket-id>.json` after every transition so a session can resume mid-lifecycle.

---

## 5. Memory Architecture

### 5.1 Root startup config

The SDLC agent system repo has a root `sdlc-agent.yaml` control-plane file. It
contains non-secret startup settings only: the target GitHub repo URL,
`specs.md` path, branch names, GitHub lifecycle client mode, and per-role OpenAI
model choices. `OPENAI_API_KEY` and `GITHUB_TOKEN` stay in `.env`.

On startup, the master agent loads `.env`, then `sdlc-agent.yaml`, parses
`target.repo_url`, derives the GitHub owner/repository name, resolves a **target
checkout** (see §5.1.1), initializes that checkout's `.deepagent/config.yaml`, and
starts the SDLC workflow.

#### 5.1.1 Target checkout (control plane vs target workspace)

The **system repository** (`sdlc_agent`) is the control plane: package, skills,
`sdlc-agent.yaml`. The **target repository** is where application code and
`.deepagent/` live.

| Resolution | Behavior |
|------------|----------|
| `--target-repo-root` set | Use that path (created if missing). |
| Omitted + `github.lifecycle_client: mcp` | `git clone --depth 1` of `target.repo_url` into `<temp>/sdlc-agent-targets/<owner>_<repo>` (override parent: env `SDLC_TARGET_CLONE_PARENT`). Reuse if `.git` already exists. |
| Omitted + `fixture` | Create the same directory name without cloning (tests pass explicit paths). |

Issue-driven runs add a **git worktree** under `<checkout>/.worktrees/<ticket-id>/`
(or `--worktrees-dir`) with branch `sdlc/issue-<n>-<slug>`; DeveloperTester and
PR Reviewer use the worktree as sandbox/git root while memory stays on the clone root.

### 5.2 The `.deepagent/` project-local folder

Created in the **target checkout** on first run (not inside the control-plane repo
unless you point `--target-repo-root` there). This *is* the memory — the context window only ever holds a working set.

```
.deepagent/
  config.yaml                 # repo info, MCP endpoints, gate policy, model config
  project_memory.json         # CURATED durable facts — the compounding store
  subagent_lore/
    backlog_analyzer.json      # per-subagent durable lore
    developer.json
    pr_reviewer.json
  episodic/
    log.jsonl                 # append-only audit log: what happened, when, by whom
  artifacts/
    <ticket-id>/
      requirement_analysis.json   # Backlog Analyzer return (full ArtifactReturn persisted)
      implementation_summary.json # Developer return
      review.json                   # PR Reviewer return
  state/
    <ticket-id>.json          # current-task working state (resume point)
  trajectories/
    <session-id>/             # COLD storage: per-task trace files (see §5.2)
      <task-id>.jsonl         # one JSON object per line: LLM prompt + response + metadata
```

### 5.3 The three memory stores (distinct lifetimes, distinct load patterns)

1. **Current-task working state** — `state/<ticket-id>.json`. This ticket, this branch, the active plan. Lives and dies with the run. Loaded on resume.
2. **Cross-task project memory** — `project_memory.json` + `subagent_lore/`. The genuinely valuable compounding store: "repo uses pytest," "auth module is fragile," "team rejects PRs without tests." Small, curated, cheap. Loaded every session.
3. **Episodic / audit log** — `episodic/log.jsonl`. Append-only traceability record. Not loaded into context; queried for "have we seen this before" and for governance. In the reference implementation, each event includes `session_id` (orchestrator run id) alongside `ticket_id` and `kind` so runs correlate with trajectory files.

**Raw trajectories** are archived to `trajectories/<session-id>/<task-id>.jsonl` as cold storage. Each line is one LLM interaction (system+user messages as sent to the model, raw assistant string, `kind` such as `developer.step` / `developer.summary`, optional metadata). Retrievable for debugging *why* a past decision was made; **never** auto-loaded into model context (see architecture principle §2 item 3: do not replay raw trajectories into context).

### 5.4 The curation gate

The reliability core. Subagents never write to project memory directly.

- Subagent returns `proposed_memory[]` entries (Section 7).
- Orchestrator evaluates each: is it an *observation* or a *durable fact*? Is there evidence? Has it been seen before?
- Only promoted entries are written to `project_memory.json` / `subagent_lore/`.
- Every promotion is recorded in the episodic log.
- Promotion threshold for "fact" status: corroborated more than once, or explicitly high-confidence with evidence.

### 5.5 Operator entrypoints (above the orchestrator)

These are not subagents; they wire config, GitHub, git, and the orchestrator for operators.

| Module | Role |
|--------|------|
| `build_sdlc_runtime` | Load config, resolve target checkout, build GitHub + OpenAI clients, subagent registry, `Orchestrator` (+ optional `OrchestratorHooks`, `worktree_root`). |
| `run_sdlc_agent` | One ticket: `backlog` (stop at DEVELOPMENT), `full` (ticket FSM to completion), or `full` + `issue_number` (issue-driven worktree, commit/push, PR hooks). |
| `run_sdlc_daemon` | Loop: dequeue lowest open issue with lifecycle status in queue (default **Backlog**), run issue-driven `full` until empty or `--max-issues`. |
| `sdlc-agent` CLI | Parses flags; prints `SDLCRunResult` or `DaemonSummary`. |

**CLI modes:** `backlog` | `full` | `daemon`. Issue-driven hooks (commit, push, `create_pull_request`) apply only when `issue_number` is set on the run (directly or via daemon).

**GitHub lifecycle labels:** one `status:<slug>` label per issue (e.g. `status:in-development`); `update_project_status` replaces the status label via MCP `issue_write`.

**Deferrals:** no wait for GitHub Actions CI before close/dequeue; no auto-install of target `.github/workflows/`; no automated promotion branch creation or merge to `release`/`main`.

---

## 6. The Task Assignment Contract (Orchestrator → Subagent)

The assignment is **stateful by injection**. The orchestrator decides what slice of memory is relevant and hands it over.

```json
{
  "task_id": "string",
  "ticket_id": "string",
  "subagent": "backlog_analyzer | developer | pr_reviewer",
  "task": "human-readable task description",
  "inputs": { "...task-specific...; orchestrator may inline prior-phase artifact bodies here" },
  "injected_context": {
    "project_facts": ["repo uses pytest", "CI is GitHub Actions"],
    "subagent_lore": ["auth module flagged fragile in 3 past reviews"],
    "relevant_artifacts": ["artifacts/TICKET-12/requirement_analysis.json"]
  },
  "constraints": {
    "allowed_tools": ["sandbox", "filesystem:read"],
    "permissions": { "filesystem": "read-only", "git": "none", "github": "issues" }
  },
  "expected_artifact_schema": { "...JSON schema the return must satisfy..." }
}
```

**Reference wiring:** The orchestrator merges `TicketState.ticket_inputs` into `inputs` for every dispatch. Common keys:

| Key | Purpose |
|-----|---------|
| `specs_path` | Backlog Analyzer reads specs via GitHub MCP |
| `github_issue_number`, `github_project_item_id` | Lifecycle sync (`ISSUE_<n>`) |
| `skip_requirements_analysis` | Issue-driven intake jumps to `DEVELOPMENT` |
| `git_work_branch` | Feature branch name in issue worktree |
| `base_ref`, `head_ref` | PR Reviewer diff (`head_ref` often `HEAD` in worktree) |
| `github_pr_number`, `github_pr_url` | Set after review-gate PR hook |
| `release_to_main_accepted` | Close issue on `DONE` when true |

To keep subagents least-privileged (no read access to `.deepagent/artifacts/`), the orchestrator **inlines** prior artifact bodies: `inputs["requirement_analysis"]` for Developer; `inputs["implementation_summary"]` for PR Reviewer. For issue-driven runs, requirements may be seeded from the GitHub issue body (`issue_workflow.synthetic_requirements_artifact`) before intake. Paths still appear in `injected_context.relevant_artifacts` for audit.

Optional future field: `"skills": ["skill-name", ...]` — if added to the contract, subagents would resolve these via the skill loader in addition to or instead of static per-role defaults.

---

## 7. The Artifact Return Contract (Subagent → Orchestrator)

Task in, **verified** artifact out. The subagent self-verifies before returning — the orchestrator should not have to second-guess raw output.

```json
{
  "task_id": "string",
  "status": "completed | failed | needs_human",
  "artifact": { "...matches expected_artifact_schema..." },
  "verification": {
    "self_checks": [
      { "check": "all acceptance criteria addressed", "passed": true }
    ],
    "passed": true,
    "notes": "string"
  },
  "proposed_memory": [
    {
      "scope": "project_fact | subagent_lore",
      "claim": "the auth module has no integration tests",
      "evidence": "grepped tests/, found only unit tests for auth",
      "confidence": "high | medium | low"
    }
  ]
}
```

---

## 8. Tool & Permission Topology

Enforce least privilege at the subagent boundary — this is the security story.

| Capability | Orchestrator | Backlog Analyzer | Developer | PR Reviewer | Runner (issue-driven) |
|---|---|---|---|---|---|
| `.deepagent/` write | ✅ (sole writer) | ❌ | ❌ | ❌ | ❌ |
| GitHub Issues | ✅ lifecycle sync | ✅ specs + create issues | — | — | ✅ get issue, status, `create_pull_request` |
| Local git | — | ❌ | via sandbox cwd | ✅ read diff | ✅ worktree, commit, push |
| Filesystem (target) | ❌ | ❌ | ✅ sandbox / worktree | ✅ read via git | sets up worktree |
| Sandbox tests | ❌ | ❌ | ✅ | ❌ | — |
| Spawn subagents | ✅ | ❌ | ❌ | ❌ | invokes `run_sdlc_agent` only |

MCP servers are attached to specific agents, not globally available.

---

## 9. Tech Stack — Recommended vs Reference Implementation

Swap freely at integration boundaries. Below, **Recommended** is the long-term / production-shaped stack; **Reference (this repo)** is what the `sdlc_agent` package implements today so all spec phases are testable without external services.

| Concern | Recommended | Reference implementation |
|--------|---------------|---------------------------|
| **Language** | Python 3.11+ | Python 3.11+ (`requires-python` in `pyproject.toml`) |
| **Orchestration** | LangGraph (supervisor, subgraphs, optional checkpointing) | **Vanilla Python FSM** — `SDLCPhase`, pure transition helpers, `Orchestrator.advance()` / `run_to_completion()` |
| **LLM** | OpenAI or other provider with structured output | **OpenAI** Chat Completions API; `OpenAIClient.complete()` with optional `response_format` JSON Schema (`strict: true`) for subagents; runtime factories route per-role models from `sdlc-agent.yaml` |
| **Persistence** | Plain files under `.deepagent/` | JSON / JSONL / YAML as in §5.1; `MemoryStores` owns all writes except subagent sandboxes |
| **GitHub lifecycle** | GitHub Issues API or MCP | **`FixtureGitHubProject`** (tests); **`GitHubMCPProjectClient`** (live Issues + **`create_pull_request`**); factory requires MCP tools including `pull_requests` toolset |
| **Git** | Real git MCP (diff, PR lifecycle) | **`LocalGitClient`** — diff, worktree add/remove, commit, push; **`GitMCPStub`** for handshake only |
| **Target checkout** | Clone per run | **`target_clone.resolve_target_workdir`** — managed clone under temp or explicit `--target-repo-root` |
| **Operator** | CLI / CI entry | **`runner.run_sdlc_agent`**, **`daemon.run_sdlc_daemon`**, **`cli.main`** (`backlog` / `full` / `daemon`) |
| **Developer sandbox** | Docker (or similar): mount working tree only | **`LocalSubprocessSandbox`** — root = checkout or issue worktree; default `unittest discover` (project-specific command not yet in YAML) |
| **Skills** | Shared markdown library, named per task | **`SkillLoader`** + per-subagent **`DEFAULT_SKILLS`**; see §10 |

**Optional swaps (unchanged architecture):** Replace `LocalGitClient` with a service-backed git client; replace `GitHubMCPProjectClient` with direct REST/GraphQL; wrap `Orchestrator` in LangGraph; add `DockerSandbox`; add configurable `test_command` in root config; add CI-wait gate before issue close/dequeue.

---

## 10. Skills System

Skills are **shared infrastructure**, not bolted onto one agent. A skill is a reusable unit of know-how: named markdown (and optionally helper code in future) that shapes *how* a subagent works without encoding project-specific facts.

- **Location:** `skills/` at the **system** repository root (not inside a target project's `.deepagent/`).
- **Format:** One file per skill — `skills/<kebab-name>.md`. The reference library includes:
  - `requirement-ambiguity-checklist.md` (Backlog Analyzer)
  - `tdd-discipline.md` (Developer)
  - `pr-review-rubric.md` (PR Reviewer)
- **Loading:** **`SkillLoader`** resolves names to file contents (validated names, in-process cache). **`assemble_system_prompt`** appends a `--- LOADED SKILLS ---` section to the subagent base system prompt when a loader is wired in.
- **Resolution in reference code:** **Static per role** — each subagent class exposes `DEFAULT_SKILLS: tuple[str, ...]` matching the files above. The orchestrator/demo passes a shared `SkillLoader` into subagent constructors. Future: add `skills: []` to `TaskAssignment` (§6) for per-task overrides without changing skill file format.
- **Versioning / scope:** Treat skills as repo-versioned, project-agnostic doctrine. Durable, ticket-specific claims live in `project_memory.json` / `subagent_lore/` after curation, not in `skills/`.

---

## 11. Build Phases

Each phase is independently testable. Do not start a phase before the prior one's test passes.

**Reference repo status:** All phases below are **implemented** in `tests/phase0` … `tests/phase5` with deterministic tests plus opt-in live OpenAI and GitHub MCP smoke tests. `scripts/demo.py` exercises a non-trivial fixture ticket end-to-end with a deterministic canned LLM.

### Phase 0 — Scaffold
- System repo structure, `config.yaml` schema, `.deepagent/` initializer.
- OpenAI client wrapper and role-model routing; local lifecycle client setup for GitHub Issues + git (stubs + handshake).
- **Test:** point at a repo, `.deepagent/` is created with empty stores; MCP connections handshake.

### Phase 1 — Orchestrator core
- SDLC state machine with all states, gates, transitions (Section 4).
- Memory store read/write layer (the three stores, Section 5).
- Task dispatch interface with **mocked subagents** returning canned artifacts.
- **Test:** a ticket walks INTAKE → DONE against mocked subagents; state persists and resumes mid-lifecycle.

### Phase 2 — First two subagents (the bookends)
- **Backlog Analyzer** and **PR Reviewer** — GitHub issue fixture + local `git`; structured LLM outputs and self-verification.
- Real task assignment contract (Section 6) and artifact return contract (Section 7).
- **Test:** requirement analysis from `specs.md` into GitHub Issues; structured review against a real local git repo (mocked LLM by default).

### Phase 3 — Developer + sandbox
- **Reference:** subprocess sandbox with path containment (Docker remains a Protocol-compatible swap).
- Developer implements against a requirement analysis **test-first**: TDD loop (failing test → code → green → iterate) inside the subagent.
- **Test:** full INTAKE → DONE with three real subagent implementations (mocked LLM); implementation artifact lists impl + test files and self-checks tie claims to sandbox test exit code.

### Phase 4 — Memory curation + gates
- Curation gate: `proposed_memory` → orchestrator evaluation → promotion (Section 5.3).
- Episodic audit log writes on transitions, dispatches, gate decisions, promotions/rejections, HITL.
- Human-in-the-loop gates at REQUIREMENTS_GATE and REVIEW_GATE (`GateApprover` protocol).
- **Test:** cross-session injection of promoted facts; empty-evidence observations not promoted; corroboration path for MEDIUM/LOW confidence.

### Phase 5 — Skills + polish
- Skill library (`skills/*.md`) + `SkillLoader` + per-role `DEFAULT_SKILLS`; prepended to subagent system prompts.
- **`TrajectoryRecorder`:** `.deepagent/trajectories/<session-id>/<task-id>.jsonl` — full prompt + response per LLM call when recorder is wired; orchestrator **`session_id`** on episodic events.
- **Live adapters:** root-config runtime assembly, GitHub MCP stdio/Docker client (Issues + PRs), fixture-vs-MCP lifecycle factory, `sdlc-agent` CLI (`backlog` / `full` / `daemon`), and opt-in live smoke tests.
- **Issue-driven delivery:** `runner` + `issue_workflow` (adopt issue, synthetic requirements, worktree), `OrchestratorHooks` (commit/push after development gate, `create_pull_request` after review gate), `LocalGitClient` worktree helpers.
- **Multi-issue supervisor:** `daemon.py` dequeues Backlog (configurable statuses), runs issue-driven `full` in a loop.
- **Target workspace:** `target_clone.py` — managed clone outside control repo; `SDLC_TARGET_CLONE_PARENT`.
- End-to-end demo (`scripts/demo.py`); architecture (`ARCHITECTURE.md`); diagrams (`system-design.md`).
- **Test:** skill resolution; trajectories; issue/PR/git/daemon/target-clone unit tests in `tests/phase0`–`phase5`.

---

## 12. Scoping for the Accenture Deliverable (historical minimum)

The original assessment framing asked candidates to **architect for three subagents** but **implement two** bookends plus a strong curation path (see wording preserved in assessments that cite this doc).

**This repository goes further:** Phases 0–5 are **fully implemented**, including the **Developer** (merged TDD loop + sandbox), **skills**, **trajectory archiving**, **issue-driven worktree/PR path**, **multi-issue daemon**, **managed target clone**, **`ARCHITECTURE.md`**, **`system-design.md`**, and **`scripts/demo.py`**. Treat §12 as the *minimum credible slice* for a time-boxed submission; treat the codebase as the *full* spec realization for learning and extension.

Regardless of scope, reviewers expect explicit tradeoff discussion — especially **merging code and test generation in one Developer** vs splitting an adversarial Tester (see **`ARCHITECTURE.md` §4**), and **control plane vs target checkout** vs nesting the target inside the system repo (see **`ARCHITECTURE.md` §8–10**).

---

## 13. The Defensible Spine (for the writeup)

> Disk is memory, context is the working set. There is exactly one orchestrator because exactly one component must own the SDLC state machine *and* the memory curation gate. Subagents are stateless workers with least-privilege tool scopes; their task assignments are made stateful by injection. Recursion depth is fixed at one. Persistent project knowledge compounds across sessions as curated artifacts on disk — never as replayed trajectories — and never rots, because every durable write passes an orchestrator-owned promotion gate that distinguishes observation from fact.
