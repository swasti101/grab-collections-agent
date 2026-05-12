import json
import os
import uuid
from datetime import datetime

import pytz
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import select

from agent.graph import agent_graph
from agent.nodes import (
    node_classify_risk,
    node_draft_message,
    node_escalate,
    node_generate_plan,
    node_handle_response,
)
from agent.state import AgentState
from agent.tools import classify_risk
from api.models import AgentResponse, MarkPaymentMissedRequest, TriggerAgentRequest, UserResponseRequest
from db.database import (
    AgentSession,
    CommitmentBreach,
    FinancialHealthScore,
    Negotiation,
    Payment,
    create_db_and_tables,
    get_session,
)

load_dotenv()
SGT = pytz.timezone("Asia/Singapore")
FREEZE_THRESHOLD = int(os.getenv("COMMITMENT_FREEZE_THRESHOLD", "2"))

app = FastAPI(title="GrabHack AI Collections Agent")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    create_db_and_tables()


def _state_from_payment(payment: Payment) -> AgentState:
    return {
        "user_id": payment.user_id,
        "payment_id": payment.id,
        "amount_due": payment.amount_due,
        "days_overdue": payment.days_overdue,
        "prior_rejections": payment.prior_rejections,
        "broken_commitments": payment.broken_commitments,
        "restructuring_frozen": payment.restructuring_frozen,
        "earnings_summary": None,
        "financial_health": None,
        "risk_tier": None,
        "risk_score": None,
        "risk_factors": None,
        "recommended_tone": None,
        "can_self_serve": None,
        "repayment_plan": None,
        "nudge_scheduled_at": None,
        "agent_message": None,
        "negotiation_round": payment.prior_rejections,
        "user_response": None,
        "status": "pending",
        "escalation_summary": None,
        "conversation_history": [],
    }


def _save_state(state: AgentState, state_id: str | None = None) -> str:
    state_id = state_id or str(uuid.uuid4())
    with get_session() as session:
        existing = session.get(AgentSession, state_id)
        if existing:
            existing.state_json = json.dumps(state, default=str)
            existing.updated_at = datetime.utcnow()
        else:
            session.add(
                AgentSession(
                    state_id=state_id,
                    user_id=state["user_id"],
                    state_json=json.dumps(state, default=str),
                )
            )
        session.commit()
    return state_id


def _load_state(state_id: str) -> AgentState:
    with get_session() as session:
        row = session.get(AgentSession, state_id)
        if not row:
            raise HTTPException(status_code=404, detail="State session not found")
        return json.loads(row.state_json)


def _response(state: AgentState, state_id: str | None = None, next_action: str | None = None) -> AgentResponse:
    return AgentResponse(
        state_id=state_id,
        agent_message=state.get("agent_message"),
        plan=state.get("repayment_plan"),
        nudge_at=state.get("nudge_scheduled_at"),
        risk_tier=state.get("risk_tier"),
        financial_health=state.get("financial_health"),
        restructuring_frozen=state.get("restructuring_frozen", False),
        status=state.get("status", "pending"),
        escalation_summary=state.get("escalation_summary"),
        next_action=next_action,
    )


@app.post("/trigger-agent", response_model=AgentResponse)
def trigger_agent(req: TriggerAgentRequest):
    with get_session() as session:
        payment = session.exec(select(Payment).where(Payment.user_id == req.user_id)).first()
        if not payment:
            raise HTTPException(status_code=404, detail="User/payment not found")
        state = _state_from_payment(payment)
    try:
        state = agent_graph.invoke(state)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Agent failed: {exc}") from exc
    state_id = _save_state(state)
    return _response(state, state_id)


@app.post("/user-response", response_model=AgentResponse)
def user_response(req: UserResponseRequest):
    state = _load_state(req.state_id)
    state["user_response"] = req.user_response
    try:
        state = node_handle_response(state)
        if state["status"] == "escalated" or state["negotiation_round"] >= 3:
            state = node_escalate(state)
            next_action = "Support team review"
        elif req.user_response == "accepted":
            next_action = "Await first installment"
        else:
            state = node_classify_risk(state)
            state = node_generate_plan(state)
            if state["status"] == "escalated":
                state = node_escalate(state)
                next_action = "Support team review"
            else:
                state = node_draft_message(state)
                next_action = "Counter-offer generated"
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Response handling failed: {exc}") from exc
    _save_state(state, req.state_id)
    return _response(state, req.state_id, next_action)


