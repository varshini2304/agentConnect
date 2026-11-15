"""Server-side validation for the visual builder and all runtime boundaries."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Limits(StrictModel):
    max_agent_messages: int = Field(default=3, ge=0, le=100)
    max_conversation_messages: int = Field(default=12, ge=1, le=1000)
    max_reply_depth: int = Field(default=6, ge=0, le=100)
    max_participants: int = Field(default=8, ge=2, le=100)
    max_concurrent_runs: int = Field(default=2, ge=1, le=20)
    max_retries: int = Field(default=3, ge=0, le=10)
    timeout_seconds: float = Field(default=30, ge=0.05, le=120)
    cooldown_seconds: float = Field(default=30, ge=0, le=86400)
    daily_runs: int = Field(default=100, ge=0, le=10000)


class CompanyPolicy(StrictModel):
    allow_public: bool = True
    allow_direct: bool = True
    allow_group: bool = True
    allow_initiation: bool = True
    allow_invitations: bool = True
    allow_replies: bool = True
    allow_knowledge: bool = True
    allow_discovery: bool = True
    emergency_paused: bool = False
    daily_execution_budget: int = Field(default=1000, ge=0, le=100000)
    allowed_actions: list[Literal["reply", "skip", "request_approval", "end_conversation"]] = Field(default_factory=lambda: ["reply", "skip", "request_approval", "end_conversation"], max_length=4)
    restricted_categories: list[str] = Field(default_factory=list, max_length=100)
    approval_categories: list[Literal["general_information", "product_announcement", "promotional_offer", "financial_claim", "partnership_proposal", "binding_commitment", "external_action"]] = Field(default_factory=list, max_length=7)
    excluded_topics: list[str] = Field(default_factory=list, max_length=100)
    require_invitation_approval: bool = True
    require_publish_approval: bool = False
    limits: Limits = Field(default_factory=Limits)
    blocked_company_ids: list[int] = Field(default_factory=list, max_length=100)
    approval_topics: list[str] = Field(default_factory=list, max_length=100)


class AgentConfig(StrictModel):
    name: str = Field(min_length=1, max_length=160)
    avatar: str = Field(default="🤖", max_length=2048)
    description: str = Field(min_length=1, max_length=2000)
    role: str = Field(min_length=1, max_length=200)
    domain: str = Field(min_length=1, max_length=120)
    purpose: str = Field(min_length=1, max_length=2000)
    responsibilities: list[str] = Field(default_factory=list, max_length=100)
    helps_with: list[str] = Field(default_factory=list, max_length=100)
    must_not_do: list[str] = Field(default_factory=list, max_length=100)
    expected_outcomes: list[str] = Field(default_factory=list, max_length=100)
    categories: list[str] = Field(default_factory=list, max_length=100)
    topics: list[str] = Field(default_factory=list, max_length=100)
    keywords: list[str] = Field(default_factory=list, max_length=100)
    excluded_topics: list[str] = Field(default_factory=list, max_length=100)
    partner_company_ids: list[int] = Field(default_factory=list, max_length=100)
    blocked_company_ids: list[int] = Field(default_factory=list, max_length=100)
    discoverable: bool = True
    tone: str = Field(default="professional", max_length=100)
    response_preferences: str = Field(default="concise", max_length=500)
    allow_public: bool = False
    allow_direct: bool = True
    allow_group: bool = True
    allow_initiation: bool = True
    allow_invitations: bool = True
    allow_replies: bool = True
    allow_knowledge: bool = True
    approval_categories: list[Literal["general_information", "product_announcement", "promotional_offer", "financial_claim", "partnership_proposal", "binding_commitment", "external_action"]] = Field(default_factory=list, max_length=7)
    discussion_topics: list[str] = Field(default_factory=list, max_length=100)
    approval_topics: list[str] = Field(default_factory=list, max_length=100)
    allowed_actions: list[Literal["reply", "skip", "request_approval", "end_conversation"]] = Field(
        default_factory=lambda: ["reply", "skip", "request_approval", "end_conversation"], max_length=4)
    allowed_publishing_categories: list[str] = Field(default_factory=list, max_length=100)
    require_approval: bool = False
    limits: Limits = Field(default_factory=Limits)
    provider: Literal["gemini", "fake"] = "gemini"
    model: str = Field(default="gemini-2.5-flash", min_length=1, max_length=120)
    temperature: float = Field(default=0.2, ge=0, le=1)
    max_output_tokens: int = Field(default=500, ge=64, le=2000)
    knowledge_source_ids: list[int] = Field(default_factory=list, max_length=100)

    @field_validator("responsibilities", "helps_with", "must_not_do", "expected_outcomes", "categories", "topics", "keywords", "excluded_topics", "discussion_topics", "approval_topics", "allowed_publishing_categories")
    @classmethod
    def bounded_phrases(cls, values):
        if any(not v.strip() or len(v) > 500 for v in values):
            raise ValueError("Entries must contain 1 to 500 characters")
        return list(dict.fromkeys(v.strip() for v in values))


class RuntimeDecision(StrictModel):
    action: Literal["reply", "skip", "request_approval", "end_conversation"]
    reason: str = Field(min_length=1, max_length=500)
    content: str | None = Field(default=None, max_length=400)

    @model_validator(mode="after")
    def check_content(self):
        if self.action == "reply" and not self.content:
            raise ValueError("reply requires content")
        if self.action in ("skip", "end_conversation") and self.content:
            raise ValueError("Only replies and approval requests can contain content")
        return self


class ConversationCreate(StrictModel):
    kind: Literal["direct", "group"]
    title: str = Field(min_length=1, max_length=200)
    agent_id: int = Field(gt=0)
    recipient_agent_id: int | None = Field(default=None, gt=0)
    publication_id: int | None = Field(default=None, gt=0)
    idempotency_key: str = Field(min_length=1, max_length=100)


class MessageCreate(StrictModel):
    agent_id: int = Field(gt=0)
    content: str = Field(min_length=1, max_length=4000)
    idempotency_key: str = Field(min_length=1, max_length=100)


class InvitationCreate(StrictModel):
    inviter_agent_id: int = Field(gt=0)
    recipient_agent_id: int = Field(gt=0)


class AcceptInput(StrictModel):
    accept: bool


class MemberInput(StrictModel):
    agent_id: int = Field(gt=0)
    by_agent_id: int | None = Field(default=None, gt=0)
