import os
from datetime import datetime
from html import escape

import httpx
import pandas as pd
import streamlit as st

API_URL = os.getenv("API_URL", "http://localhost:8000")

st.set_page_config(page_title="Grab Collections Agent", layout="wide")

st.markdown(
    """
    <style>
    .stApp {background:#1f1f1e;color:#f5f5f1;}
    h1,h2,h3,p,span,div,label {letter-spacing:0;}
    .page {max-width:1180px;margin:0 auto;}
    .home-card,.metric-card,.panel,.worker-row,.notification,.timeline-card {
        border:1px solid #3f3f3d;border-radius:8px;background:#282827;
    }
    .home-card {padding:28px;text-align:center;}
    .metric-card {padding:16px;min-height:116px;}
    .metric-label {color:#bbb8b2;font-weight:700;font-size:0.9rem;}
    .metric-value {font-size:1.75rem;font-weight:800;line-height:1.15;color:#fff;}
    .metric-subtle {color:#c7c3bc;font-weight:700;font-size:0.92rem;}
    .metric-good {color:#539b25;font-weight:800;}
    .metric-warn {color:#c42020;font-weight:800;}
    .nav-row {display:flex;gap:8px;margin:18px 0 12px;border-bottom:1px solid #444;padding-bottom:0;}
    .nav-pill {border:1px solid #666;border-radius:8px 8px 0 0;padding:10px 22px;font-weight:800;color:#f6f4ef;}
    .nav-active {background:#30302f;border-bottom-color:#30302f;}
    .panel {padding:16px;margin-top:12px;}
    .worker-row {
        display:grid;grid-template-columns:1.3fr 1fr 1fr .8fr .8fr .8fr 1fr;gap:14px;
        align-items:center;padding:12px;border-top:0;border-left:0;border-right:0;border-radius:0;
    }
    .table-head {color:#bdb9b1;font-size:.85rem;font-weight:800;}
    .worker-name {font-weight:900;color:#fff;}
    .worker-id {color:#999;font-size:.85rem;font-weight:700;}
    .badge {display:inline-block;border-radius:999px;padding:3px 10px;font-weight:900;font-size:.78rem;}
    .badge-low {background:#e5f2d8;color:#2f6417;}
    .badge-medium {background:#fff0cf;color:#805313;}
    .badge-high {background:#ffe2e2;color:#922525;}
    .badge-hardship {background:#f1eadf;color:#574d42;}
    .badge-status {background:#e4f1ff;color:#0f4d86;}
    .badge-escalated {background:#ffe6e6;color:#8b2424;}
    .badge-frozen {background:#ffe5e5;color:#8b2424;border:1px solid #ffb8b8;}
    .health-track {height:7px;background:#333;border-radius:999px;overflow:hidden;display:inline-block;width:64px;margin-right:10px;}
    .health-fill {height:7px;border-radius:999px;}
    .quote {border-left:2px solid #777;padding-left:12px;color:#d1cdc5;font-weight:700;line-height:1.45;}
    .notification {background:#e9f5ff;color:#084d91;border-color:#b9d8f3;padding:16px;margin:10px 0 18px;}
    .notification * {color:inherit;}
    .plan-box {background:rgba(255,255,255,.18);border:1px solid rgba(255,255,255,.22);border-radius:8px;padding:12px;margin:12px 0;}
    .plan-line {display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;padding:8px 0;border-top:1px solid rgba(255,255,255,.18);font-weight:800;}
    .plan-line:first-child {border-top:0;}
    .profile-head {display:flex;align-items:center;gap:14px;margin-bottom:10px;}
    .avatar {height:48px;width:48px;border-radius:50%;display:flex;align-items:center;justify-content:center;background:#dcefff;color:#173b63;font-weight:900;}
    .score-circle {height:78px;width:78px;border-radius:50%;border:8px solid #60a51f;display:flex;align-items:center;justify-content:center;font-size:1.35rem;font-weight:900;}
    .component-row {display:grid;grid-template-columns:1.4fr 1fr 32px;gap:8px;align-items:center;margin:5px 0;}
    .bar-track {height:7px;background:#3a3a38;border-radius:999px;overflow:hidden;}
    .bar-fill {height:7px;background:#61a524;border-radius:999px;}
    .earn-chart {display:flex;gap:8px;align-items:end;height:130px;padding:10px 0;}
    .earn-bar-wrap {flex:1;text-align:center;color:#bbb;font-weight:700;font-size:.8rem;}
    .earn-bar {border-radius:4px 4px 0 0;background:#9ddcc8;min-height:4px;}
    .earn-bar.peak {background:#5d9f1e;}
    .timeline-card {padding:14px;margin:10px 0;display:grid;grid-template-columns:36px 1fr;gap:12px;}
    div[data-testid="stButton"] button {border-radius:8px;font-weight:800;}
    div[data-testid="stDataFrame"] {border:1px solid #3f3f3d;border-radius:8px;}
    </style>
    """,
    unsafe_allow_html=True,
)


