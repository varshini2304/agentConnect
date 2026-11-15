"""Measured company reports; notification links are independently authorized on every read."""
from collections import Counter
from datetime import timedelta
import os

from sqlalchemy import exists, func, select

from app.db.models import utc_now
from app.db.network import (
    AgentAccount, AgentRun, AgentRunAttempt, ApprovalRequest, AuditEvent, CompanyMember,
    Conversation, ConversationMember, Invitation, Message, MessageDelivery, Publication,
    PublishingJob, RunApproval, UserNotification,
)
from app.services.security import aware, permissions_for, require_permission
from app.services.workspace import config_for, owner_agent


def granted(db, principal):
    member = db.scalar(select(CompanyMember).where(CompanyMember.company_id == principal.company.id,
        CompanyMember.user_id == principal.user.id, CompanyMember.status == "active"))
    return permissions_for(db, member) if member else set()


def conversation_floor(db, company_id, conversation_id, agent_id=None):
    query = select(ConversationMember.history_from_seq).join(AgentAccount, AgentAccount.id == ConversationMember.agent_id).where(
        AgentAccount.company_id == company_id, ConversationMember.conversation_id == conversation_id,
        ConversationMember.status == "active")
    if agent_id is not None:
        query = query.where(ConversationMember.agent_id == agent_id)
    floors = list(db.scalars(query))
    return min(floors) if floors else None


def message_visible(db, principal, message, permissions=None):
    if message is None or "conversations.read" not in (permissions if permissions is not None else granted(db, principal)):
        return False
    floor = conversation_floor(db, principal.company.id, message.conversation_id)
    return floor is not None and message.sequence >= floor


def approval_visible(db, principal, row, permissions):
    if row is None or row.company_id != principal.company.id or "approvals.manage" not in permissions:
        return False
    if row.source_type in {"run", "agent_run", "run_approval"}:
        legacy = db.get(RunApproval, row.source_id) if row.source_type == "run_approval" else None
        if row.source_type == "run_approval" and legacy is None:
            return False
        run = db.get(AgentRun, legacy.run_id if legacy else row.source_id)
        delivery = db.get(MessageDelivery, run.delivery_id) if run else None
        message = db.get(Message, delivery.message_id) if delivery else None
        if message is None:
            return False
        floor = conversation_floor(db, principal.company.id, message.conversation_id, row.agent_id)
        return floor is not None and message.sequence >= floor
    if row.source_type == "invitation":
        invitation = db.get(Invitation, row.source_id)
        if invitation is None:
            return False
        return principal.company.id in {db.get(AgentAccount, aid).company_id for aid in
            (invitation.inviter_agent_id, invitation.recipient_agent_id) if db.get(AgentAccount, aid)}
    if row.agent_id:
        account = db.get(AgentAccount, row.agent_id)
        if account is None or account.company_id != principal.company.id:
            return False
    if row.source_type == "publication":
        source = db.get(Publication, row.source_id)
    elif row.source_type == "publishing_job":
        source = db.get(PublishingJob, row.source_id)
    else:
        return False
    return bool(source and source.company_id == principal.company.id)


def notification_visible(db, principal, row, permissions):
    if row.company_id != principal.company.id or row.recipient_user_id != principal.user.id:
        return False
    try:
        resource_id = int(row.resource_id)
    except ValueError:
        return False
    if row.resource_type == "message":
        return message_visible(db, principal, db.get(Message, resource_id), permissions)
    if row.resource_type == "invitation":
        invitation = db.get(Invitation, resource_id)
        if invitation is None or "conversations.read" not in permissions:
            return False
        inviter = db.get(AgentAccount, invitation.inviter_agent_id)
        recipient = db.get(AgentAccount, invitation.recipient_agent_id)
        if not inviter or not recipient:
            return False
        if invitation.status == "pending" and recipient.company_id == principal.company.id:
            return True
        return (principal.company.id in {inviter.company_id, recipient.company_id}
                and conversation_floor(db, principal.company.id, invitation.conversation_id) is not None)
    if row.resource_type == "approval":
        return approval_visible(db, principal, db.get(ApprovalRequest, resource_id), permissions)
    if row.resource_type == "agent":
        account = db.get(AgentAccount, resource_id)
        return bool(account and account.company_id == principal.company.id and "agents.read" in permissions)
    if row.resource_type in {"run", "delivery"}:
        resource = db.get(AgentRun if row.resource_type == "run" else MessageDelivery, resource_id)
        if resource is None or "agents.read" not in permissions:
            return False
        account = db.get(AgentAccount, resource.agent_id)
        delivery = db.get(MessageDelivery, resource.delivery_id) if row.resource_type == "run" else resource
        message = db.get(Message, delivery.message_id) if delivery else None
        return bool(account and account.company_id == principal.company.id and message_visible(db, principal, message, permissions))
    if row.resource_type == "publishing_job":
        job = db.get(PublishingJob, resource_id)
        return bool(job and job.company_id == principal.company.id and "posts.read" in permissions)
    return row.resource_type == "company" and resource_id == principal.company.id and "company.read" in permissions


