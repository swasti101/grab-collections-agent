from langgraph.graph import END, StateGraph

from agent.nodes import (
    node_check_commitment_freeze,
    node_classify_risk,
    node_draft_message,
    node_escalate,
    node_fetch_and_analyze,
    node_generate_plan,
    node_handle_response,
)
from agent.state import AgentState


def route_after_freeze_check(state: AgentState) -> str:
    if state["status"] == "escalated":
        return "escalate"
    return "classify_risk"


def should_continue(state: AgentState) -> str:
    if state["status"] == "resolved":
        return "end"
    if state["status"] == "escalated":
        return "escalate"
    if state["negotiation_round"] >= 3:
        return "escalate"
    return "generate_plan"


def route_after_plan(state: AgentState) -> str:
    if state["status"] == "escalated":
        return "escalate"
    return "draft_message"


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("fetch_and_analyze", node_fetch_and_analyze)
    graph.add_node("check_commitment_freeze", node_check_commitment_freeze)
    graph.add_node("classify_risk", node_classify_risk)
    graph.add_node("generate_plan", node_generate_plan)
    graph.add_node("draft_message", node_draft_message)
    graph.add_node("handle_response", node_handle_response)
    graph.add_node("escalate", node_escalate)

    graph.set_entry_point("fetch_and_analyze")
    graph.add_edge("fetch_and_analyze", "check_commitment_freeze")
    graph.add_conditional_edges(
        "check_commitment_freeze",
        route_after_freeze_check,
        {"escalate": "escalate", "classify_risk": "classify_risk"},
    )
    graph.add_edge("classify_risk", "generate_plan")
    graph.add_conditional_edges(
        "generate_plan",
        route_after_plan,
        {"escalate": "escalate", "draft_message": "draft_message"},
    )
    graph.add_edge("draft_message", END)
    graph.add_conditional_edges(
        "handle_response",
        should_continue,
        {"end": END, "escalate": "escalate", "generate_plan": "generate_plan"},
    )
    graph.add_edge("escalate", END)
    return graph.compile()


agent_graph = build_graph()
