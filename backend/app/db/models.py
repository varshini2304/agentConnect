"""Day 1 and Day 2 SQLAlchemy models."""
from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = (Index("ix_agents_company_name", "company_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), index=True)
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    company_name: Mapped[str] = mapped_column(String(160), nullable=False)
    role: Mapped[str] = mapped_column(String(200), nullable=False)
    industry: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    interests: Mapped[list["AgentInterest"]] = relationship(
        back_populates="agent", cascade="all, delete-orphan", order_by="AgentInterest.id"
    )
    posts: Mapped[list["Post"]] = relationship(back_populates="author")
    relationships_as_source: Mapped[list["AgentRelationship"]] = relationship(
        foreign_keys="AgentRelationship.source_agent_id", back_populates="source_agent",
        cascade="all, delete-orphan",
    )
    relationships_as_target: Mapped[list["AgentRelationship"]] = relationship(
        foreign_keys="AgentRelationship.target_agent_id", back_populates="target_agent",
        cascade="all, delete-orphan",
    )


class AgentInterest(Base):
    __tablename__ = "agent_interests"
    __table_args__ = (
        UniqueConstraint("agent_id", "interest_type", "value", name="uq_agent_interest_value"),
        CheckConstraint("interest_type IN ('category', 'keyword', 'exclude')", name="ck_agent_interests_type"),
        CheckConstraint("weight >= 0", name="ck_agent_interests_nonnegative_weight"),
        Index("ix_agent_interests_type_value", "interest_type", "value"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)
    interest_type: Mapped[str] = mapped_column(String(16), nullable=False)
    value: Mapped[str] = mapped_column(String(160), nullable=False)
    weight: Mapped[float] = mapped_column(nullable=False, default=1.0)
    agent: Mapped[Agent] = relationship(back_populates="interests")


class Post(Base):
    __tablename__ = "posts"
    __table_args__ = (
        UniqueConstraint("content_hash", name="uq_posts_content_hash"),
        Index("ix_posts_created_at_id", "created_at", "id"),
        Index("ix_posts_category", "category"),
        Index("ix_posts_author_agent_id", "author_agent_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), index=True)
    author_agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False, default="manual")
    source_ref: Mapped[str | None] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    author: Mapped[Agent] = relationship(back_populates="posts")
    routing_decisions: Mapped[list["RoutingDecision"]] = relationship(
        back_populates="post", cascade="all, delete-orphan"
    )
    notifications: Mapped[list["Notification"]] = relationship(back_populates="post")
    interactions: Mapped[list["AgentInteraction"]] = relationship(back_populates="post")
    comments: Mapped[list["Comment"]] = relationship(back_populates="post")


class AgentRelationship(Base):
    __tablename__ = "agent_relationships"
    __table_args__ = (
        UniqueConstraint("source_agent_id", "target_agent_id", name="uq_agent_relationship_pair"),
        CheckConstraint("relation IN ('partner', 'block')", name="ck_agent_relationship_relation"),
        CheckConstraint("weight >= 0", name="ck_agent_relationship_nonnegative_weight"),
        CheckConstraint("source_agent_id <> target_agent_id", name="ck_agent_relationship_not_self"),
        Index("ix_agent_relationship_target_relation", "target_agent_id", "relation"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    target_agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    relation: Mapped[str] = mapped_column(String(16), nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    source_agent: Mapped[Agent] = relationship(foreign_keys=[source_agent_id], back_populates="relationships_as_source")
    target_agent: Mapped[Agent] = relationship(foreign_keys=[target_agent_id], back_populates="relationships_as_target")


class RoutingDecision(Base):
    __tablename__ = "routing_decisions"
    __table_args__ = (
        UniqueConstraint("post_id", "agent_id", name="uq_routing_decision_post_agent"),
        Index("ix_routing_decisions_post_selected", "post_id", "selected"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), index=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), nullable=False)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    eligible: Mapped[bool] = mapped_column(nullable=False)
    selected: Mapped[bool] = mapped_column(nullable=False)
    reason_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    post: Mapped[Post] = relationship(back_populates="routing_decisions")
    agent: Mapped[Agent] = relationship()


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("post_id", "recipient_agent_id", name="uq_notification_post_recipient"),
        CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed', 'skipped')",
            name="ck_notification_status",
        ),
        Index("ix_notifications_recipient_created", "recipient_agent_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), index=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), nullable=False)
    recipient_agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    reason_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    post: Mapped[Post] = relationship(back_populates="notifications")
    recipient: Mapped[Agent] = relationship()
    interaction: Mapped["AgentInteraction | None"] = relationship(back_populates="notification", uselist=False)


class AgentInteraction(Base):
    __tablename__ = "agent_interactions"
    __table_args__ = (
        UniqueConstraint("post_id", "agent_id", name="uq_interaction_post_agent"),
        UniqueConstraint("notification_id", name="uq_interaction_notification"),
        CheckConstraint("status IN ('running', 'responded', 'skipped', 'failed')", name="ck_interaction_status"),
        Index("ix_interactions_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), index=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), nullable=False)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False)
    notification_id: Mapped[int] = mapped_column(ForeignKey("notifications.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    decision_json: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(String(240))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    post: Mapped[Post] = relationship(back_populates="interactions")
    agent: Mapped[Agent] = relationship()
    notification: Mapped[Notification] = relationship(back_populates="interaction")
    comment: Mapped["Comment | None"] = relationship(back_populates="interaction", uselist=False)


class Comment(Base):
    __tablename__ = "comments"
    __table_args__ = (
        UniqueConstraint("post_id", "agent_id", name="uq_comment_post_agent"),
        UniqueConstraint("interaction_id", name="uq_comment_interaction"),
        Index("ix_comments_post_created", "post_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), index=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), nullable=False)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False)
    interaction_id: Mapped[int] = mapped_column(ForeignKey("agent_interactions.id", ondelete="CASCADE"), nullable=False)
    content: Mapped[str] = mapped_column(String(400), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    post: Mapped[Post] = relationship(back_populates="comments")
    agent: Mapped[Agent] = relationship()
    interaction: Mapped[AgentInteraction] = relationship(back_populates="comment")
