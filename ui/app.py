import os
from html import escape
from datetime import datetime

import httpx
import pandas as pd
import streamlit as st

API_URL = os.getenv("API_URL", "http://localhost:8000")

st.set_page_config(page_title="Grab Collections Agent", layout="wide")

st.markdown(
    """
    <style>
    .metric-card,
    .chat,
    .alert,
    .plan,
    .support {
        color:#17202a;
        line-height:1.55;
    }
    .metric-card {border:1px solid #d9e2ec;border-radius:8px;padding:14px;background:#ffffff;}
    .chat {border-radius:8px;padding:16px;background:#e9f7ef;border-left:5px solid #00b14f;}
    .alert {border-radius:8px;padding:12px;background:#fdecea;border-left:5px solid #d93025;color:#7a1f17;}
    .plan {border:1px solid #d9e2ec;border-radius:8px;padding:14px;background:#fbfcfd;}
    .installment-row {
        display:flex;
        justify-content:space-between;
        gap:16px;
        border-top:1px solid #e5e7eb;
        padding:10px 0;
    }
    .installment-row:first-of-type {border-top:0;}
    .muted {color:#64748b;font-size:0.92rem;}
    .support {border-radius:8px;padding:14px;background:#fff4db;border-left:5px solid #f59e0b;color:#3d2b00;}
    .chat b,
    .alert b,
    .plan b,
    .support b {color:inherit;}
    </style>
    """,
    unsafe_allow_html=True,
)


def api(method: str, path: str, **kwargs):
    with httpx.Client(timeout=30.0) as client:
        resp = client.request(method, f"{API_URL}{path}", **kwargs)
        resp.raise_for_status()
        return resp.json()


def color_for_label(label: str) -> str:
    return {"Healthy": "green", "Fair": "orange", "At Risk": "orange", "Critical": "red"}.get(label, "gray")


def render_plan(plan: dict) -> None:
    rows = []
    for idx, installment in enumerate(plan.get("installments") or [], start=1):
        rows.append(
            "<div class='installment-row'>"
            f"<div><b>Installment {idx}</b><br><span class='muted'>Due {escape(str(installment.get('due_date', 'n/a')))}</span></div>"
            f"<div><b>SGD {float(installment.get('amount', 0)):.2f}</b></div>"
            "</div>"
        )
    summary = escape(str(plan.get("summary") or ""))
    html = (
        "<div class='plan'>"
        "<b>Repayment plan</b>"
        f"<div class='muted'>{summary}</div>"
        f"{''.join(rows)}"
        f"<div class='installment-row'><div><b>Total</b></div><div><b>SGD {float(plan.get('total_amount', 0)):.2f}</b></div></div>"
        "</div>"
    )
    st.markdown(html, unsafe_allow_html=True)


def refresh():
    st.session_state["users"] = api("GET", "/users")
    st.session_state["dashboard"] = api("GET", "/dashboard")


if "users" not in st.session_state:
    try:
        refresh()
    except Exception as exc:
        st.error(f"API unavailable at {API_URL}: {exc}")
        st.stop()

st.title("AI Collections Agent")

users = st.session_state["users"]
labels = {
    f"{u['name']} ({u['user_id']}) · {str(u['risk_tier']).title()} risk · Health: {u['health_score']}": u
    for u in users
}
selected_label = st.selectbox("Worker", list(labels.keys()))
user = labels[selected_label]
user_id = user["user_id"]

if "active_user" not in st.session_state or st.session_state["active_user"] != user_id:
    st.session_state["active_user"] = user_id
    st.session_state["agent_response"] = None
    st.session_state["state_id"] = None

health = api("GET", f"/user/{user_id}/health-score")
history = api("GET", f"/user/{user_id}/history")

top = st.container()
with top:
    c1, c2, c3, c4 = st.columns([1.2, 1, 1, 1])
    c1.markdown(f"**Gig type**  \n{user['gig_type'].replace('_', ' ').title()}")
    c2.markdown(f"**Overdue**  \nSGD {user['amount_due']:.2f} · {user['days_overdue']} days")
    c3.markdown(f"**Risk tier**  \n{str(user['risk_tier']).title()}")
    c4.markdown(f"**Broken commitments**  \n{user['broken_commitments']}")
    st.progress(int(health["score"]), text=f"Financial Health: {health['score']} · {health['label']}")
    cols = st.columns(5)
    for idx, (name, score) in enumerate(health["component_scores"].items()):
        cols[idx].metric(name.replace("_", " ").title(), score)
    if user["broken_commitments"] > 0:
        st.warning(f"Warning: {user['broken_commitments']} broken commitment(s)")
    if user["restructuring_frozen"]:
        st.error("Autonomous restructuring frozen")