def notification_data(db, row):
    result = {key: getattr(row, key) for key in ("id", "company_id", "category", "title", "resource_type", "resource_id", "read_at", "created_at")}
    if row.resource_type == "message":
        message = db.get(Message, int(row.resource_id))
        if message:
            result["conversation_id"] = message.conversation_id
    elif row.resource_type == "invitation":
        invitation = db.get(Invitation, int(row.resource_id))
        if invitation:
            result["conversation_id"] = invitation.conversation_id
    elif row.resource_type in {"run", "delivery", "publishing_job"}:
        model = {"run": AgentRun, "delivery": MessageDelivery, "publishing_job": PublishingJob}[row.resource_type]
        resource = db.get(model, int(row.resource_id))
        if resource:
            result["agent_id"] = resource.agent_id
    return result


def notifications(db, principal, category=None, unread=None, search=None):
    query = select(UserNotification).where(UserNotification.company_id == principal.company.id,
        UserNotification.recipient_user_id == principal.user.id)
    if category:
        query = query.where(UserNotification.category == category)
    if unread is not None:
        query = query.where(UserNotification.read_at.is_(None) if unread else UserNotification.read_at.is_not(None))
    if search:
        query = query.where(UserNotification.title.icontains(search, autoescape=True))
    permissions = granted(db, principal)
    # Filter before pagination so revoked resources cannot leak through totals or empty pages.
    return [row for row in db.scalars(query.order_by(UserNotification.created_at.desc(), UserNotification.id.desc()))
            if notification_visible(db, principal, row, permissions)]


def audit_data(row):
    return {**{key: getattr(row, key) for key in ("id", "company_id", "actor_type", "actor_id", "event_type",
        "resource_type", "resource_id", "outcome", "created_at")}, "metadata": row.metadata_json}


def usage(db, principal, accounts=None):
    now = utc_now()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    ids = [a.id for a in accounts] if accounts is not None else list(db.scalars(select(AgentAccount.id).where(AgentAccount.company_id == principal.company.id)))
    executions = db.scalar(select(func.count(AgentRunAttempt.id)).join(AgentRun, AgentRun.id == AgentRunAttempt.run_id)
        .where(AgentRun.agent_id.in_(ids), AgentRunAttempt.started_at >= midnight))
    for history in db.scalars(select(PublishingJob.attempt_history).where(PublishingJob.company_id == principal.company.id)):
        executions += sum(1 for attempt in history if attempt.get("started_at", "") >= midnight.isoformat())
    from app.services.governance import legacy_attempt_count
    executions += legacy_attempt_count(db, now=utc_now(), company_id=principal.company.id)
    budget = min(max(0, int(os.getenv("AGENTCONNECT_DAILY_COMPANY_BUDGET", "1000"))), principal.company.policy.get("daily_execution_budget", 1000))
    return {"daily_runs": executions, "daily_budget": budget, "remaining": max(0, budget - executions)}


def _authorized_rows(db, principal, agent_id=None, since=None):
    accounts = list(db.scalars(select(AgentAccount).where(AgentAccount.company_id == principal.company.id)))
    ids = [a.id for a in accounts if agent_id is None or a.id == agent_id]
    members = list(db.scalars(select(ConversationMember).where(ConversationMember.agent_id.in_(ids), ConversationMember.status == "active")))
    floors = {}
    for member in members:
        floors[member.conversation_id] = min(floors.get(member.conversation_id, member.history_from_seq), member.history_from_seq)
    conversations = list(db.scalars(select(Conversation).where(Conversation.id.in_(floors))))
    visible_message = exists(select(ConversationMember.id).where(ConversationMember.conversation_id == Message.conversation_id,
        ConversationMember.agent_id.in_(ids), ConversationMember.status == "active", ConversationMember.history_from_seq <= Message.sequence))
    message_query = select(Message).where(visible_message)
    run_query = select(AgentRun).join(MessageDelivery, MessageDelivery.id == AgentRun.delivery_id).join(Message, Message.id == MessageDelivery.message_id).where(
        AgentRun.agent_id.in_(ids), exists(select(ConversationMember.id).where(ConversationMember.conversation_id == Message.conversation_id,
            ConversationMember.agent_id == AgentRun.agent_id, ConversationMember.status == "active", ConversationMember.history_from_seq <= Message.sequence)))
    if since is not None:
        message_query = message_query.where(Message.created_at >= since)
        run_query = run_query.where(AgentRun.created_at >= since)
        conversations = [conv for conv in conversations if aware(conv.created_at) >= since]
    messages = list(db.scalars(message_query))
    runs = list(db.scalars(run_query))
    return accounts, members, conversations, messages, runs


