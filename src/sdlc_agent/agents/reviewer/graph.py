"""PR Reviewer ReAct agent — principal engineer, read-only, approve or reject."""
from __future__ import annotations
from pathlib import Path
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent
from sdlc_agent.agents.reviewer.tools import make_reviewer_tools
from sdlc_agent.config import RootModelConfig
from sdlc_agent.mcp.git import LocalGitClient
from sdlc_agent.mcp.github import GitHubProjectClient
from sdlc_agent.skills.loader import SkillLoader, assemble_system_prompt

_REVIEWER_BASE_PROMPT = """You are the PR Reviewer agent — a principal engineer conducting a structured code review.

Your review checklist (in order):
1. Read the issue and acceptance criteria (provided in your task context).
2. Call list_changed_files to see what changed.
3. Call read_pr_diff to read the full diff.
4. Verify each acceptance criterion is met by the implementation.
5. Call read_test_report to check test results and coverage.
6. Check that unit tests exist for all new code paths.
7. Check that integration tests cover the full acceptance criteria flow.
8. Check coding standards: naming, structure, no hardcoded secrets.
9. If ALL criteria are met: call github_approve_pr with a clear summary.
10. If ANY criterion fails: call github_request_changes with SPECIFIC, ACTIONABLE feedback.

HARD RULES:
- You NEVER call write_file or any tool that modifies code.
- Rejection feedback must name the specific criterion that failed and describe exactly what fix is needed.
"""


def build_reviewer_graph(*, git_client: LocalGitClient, github: GitHubProjectClient,
                          repo_root: Path, model_config: RootModelConfig):
    llm = ChatOpenAI(model=model_config.default, temperature=0)
    tools = make_reviewer_tools(git_client=git_client, github=github, repo_root=repo_root)
    loader = SkillLoader()
    skill_names = [n for n in loader.available() if "review" in n]
    system_prompt = assemble_system_prompt(_REVIEWER_BASE_PROMPT, loader=loader, skill_names=skill_names)
    memory = MemorySaver()
    return create_react_agent(llm, tools=tools, checkpointer=memory, state_modifier=system_prompt)
