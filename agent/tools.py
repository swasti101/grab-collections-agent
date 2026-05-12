import json
import os
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import pytz
from langchain_core.tools import tool
from sqlmodel import select

from agent.health_score import calculate_health_score_data
from db.database import Earning, Payment, get_session

FREEZE_THRESHOLD = int(os.getenv("COMMITMENT_FREEZE_THRESHOLD", "2"))
SGT = pytz.timezone("Asia/Singapore")


def _tool_result(result):
    return result


def _earnings_summary(user_id: str, days: int = 30) -> dict:
    with get_session() as session:
        rows = session.exec(
            select(Earning).where(Earning.user_id == user_id).order_by(Earning.date)
        ).all()
    if not rows:
        raise ValueError(f"No earnings found for {user_id}")

    df = pd.DataFrame([r.model_dump() for r in rows])
    df["date"] = pd.to_datetime(df["date"])
    recent = df.tail(days).copy()
    recent["weekday"] = recent["date"].dt.day_name()
    avg_daily = float(recent["amount"].mean())
    day_means = recent.groupby("weekday")["amount"].mean().sort_values(ascending=False)
    peak_days = day_means.head(2).index.tolist()
    peak_hour = int(round(recent["hour_of_peak"].mode().iloc[0]))
    nudge_hour = max(8, min(22, peak_hour + 2))
    recent_avg = float(recent.tail(14)["amount"].mean())
    prior_avg = float(recent.head(max(1, len(recent) - 14))["amount"].mean())

    x = np.arange(len(recent))
    slope = float(np.polyfit(x, recent["amount"].to_numpy(), 1)[0]) if len(recent) > 1 else 0.0
    if slope > 3:
        trend = "improving"
    elif slope < -3:
        trend = "declining"
    else:
        trend = "stable"
    cv = float(recent["amount"].std() / avg_daily) if avg_daily else 1.0
    volatility = "high" if cv >= 0.6 else "medium" if cv >= 0.35 else "low"
    consistency_ratio = float((recent["amount"] > avg_daily * 0.6).mean())
    gig_stability = float(1 - min(cv, 1.0))
    hardship = recent_avg < prior_avg * 0.6 if prior_avg else False

    return {
        "avg_daily_income": round(avg_daily, 2),
        "peak_days": peak_days,
        "peak_hour": peak_hour,
        "nudge_hour": nudge_hour,
        "income_trend": trend,
        "income_volatility": volatility,
        "hardship_detected": bool(hardship),
        "recent_avg": round(recent_avg, 2),
        "prior_avg": round(prior_avg, 2),
        "income_slope": round(slope, 2),
        "consistency_ratio": round(consistency_ratio, 2),
        "gig_stability": round(gig_stability, 2),
        "repayment_ratio": 1.0,
    }


@tool
def analyze_earning_windows(user_id: str) -> dict:
    """Analyze the last 30 days of earnings and return peak windows and hardship signals."""
    return _tool_result(_earnings_summary(user_id, 30))


@tool
def classify_risk(user_id: str, days_overdue: int, prior_rejections: int, broken_commitments: int) -> dict:
    """Classify recovery risk for a specific overdue debt."""
    summary = _earnings_summary(user_id, 30)
    if summary["hardship_detected"]:
        return {
            "risk_tier": "hardship",
            "risk_score": 85,
            "risk_factors": ["Recent income dropped below 60% of prior baseline"],
            "recommended_tone": "empathetic and supportive",
            "can_self_serve": True,
        }

    score = 0
    factors: list[str] = []
    if days_overdue <= 7:
        score += 15
    elif days_overdue <= 14:
        score += 28
    else:
        score += 42
    factors.append(f"{days_overdue} days overdue")

    if prior_rejections == 1:
        score += 10
        factors.append("Rejected one prior plan")
    elif prior_rejections == 2:
        score += 22
        factors.append("Rejected two prior plans")
    elif prior_rejections >= 3:
        score += 35
        factors.append("Rejected three or more prior plans")

    if broken_commitments == 1:
        score += 18
    elif broken_commitments == 2:
        score += 32
    elif broken_commitments >= 3:
        score += 45
    if broken_commitments:
        factors.append(f"Accepted {broken_commitments} prior plan(s) but did not follow through")

    if summary["income_volatility"] == "high":
        score += 16
        factors.append("High income volatility")
    elif summary["income_volatility"] == "medium":
        score += 8
        factors.append("Moderate income volatility")
    if summary["income_trend"] == "declining":
        score += 12
        factors.append("Declining recent income")
    if summary["consistency_ratio"] < 0.5:
        score += 10
        factors.append("Income is inconsistent across active days")
    if summary["gig_stability"] < 0.5:
        score += 8
        factors.append("Low gig stability signal")

    repayment_ratio = max(0.0, 1.0 - prior_rejections * 0.12 - broken_commitments * 0.25)
    if repayment_ratio < 0.4:
        score += 12
        factors.append("Weak repayment history")
    elif repayment_ratio >= 0.8:
        score -= 8
    if summary["income_slope"] > 5:
        score -= 5
        factors.append("Income is improving")

    score = int(max(0, min(100, score)))
    tier = "low" if score < 35 else "medium" if score < 65 else "high"
    tone = {
        "low": "friendly and direct",
        "medium": "flexible and encouraging",
        "high": "careful, supportive, and specific",
    }[tier]
    return {
        "risk_tier": tier,
        "risk_score": score,
        "risk_factors": factors,
        "recommended_tone": tone,
        "can_self_serve": broken_commitments < FREEZE_THRESHOLD and score < 80,
    }