def dashboard(db, principal):
    require_permission(db, principal, "company.read")
    accounts = list(db.scalars(select(AgentAccount).where(AgentAccount.company_id == principal.company.id)))
    conversations = list(db.scalars(select(Conversation).join(ConversationMember).join(AgentAccount, AgentAccount.id == ConversationMember.agent_id)
        .where(AgentAccount.company_id == principal.company.id, ConversationMember.status == "active").distinct()))
    counts = Counter(account.state for account in accounts)
    active = [conv for conv in conversations if conv.status == "active"]
    owned_ids = [a.id for a in accounts]
    failed_runs = db.scalar(select(func.count(AgentRun.id)).where(AgentRun.agent_id.in_(owned_ids), AgentRun.status == "failed"))
    failed_jobs = db.scalar(select(func.count(PublishingJob.id)).where(PublishingJob.company_id == principal.company.id, PublishingJob.status == "failed"))
    permissions = granted(db, principal)
    audit = list(db.scalars(select(AuditEvent).where(AuditEvent.company_id == principal.company.id)
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).limit(8))) if "settings.manage" in permissions else []
    return {"agents": {"total": len(accounts), "active": counts["active"], "paused": counts["paused"]},
        "published_posts": db.scalar(select(func.count(Publication.id)).where(Publication.company_id == principal.company.id, Publication.status == "published")),
        "active_conversations": len(active), "direct_conversations": sum(c.kind == "direct" for c in active),
        "group_conversations": sum(c.kind == "group" for c in active),
        "pending_approvals": db.scalar(select(func.count(ApprovalRequest.id)).where(ApprovalRequest.company_id == principal.company.id, ApprovalRequest.status == "pending", ApprovalRequest.expires_at > utc_now())),
        "failed_executions": failed_runs + failed_jobs, "usage": usage(db, principal, accounts),
        "recent_activity": [audit_data(row) for row in audit],
        "recent_notifications": [notification_data(db, row) for row in notifications(db, principal)[:8]]}


