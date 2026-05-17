import os
from typing import Any

from agent.graph import agent_graph
from agent.model_factory import get_model_factory
from agent.state import AgentState


def _money(value: float) -> str:
    return f"SGD {float(value):.2f}"


def _installment_summary(plan: dict | None) -> str:
    if not plan:
        return "No repayment plan generated."
    installments = plan.get("installments") or []
    if not installments:
        return plan.get("summary") or "No installments generated."
    return "; ".join(f"{_money(item['amount'])} on {item['due_date']}" for item in installments)


def _step_payload(node_name: str, state: AgentState) -> dict[str, Any]:
    reasoning_model = os.getenv("BEDROCK_REASONING_MODEL", get_model_factory().reasoning_model_id)
    if node_name == "fetch_and_analyze":
        earnings = state.get("earnings_summary") or {}
        health = state.get("financial_health") or {}
        analysis = [
            f"Pulled the last 30 days of earnings for {state['user_id']}.",
            f"Checked peak earning days: {', '.join(earnings.get('peak_days', [])) or 'not available'}.",
            f"Calculated financial health score: {health.get('score', 'n/a')} ({health.get('label', 'unknown')}).",
            f"Scheduled the next nudge for {state.get('nudge_scheduled_at') or 'not available'}.",
        ]
        result = (
            f"Average daily income {_money(earnings.get('avg_daily_income', 0))}; "
            f"trend {earnings.get('income_trend', 'unknown')}; volatility {earnings.get('income_volatility', 'unknown')}."
        )
        return {
            "langgraph_node": node_name,
            "title": "Analyze worker income patterns and financial health",
            "tools_called": ["analyze_earning_windows", "calculate_financial_health_score", "schedule_nudge"],
            "analysis": analysis,
            "result": result,
        }
    if node_name == "check_commitment_freeze":
        frozen = state.get("restructuring_frozen")
        broken = state.get("broken_commitments", 0)
        threshold = os.getenv("COMMITMENT_FREEZE_THRESHOLD", "2")
        return {
            "langgraph_node": node_name,
            "title": "Check commitment freeze",
            "tools_called": [],
            "analysis": [
                f"Broken commitments on record: {broken}.",
                f"Autonomous freeze threshold: {threshold}.",
                "Checked whether the worker must be escalated before any new offer is generated.",
            ],
            "result": "Escalation required." if frozen and broken >= int(threshold) else "Worker can continue through the self-serve collections flow.",
        }
    if node_name == "classify_risk":
        return {
            "langgraph_node": node_name,
            "title": "Classify repayment risk score",
            "tools_called": ["classify_risk"],
            "analysis": [
                f"Reviewed overdue days: {state.get('days_overdue', 0)}.",
                f"Reviewed prior rejections: {state.get('prior_rejections', 0)}.",
                f"Reviewed broken commitments: {state.get('broken_commitments', 0)}.",
                f"Considered current earnings stability and hardship signals.",
            ],
            "result": (
                f"Risk tier {state.get('risk_tier', 'unknown')} with score {state.get('risk_score', 'n/a')}. "
                f"Key factors: {', '.join(state.get('risk_factors') or ['none'])}."
            ),
        }
    if node_name == "generate_plan":
        plan = state.get("repayment_plan") or {}
        return {
            "langgraph_node": node_name,
            "title": "Generate repayment plan",
            "tools_called": ["generate_repayment_plan"],
            "analysis": [
                f"Risk tier driving plan logic: {state.get('risk_tier', 'unknown')}.",
                f"Negotiation round: {state.get('negotiation_round', 0)}.",
                f"Broken commitments: {state.get('broken_commitments', 0)}.",
                "Aligned plan timing to the worker's stronger earning windows when possible.",
            ],
            "result": (
                f"Status moved to {state.get('status', 'pending')}. "
                f"Plan output: {_installment_summary(plan)}"
            ),
        }
    if node_name == "draft_message":
        return {
            "langgraph_node": node_name,
            "title": "Draft worker notification message",
            "tools_called": [f"bedrock.invoke_model ({reasoning_model})"],
            "analysis": [
                f"Used tone {state.get('recommended_tone', 'unknown')}.",
                f"Used plan summary: {_installment_summary(state.get('repayment_plan'))}.",
                "Drafted an empathetic worker-facing message with no legal or aggressive language.",
            ],
            "result": state.get("agent_message") or "No message drafted.",
        }
    if node_name == "escalate":
        return {
            "langgraph_node": node_name,
            "title": "Escalate to support",
            "tools_called": [f"bedrock.invoke_model ({reasoning_model})"],
            "analysis": [
                "Collected breach history, negotiation history, debt summary, and income trajectory.",
                "Prepared a support-facing escalation briefing.",
            ],
            "result": state.get("escalation_summary") or "Escalation summary unavailable.",
        }
    return {
        "langgraph_node": node_name,
        "title": node_name.replace("_", " ").title(),
        "tools_called": [],
        "analysis": [],
        "result": "Step completed.",
    }


def stream_agent_preview(initial_state: AgentState):
    trace_steps: list[dict[str, Any]] = []
    raw_trace: list[dict[str, Any]] = []
    final_state = initial_state

    for index, event in enumerate(agent_graph.stream(initial_state, stream_mode="updates"), start=1):
        if not isinstance(event, dict):
            continue
        node_name, state = next(iter(event.items()))
        final_state = state
        step = _step_payload(node_name, state)
        step["step_number"] = index
        trace_steps.append(step)
        raw_trace.append({"step_number": index, "langgraph_node": node_name})
        yield {"event": "step", "step": step}

    yield {
        "event": "completed",
        "final_state": final_state,
        "trace_steps": trace_steps,
        "langgraph_trace": raw_trace,
    }


def run_agent_preview(initial_state: AgentState) -> tuple[AgentState, list[dict[str, Any]], list[dict[str, Any]]]:
    trace_steps: list[dict[str, Any]] = []
    raw_trace: list[dict[str, Any]] = []
    final_state = initial_state

    for index, event in enumerate(agent_graph.stream(initial_state, stream_mode="updates"), start=1):
        if not isinstance(event, dict):
            continue
        node_name, state = next(iter(event.items()))
        final_state = state
        step = _step_payload(node_name, state)
        step["step_number"] = index
        trace_steps.append(step)
        raw_trace.append({"step_number": index, "langgraph_node": node_name})

    return final_state, trace_steps, raw_trace
