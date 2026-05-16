import json
import os
from datetime import datetime

from dotenv import load_dotenv
from sqlmodel import select

from agent.model_factory import get_model_factory
from agent.state import AgentState
from agent.tools import (
    analyze_earning_windows,
    calculate_financial_health_score,
    classify_risk,
    generate_repayment_plan,
    schedule_nudge,
)
from db.database import CommitmentBreach, Negotiation, Payment, get_session

load_dotenv()

FREEZE_THRESHOLD = int(os.getenv("COMMITMENT_FREEZE_THRESHOLD", "2"))
USE_MOCK_LLM = os.getenv("USE_MOCK_LLM", "false").lower() == "true"


class MockChatModel:
    def __init__(self, kind: str):
        self.kind = kind

    def invoke(self, prompt):
        text = str(prompt)
        if "professional case briefing" in text or "case briefing" in text.lower():
            content = (
                "This worker has repeated accepted-plan breaches and now requires manual review. "
                "Income data, overdue balance, and prior negotiation records indicate that another automated offer is unlikely to resolve the case without direct support contact. "
                "Recommended action: offer a structured 6-month micro-installment plan via phone call, confirm affordability verbally, and document whether hardship support or account review is needed before any further automated restructuring."
            )
        else:
            content = (
                "Thanks for continuing to work with us on this. Based on your recent earning pattern, we can align repayment with your stronger earning days and keep the amount manageable. Please review the plan below and let us know if it works for you."
            )
        return type("MockResponse", (), {"content": content})()


def _build_live_llms():
    factory = get_model_factory()
    return (factory.create_reasoning_model(), factory.create_fast_model())


if USE_MOCK_LLM:
    reasoning_llm = MockChatModel("reasoning")
    fast_llm = MockChatModel("fast")
else:
    reasoning_llm, fast_llm = _build_live_llms()


def _content(response) -> str:
    if hasattr(response, "content"):
        return response.content
    if hasattr(response, "text"):
        return response.text()
    return getattr(response, "content", str(response))


def _llm_error_message(exc: Exception) -> str:
    if "BEDROCK_REGION" in str(exc) or "AWS_DEFAULT_REGION" in str(exc):
        return "AWS region is missing. Set BEDROCK_REGION or AWS_DEFAULT_REGION, then restart the backend."
    if "Unable to locate credentials" in str(exc):
        return "AWS credentials were not found. Export AWS credentials in your environment, then restart the backend."
    if "InvalidClientTokenId" in str(exc) or "UnrecognizedClientException" in str(exc):
        return "AWS credentials or session token are invalid. Refresh the active AWS credentials and restart the backend."
    if "ExpiredToken" in str(exc):
        return "AWS session credentials have expired. Refresh AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, and AWS_SESSION_TOKEN, then restart the backend."
    if "AccessDenied" in str(exc) or "not authorized" in str(exc).lower():
        return "AWS denied Bedrock access. Check the IAM permissions for your current credentials and the chosen model IDs."
    return f"LLM call failed: {exc}"


def _format_installments(plan: dict) -> str:
    installments = plan.get("installments") or []
    if not installments:
        return "no automated installments"
    if len(installments) == 1:
        item = installments[0]
        return f"SGD {float(item['amount']):.2f} on {item['due_date']}"
    parts = [f"SGD {float(item['amount']):.2f} on {item['due_date']}" for item in installments]
    return ", ".join(parts[:-1]) + f", and {parts[-1]}"


def _fallback_agent_message(state: AgentState) -> str:
    peak_days = state["earnings_summary"].get("peak_days") or ["your stronger earning days"]
    plan = state.get("repayment_plan") or {}
    plan_text = _format_installments(plan)
    opener = f"Hi {state['user_id']}, we're reaching out about your overdue balance of SGD {state['amount_due']:.2f}."
    if state["risk_tier"] == "hardship":
        return (
            f"{opener} We can see your recent earnings have been lower, so we've included extra breathing room. "
            f"The proposed plan is {plan_text}. Please review it and tell us if this feels manageable."
        )
    if state["broken_commitments"] > 0:
        return (
            f"{opener} We know the last plan did not work out as expected, so this offer is aligned with "
            f"{' and '.join(peak_days)}. The proposed plan is {plan_text}. Please confirm if this works for you."
        )
    return (
        f"{opener} Based on your recent earnings, this is aligned with your stronger "
        f"{' and '.join(peak_days)} earning window. The proposed plan is {plan_text}. Please confirm if this works for you."
    )


