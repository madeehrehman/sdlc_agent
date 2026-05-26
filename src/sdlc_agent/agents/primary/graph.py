"""Primary supervisor StateGraph."""
from __future__ import annotations

from typing import Any

from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from sdlc_agent.agents.primary.memory import ProjectMemory
from sdlc_agent.agents.primary.nodes import PrimaryNodes
from sdlc_agent.config import HitlConfig, RootModelConfig
from sdlc_agent.mcp.github import GitHubProjectClient
from sdlc_agent.state.schemas import PrimaryState


def route_intake(state: PrimaryState) -> str:
    return "create_issues"


def route_dev_result(state: PrimaryState) -> str:
    dev = state.get("dev_result")
    if dev and dev.get("success"):
        return "assign_review"
    return "handle_rejection"


def route_review_result(state: PrimaryState) -> str:
    review = state.get("review_result")
    if review and review.get("approved"):
        return "assign_release"
    return "handle_rejection"


def route_release_result(state: PrimaryState, hitl_config: HitlConfig) -> str:
    release = state.get("release_result")
    if release and release.get("deployed"):
        return "close_issue"
    return "handle_rejection"


def route_next_ticket(state: PrimaryState) -> str:
    return "assign_development"


def build_primary_graph(
    *,
    github: GitHubProjectClient,
    memory: ProjectMemory,
    model_config: RootModelConfig,
    hitl_config: HitlConfig,
    developer_subgraph: Any,
    reviewer_subgraph: Any,
    release_subgraph: Any,
):
    llm = ChatOpenAI(model=model_config.default, temperature=model_config.temperature)
    nodes = PrimaryNodes(
        llm=llm,
        github=github,
        memory=memory,
        developer_subgraph=developer_subgraph,
        reviewer_subgraph=reviewer_subgraph,
        release_subgraph=release_subgraph,
    )

    graph = StateGraph(PrimaryState)

    graph.add_node("intake", nodes.intake)
    graph.add_node("create_issues", nodes.create_issues)
    graph.add_node("assign_development", nodes.assign_development)
    graph.add_node("assign_review", nodes.assign_review)
    graph.add_node("assign_release", nodes.assign_release)
    graph.add_node("close_issue", nodes.close_issue)
    graph.add_node("handle_rejection", nodes.handle_rejection)

    graph.set_entry_point("intake")

    graph.add_conditional_edges("intake", route_intake, {
        "create_issues": "create_issues",
        "assign_development": "assign_development",
    })
    graph.add_edge("create_issues", "assign_development")
    graph.add_conditional_edges("assign_development", route_dev_result, {
        "assign_review": "assign_review",
        "handle_rejection": "handle_rejection",
    })
    graph.add_conditional_edges("assign_review", route_review_result, {
        "assign_release": "assign_release",
        "handle_rejection": "handle_rejection",
    })
    graph.add_conditional_edges(
        "assign_release",
        lambda s: route_release_result(s, hitl_config),
        {"close_issue": "close_issue", "handle_rejection": "handle_rejection"},
    )
    graph.add_conditional_edges("close_issue", route_next_ticket, {
        "assign_development": "assign_development",
        END: END,
    })
    graph.add_edge("handle_rejection", "assign_development")

    checkpointer = MemorySaver()
    return graph.compile(checkpointer=checkpointer)
