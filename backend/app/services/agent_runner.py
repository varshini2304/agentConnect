"""Per-notification interactions use the shared policy and execution reservations."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.db.models import Agent, AgentInteraction, Comment, Notification, Post
from app.db.network import AgentAccount, AgentRun, AgentRunAttempt, Company, MessageDelivery, PublishingJob
from app.schemas.network import RuntimeDecision
from app.services.governance import company_budget_exhausted, legacy_attempt_count, legacy_running_count
from app.services.locking import lock_runtime
from app.services.policy import evaluate_action
from app.services.response_generation import (
    AgentContext, AgentResponseService, PolicyViolationError, PostContext,
)
from app.services.security import aware
from app.services.workspace import config_for, effective_limits, reject_private_material


class RetryNotAllowedError(Exception):
    pass


class LegacyGovernanceError(PolicyViolationError):
    safe_message = "Use governed conversations for review."

    def __init__(self, code="policy_rejected"):
        self.error_code = code


def _now():
    return datetime.now(timezone.utc)


def _safe_error(exc: Exception) -> str:
    code = getattr(exc, "error_code", "processing_error")
    message = getattr(exc, "safe_message", "The agent could not complete this interaction.")
    return f"{code}: {message}"[:240]


def _same_tenant(notification: Notification) -> bool:
    return bool(notification.post is not None and notification.recipient is not None
                and notification.post.author is not None
                and notification.company_id == notification.post.company_id
                == notification.recipient.company_id == notification.post.author.company_id)


def _lock(db, company_id):
    # Tenantless rows exist only in the retained isolated database unit fixtures.
    if company_id is not None:
        lock_runtime(db)


def _notification(db, notification_id):
    return db.scalar(select(Notification).options(
        joinedload(Notification.post).joinedload(Post.author),
        joinedload(Notification.recipient).selectinload(Agent.interests),
    ).where(Notification.id == notification_id).execution_options(populate_existing=True))


def _interaction(db, interaction_id):
    return db.scalar(select(AgentInteraction).options(joinedload(AgentInteraction.comment))
                     .where(AgentInteraction.id == interaction_id).execution_options(populate_existing=True))


def _governance(db, notification, pinned=None, decision=None):
    if not _same_tenant(notification):
        raise LegacyGovernanceError()
    if notification.company_id is None:
        return {}
    account = db.get(AgentAccount, notification.recipient_agent_id)
    company = db.get(Company, notification.company_id)
    current = config_for(db, account, active=True) if account else {}
    if (company is None or company.status != "active" or account is None
            or account.company_id != company.id or account.state != "active"
            or not notification.recipient.is_active or not current):
        raise LegacyGovernanceError()
    source = f"{notification.post.title} {notification.post.content} {notification.post.category}"
    configs = [pinned, current] if pinned else [current]
    evaluation = evaluate_action(action="message.reply", content=(decision.comment or "") if decision else "",
        company_policy=company.policy, configs=configs, source_content=source,
        business_category=notification.post.category)
    if evaluation.disposition != "allow":
        raise LegacyGovernanceError()
    try:
        reject_private_material(db, company.id, notification.post.title, notification.post.content)
        if decision:
            reject_private_material(db, company.id, decision.reason, decision.comment or "")
        if decision and decision.should_respond:
            from app.services.runtime import validate_reply
            validate_reply(db, account, pinned or current, company,
                           RuntimeDecision(action="reply", reason=decision.reason, content=decision.comment),
                           source_content=source, business_category=notification.post.category)
            reject_private_material(db, company.id, "", decision.comment or "")
    except (HTTPException, PolicyViolationError):
        raise LegacyGovernanceError() from None
    return current


def _budget(db, notification, config, now):
    if notification.company_id is None:
        return
    company = db.get(Company, notification.company_id)
    limits = effective_limits(config, company.policy)
    agent_id = notification.recipient_agent_id
    processing = legacy_running_count(db, agent_id)
    processing += db.scalar(select(func.count(MessageDelivery.id)).where(MessageDelivery.agent_id == agent_id, MessageDelivery.status == "processing"))
    processing += db.scalar(select(func.count(PublishingJob.id)).where(PublishingJob.agent_id == agent_id, PublishingJob.status == "processing"))
    if processing >= limits["max_concurrent_runs"]:
        raise LegacyGovernanceError("concurrency_limit")
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    executions = legacy_attempt_count(db, now=now, agent_id=agent_id)
    executions += db.scalar(select(func.count(AgentRunAttempt.id)).join(AgentRun, AgentRun.id == AgentRunAttempt.run_id)
                            .where(AgentRun.agent_id == agent_id, AgentRunAttempt.started_at >= midnight))
    executions += sum(1 for history in db.scalars(select(PublishingJob.attempt_history).where(PublishingJob.agent_id == agent_id))
                      for attempt in history if attempt.get("started_at", "") >= midnight.isoformat())
    if executions >= limits["daily_runs"] or company_budget_exhausted(db, company, now):
        raise LegacyGovernanceError("daily_budget")
    from app.services.publishing_runtime import latest_output
    latest = latest_output(db, agent_id)
    if latest and latest + timedelta(seconds=limits["cooldown_seconds"]) > now:
        raise LegacyGovernanceError("cooldown")


def recover_legacy_runs(db, now):
    """Release expired reservations; callers hold the runtime mutex."""
    now = aware(now)
    running = list(db.scalars(select(AgentInteraction).where(AgentInteraction.status == "running",
                                                           AgentInteraction.company_id.is_not(None))))
    for interaction in running:
        account = db.get(AgentAccount, interaction.agent_id)
        company = db.get(Company, interaction.company_id)
        config = config_for(db, account, active=True) if account else {}
        limits = effective_limits(config, company.policy if company else {})
        history = (interaction.decision_json or {}).get("attempt_history") or []
        started = history[-1].get("started_at") if history else None
        try:
            started_at = aware(datetime.fromisoformat(started)) if started else aware(interaction.started_at)
        except (TypeError, ValueError):
            started_at = aware(interaction.started_at)
        if started_at + timedelta(seconds=limits["timeout_seconds"] + 15) > now:
            continue
        if not history:
            history = [{"started_at": started_at.isoformat()}]
        history = [*history[:-1], {**history[-1], "status": "abandoned", "completed_at": now.isoformat()}]
        interaction.status, interaction.completed_at = "failed", now
        interaction.error = "lease_expired: The previous legacy execution did not finish."
        interaction.decision_json = {"attempt_history": history}
        notification = db.get(Notification, interaction.notification_id)
        if (notification and notification.company_id == interaction.company_id
                and notification.recipient_agent_id == interaction.agent_id and notification.post_id == interaction.post_id):
            notification.status = "failed"
    db.flush()


@dataclass(frozen=True)
class Work:
    interaction_id: int
    company_id: int | None
    attempt_id: str
    config: dict
    agent: AgentContext
    post: PostContext


class AgentRunner:
    def __init__(self, response_service: AgentResponseService):
        self.response_service = response_service

    def run_post(self, db: Session, post_id: int) -> list[AgentInteraction]:
        post = db.get(Post, post_id)
        if post is None:
            return []
        notification_ids = list(db.scalars(select(Notification.id).where(
            Notification.post_id == post_id, Notification.company_id == post.company_id,
            Notification.recipient_agent_id.in_(select(Agent.id).where(Agent.company_id == post.company_id)),
        ).order_by(Notification.recipient_agent_id)))
        interactions = []
        for notification_id in notification_ids:
            try:
                interaction = self.process_notification(db, notification_id)
                if interaction is not None:
                    interactions.append(interaction)
            except Exception as exc:
                db.rollback()
                notification = db.get(Notification, notification_id)
                if notification is None:
                    continue
                _lock(db, notification.company_id)
                notification = _notification(db, notification_id)
                if notification is not None and _same_tenant(notification):
                    notification.status = "failed"
                    interaction = db.scalar(select(AgentInteraction).where(
                        AgentInteraction.notification_id == notification_id,
                        AgentInteraction.company_id == notification.company_id,
                        AgentInteraction.post_id == notification.post_id,
                        AgentInteraction.agent_id == notification.recipient_agent_id,
                    ))
                    if interaction is not None and interaction.status == "running":
                        interaction.status, interaction.error, interaction.completed_at = "failed", _safe_error(exc), _now()
                db.commit()
        return interactions

    def process_notification(self, db: Session, notification_id: int) -> AgentInteraction | None:
        work = self._claim(db, notification_id)
        return self._execute(db, work) if isinstance(work, Work) else work

    def retry(self, db: Session, interaction_id: int) -> AgentInteraction:
        current = db.get(AgentInteraction, interaction_id)
        if current is None:
            raise LookupError(interaction_id)
        work = self._claim(db, current.notification_id, retry_id=interaction_id)
        if work is None:
            raise LookupError(interaction_id)
        return self._execute(db, work) if isinstance(work, Work) else work

    def _claim(self, db, notification_id, retry_id=None):
        notification = db.get(Notification, notification_id)
        if notification is None:
            return None
        _lock(db, notification.company_id)
        if notification.company_id is not None:
            recover_legacy_runs(db, _now())
        notification = _notification(db, notification_id)
        if notification is None or not _same_tenant(notification):
            db.rollback()
            return None
        query = select(AgentInteraction).where(
            AgentInteraction.notification_id == notification_id,
            AgentInteraction.company_id == notification.company_id,
            AgentInteraction.post_id == notification.post_id,
            AgentInteraction.agent_id == notification.recipient_agent_id,
        )
        interaction = db.scalar(query)
        if retry_id is not None:
            if interaction is None or interaction.id != retry_id:
                db.rollback()
                raise LookupError(retry_id)
            if interaction.status != "failed":
                db.rollback()
                raise RetryNotAllowedError(interaction.status)
        elif interaction is not None:
            db.commit()
            return _interaction(db, interaction.id)
        now = _now()
        history = []
        if interaction is None:
            interaction = AgentInteraction(company_id=notification.company_id, post_id=notification.post_id,
                agent_id=notification.recipient_agent_id, notification_id=notification_id, status="skipped", started_at=now)
            db.add(interaction)
        else:
            history = (interaction.decision_json or {}).get("attempt_history")
            if history is None:
                history = [{"started_at": aware(interaction.started_at).isoformat(), "status": interaction.status}]
        interaction.decision_json = {"attempt_history": history}
        try:
            config = _governance(db, notification)
            _budget(db, notification, config, now)
        except LegacyGovernanceError as exc:
            interaction.status, interaction.error, interaction.completed_at = "skipped", _safe_error(exc), now
            interaction.decision_json = {"attempt_history": history}
            notification.status = "skipped"
            db.commit()
            return _interaction(db, interaction.id)
        marker = uuid4().hex
        interaction.status, interaction.error, interaction.started_at, interaction.completed_at = "running", None, now, None
        interaction.decision_json = {"attempt_history": [*history, {"attempt_id": marker, "started_at": now.isoformat(), "status": "running"}]}
        notification.status = "processing"
        agent, post = notification.recipient, notification.post
        context = AgentContext(id=agent.id, company_name=agent.company_name, role=agent.role, industry=agent.industry,
            interests=tuple({"interest_type": item.interest_type, "value": item.value, "weight": item.weight} for item in agent.interests))
        post_context = PostContext(id=post.id, title=post.title, category=post.category, content=post.content)
        try:
            db.flush()
            work = Work(interaction.id, notification.company_id, marker, config, context, post_context)
            db.commit()
        except IntegrityError:
            db.rollback()
            return db.scalar(query)
        return work

    def _execute(self, db, work):
        error, decision = None, None
        try:
            decision = self.response_service.decide(work.agent, work.post)
        except Exception as exc:
            error = _safe_error(exc)
        _lock(db, work.company_id)
        if work.company_id is not None:
            recover_legacy_runs(db, _now())
        interaction = _interaction(db, work.interaction_id)
        history = (interaction.decision_json or {}).get("attempt_history", []) if interaction else []
        if (interaction is None or interaction.company_id != work.company_id or interaction.status != "running"
                or not history or history[-1].get("attempt_id") != work.attempt_id):
            db.commit()
            return interaction
        notification = _notification(db, interaction.notification_id)
        if error is None:
            try:
                _governance(db, notification, work.config, decision)
            except LegacyGovernanceError as exc:
                error = _safe_error(exc)
        now = _now()
        if error:
            interaction.status, interaction.error, notification.status = "failed", error, "failed"
            payload = {}
        else:
            interaction.status = "responded" if decision.should_respond else "skipped"
            notification.status = "completed" if decision.should_respond else "skipped"
            interaction.error = None
            payload = {"provider": self.response_service.provider_name, "decision": decision.model_dump(mode="json")}
            if decision.should_respond:
                db.add(Comment(company_id=work.company_id, post_id=interaction.post_id,
                               agent_id=interaction.agent_id, interaction_id=interaction.id, content=decision.comment or ""))
        history = [*history[:-1], {**history[-1], "status": interaction.status, "completed_at": now.isoformat()}]
        interaction.decision_json, interaction.completed_at = {**payload, "attempt_history": history}, now
        db.commit()
        return _interaction(db, work.interaction_id)
