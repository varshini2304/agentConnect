"""Human-only review. Approval records never confer resource or execution permissions."""
from datetime import timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import func, select, update

from app.db.models import utc_now
from app.db.network import ApprovalRequest, AgentAccount, AgentRun, Company, Message, MessageDelivery, Publication, RunApproval
from app.services.security import require_permission
from app.services.locking import lock_runtime


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def request_approval(db, *, company_id, agent_id, requesting_user_id, action_type, source_type, source_id, content, evaluation, config_version_id, policy_version, now=None):
    previous = db.scalar(select(ApprovalRequest).where(ApprovalRequest.source_type == source_type, ApprovalRequest.source_id == source_id))
    if previous:
        return previous
    now = now or utc_now()
    row = ApprovalRequest(company_id=company_id, agent_id=agent_id, requesting_user_id=requesting_user_id,
        action_type=action_type, source_type=source_type, source_id=source_id, proposed_content=content or "",
        category=evaluation.category, reason="Human review required by business policy", triggered_policy=list(evaluation.reasons),
        config_version_id=config_version_id, policy_version=policy_version, status="pending", created_at=now,
        expires_at=now + timedelta(hours=24))
    db.add(row)
    db.flush()
    return row


def data(row):
    return {"decision": "approved" if row.status in ("approved", "executed", "blocked") else "rejected" if row.status == "rejected" else None, **{key: getattr(row, key) for key in ("id", "company_id", "agent_id", "requesting_user_id", "action_type", "source_type", "source_id", "proposed_content", "category", "reason", "triggered_policy", "config_version_id", "policy_version", "status", "reviewer_id", "decision_at", "reviewer_comments", "expires_at", "created_at")}}


def owned(db, principal, approval_id):
    require_permission(db, principal, "approvals.manage")
    row = db.get(ApprovalRequest, approval_id)
    from app.services.reporting import approval_visible, granted
    if row is None or not approval_visible(db, principal, row, granted(db, principal)):
        raise HTTPException(404, "Approval not found")
    return row


def finish_source(db, row, status):
    if row.source_type == "run_approval":
        legacy = db.get(RunApproval, row.source_id)
        run = db.get(AgentRun, legacy.run_id)
        delivery = db.get(MessageDelivery, run.delivery_id)
        legacy.status = "rejected"
        run.status, delivery.status = status, "completed"
    elif row.source_type == "publication":
        # Rejected drafts remain private; publishing them still requires this request to be executed.
        pass


def expire(db, row, now=None):
    now = now or utc_now()
    changed = db.execute(update(ApprovalRequest).where(ApprovalRequest.id == row.id,
        ApprovalRequest.status == "pending", ApprovalRequest.expires_at <= now)
        .values(status="expired", decision_at=now).execution_options(synchronize_session=False)).rowcount
    db.refresh(row)
    if changed:
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(row, "status")  # Feed the committed transition through audit/notification hooks.
        finish_source(db, row, "expired")
        from app.services.audit import record_event
        record_event(db, "approval.expired", "approval", row.id, company_id=row.company_id, outcome="expired")
    return row


def approval_context_current(db, approval):
    from app.services.conversations import membership
    member = membership(db, approval.conversation_id, approval.agent_id)
    run = db.get(AgentRun, approval.run_id)
    delivery = db.get(MessageDelivery, run.delivery_id)
    incoming = db.get(Message, delivery.message_id)
    return bool(member and incoming.sequence >= member.history_from_seq
                and member.config_version_id == run.config_version_id
                and membership(db, approval.conversation_id, incoming.sender_agent_id))


