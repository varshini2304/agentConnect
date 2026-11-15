"""Idempotent notification creation and retrieval."""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.db.models import Agent, AgentRelationship, Notification, Post
from app.services.relevance import ScoringResult


def _is_blocked(db: Session, author_id: int, recipient_id: int) -> bool:
    return db.scalar(select(AgentRelationship.id).where(
        AgentRelationship.relation == "block",
        (
            ((AgentRelationship.source_agent_id == author_id) & (AgentRelationship.target_agent_id == recipient_id))
            | ((AgentRelationship.source_agent_id == recipient_id) & (AgentRelationship.target_agent_id == author_id))
        ),
    ).limit(1)) is not None


def create_selected_notifications(
    db: Session, post: Post, results: list[ScoringResult]
) -> list[Notification]:
    """Create only selected, active, non-author, non-blocked notifications."""
    author_id = post.author_agent_id
    for result in results:
        if not result.selected or result.agent_id == author_id:
            continue
        agent = db.get(Agent, result.agent_id)
        if (agent is None or agent.company_id != post.company_id or not agent.is_active
                or _is_blocked(db, author_id, result.agent_id)):
            continue
        exists = db.scalar(select(Notification.id).where(
            Notification.post_id == post.id,
            Notification.recipient_agent_id == result.agent_id,
        ))
        if exists is not None:
            continue
        row = Notification(
            company_id=post.company_id,
            post_id=post.id,
            recipient_agent_id=result.agent_id,
            score=result.final_score,
            reason_json=result.to_dict(),
            status="pending",
        )
        try:
            with db.begin_nested():
                db.add(row)
                db.flush()
        except IntegrityError:
            # A concurrent request already created the unique notification.
            continue
    db.commit()
    return list(db.scalars(
        select(Notification)
        .options(joinedload(Notification.recipient))
        .where(Notification.post_id == post.id, Notification.company_id == post.company_id,
               Notification.recipient_agent_id.in_(select(Agent.id).where(Agent.company_id == post.company_id)))
        .order_by(Notification.id)
    ))


def list_notifications(db: Session, limit: int = 50, offset: int = 0) -> list[Notification]:
    return list(db.scalars(
        select(Notification).options(joinedload(Notification.recipient))
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(limit).offset(offset)
    ))


def mark_notification_read(db: Session, notification_id: int) -> Notification | None:
    notification = db.scalar(
        select(Notification).options(joinedload(Notification.recipient))
        .where(Notification.id == notification_id)
    )
    if notification is None:
        return None
    if notification.read_at is None:
        notification.read_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(notification)
    return notification
