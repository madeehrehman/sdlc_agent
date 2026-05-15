# System-level design diagrams

This document is a **visual companion** to `sdlc-deep-agent-spec.md` and `ARCHITECTURE.md`. Diagrams use [Mermaid](https://mermaid.js.org/); they render in GitHub, GitLab, many IDEs, and Cursor preview.

---

## 1. System context (C4-style)

Two repositories matter: the **control plane** (`sdlc_agent` package + `sdlc-agent.yaml`) and the **target project** (checkout where code and `.deepagent/` live).

```mermaid
flowchart TB
  subgraph Actors
    OP[Operator runs sdlc-agent CLI]
    HM[Human approver optional HITL]
  end

  subgraph External["External systems"]
    OAI[OpenAI Chat Completions API]
    GHMCP[GitHub MCP server Docker stdio]
    GH[GitHub repo Issues and PRs]
    GIT[Git local clone and worktrees]
  end

  subgraph Control["Control plane sdlc_agent repo"]
    CFG[sdlc-agent.yaml + .env secrets]
    CLI[sdlc-agent CLI]
    RUN[runner.py]
    DMN[daemon.py]
    RT[runtime.py build_sdlc_runtime]
  end

  subgraph Process["Orchestration in-process"]
    ORCH["Orchestrator dispatcher + FSM"]
    SUP["OrchestratorSupervisor LLM optional"]
    CG["CurationGate"]
    GA["GateApprover"]
    HOOKS["OrchestratorHooks commit push PR"]
    LOAD["SkillLoader skills/*.md"]

    subgraph Subagents["Subagents depth 1"]
      BA[BacklogAnalyzer]
      DV[DeveloperTester]
      PR[PRReviewer]
    end
    REG["Subagent registry"]
    ORCH --> REG
    ORCH -. plan + gate advice .-> SUP
    SUP --> OAI
    ORCH --> CG
    ORCH --> GA
    ORCH --> HOOKS
    REG --> BA
    REG --> DV
    REG --> PR
    LOAD -. system prompt .-> BA
    LOAD -. system prompt .-> DV
    LOAD -. system prompt .-> PR
    LOAD -. orchestrator-supervisor.md .-> SUP
  end

  subgraph TargetCheckout["Target checkout disk"]
    SRC[source tree specs.md code tests]
    WT[".worktrees/ticket-id issue branch"]
    DA[".deepagent state artifacts memory trajectories"]
  end

  OP --> CLI
  CLI --> RUN
  CLI --> DMN
  RUN --> RT
  DMN --> RUN
  RUN --> ORCH
  RT --> ORCH
  CFG --> RUN

  BA --> OAI
  BA --> GHMCP
  DV --> OAI
  PR --> OAI
  DV --> SBX["LocalSubprocessSandbox"]
  PR --> LGC["LocalGitClient"]
  RUN --> GHMCP
  RUN --> LGC
  HOOKS --> GHMCP
  HOOKS --> LGC

  GHMCP --> GH
  LGC --> GIT
  GIT --> TargetCheckout
  SBX --> WT
  LGC --> WT
  ORCH <--> DA
  CG <--> DA
  BA -. assignment only .-> DA
  DV -. assignment only .-> DA
  PR -. assignment only .-> DA
  HM -. GateApprover .-> GA
```

**Legend:** The operator runs the CLI from the control repo. The target checkout is either `--target-repo-root` or an auto-managed clone under `%TEMP%/sdlc-agent-targets/` (see `target_clone.py`). Subagents never read `.deepagent/` directly. When `orchestrator.use_llm_supervisor` is true, `OrchestratorSupervisor` plans delegation and advises gates; the FSM still applies safety clamps (see §7.1).

---

## 2. Target checkout resolution

```mermaid
flowchart TD
  START[sdlc-agent invoked]
  EXPLICIT{--target-repo-root set?}
  USE[Use explicit path mkdir if needed]
  MCP{lifecycle_client mcp?}
  CLONE["git clone --depth 1 into SDLC_TARGET_CLONE_PARENT or temp/sdlc-agent-targets/owner_repo"]
  MK[Create directory only fixture mode]
  RUN[run_sdlc_agent / daemon / build_sdlc_runtime]

  START --> EXPLICIT
  EXPLICIT -->|yes| USE
  EXPLICIT -->|no| MCP
  MCP -->|yes| CLONE
  MCP -->|no| MK
  USE --> RUN
  CLONE --> RUN
  MK --> RUN
```

`.deepagent/` is always written under this checkout root. Issue worktrees live under `<checkout>/.worktrees/<ticket-id>/` unless `--worktrees-dir` overrides the parent.

---

## 3. CLI run modes

```mermaid
flowchart LR
  CLI[sdlc-agent]
  B[mode backlog]
  F[mode full]
  D[mode daemon]

  CLI --> B
  CLI --> F
  CLI --> D

  B --> R1[run_sdlc_agent stop at DEVELOPMENT]
  F --> Q{--issue-number?}
  Q -->|yes| R2[issue-driven full worktree commit PR]
  Q -->|no| R3[ticket full requirements to DONE]
  D --> LOOP[dequeue Backlog issues FIFO by number]
  LOOP --> R2
```

| Mode | Stops / behavior |
|------|------------------|
| `backlog` | After first issue adopted; phase `DEVELOPMENT` |
| `full` + ticket | Full FSM on ticket; no auto commit/PR unless hooks added elsewhere |
| `full` + `--issue-number` | Skip requirements phase; worktree; commit/push; `create_pull_request` |
| `daemon` | Repeat issue-driven `full` until queue empty or `--max-issues` |

**Config (optional):** `orchestrator.use_llm_supervisor: true` in `sdlc-agent.yaml` enables the supervisor LLM (`model.roles.orchestrator`). Default is `false` (rules-only gates).

---

## 4. Issue-driven sequence (worktree → PR)

```mermaid
sequenceDiagram
  autonumber
  participant CLI as sdlc-agent
  participant R as runner
  participant GH as GitHubProjectClient
  participant G as LocalGitClient
  participant O as Orchestrator
  participant DV as DeveloperTester
  participant PR as PRReviewer

  CLI->>R: mode full issue_number N
  R->>GH: get_issue update status In Development
  R->>G: validate base_ref add_worktree branch
  R->>O: seed requirement_analysis artifact intake skip to DEVELOPMENT
  O->>DV: run TDD in worktree sandbox
  DV-->>O: ArtifactReturn
  O->>O: DEVELOPMENT_GATE proceed
  R->>G: commit_all push_branch hook
  O->>PR: run diff vs base_ref
  PR-->>O: ArtifactReturn
  O->>O: REVIEW_GATE proceed
  R->>GH: create_pull_request hook
  R->>G: remove_worktree
```

Hooks run only on **`PROCEED`** at the development and review gates when `issue_number` was set at intake.

---

## 5. Internal components and data ownership

```mermaid
flowchart LR
  subgraph Operator
    RUN2[runner.py]
    DMN2[daemon.py]
    TC[target_clone.py]
  end

  subgraph Contracts
    TA[TaskAssignment]
    AR[ArtifactReturn]
  end

  subgraph Orchestrator_pkg["orchestrator/"]
    SM[state_machine.py]
    DP[dispatcher.py + OrchestratorHooks]
    SUP2[supervisor.py + prompts.py]
    CU[curation.py]
    HI[hitl.py]
  end

  subgraph Memory_pkg["memory/"]
    PTH[paths.py]
    STO[stores.py]
    TRK[trajectories.py]
  end

  subgraph Integration
    LLM[llm/]
    GHF[github.py fixture]
    GHM[github_mcp.py]
    FAC[mcp/factory.py]
    GIT2[git.py LocalGitClient]
    SBX2[sandbox/]
  end

  subgraph Workers["subagents/"]
    BA2[backlog_analyzer]
    DV2[developer]
    PR2[pr_reviewer]
  end

  RUN2 --> TC
  DMN2 --> RUN2
  RUN2 --> DP
  RUN2 --> GHF
  RUN2 --> GHM
  FAC --> GHM
  DP --> SM
  DP -. optional .-> SUP2
  SUP2 --> LLM
  DP --> CU
  DP --> HI
  DP --> STO
  BA2 --> TA
  DV2 --> TA
  PR2 --> TA
  STO --> PTH
  TRK --> PTH
```

**Import note:** `Orchestrator` is imported from `sdlc_agent.orchestrator.dispatcher` (not `orchestrator.__init__`) to avoid a circular import with `memory.stores`.

---

## 6. Memory layout (target checkout)

```mermaid
flowchart TB
  subgraph Working["1 Working state per ticket"]
    SF["state/ticket_id.json TicketState + ticket_inputs"]
  end

  subgraph Curated["2 Curated cross-session"]
    PJ[project_memory.json]
    LO[subagent_lore/*.json]
  end

  subgraph Audit["3 Episodic append-only"]
    EP[episodic/log.jsonl]
  end

  subgraph Art["Per-ticket artifacts"]
    A1[requirement_analysis.json]
    A2[implementation_summary.json]
    A3[review.json]
  end

  subgraph Cold["Cold storage"]
    TJ[trajectories/session/task.jsonl]
  end

  subgraph GitWork["Issue branch optional"]
    WT2[".worktrees/ticket-id/"]
  end

  ORC[Orchestrator] --> Working
  ORC --> Curated
  ORC --> Audit
  ORC --> Art
  RUNR[runner issue path] --> WT2
  TR[TrajectoryRecorder] --> Cold
```

---

## 7. SDLC state machine (phases)

Standard path. Issue-driven intake can skip directly to `DEVELOPMENT` when `skip_requirements_analysis` is on `ticket_inputs`.

```mermaid
stateDiagram-v2
  [*] --> INTAKE
  INTAKE --> REQUIREMENTS_ANALYSIS : default intake
  INTAKE --> DEVELOPMENT : issue-driven intake skip_requirements_analysis

  REQUIREMENTS_ANALYSIS --> REQUIREMENTS_GATE : BacklogAnalyzer
  REQUIREMENTS_GATE --> DEVELOPMENT : proceed
  REQUIREMENTS_GATE --> REQUIREMENTS_ANALYSIS : retry
  REQUIREMENTS_GATE --> BLOCKED : blocked
  REQUIREMENTS_GATE --> NEEDS_HUMAN : needs_human

  DEVELOPMENT --> DEVELOPMENT_GATE : DeveloperTester
  DEVELOPMENT_GATE --> PR_REVIEW : proceed
  DEVELOPMENT_GATE --> DEVELOPMENT : retry
  DEVELOPMENT_GATE --> BLOCKED : blocked
  DEVELOPMENT_GATE --> NEEDS_HUMAN : needs_human

  PR_REVIEW --> REVIEW_GATE : PRReviewer
  REVIEW_GATE --> DONE : proceed
  REVIEW_GATE --> PR_REVIEW : retry
  REVIEW_GATE --> BLOCKED : blocked
  REVIEW_GATE --> NEEDS_HUMAN : needs_human

  DONE --> [*]
  BLOCKED --> [*]
  NEEDS_HUMAN --> [*]
```

Gate decisions: `proceed`, `retry`, `blocked`, `needs_human` (`state_machine.py`). With the supervisor enabled, the LLM *recommends* a decision; `evaluate_default_gate` plus verification clamps still bound what the FSM can accept.

---

## 7.1 Supervisor LLM (hybrid orchestration)

When `orchestrator.use_llm_supervisor` is true, each work phase and gate consults `OrchestratorSupervisor` before the subagent runs and before the gate transition is recorded.

```mermaid
flowchart TD
  WORK[Work phase e.g. DEVELOPMENT]
  PLAN[supervisor.plan_delegation if enabled]
  ASSIGN[TaskAssignment + supervisor instructions]
  SUB[subagent.run]
  GATE[Gate phase]
  HITL{HITL configured?}
  HUM[GateApprover human only]
  DEF[evaluate_default_gate]
  ADV[supervisor.advise_gate if enabled]
  CLAMP[Clamp: cannot proceed if default blocks or verify failed]
  TRANS[FSM record_transition]

  WORK --> PLAN --> ASSIGN --> SUB --> GATE
  GATE --> HITL
  HITL -->|yes| HUM --> TRANS
  HITL -->|no| DEF --> ADV --> CLAMP --> TRANS
```

| Step | Owner | Notes |
|------|--------|--------|
| Phase transitions | FSM (`state_machine.py`) | Single source of truth for `current_phase` |
| Delegation text | Supervisor LLM | Scoped to ticket inputs, prior artifacts, retry guidance |
| Gate decision | Supervisor + rules | Cannot `proceed` if `verification.passed` is false or default would block |
| HITL | `GateApprover` | Supervisor skipped; human decides |
| Protocol | `skills/orchestrator-supervisor.md` | Loaded with `orchestrator/prompts.py` system prompt |

---

## 8. Daemon dequeue loop

```mermaid
flowchart TD
  START[run_sdlc_daemon]
  LIST[list_project_items via GitHub client]
  PICK[pick lowest issue_number with status in dequeue set default Backlog]
  EMPTY{any candidate?}
  CAP{started less than max_issues?}
  RUN[run_sdlc_agent full issue_number]
  INC[started += 1]
  ERR{continue_on_error?}
  STOP1[stopped_reason queue_empty]
  STOP2[stopped_reason max_issues]

  START --> LIST --> PICK --> EMPTY
  EMPTY -->|no| STOP1
  EMPTY -->|yes| CAP
  CAP -->|no| STOP2
  CAP -->|yes| RUN --> INC
  RUN -->|exception| ERR
  ERR -->|raise| X[abort]
  ERR -->|log continue| LIST
  INC --> LIST
```

Successful runs move issues out of **Backlog** via lifecycle label updates, so they are not picked again.

---

## 9. Least privilege: what each role touches

```mermaid
flowchart TB
  subgraph Orchestrator_only["Orchestrator only"]
    W[write .deepagent all stores]
    R[read stores build assignments]
  end

  subgraph BA["BacklogAnalyzer"]
    B1[read specs via GitHub MCP or fixture]
    B2[create/list issues]
    B3[LLM only no target .deepagent read]
  end

  subgraph DV["DeveloperTester"]
    D1[sandbox root or issue worktree read write]
    D2[LLM]
    D3[run tests subprocess in sandbox cwd]
  end

  subgraph PRr["PRReviewer"]
    P1[LocalGitClient diff at sandbox or worktree root]
    P2[LLM]
  end

  subgraph Runner_only["runner issue-driven hooks"]
    H1[commit push worktree]
    H2[create_pull_request MCP]
  end
```

---

## 10. Promotion and CI (reference only)

The **sdlc_agent** repo may ship `.github/workflows/sdlc-promotion.yml` as a **template** for PR gates (`develop` → `release` → `main`). The agent does **not** install that workflow into the target repo automatically. When a PR exists on the target, GitHub Actions run according to **that** repo's workflows; the orchestrator does not wait for CI before dequeuing the next issue.

```mermaid
flowchart LR
  PR[PR merged or open on target]
  GHA[Target repo GitHub Actions]
  AG[sdlc_agent process]
  PR --> GHA
  GHA -. no feedback loop yet .-> AG
```

---

## Related reading

| Document | Use when |
|----------|----------|
| `sdlc-deep-agent-spec.md` | Full contracts, gates, build phases |
| `ARCHITECTURE.md` | Tradeoffs, control vs target, issue-driven path, deferrals |
| `README.md` | Setup, CLI examples, env vars |
