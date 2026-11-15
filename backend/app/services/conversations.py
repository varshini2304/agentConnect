"""Shared conversations: authorization comes from active membership, never creator ownership."""
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import utc_now
from app.db.network import (
    AgentAccount, AgentVersion, Company, Conversation, ConversationMember, Invitation,
    KnowledgeSource, Message, MessageDelivery, Publication,
)
from app.services.workspace import (
    Principal, company_pair_allowed, config_for, effective_limits, owner_agent,
)


def fail(code: int, detail: str):
    raise HTTPException(code, detail)


def active_members(db: Session, conversation_id: int) -> list[ConversationMember]:
    return list(db.scalars(select(ConversationMember).where(
        ConversationMember.conversation_id == conversation_id,
        ConversationMember.status == "active",
    ).order_by(ConversationMember.id)))


def access(db: Session, principal: Principal, conversation_id: int):
    conv = db.get(Conversation, conversation_id)
    own = list(db.scalars(select(ConversationMember).join(AgentAccount, AgentAccount.id == ConversationMember.agent_id).where(
        ConversationMember.conversation_id == conversation_id,
        ConversationMember.status == "active", AgentAccount.company_id == principal.company.id,
    )))
    if conv is None or not own:
        fail(404, "Conversation not found")
    return conv, own


def member_config(db: Session, member: ConversationMember) -> dict:
    return db.get(AgentVersion, member.config_version_id).config


def membership(db: Session, cid: int, aid: int):
    return db.scalar(select(ConversationMember).where(
        ConversationMember.conversation_id == cid, ConversationMember.agent_id == aid,
        ConversationMember.status == "active",
    ))


def check_participant(db: Session, conv: Conversation, member: ConversationMember):
    account = db.get(AgentAccount, member.agent_id)
    cfg = member_config(db, member)
    company = db.get(Company, account.company_id)
    permission = "allow_" + conv.kind
    current = config_for(db, account, active=True)
    if (conv.status != "active" or member.status != "active" or account.state != "active" or company.status != "active"
            or not cfg.get(permission, True) or not current.get(permission, True)
            or not company.policy.get(permission, True) or company.policy.get("emergency_paused", False)):
        fail(403, "Agent participation is paused or prohibited by policy")
    members = active_members(db, conv.id)
    for other in members:
        if other.agent_id == account.id:
            continue
        peer = db.get(AgentAccount, other.agent_id)
        peer_company = db.get(Company, peer.company_id)
        peer_cfg = member_config(db, other)
        peer_current = config_for(db, peer, active=True)
        # A paused peer cannot respond, but does not stop other members from sending.
        if (peer.company_id in cfg.get("blocked_company_ids", [])
                or peer.company_id in current.get("blocked_company_ids", [])
                or account.company_id in peer_cfg.get("blocked_company_ids", [])
                or account.company_id in peer_current.get("blocked_company_ids", [])
                or peer.company_id in company.policy.get("blocked_company_ids", [])
                or account.company_id in peer_company.policy.get("blocked_company_ids", [])):
            fail(403, "Company relationship policy prohibits communication")
        if (peer_company.status != "active" or not peer_company.policy.get(permission, True) or not peer_cfg.get(permission, True)
                or not peer_current.get(permission, True)
                or (peer.company_id != company.id and (not company.network_opt_in or not peer_company.network_opt_in))):
            fail(403, "A participant company has revoked communication permission")
    return account, cfg, company


def conversation_limits(db: Session, conv: Conversation) -> dict:
    limits = []
    for member in active_members(db, conv.id):
        account = db.get(AgentAccount, member.agent_id)
        company = db.get(Company, account.company_id)
        limits.append(effective_limits(member_config(db, member), company.policy))
        limits.append(effective_limits(config_for(db, account, active=True), company.policy))
    if not limits:
        return effective_limits({}, {})
    return {k: (max if k == "cooldown_seconds" else min)(x[k] for x in limits) for k in limits[0]}


def private_excerpt(db: Session, company_id: int, content: str) -> bool:
    text = " ".join(content.casefold().split())
    sources = db.scalars(select(KnowledgeSource).where(
        KnowledgeSource.company_id == company_id, KnowledgeSource.visibility == "private",
        KnowledgeSource.deleted_at.is_(None),
    ))
    for source in sources:
        secret = " ".join(source.content.casefold().split())
        if secret and (secret in text or (len(text) >= 24 and text in secret)):
            return True
        # shortcut: literal excerpt detection is not semantic DLP; private sources never enter external prompts.
        if any(secret[i:i + 48] in text for i in range(max(0, len(secret) - 47))):
            return True
    return False


