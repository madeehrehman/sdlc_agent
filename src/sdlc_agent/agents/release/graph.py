"""Release Engineer ReAct agent — merge, build, smoke test, HITL gate, deploy."""
from __future__ import annotations
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent
from sdlc_agent.agents.release.tools import make_release_tools
from sdlc_agent.config import DockerConfig, HitlConfig, RootModelConfig
from sdlc_agent.mcp.git import LocalGitClient

_RELEASE_PROMPT = """You are the Release Engineer agent.

Your workflow:
1. Call git_merge_branch to merge the approved feature branch into main.
2. Call docker_build to build the production Docker image.
3. Call run_smoke_tests to verify the image passes basic checks.
4. Call generate_release_summary with: branch, issue title, diff stats, test results, image tag.
5. Call request_human_approval with the summary. STOP and wait — execution pauses here.
6. If approved=true: call docker_deploy, then git_tag_release.
7. If approved=false: report the rejection reason back. Do NOT deploy.

RULES:
- NEVER call docker_deploy before request_human_approval returns approved=true.
- If docker_build or smoke tests fail, report the error and do NOT proceed to approval gate.
"""


def build_release_graph(*, git_client: LocalGitClient, model_config: RootModelConfig,
                         hitl_config: HitlConfig, docker_config: DockerConfig):
    llm = ChatOpenAI(model=model_config.default, temperature=0)
    tools = make_release_tools(git_client=git_client, docker_config=docker_config)
    memory = MemorySaver()
    return create_react_agent(llm, tools=tools, checkpointer=memory, state_modifier=_RELEASE_PROMPT)