def review_run(db, principal, legacy, *, now=None):
    from app.schemas.network import RuntimeDecision
    from app.services import conversations as conversations
    from app.services.runtime import combined_limits, reservation_count, validate_reply
    from app.services.publishing_runtime import latest_output
    from app.services.response_generation import PolicyViolationError
    from app.services.workspace import owner_agent
    account = owner_agent(db, principal, legacy.agent_id)
    conv, _ = conversations.access(db, principal, legacy.conversation_id)
    if not approval_context_current(db, legacy):
        raise HTTPException(409, "Approval belongs to a previous membership or configuration")
    run = db.get(AgentRun, legacy.run_id)
    delivery = db.get(MessageDelivery, run.delivery_id)
    incoming = db.get(Message, delivery.message_id)
    if not legacy.content:
        raise HTTPException(422, "No proposed reply is available")
    member = conversations.membership(db, conv.id, account.id)
    _, cfg, company = conversations.check_participant(db, conv, member)
    decision = RuntimeDecision(action="reply", reason="Human reviewed proposed reply", content=legacy.content)
    try:
        validate_reply(db, account, cfg, company, decision, incoming.content)
    except PolicyViolationError:
        raise HTTPException(403, "Proposed reply is prohibited by current policy") from None
    limits, now = combined_limits(db, account, cfg, company), now or utc_now()
    latest = latest_output(db, account.id)
    if latest and latest + timedelta(seconds=limits["cooldown_seconds"]) > now:
        raise HTTPException(409, "Agent is in cooldown")
    if conv.message_count + reservation_count(db, conversation_id=conv.id) >= conversations.conversation_limits(db, conv)["max_conversation_messages"]:
        raise HTTPException(409, "Conversation slots are reserved or exhausted")
    sent = db.scalar(select(func.count(Message.id)).where(Message.conversation_id == conv.id, Message.sender_agent_id == account.id, Message.author_type == "agent"))
    if sent + reservation_count(db, agent_id=account.id, conversation_id=conv.id) >= limits["max_agent_messages"]:
        raise HTTPException(409, "Agent message slots are reserved or exhausted")
    conversations.enqueue_message(db, conv, member, legacy.content, "delivery:" + str(delivery.id), now, depth=incoming.reply_depth + 1, reviewed=True)
    legacy.status, delivery.status, run.status = "accepted", "completed", "completed"


def review(db, principal, row, *, approve, comments=""):
    lock_runtime(db)
    require_permission(db, principal, "approvals.manage")
    db.refresh(row)
    if row.company_id != principal.company.id:
        raise HTTPException(404, "Approval not found")
    expire(db, row)
    if row.status != "pending":
        return row
    # A user session and fresh permission check are mandatory; workers cannot call this operation.
    if not principal.token_hash:
        raise HTTPException(403, "A human reviewer session is required")
    now = utc_now()
    if approve:
        try:
            with db.begin_nested():
                if row.source_type == "run_approval":
                    review_run(db, principal, db.get(RunApproval, row.source_id), now=now)
                elif row.source_type == "publication":
                    from app.services.workspace import approve_publication
                    publication = db.get(Publication, row.source_id)
                    approve_publication(db, principal, publication, reviewed=True)
                else:
                    raise HTTPException(403, "No executor is configured for this action")
        except HTTPException as exc:
            if exc.status_code == 409:  # Temporary capacity/cooldown can be reviewed again later.
                raise
            row.status = "blocked"
            finish_source(db, row, "rejected")
        else:
            row.status = "executed"
    else:
        row.status = "rejected"
        finish_source(db, row, "rejected")
    row.reviewer_id, row.decision_at, row.reviewer_comments = principal.user.id, now, comments
    from app.services.audit import record_event
    record_event(db, "approval.reviewed", "approval", row.id, company_id=row.company_id, outcome="approved" if approve else "rejected")
    db.flush()
    return row


def cancel(db, principal, row):
    lock_runtime(db)
    require_permission(db, principal, "approvals.manage")
    expire(db, row)
    if row.status == "pending":
        row.status, row.decision_at, row.reviewer_id = "cancelled", utc_now(), principal.user.id
        finish_source(db, row, "cancelled")
    return row
