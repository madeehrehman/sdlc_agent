# System Design — SDLC Deep Agent v2

Visual companion to `ARCHITECTURE.md` and the design spec at `docs/superpowers/specs/2026-05-26-deep-agent-orchestrator-design.md`. All diagrams use [Mermaid](https://mermaid.js.org/).

---

## 1. System context (C4-style)

Two repositories matter: the **control plane** (`sdlc_agent` package + `sdlc-agent.yaml`) and the **target project** (checkout where code and `.deepagent/` live).

```mermaid
flowchart TB
  subgraph Actors
    OP[Operator — runs sdlc-agent CLI]
    HM[Human approver — HITL at release]
  end

  subgraph External
    OAI[OpenAI gpt-4o]
    GHMCP[GitHub MCP server — Docker stdio]
    GH[GitHub repo — Issues and PRs]
    GIT[Git — local clone]
  end

  subgraph ControlPlane["Control plane — sdlc_agent repo"]
    CFG[sdlc-agent.yaml + .env]
    CLI[sdlc-agent CLI]
    RT[build_runtime]
    PA[Primary Agent — StateGraph]
    MEM[project_memory.md — living memory]
  end

  subgraph SubAgents["Sub-agents — compiled subgraphs"]
    DEV[Developer/Tester — ReAct]
    REV[PR Reviewer — ReAct]
    REL[Release Engineer — ReAct + HITL]
  end

  subgraph Docker["Docker containers — isolated execution"]
    DDEV[sdlc-developer — full toolchain]
    DREV[sdlc-reviewer — read-only]
    DREL[sdlc-release — Docker-in-Docker]
  end

  subgraph TargetCheckout["Target checkout — disk"]
    SRC[source tree — code and tests]
    DA[.deepagent/memory.md]
    BR[feature branches]
  end

  OP --> CLI --> RT --> PA
  CFG --> RT
  PA --> MEM
  PA --> GHMCP --> GH
  PA --> DEV
  PA --> REV
  PA --> REL
  DEV --> DDEV --> SRC
  REV --> DREV --> SRC
  REL --> DREL --> BR
  HM -. HITL approve/reject .-> REL
  DEV --> OAI
  REV --> OAI
  REL --> OAI
  PA --> OAI
  MEM --> DA
```

---

## 2. Primary agent — StateGraph nodes

```mermaid
stateDiagram-v2
  [*] --> intake
  intake --> create_issues : backlog mode
  intake --> assign_development : single-issue mode

  create_issues --> assign_development

  assign_development --> assign_review : dev_result.success
  assign_development --> handle_rejection : retry after rejection
  assign_development --> next_ticket : max retries exceeded → Blocked

  assign_review --> assign_release : review approved
  assign_review --> handle_rejection : review rejected

  handle_rejection --> assign_development : re-assign with feedback

  assign_release --> close_issue : deployed
  assign_release --> handle_rejection : deploy rejected

  close_issue --> next_ticket
  next_ticket --> assign_development : backlog has more issues
  next_ticket --> [*] : backlog empty
```

---

## 3. Developer/Tester sub-agent — TDD loop

```mermaid
flowchart TD
  START([Primary invokes Developer subgraph])
  SE[setup_environment\ncheckout repo, install deps, verify clean]
  PI[plan_implementation\nread issue + arch context, plan files + contracts]
  WT[write_tests_first\nunit + integration tests — RED phase]
  IM[implement\nwrite code, run tests, iterate until GREEN\nfix lint + type errors]
  CR[commit_and_report\ngit commit feature branch, push,\nreturn branch + test results to Primary]
  END([DevResult → Primary])

  START --> SE --> PI --> WT --> IM
  IM -->|tests GREEN| CR --> END
  IM -->|tests still RED| IM
```

---

## 4. PR Reviewer sub-agent — review loop

```mermaid
flowchart TD
  START([Primary invokes Reviewer subgraph])
  LC[load_context\ncheckout feature branch\nread issue + acceptance criteria + arch notes]
  RD[read_diff\nmap changed files to acceptance criteria\nidentify untested paths]
  VT[verify_tests\ncoverage report — unit tests for all new code\nintegration tests cover full acceptance criteria flow]
  VS[verify_standards\ncoding standards, naming, security anti-patterns\nno hardcoded secrets]
  AOR{all gates pass?}
  APP[approve PR\ngithub_approve_pr + summary comment]
  REJ[reject with specific actionable feedback\nper failing criterion\ngithub_request_changes]
  END([ReviewResult → Primary])

  START --> LC --> RD --> VT --> VS --> AOR
  AOR -->|yes| APP --> END
  AOR -->|no| REJ --> END
```

---

## 5. Release Engineer sub-agent — deploy loop with HITL

```mermaid
flowchart TD
  START([Primary invokes Release subgraph])
  PR[prepare_release\ncheckout approved branch\nmerge into main / release branch\ntag release]
  BV[build_and_verify\nbuild production Docker image\nrun smoke tests inside container\nverify it starts clean]
  PH[present_to_human\nrelease summary: diff stats, test results,\nimage size, smoke test output]
  INT[[interrupt — HITL checkpoint\nexecution pauses, human reviews]]
  HUM{human decision}
  DEP[deploy\npush image, deploy container, confirm running]
  ROL[rollback\nreport rejection to Primary\nissue stays open]
  END([ReleaseResult → Primary])

  START --> PR --> BV --> PH --> INT --> HUM
  HUM -->|approved| DEP --> END
  HUM -->|rejected| ROL --> END
```

---

## 6. Full issue lifecycle — sequence

```mermaid
sequenceDiagram
  autonumber
  participant OP as Operator
  participant PA as Primary Agent
  participant GH as GitHub
  participant DEV as Developer/Tester
  participant REV as PR Reviewer
  participant REL as Release Engineer
  participant HM as Human

  OP->>PA: sdlc-agent run --issue 5
  PA->>GH: update label → In Progress + add comment
  PA->>DEV: invoke subgraph (issue + arch context + memory)
  DEV-->>PA: DevResult {branch, test_results, success}
  PA->>GH: update label → Ready for Review + assign branch
  PA->>REV: invoke subgraph (issue + branch + acceptance criteria)
  REV-->>PA: ReviewResult {approved, feedback}
  PA->>GH: update label → Approved + PR review comment
  PA->>REL: invoke subgraph (branch + issue summary + deploy config)
  REL->>HM: interrupt — release summary for approval
  HM-->>REL: approve
  REL-->>PA: ReleaseResult {deployed, deployment_url}
  PA->>GH: close issue + deployment summary comment
  PA->>PA: update living memory (lessons learned, component map)
```

---

## 7. Primary living memory — structure and lifecycle

```mermaid
flowchart LR
  subgraph Write["Written by Primary after each closed ticket"]
    AD[architecture_decisions\nwhy key tech choices were made]
    CS[coding_standards\nlanguage, patterns, naming, test requirements]
    LL[lessons_learned\nwhat went right/wrong per ticket]
    CM[component_map\nfiles/modules and their domain ownership]
    OR[open_risks\nknown debt or deferred decisions]
  end

  subgraph Inject["Injected into every sub-agent assignment"]
    DEV2[Developer/Tester context]
    REV2[PR Reviewer context]
    REL2[Release Engineer context]
  end

  MDF[.deepagent/memory.md\non target checkout] --> Inject
  Write --> MDF
```

---

## 8. CLI run modes

```mermaid
flowchart LR
  CLI[sdlc-agent]

  CLI --> B[backlog\nread specs.md\ncreate GitHub issues\nlabel Backlog]
  CLI --> R[run\nfull SDLC for one issue\ndev → review → release]
  CLI --> D[daemon\nloop: pick next Backlog issue\nrun → repeat until empty]

  R --> OPT{--issue N?}
  OPT -->|yes| R1[adopt issue N\nskip issue creation]
  OPT -->|no| R2[auto-pick next Backlog issue]

  D --> R
```

---

## 9. Docker execution model

```mermaid
flowchart TB
  subgraph Host["Host process — Python"]
    PA2[Primary Agent]
    DEV3[Developer/Tester subgraph]
    REV3[PR Reviewer subgraph]
    REL3[Release Engineer subgraph]
    DS[DockerSandbox\n docker run --rm -v]
  end

  subgraph Containers["Docker containers — ephemeral"]
    C1[sdlc-developer\nfull write access\ntest runner, lint, git]
    C2[sdlc-reviewer\nread-only mount\ndiff + coverage only]
    C3[sdlc-release\nDocker-in-Docker\ndeploy tools]
  end

  subgraph LocalFallback["Local fallback — use_docker=False"]
    LS[LocalSubprocessSandbox]
  end

  PA2 --> DEV3 --> DS
  PA2 --> REV3 --> DS
  PA2 --> REL3 --> DS
  DS -->|use_docker=True| C1
  DS -->|use_docker=True| C2
  DS -->|use_docker=True| C3
  DS -->|use_docker=False| LS
```

---

## 10. Least privilege per agent

```mermaid
flowchart TB
  subgraph Primary["Primary Agent — no codebase access"]
    P1[read_spec_file]
    P2[create / update / close GitHub issues]
    P3[add_issue_comment]
    P4[list_open_issues]
    P5[read / write project_memory.md]
  end

  subgraph Dev["Developer/Tester — full read/write in container"]
    D1[read_file / write_file]
    D2[run_tests — Docker subprocess]
    D3[git_branch / git_commit / git_push]
    D4[install_dependencies]
    D5[run_shell_command — container-scoped]
  end

  subgraph Rev["PR Reviewer — read-only in container"]
    R1[read_pr_diff]
    R2[read_test_report / read_coverage]
    R3[read_file — no write]
    R4[github_approve_pr / github_request_changes]
  end

  subgraph Rel["Release Engineer — deploy tools only"]
    RL1[git_merge / git_tag]
    RL2[docker_build / docker_deploy]
    RL3[run_smoke_tests]
    RL4[generate_release_summary]
    RL5[interrupt — HITL checkpoint]
  end
```

---

## Related reading

| Document | Purpose |
|---|---|
| `ARCHITECTURE.md` | Decision rationale and trade-offs |
| `README.md` | Setup, CLI, quick start |
| `docs/superpowers/specs/2026-05-26-deep-agent-orchestrator-design.md` | Full design specification |
