"""Interaction and comment response schemas."""
from datetime import datetime
from typing import Literal, Any

from pydantic import BaseModel, ConfigDict

InteractionStatus = Literal["running", "responded", "skipped", "failed"]


class CommentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    post_id: int
    agent_id: int
    interaction_id: int
    content: str
    created_at: datetime


class InteractionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    post_id: int
    agent_id: int
    notification_id: int
    status: InteractionStatus
    decision_json: dict[str, Any] | None
    error: str | None
    started_at: datetime
    completed_at: datetime | None
    comment: CommentRead | None = None
