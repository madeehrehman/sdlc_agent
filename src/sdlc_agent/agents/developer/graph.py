"""Developer/Tester ReAct agent — TDD loop in Docker-isolated sandbox."""
from __future__ import annotations
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent
from sdlc_agent.agents.developer.tools import make_developer_tools
from sdlc_agent.config import RootModelConfig
from sdlc_agent.mcp.git import LocalGitClient
from sdlc_agent.sandbox.local import Sandbox
from sdlc_agent.skills.loader import SkillLoader, assemble_system_prompt

_DEVELOPER_BASE_PROMPT = """You are the Developer/Tester agent for this project.

Your workflow (strictly TDD):
1. Read the assigned issue and acceptance criteria carefully.
2. Call git_create_branch with name "feature/issue-{number}".
3. Call list_files to understand the current codebase structure.
4. Write tests FIRST (write_file for test files) — they must FAIL at this point.
5. Run tests to confirm they fail (run_tests).
6. Write implementation code to make tests pass (write_file for src files).
7. Run tests again until all pass.
8. Run linting if available (run_shell_command).
9. Call git_commit_all with a descriptive message.
10. Call git_push.
11. Report back: branch name, commit SHA, test results summary.

IMPORTANT: Tests must be written before implementation. Never skip the failing-test step.
"""


def build_developer_graph(*, sandbox: Sandbox, git_client: LocalGitClient, model_config: RootModelConfig):
    llm = ChatOpenAI(model=model_config.default, temperature=0)
    tools = make_developer_tools(sandbox=sandbox, git_client=git_client)
    loader = SkillLoader()
    system_prompt = assemble_system_prompt(_DEVELOPER_BASE_PROMPT, loader=loader, skill_names=loader.available())
    memory = MemorySaver()
    return create_react_agent(llm, tools=tools, checkpointer=memory, state_modifier=system_prompt)