@app.post("/mark-payment-missed")
def mark_payment_missed(req: MarkPaymentMissedRequest):
    with get_session() as session:
        negotiation = session.get(Negotiation, req.negotiation_id)
        if not negotiation or negotiation.user_id != req.user_id:
            raise HTTPException(status_code=404, detail="Negotiation not found for user")
        payment = session.exec(select(Payment).where(Payment.user_id == req.user_id)).first()
        if not payment:
            raise HTTPException(status_code=404, detail="Payment not found")

        negotiation.commitment_kept = False
        payment.broken_commitments += 1
        breach_number = payment.broken_commitments

        plan = json.loads(negotiation.plan_offered or "{}")
        first = (plan.get("installments") or [{}])[0]
        due_date = first.get("due_date") or datetime.now(SGT).date().isoformat()
        amount = float(first.get("amount") or payment.amount_due)

        breach = CommitmentBreach(
            user_id=req.user_id,
            payment_id=payment.id,
            negotiation_id=negotiation.id,
            plan_accepted_at=negotiation.timestamp,
            installment_due_date=datetime.fromisoformat(due_date).date(),
            installment_amount=amount,
            breach_detected_at=datetime.utcnow(),
            breach_number=breach_number,
        )
        session.add(breach)
        if payment.broken_commitments >= FREEZE_THRESHOLD:
            payment.restructuring_frozen = True
            payment.status = "escalated"
        frozen = payment.broken_commitments >= FREEZE_THRESHOLD
        session.commit()

    return {
        "breach_number": breach_number,
        "restructuring_frozen": frozen,
        "message": (
            "Commitment breach recorded. Autonomous restructuring is now frozen."
            if frozen
            else "Commitment breach recorded. One more breach will freeze autonomous restructuring."
        ),
    }


@app.get("/users")
def users():
    with get_session() as session:
        payments = session.exec(select(Payment).order_by(Payment.user_id)).all()
        health_rows = {h.user_id: h for h in session.exec(select(FinancialHealthScore)).all()}
    result = []
    for payment in payments:
        try:
            risk = classify_risk.invoke(
                {
                    "user_id": payment.user_id,
                    "days_overdue": payment.days_overdue,
                    "prior_rejections": payment.prior_rejections,
                    "broken_commitments": payment.broken_commitments,
                }
            )
            risk_tier = risk["risk_tier"]
        except Exception:
            risk_tier = "unknown"
        health = health_rows.get(payment.user_id)
        result.append(
            {
                "user_id": payment.user_id,
                "name": payment.name,
                "gig_type": payment.gig_type,
                "risk_tier": risk_tier,
                "health_score": health.score if health else None,
                "health_label": health.label if health else None,
                "broken_commitments": payment.broken_commitments,
                "restructuring_frozen": payment.restructuring_frozen,
                "status": payment.status,
                "amount_due": payment.amount_due,
                "days_overdue": payment.days_overdue,
            }
        )
    return result


@app.get("/dashboard")
def dashboard():
    user_rows = users()
    risk_breakdown = {"low": 0, "medium": 0, "high": 0, "hardship": 0}
    health_breakdown = {"Healthy": 0, "Fair": 0, "At Risk": 0, "Critical": 0}
    for row in user_rows:
        if row["risk_tier"] in risk_breakdown:
            risk_breakdown[row["risk_tier"]] += 1
        if row["health_label"] in health_breakdown:
            health_breakdown[row["health_label"]] += 1
    with get_session() as session:
        breaches = session.exec(select(CommitmentBreach)).all()
        negotiations = session.exec(select(Negotiation)).all()
    resolved = len([u for u in user_rows if u["status"] in ("resolved", "in_negotiation")])
    high_risk = [u for u in user_rows if u["risk_tier"] == "high"]
    return {
        "recovery_rate": round(resolved / max(len(user_rows), 1), 2),
        "risk_breakdown": risk_breakdown,
        "health_breakdown": health_breakdown,
        "commitment_breach_stats": {
            "total_breaches": len(breaches),
            "frozen_cases": len([u for u in user_rows if u["restructuring_frozen"]]),
            "avg_breaches_per_high_risk_user": round(
                sum(u["broken_commitments"] for u in high_risk) / max(len(high_risk), 1), 2
            ),
        },
        "escalated_cases": len([u for u in user_rows if u["status"] == "escalated"]),
        "avg_negotiation_rounds_to_resolve": round(
            sum(n.round for n in negotiations if n.user_response == "accepted") / max(len(negotiations), 1), 2
        ),
        "users": user_rows,
    }


@app.get("/user/{user_id}/history")
def user_history(user_id: str):
    with get_session() as session:
        negotiations = session.exec(
            select(Negotiation).where(Negotiation.user_id == user_id).order_by(Negotiation.timestamp)
        ).all()
        breaches = session.exec(
            select(CommitmentBreach).where(CommitmentBreach.user_id == user_id).order_by(CommitmentBreach.breach_number)
        ).all()
    return {
        "negotiations": [n.model_dump(mode="json") for n in negotiations],
        "commitment_breaches": [b.model_dump(mode="json") for b in breaches],
    }


@app.get("/user/{user_id}/health-score")
def user_health_score(user_id: str):
    with get_session() as session:
        health = session.exec(
            select(FinancialHealthScore).where(FinancialHealthScore.user_id == user_id)
        ).first()
        if not health:
            raise HTTPException(status_code=404, detail="Health score not found")
        return {
            "user_id": user_id,
            "score": health.score,
            "label": health.label,
            "component_scores": json.loads(health.component_scores),
            "insight": health.insight,
            "computed_at": health.computed_at.isoformat(),
        }