def serialize_conversation(db: Session, conv: Conversation) -> dict:
    rows = list(db.scalars(select(ConversationMember).where(ConversationMember.conversation_id == conv.id).order_by(ConversationMember.id)))
    members = []
    for member in rows:
        a = db.get(AgentAccount, member.agent_id)
        cfg = member_config(db, member)
        company = db.get(Company, a.company_id)
        members.append({"id": member.id, "agent_id": a.id, "agent_name": cfg["name"],
                        "company_id": company.id, "company_name": company.name,
                        "status": member.status, "joined_at": member.joined_at,
                        "left_at": member.left_at, "history_from_seq": member.history_from_seq,
                        "config_version_id": member.config_version_id})
    return {"id": conv.id, "kind": conv.kind, "title": conv.title, "status": conv.status,
            "created_at": conv.created_at, "members": members, "message_count": conv.message_count}


def serialize_message(db: Session, msg: Message, company_id: int) -> dict:
    # Only show delivery processing metadata for the viewer's own company.
    deliveries = list(db.scalars(select(MessageDelivery).join(AgentAccount, AgentAccount.id == MessageDelivery.agent_id).where(
        MessageDelivery.message_id == msg.id, AgentAccount.company_id == company_id,
    )))
    return {"id": msg.id, "conversation_id": msg.conversation_id, "sequence": msg.sequence,
            "sender_agent_id": msg.sender_agent_id, "sender_user_id": msg.sender_user_id,
            "author_type": msg.author_type, "content": msg.content, "reply_depth": msg.reply_depth,
            "created_at": msg.created_at,
            "deliveries": [{"id": d.id, "agent_id": d.agent_id, "status": d.status,
                            "attempts": d.attempts, "error": d.error} for d in deliveries]}


def check_invitation(db: Session, conv: Conversation, inviter: AgentAccount, recipient: AgentAccount):
    if conv.status != "active" or membership(db, conv.id, inviter.id) is None:
        fail(403, "Inviter must be an active participant")
    company = db.get(Company, inviter.company_id)
    pinned = member_config(db, membership(db, conv.id, inviter.id))
    if any(not policy.get("allow_invitations", True) for policy in (company.policy, pinned, config_for(db, inviter, active=True))):
        fail(403, "Participant invitations are disabled")
    if inviter.id == recipient.id:
        fail(422, "An agent cannot invite itself")
    if conv.kind == "direct":
        known_ids = set(db.scalars(select(ConversationMember.agent_id).where(ConversationMember.conversation_id == conv.id)))
        known_ids.update(db.scalars(select(Invitation.recipient_agent_id).where(Invitation.conversation_id == conv.id)))
        if recipient.id not in known_ids and len(known_ids) >= 2:
            fail(403, "Direct conversations have exactly two designated agents")
    for existing in active_members(db, conv.id):
        peer = db.get(AgentAccount, existing.agent_id)
        if not company_pair_allowed(db, peer, recipient, conv.kind):
            fail(403, "Recipient or participant company policy prohibits this invitation")
        pinned = member_config(db, existing)
        if not pinned.get("allow_" + conv.kind, True):
            fail(403, "Pinned participant configuration prohibits this invitation")
    if membership(db, conv.id, recipient.id):
        fail(409, "Agent is already an active participant")


def join_invitation(db: Session, invitation: Invitation, now: datetime):
    conv = db.get(Conversation, invitation.conversation_id)
    inviter = db.get(AgentAccount, invitation.inviter_agent_id)
    recipient = db.get(AgentAccount, invitation.recipient_agent_id)
    check_invitation(db, conv, inviter, recipient)
    company = db.get(Company, recipient.company_id)
    cfg = config_for(db, recipient, active=True)
    maximum = min(conversation_limits(db, conv)["max_participants"], effective_limits(cfg, company.policy)["max_participants"])
    if conv.kind == "direct":
        maximum = min(maximum, 2)
    if len(active_members(db, conv.id)) >= maximum:
        fail(409, "Conversation participant limit reached")
    member = db.scalar(select(ConversationMember).where(ConversationMember.conversation_id == conv.id, ConversationMember.agent_id == recipient.id))
    if member is None:
        member = ConversationMember(conversation_id=conv.id, agent_id=recipient.id, config_version_id=recipient.active_version_id)
        db.add(member)
    member.status, member.joined_at, member.left_at = "active", now, None
    member.config_version_id = recipient.active_version_id
    member.history_from_seq = conv.message_count + 1
    invitation.status = "accepted"
    db.flush()


