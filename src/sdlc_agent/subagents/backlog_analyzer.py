"""Backlog Analyzer subagent for GitHub-native SDLC.

The analyzer reads the target repository's living `specs.md`, compares it with
existing GitHub Project items, asks the LLM for issue drafts with acceptance
criteria, creates those GitHub Issues, and returns a verified requirement
analysis artifact to the orchestrator.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from sdlc_agent.contracts import (
    ArtifactReturn,
    SubagentName,
    TaskAssignment,
    VerificationCheck,
)
from sdlc_agent.llm import OpenAIClient
from sdlc_agent.mcp.github import GitHubIssueDraft, GitHubProjectClient, GitHubSpecDocument
from sdlc_agent.memory.trajectories import TrajectoryRecorder
from sdlc_agent.skills import SkillLoader, assemble_system_prompt
from sdlc_agent.subagents.base import (
    PROPOSED_MEMORY_SCHEMA,
    build_artifact_return,
    call_llm_with_schema,
    parse_proposed_memory,
    render_injected_context,
)


_ISSUE_DRAFT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "body": {"type": "string"},
        "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
        "labels": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "body", "acceptance_criteria", "labels"],
    "additionalProperties": False,
}


_BACKLOG_ANALYZER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "artifact": {
            "type": "object",
            "properties": {
                "source_spec": {"type": "string"},
                "summary": {"type": "string"},
                "repo_gaps": {"type": "array", "items": {"type": "string"}},
                "issue_drafts": {"type": "array", "items": _ISSUE_DRAFT_SCHEMA},
                "blocking_questions": {"type": "array", "items": {"type": "string"}},
                "ready_for_development": {"type": "boolean"},
                "notes": {"type": "string"},
            },
            "required": [
                "source_spec",
                "summary",
                "repo_gaps",
                "issue_drafts",
                "blocking_questions",
                "ready_for_development",
                "notes",
            ],
            "additionalProperties": False,
        },
        "proposed_memory": PROPOSED_MEMORY_SCHEMA,
    },
    "required": ["artifact", "proposed_memory"],
    "additionalProperties": False,
}


_SYSTEM_PROMPT = """\
You are the Backlog Analyzer subagent in a GitHub-native SDLC orchestration
system.

Your job:
  * Read the target repository's `specs.md` living specification.
  * Compare it with existing GitHub Project items and curated project memory.
  * Identify gaps that should become GitHub Issues.
  * Produce issue drafts with full, testable acceptance criteria.
  * Mark `ready_for_development` true only when there are no blocking questions
    and every issue draft has acceptance criteria.
  * Optionally propose durable memory entries with concrete evidence.

Constraints:
  * GitHub Issues/Projects are the lifecycle system. Do not reference external trackers.
  * Respond ONLY in the JSON shape required by the structured-output schema.
