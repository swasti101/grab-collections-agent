import math
import os
from datetime import datetime

import numpy as np
import pandas as pd
import pytz
from sqlmodel import select

from agent.model_factory import get_model_factory
from db.database import Earning, Payment, WorkerNotification, get_session

SGT = pytz.timezone("Asia/Singapore")
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
DRIFT_THRESHOLD = float(os.getenv("DRIFT_SCORE_THRESHOLD", "0.50"))


def _money(value: float) -> str:
    return f"SGD {float(value):.2f}"


def _safe_mode_hour(series: pd.Series) -> int:
    modes = series.mode()
    if modes.empty:
        return int(round(float(series.mean()))) if not series.empty else 0
    return int(modes.iloc[0])


def _safe_corr(left: pd.Series, right: pd.Series) -> float:
    if left.std() == 0 or right.std() == 0:
        return 1.0 if np.allclose(left.to_numpy(), right.to_numpy()) else 0.0
    corr = float(np.corrcoef(left.to_numpy(), right.to_numpy())[0, 1])
    if math.isnan(corr):
        return 0.0
    return max(-1.0, min(1.0, corr))


def _format_hour(hour: int) -> str:
    if hour == 0:
        return "12 AM"
    suffix = "AM" if hour < 12 else "PM"
    display = hour if 1 <= hour <= 12 else hour - 12 if hour > 12 else 12
    return f"{display} {suffix}"


def _format_due_context(days_until_due: int) -> str:
    if days_until_due > 0:
        return f"Next payment due in {days_until_due} days"
    if days_until_due == 0:
        return "Payment due today"
    return f"Currently {abs(days_until_due)} days overdue"


def _worker_earnings_frame(user_id: str) -> pd.DataFrame:
    with get_session() as session:
        rows = session.exec(select(Earning).where(Earning.user_id == user_id).order_by(Earning.date)).all()
    if not rows:
        raise ValueError(f"No earnings found for {user_id}")
    df = pd.DataFrame([row.model_dump() for row in rows])
    df["date"] = pd.to_datetime(df["date"])
    df["weekday"] = df["date"].dt.day_name()
    return df