def propose_invitation(db: Session, principal: Principal, conv: Conversation, inviter_id: int, recipient_id: int):
    inviter = owner_agent(db, principal, inviter_id)
    recipient = db.get(AgentAccount, recipient_id)
    if recipient is None:
        fail(404, "Recipient agent not found")
    check_invitation(db, conv, inviter, recipient)
    pending = db.scalar(select(Invitation).where(Invitation.conversation_id == conv.id, Invitation.recipient_agent_id == recipient_id, Invitation.status == "pending"))
    if pending:
        return pending
    company = db.get(Company, recipient.company_id)
    requires = company.policy.get("require_invitation_approval", True)
    invitation = Invitation(conversation_id=conv.id, inviter_agent_id=inviter_id, recipient_agent_id=recipient_id, requires_approval=requires)
    db.add(invitation)
    db.flush()
    if not requires:
        join_invitation(db, invitation, utc_now())
    return invitation


def create_conversation(db: Session, principal: Principal, payload):
    previous = db.scalar(select(Conversation).where(Conversation.created_by == principal.user.id, Conversation.idempotency_key == payload.idempotency_key))
    if previous:
        access(db, principal, previous.id)
        if previous.kind != payload.kind or previous.title != payload.title:
            fail(409, "Idempotency key was already used for another conversation")
        return previous
    agent = owner_agent(db, principal, payload.agent_id)
    cfg = config_for(db, agent, active=True)
    if (agent.state != "active" or not cfg.get("allow_" + payload.kind, True) or not principal.company.policy.get("allow_" + payload.kind, True)
            or not cfg.get("allow_initiation", True) or not principal.company.policy.get("allow_initiation", True)
            or principal.company.policy.get("emergency_paused", False)):
        fail(403, "Agent or company prohibits this conversation")
    if payload.kind == "direct" and payload.recipient_agent_id is None:
        fail(422, "Direct conversations require a recipient")
    if payload.publication_id is not None:
        from app.services.workspace import publication_visible
        post = db.get(Publication, payload.publication_id)
        if post is None or not publication_visible(db, principal, post):
            fail(404, "Publication not found")
    conv = Conversation(kind=payload.kind, title=payload.title, created_by=principal.user.id,
                        publication_id=payload.publication_id, idempotency_key=payload.idempotency_key)
    db.add(conv)
    db.flush()
    member = ConversationMember(conversation_id=conv.id, agent_id=agent.id, config_version_id=agent.active_version_id)
    db.add(member)
    db.flush()
    if payload.recipient_agent_id:
        propose_invitation(db, principal, conv, agent.id, payload.recipient_agent_id)
    return conv


def enqueue_message(db: Session, conv: Conversation, member: ConversationMember, content: str,
                    key: str, now: datetime, *, user_id=None, depth=0, reviewed=False) -> Message:
    """Caller holds RuntimeMutex. Message and delivery outbox rows share the transaction."""
    existing = db.scalar(select(Message).where(Message.conversation_id == conv.id, Message.sender_agent_id == member.agent_id, Message.idempotency_key == key))
    if existing:
        if existing.content != content or existing.sender_user_id != user_id:
            fail(409, "Idempotency key was already used for another message")
        return existing
    account, cfg, company = check_participant(db, conv, member)
    if private_excerpt(db, company.id, content):
        fail(403, "Private company knowledge cannot be shared in a conversation")
    from app.services.policy import evaluate_action
    configs = [cfg, config_for(db, account, active=True)]
    if user_id is not None:
        configs = [{**config, "require_approval": False} for config in configs]
    evaluation = evaluate_action(action="message.reply", content=content, company_policy=company.policy, configs=configs)
    if evaluation.disposition == "reject":
        fail(403, "Message is prohibited by current company or agent policy")
    if evaluation.disposition == "approval" and not reviewed:
        fail(403, "Restricted messages require review through an agent proposal or a governed publication draft")
    limits = conversation_limits(db, conv)
    if conv.message_count >= limits["max_conversation_messages"] or depth > limits["max_reply_depth"]:
        fail(409, "Conversation message or reply depth limit reached")
    if user_id is None:
        sent = db.scalar(select(func.count(Message.id)).where(Message.conversation_id == conv.id, Message.sender_agent_id == member.agent_id, Message.author_type == "agent"))
        own_limits = effective_limits(cfg, company.policy)
        current_limits = effective_limits(config_for(db, account, active=True), company.policy)
        if sent >= min(own_limits["max_agent_messages"], current_limits["max_agent_messages"]):
            fail(409, "Agent message limit reached")
    conv.message_count += 1
    msg = Message(conversation_id=conv.id, sequence=conv.message_count, sender_agent_id=member.agent_id,
                  sender_user_id=user_id, author_type="human" if user_id else "agent", content=content,
                  reply_depth=depth, idempotency_key=key, created_at=now)
    db.add(msg)
    db.flush()
    for recipient in active_members(db, conv.id):
        if recipient.agent_id != member.agent_id:
            db.add(MessageDelivery(message_id=msg.id, agent_id=recipient.agent_id, available_at=now))
    db.flush()
    return msg