def analytics(db, principal, days):
    require_permission(db, principal, "company.read")
    now = utc_now()
    since = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days - 1)
    accounts, members, conversations, messages, runs = _authorized_rows(db, principal, since=since)
    own_ids = [a.id for a in accounts]
    attempts = list(db.execute(select(AgentRunAttempt, AgentRun.agent_id).join(AgentRun, AgentRun.id == AgentRunAttempt.run_id)
        .where(AgentRun.agent_id.in_(own_ids), AgentRunAttempt.started_at >= since)))
    jobs = list(db.scalars(select(PublishingJob).where(PublishingJob.company_id == principal.company.id)))
    approvals = list(db.scalars(select(ApprovalRequest).where(ApprovalRequest.company_id == principal.company.id, ApprovalRequest.created_at >= since)))
    routing = list(db.scalars(select(AuditEvent).where(AuditEvent.company_id == principal.company.id,
        AuditEvent.event_type == "discovery.created", AuditEvent.created_at >= since)))
    daily = {(since + timedelta(days=offset)).date().isoformat(): {"date": (since + timedelta(days=offset)).date().isoformat(),
        **dict.fromkeys(("runs", "messages", "conversations", "skips", "approvals", "retries"), 0)} for offset in range(days)}
    per_agent = {a.id: {"agent_id": a.id, "name": config_for(db, a).get("name", a.slug),
        **dict.fromkeys(("runs", "messages", "conversations", "skips", "failures"), 0)} for a in accounts}
    def increment(timestamp, key, amount=1):
        day = aware(timestamp).date().isoformat()
        if day in daily:
            daily[day][key] += amount
    for attempt, agent_id in attempts:
        increment(attempt.started_at, "runs")
        increment(attempt.started_at, "retries", int(attempt.number > 1))
        per_agent[agent_id]["runs"] += 1
    failed_jobs = 0
    for job in jobs:
        history = [entry for entry in job.attempt_history if entry.get("started_at", "") >= since.isoformat()]
        for entry in history:
            from datetime import datetime
            try:
                started = datetime.fromisoformat(entry["started_at"])
            except (ValueError, TypeError):
                continue
            increment(started, "runs")
            increment(started, "retries", int(entry.get("number", 1) > 1))
            per_agent[job.agent_id]["runs"] += 1
        if job.status == "skipped" and aware(job.created_at) >= since:
            increment(job.created_at, "skips")
            per_agent[job.agent_id]["skips"] += 1
        if job.status == "failed" and aware(job.created_at) >= since:
            failed_jobs += 1
            per_agent[job.agent_id]["failures"] += 1
    for message in messages:
        increment(message.created_at, "messages")
        if message.sender_agent_id in per_agent:
            per_agent[message.sender_agent_id]["messages"] += 1
    for conv in conversations:
        increment(conv.created_at, "conversations")
    for member in members:
        if any(conv.id == member.conversation_id for conv in conversations):
            per_agent[member.agent_id]["conversations"] += 1
    for run in runs:
        if run.status == "skipped":
            increment(run.created_at, "skips")
            per_agent[run.agent_id]["skips"] += 1
        if run.status == "failed":
            per_agent[run.agent_id]["failures"] += 1
    for approval in approvals:
        increment(approval.created_at, "approvals")
    totals = {key: sum(day[key] for day in daily.values()) for key in ("runs", "messages", "conversations", "skips", "approvals", "retries")}
    sent = [message for message in messages if message.sender_agent_id in own_ids]
    received = [message for message in messages if db.scalar(select(MessageDelivery.id).where(MessageDelivery.message_id == message.id, MessageDelivery.agent_id.in_(own_ids)).limit(1))]
    decisions = [row for row in approvals if row.status in {"approved", "executed", "blocked", "rejected"}]
    approved = sum(row.status in {"approved", "executed", "blocked"} for row in decisions)
    rejected = sum(row.status == "rejected" for row in decisions)
    totals.update(messages_sent=len(sent), messages_received=len(received),
        responses=sum(message.author_type == "agent" for message in sent),
        conversations_initiated=sum(db.scalar(select(ConversationMember.agent_id).where(ConversationMember.conversation_id == conv.id).order_by(ConversationMember.id).limit(1)) in own_ids for conv in conversations),
        successful_executions=sum(run.status == "completed" for run in runs) + sum(job.status == "completed" and aware(job.created_at) >= since for job in jobs),
        approvals_approved=approved, approvals_rejected=rejected,
        approval_acceptance_percent=round(100 * approved / len(decisions), 2) if decisions else 0,
        approval_rejection_percent=round(100 * rejected / len(decisions), 2) if decisions else 0,
        routing_excluded=sum(not bool(row.metadata_json.get("eligible")) for row in routing))
    totals.update(routing_evaluations=len(routing), routing_selected=sum(bool(row.metadata_json.get("selected")) for row in routing),
        failed_executions=sum(run.status == "failed" for run in runs) + failed_jobs)
    return {"days": days, "totals": totals, "daily": list(daily.values()), "agents": list(per_agent.values()), "usage": usage(db, principal, accounts)}


def activity(db, principal, agent_id):
    require_permission(db, principal, "agents.read")
    owner_agent(db, principal, agent_id)
    _, _, conversations, messages, runs = _authorized_rows(db, principal, agent_id=agent_id)
    if "conversations.read" not in granted(db, principal):
        conversations, messages, runs = [], [], []
    run_data = []
    for run in sorted(runs, key=lambda row: row.id, reverse=True)[:100]:
        attempts = db.scalars(select(AgentRunAttempt).where(AgentRunAttempt.run_id == run.id).order_by(AgentRunAttempt.number))
        run_data.append({**{key: getattr(run, key) for key in ("id", "agent_id", "delivery_id", "status", "action", "config_version_id", "policy_version", "created_at")},
            "attempts": [{key: getattr(attempt, key) for key in ("number", "status", "started_at", "completed_at")} for attempt in attempts]})
    deliveries = db.scalars(select(MessageDelivery).where(MessageDelivery.agent_id == agent_id, MessageDelivery.status == "failed",
        MessageDelivery.message_id.in_([message.id for message in messages])))
    failures = [{"resource_type": "run", **run} for run in run_data if run["status"] == "failed"]
    failures += [{"resource_type": "delivery", **{key: getattr(delivery, key) for key in ("id", "agent_id", "message_id", "status", "attempts")}} for delivery in deliveries]
    return {"agent_id": agent_id, "runs": run_data,
        "messages": [{key: getattr(message, key) for key in ("id", "conversation_id", "sequence", "sender_agent_id", "author_type", "created_at")}
                     for message in sorted(messages, key=lambda row: row.id, reverse=True)[:100]],
        "conversations": [{key: getattr(conv, key) for key in ("id", "kind", "status", "created_at")} for conv in conversations], "failures": failures}
