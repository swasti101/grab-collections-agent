import json
import os
import re
from datetime import datetime
from html import escape

import httpx
import pandas as pd
import streamlit as st

API_URL = os.getenv("API_URL", "http://localhost:8000")

WORKER_LOCALES = {
    "GW007": "ms",
    "GW003": "hi",
}

LANGUAGE_OPTIONS = [
    ("en", "English"),
    ("ms", "Bahasa Melayu"),
    ("hi", "Hindi"),
    ("my", "Burmese"),
    ("th", "Thai"),
    ("zh", "Mandarin"),
]

I18N = {
    "en": {
        "no_active_title": "No active message from Grab",
        "no_active_body": "You have no repayment notification right now.",
        "new_message": "New message from Grab",
        "plan_offered": "Repayment plan offered",
        "installment": "Installment",
        "accept_plan": "Accept plan",
        "suggest_plan": "Suggest different plan",
        "talk_support": "Talk to support",
        "notification_status": "Notification status",
        "worker_auth": "Worker authentication",
        "language_pref": "Language preference",
        "switch_role": "Switch role",
        "overview": "Overview",
        "earnings": "Earnings",
        "history": "History",
        "support_review": "Your case is being reviewed by our support team, who will contact you shortly.",
        "agent_message": "Agent message",
        "support_checkin": "Support check-in",
    },
    "ms": {
        "no_active_title": "Tiada mesej aktif daripada Grab",
        "no_active_body": "Anda tiada notifikasi bayaran balik buat masa ini.",
        "new_message": "Mesej baharu daripada Grab",
        "plan_offered": "Pelan bayaran balik ditawarkan",
        "installment": "Ansuran",
        "accept_plan": "Terima pelan",
        "suggest_plan": "Cadangkan pelan lain",
        "talk_support": "Hubungi sokongan",
        "notification_status": "Status notifikasi",
        "worker_auth": "Pengesahan pekerja",
        "language_pref": "Pilihan bahasa",
        "switch_role": "Tukar peranan",
        "overview": "Gambaran keseluruhan",
        "earnings": "Pendapatan",
        "history": "Sejarah",
        "support_review": "Kes anda sedang disemak oleh pasukan sokongan kami dan mereka akan menghubungi anda tidak lama lagi.",
        "agent_message": "Mesej ejen",
        "support_checkin": "Semakan sokongan",
    },
    "hi": {
        "no_active_title": "Grab से कोई सक्रिय संदेश नहीं है",
        "no_active_body": "अभी आपके पास कोई पुनर्भुगतान सूचना नहीं है।",
        "new_message": "Grab का नया संदेश",
        "plan_offered": "प्रस्तावित पुनर्भुगतान योजना",
        "installment": "किस्त",
        "accept_plan": "योजना स्वीकार करें",
        "suggest_plan": "दूसरी योजना सुझाएं",
        "talk_support": "सहायता से बात करें",
        "notification_status": "सूचना की स्थिति",
        "worker_auth": "वर्कर प्रमाणीकरण",
        "switch_role": "भूमिका बदलें",
        "overview": "ओवरव्यू",
        "earnings": "कमाई",
        "history": "इतिहास",
        "support_review": "आपका मामला हमारी सहायता टीम देख रही है और वे जल्द ही आपसे संपर्क करेंगे।",
        "agent_message": "एजेंट संदेश",
        "support_checkin": "सहायता जाँच",
    },
}

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
    .badge-frozen {background:#eef0ff;color:#4b4e9e;border:1px solid #c8ccff;}
    .health-track {height:7px;background:#333;border-radius:999px;overflow:hidden;display:inline-block;width:64px;margin-right:10px;}
    .health-fill {height:7px;border-radius:999px;}
    .quote {border-left:2px solid #777;padding-left:12px;color:#d1cdc5;font-weight:700;line-height:1.45;}
    .notification {padding:16px;margin:10px 0 18px;}
    .notification * {color:inherit;}
    .notification-collection {background:#e9f5ff;color:#084d91;border-color:#b9d8f3;}
    .notification-proactive {background:#f3eee3;color:#59442a;border-color:#cdbb98;}
    .notification-proactive .subtle {color:#7a6247;font-weight:800;font-size:.85rem;letter-spacing:.02em;text-transform:uppercase;}
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
    .escalation-section-title {
        color:#bdb9b1;font-size:.88rem;font-weight:900;letter-spacing:.02em;margin:6px 0 10px;
    }
    .escalation-card {padding:16px;margin-bottom:12px;}
    .escalation-topline {
        display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:10px;
    }
    .escalation-meta {color:#c7c3bc;font-weight:800;margin-top:8px;line-height:1.45;}
    .escalation-summary {border-left:2px solid #555;padding-left:12px;color:#d1cdc5;font-weight:700;line-height:1.45;margin:12px 0 14px;}
    .modal-grid {display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:10px 0 14px;}
    .modal-stat {background:#282827;border:1px solid #3f3f3d;border-radius:8px;padding:12px;}
    .modal-stat-label {color:#bdb9b1;font-size:.85rem;font-weight:800;}
    .modal-stat-value {color:#fff;font-size:1.15rem;font-weight:900;line-height:1.2;}
    .modal-note {background:#282827;border:1px solid #3f3f3d;border-radius:8px;padding:14px;color:#e0ddd6;font-weight:700;line-height:1.5;}
    .drift-card {padding:16px;margin-bottom:14px;}
    .drift-top {display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:12px;}
    .drift-box {border:1px solid #484845;border-radius:10px;background:#222220;padding:14px 16px;margin:12px 0;color:#f1efe9;font-family:Consolas, monospace;}
    .drift-line {margin:4px 0;font-size:.95rem;}
    .drift-preview {border-left:3px solid #8e846a;padding-left:12px;color:#ddd7cb;font-style:italic;font-size:1.03rem;line-height:1.5;margin:14px 0;}
    .drift-meta {color:#c7c3bc;font-weight:800;line-height:1.45;}
    .pill-proactive {display:inline-block;border-radius:999px;padding:3px 10px;font-weight:900;font-size:.78rem;background:#f3eee3;color:#59442a;border:1px solid #cdbb98;}
    .trace-card {padding:14px 16px;margin:10px 0;}
    .trace-title {font-size:1rem;font-weight:900;color:#fff;margin-bottom:6px;}
    .trace-meta {color:#c7c3bc;font-weight:800;font-size:.84rem;margin-bottom:10px;}
    .trace-list {margin:0;padding-left:18px;color:#e7e3db;line-height:1.5;}
    .trace-result {border-left:2px solid #6f6b62;padding-left:12px;color:#f5f2ec;font-weight:700;line-height:1.5;margin-top:12px;}
    .review-card {padding:16px;margin-top:14px;}
    .review-label {color:#bdb9b1;font-size:.84rem;font-weight:900;letter-spacing:.03em;}
    .flow-shell {margin:12px 0 18px;}
    .flow-title {color:#bdb9b1;font-size:.84rem;font-weight:900;letter-spacing:.03em;margin-bottom:10px;}
    .flow-track {display:flex;align-items:stretch;gap:10px;flex-wrap:wrap;}
    .flow-node {min-width:220px;max-width:280px;flex:1 1 220px;border:1px solid #4a4a47;border-radius:10px;background:#262624;padding:12px;}
    .flow-node.flow-active {border-color:#d3c08b;background:#2f2c24;}
    .flow-step {color:#bdb9b1;font-size:.78rem;font-weight:900;letter-spacing:.03em;margin-bottom:6px;}
    .flow-name {color:#fff;font-size:.95rem;font-weight:900;line-height:1.35;margin-bottom:8px;}
    .flow-tools {color:#d4cebe;font-size:.8rem;font-weight:800;line-height:1.4;margin-bottom:8px;}
    .flow-result {color:#ece7dc;font-size:.82rem;line-height:1.45;}
    .flow-arrow {display:flex;align-items:center;justify-content:center;color:#978d79;font-size:1.2rem;font-weight:900;min-width:26px;}
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


def stream_api_events(method: str, path: str, **kwargs):
    timeout = kwargs.pop("timeout", None)
    with httpx.Client(timeout=timeout) as client:
        with client.stream(method, f"{API_URL}{path}", **kwargs) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                yield json.loads(line)


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


def notification_type(notification: dict | None) -> str:
    if not notification:
        return "collections"
    kind = str(notification.get("notification_type") or "")
    if kind:
        return kind
    status = str(notification.get("status") or "")
    return "proactive_checkin" if status.startswith("proactive_") else "collections"


def fmt_date(value: str) -> str:
    try:
        return datetime.fromisoformat(value.replace("Z", "")).strftime("%d %b %Y")
    except Exception:
        return value


def plain_text(value: str) -> str:
    if not value:
        return ""
    text = str(value)
    text = text.replace("\r", " ").replace("\n", " ")
    text = text.replace("<br>", " ").replace("<br/>", " ").replace("<br />", " ")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def worker_locale(user_id: str) -> str:
    selected = st.session_state.get("worker_language_preferences", {}).get(user_id)
    if selected:
        return selected
    return WORKER_LOCALES.get(user_id, "en")


def t(user_id: str, key: str) -> str:
    locale = worker_locale(user_id)
    return I18N.get(locale, I18N["en"]).get(key, I18N["en"].get(key, key))


def localized_collection_message(user_id: str, notification: dict, message: str) -> str:
    locale = worker_locale(user_id)
    if locale == "en":
        return message

    plan = notification.get("repayment_plan") or {}
    installments = plan.get("installments") or []
    total_amount = float(plan.get("total_amount") or 0)

    if locale == "ms":
        if installments:
            plan_text = ", ".join(
                f"SGD {float(item.get('amount', 0)):.2f} pada {fmt_date(str(item.get('due_date', '')))}"
                for item in installments
            )
            return (
                f"Hai {notification.get('user_id')}, baki tertunggak anda ialah SGD {total_amount:.2f}. "
                f"Berdasarkan corak pendapatan anda, kami telah menyusun pelan ini mengikut hari pendapatan anda yang lebih kukuh. "
                f"Cadangan pelan ialah {plan_text}. Sila sahkan jika pelan ini sesuai untuk anda."
            )
        return t(user_id, "support_review")

    if locale == "hi":
        if installments:
            plan_text = ", ".join(
                f"SGD {float(item.get('amount', 0)):.2f} दिनांक {fmt_date(str(item.get('due_date', '')))}"
                for item in installments
            )
            return (
                f"नमस्ते {notification.get('user_id')}, आपकी बकाया राशि SGD {total_amount:.2f} है। "
                f"आपकी हाल की कमाई के पैटर्न के आधार पर हमने यह योजना आपके मजबूत कमाई वाले दिनों के अनुसार बनाई है। "
                f"प्रस्तावित योजना है {plan_text}। कृपया बताएं कि क्या यह योजना आपके लिए ठीक है।"
            )
        return t(user_id, "support_review")

    if locale == "my":
        if installments:
            plan_text = ", ".join(
                f"SGD {float(item.get('amount', 0)):.2f} ကို {fmt_date(str(item.get('due_date', '')))} တွင်"
                for item in installments
            )
            return (
                f"မင်္ဂလာပါ {notification.get('user_id')}၊ သင်၏ကျန်ငွေပမာဏမှာ SGD {total_amount:.2f} ဖြစ်သည်။ "
                f"သင်၏ဝင်ငွေပုံစံအရ ကျွန်ုပ်တို့သည် အားကောင်းသောဝင်ငွေရက်များနှင့်ကိုက်ညီအောင် ဤအစီအစဉ်ကိုပြုလုပ်ထားပါသည်။ "
                f"အဆိုပြုအစီအစဉ်မှာ {plan_text} ဖြစ်ပါသည်။ ဤအစီအစဉ်က သင့်အတွက်အဆင်ပြေမပြေ အတည်ပြုပေးပါ။"
            )
        return "သင်၏ကိစ္စကို ကျွန်ုပ်တို့၏ပံ့ပိုးမှုအဖွဲ့က စစ်ဆေးနေပြီး မကြာမီ သင့်ကို ဆက်သွယ်ပါမည်။"

    if locale == "th":
        if installments:
            plan_text = ", ".join(
                f"SGD {float(item.get('amount', 0)):.2f} วันที่ {fmt_date(str(item.get('due_date', '')))}"
                for item in installments
            )
            return (
                f"สวัสดี {notification.get('user_id')} ยอดค้างชำระของคุณคือ SGD {total_amount:.2f} "
                f"จากรูปแบบรายได้ล่าสุดของคุณ เราได้จัดแผนนี้ให้สอดคล้องกับวันที่คุณมีรายได้ดีกว่า "
                f"แผนที่เสนอคือ {plan_text} กรุณายืนยันว่าแผนนี้เหมาะกับคุณหรือไม่"
            )
        return "ทีมสนับสนุนของเรากำลังตรวจสอบกรณีของคุณและจะติดต่อคุณในไม่ช้า"

    if locale == "zh":
        if installments:
            plan_text = "，".join(
                f"SGD {float(item.get('amount', 0)):.2f}，日期 {fmt_date(str(item.get('due_date', '')))}"
                for item in installments
            )
            return (
                f"您好 {notification.get('user_id')}，您的逾期金额为 SGD {total_amount:.2f}。"
                f"根据您最近的收入模式，我们已按您较强的收入日期安排此计划。"
                f"建议方案为 {plan_text}。请确认这是否适合您。"
            )
        return "您的个案正在由我们的客服团队审核，他们会尽快联系您。"

    return message


def payment_timing_text(payment: dict) -> tuple[str, str]:
    due_raw = str(payment.get("due_date") or "")
    try:
        due_date = datetime.fromisoformat(due_raw).date()
        today = datetime.now().date()
        delta = (due_date - today).days
        if delta > 0:
            return "Due date", f"{fmt_date(due_raw)} ({delta} days away)"
        if delta == 0:
            return "Due date", f"{fmt_date(due_raw)} (today)"
    except Exception:
        pass
    overdue_days = int(payment.get("days_overdue") or 0)
    if overdue_days > 0:
        return "Days overdue", f"{overdue_days} days"
    return "Due date", fmt_date(due_raw)


def notification_status_label(notification: dict | None) -> str:
    if not notification:
        return "No active message"
    if notification_type(notification) == "proactive_checkin":
        return str(notification.get("status", "proactive_unread")).replace("proactive_", "").replace("_", " ").title()
    return str(notification.get("status", "No offer")).replace("_", " ").title()


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


def _short_result(value: str, limit: int = 120) -> str:
    text = plain_text(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def flow_arrows_html(trace_steps: list[dict], active_step_number: int | None = None) -> str:
    items = []
    for index, step in enumerate(trace_steps):
        step_number = int(step.get("step_number", index + 1))
        tools = ", ".join(step.get("tools_called") or ["No explicit tool"])
        node_class = "flow-node flow-active" if active_step_number == step_number else "flow-node"
        items.append(
            f"""
            <div class="{node_class}">
              <div class="flow-step">STEP {step_number}</div>
              <div class="flow-name">{escape(step.get('title', 'Step'))}</div>
              <div class="flow-tools">Tools: {escape(tools)}</div>
              <div class="flow-result">{escape(_short_result(step.get('result', '')))}</div>
            </div>
            """
        )
        if index < len(trace_steps) - 1:
            items.append('<div class="flow-arrow">-&gt;</div>')
    return f"""
    <div class="flow-shell">
      <div class="flow-title">FLOW OF ANALYSIS</div>
      <div class="flow-track">{''.join(items)}</div>
    </div>
    """


def render_flow_arrows(trace_steps: list[dict], active_step_number: int | None = None):
    if not trace_steps:
        return
    st.markdown(flow_arrows_html(trace_steps, active_step_number=active_step_number), unsafe_allow_html=True)


def render_trace_flow(title: str, trace_steps: list[dict], key_prefix: str):
    with st.status(title, expanded=True) as status:
        for step in trace_steps:
            status.write(f"Step {step.get('step_number', '?')}: {step.get('title', 'Step completed')}")
        status.update(label=f"{title} complete", state="complete")

    render_flow_arrows(trace_steps)

    for step in trace_steps:
        tools = ", ".join(step.get("tools_called") or ["No explicit tool"])
        analysis = "".join(f"<li>{escape(item)}</li>" for item in step.get("analysis") or [])
        st.markdown(
            f"""
            <div class="panel trace-card">
              <div class="trace-title">Step {int(step.get('step_number', 0))}: {escape(step.get('title', 'Step'))}</div>
              <div class="trace-meta">LangGraph node: {escape(step.get('langgraph_node', 'n/a'))} | Tools: {escape(tools)}</div>
              <ul class="trace-list">{analysis}</ul>
              <div class="trace-result">{escape(plain_text(step.get('result', '')))}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_admin_notification_preview(preview: dict, heading: str):
    notification = preview.get("notification_preview") or preview
    plan = notification.get("repayment_plan") or {}
    lines = []
    for idx, item in enumerate(plan.get("installments") or [], start=1):
        lines.append(
            f"<div class='plan-line'><div>Installment {idx}</div><div>{sgd(item.get('amount', 0))}</div><div>{fmt_date(str(item.get('due_date', '')))}</div></div>"
        )
    plan_html = (
        f"<div class='plan-box'><b>Plan that will be sent</b>{''.join(lines)}</div>"
        if lines
        else ""
    )
    kind = notification.get("notification_type", "collections")
    css_class = "notification-proactive" if kind == "proactive_checkin" else "notification-collection"
    title = "Proactive check-in preview" if kind == "proactive_checkin" else heading
    st.markdown(
        f"""
        <div class="panel review-card">
          <div class="review-label">REVIEW BEFORE SEND</div>
          <div class="notification {css_class}" style="margin-bottom:0;">
            <b>{escape(title)}</b><br>
            {escape(notification.get('message') or '')}
            {plan_html}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def run_agent_preview_live(user_id: str):
    live_status = st.status("Running collections agent preview", expanded=True)
    current_step = st.empty()
    flow_placeholder = st.empty()
    trace_steps: list[dict] = []
    preview = None
    try:
        for event in stream_api_events("POST", "/agent-preview/stream", json={"user_id": user_id}, timeout=None):
            if event.get("event") == "started":
                live_status.write(f"Starting LangGraph run for {user_id}.")
                current_step.info("Agent starting.")
            elif event.get("event") == "step":
                step = event["step"]
                trace_steps.append(step)
                live_status.write(f"Step {step['step_number']}: {step['title']}")
                current_step.info(f"Currently running: {step['title']}")
                flow_placeholder.markdown(
                    flow_arrows_html(trace_steps, active_step_number=step["step_number"]),
                    unsafe_allow_html=True,
                )
            elif event.get("event") == "completed":
                preview = event.get("preview")
        live_status.update(label="Collections preview complete", state="complete")
        current_step.success("Agent run complete. Review the draft below before sending.")
        if trace_steps:
            flow_placeholder.markdown(flow_arrows_html(trace_steps), unsafe_allow_html=True)
        return preview
    except httpx.HTTPError as exc:
        live_status.update(label="Collections preview failed", state="error")
        current_step.error(f"Preview failed: {exc}")
        raise


def run_drift_scan_live():
    live_status = st.status("Running drift scan", expanded=True)
    current_step = st.empty()
    flow_placeholder = st.empty()
    scan = None
    trace_steps: list[dict] = []
    try:
        for event in stream_api_events("GET", "/drift-scan/stream", timeout=None):
            if event.get("event") == "started":
                live_status.write("Starting portfolio-wide drift scan.")
                current_step.info("Loading worker portfolio.")
            elif event.get("event") == "step":
                step = event["step"]
                trace_steps.append(step)
                live_status.write(f"Step {step['step_number']}: {step['title']}")
                current_step.info(f"Currently running: {step['title']}")
                flow_placeholder.markdown(
                    flow_arrows_html(trace_steps, active_step_number=step["step_number"]),
                    unsafe_allow_html=True,
                )
            elif event.get("event") == "worker_progress":
                live_status.write(event.get("message", "Analyzing worker"))
                current_step.info(event.get("message", "Analyzing worker"))
            elif event.get("event") == "worker_result":
                status_text = "drifting" if event.get("drifting") else "stable"
                live_status.write(
                    f"{event.get('worker_id')}: drift score {float(event.get('drift_score') or 0):.2f} ({status_text})"
                )
            elif event.get("event") == "completed":
                scan = event.get("scan")
        live_status.update(label="Drift scan complete", state="complete")
        current_step.success("Drift scan complete. Review the candidates below before sending any check-in.")
        if trace_steps:
            flow_placeholder.markdown(flow_arrows_html(trace_steps), unsafe_allow_html=True)
        return scan
    except httpx.HTTPError as exc:
        live_status.update(label="Drift scan failed", state="error")
        current_step.error(f"Drift scan failed: {exc}")
        raise


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
    c1, c2, c3, c4, _ = st.columns([1.05, 1.2, 1.05, 1.2, 2.5])
    if c1.button("All workers", type="primary" if active == "workers" else "secondary", use_container_width=True):
        st.session_state["admin_tab"] = "workers"
        st.rerun()
    if c2.button("Escalated cases", type="primary" if active == "escalated" else "secondary", use_container_width=True):
        st.session_state["admin_tab"] = "escalated"
        st.rerun()
    if c3.button("Drift scanner", type="primary" if active == "drift" else "secondary", use_container_width=True):
        st.session_state["admin_tab"] = "drift"
        st.rerun()
    if c4.button("Trigger agent", type="primary" if active == "trigger" else "secondary", use_container_width=True):
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
        breach_text = f" | {breach} breach{'es' if breach != 1 else ''}" if breach else ""
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


def render_escalation_detail(user_id: str, source: str | None = None):
    overview = api("GET", f"/worker/{user_id}/overview")
    profile = overview["profile"]
    payment = overview["payment"]
    financial_health = overview.get("financial_health") or {}
    negotiations = overview.get("negotiations") or []
    breaches = overview.get("commitment_breaches") or []
    notifications = overview["notifications"]
    latest_notification = notifications[-1] if notifications else None
    escalation_record = next((n for n in reversed(negotiations) if n.get("user_response") == "escalated"), None)

    origin = "Agent auto-escalation"
    reason = "Repeated broken commitments and overdue balance triggered a support review."
    if source == "worker":
        origin = "Worker requested support"
        reason = (latest_notification or {}).get("escalation_summary") or "Worker asked for additional help through the agent."
    elif escalation_record and escalation_record.get("agent_message"):
        reason = escalation_record.get("agent_message")
    elif latest_notification and latest_notification.get("escalation_summary"):
        reason = latest_notification.get("escalation_summary")
    elif payment.get("restructuring_frozen"):
        reason = "Autonomous restructuring was frozen after repeated broken commitments."

    st.markdown(
        f"""
        <div style="margin-bottom:12px;">
          <div style="font-size:2rem;font-weight:900;color:#fff;line-height:1.1;">{escape(profile['name'])}</div>
          <div class="metric-subtle" style="margin-top:4px;">
            {escape(profile['user_id'])} | {escape(profile['gig_type'].replace('_', '-').title())} | {escape(str(profile['risk_tier']).title())} risk
          </div>
          <div class="metric-subtle" style="margin-top:4px;">{escape(origin)}</div>
        </div>
        <div class="metric-label">CASE OVERVIEW</div>
        <div class="modal-grid">
          <div class="modal-stat">
            <div class="modal-stat-label">Origin of escalation</div>
            <div class="modal-stat-value">{escape(origin)}</div>
          </div>
          <div class="modal-stat">
            <div class="modal-stat-label">Amount overdue</div>
            <div class="modal-stat-value">{money(payment['amount_due'])}</div>
          </div>
          <div class="modal-stat">
            <div class="modal-stat-label">Days overdue</div>
            <div class="modal-stat-value">{int(payment['days_overdue'])}</div>
          </div>
          <div class="modal-stat">
            <div class="modal-stat-label">Health score</div>
            <div class="modal-stat-value">{int(financial_health.get('score') or 0)}/100</div>
          </div>
          <div class="modal-stat">
            <div class="modal-stat-label">Broken commitments</div>
            <div class="modal-stat-value">{int(payment['broken_commitments'])}</div>
          </div>
        </div>
        <div class="metric-label">CASE SUMMARY</div>
        <div class="modal-note">{escape(plain_text(reason))}</div>
        """,
        unsafe_allow_html=True,
    )

    history_rows = [
        {
            "Date": fmt_date(str(item.get("timestamp", ""))),
            "Round": item.get("round"),
            "Response": str(item.get("user_response", "")).replace("_", " ").title(),
            "Agent message": plain_text(item.get("agent_message") or ""),
        }
        for item in negotiations
    ]
    breach_rows = [
        {
            "Breach #": item.get("breach_number"),
            "Due date": fmt_date(str(item.get("installment_due_date", ""))),
            "Amount": money(float(item.get("installment_amount") or 0)),
            "Detected": fmt_date(str(item.get("breach_detected_at", ""))),
        }
        for item in breaches
    ]
    comm_rows = [
        {
            "Date": fmt_date(str(item.get("created_at", ""))),
            "Status": str(item.get("status", "")).replace("_", " ").title(),
            "Message": plain_text(item.get("message") or ""),
        }
        for item in notifications
    ]

    st.markdown('<div class="metric-label" style="margin-top:16px;">BREACH HISTORY</div>', unsafe_allow_html=True)
    if breach_rows:
        st.dataframe(pd.DataFrame(breach_rows), use_container_width=True, hide_index=True)
    else:
        st.caption("No commitment breaches recorded.")

    st.markdown('<div class="metric-label" style="margin-top:16px;">CASE HISTORY</div>', unsafe_allow_html=True)
    if history_rows:
        st.dataframe(pd.DataFrame(history_rows), use_container_width=True, hide_index=True)
    else:
        st.caption("No negotiation history recorded.")

    st.markdown('<div class="metric-label" style="margin-top:16px;">AGENT COMM RECORD</div>', unsafe_allow_html=True)
    if comm_rows:
        st.dataframe(pd.DataFrame(comm_rows), use_container_width=True, hide_index=True)
    else:
        st.caption("No agent communication record available.")


@st.dialog("Case details", width="large")
def render_escalation_dialog(user_id: str, source: str | None = None):
    render_escalation_detail(user_id, source)


def render_escalations(dashboard: dict):
    queue = dashboard.get("escalation_queue") or []
    if not queue:
        st.info("No escalated cases in queue.")
        return

    agent_cases = [case for case in queue if case.get("escalation_source") != "worker"]
    worker_cases = [case for case in queue if case.get("escalation_source") == "worker"]

    def render_case_column(title: str, cases: list[dict], key_prefix: str):
        st.markdown(
            f'<div class="escalation-section-title">{escape(title.upper())} {len(cases)}</div>',
            unsafe_allow_html=True,
        )
        if not cases:
            st.info("No cases in this list.")
            return
        for case in cases:
            frozen = '<span class="badge badge-frozen">Frozen</span>' if case.get("restructuring_frozen") else ""
            st.markdown(
                f"""
                <div class="panel escalation-card">
                  <div class="escalation-topline">
                    <div>
                      <b style="font-size:1.15rem;color:#fff;">{escape(case['name'])}</b><br>
                      <span class="badge {risk_class(case['risk_tier'])}">{escape(str(case['risk_tier']).title())}</span>
                      <span class="badge badge-medium">{int(case['broken_commitments'])} breaches</span>
                      {frozen}
                    </div>
                    <span class="badge badge-escalated">Escalated</span>
                  </div>
                  <div class="escalation-meta">
                    {escape(case['user_id'])} | {money(case['amount_due'])} | {int(case['days_overdue'])} days overdue | {escape(case['gig_type'].replace('_', '-').title())}
                  </div>
                  <div class="escalation-summary">{escape(plain_text(case['summary']))}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if st.button(f"Review {case['user_id']}", use_container_width=True, key=f"{key_prefix}_{case['user_id']}"):
                st.session_state["escalation_detail_user"] = case["user_id"]
                st.session_state["escalation_detail_source"] = case.get("escalation_source", "agent")
                st.rerun()

    left, right = st.columns(2)
    with left:
        render_case_column("Escalated by agent", agent_cases, "agent_review")
    with right:
        render_case_column("Escalated by worker", worker_cases, "worker_review")

    selected = st.session_state.get("escalation_detail_user")
    if selected:
        render_escalation_dialog(selected, st.session_state.get("escalation_detail_source"))


def render_trigger_agent(users: list[dict]):
    st.markdown(
        '<p class="metric-subtle">Run the LangGraph collections agent for a specific worker, inspect the full step-by-step trace and draft notification, then explicitly approve the send.</p>',
        unsafe_allow_html=True,
    )
    labels = {
        f"{u['user_id']} - {u['name']} ({str(u['risk_tier']).title()} risk)": u["user_id"]
        for u in users
    }
    c1, c2, c3 = st.columns([4, 1.2, 1.1])
    selected = c1.selectbox("Worker", labels.keys(), label_visibility="collapsed")
    selected_user_id = labels[selected]
    if c2.button("Run preview", type="primary", use_container_width=True, key="trigger_agent_preview_btn"):
        st.session_state["agent_preview"] = run_agent_preview_live(selected_user_id)
        st.session_state.pop("last_trigger", None)
    if c3.button("Clear preview", use_container_width=True, key="clear_agent_preview"):
        st.session_state.pop("agent_preview", None)
        st.session_state.pop("last_trigger", None)
        st.rerun()

    preview = st.session_state.get("agent_preview")
    if preview and preview.get("user_id") == selected_user_id:
        render_trace_flow("Running collections agent preview", preview.get("trace_steps") or [], "agent_preview")
        render_admin_notification_preview(preview, "Collections notification preview")
        send_cols = st.columns([1.2, 3])
        if send_cols[0].button("Send to worker", type="primary", use_container_width=True, key="send_previewed_notification"):
            result = api("POST", "/notifications/send-previewed", json={"state_id": preview["state_id"]})
            st.session_state["last_trigger"] = result
            st.session_state.pop("agent_preview", None)
            refresh_admin()
            st.success(f"Notification delivered to {selected_user_id}")
            st.rerun()
        send_cols[1].caption("Send Notification will deliver the message previewed above, without changes.")

    if st.session_state.get("last_trigger"):
        notification = st.session_state["last_trigger"]["notification"]
        st.markdown(
            f"""
            <div class="panel">
              <b>Last delivered:</b> {escape(notification['user_id'])} |
              {fmt_date(notification['created_at'])} | Status: notification delivered
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_drift_scanner():
    st.markdown(
        '<p class="metric-subtle">Run one portfolio-wide scan, inspect what the detector is analyzing, review the proactive message draft, and only send after explicit approval.</p>',
        unsafe_allow_html=True,
    )
    c1, c2 = st.columns([1.25, 4])
    if c1.button("Run drift scanner", type="primary", use_container_width=True, key="run_drift_scanner"):
        st.session_state["drift_scan"] = run_drift_scan_live()
        st.session_state.pop("last_drift_send", None)
    if c2.button("Clear scan", use_container_width=True, key="clear_drift_scan"):
        st.session_state.pop("drift_scan", None)
        st.session_state.pop("last_drift_send", None)
        st.rerun()

    scan = st.session_state.get("drift_scan")
    if not scan:
        st.info("No scan has been run yet.")
        return

    results = scan.get("results") or []
    drifting = [row for row in results if row.get("drifting")]
    metric_cols = st.columns(3)
    with metric_cols[0]:
        render_metric("Workers scanned", str(scan.get("total_workers", 0)), fmt_date(scan.get("scanned_at", "")))
    with metric_cols[1]:
        render_metric("Drift signals", str(scan.get("drifting_workers", 0)), "watchlist surfaced", "warn" if drifting else "")
    with metric_cols[2]:
        max_score = max((float(row.get("drift_score") or 0) for row in drifting), default=0)
        render_metric("Highest drift", f"{max_score:.2f}", "score out of 1.00")

    render_trace_flow("Running drift scanner preview", scan.get("scan_trace") or [], "drift_scan")

    if not drifting:
        st.success("No workers crossed the drift threshold on this run.")
        return

    for row in drifting:
        summary_html = "".join(f"<div class='drift-line'>{escape(line)}</div>" for line in row.get("summary_lines") or [])
        st.markdown(
            f"""
            <div class="panel drift-card">
              <div class="drift-top">
                <div>
                  <b style="font-size:1.18rem;color:#fff;">{escape(row['name'])}</b><br>
                  <span class="pill-proactive">Drift detected</span>
                  <span class="badge {risk_class('high' if float(row.get('drift_score') or 0) >= 0.7 else 'medium')}">{float(row.get('drift_score') or 0):.2f}</span>
                </div>
                <div class="drift-meta">{escape(row['user_id'])} | {escape(row['gig_type'].replace('_', '-').title())}<br>{escape(row.get('due_context') or '')}</div>
              </div>
              <div class="drift-box">{summary_html}</div>
              <div class="metric-label">PROACTIVE MESSAGE PREVIEW</div>
              <div class="drift-preview">{escape(row.get('preview_message') or '')}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        render_trace_flow(f"Explain drift logic for {row['user_id']}", row.get("trace_steps") or [], f"drift_{row['user_id']}")
        render_admin_notification_preview(
            {
                "notification_preview": {
                    "notification_type": "proactive_checkin",
                    "message": row.get("preview_message") or "",
                    "repayment_plan": {},
                }
            },
            "Proactive check-in preview",
        )
        sent_status = str(row.get("latest_proactive_status") or "")
        can_send = bool(row.get("can_send_checkin"))
        label = f"Send check-in to {row['user_id']}"
        if st.button(label, type="primary", use_container_width=True, key=f"drift_send_{row['user_id']}", disabled=not can_send):
            result = api(
                "POST",
                "/notifications/send-proactive-checkin",
                json={
                    "user_id": row["user_id"],
                    "message": row.get("preview_message") or "",
                    "drift_summary": "\n".join(row.get("summary_lines") or []),
                },
            )
            st.session_state["last_drift_send"] = result
            st.session_state["drift_scan"] = api("GET", "/drift-scan")
            refresh_admin()
            st.success(f"Proactive check-in delivered to {row['user_id']}")
            st.rerun()
        st.caption("This proactive message is only sent after you press the send button.")
        if sent_status and not can_send:
            st.caption(f"Open proactive check-in already exists: {sent_status.replace('proactive_', '').replace('_', ' ').title()}")
    if st.session_state.get("last_drift_send"):
        notification = st.session_state["last_drift_send"]["notification"]
        st.markdown(
            f"""
            <div class="panel">
              <b>Last proactive check-in sent:</b> {escape(notification['user_id'])} |
              {fmt_date(notification['created_at'])} | Status: delivered
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
    elif active == "drift":
        render_drift_scanner()
    else:
        render_trigger_agent(users)
    st.markdown("</div>", unsafe_allow_html=True)


def notification_actions(notification: dict, user_id: str):
    status = notification.get("status")
    kind = notification_type(notification)
    if kind == "proactive_checkin":
        if status in {"proactive_acknowledged", "proactive_options_requested", "proactive_support_requested"}:
            st.caption(f"{t(user_id, 'notification_status')}: {status.replace('proactive_', '').replace('_', ' ').title()}")
            return
        c1, c2, c3 = st.columns([1, 1.5, 1.2])
        if c1.button("I'm okay", use_container_width=True, key=f"accept_{notification['id']}"):
            api("POST", "/worker/notification-response", json={"notification_id": notification["id"], "user_response": "accepted"})
            st.rerun()
        if c2.button("Talk through options early", use_container_width=True, key=f"reject_{notification['id']}"):
            api("POST", "/worker/notification-response", json={"notification_id": notification["id"], "user_response": "rejected"})
            st.rerun()
        if c3.button("Talk to support", use_container_width=True, key=f"support_{notification['id']}"):
            api("POST", "/worker/notification-response", json={"notification_id": notification["id"], "user_response": "support_requested"})
            st.rerun()
        return
    if status in {"accepted", "escalated", "worker_escalated"}:
        st.caption(f"{t(user_id, 'notification_status')}: {status.replace('_', ' ').title()}")
        return
    c1, c2, c3 = st.columns([1, 1.55, 1.15])
    if c1.button(t(user_id, "accept_plan"), use_container_width=True, key=f"accept_{notification['id']}"):
        api("POST", "/worker/notification-response", json={"notification_id": notification["id"], "user_response": "accepted"})
        st.rerun()
    if c2.button(t(user_id, "suggest_plan"), use_container_width=True, key=f"reject_{notification['id']}"):
        api("POST", "/worker/notification-response", json={"notification_id": notification["id"], "user_response": "rejected"})
        st.rerun()
    if c3.button(t(user_id, "talk_support"), use_container_width=True, key=f"support_{notification['id']}"):
        api("POST", "/worker/notification-response", json={"notification_id": notification["id"], "user_response": "support_requested"})
        st.rerun()


def render_notification(notification: dict | None, user_id: str):
    if not notification:
        st.markdown(
            f"<div class=\"notification notification-collection\"><b>{escape(t(user_id, 'no_active_title'))}</b><br>{escape(t(user_id, 'no_active_body'))}</div>",
            unsafe_allow_html=True,
        )
        return
    if notification_type(notification) == "proactive_checkin":
        st.markdown(
            f"""
            <div class="notification notification-proactive">
              <div class="subtle">Early support check-in</div>
              <b>We noticed your routine looks a little different lately</b><br>
              {escape(notification.get('message') or '')}
            </div>
            """,
            unsafe_allow_html=True,
        )
        notification_actions(notification, user_id)
        return
    message = notification.get("message") or ""
    if not plain_text(message):
        message = (
            notification.get("escalation_summary")
            or t(user_id, "support_review")
        )
    message = localized_collection_message(user_id, notification, message)
    plan = notification.get("repayment_plan") or {}
    lines = []
    for idx, item in enumerate(plan.get("installments") or [], start=1):
        lines.append(
            f"<div class='plan-line'><div>{escape(t(user_id, 'installment'))} {idx}</div><div>{sgd(item.get('amount', 0))}</div><div>{fmt_date(str(item.get('due_date', '')))}</div></div>"
        )
    plan_html = (
        f"<div class='plan-box'><b>{escape(t(user_id, 'plan_offered'))}</b>{''.join(lines)}</div>"
        if lines
        else ""
    )
    st.markdown(
        f"""
        <div class="notification notification-collection">
          <b>{escape(t(user_id, 'new_message'))}</b><br>
          {escape(message)}
          {plan_html}
        </div>
        """,
        unsafe_allow_html=True,
    )
    notification_actions(notification, user_id)


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
    user_id = overview["profile"]["user_id"]
    if notifications:
        for n in reversed(notifications[-4:]):
            label = t(user_id, "support_checkin") if notification_type(n) == "proactive_checkin" else t(user_id, "agent_message")
            body = n.get("message") or ""
            if notification_type(n) != "proactive_checkin":
                body = localized_collection_message(user_id, n, body)
            st.markdown(
                f"""
                <div class="timeline-card">
                  <div class="avatar" style="height:32px;width:32px;">G</div>
                  <div><b>{fmt_date(n['created_at'])} | {escape(label)}</b><br>{escape(body)}</div>
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
    lang_prefs = st.session_state.setdefault("worker_language_preferences", {})
    top_l, top_m, top_r = st.columns([3.3, 1.8, 1])
    selected = top_l.selectbox("Worker authentication", labels.keys())
    user_id = labels[selected]
    option_labels = [label for _, label in LANGUAGE_OPTIONS]
    current_locale = lang_prefs.get(user_id, WORKER_LOCALES.get(user_id, "en"))
    selected_index = next((idx for idx, (code, _) in enumerate(LANGUAGE_OPTIONS) if code == current_locale), 0)
    selected_label = top_m.selectbox(
        t(user_id, "language_pref"),
        option_labels,
        index=selected_index,
        key=f"worker_language_selector_{user_id}",
    )
    selected_locale = next(code for code, label in LANGUAGE_OPTIONS if label == selected_label)
    lang_prefs[user_id] = selected_locale
    if top_r.button(t(user_id, "switch_role"), use_container_width=True):
        st.session_state.pop("role", None)
        st.rerun()
    overview = api("GET", f"/worker/{user_id}/overview")
    profile = overview["profile"]
    payment = overview["payment"]
    health = overview["financial_health"]
    notifications = overview["notifications"]
    latest_notification = notifications[-1] if notifications else None
    due_label, due_value = payment_timing_text(payment)
    balance_suffix = (
        '<span class="metric-warn" style="font-size:1rem;">overdue</span>'
        if int(payment.get("days_overdue") or 0) > 0
        else '<span class="metric-subtle" style="font-size:1rem;">upcoming</span>'
    )

    initials = "".join(part[0] for part in profile["name"].split()[:2]).upper()
    st.markdown(
        f"""
        <div class="profile-head">
          <div class="avatar">{escape(initials)}</div>
          <div><b style="font-size:1.25rem;">{escape(profile['name'])}</b><br><span class="metric-subtle">{escape(profile['user_id'])} | {escape(profile['gig_type'].replace('_', '-').title())}</span></div>
          <div style="margin-left:auto;"><span class="badge {risk_class(profile['risk_tier'])}">{escape(str(profile['risk_tier']).title())} risk</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    render_notification(latest_notification, user_id)

    tabs = st.tabs([t(user_id, "overview"), t(user_id, "earnings"), t(user_id, "history")])
    with tabs[0]:
        c1, c2 = st.columns([1, 2.2])
        with c1:
            render_health_card(health)
        with c2:
            st.markdown(
                f"""
                <div class="panel">
                  <div class="metric-label">CURRENT BALANCE</div>
                  <div class="metric-value">{sgd(payment['amount_due'])} {balance_suffix}</div>
                  <div class="plan-line"><div>{escape(due_label)}</div><div></div><div>{escape(due_value)}</div></div>
                  <div class="plan-line"><div>Notification type</div><div></div><div>{escape('Support check-in' if notification_type(latest_notification) == 'proactive_checkin' else 'Collections message' if latest_notification else 'No active message')}</div></div>
                  <div class="plan-line"><div>Notification status</div><div></div><div>{escape(notification_status_label(latest_notification))}</div></div>
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
    st.error(f"API request failed: {exc}")
except Exception as exc:
    st.error(f"App failed: {exc}")