def _message_is_complete(message: str, state: AgentState) -> bool:
    if not message or len(message.strip()) < 80:
        return False
    stripped = message.strip()
    if stripped.endswith((" for", " to", " with", " and", " of", " a", " the", ",", ":")):
        return False
    plan = state.get("repayment_plan") or {}
    installments = plan.get("installments") or []
    if installments and "SGD" not in stripped:
        return False
    if installments and not any(item["due_date"] in stripped for item in installments):
        return False
    return True


def node_fetch_and_analyze(state: AgentState) -> AgentState:
    earnings = analyze_earning_windows.invoke({"user_id": state["user_id"]})
    health = calculate_financial_health_score.invoke({"user_id": state["user_id"]})
    nudge = schedule_nudge.invoke({"earnings_summary": earnings})
    with get_session() as session:
        payment = session.get(Payment, state["payment_id"])
        if payment:
            state["broken_commitments"] = payment.broken_commitments
            state["restructuring_frozen"] = payment.restructuring_frozen
            state["days_overdue"] = payment.days_overdue
            state["prior_rejections"] = payment.prior_rejections
            state["amount_due"] = payment.amount_due
    state["earnings_summary"] = earnings
    state["financial_health"] = health
    state["nudge_scheduled_at"] = nudge
    return state


def node_check_commitment_freeze(state: AgentState) -> AgentState:
    if state["restructuring_frozen"] and state["broken_commitments"] >= FREEZE_THRESHOLD:
        state["status"] = "escalated"
        state["agent_message"] = (
            "We've noticed the repayment plans we agreed on haven't been followed through. "
            "Your case is being reviewed by our support team, who will contact you shortly."
        )
    return state


def node_classify_risk(state: AgentState) -> AgentState:
    risk = classify_risk.invoke(
        {
            "user_id": state["user_id"],
            "days_overdue": state["days_overdue"],
            "prior_rejections": state["prior_rejections"],
            "broken_commitments": state["broken_commitments"],
        }
    )
    state["risk_tier"] = risk["risk_tier"]
    state["risk_score"] = risk["risk_score"]
    state["risk_factors"] = risk["risk_factors"]
    state["recommended_tone"] = risk["recommended_tone"]
    state["can_self_serve"] = risk["can_self_serve"]
    return state


def node_generate_plan(state: AgentState) -> AgentState:
    plan = generate_repayment_plan.invoke(
        {
            "user_id": state["user_id"],
            "amount_due": state["amount_due"],
            "earnings_summary": state["earnings_summary"],
            "risk_tier": state["risk_tier"],
            "negotiation_round": state["negotiation_round"],
            "broken_commitments": state["broken_commitments"],
            "current_plan": state.get("prior_plan"),
        }
    )
    state["repayment_plan"] = plan
    state["prior_plan"] = None
    if plan["plan_type"] in {"frozen", "escalate"}:
        state["status"] = "escalated"
    else:
        state["status"] = "negotiating"
    return state


def node_draft_message(state: AgentState) -> AgentState:
    if state["status"] == "escalated":
        return state
    prompt = f"""
    You are a Grab collections support agent. Respond in 3-4 sentences maximum.
    Be empathetic, non-aggressive, never mention legal action.
    Tone: {state.get("recommended_tone")}.
    User: {state["user_id"]}; amount due SGD {state["amount_due"]:.2f}; days overdue {state["days_overdue"]}.
    Peak earning days: {", ".join(state["earnings_summary"].get("peak_days", []))}.
    Financial health: {state["financial_health"]}.
    Risk tier: {state["risk_tier"]}; factors: {state.get("risk_factors")}.
    Broken commitments: {state["broken_commitments"]}. If this is greater than 0, gently acknowledge that last time did not work out as planned.
    Repayment plan: {json.dumps(state["repayment_plan"])}.
    For hardship, acknowledge difficulty and offer the grace period proactively.
    """
    try:
        message = _content(reasoning_llm.invoke(prompt)).strip()
        state["agent_message"] = message if _message_is_complete(message, state) else _fallback_agent_message(state)
    except Exception as exc:
        state["agent_message"] = f"We had trouble drafting a personalized message. {_llm_error_message(exc)}"
    return state


