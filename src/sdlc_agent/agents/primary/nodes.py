"""Node functions for the Primary supervisor graph."""
from __future__ import annotations

import uuid

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from sdlc_agent.agents.primary.memory import ProjectMemory
from sdlc_agent.agents.primary.tools import make_primary_tools
from sdlc_agent.mcp.github import GitHubProjectClient
from sdlc_agent.state.schemas import IssueContext, PrimaryState

_PRIMARY_SYSTEM = """You are the Primary Agent: Project Manager, Business Analyst, and Architect for this software project.

Your responsibilities:
- Read specs and decompose them into clear, actionable GitHub issues with acceptance criteria
- Set architecture standards and coding conventions (stored in living memory)
- Assign issues to the Developer/Tester and track progress
- Review sub-agent reports and route to the next phase
- Update living memory with lessons learned after each ticket
- Close issues ONLY when deployment is confirmed

You NEVER write code, run tests, or access the codebase directly. All code work goes through sub-agents.
"""


class PrimaryNodes:
    def __init__(
        self,
        llm: ChatOpenAI,
        github: GitHubProjectClient,
        memory: ProjectMemory,
        developer_subgraph=None,
        reviewer_subgraph=None,
        release_subgraph=None,
    ) -> None:
        self.llm = llm
        self.github = github
        self.memory = memory
        self.developer_subgraph = developer_subgraph
        self.reviewer_subgraph = reviewer_subgraph
        self.release_subgraph = release_subgraph
        self.tools = make_primary_tools(github=github, memory=memory)
        self.llm_with_tools = llm.bind_tools(self.tools)

    def intake(self, state: PrimaryState) -> dict:
        snapshot = self.memory.read()
        memory_ctx = self.memory.as_context_string()
        msg = HumanMessage(content=(
            "Begin the SDLC workflow. Read the project specs and prepare to create issues.\n\n"
            f"Current project memory:\n{memory_ctx}"
        ))
        return {
            "phase": "intake",
            "memory_snapshot": snapshot,
            "messages": [SystemMessage(content=_PRIMARY_SYSTEM), msg],
        }

    def create_issues(self, state: PrimaryState) -> dict:
        response = self.llm_with_tools.invoke(state["messages"] + [
            HumanMessage(content=(
                "Read the spec file. Decompose it into detailed GitHub issues. "
                "For each issue: write a user story in the body, list acceptance criteria, "
                "add architecture notes based on project memory, label as 'Backlog'. "
                "Call create_github_issue for each one."
            ))
        ])
        return {"messages": [response], "phase": "create_issues"}

    def assign_development(self, state: PrimaryState) -> dict:
        response = self.llm_with_tools.invoke(state["messages"] + [
            HumanMessage(content=(
                "Call list_open_issues to find the next Backlog issue. "
                "Call update_issue_label to set it to 'In Progress'. "
                "Return the issue number and title."
            ))
        ])
        items = self.github.list_project_items()
        in_progress = [i for i in items if i.status == "In Progress"]
        if not in_progress:
            return {"messages": [response], "phase": "done", "retry_count": 0}
        item = in_progress[0]
        issue = self.github.get_issue(item.issue_number)
        issue_ctx: IssueContext = {
            "number": issue.number,
            "title": issue.title,
            "body": issue.body,
            "url": issue.url,
            "acceptance_criteria": issue.acceptance_criteria,
        }
        dev_result = None
        if self.developer_subgraph is not None:
            thread_id = str(uuid.uuid4())
            dev_input = {
                "messages": [HumanMessage(content=(
                    f"Issue #{issue.number}: {issue.title}\n\n"
                    f"{issue.body}\n\n"
                    "Acceptance criteria:\n" +
                    "\n".join(f"- {c}" for c in issue.acceptance_criteria) +
                    f"\n\nMemory context:\n{self.memory.as_context_string()}"
                ))]
            }
            dev_output = self.developer_subgraph.invoke(dev_input, {"configurable": {"thread_id": thread_id}})
            last_msg = dev_output.get("messages", [{}])[-1]
            content = getattr(last_msg, "content", "") if hasattr(last_msg, "content") else str(last_msg)
            dev_result = {
                "branch": f"feature/issue-{issue.number}",
                "test_results": {"summary": content[:200]},
                "commit_sha": "",
                "success": "error" not in content.lower(),
            }
        return {
            "messages": [response],
            "phase": "dev",
            "current_issue": issue_ctx,
            "dev_result": dev_result,
            "retry_count": state.get("retry_count", 0),
        }

    def assign_review(self, state: PrimaryState) -> dict:
        issue = state.get("current_issue")
        dev = state.get("dev_result") or {}
        if issue:
            self.github.update_project_status(f"ISSUE_{issue['number']}", "Ready for Review")
        review_result = None
        if self.reviewer_subgraph is not None and issue:
            thread_id = str(uuid.uuid4())
            review_input = {
                "messages": [HumanMessage(content=(
                    f"Review PR for Issue #{issue['number']}: {issue['title']}\n"
                    f"Branch: {dev.get('branch', 'unknown')}\n\n"
                    "Acceptance criteria:\n" +
                    "\n".join(f"- {c}" for c in issue.get("acceptance_criteria", [])) +
                    "\n\nPlease review the diff and verify all criteria are met."
                ))]
            }
            rev_output = self.reviewer_subgraph.invoke(review_input, {"configurable": {"thread_id": thread_id}})
            last_msg = rev_output.get("messages", [{}])[-1]
            content = getattr(last_msg, "content", "") if hasattr(last_msg, "content") else str(last_msg)
            approved = "approved" in content.lower() and "request_changes" not in content.lower()
            review_result = {
                "approved": approved,
                "feedback": content[:400],
                "pr_url": f"https://github.com/owner/repo/pull/{issue['number']}",
            }
        return {
            "phase": "review",
            "review_result": review_result,
            "messages": state["messages"] + [HumanMessage(content=(
                f"Developer finished. Branch: {dev.get('branch', 'unknown')}. Invoking PR Reviewer."
            ))],
        }

    def assign_release(self, state: PrimaryState) -> dict:
        issue = state.get("current_issue")
        dev = state.get("dev_result") or {}
        if issue:
            self.github.update_project_status(f"ISSUE_{issue['number']}", "Approved")
        release_result = None
        if self.release_subgraph is not None and issue:
            thread_id = str(uuid.uuid4())
            release_input = {
                "messages": [HumanMessage(content=(
                    f"Deploy approved branch for Issue #{issue['number']}: {issue['title']}\n"
                    f"Branch: {dev.get('branch', 'unknown')}\n"
                    "Build the Docker image, run smoke tests, present summary for human approval, then deploy."
                ))]
            }
            rel_output = self.release_subgraph.invoke(release_input, {"configurable": {"thread_id": thread_id}})
            last_msg = rel_output.get("messages", [{}])[-1]
            content = getattr(last_msg, "content", "") if hasattr(last_msg, "content") else str(last_msg)
            deployed = "deployed" in content.lower() or "running" in content.lower()
            release_result = {
                "deployed": deployed,
                "deployment_url": "docker://sdlc-app-prod" if deployed else "",
                "reason": content[:300],
            }
        return {
            "phase": "release",
            "release_result": release_result,
            "messages": state["messages"] + [HumanMessage(content="PR approved. Invoking Release Engineer.")],
        }

    def close_issue(self, state: PrimaryState) -> dict:
        issue = state.get("current_issue")
        release = state.get("release_result") or {}
        if issue:
            self.github.close_issue(issue["number"])
        self.memory.update({
            "lessons_learned": [f"Issue #{issue['number'] if issue else '?'}: deployed to {release.get('deployment_url', 'unknown')}"],
        })
        return {
            "phase": "done",
            "retry_count": 0,
            "messages": state["messages"] + [HumanMessage(content="Issue closed. Memory updated.")],
        }

    def handle_rejection(self, state: PrimaryState) -> dict:
        review = state.get("review_result") or {}
        release = state.get("release_result") or {}
        feedback = review.get("feedback") or release.get("reason") or "Rejected without feedback."
        retry = state.get("retry_count", 0) + 1
        issue = state.get("current_issue")
        if issue:
            self.github.update_project_status(f"ISSUE_{issue['number']}", "Changes Requested")
        return {
            "phase": "dev",
            "retry_count": retry,
            "review_result": None,
            "release_result": None,
            "messages": state["messages"] + [HumanMessage(content=(
                f"Rejected (attempt {retry}). Feedback: {feedback}. Re-assigning to Developer."
            ))],
        }
