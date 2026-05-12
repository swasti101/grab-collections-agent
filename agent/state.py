from typing import List, Optional, TypedDict


class AgentState(TypedDict):
    user_id: str
    payment_id: int
    amount_due: float
    days_overdue: int
    prior_rejections: int

    broken_commitments: int
    restructuring_frozen: bool

    earnings_summary: Optional[dict]
    financial_health: Optional[dict]
    risk_tier: Optional[str]
    risk_score: Optional[int]
    risk_factors: Optional[List[str]]
    recommended_tone: Optional[str]
    can_self_serve: Optional[bool]
    repayment_plan: Optional[dict]
    nudge_scheduled_at: Optional[str]
    agent_message: Optional[str]
    negotiation_round: int
    user_response: Optional[str]
    status: str
    escalation_summary: Optional[str]
    conversation_history: List[dict]