def node_handle_response(state: AgentState) -> AgentState:
    response = state.get("user_response")
    if response == "accepted":
        state["status"] = "in_negotiation"
        with get_session() as session:
            session.add(
                Negotiation(
                    user_id=state["user_id"],
                    round=state["negotiation_round"],
                    plan_offered=json.dumps(state.get("repayment_plan") or {}),
                    user_response="accepted",
                    commitment_kept=None,
                    agent_message=state.get("agent_message") or "",
                )
            )
            payment = session.get(Payment, state["payment_id"])
            if payment:
                payment.status = "in_negotiation"
            session.commit()
    elif response == "rejected":
        offered_plan = state.get("repayment_plan") or {}
        state["negotiation_round"] += 1
        state["prior_plan"] = offered_plan
        state["repayment_plan"] = None
        state["status"] = "negotiating"
        with get_session() as session:
            payment = session.get(Payment, state["payment_id"])
            if payment:
                payment.prior_rejections += 1
                state["prior_rejections"] = payment.prior_rejections
            session.add(
                Negotiation(
                    user_id=state["user_id"],
                    round=state["negotiation_round"] - 1,
                    plan_offered=json.dumps(offered_plan),
                    user_response="rejected",
                    commitment_kept=None,
                    agent_message=state.get("agent_message") or "",
                )
            )
            session.commit()
    elif response == "support_requested":
        state["status"] = "escalated"
    return state


def _briefing_recommendation(state: AgentState) -> str:
    if state["risk_tier"] == "hardship" and state["broken_commitments"] > 0:
        return "Refer to Grab's financial assistance program (hardship + breaches)"
    if state["broken_commitments"] >= 3:
        return "Flag for GrabPay account review - possible fraud or identity issue"
    if state["broken_commitments"] >= 2:
        return "Offer a structured 6-month micro-installment plan via phone call"
    return "Issue final notice - standard collections process"


def node_escalate(state: AgentState) -> AgentState:
    with get_session() as session:
        payment = session.get(Payment, state["payment_id"])
        breaches = session.exec(
            select(CommitmentBreach).where(CommitmentBreach.user_id == state["user_id"]).order_by(CommitmentBreach.breach_number)
        ).all()
        negotiations = session.exec(
            select(Negotiation).where(Negotiation.user_id == state["user_id"]).order_by(Negotiation.timestamp)
        ).all()
        profile = {
            "name": payment.name if payment else state["user_id"],
            "gig_type": payment.gig_type if payment else "",
            "avg_daily_income": state.get("earnings_summary", {}).get("avg_daily_income"),
            "financial_health": state.get("financial_health"),
            "amount_due": state["amount_due"],
            "days_overdue": state["days_overdue"],
            "payment_id": state["payment_id"],
            "breaches": [b.model_dump(mode="json") for b in breaches],
            "negotiations": [n.model_dump(mode="json") for n in negotiations],
            "income_trajectory": state.get("earnings_summary"),
            "risk": {
                "tier": state.get("risk_tier"),
                "score": state.get("risk_score"),
                "factors": state.get("risk_factors"),
            },
            "recommended_action": _briefing_recommendation(state),
        }
        prompt = f"""
        Write a professional case briefing for an admin/support team. Target 200-300 words.
        Cover worker profile, debt summary, commitment breach history, negotiation history,
        income trajectory, risk assessment, and recommended action.
        Data: {json.dumps(profile, default=str)}
        """
        try:
            summary = _content(reasoning_llm.invoke(prompt)).strip()
        except Exception as exc:
            summary = (
                "Escalation summary could not be generated by the LLM. "
                f"{_llm_error_message(exc)} Recommended action: {profile['recommended_action']}."
            )

        state["escalation_summary"] = summary
        state["status"] = "escalated"
        state["agent_message"] = state.get("agent_message") or (
            "Your case is being reviewed by our support team, who will contact you shortly."
        )
        session.add(
            Negotiation(
                user_id=state["user_id"],
                round=state["negotiation_round"],
                plan_offered=json.dumps(state.get("repayment_plan") or {}),
                user_response="escalated",
                commitment_kept=None,
                agent_message=summary,
                timestamp=datetime.utcnow(),
            )
        )
        if payment:
            payment.status = "escalated"
            payment.restructuring_frozen = True
            state["restructuring_frozen"] = True
        session.commit()
    return state
