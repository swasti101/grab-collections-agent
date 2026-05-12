import json
import math
import random
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytz
from faker import Faker
from sqlmodel import Session, delete, select

import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.health_score import calculate_health_score_data
from db.database import (
    CommitmentBreach,
    Earning,
    FinancialHealthScore,
    Negotiation,
    Payment,
    create_db_and_tables,
    engine,
)

fake = Faker()
random.seed(42)
np.random.seed(42)
SGT = pytz.timezone("Asia/Singapore")

PERSONAS = [
    ("GW001", "Siti Noor", "ride_hailing", "low", 0, "Steady high earner, peaks Fri/Sat nights"),
    ("GW002", "Ahmad Razali", "delivery", "medium", 0, "Volatile income, peaks weekday lunch/dinner"),
    ("GW003", "Priya Pillai", "delivery", "hardship", 0, "Income dropped 40% last 2 weeks"),
    ("GW004", "Budi Santoso", "ride_hailing", "medium", 1, "Accepted once before, did not pay"),
    ("GW005", "Linh Nguyen", "merchant", "low", 0, "Very stable business owner pattern"),
    ("GW006", "Ravi Kumar", "ride_hailing", "high", 2, "Accepted twice, broke both"),
    ("GW007", "Mei Lin", "delivery", "low", 0, "Part-time, earns well on weekends only"),
    ("GW008", "Farid Hassan", "ride_hailing", "high", 3, "Accepted 3 times, broke all"),
    ("GW009", "Ananya Sharma", "merchant", "medium", 0, "Growing business, improving trend"),
    ("GW010", "Zul Ariffin", "delivery", "hardship", 1, "Very low income and one broken commitment"),
]

AMOUNTS = {"low": 150.0, "medium": 250.0, "high": 400.0, "hardship": 200.0}


def _earning_amount(risk: str, gig_type: str, day: datetime, idx: int) -> float:
    weekday = day.weekday()
    if risk == "hardship" and idx >= 45:
        mean, std = 40, 15
    elif risk == "low":
        mean, std = 180, 20
    elif risk == "medium":
        mean, std = 120, 45
    elif risk == "high":
        mean, std = 90, 70
    else:
        mean, std = 120, 35

    multiplier = 1.0
    if gig_type == "ride_hailing":
        multiplier = 2.0 if weekday in (4, 5) else 0.75
    elif gig_type == "delivery":
        multiplier = 1.25 if weekday < 5 else 0.7
    elif gig_type == "merchant":
        multiplier = 1.1 if weekday < 5 else 0.85

    if gig_type == "merchant" and risk == "medium":
        multiplier += idx * 0.008
    if gig_type == "delivery" and risk == "low":
        multiplier = 1.8 if weekday in (5, 6) else 0.45

    return round(max(8.0, np.random.normal(mean * multiplier, std)), 2)


def _peak_hour(gig_type: str) -> int:
    if gig_type == "ride_hailing":
        return random.randint(20, 22)
    if gig_type == "delivery":
        return random.choice([12, 18, 19])
    return random.randint(10, 17)


def _trips(amount: float, gig_type: str) -> int:
    divisor = {"ride_hailing": 18, "delivery": 8, "merchant": 25}[gig_type]
    return max(1, int(amount / divisor + random.randint(-2, 3)))


def seed_database() -> None:
    create_db_and_tables()
    today = datetime.now(SGT).date()
    with Session(engine) as session:
        for table in [CommitmentBreach, Negotiation, FinancialHealthScore, Earning, Payment]:
            session.exec(delete(table))
        session.commit()

        for user_id, name, gig_type, risk, broken, notes in PERSONAS:
            for idx in range(60):
                day = today - timedelta(days=59 - idx)
                amount = _earning_amount(risk, gig_type, datetime.combine(day, datetime.min.time()), idx)
                session.add(
                    Earning(
                        user_id=user_id,
                        date=day,
                        amount=amount,
                        hour_of_peak=_peak_hour(gig_type),
                        trips_or_orders=_trips(amount, gig_type),
                        gig_type=gig_type,
                    )
                )

            days_overdue = {"low": 4, "medium": 10, "high": 18, "hardship": 13}[risk] + broken
            payment = Payment(
                user_id=user_id,
                name=name,
                gig_type=gig_type,
                amount_due=AMOUNTS[risk],
                due_date=today - timedelta(days=days_overdue),
                days_overdue=days_overdue,
                prior_rejections=1 if risk in ("medium", "high") else 0,
                broken_commitments=broken,
                restructuring_frozen=broken >= 2,
                status="escalated" if broken >= 2 else "overdue",
            )
            session.add(payment)
            session.flush()

            for breach_no in range(1, broken + 1):
                accepted_at = SGT.localize(datetime.combine(today - timedelta(days=28 - breach_no * 5), datetime.min.time())).replace(hour=14)
                due_date = (accepted_at + timedelta(days=7)).date()
                nego = Negotiation(
                    user_id=user_id,
                    round=breach_no - 1,
                    plan_offered=json.dumps(
                        {
                            "plan_type": "installments",
                            "installments": [{"due_date": due_date.isoformat(), "amount": round(payment.amount_due / 2, 2)}],
                            "total_amount": payment.amount_due,
                        }
                    ),
                    user_response="accepted",
                    commitment_kept=False,
                    agent_message=f"Historical plan accepted by {name}; first installment was missed.",
                    timestamp=accepted_at.replace(tzinfo=None),
                )
                session.add(nego)
                session.flush()
                session.add(
                    CommitmentBreach(
                        user_id=user_id,
                        payment_id=payment.id,
                        negotiation_id=nego.id,
                        plan_accepted_at=accepted_at.replace(tzinfo=None),
                        installment_due_date=due_date,
                        installment_amount=round(payment.amount_due / 2, 2),
                        breach_detected_at=(accepted_at + timedelta(days=8)).replace(tzinfo=None),
                        breach_number=breach_no,
                    )
                )

        session.commit()

    for user_id, *_ in PERSONAS:
        calculate_health_score_data(user_id)

    with Session(engine) as session:
        counts = {
            "earnings": len(session.exec(select(Earning)).all()),
            "payments": len(session.exec(select(Payment)).all()),
            "negotiations": len(session.exec(select(Negotiation)).all()),
            "commitment_breaches": len(session.exec(select(CommitmentBreach)).all()),
            "financial_health_scores": len(session.exec(select(FinancialHealthScore)).all()),
        }
    print(json.dumps(counts, indent=2))


if __name__ == "__main__":
    seed_database()
