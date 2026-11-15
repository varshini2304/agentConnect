"""Membership-authorized conversation, message, invitation and run APIs."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_session
from app.db.models import utc_now
from app.db.network import (
    AgentAccount, AgentRun, AgentRunAttempt, Conversation, ConversationMember,
    Invitation, Message, MessageDelivery, RunApproval,
)
from app.schemas.network import AcceptInput, ConversationCreate, InvitationCreate, MemberInput, MessageCreate
from app.services import conversations as service
from app.services.runtime import aware, combined_limits, validate_reply
from app.schemas.network import RuntimeDecision
from app.services.response_generation import PolicyViolationError
from app.services.workspace import Principal, current_principal, lock_runtime, owner_agent

router = APIRouter( tags=["conversations"])


@router.get("/conversations")
def conversations(principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    rows = db.scalars(select(Conversation).join(ConversationMember).join(AgentAccount, AgentAccount.id == ConversationMember.agent_id).where(
        ConversationMember.status == "active", AgentAccount.company_id == principal.company.id,
    ).distinct().order_by(Conversation.id.desc()))
    return [service.serialize_conversation(db, row) for row in rows]


@router.post("/conversations", status_code=201)
def create(payload: ConversationCreate, principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    lock_runtime(db)
    conv = service.create_conversation(db, principal, payload)
    db.commit()
    return service.serialize_conversation(db, conv)


@router.get("/conversations/{conversation_id}")
def detail(conversation_id: int, principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    conv, _ = service.access(db, principal, conversation_id)
    return service.serialize_conversation(db, conv)


@router.get("/conversations/{conversation_id}/messages")
def messages(conversation_id: int, after: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    _, own = service.access(db, principal, conversation_id)
    floor = min(m.history_from_seq for m in own)
    rows = list(db.scalars(select(Message).where(Message.conversation_id == conversation_id,
        Message.sequence > after, Message.sequence >= floor).order_by(Message.sequence).limit(limit)))
    return {"items": [service.serialize_message(db, row, principal.company.id) for row in rows],
            "next_after": rows[-1].sequence if rows else after}


@router.post("/conversations/{conversation_id}/messages", status_code=201)
def send(conversation_id: int, payload: MessageCreate, principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    from app.services.runtime import reservation_count
    lock_runtime(db)
    conv, _ = service.access(db, principal, conversation_id)
    owner_agent(db, principal, payload.agent_id)
    member = service.membership(db, conv.id, payload.agent_id)
    if member is None:
        raise HTTPException(403, "Sending agent is not an active participant")
    existing = db.scalar(select(Message).where(Message.conversation_id == conv.id, Message.sender_agent_id == payload.agent_id, Message.idempotency_key == payload.idempotency_key))
    if existing is None and conv.message_count + reservation_count(db, conversation_id=conv.id) >= service.conversation_limits(db, conv)["max_conversation_messages"]:
        raise HTTPException(409, "Conversation slots are reserved or exhausted")
    msg = service.enqueue_message(db, conv, member, payload.content, payload.idempotency_key, utc_now(), user_id=principal.user.id)
    db.commit()
    return service.serialize_message(db, msg, principal.company.id)


@router.post("/conversations/{conversation_id}/invitations", status_code=201)
def invite(conversation_id: int, payload: InvitationCreate, principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    lock_runtime(db)
    conv, _ = service.access(db, principal, conversation_id)
    invitation = service.propose_invitation(db, principal, conv, payload.inviter_agent_id, payload.recipient_agent_id)
    db.commit()
    return invitation_data(invitation)


def invitation_data(invitation):
    return {"id": invitation.id, "conversation_id": invitation.conversation_id,
            "inviter_agent_id": invitation.inviter_agent_id, "recipient_agent_id": invitation.recipient_agent_id,
            "status": invitation.status, "requires_approval": invitation.requires_approval, "created_at": invitation.created_at}


@router.get("/invitations")
def invitations(principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    owned_ids = select(AgentAccount.id).where(AgentAccount.company_id == principal.company.id)
    rows = db.scalars(select(Invitation).where(
        Invitation.inviter_agent_id.in_(owned_ids) | Invitation.recipient_agent_id.in_(owned_ids),
    ).order_by(Invitation.id.desc()))
    return [invitation_data(i) for i in rows]


@router.post("/invitations/{invitation_id}/respond")
def respond(invitation_id: int, payload: AcceptInput, principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    lock_runtime(db)
    invitation = db.get(Invitation, invitation_id)
    if invitation is None:
        raise HTTPException(404, "Invitation not found")
    owner_agent(db, principal, invitation.recipient_agent_id)
    desired = "accepted" if payload.accept else "rejected"
    if invitation.status == desired:
        return invitation_data(invitation)
    if invitation.status != "pending":
        raise HTTPException(409, "Invitation has already been resolved")
    if payload.accept:
        service.join_invitation(db, invitation, utc_now())
    else:
        invitation.status = "rejected"
    db.commit()
    return invitation_data(invitation)


@router.post("/conversations/{conversation_id}/leave")
@router.post("/conversations/{conversation_id}/remove")
def leave(conversation_id: int, payload: MemberInput, principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    lock_runtime(db)
    conv, _ = service.access(db, principal, conversation_id)
    owner_agent(db, principal, payload.agent_id)
    if payload.by_agent_id is not None:
        owner_agent(db, principal, payload.by_agent_id)
    member = service.membership(db, conv.id, payload.agent_id)
    if member is None:
        raise HTTPException(404, "Active membership not found")
    member.status, member.left_at = "left", utc_now()
    db.flush()
    if not service.active_members(db, conv.id):
        conv.status = "ended"
    db.commit()
    return {"ok": True}


@router.get("/conversations/{conversation_id}/runs")
def runs(conversation_id: int, principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    _, own = service.access(db, principal, conversation_id)
    floor = min(m.history_from_seq for m in own)
    rows = db.scalars(select(AgentRun).join(MessageDelivery, MessageDelivery.id == AgentRun.delivery_id)
        .join(Message, Message.id == MessageDelivery.message_id).join(AgentAccount, AgentAccount.id == AgentRun.agent_id)
        .where(Message.conversation_id == conversation_id, Message.sequence >= floor, AgentAccount.company_id == principal.company.id)
        .order_by(AgentRun.id.desc()).limit(100))
    result = []
    for run in rows:
        attempts = db.scalars(select(AgentRunAttempt).where(AgentRunAttempt.run_id == run.id).order_by(AgentRunAttempt.number))
        result.append({"id": run.id, "agent_id": run.agent_id, "delivery_id": run.delivery_id,
            "config_version_id": run.config_version_id, "policy_version": run.policy_version, "status": run.status,
            "action": run.action, "reason": run.reason, "provider": run.provider, "model": run.model, "created_at": run.created_at,
            "attempts": [{"id": a.id, "number": a.number, "status": a.status, "error": a.error,
                          "started_at": a.started_at, "completed_at": a.completed_at} for a in attempts]})
    return result


def approval_data(row):
    return {"id": row.id, "conversation_id": row.conversation_id, "agent_id": row.agent_id,
            "run_id": row.run_id, "status": row.status, "content": row.content, "reason": row.reason}


def approval_context_current(db, approval):
    member = service.membership(db, approval.conversation_id, approval.agent_id)
    run = db.get(AgentRun, approval.run_id)
    delivery = db.get(MessageDelivery, run.delivery_id)
    incoming = db.get(Message, delivery.message_id)
    return bool(member and incoming.sequence >= member.history_from_seq
                and member.config_version_id == run.config_version_id
                and service.membership(db, approval.conversation_id, incoming.sender_agent_id))


@router.get("/approvals")
def approvals(principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    rows = db.scalars(select(RunApproval).join(AgentAccount, AgentAccount.id == RunApproval.agent_id).where(
        AgentAccount.company_id == principal.company.id, RunApproval.status == "pending").order_by(RunApproval.id))
    return [approval_data(row) for row in rows if approval_context_current(db, row)]


@router.post("/approvals/{approval_id}/respond")
def approve(approval_id: int, payload: AcceptInput, principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    from app.db.network import ApprovalRequest
    from app.services import approvals as review_service
    from app.services.security import require_permission
    require_permission(db, principal, "approvals.manage")
    lock_runtime(db)
    approval = db.get(RunApproval, approval_id)
    if approval is None:
        raise HTTPException(404, "Approval not found")
    owner_agent(db, principal, approval.agent_id)
    if not approval_context_current(db, approval):
        raise HTTPException(409, "Approval is no longer accessible through current membership")
    if approval.status != "pending":
        return approval_data(approval)
    request = db.scalar(select(ApprovalRequest).where(ApprovalRequest.source_type == "run_approval", ApprovalRequest.source_id == approval.id))
    if request is None:
        from app.services.policy import evaluate_action
        run = db.get(AgentRun, approval.run_id)
        request = review_service.request_approval(db, company_id=principal.company.id, agent_id=approval.agent_id,
            requesting_user_id=None, action_type="message.reply", source_type="run_approval", source_id=approval.id,
            content=approval.content, evaluation=evaluate_action(action="message.reply", content=approval.content or "",
                company_policy=principal.company.policy, configs=[], requested_approval=True),
            config_version_id=run.config_version_id, policy_version=run.policy_version)
    review_service.owned(db, principal, request.id)
    result = review_service.review(db, principal, request, approve=payload.accept)
    db.commit()
    if result.status == "blocked":
        raise HTTPException(403, "Proposed reply is prohibited by current policy")
    return approval_data(approval)