def _split_windows(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if len(df) >= 44:
        baseline = df.iloc[-44:-14].copy()
        recent = df.iloc[-14:].copy()
    else:
        split = max(7, len(df) // 3)
        baseline = df.iloc[: len(df) - split].copy()
        recent = df.iloc[len(df) - split :].copy()
    return baseline, recent


def _weekday_profile(frame: pd.DataFrame) -> pd.Series:
    return frame.groupby("weekday")["amount"].mean().reindex(WEEKDAYS, fill_value=0.0)


def _latest_proactive_status(user_id: str) -> str | None:
    with get_session() as session:
        notifications = session.exec(
            select(WorkerNotification).where(WorkerNotification.user_id == user_id).order_by(WorkerNotification.created_at)
        ).all()
    proactive = [n for n in notifications if n.status.startswith("proactive_")]
    return proactive[-1].status if proactive else None


def _base_drift_features(payment: Payment) -> dict:
    df = _worker_earnings_frame(payment.user_id)
    baseline, recent = _split_windows(df)

    baseline_avg = float(baseline["amount"].mean()) if not baseline.empty else float(df["amount"].mean())
    recent_avg = float(recent["amount"].mean()) if not recent.empty else baseline_avg

    baseline_hour = _safe_mode_hour(baseline["hour_of_peak"]) if not baseline.empty else _safe_mode_hour(df["hour_of_peak"])
    recent_hour = _safe_mode_hour(recent["hour_of_peak"]) if not recent.empty else baseline_hour
    timing_drift_hours = abs(recent_hour - baseline_hour)

    activity_threshold = max(25.0, baseline_avg * 0.6)
    baseline_active_ratio = float((baseline["amount"] >= activity_threshold).mean()) if not baseline.empty else 0.0
    recent_active_ratio = float((recent["amount"] >= activity_threshold).mean()) if not recent.empty else 0.0
    consistency_drop = max(0.0, baseline_active_ratio - recent_active_ratio)

    baseline_week = _weekday_profile(baseline if not baseline.empty else df)
    recent_week = _weekday_profile(recent if not recent.empty else df)
    pattern_correlation = _safe_corr(baseline_week, recent_week)

    income_drop_ratio = max(0.0, 1.0 - (recent_avg / max(baseline_avg, 1.0)))
    days_until_due = (payment.due_date - datetime.now(SGT).date()).days

    return {
        "user_id": payment.user_id,
        "name": payment.name,
        "gig_type": payment.gig_type,
        "payment_id": payment.id,
        "amount_due": round(float(payment.amount_due), 2),
        "due_date": payment.due_date.isoformat(),
        "days_until_due": days_until_due,
        "days_overdue": payment.days_overdue,
        "status": payment.status,
        "broken_commitments": payment.broken_commitments,
        "prior_rejections": payment.prior_rejections,
        "baseline_avg_income": round(baseline_avg, 2),
        "recent_avg_income": round(recent_avg, 2),
        "baseline_peak_hour": baseline_hour,
        "recent_peak_hour": recent_hour,
        "timing_drift_hours": timing_drift_hours,
        "baseline_active_ratio": round(baseline_active_ratio, 2),
        "recent_active_ratio": round(recent_active_ratio, 2),
        "consistency_drop": round(consistency_drop, 2),
        "pattern_correlation": round(pattern_correlation, 2),
        "income_drop_ratio": round(income_drop_ratio, 2),
        "due_context": _format_due_context(days_until_due),
        "latest_proactive_status": _latest_proactive_status(payment.user_id),
    }


def _feature_vector(metrics: dict) -> np.ndarray:
    return np.array(
        [
            min(metrics["timing_drift_hours"] / 8.0, 1.0),
            min(metrics["consistency_drop"] / 0.45, 1.0),
            min((1.0 - metrics["pattern_correlation"]) / 1.2, 1.0),
            min(metrics["income_drop_ratio"] / 0.5, 1.0),
            min((metrics["broken_commitments"] * 0.2) + (metrics["prior_rejections"] * 0.08), 1.0),
        ],
        dtype=float,
    )


def _default_reference_ids(payments: list[Payment]) -> set[str]:
    return {
        payment.user_id
        for payment in payments
        if payment.broken_commitments > 0 or payment.restructuring_frozen or payment.status == "escalated"
    }


def _proactive_message_complete(message: str) -> bool:
    if not message or len(message.strip()) < 100:
        return False
    lowered = message.lower()
    blocked = ["collections", "default", "overdue", "legal action", "risk score", "debt"]
    return not any(token in lowered for token in blocked)


def _fallback_proactive_message(metrics: dict) -> str:
    due_context = (
        f"Your next payment is not due for {metrics['days_until_due']} days, so there is no rush."
        if metrics["days_until_due"] > 0
        else "There is no urgent action needed right now."
    )
    return (
        f"Hi {metrics['name'].split()[0]}, hope your week is going smoothly. "
        "We noticed your recent work pattern looks a little different from your usual rhythm, so we wanted to check in early and see how things are going. "
        f"{due_context} If it would help, we are here to talk through options early and keep things manageable."
    )


def generate_proactive_checkin_message(metrics: dict) -> str:
    prompt = f"""
    You are a Grab worker support assistant.
    Write a proactive check-in in 2-3 sentences.
    This is NOT a collections message.
    Do not mention debt, overdue balances, default risk, collections, or legal action.
    Sound warm, observant, and supportive.
    Worker name: {metrics['name']}.
    Gig type: {metrics['gig_type']}.
    Due context: {metrics['due_context']}.
    Drift facts:
    - Peak working hour shifted from {metrics['baseline_peak_hour']} to {metrics['recent_peak_hour']}
    - Active day ratio moved from {metrics['baseline_active_ratio']:.0%} to {metrics['recent_active_ratio']:.0%}
    - Weekly pattern correlation is {metrics['pattern_correlation']:.2f}
    - Recent average income is {metrics['income_drop_ratio']:.0%} below baseline
    Include a light offer to talk through options early if helpful.
    """
    try:
        response = get_model_factory().create_fast_model().invoke(prompt)
        message = str(getattr(response, "content", "")).strip()
        return message if _proactive_message_complete(message) else _fallback_proactive_message(metrics)
    except Exception:
        return _fallback_proactive_message(metrics)


def _drift_summary_lines(metrics: dict, similarity_count: int, total_defaults: int) -> list[str]:
    return [
        f"Drift score: {metrics['drift_score']:.2f}",
        (
            f"Timing drift: {metrics['timing_drift_hours']} hour(s) "
            f"(used to peak around {_format_hour(metrics['baseline_peak_hour'])}, now around {_format_hour(metrics['recent_peak_hour'])})"
        ),
        (
            f"Consistency drop: active days moved from {metrics['baseline_active_ratio']:.0%} "
            f"to {metrics['recent_active_ratio']:.0%}"
        ),
        f"Pattern correlation: {metrics['pattern_correlation']:.2f}",
        f"Earnings drop: recent average is {metrics['income_drop_ratio']:.0%} below baseline",
        f"Similar to {similarity_count} of {total_defaults} historical defaulter pattern(s)",
    ]


def _worker_trace_steps(metrics: dict) -> list[dict]:
    return [
        {
            "step_number": 1,
            "title": "Analyze worker income baseline",
            "tools_called": ["earnings_history_lookup", "payment_lookup"],
            "analysis": [
                f"Loaded the worker's baseline earnings pattern and the most recent activity window for {metrics['user_id']}.",
                f"Due context: {metrics['due_context']}.",
            ],
            "result": (
                f"Baseline avg income {_money(metrics['baseline_avg_income'])}; "
                f"recent avg income {_money(metrics['recent_avg_income'])}."
            ),
        },
        {
            "step_number": 2,
            "title": "Analyze timing drift and activity consistency",
            "tools_called": ["timing_shift_detector", "consistency_monitor"],
            "analysis": [
                f"Peak hour moved from {_format_hour(metrics['baseline_peak_hour'])} to {_format_hour(metrics['recent_peak_hour'])}.",
                f"Active-day ratio moved from {metrics['baseline_active_ratio']:.0%} to {metrics['recent_active_ratio']:.0%}.",
            ],
            "result": f"Timing drift {metrics['timing_drift_hours']} hour(s); consistency drop {metrics['consistency_drop']:.0%}.",
        },
        {
            "step_number": 3,
            "title": "Compare recent earning pattern to baseline",
            "tools_called": ["weekday_pattern_correlation"],
            "analysis": [
                "Compared the current week-shape against the worker's own baseline earning rhythm.",
            ],
            "result": f"Pattern correlation {metrics['pattern_correlation']:.2f}; earnings drop {metrics['income_drop_ratio']:.0%}.",
        },
        {
            "step_number": 4,
            "title": "Compare against historical default patterns",
            "tools_called": ["historical_similarity_match"],
            "analysis": [
                "Compared the worker's current drift vector against workers with prior broken commitments or frozen cases.",
            ],
            "result": (
                f"Matched {metrics['similarity_count']} of {metrics['total_default_patterns']} reference default pattern(s). "
                f"Final drift score {metrics['drift_score']:.2f}."
            ),
        },
        {
            "step_number": 5,
            "title": "Draft proactive check-in",
            "tools_called": [f"bedrock.invoke_model ({get_model_factory().fast_model_id})"],
            "analysis": [
                "Drafted a soft support-first message with no collections wording.",
                "The message is meant for early outreach before the worker fully slips into a missed-payment pattern.",
            ],
            "result": metrics.get("preview_message") or "No proactive message drafted.",
        },
    ]


def scan_all_workers() -> list[dict]:
    with get_session() as session:
        payments = session.exec(select(Payment).order_by(Payment.user_id)).all()
    if not payments:
        return []

    default_ids = _default_reference_ids(payments)
    metrics_rows = [_base_drift_features(payment) for payment in payments]
    vectors = {row["user_id"]: _feature_vector(row) for row in metrics_rows}

    results = []
    default_vectors = {user_id: vector for user_id, vector in vectors.items() if user_id in default_ids}
    for row in metrics_rows:
        comparisons = [
            float(np.linalg.norm(vectors[row["user_id"]] - default_vector))
            for ref_id, default_vector in default_vectors.items()
            if ref_id != row["user_id"]
        ]
        similarity_count = len([distance for distance in comparisons if distance <= 0.9])
        total_defaults = len(comparisons)
        similarity_ratio = (similarity_count / total_defaults) if total_defaults else 0.0
        feature_vector = vectors[row["user_id"]]
        drift_score = float(
            0.24 * feature_vector[0]
            + 0.22 * feature_vector[1]
            + 0.22 * feature_vector[2]
            + 0.20 * feature_vector[3]
            + 0.12 * similarity_ratio
        )
        drifting = drift_score >= DRIFT_THRESHOLD and (
            row["timing_drift_hours"] >= 2 or row["consistency_drop"] >= 0.12 or row["income_drop_ratio"] >= 0.15
        )
        row["drift_score"] = round(drift_score, 2)
        row["drifting"] = drifting
        row["similarity_count"] = similarity_count
        row["total_default_patterns"] = total_defaults
        row["summary_lines"] = _drift_summary_lines(row, similarity_count, total_defaults)
        row["preview_message"] = generate_proactive_checkin_message(row) if drifting else ""
        row["trace_steps"] = _worker_trace_steps(row)
        row["can_send_checkin"] = drifting and row["latest_proactive_status"] not in {
            "proactive_unread",
            "proactive_options_requested",
            "proactive_support_requested",
        }
        results.append(row)

    results.sort(key=lambda item: item["drift_score"], reverse=True)
    return results


def scan_all_workers_with_trace() -> dict:
    results = scan_all_workers()
    drifting = [row for row in results if row.get("drifting")]
    return {
        "scan_trace": [
            {
                "step_number": 1,
                "title": "Load worker portfolio for income analysis",
                "tools_called": ["payment_lookup", "earnings_history_lookup"],
                "analysis": ["Loaded every worker's payment record and recent earnings history."],
                "result": f"Prepared {len(results)} worker profile(s) for drift analysis.",
            },
            {
                "step_number": 2,
                "title": "Establish reference default patterns",
                "tools_called": ["historical_default_profile_builder"],
                "analysis": ["Built a reference set from workers with broken commitments, frozen restructuring, or escalated status."],
                "result": "Historical drift signatures are ready for comparison.",
            },
            {
                "step_number": 3,
                "title": "Analyze drift across the portfolio",
                "tools_called": ["timing_shift_detector", "consistency_monitor", "weekday_pattern_correlation", "historical_similarity_match"],
                "analysis": ["Calculated timing drift, active-day consistency drop, weekly-pattern mismatch, earnings drop, and historical similarity for each worker."],
                "result": f"Flagged {len(drifting)} worker(s) above the drift threshold of {DRIFT_THRESHOLD:.2f}.",
            },
            {
                "step_number": 4,
                "title": "Draft proactive check-ins",
                "tools_called": [f"bedrock.invoke_model ({get_model_factory().fast_model_id})"],
                "analysis": ["Drafted support-first messages only for workers who crossed the drift threshold."],
                "result": "Proactive message previews are ready for admin review before sending.",
            },
        ],
        "results": results,
    }


def stream_drift_scan_with_trace():
    with get_session() as session:
        payments = session.exec(select(Payment).order_by(Payment.user_id)).all()
    if not payments:
        yield {
            "event": "completed",
            "scan_trace": [],
            "results": [],
        }
        return

    yield {
        "event": "step",
        "step": {
            "step_number": 1,
            "title": "Load worker portfolio for income analysis",
            "tools_called": ["payment_lookup", "earnings_history_lookup"],
            "analysis": ["Loaded every worker's payment record and recent earnings history."],
            "result": f"Prepared {len(payments)} worker profile(s) for drift analysis.",
        },
    }

    default_ids = _default_reference_ids(payments)
    yield {
        "event": "step",
        "step": {
            "step_number": 2,
            "title": "Establish reference default patterns",
            "tools_called": ["historical_default_profile_builder"],
            "analysis": ["Built a reference set from workers with broken commitments, frozen restructuring, or escalated status."],
            "result": "Historical drift signatures are ready for comparison.",
        },
    }

    metrics_rows = []
    for payment in payments:
        yield {
            "event": "worker_progress",
            "worker_id": payment.user_id,
            "message": f"Analyzing recent earning behaviour for {payment.user_id}.",
        }
        metrics_rows.append(_base_drift_features(payment))

    vectors = {row["user_id"]: _feature_vector(row) for row in metrics_rows}
    default_vectors = {user_id: vector for user_id, vector in vectors.items() if user_id in default_ids}

    yield {
        "event": "step",
        "step": {
            "step_number": 3,
            "title": "Analyze drift across the portfolio",
            "tools_called": ["timing_shift_detector", "consistency_monitor", "weekday_pattern_correlation", "historical_similarity_match"],
            "analysis": ["Calculated timing drift, active-day consistency drop, weekly-pattern mismatch, earnings drop, and historical similarity for each worker."],
            "result": "Scoring each worker for default-pattern drift.",
        },
    }

    results = []
    for row in metrics_rows:
        comparisons = [
            float(np.linalg.norm(vectors[row["user_id"]] - default_vector))
            for ref_id, default_vector in default_vectors.items()
            if ref_id != row["user_id"]
        ]
        similarity_count = len([distance for distance in comparisons if distance <= 0.9])
        total_defaults = len(comparisons)
        similarity_ratio = (similarity_count / total_defaults) if total_defaults else 0.0
        feature_vector = vectors[row["user_id"]]
        drift_score = float(
            0.24 * feature_vector[0]
            + 0.22 * feature_vector[1]
            + 0.22 * feature_vector[2]
            + 0.20 * feature_vector[3]
            + 0.12 * similarity_ratio
        )
        drifting = drift_score >= DRIFT_THRESHOLD and (
            row["timing_drift_hours"] >= 2 or row["consistency_drop"] >= 0.12 or row["income_drop_ratio"] >= 0.15
        )
        row["drift_score"] = round(drift_score, 2)
        row["drifting"] = drifting
        row["similarity_count"] = similarity_count
        row["total_default_patterns"] = total_defaults
        row["summary_lines"] = _drift_summary_lines(row, similarity_count, total_defaults)
        row["preview_message"] = generate_proactive_checkin_message(row) if drifting else ""
        row["trace_steps"] = _worker_trace_steps(row)
        row["can_send_checkin"] = drifting and row["latest_proactive_status"] not in {
            "proactive_unread",
            "proactive_options_requested",
            "proactive_support_requested",
        }
        results.append(row)
        yield {
            "event": "worker_result",
            "worker_id": row["user_id"],
            "drift_score": row["drift_score"],
            "drifting": row["drifting"],
        }

    results.sort(key=lambda item: item["drift_score"], reverse=True)
    drifting = [row for row in results if row.get("drifting")]

    yield {
        "event": "step",
        "step": {
            "step_number": 4,
            "title": "Draft proactive check-ins",
            "tools_called": [f"bedrock.invoke_model ({get_model_factory().fast_model_id})"],
            "analysis": ["Drafted support-first messages only for workers who crossed the drift threshold."],
            "result": f"Prepared proactive check-in previews for {len(drifting)} drifting worker(s).",
        },
    }

    yield {
        "event": "completed",
        "scan_trace": [
            {
                "step_number": 1,
                "title": "Load worker portfolio for income analysis",
                "tools_called": ["payment_lookup", "earnings_history_lookup"],
                "analysis": ["Loaded every worker's payment record and recent earnings history."],
                "result": f"Prepared {len(results)} worker profile(s) for drift analysis.",
            },
            {
                "step_number": 2,
                "title": "Establish reference default patterns",
                "tools_called": ["historical_default_profile_builder"],
                "analysis": ["Built a reference set from workers with broken commitments, frozen restructuring, or escalated status."],
                "result": "Historical drift signatures are ready for comparison.",
            },
            {
                "step_number": 3,
                "title": "Analyze drift across the portfolio",
                "tools_called": ["timing_shift_detector", "consistency_monitor", "weekday_pattern_correlation", "historical_similarity_match"],
                "analysis": ["Calculated timing drift, active-day consistency drop, weekly-pattern mismatch, earnings drop, and historical similarity for each worker."],
                "result": f"Flagged {len(drifting)} worker(s) above the drift threshold of {DRIFT_THRESHOLD:.2f}.",
            },
            {
                "step_number": 4,
                "title": "Draft proactive check-ins",
                "tools_called": [f"bedrock.invoke_model ({get_model_factory().fast_model_id})"],
                "analysis": ["Drafted support-first messages only for workers who crossed the drift threshold."],
                "result": "Proactive message previews are ready for admin review before sending.",
            },
        ],
        "results": results,
    }
