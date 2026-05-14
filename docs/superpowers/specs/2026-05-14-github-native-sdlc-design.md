# GitHub-Native SDLC Agent Design

## Goal

The SDLC Deep Agent should operate from a GitHub-native target project. A new
target repository can begin with only `specs.md`; the agent analyzes that living
specification, creates GitHub Issues with full acceptance criteria, tracks those
issues in GitHub Issues, implements and tests work on `develop`, reviews
against acceptance criteria, and promotes through `release` to `main` with
PR-gated GitHub Actions.

GitHub Issues are the backlog and lifecycle system.

## Lifecycle

1. `BacklogAnalyzer` reads `specs.md`, current repository context, and existing
   GitHub Issues.
2. It identifies missing work and creates GitHub Issues with explicit acceptance
   criteria, then labels those issues with lifecycle status.
3. The orchestrator selects an issue, injects the issue and acceptance criteria
   into the DeveloperTester assignment, and moves the Project item through SDLC
   states.
4. DeveloperTester implements code plus unit and integration tests in a TDD
   loop and targets `develop`.
5. PRReviewer reviews the diff against the requirement analysis and acceptance
   criteria, then recommends whether the work is ready for release promotion.
6. GitHub Actions handles PR-gated promotion: feature to `develop`,
   `develop` to `release`, and `release` to `main`. The first implementation
   verifies deployment with a container build/run smoke test inside Actions,
   not an external cloud platform.
7. When `release -> main` is accepted, the orchestrator marks the GitHub Issue
   item done and closes the GitHub Issue.

## Boundaries

- The orchestrator remains the only owner of the SDLC state machine, `.deepagent`
  memory, and lifecycle transitions.
- Subagents remain stateless workers. They receive GitHub/spec context by
  assignment and return structured artifacts.
- The first GitHub adapter is testable and deterministic. Live GitHub API wiring
  can be added behind the same protocol later.
- The first deployment verification is a local container smoke test in GitHub
  Actions. Real cloud deployment is deferred behind a provider interface.

## Verification Strategy

Tests should cover GitHub issue/project client behavior, `specs.md` backlog
analysis, lifecycle status updates, PR reviewer acceptance-criteria context, and
the presence of PR-gated promotion workflow files. The full suite remains
`python -m pytest`, with live external API tests opt-in only.
