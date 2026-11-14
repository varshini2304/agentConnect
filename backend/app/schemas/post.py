"""Post, demo and full post-detail response schemas."""
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.agent import AgentRead
from app.schemas.interaction import CommentRead, InteractionRead
from app.schemas.notification import AgentSummary, NotificationRead, RoutingDecisionRead


class PostCreate(BaseModel):
    author_agent_id: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=240)
    content: str = Field(min_length=1, max_length=10000)
    category: str = Field(min_length=1, max_length=80)
    source_type: str = Field(default="manual", min_length=1, max_length=40)
    source_ref: str | None = Field(default=None, max_length=160)

    @field_validator("title", "content", "category", "source_type")
    @classmethod
    def normalize_whitespace(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("value cannot be blank")
        return value

    @field_validator("category")
    @classmethod
    def normalize_category(cls, value: str) -> str:
        return value.lower()


class SourcePayload(BaseModel):
    scenario_id: str = Field(min_length=1, max_length=80)
    author_agent_slug: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=240)
    content: str = Field(min_length=1, max_length=10000)
    category: str = Field(min_length=1, max_length=80)
    source_type: str = Field(min_length=1, max_length=40)
    source_ref: str = Field(min_length=1, max_length=160)


class PostAuthorRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    slug: str
    company_name: str


class PostRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    author_agent_id: int
    title: str
    content: str
    category: str
    source_type: str
    source_ref: str | None
    created_at: datetime
    author: PostAuthorRead


class PostDetailRead(PostRead):
    routing_decisions: list[RoutingDecisionRead] = Field(default_factory=list)
    selected_recipients: list[AgentSummary] = Field(default_factory=list)
    notifications: list[NotificationRead] = Field(default_factory=list)
    interactions: list[InteractionRead] = Field(default_factory=list)
    comments: list[CommentRead] = Field(default_factory=list)


class PostFeed(BaseModel):
    items: list[PostRead]
    limit: int
    offset: int


class DemoRequest(BaseModel):
    scenario_id: str = Field(min_length=1, max_length=80)


class DemoResponse(BaseModel):
    scenario_id: str
    created: bool
    post: PostDetailRead
