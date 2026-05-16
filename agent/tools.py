import json
import math
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
SMALL_BALANCE_THRESHOLD = 80.0
TARGET_INSTALLMENT_SIZE = 75.0
MAX_INSTALLMENTS = 6


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
    weekday_averages = {day: round(float(amount), 2) for day, amount in day_means.items()}
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
        "weekday_averages": weekday_averages,
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


def _next_date_on_or_after(day_name: str, start_date: date) -> date:
    weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    target = weekdays.index(day_name)
    delta = (target - start_date.weekday()) % 7
    return start_date + timedelta(days=delta)


def _build_peak_day_sequence(peak_days: list[str], count: int) -> list[str]:
    days = peak_days or ["Friday"]
    return [days[idx % len(days)] for idx in range(count)]


def _weighted_installment_amounts(amount_due: float, day_sequence: list[str], weekday_averages: dict) -> list[float]:
    if not day_sequence:
        return [round(amount_due, 2)]

    strengths = [max(float(weekday_averages.get(day, 0.0)), 1.0) for day in day_sequence]
    total_strength = sum(strengths)
    raw_cents = [(amount_due * 100) * (strength / total_strength) for strength in strengths]
    floor_cents = [int(value) for value in raw_cents]
    remainder = int(round(amount_due * 100)) - sum(floor_cents)

    ranked = sorted(
        enumerate(raw_cents),
        key=lambda item: item[1] - floor_cents[item[0]],
        reverse=True,
    )
    for idx, _ in ranked[:remainder]:
        floor_cents[idx] += 1

    return [round(cents / 100, 2) for cents in floor_cents]


def _peak_aligned_installments(
    amount_due: float,
    count: int,
    peak_days: list[str],
    weekday_averages: dict,
    initial_offset_days: int = 0,
) -> list[dict]:
    day_sequence = _build_peak_day_sequence(peak_days, count)
    amounts = _weighted_installment_amounts(amount_due, day_sequence, weekday_averages)
    installments = []

    first_due = _next_date_for_day(day_sequence[0], initial_offset_days)
    installments.append({"due_date": first_due.isoformat(), "amount": amounts[0]})

    previous_due = first_due
    for idx in range(1, count):
        # Keep offers on strong earning days while avoiding back-to-back dates.
        search_start = previous_due + timedelta(days=6)
        due = _next_date_on_or_after(day_sequence[idx], search_start)
        installments.append({"due_date": due.isoformat(), "amount": amounts[idx]})
        previous_due = due

    return installments


def _installment_count_for_amount(amount_due: float) -> int:
    if amount_due <= SMALL_BALANCE_THRESHOLD:
        return 1
    return max(2, min(MAX_INSTALLMENTS, int(math.ceil(amount_due / TARGET_INSTALLMENT_SIZE))))


def _postpone_days_for_small_amount(amount_due: float) -> int:
    if amount_due <= 40:
        return 5
    if amount_due <= 60:
        return 4
    return 3


def _counter_offer_from_existing_plan(
    amount_due: float,
    current_plan: dict,
    peak_days: list[str],
    weekday_averages: dict,
) -> dict | None:
    installments = current_plan.get("installments") or []
    if not installments:
        return None

    current_count = len(installments)
    if current_count == 1 and amount_due <= SMALL_BALANCE_THRESHOLD:
        current_due = installments[0].get("due_date")
        try:
            base_date = datetime.fromisoformat(str(current_due)).date()
        except Exception:
            base_date = datetime.now(SGT).date()
        postpone_days = _postpone_days_for_small_amount(amount_due)
        due_date = base_date + timedelta(days=postpone_days)
        return {
            "plan_type": "deferred_single",
            "installments": [{"due_date": due_date.isoformat(), "amount": round(amount_due, 2)}],
            "total_amount": round(amount_due, 2),
            "peak_day_aligned": False,
            "summary": f"Single payment deferred by {postpone_days} more days to {due_date.isoformat()}.",
        }

    next_count = min(current_count + 1, MAX_INSTALLMENTS)
    installments = _peak_aligned_installments(
        amount_due=amount_due,
        count=next_count,
        peak_days=peak_days,
        weekday_averages=weekday_averages,
        initial_offset_days=7,
    )
    return {
        "plan_type": "installments",
        "installments": installments,
        "total_amount": round(amount_due, 2),
        "peak_day_aligned": True,
        "summary": f"Counter-offer with {next_count} payment(s) aligned to expected peak earning days.",
    }


@tool
def generate_repayment_plan(
    user_id: str,
    amount_due: float,
    earnings_summary: dict,
    risk_tier: str,
    negotiation_round: int,
    broken_commitments: int,
    current_plan: dict | None = None,
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
    weekday_averages = earnings_summary.get("weekday_averages") or {}
    if current_plan:
        counter_offer = _counter_offer_from_existing_plan(
            amount_due=amount_due,
            current_plan=current_plan,
            peak_days=peak_days,
            weekday_averages=weekday_averages,
        )
        if counter_offer:
            return counter_offer

    if risk_tier == "hardship":
        grace_days = 14 if negotiation_round == 0 else 21 if negotiation_round == 1 else 28
        pay_date = datetime.now(SGT).date() + timedelta(days=grace_days)
        hardship_count = _installment_count_for_amount(amount_due)
        installments = []
        if hardship_count == 1:
            installments = [{"due_date": pay_date.isoformat(), "amount": round(amount_due, 2)}]
        else:
            day_sequence = _build_peak_day_sequence(peak_days, hardship_count)
            amounts = _weighted_installment_amounts(amount_due, day_sequence, weekday_averages)
            current_due = pay_date
            for idx, day_name in enumerate(day_sequence):
                due_date = _next_date_on_or_after(day_name, current_due) if idx == 0 else _next_date_on_or_after(day_name, current_due + timedelta(days=6))
                installments.append({"due_date": due_date.isoformat(), "amount": amounts[idx]})
                current_due = due_date
        return {
            "plan_type": "grace_period" if hardship_count == 1 else "hardship_installments",
            "installments": installments,
            "total_amount": round(amount_due, 2),
            "peak_day_aligned": hardship_count > 1,
            "summary": (
                f"{grace_days}-day pause, then {hardship_count} payment(s) starting on {installments[0]['due_date']}."
            ),
        }

    count = _installment_count_for_amount(amount_due)
    if count == 1:
        postpone_days = _postpone_days_for_small_amount(amount_due)
        due_date = datetime.now(SGT).date() + timedelta(days=postpone_days)
        return {
            "plan_type": "deferred_single",
            "installments": [{"due_date": due_date.isoformat(), "amount": round(amount_due, 2)}],
            "total_amount": round(amount_due, 2),
            "peak_day_aligned": False,
            "summary": f"Single payment deferred by {postpone_days} days to {due_date.isoformat()}.",
        }

    installments = _peak_aligned_installments(
        amount_due=amount_due,
        count=count,
        peak_days=peak_days,
        weekday_averages=weekday_averages,
        initial_offset_days=7 if negotiation_round >= 2 else 0,
    )
    return {
        "plan_type": "installments",
        "installments": installments,
        "total_amount": round(amount_due, 2),
        "peak_day_aligned": True,
        "summary": f"Counter-offer with {count} payment(s) aligned to expected peak earning days.",
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
