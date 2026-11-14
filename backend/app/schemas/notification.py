"""Notification and persisted routing response schemas."""
from datetime import datetime
from typing import Literal, Any

from pydantic import BaseModel, ConfigDict

NotificationStatus = Literal["pending", "processing", "completed", "failed", "skipped"]


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    post_id: int
    recipient_agent_id: int
    score: float
    reason_json: dict[str, Any]
    status: NotificationStatus
    created_at: datetime
    read_at: datetime | None


class RoutingDecisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    post_id: int
    agent_id: int
    score: float
    eligible: bool
    selected: bool
    reason_json: dict[str, Any]
    created_at: datetime


class AgentSummary(BaseModel):
    id: int
    slug: str
    company_name: str
