import json
import os
import uuid
from collections import defaultdict
from datetime import datetime, timedelta

import pytz
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlmodel import select

from agent.drift import scan_all_workers_with_trace, stream_drift_scan_with_trace
from agent.graph import agent_graph
from agent.nodes import (
    node_classify_risk,
    node_draft_message,
    node_escalate,
    node_generate_plan,
    node_handle_response,
)
from agent.state import AgentState
from agent.trace import run_agent_preview, stream_agent_preview
from agent.tools import classify_risk
from api.models import (
    AgentResponse,
    MarkPaymentMissedRequest,
    SendProactiveCheckInRequest,
    SendPreviewNotificationRequest,
    SendNotificationRequest,
    TriggerAgentRequest,
    UserResponseRequest,
    WorkerNotificationResponseRequest,
)
from db.database import (
    AgentSession,
    CommitmentBreach,
    Earning,
    FinancialHealthScore,
    Negotiation,
    Payment,
    WorkerNotification,
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
        "prior_plan": None,
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


def _run_agent_for_user(user_id: str) -> tuple[AgentState, str]:
    with get_session() as session:
        payment = session.exec(select(Payment).where(Payment.user_id == user_id)).first()
        if not payment:
            raise HTTPException(status_code=404, detail="User/payment not found")
        state = _state_from_payment(payment)
    try:
        state = agent_graph.invoke(state)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Agent failed: {exc}") from exc
    state_id = _save_state(state)
    return state, state_id


def _load_payment_for_user(user_id: str) -> Payment:
    with get_session() as session:
        payment = session.exec(select(Payment).where(Payment.user_id == user_id)).first()
        if not payment:
            raise HTTPException(status_code=404, detail="User/payment not found")
        return payment


def _notification_preview_from_state(state: AgentState, state_id: str) -> dict:
    return {
        "state_id": state_id,
        "notification_type": "collections",
        "status": "ready_for_review",
        "message": state.get("agent_message") or "",
        "repayment_plan": state.get("repayment_plan") or {},
        "escalation_summary": state.get("escalation_summary"),
    }


def _agent_preview_payload(user_id: str) -> dict:
    payment = _load_payment_for_user(user_id)
    initial_state = _state_from_payment(payment)
    try:
        final_state, trace_steps, raw_trace = run_agent_preview(initial_state)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Agent preview failed: {exc}") from exc
    state_id = _save_state(final_state)
    return {
        "state_id": state_id,
        "user_id": user_id,
        "trace_steps": trace_steps,
        "langgraph_trace": raw_trace,
        "agent": _response(final_state, state_id).model_dump(),
        "notification_preview": _notification_preview_from_state(final_state, state_id),
    }


def _stream_json_line(payload: dict) -> str:
    return json.dumps(payload, default=str) + "\n"


def _store_notification(state: AgentState, state_id: str) -> WorkerNotification:
    with get_session() as session:
        notification = WorkerNotification(
            user_id=state["user_id"],
            payment_id=state["payment_id"],
            state_id=state_id,
            message=state.get("agent_message") or "",
            repayment_plan=json.dumps(state.get("repayment_plan") or {}),
            status="escalated" if state.get("status") == "escalated" else "unread",
            escalation_summary=state.get("escalation_summary"),
        )
        session.add(notification)
        session.commit()
        session.refresh(notification)
        return notification


def _notification_type(notification: WorkerNotification) -> str:
    return "proactive_checkin" if notification.status.startswith("proactive_") else "collections"


def _store_proactive_notification(req: SendProactiveCheckInRequest) -> WorkerNotification:
    with get_session() as session:
        payment = session.exec(select(Payment).where(Payment.user_id == req.user_id)).first()
        if not payment:
            raise HTTPException(status_code=404, detail="User/payment not found")

        existing = session.exec(
            select(WorkerNotification)
            .where(WorkerNotification.user_id == req.user_id)
            .order_by(WorkerNotification.created_at)
        ).all()
        open_proactive = next(
            (
                notification
                for notification in reversed(existing)
                if notification.status in {"proactive_unread", "proactive_options_requested", "proactive_support_requested"}
            ),
            None,
        )
        if open_proactive:
            open_proactive.message = req.message
            open_proactive.escalation_summary = req.drift_summary
            open_proactive.updated_at = datetime.utcnow()
            session.add(open_proactive)
            session.commit()
            session.refresh(open_proactive)
            return open_proactive

        notification = WorkerNotification(
            user_id=req.user_id,
            payment_id=payment.id,
            state_id=f"drift-{uuid.uuid4()}",
            message=req.message,
            repayment_plan="{}",
            status="proactive_unread",
            escalation_summary=req.drift_summary,
        )
        session.add(notification)
        session.commit()
        session.refresh(notification)
        return notification


def _notification_payload(notification: WorkerNotification) -> dict:
    return {
        "id": notification.id,
        "user_id": notification.user_id,
        "payment_id": notification.payment_id,
        "state_id": notification.state_id,
        "notification_type": _notification_type(notification),
        "message": notification.message,
        "repayment_plan": json.loads(notification.repayment_plan or "{}"),
        "status": notification.status,
        "drift_summary": notification.escalation_summary if _notification_type(notification) == "proactive_checkin" else None,
        "escalation_summary": notification.escalation_summary,
        "created_at": notification.created_at.isoformat(),
        "updated_at": notification.updated_at.isoformat(),
    }


@app.post("/trigger-agent", response_model=AgentResponse)
def trigger_agent(req: TriggerAgentRequest):
    state, state_id = _run_agent_for_user(req.user_id)
    return _response(state, state_id)


@app.post("/agent-preview")
def agent_preview(req: TriggerAgentRequest):
    return _agent_preview_payload(req.user_id)


@app.post("/agent-preview/stream")
def agent_preview_stream(req: TriggerAgentRequest):
    def generate():
        payment = _load_payment_for_user(req.user_id)
        initial_state = _state_from_payment(payment)
        yield _stream_json_line({"event": "started", "user_id": req.user_id})
        final_payload = None
        for event in stream_agent_preview(initial_state):
            if event.get("event") == "step":
                yield _stream_json_line(event)
                continue
            final_state = event["final_state"]
            state_id = _save_state(final_state)
            final_payload = {
                "state_id": state_id,
                "user_id": req.user_id,
                "trace_steps": event["trace_steps"],
                "langgraph_trace": event["langgraph_trace"],
                "agent": _response(final_state, state_id).model_dump(),
                "notification_preview": _notification_preview_from_state(final_state, state_id),
            }
        yield _stream_json_line({"event": "completed", "preview": final_payload})

    return StreamingResponse(generate(), media_type="application/x-ndjson")


@app.post("/notifications/send-previewed")
def send_previewed_notification(req: SendPreviewNotificationRequest):
    state = _load_state(req.state_id)
    notification = _store_notification(state, req.state_id)
    return {
        "message": "notification delivered",
        "notification": _notification_payload(notification),
        "agent": _response(state, req.state_id).model_dump(),
    }


@app.post("/notifications/send")
def send_notification(req: SendNotificationRequest):
    state, state_id = _run_agent_for_user(req.user_id)
    notification = _store_notification(state, state_id)
    return {
        "message": "notification delivered",
        "notification": _notification_payload(notification),
        "agent": _response(state, state_id).model_dump(),
    }


@app.get("/drift-scan")
def drift_scan():
    scan = scan_all_workers_with_trace()
    results = scan["results"]
    drifting = [row for row in results if row.get("drifting")]
    return {
        "scanned_at": datetime.utcnow().isoformat(),
        "total_workers": len(results),
        "drifting_workers": len(drifting),
        "scan_trace": scan["scan_trace"],
        "results": results,
    }


@app.get("/drift-scan/stream")
def drift_scan_stream():
    def generate():
        yield _stream_json_line({"event": "started"})
        final_payload = None
        for event in stream_drift_scan_with_trace():
            if event.get("event") == "completed":
                results = event["results"]
                drifting = [row for row in results if row.get("drifting")]
                final_payload = {
                    "scanned_at": datetime.utcnow().isoformat(),
                    "total_workers": len(results),
                    "drifting_workers": len(drifting),
                    "scan_trace": event["scan_trace"],
                    "results": results,
                }
                continue
            yield _stream_json_line(event)
        yield _stream_json_line({"event": "completed", "scan": final_payload})

    return StreamingResponse(generate(), media_type="application/x-ndjson")


@app.post("/notifications/send-proactive-checkin")
def send_proactive_checkin(req: SendProactiveCheckInRequest):
    notification = _store_proactive_notification(req)
    return {
        "message": "proactive check-in delivered",
        "notification": _notification_payload(notification),
    }


def _proactive_response_payload(notification: WorkerNotification) -> dict:
    return {
        "state_id": notification.state_id,
        "agent_message": notification.message,
        "plan": {},
        "nudge_at": None,
        "risk_tier": None,
        "financial_health": None,
        "restructuring_frozen": False,
        "status": notification.status,
        "escalation_summary": notification.escalation_summary,
        "next_action": None,
    }


def _handle_proactive_notification_response(req: WorkerNotificationResponseRequest) -> dict:
    with get_session() as session:
        notification = session.get(WorkerNotification, req.notification_id)
        if not notification:
            raise HTTPException(status_code=404, detail="Notification not found")
        if req.user_response == "accepted":
            notification.status = "proactive_acknowledged"
            notification.message = (
                "Thanks for checking in. We will keep things flexible on our side, and if your routine changes again you can reach out early anytime."
            )
        elif req.user_response == "rejected":
            notification.status = "proactive_options_requested"
            notification.message = (
                "Thanks for raising your hand early. We can talk through lighter options ahead of time so nothing feels rushed closer to your next payment window."
            )
        else:
            notification.status = "proactive_support_requested"
            notification.message = (
                "Thanks for letting us know. A support teammate will review this early and help you talk through options before things become urgent."
            )
            notification.escalation_summary = notification.escalation_summary or "Worker requested proactive support."
        notification.updated_at = datetime.utcnow()
        session.add(notification)
        session.commit()
        session.refresh(notification)
        return _proactive_response_payload(notification)


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


@app.post("/worker/notification-response")
def worker_notification_response(req: WorkerNotificationResponseRequest):
    with get_session() as session:
        notification = session.get(WorkerNotification, req.notification_id)
        if not notification:
            raise HTTPException(status_code=404, detail="Notification not found")
        if _notification_type(notification) == "proactive_checkin":
            return _handle_proactive_notification_response(req)
        state_id = notification.state_id
    response = user_response(UserResponseRequest(state_id=state_id, user_response=req.user_response))
    with get_session() as session:
        notification = session.get(WorkerNotification, req.notification_id)
        if notification:
            notification.status = {
                "accepted": "accepted",
                "rejected": "counter_offered",
                "support_requested": "worker_escalated",
            }[req.user_response]
            notification.updated_at = datetime.utcnow()
            if response.plan:
                notification.repayment_plan = json.dumps(response.plan)
            if response.agent_message:
                notification.message = response.agent_message
            if response.escalation_summary:
                notification.escalation_summary = response.escalation_summary
            session.commit()
    return response


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


def _latest_health_map(session):
    return {h.user_id: h for h in session.exec(select(FinancialHealthScore)).all()}


def _risk_for_payment(payment: Payment) -> dict:
    try:
        return classify_risk.invoke(
            {
                "user_id": payment.user_id,
                "days_overdue": payment.days_overdue,
                "prior_rejections": payment.prior_rejections,
                "broken_commitments": payment.broken_commitments,
            }
        )
    except Exception:
        return {"risk_tier": "unknown", "risk_score": 0, "risk_factors": []}


def _escalation_source_for_user(user_id: str, notifications: list[WorkerNotification]) -> str:
    if any(n.user_id == user_id and n.status == "worker_escalated" for n in notifications):
        return "worker"
    user_escalations = [n for n in notifications if n.user_id == user_id and n.status == "escalated"]
    for notification in user_escalations:
        created_at = notification.created_at
        updated_at = notification.updated_at
        if isinstance(created_at, datetime) and isinstance(updated_at, datetime):
            if (updated_at - created_at).total_seconds() > 5:
                return "worker"
    return "agent"


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
        payments = session.exec(select(Payment).order_by(Payment.user_id)).all()
        health_rows = _latest_health_map(session)
        breaches = session.exec(select(CommitmentBreach)).all()
        negotiations = session.exec(select(Negotiation)).all()
        notifications = session.exec(select(WorkerNotification)).all()

    resolved = len([u for u in user_rows if u["status"] in ("resolved", "in_negotiation")])
    actual_recovery_rate = round(resolved / max(len(user_rows), 1), 2)
    demo_recovery_rate = max(actual_recovery_rate, 0.64)
    high_risk = [u for u in user_rows if u["risk_tier"] == "high"]
    revenue_by_tier = defaultdict(float)
    health_by_gig = defaultdict(list)
    escalation_queue = []
    for payment in payments:
        risk = _risk_for_payment(payment)
        revenue_by_tier[risk["risk_tier"]] += payment.amount_due if payment.status != "resolved" else 0
        health = health_rows.get(payment.user_id)
        if health:
            health_by_gig[payment.gig_type].append(health.score)
        if payment.status == "escalated" or payment.restructuring_frozen:
            escalation_source = _escalation_source_for_user(payment.user_id, notifications)
            latest_summary = next(
                (n.agent_message for n in reversed(negotiations) if n.user_id == payment.user_id and n.user_response == "escalated"),
                "",
            )
            escalation_queue.append(
                {
                    "user_id": payment.user_id,
                    "name": payment.name,
                    "gig_type": payment.gig_type,
                    "risk_tier": risk["risk_tier"],
                    "risk_score": risk.get("risk_score", 0),
                    "health_score": health.score if health else None,
                    "health_label": health.label if health else None,
                    "amount_due": payment.amount_due,
                    "days_overdue": payment.days_overdue,
                    "broken_commitments": payment.broken_commitments,
                    "restructuring_frozen": payment.restructuring_frozen,
                    "escalation_source": escalation_source,
                    "summary": latest_summary
                    or (
                        f"{payment.name} has {payment.broken_commitments} broken commitment(s), "
                        f"SGD {payment.amount_due:.2f} overdue, and should be reviewed by support."
                    ),
                    "severity": risk.get("risk_score", 0) + payment.broken_commitments * 15,
                    "status": payment.status,
                }
            )
    escalation_queue.sort(key=lambda row: row["severity"], reverse=True)
    total_due = sum(p.amount_due for p in payments if p.status != "resolved")
    avg_health = round(
        sum(h.score for h in health_rows.values()) / max(len(health_rows), 1)
    )
    monthly_recovery_rate = [
        {"month": "Mar", "rate": 0.52},
        {"month": "Apr", "rate": 0.56},
        {"month": "May", "rate": demo_recovery_rate},
    ]
    active_negotiations = len([p for p in payments if p.status == "in_negotiation"]) + len(
        [n for n in notifications if n.status in {"unread", "counter_offered"}]
    )
    ai_resolved = len([n for n in negotiations if n.user_response == "accepted"])
    human_escalated = len([p for p in payments if p.status == "escalated"])
    return {
        "recovery_rate": demo_recovery_rate,
        "monthly_recovery_rate": monthly_recovery_rate,
        "revenue_at_risk": round(total_due, 2),
        "revenue_at_risk_by_tier": {k: round(v, 2) for k, v in revenue_by_tier.items()},
        "active_negotiations": active_negotiations,
        "risk_breakdown": risk_breakdown,
        "health_breakdown": health_breakdown,
        "health_by_gig_type": [
            {"gig_type": gig, "avg_health_score": round(sum(scores) / len(scores), 1)}
            for gig, scores in health_by_gig.items()
        ],
        "commitment_breach_stats": {
            "total_breaches": len(breaches),
            "frozen_cases": len([u for u in user_rows if u["restructuring_frozen"]]),
            "avg_breaches_per_high_risk_user": round(
                sum(u["broken_commitments"] for u in high_risk) / max(len(high_risk), 1), 2
            ),
        },
        "escalated_cases": len([u for u in user_rows if u["status"] == "escalated"]),
        "escalation_queue": escalation_queue,
        "resolution_split": {"ai_resolved": ai_resolved, "human_escalated": human_escalated},
        "avg_health_score": avg_health,
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


@app.get("/worker/{user_id}/notifications")
def worker_notifications(user_id: str):
    with get_session() as session:
        notifications = session.exec(
            select(WorkerNotification).where(WorkerNotification.user_id == user_id).order_by(WorkerNotification.created_at)
        ).all()
    return [_notification_payload(n) for n in notifications]


@app.get("/worker/{user_id}/overview")
def worker_overview(user_id: str):
    with get_session() as session:
        payment = session.exec(select(Payment).where(Payment.user_id == user_id)).first()
        if not payment:
            raise HTTPException(status_code=404, detail="Worker not found")
        health = session.exec(select(FinancialHealthScore).where(FinancialHealthScore.user_id == user_id)).first()
        earnings = session.exec(select(Earning).where(Earning.user_id == user_id).order_by(Earning.date)).all()
        negotiations = session.exec(
            select(Negotiation).where(Negotiation.user_id == user_id).order_by(Negotiation.timestamp)
        ).all()
        breaches = session.exec(
            select(CommitmentBreach).where(CommitmentBreach.user_id == user_id).order_by(CommitmentBreach.breach_number)
        ).all()
        notifications = session.exec(
            select(WorkerNotification).where(WorkerNotification.user_id == user_id).order_by(WorkerNotification.created_at)
        ).all()
    risk = _risk_for_payment(payment)
    return {
        "profile": {
            "user_id": payment.user_id,
            "name": payment.name,
            "gig_type": payment.gig_type,
            "risk_tier": risk["risk_tier"],
        },
        "payment": payment.model_dump(mode="json"),
        "financial_health": {
            "score": health.score,
            "label": health.label,
            "component_scores": json.loads(health.component_scores),
            "insight": health.insight,
            "computed_at": health.computed_at.isoformat(),
        }
        if health
        else None,
        "earnings_last_14_days": [e.model_dump(mode="json") for e in earnings[-14:]],
        "earnings": [e.model_dump(mode="json") for e in earnings],
        "negotiations": [n.model_dump(mode="json") for n in negotiations],
        "commitment_breaches": [b.model_dump(mode="json") for b in breaches],
        "notifications": [_notification_payload(n) for n in notifications],
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
