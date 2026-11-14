"""Per-notification agent interaction lifecycle, including failed retries."""
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.adapters.gemini import ProviderError
from app.db.models import Agent, AgentInteraction, Comment, Notification, Post
from app.services.response_generation import (
    AgentContext, AgentResponseService, InvalidDecisionError, PolicyViolationError, PostContext,
)


class RetryNotAllowedError(Exception):
    pass


def _now():
    return datetime.now(timezone.utc)


def _safe_error(exc: Exception) -> str:
    code = getattr(exc, "error_code", "processing_error")
    message = getattr(exc, "safe_message", "The agent could not complete this interaction.")
    if isinstance(exc, PolicyViolationError):
        code, message = exc.error_code, exc.safe_message
    elif isinstance(exc, InvalidDecisionError):
        code, message = exc.error_code, exc.safe_message
    elif isinstance(exc, ProviderError):
        code, message = exc.error_code, exc.safe_message
    return f"{code}: {message}"[:240]


class AgentRunner:
    def __init__(self, response_service: AgentResponseService):
        self.response_service = response_service

    def run_post(self, db: Session, post_id: int) -> list[AgentInteraction]:
        notification_ids = list(db.scalars(
            select(Notification.id).where(Notification.post_id == post_id)
            .order_by(Notification.recipient_agent_id)
        ))
        interactions = []
        for notification_id in notification_ids:
            try:
                interaction = self.process_notification(db, notification_id)
                if interaction is not None:
                    interactions.append(interaction)
            except Exception as exc:
                db.rollback()
                notification = db.get(Notification, notification_id)
                if notification is not None:
                    notification.status = "failed"
                    interaction = db.scalar(select(AgentInteraction).where(
                        AgentInteraction.notification_id == notification_id
                    ))
                    if interaction is not None and interaction.status == "running":
                        interaction.status = "failed"
                        interaction.error = _safe_error(exc)
                        interaction.completed_at = _now()
                    db.commit()
        return interactions

    def process_notification(self, db: Session, notification_id: int) -> AgentInteraction | None:
        notification = db.scalar(
            select(Notification)
            .options(
                joinedload(Notification.post),
                joinedload(Notification.recipient).selectinload(Agent.interests),
            )
            .where(Notification.id == notification_id)
        )
        if notification is None:
            return None

        interaction = db.scalar(select(AgentInteraction).where(
            AgentInteraction.notification_id == notification_id
        ))
        if interaction is not None:
            return interaction

        interaction = AgentInteraction(
            post_id=notification.post_id,
            agent_id=notification.recipient_agent_id,
            notification_id=notification_id,
            status="running",
            started_at=_now(),
        )
        notification.status = "processing"
        db.add(interaction)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            return db.scalar(select(AgentInteraction).where(
                AgentInteraction.notification_id == notification_id
            ))

        try:
            agent = notification.recipient
            post = notification.post
            context = AgentContext(
                id=agent.id,
                company_name=agent.company_name,
                role=agent.role,
                industry=agent.industry,
                interests=tuple({
                    "interest_type": item.interest_type,
                    "value": item.value,
                    "weight": item.weight,
                } for item in agent.interests),
            )
            post_context = PostContext(
                id=post.id,
                title=post.title,
                category=post.category,
                content=post.content,
            )
            decision = self.response_service.decide(context, post_context)
            interaction.decision_json = {
                "provider": self.response_service.provider_name,
                "decision": decision.model_dump(mode="json"),
            }
            interaction.completed_at = _now()
            if not decision.should_respond:
                interaction.status = "skipped"
                notification.status = "skipped"
            else:
                comment = Comment(
                    post_id=post.id,
                    agent_id=agent.id,
                    interaction_id=interaction.id,
                    content=decision.comment or "",
                )
                db.add(comment)
                interaction.status = "responded"
                notification.status = "completed"
            interaction.error = None
            db.commit()
        except Exception as exc:
            db.rollback()
            interaction = db.get(AgentInteraction, interaction.id)
            notification = db.get(Notification, notification_id)
            if interaction is not None:
                interaction.status = "failed"
                interaction.error = _safe_error(exc)
                interaction.completed_at = _now()
            if notification is not None:
                notification.status = "failed"
            db.commit()
        return db.scalar(
            select(AgentInteraction)
            .options(joinedload(AgentInteraction.comment))
            .where(AgentInteraction.id == interaction.id)
        )

    def retry(self, db: Session, interaction_id: int) -> AgentInteraction:
        current = db.get(AgentInteraction, interaction_id)
        if current is None:
            raise LookupError(interaction_id)
        notification_id = current.notification_id
        claimed = db.execute(
            update(AgentInteraction)
            .where(
                AgentInteraction.id == interaction_id,
                AgentInteraction.status == "failed",
            )
            .values(
                status="running",
                error=None,
                decision_json=None,
                started_at=_now(),
                completed_at=None,
            )
        )
        if claimed.rowcount != 1:
            db.rollback()
            current = db.get(AgentInteraction, interaction_id)
            if current is None:
                raise LookupError(interaction_id)
            raise RetryNotAllowedError(current.status)
        notification = db.get(Notification, notification_id)
        if notification is None:
            db.rollback()
            raise LookupError(notification_id)
        notification.status = "processing"
        db.commit()
        return self._finish_existing(db, interaction_id)
    def _finish_existing(self, db: Session, interaction_id: int) -> AgentInteraction:
        interaction = db.scalar(
            select(AgentInteraction)
            .options(
                joinedload(AgentInteraction.notification).joinedload(Notification.post),
                joinedload(AgentInteraction.notification).joinedload(Notification.recipient).selectinload(Agent.interests),
            )
            .where(AgentInteraction.id == interaction_id)
        )
        notification = interaction.notification
        agent = notification.recipient
        post = notification.post
        try:
            context = AgentContext(
                id=agent.id, company_name=agent.company_name, role=agent.role,
                industry=agent.industry,
                interests=tuple({
                    "interest_type": item.interest_type, "value": item.value, "weight": item.weight,
                } for item in agent.interests),
            )
            decision = self.response_service.decide(
                context, PostContext(id=post.id, title=post.title, category=post.category, content=post.content)
            )
            interaction.decision_json = {
                "provider": self.response_service.provider_name,
                "decision": decision.model_dump(mode="json"),
            }
            interaction.completed_at = _now()
            if decision.should_respond:
                db.add(Comment(
                    post_id=post.id, agent_id=agent.id, interaction_id=interaction.id,
                    content=decision.comment or "",
                ))
                interaction.status = "responded"
                notification.status = "completed"
            else:
                interaction.status = "skipped"
                notification.status = "skipped"
            interaction.error = None
            db.commit()
        except Exception as exc:
            db.rollback()
            interaction = db.get(AgentInteraction, interaction_id)
            notification = db.get(Notification, interaction.notification_id)
            interaction.status = "failed"
            interaction.error = _safe_error(exc)
            interaction.completed_at = _now()
            notification.status = "failed"
            db.commit()
        return db.scalar(
            select(AgentInteraction).options(joinedload(AgentInteraction.comment))
            .where(AgentInteraction.id == interaction_id)
        )


# A class sentinel lets SQLAlchemy resolve the selectinload target without importing Agent again.


