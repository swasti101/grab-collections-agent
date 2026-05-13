import os
from contextlib import contextmanager
from datetime import date as Date
from datetime import datetime as DateTime
from typing import Optional

from dotenv import load_dotenv
from sqlmodel import Field, Session, SQLModel, create_engine

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./grab_collections.db")
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, echo=False, connect_args=connect_args)


class Earning(SQLModel, table=True):
    __tablename__ = "earnings"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str = Field(index=True)
    date: Date = Field(index=True)
    amount: float
    hour_of_peak: int
    trips_or_orders: int
    gig_type: str


class Payment(SQLModel, table=True):
    __tablename__ = "payments"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str = Field(index=True, unique=True)
    name: str
    gig_type: str
    amount_due: float
    due_date: Date
    days_overdue: int
    prior_rejections: int = 0
    broken_commitments: int = 0
    restructuring_frozen: bool = False
    status: str = "overdue"


class Negotiation(SQLModel, table=True):
    __tablename__ = "negotiations"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str = Field(index=True)
    round: int
    plan_offered: str
    user_response: str
    commitment_kept: Optional[bool] = None
    agent_message: str
    timestamp: DateTime = Field(default_factory=DateTime.utcnow)


class CommitmentBreach(SQLModel, table=True):
    __tablename__ = "commitment_breaches"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str = Field(index=True)
    payment_id: int = Field(index=True)
    negotiation_id: int = Field(index=True)
    plan_accepted_at: DateTime
    installment_due_date: Date
    installment_amount: float
    breach_detected_at: DateTime
    breach_number: int


class FinancialHealthScore(SQLModel, table=True):
    __tablename__ = "financial_health_scores"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str = Field(index=True, unique=True)
    score: int
    label: str
    component_scores: str
    insight: str = ""
    computed_at: DateTime = Field(default_factory=DateTime.utcnow)


class AgentSession(SQLModel, table=True):
    __tablename__ = "agent_sessions"

    state_id: str = Field(primary_key=True)
    user_id: str = Field(index=True)
    state_json: str
    created_at: DateTime = Field(default_factory=DateTime.utcnow)
    updated_at: DateTime = Field(default_factory=DateTime.utcnow)


class WorkerNotification(SQLModel, table=True):
    __tablename__ = "worker_notifications"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str = Field(index=True)
    payment_id: int = Field(index=True)
    state_id: str = Field(index=True)
    message: str
    repayment_plan: str = "{}"
    status: str = "unread"
    escalation_summary: Optional[str] = None
    created_at: DateTime = Field(default_factory=DateTime.utcnow)
    updated_at: DateTime = Field(default_factory=DateTime.utcnow)


def create_db_and_tables() -> None:
    SQLModel.metadata.create_all(engine)


@contextmanager
def get_session():
    with Session(engine) as session:
        yield session
