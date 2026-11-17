"""Additive, tenant-scoped product records; legacy demo tables remain intact."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base, utc_now


class Company(Base):
    __tablename__ = "companies"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    network_opt_in: Mapped[bool] = mapped_column(default=False)
    policy: Mapped[dict] = mapped_column(JSON, default=dict)
    policy_version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    password_hash: Mapped[str] = mapped_column(String(256))
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CompanyRole(Base):
    __tablename__ = "company_roles"
    __table_args__ = (UniqueConstraint("company_id", "slug"), UniqueConstraint("id", "company_id"))
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    slug: Mapped[str] = mapped_column(String(100))
    is_builtin: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Permission(Base):
    __tablename__ = "permissions"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    description: Mapped[str] = mapped_column(String(200))


class RolePermissionGrant(Base):
    __tablename__ = "role_permission_grants"
    role_id: Mapped[int] = mapped_column(ForeignKey("company_roles.id", ondelete="CASCADE"), primary_key=True)
    permission_key: Mapped[str] = mapped_column(ForeignKey("permissions.key"), primary_key=True)


class CompanySettings(Base):
    __tablename__ = "company_settings"
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), primary_key=True)
    description: Mapped[str] = mapped_column(Text, default="")
    website: Mapped[str] = mapped_column(String(2000), default="")
    industry: Mapped[str] = mapped_column(String(120), default="")
    onboarding_complete: Mapped[bool] = mapped_column(default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class CompanyMember(Base):
    __tablename__ = "company_members"
    __table_args__ = (
        UniqueConstraint("company_id", "user_id"),
        ForeignKeyConstraint(["role_id", "company_id"], ["company_roles.id", "company_roles.company_id"], name="fk_membership_company_role"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(20), default="owner")
    role_id: Mapped[int | None] = mapped_column(index=True)
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LoginSession(Base):
    __tablename__ = "login_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    csrf_token_hash: Mapped[str] = mapped_column(String(64), default="")
    selected_company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CompanyInvitation(Base):
    __tablename__ = "company_invitations"
    __table_args__ = (
        ForeignKeyConstraint(["role_id", "company_id"], ["company_roles.id", "company_roles.company_id"], name="fk_invitation_company_role"),
        Index("ix_company_invitation_email_status", "company_id", "email", "status"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    email: Mapped[str] = mapped_column(String(254))
    role_id: Mapped[int] = mapped_column()
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LoginRateLimit(Base):
    __tablename__ = "login_rate_limits"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    attempts: Mapped[int] = mapped_column(default=0)


CompanyMembership = CompanyMember
AuthSession = LoginSession


class AgentAccount(Base):
    __tablename__ = "agent_accounts"
    __table_args__ = (UniqueConstraint("company_id", "slug"),)
    id: Mapped[int] = mapped_column(ForeignKey("agents.id"), primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    slug: Mapped[str] = mapped_column(String(80))
    state: Mapped[str] = mapped_column(String(16), default="draft")
    active_version_id: Mapped[int | None] = mapped_column(ForeignKey("agent_versions.id", use_alter=True))
    config_version_id: Mapped[int | None] = mapped_column(ForeignKey("agent_versions.id", use_alter=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AgentVersion(Base):
    __tablename__ = "agent_versions"
    __table_args__ = (UniqueConstraint("agent_id", "version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)
    version: Mapped[int] = mapped_column()
    config: Mapped[dict] = mapped_column(JSON)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class KnowledgeSource(Base):
    __tablename__ = "knowledge_sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    visibility: Mapped[str] = mapped_column(String(16), default="private")
    source_url: Mapped[str | None] = mapped_column(String(2000))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Publication(Base):
    __tablename__ = "publications"
    __table_args__ = (UniqueConstraint("company_id", "idempotency_key"), UniqueConstraint("company_id", "content_hash"),
                      Index("uq_publication_external_record", "company_id", "external_record_id", unique=True))
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    author_type: Mapped[str] = mapped_column(String(16))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id"))
    title: Mapped[str] = mapped_column(String(240))
    content: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(80))
    visibility: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(24), default="draft")
    idempotency_key: Mapped[str] = mapped_column(String(100))
    content_hash: Mapped[str] = mapped_column(String(64))
    external_record_id: Mapped[str | None] = mapped_column(String(160))
    source_name: Mapped[str | None] = mapped_column(String(160))
    source_reference: Mapped[str | None] = mapped_column(String(500))
    config_version_id: Mapped[int | None] = mapped_column(ForeignKey("agent_versions.id"))
    policy_version: Mapped[int] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class DiscoveryRecord(Base):
    __tablename__ = "discovery_records"
    __table_args__ = (UniqueConstraint("publication_id", "agent_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    publication_id: Mapped[int] = mapped_column(ForeignKey("publications.id"), index=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"))
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    agent_name: Mapped[str] = mapped_column(String(160))
    eligible: Mapped[bool] = mapped_column()
    selected: Mapped[bool] = mapped_column()
    score: Mapped[float] = mapped_column()
    explanation: Mapped[str] = mapped_column(Text)
    signals: Mapped[dict] = mapped_column(JSON)
    audit_json: Mapped[dict] = mapped_column(JSON, default=dict)


class StoredEmbedding(Base):
    __tablename__ = "stored_embeddings"
    __table_args__ = (
        UniqueConstraint("entity_type", "entity_id", "model_name", name="uq_stored_embeddings_entity"),
        Index("ix_stored_embeddings_lookup", "entity_type", "entity_id"),
        Index("ix_stored_embeddings_hash", "entity_type", "content_hash"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(32), index=True)
    entity_id: Mapped[int] = mapped_column(Integer, index=True)
    model_name: Mapped[str] = mapped_column(String(100))
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    embedding: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class PublishingJob(Base):
    """An authorized publishing brief; the agent independently proposes content or skips."""
    __tablename__ = "publishing_jobs"
    __table_args__ = (UniqueConstraint("company_id", "idempotency_key"), Index("ix_publishing_claim", "status", "available_at"))
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)
    requested_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    config_version_id: Mapped[int] = mapped_column(ForeignKey("agent_versions.id"))
    policy_version: Mapped[int] = mapped_column()
    title: Mapped[str] = mapped_column(String(240))
    brief: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(80))
    visibility: Mapped[str] = mapped_column(String(16), default="network")
    idempotency_key: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(24), default="pending")
    attempts: Mapped[int] = mapped_column(default=0)
    attempt_history: Mapped[list] = mapped_column(JSON, default=list)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(String(80))
    publication_id: Mapped[int | None] = mapped_column(ForeignKey("publications.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class RuntimeMutex(Base):
    __tablename__ = "runtime_mutex"
    id: Mapped[int] = mapped_column(primary_key=True)
    value: Mapped[int] = mapped_column(default=0)


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (UniqueConstraint("created_by", "idempotency_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(12))
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    publication_id: Mapped[int | None] = mapped_column(ForeignKey("publications.id"))
    idempotency_key: Mapped[str] = mapped_column(String(100))
    message_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ConversationMember(Base):
    __tablename__ = "conversation_members"
    __table_args__ = (UniqueConstraint("conversation_id", "agent_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)
    config_version_id: Mapped[int] = mapped_column(ForeignKey("agent_versions.id"))
    status: Mapped[str] = mapped_column(String(16), default="active")
    history_from_seq: Mapped[int] = mapped_column(default=1)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Invitation(Base):
    __tablename__ = "invitations"
    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    inviter_agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"))
    recipient_agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    requires_approval: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("conversation_id", "sequence"), UniqueConstraint("conversation_id", "sender_agent_id", "idempotency_key"))
    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    sequence: Mapped[int] = mapped_column()
    sender_agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"))
    sender_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    author_type: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    reply_depth: Mapped[int] = mapped_column(default=0)
    idempotency_key: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class MessageDelivery(Base):
    """Transactional outbox: one durable job for each message/recipient pair."""
    __tablename__ = "message_deliveries"
    __table_args__ = (UniqueConstraint("message_id", "agent_id"), Index("ix_delivery_claim", "status", "available_at"))
    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"))
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)
    status: Mapped[str] = mapped_column(String(24), default="pending")
    attempts: Mapped[int] = mapped_column(default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(String(80))


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (UniqueConstraint("delivery_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    delivery_id: Mapped[int] = mapped_column(ForeignKey("message_deliveries.id"))
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)
    config_version_id: Mapped[int] = mapped_column(ForeignKey("agent_versions.id"))
    policy_version: Mapped[int] = mapped_column()
    status: Mapped[str] = mapped_column(String(24), default="running")
    action: Mapped[str | None] = mapped_column(String(24))
    reason: Mapped[str | None] = mapped_column(String(500))
    provider: Mapped[str] = mapped_column(String(30))
    model: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AgentRunAttempt(Base):
    __tablename__ = "agent_run_attempts"
    __table_args__ = (UniqueConstraint("run_id", "number"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    number: Mapped[int] = mapped_column()
    status: Mapped[str] = mapped_column(String(20), default="running")
    error: Mapped[str | None] = mapped_column(String(80))
    policy_version: Mapped[int] = mapped_column()
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RunApproval(Base):
    __tablename__ = "run_approvals"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("agent_runs.id"), unique=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"))
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    content: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(String(500))


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"
    __table_args__ = (UniqueConstraint("source_type", "source_id"), Index("ix_approval_company_status", "company_id", "status", "created_at"))
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id"))
    requesting_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    action_type: Mapped[str] = mapped_column(String(50))
    source_type: Mapped[str] = mapped_column(String(30))
    source_id: Mapped[int] = mapped_column()
    proposed_content: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(50))
    reason: Mapped[str] = mapped_column(String(500))
    triggered_policy: Mapped[list] = mapped_column(JSON, default=list)
    config_version_id: Mapped[int | None] = mapped_column(ForeignKey("agent_versions.id"))
    policy_version: Mapped[int] = mapped_column()
    status: Mapped[str] = mapped_column(String(20), default="pending")
    reviewer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    decision_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewer_comments: Mapped[str | None] = mapped_column(String(1000))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_company_created", "company_id", "created_at"), Index("ix_audit_event_type", "event_type"))
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"))
    actor_type: Mapped[str] = mapped_column(String(20))
    actor_id: Mapped[str | None] = mapped_column(String(100))
    event_type: Mapped[str] = mapped_column(String(100))
    resource_type: Mapped[str] = mapped_column(String(50))
    resource_id: Mapped[str | None] = mapped_column(String(100))
    outcome: Mapped[str] = mapped_column(String(30))
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class UserNotification(Base):
    __tablename__ = "user_notifications"
    __table_args__ = (UniqueConstraint("recipient_user_id", "dedupe_key"), Index("ix_user_notification_inbox", "company_id", "recipient_user_id", "read_at", "created_at"))
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    recipient_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    category: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(200))
    resource_type: Mapped[str] = mapped_column(String(40))
    resource_id: Mapped[str] = mapped_column(String(100))
    dedupe_key: Mapped[str] = mapped_column(String(200))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