"""


@dataclass
class BacklogAnalyzer:
    """Stateless Backlog Analyzer using GitHub Issues/Projects."""

    DEFAULT_SKILLS: ClassVar[tuple[str, ...]] = ("requirement-ambiguity-checklist",)

    llm: OpenAIClient
    github: GitHubProjectClient
    name: SubagentName = SubagentName.BACKLOG_ANALYZER
    skills: SkillLoader | None = None
    recorder: TrajectoryRecorder | None = None

    def run(self, assignment: TaskAssignment) -> ArtifactReturn:
        if assignment.subagent is not SubagentName.BACKLOG_ANALYZER:
            raise ValueError(
                f"BacklogAnalyzer received assignment for {assignment.subagent}"
            )

        specs_path = str(assignment.inputs.get("specs_path") or "specs.md")
        spec = self.github.read_specs(specs_path)
        existing_items = self.github.list_project_items()

        system_prompt = assemble_system_prompt(
            _SYSTEM_PROMPT,
            loader=self.skills,
            skill_names=self.DEFAULT_SKILLS,
        )
        user_prompt = self._build_user_prompt(assignment, spec, existing_items)
        response = call_llm_with_schema(
            self.llm,
            system=system_prompt,
            user=user_prompt,
            schema_name="github_backlog_analyzer_response",
            schema=_BACKLOG_ANALYZER_SCHEMA,
            recorder=self.recorder,
            task_id=assignment.task_id,
            kind="backlog_analyzer.run",
            metadata={"source_spec": spec.path},
        )

        artifact_body = response["artifact"]
        drafts = self._validated_issue_drafts(artifact_body)
        created_issues = self._create_github_issues(drafts) if drafts else []
        artifact_body["created_issues"] = created_issues
        proposals = parse_proposed_memory(response.get("proposed_memory"))
        checks = self._self_check(spec, artifact_body)

        return build_artifact_return(
            task_id=assignment.task_id,
            artifact_body=artifact_body,
            proposed_memory=proposals,
            self_checks=checks,
            notes="github backlog analyzer self-verified",
        )

    @staticmethod
    def _validated_issue_drafts(artifact: dict[str, Any]) -> list[GitHubIssueDraft]:
        issue_drafts = artifact.get("issue_drafts") or []
        parsed = [GitHubIssueDraft.model_validate(draft) for draft in issue_drafts]
        if not parsed or not all(draft.acceptance_criteria for draft in parsed):
            return []
        return parsed

    def _create_github_issues(
        self, drafts: list[GitHubIssueDraft]
    ) -> list[dict[str, Any]]:
        created: list[dict[str, Any]] = []
        for draft in drafts:
            issue = self.github.create_issue(draft)
            item = self.github.add_issue_to_project(issue, status="Backlog")
            created.append(
                {
                    "number": issue.number,
                    "title": issue.title,
                    "url": issue.url,
                    "project_item_id": item.item_id,
                    "status": item.status,
                    "acceptance_criteria": list(issue.acceptance_criteria),
                }
            )
        return created

    @staticmethod
    def _build_user_prompt(
        assignment: TaskAssignment,
        spec: GitHubSpecDocument,
        existing_items: list[Any],
    ) -> str:
        context = render_injected_context(assignment.injected_context)
        items = (
            "\n".join(
                f"  - #{item.issue_number} {item.title} [{item.status}]"
                for item in existing_items
            )
            if existing_items
            else "  (none)"
        )
        return f"""\
{context}

Target repository specification:
  Path: {spec.path}

```markdown
{spec.body}
```

Existing GitHub Project items:
{items}

Analyze the living specification, identify missing work, and draft GitHub Issues
with full acceptance criteria."""

    @staticmethod
    def _self_check(
        spec: GitHubSpecDocument, artifact: dict[str, Any]
    ) -> list[VerificationCheck]:
        issue_drafts = artifact.get("issue_drafts") or []
        created = artifact.get("created_issues") or []
        blocking = artifact.get("blocking_questions") or []
        every_draft_has_ac = all(
            len(draft.get("acceptance_criteria") or []) >= 1 for draft in issue_drafts
        )
        every_created_has_ac = all(
            len(issue.get("acceptance_criteria") or []) >= 1 for issue in created
        )

        return [
            VerificationCheck(
                check="source_spec matches requested specs document",
                passed=artifact.get("source_spec") == spec.path,
            ),
            VerificationCheck(
                check="at least one GitHub issue draft present",
                passed=len(issue_drafts) >= 1,
            ),
            VerificationCheck(
                check="every issue draft has acceptance criteria",
                passed=every_draft_has_ac,
            ),
            VerificationCheck(
                check="created GitHub issues match issue drafts",
                passed=len(created) == len(issue_drafts),
            ),
            VerificationCheck(
                check="every created GitHub issue has acceptance criteria",
                passed=every_created_has_ac,
            ),
            VerificationCheck(
                check="ready_for_development is consistent with blocking questions",
                passed=(
                    not artifact.get("ready_for_development") or not blocking
                ),
            ),
        ]
