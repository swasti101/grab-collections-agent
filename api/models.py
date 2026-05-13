from typing import Literal, Optional

from pydantic import BaseModel


class TriggerAgentRequest(BaseModel):
    user_id: str


class UserResponseRequest(BaseModel):
    state_id: str
    user_response: Literal["accepted", "rejected", "support_requested"]


class MarkPaymentMissedRequest(BaseModel):
    user_id: str
    negotiation_id: int


class SendNotificationRequest(BaseModel):
    user_id: str


class WorkerNotificationResponseRequest(BaseModel):
    notification_id: int
    user_response: Literal["accepted", "rejected", "support_requested"]


class AgentResponse(BaseModel):
    state_id: Optional[str] = None
    agent_message: Optional[str] = None
    plan: Optional[dict] = None
    nudge_at: Optional[str] = None
    risk_tier: Optional[str] = None
    financial_health: Optional[dict] = None
    restructuring_frozen: bool = False
    status: str
    escalation_summary: Optional[str] = None
    next_action: Optional[str] = None