def api(method: str, path: str, **kwargs):
    with httpx.Client(timeout=45.0) as client:
        resp = client.request(method, f"{API_URL}{path}", **kwargs)
        resp.raise_for_status()
        return resp.json()


def money(value: float) -> str:
    return f"${float(value):,.0f}"


def sgd(value: float) -> str:
    return f"SGD {float(value):,.2f}"


def risk_class(risk: str) -> str:
    return {
        "low": "badge-low",
        "medium": "badge-medium",
        "high": "badge-high",
        "hardship": "badge-hardship",
    }.get(str(risk).lower(), "badge-hardship")


def health_color(score: int) -> str:
    if score >= 76:
        return "#62a521"
    if score >= 51:
        return "#f5a623"
    if score >= 26:
        return "#f28b2e"
    return "#ef5350"


def fmt_date(value: str) -> str:
    try:
        return datetime.fromisoformat(value.replace("Z", "")).strftime("%d %b %Y")
    except Exception:
        return value


def refresh_admin():
    st.session_state["users"] = api("GET", "/users")
    st.session_state["dashboard"] = api("GET", "/dashboard")


def render_metric(label: str, value: str, subtitle: str = "", tone: str = ""):
    tone_class = "metric-good" if tone == "good" else "metric-warn" if tone == "warn" else "metric-subtle"
    st.markdown(
        f"""
        <div class="metric-card">
          <div class="metric-label">{escape(label)}</div>
          <div class="metric-value">{escape(value)}</div>
          <div class="{tone_class}">{escape(subtitle)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def set_role(role: str):
    st.session_state["role"] = role
    st.rerun()


def render_home():
    st.markdown('<div class="page">', unsafe_allow_html=True)
    st.title("Grab Collections Agent")
    st.caption("Choose how you want to enter the demo.")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown('<div class="home-card"><h3>Admin dashboard</h3><p>Portfolio, escalations, worker records, and agent triggers.</p></div>', unsafe_allow_html=True)
        if st.button("Enter as admin", type="primary", use_container_width=True):
            set_role("admin")
    with c2:
        st.markdown('<div class="home-card"><h3>Worker view</h3><p>Notification, payment plan, health score, earnings, and history.</p></div>', unsafe_allow_html=True)
        if st.button("Enter as worker", use_container_width=True):
            set_role("worker")
    st.markdown("</div>", unsafe_allow_html=True)


def render_admin_nav(active: str):
    c1, c2, c3, _ = st.columns([1.1, 1.25, 1.15, 3])
    if c1.button("All workers", type="primary" if active == "workers" else "secondary", use_container_width=True):
        st.session_state["admin_tab"] = "workers"
        st.rerun()
    if c2.button("Escalated cases", type="primary" if active == "escalated" else "secondary", use_container_width=True):
        st.session_state["admin_tab"] = "escalated"
        st.rerun()
    if c3.button("Trigger agent", type="primary" if active == "trigger" else "secondary", use_container_width=True):
        st.session_state["admin_tab"] = "trigger"
        st.rerun()


def render_admin_metrics(dashboard: dict):
    cols = st.columns(5)
    with cols[0]:
        render_metric("Recovery rate", f"{dashboard['recovery_rate'] * 100:.0f}%", "+8% vs last month", "good")
    with cols[1]:
        render_metric("Revenue at risk", money(dashboard["revenue_at_risk"]), f"across {len(dashboard['users'])} workers")
    with cols[2]:
        render_metric("Escalated cases", str(dashboard["escalated_cases"]), "needs review", "warn")
    with cols[3]:
        render_metric("Frozen cases", str(dashboard["commitment_breach_stats"]["frozen_cases"]), "auto-restructuring off", "warn")
    with cols[4]:
        render_metric("Avg health score", str(dashboard["avg_health_score"]), "Fair overall")


def render_worker_table(users: list[dict]):
    st.markdown('<div class="panel" style="padding:0;overflow:hidden;">', unsafe_allow_html=True)
    st.markdown(
        """
        <div class="worker-row table-head">
          <div>Worker</div><div>Gig type</div><div>Health score</div><div>Risk tier</div>
          <div>Amount due</div><div>Days OD</div><div>Status</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    for user in users:
        score = int(user.get("health_score") or 0)
        risk = str(user.get("risk_tier") or "unknown").title()
        status = str(user.get("status") or "").replace("_", " ").title()
        status_class = "badge-escalated" if status.lower() == "escalated" else "badge-status"
        breach = user.get("broken_commitments") or 0
        breach_text = f" · {breach} breach{'es' if breach != 1 else ''}" if breach else ""
        st.markdown(
            f"""
            <div class="worker-row">
              <div><div class="worker-name">{escape(user['name'])}</div><div class="worker-id">{escape(user['user_id'])}</div></div>
              <div><b>{escape(user['gig_type'].replace('_', '-').title())}</b></div>
              <div><span class="health-track"><span class="health-fill" style="width:{score}%;background:{health_color(score)}"></span></span><b>{score}</b></div>
              <div><span class="badge {risk_class(user.get('risk_tier'))}">{escape(risk)}</span></div>
              <div><b>{money(user['amount_due'])}</b></div>
              <div><b>{int(user['days_overdue'])}</b>{escape(breach_text)}</div>
              <div><span class="badge {status_class}">{escape(status)}</span></div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)


def render_escalations(dashboard: dict):
    queue = dashboard.get("escalation_queue") or []
    if not queue:
        st.info("No escalated cases in queue.")
        return
    for case in queue:
        frozen = '<span class="badge badge-frozen">Frozen</span>' if case.get("restructuring_frozen") else ""
        st.markdown(
            f"""
            <div class="panel">
              <div style="display:flex;justify-content:space-between;gap:12px;">
                <div>
                  <b style="font-size:1.05rem;">{escape(case['name'])}</b>
                  <span class="badge {risk_class(case['risk_tier'])}">{escape(str(case['risk_tier']).title())}</span>
                  <span class="badge badge-medium">{int(case['broken_commitments'])} breaches</span>
                  {frozen}
                  <div class="metric-subtle">{escape(case['user_id'])} · {money(case['amount_due'])} · {int(case['days_overdue'])} days overdue · {escape(case['gig_type'].replace('_','-').title())}</div>
                </div>
                <span class="badge badge-escalated">Escalated</span>
              </div>
              <div class="quote">{escape(case['summary'])}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_trigger_agent(users: list[dict]):
    st.markdown(
        '<p class="metric-subtle">Manually trigger the agent for a specific worker. This fires the graph and delivers a notification to their view.</p>',
        unsafe_allow_html=True,
    )
    labels = {
        f"{u['user_id']} - {u['name']} ({str(u['risk_tier']).title()} risk)": u["user_id"]
        for u in users
    }
    c1, c2 = st.columns([4, 1.1])
    selected = c1.selectbox("Worker", labels.keys(), label_visibility="collapsed")
    if c2.button("Trigger agent", type="primary", use_container_width=True, key="trigger_agent_btn"):
        result = api("POST", "/notifications/send", json={"user_id": labels[selected]})
        st.session_state["last_trigger"] = result
        refresh_admin()
        st.success(f"Notification delivered to {labels[selected]}")
    if st.session_state.get("last_trigger"):
        notification = st.session_state["last_trigger"]["notification"]
        st.markdown(
            f"""
            <div class="panel">
              <b>Last triggered:</b> {escape(notification['user_id'])} ·
              {fmt_date(notification['created_at'])} · Status: notification delivered
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_admin():
    refresh_admin()
    dashboard = st.session_state["dashboard"]
    users = dashboard["users"]
    st.markdown('<div class="page">', unsafe_allow_html=True)
    left, right = st.columns([5, 1])
    left.title("Admin dashboard")
    if right.button("Switch role", use_container_width=True):
        st.session_state.pop("role", None)
        st.rerun()
    render_admin_metrics(dashboard)
    active = st.session_state.get("admin_tab", "workers")
    render_admin_nav(active)

    if active == "workers":
        render_worker_table(users)
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Health score distribution")
            st.bar_chart(pd.DataFrame([dashboard["health_breakdown"]]).T.rename(columns={0: "workers"}))
        with c2:
            st.subheader("Health score by gig type")
            st.bar_chart(pd.DataFrame(dashboard["health_by_gig_type"]).set_index("gig_type"))
    elif active == "escalated":
        render_escalations(dashboard)
    else:
        render_trigger_agent(users)
    st.markdown("</div>", unsafe_allow_html=True)


def notification_actions(notification: dict):
    status = notification.get("status")
    if status in {"accepted", "escalated"}:
        st.caption(f"Notification status: {status.replace('_', ' ').title()}")
        return
    c1, c2, c3 = st.columns([1, 1.55, 1.15])
    if c1.button("Accept plan", use_container_width=True, key=f"accept_{notification['id']}"):
        api("POST", "/worker/notification-response", json={"notification_id": notification["id"], "user_response": "accepted"})
        st.rerun()
    if c2.button("Suggest different plan", use_container_width=True, key=f"reject_{notification['id']}"):
        api("POST", "/worker/notification-response", json={"notification_id": notification["id"], "user_response": "rejected"})
        st.rerun()
    if c3.button("Talk to support", use_container_width=True, key=f"support_{notification['id']}"):
        api("POST", "/worker/notification-response", json={"notification_id": notification["id"], "user_response": "support_requested"})
        st.rerun()


def render_notification(notification: dict | None):
    if not notification:
        st.markdown('<div class="notification"><b>No active message from Grab</b><br>You have no repayment notification right now.</div>', unsafe_allow_html=True)
        return
    plan = notification.get("repayment_plan") or {}
    lines = []
    for idx, item in enumerate(plan.get("installments") or [], start=1):
        lines.append(
            f"<div class='plan-line'><div>Installment {idx}</div><div>{sgd(item.get('amount', 0))}</div><div>{fmt_date(str(item.get('due_date', '')))}</div></div>"
        )
    plan_html = (
        f"<div class='plan-box'><b>Repayment plan offered</b>{''.join(lines)}</div>"
        if lines
        else ""
    )
    st.markdown(
        f"""
        <div class="notification">
          <b>New message from Grab</b><br>
          {escape(notification.get('message') or '')}
          {plan_html}
        </div>
        """,
        unsafe_allow_html=True,
    )
    notification_actions(notification)


def render_health_card(health: dict):
    score = int(health["score"])
    comps = health["component_scores"]
    rows = []
    for name, value in comps.items():
        rows.append(f"""
<div class="component-row">
  <div>{escape(name.replace('_', ' ').title())}</div>
  <div class="bar-track">
    <div class="bar-fill"
         style="width:{int(value)}%; background:{health_color(int(value))}">
    </div>
  </div>
  <div>{int(value)}</div>
</div>
""")
    st.markdown(
        f"""
<div class="panel">
    <div class="metric-label">FINANCIAL HEALTH</div>
    <div style="display:flex;gap:18px;align-items:center;margin:10px 0;">
    <div class="score-circle">{score}</div>
    <div><b style="font-size:1.1rem;">{escape(health['label'])}</b><br><span class="metric-subtle">Above average for your gig type</span></div>
    </div>
    {''.join(rows)}
</div>
""",
unsafe_allow_html=True,
)


def render_earnings_chart(earnings: list[dict]):
    if not earnings:
        st.info("No earnings data.")
        return
    max_amount = max(float(e["amount"]) for e in earnings) or 1
    bars = []
    for e in earnings:
        day = datetime.fromisoformat(e["date"]).strftime("%a")[0]
        amount = float(e["amount"])
        is_peak = amount >= max_amount * 0.75
        bars.append(
            f"<div class='earn-bar-wrap'><div class='earn-bar {'peak' if is_peak else ''}' style='height:{max(4, amount / max_amount * 98):.0f}px'></div><div>{day}</div></div>"
        )
    avg_peak = sum(float(e["amount"]) for e in earnings) / len(earnings)
    st.markdown(
        f"""
        <div class="panel">
          <div class="metric-label">EARNINGS - LAST 14 DAYS</div>
          <div class="earn-chart">{''.join(bars)}</div>
          <div class="metric-subtle">Average daily earnings: {sgd(avg_peak)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_worker_history(overview: dict):
    notifications = overview["notifications"]
    negotiations = overview["negotiations"]
    if notifications:
        for n in reversed(notifications[-4:]):
            st.markdown(
                f"""
                <div class="timeline-card">
                  <div class="avatar" style="height:32px;width:32px;">G</div>
                  <div><b>{fmt_date(n['created_at'])} · Agent message</b><br>{escape(n.get('message') or '')}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
    if negotiations:
        st.dataframe(pd.DataFrame(negotiations), use_container_width=True, hide_index=True)


def render_worker():
    users = api("GET", "/users")
    labels = {f"{u['name']} ({u['user_id']})": u["user_id"] for u in users}
    st.markdown('<div class="page">', unsafe_allow_html=True)
    top_l, top_r = st.columns([4, 1])
    selected = top_l.selectbox("Worker authentication", labels.keys())
    if top_r.button("Switch role", use_container_width=True):
        st.session_state.pop("role", None)
        st.rerun()
    user_id = labels[selected]
    overview = api("GET", f"/worker/{user_id}/overview")
    profile = overview["profile"]
    payment = overview["payment"]
    health = overview["financial_health"]
    notifications = overview["notifications"]
    latest_notification = notifications[-1] if notifications else None

    initials = "".join(part[0] for part in profile["name"].split()[:2]).upper()
    st.markdown(
        f"""
        <div class="profile-head">
          <div class="avatar">{escape(initials)}</div>
          <div><b style="font-size:1.25rem;">{escape(profile['name'])}</b><br><span class="metric-subtle">{escape(profile['user_id'])} · {escape(profile['gig_type'].replace('_','-').title())}</span></div>
          <div style="margin-left:auto;"><span class="badge {risk_class(profile['risk_tier'])}">{escape(str(profile['risk_tier']).title())} risk</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    render_notification(latest_notification)

    tabs = st.tabs(["Overview", "Earnings", "History"])
    with tabs[0]:
        c1, c2 = st.columns([1, 2.2])
        with c1:
            render_health_card(health)
        with c2:
            st.markdown(
                f"""
                <div class="panel">
                  <div class="metric-label">CURRENT BALANCE</div>
                  <div class="metric-value">{sgd(payment['amount_due'])} <span class="metric-warn" style="font-size:1rem;">overdue</span></div>
                  <div class="plan-line"><div>Due date</div><div></div><div>{fmt_date(payment['due_date'])}</div></div>
                  <div class="plan-line"><div>Days overdue</div><div></div><div>{int(payment['days_overdue'])} days</div></div>
                  <div class="plan-line"><div>Plan status</div><div></div><div>{escape(str(latest_notification.get('status','No offer') if latest_notification else 'No offer').replace('_',' ').title())}</div></div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            render_earnings_chart(overview["earnings_last_14_days"])
    with tabs[1]:
        render_earnings_chart(overview["earnings_last_14_days"])
        st.dataframe(pd.DataFrame(overview["earnings"]), use_container_width=True, hide_index=True)
    with tabs[2]:
        render_worker_history(overview)
        if overview["commitment_breaches"]:
            st.subheader("Commitment breaches")
            st.dataframe(pd.DataFrame(overview["commitment_breaches"]), use_container_width=True, hide_index=True)
    st.markdown("</div>", unsafe_allow_html=True)


try:
    if "role" not in st.session_state:
        render_home()
    elif st.session_state["role"] == "admin":
        render_admin()
    else:
        render_worker()
except httpx.HTTPError as exc:
    st.error(f"API unavailable at {API_URL}: {exc}")