def _next_date_for_day(day_name: str, offset_days: int = 0) -> date:
    weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    target = weekdays.index(day_name)
    today = datetime.now(SGT).date() + timedelta(days=offset_days)
    delta = (target - today.weekday()) % 7
    return today + timedelta(days=delta or 7)


@tool
def generate_repayment_plan(
    user_id: str,
    amount_due: float,
    earnings_summary: dict,
    risk_tier: str,
    negotiation_round: int,
    broken_commitments: int,
) -> dict:
    """Generate an income-aware repayment plan unless autonomous restructuring is frozen."""
    if broken_commitments >= FREEZE_THRESHOLD:
        return {
            "plan_type": "frozen",
            "reason": "Autonomous restructuring frozen after repeated broken commitments",
            "broken_commitments": broken_commitments,
            "installments": [],
            "total_amount": amount_due,
            "peak_day_aligned": False,
            "summary": "Autonomous restructuring is frozen.",
        }
    if negotiation_round >= 3:
        return {
            "plan_type": "escalate",
            "installments": [],
            "total_amount": amount_due,
            "peak_day_aligned": False,
            "summary": "Manual support needed after repeated negotiation rounds.",
        }

    peak_days = earnings_summary.get("peak_days") or ["Friday"]
    first_date = _next_date_for_day(peak_days[0], 7 if negotiation_round >= 2 else 0)
    if risk_tier == "hardship":
        pay_date = datetime.now(SGT).date() + timedelta(days=14)
        installments = [{"due_date": pay_date.isoformat(), "amount": round(amount_due, 2)}]
        return {
            "plan_type": "grace_period",
            "installments": installments,
            "total_amount": round(amount_due, 2),
            "peak_day_aligned": False,
            "summary": f"14-day pause, then SGD {amount_due:.2f} due on {pay_date.isoformat()}.",
        }

    base_count = {"low": 1, "medium": 2, "high": 3}.get(risk_tier, 2)
    count = base_count + (1 if negotiation_round >= 1 else 0)
    amount = round(amount_due / count, 2)
    installments = []
    for idx in range(count):
        due = first_date + timedelta(days=7 * idx)
        installments.append({"due_date": due.isoformat(), "amount": amount if idx < count - 1 else round(amount_due - amount * (count - 1), 2)})
    return {
        "plan_type": "immediate" if count == 1 else "installments",
        "installments": installments,
        "total_amount": round(amount_due, 2),
        "peak_day_aligned": True,
        "summary": f"{count} payment(s) aligned to expected peak earning days.",
    }


@tool
def schedule_nudge(earnings_summary: dict) -> str:
    """Return the next peak-day nudge datetime in SGT."""
    peak_day = (earnings_summary.get("peak_days") or ["Friday"])[0]
    nudge_date = _next_date_for_day(peak_day)
    nudge_dt = SGT.localize(datetime.combine(nudge_date, datetime.min.time())).replace(
        hour=int(earnings_summary.get("nudge_hour", 20))
    )
    return nudge_dt.isoformat()


@tool
def calculate_financial_health_score(user_id: str) -> dict:
    """Calculate and upsert the holistic financial health score for a worker."""
    return calculate_health_score_data(user_id)
