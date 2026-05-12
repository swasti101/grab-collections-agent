import json
import math
from datetime import datetime
from typing import Callable, Optional

import numpy as np
from sqlmodel import select

from db.database import Earning, FinancialHealthScore, Payment, get_session


def _clamp(value: float, low: int = 0, high: int = 100) -> int:
    return int(max(low, min(high, round(value))))


def _label(score: int) -> str:
    if score >= 76:
        return "Healthy"
    if score >= 51:
        return "Fair"
    if score >= 26:
        return "At Risk"
    return "Critical"


def _score_cv(cv: float) -> int:
    if cv < 0.2:
        return _clamp(100 - cv * 50, 90, 100)
    if cv < 0.4:
        return _clamp(90 - (cv - 0.2) * 100, 70, 89)
    if cv < 0.6:
        return _clamp(70 - (cv - 0.4) * 125, 45, 69)
    if cv < 0.8:
        return _clamp(45 - (cv - 0.6) * 125, 20, 44)
    return _clamp(20 - min(cv - 0.8, 1.0) * 20, 0, 19)


def _score_trend(slope: float) -> int:
    if slope > 10:
        return _clamp(85 + min(slope - 10, 15), 85, 100)
    if slope > 3:
        return _clamp(65 + (slope - 3) * 2.7, 65, 84)
    if slope >= -3:
        return _clamp(57 + slope * 2, 50, 64)
    if slope < -10:
        return _clamp(19 + max(slope + 10, -20), 0, 19)
    return _clamp(49 + (slope + 3) * 4.1, 20, 49)


def _score_repayment(repayment_ratio: float, broken: int) -> int:
    base = _clamp(repayment_ratio * 100)
    if repayment_ratio == 1.0 and broken == 0:
        base = 100
    elif repayment_ratio >= 0.8 and broken == 0:
        base = max(80, base)
    if broken == 1:
        return min(base, 55)
    if broken == 2:
        return min(base, 30)
    if broken >= 3:
        return min(base, 10)
    return base


def _score_dti(ratio: float) -> int:
    if ratio < 0.5:
        return _clamp(100 - ratio * 40, 80, 100)
    if ratio < 1.0:
        return _clamp(80 - (ratio - 0.5) * 50, 55, 79)
    if ratio < 2.0:
        return _clamp(55 - (ratio - 1.0) * 25, 30, 54)
    return _clamp(30 - min(ratio - 2.0, 3.0) * 10, 0, 29)


def _recovery_score(amounts: list[float]) -> float:
    if len(amounts) < 21:
        return 0.5
    weekly = [sum(amounts[i : i + 7]) / 7 for i in range(0, len(amounts) - 6)]
    worst_idx = int(np.argmin(weekly))
    if worst_idx + 14 >= len(amounts):
        return 0.4
    bad_week = max(weekly[worst_idx], 1)
    next_week = sum(amounts[worst_idx + 7 : worst_idx + 14]) / 7
    normal = max(sum(amounts) / len(amounts), 1)
    return max(0.0, min(1.0, (next_week - bad_week) / normal + 0.5))


def calculate_health_score_data(user_id: str, insight_generator: Optional[Callable[[dict], str]] = None) -> dict:
    with get_session() as session:
        earnings = session.exec(
            select(Earning).where(Earning.user_id == user_id).order_by(Earning.date)
        ).all()
        payment = session.exec(select(Payment).where(Payment.user_id == user_id)).first()

        if not earnings or not payment:
            raise ValueError(f"No earnings/payment data found for {user_id}")

        amounts = [float(e.amount) for e in earnings[-60:]]
        avg_daily = sum(amounts) / len(amounts)
        std = float(np.std(amounts))
        cv = std / avg_daily if avg_daily else 1.0
        x = np.arange(min(30, len(amounts)))
        y = np.array(amounts[-len(x) :])
        slope = float(np.polyfit(x, y, 1)[0]) if len(x) > 1 else 0.0

        repayment_ratio = max(0.0, 1.0 - (payment.prior_rejections * 0.12) - (payment.broken_commitments * 0.25))
        recovery_raw = _recovery_score(amounts)
        monthly_income = max(avg_daily * 22, 1)
        dti_ratio = payment.amount_due / monthly_income

        components = {
            "income_stability": _score_cv(cv),
            "earnings_trend": _score_trend(slope),
            "repayment_record": _score_repayment(repayment_ratio, payment.broken_commitments),
            "debt_to_income": _score_dti(dti_ratio),
            "recovery_speed": _clamp(recovery_raw * 100),
        }
        score = int(
            components["income_stability"] * 0.30
            + components["earnings_trend"] * 0.20
            + components["repayment_record"] * 0.25
            + components["debt_to_income"] * 0.15
            + components["recovery_speed"] * 0.10
        )
        result = {
            "score": score,
            "label": _label(score),
            "component_scores": components,
            "insight": "",
        }

        if insight_generator:
            try:
                result["insight"] = insight_generator(
                    {
                        "user_id": user_id,
                        "name": payment.name,
                        "gig_type": payment.gig_type,
                        "score": score,
                        "label": result["label"],
                        "components": components,
                        "broken_commitments": payment.broken_commitments,
                        "amount_due": payment.amount_due,
                    }
                )
            except Exception:
                result["insight"] = ""

        if not result["insight"]:
            result["insight"] = (
                f"{payment.name}'s financial health is {result['label'].lower()}, with "
                f"stability at {components['income_stability']} and repayment record at "
                f"{components['repayment_record']}."
            )

        existing = session.exec(
            select(FinancialHealthScore).where(FinancialHealthScore.user_id == user_id)
        ).first()
        payload = json.dumps(components)
        if existing:
            existing.score = score
            existing.label = result["label"]
            existing.component_scores = payload
            existing.insight = result["insight"]
            existing.computed_at = datetime.utcnow()
        else:
            session.add(
                FinancialHealthScore(
                    user_id=user_id,
                    score=score,
                    label=result["label"],
                    component_scores=payload,
                    insight=result["insight"],
                )
            )
        session.commit()
        return result