left, right = st.columns([0.9, 1.4])
with left:
    st.subheader("Controls")
    if user["restructuring_frozen"]:
        st.info("Case has been auto-escalated. Run Agent will generate the support briefing.")
    if st.button("Run Agent", type="primary", use_container_width=True):
        try:
            res = api("POST", "/trigger-agent", json={"user_id": user_id})
            st.session_state["agent_response"] = res
            st.session_state["state_id"] = res.get("state_id")
            refresh()
            st.rerun()
        except Exception as exc:
            st.error(f"Agent run failed: {exc}")

    accepted = [n for n in history["negotiations"] if n["user_response"] == "accepted" and n["commitment_kept"] is None]
    latest = accepted[-1] if accepted else None
    if st.button("Simulate missed installment", use_container_width=True, disabled=latest is None):
        try:
            res = api("POST", "/mark-payment-missed", json={"user_id": user_id, "negotiation_id": latest["id"]})
            st.success(res["message"])
            refresh()
            st.rerun()
        except Exception as exc:
            st.error(f"Could not mark missed installment: {exc}")

    res = st.session_state.get("agent_response")
    if res:
        st.caption(f"Nudge scheduled: {res.get('nudge_at') or 'n/a'}")
        st.caption(f"Risk classification: {res.get('risk_tier') or user['risk_tier']}")

with right:
    st.subheader("Conversation")
    res = st.session_state.get("agent_response")
    if res:
        if res["status"] == "escalated":
            st.markdown('<div class="alert"><b>Routed to support team</b></div>', unsafe_allow_html=True)
        if res.get("agent_message"):
            st.markdown(f"<div class='chat'>{escape(res['agent_message'])}</div>", unsafe_allow_html=True)
        plan = res.get("plan")
        if plan and plan.get("installments"):
            render_plan(plan)
        if res["status"] not in ("escalated", "resolved", "in_negotiation"):
            a, b, c = st.columns(3)
            if a.button("Accept", use_container_width=True):
                out = api("POST", "/user-response", json={"state_id": st.session_state["state_id"], "user_response": "accepted"})
                st.session_state["agent_response"] = out
                refresh()
                st.rerun()
            if b.button("Reject", use_container_width=True):
                out = api("POST", "/user-response", json={"state_id": st.session_state["state_id"], "user_response": "rejected"})
                st.session_state["agent_response"] = out
                refresh()
                st.rerun()
            if c.button("Ask Support", use_container_width=True):
                out = api("POST", "/user-response", json={"state_id": st.session_state["state_id"], "user_response": "support_requested"})
                st.session_state["agent_response"] = out
                refresh()
                st.rerun()
        if res["status"] == "in_negotiation":
            st.success("Payment plan confirmed")
        if res.get("escalation_summary"):
            with st.expander("AI-generated escalation summary", expanded=True):
                st.markdown(f"<div class='support'>{escape(res['escalation_summary'])}</div>", unsafe_allow_html=True)
    else:
        st.info("Run the agent to begin the negotiation.")

    with st.expander("Negotiation history", expanded=False):
        if history["negotiations"]:
            st.dataframe(pd.DataFrame(history["negotiations"]), use_container_width=True)
        else:
            st.caption("No negotiation history yet.")
    with st.expander("Commitment breaches", expanded=False):
        if history["commitment_breaches"]:
            st.dataframe(pd.DataFrame(history["commitment_breaches"]), use_container_width=True)
        else:
            st.caption("No breaches recorded.")

st.divider()
st.subheader("Admin Dashboard")
dashboard = st.session_state["dashboard"]
df = pd.DataFrame(dashboard["users"])
st.dataframe(
    df[
        [
            "name",
            "gig_type",
            "health_score",
            "health_label",
            "risk_tier",
            "amount_due",
            "days_overdue",
            "broken_commitments",
            "restructuring_frozen",
            "status",
        ]
    ],
    use_container_width=True,
    hide_index=True,
)
m1, m2, m3 = st.columns(3)
m1.metric("Overall recovery rate", f"{dashboard['recovery_rate'] * 100:.0f}%")
m2.metric("Frozen cases", dashboard["commitment_breach_stats"]["frozen_cases"])
m3.metric("Average health score", f"{df['health_score'].dropna().mean():.0f}")
