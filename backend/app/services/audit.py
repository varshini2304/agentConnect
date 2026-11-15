"""Transaction-local audit records and notification fanout with an explicit metadata allowlist."""
from sqlalchemy import event, inspect, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.orm import Session

from app.db.models import utc_now
from app.db.network import (
    AgentAccount, AgentRun, AgentRunAttempt, AgentVersion, ApprovalRequest, AuditEvent,
    Company, CompanyInvitation, CompanyMember, CompanyRole, CompanySettings, Conversation,
    ConversationMember, DiscoveryRecord, Invitation, KnowledgeSource, Message,
    MessageDelivery, Publication, PublishingJob, RolePermissionGrant, RunApproval, User,
    UserNotification,
)


_TYPES = {
    Company: "company", CompanyMember: "company_member", CompanyRole: "role",
    RolePermissionGrant: "role_grant", CompanySettings: "company_settings",
    CompanyInvitation: "company_invitation", AgentAccount: "agent", AgentVersion: "agent_version",
    KnowledgeSource: "knowledge_source", Publication: "publication", DiscoveryRecord: "discovery",
    PublishingJob: "publishing_job", Conversation: "conversation", ConversationMember: "conversation_member",
    Invitation: "invitation", Message: "message", MessageDelivery: "delivery", AgentRun: "run",
    AgentRunAttempt: "run_attempt", RunApproval: "run_approval", ApprovalRequest: "approval",
}
_NUMBERS = {"agent_id", "conversation_id", "publication_id", "run_id", "version", "config_version_id",
            "policy_version", "attempts", "number", "sequence", "role_id", "member_id", "source_id", "paused_agents"}
_ENUMS = {
    "status": {"active", "pending", "accepted", "approved", "rejected", "cancelled", "expired", "stale",
               "processing", "running", "completed", "failed", "skipped", "awaiting_approval", "draft",
               "published", "revoked", "left", "ended", "disabled", "archived", "paused", "abandoned", "deferred"},
    "state": {"draft", "active", "paused", "disabled", "archived"},
    "action": {"reply", "skip", "request_approval", "end_conversation", "publish", "invite"},
    "category": {"general_information", "product_announcement", "promotional_offer", "financial_claim",
                 "partnership_proposal", "binding_commitment", "external_action"},
    "source_type": {"run", "publication", "publishing_job", "invitation", "agent_run", "run_approval"},
}


def safe_metadata(metadata):
    result = {}
    for key, value in (metadata or {}).items():
        if key in _NUMBERS and type(value) is int and value >= 0:
            result[key] = value
        elif key in _ENUMS and isinstance(value, str) and value in _ENUMS[key]:
            result[key] = value
        elif key in {"eligible", "selected", "network_opt_in", "emergency_paused"} and type(value) is bool:
            result[key] = value
    return result


def record_event(db, event_type, resource_type, resource_id, company_id=None, outcome="success",
                 metadata=None, actor_type=None, actor_id=None):
    row = AuditEvent(company_id=company_id if company_id is not None else db.info.get("company_id"),
        actor_type=actor_type or db.info.get("actor_type", "system"),
        actor_id=str(actor_id if actor_id is not None else db.info["actor_id"]) if actor_id is not None or db.info.get("actor_id") is not None else None,
        event_type=event_type, resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        outcome=outcome, metadata_json=safe_metadata(metadata))
    db.add(row)
    return row


def _company_for_agent(db, agent_id):
    account = db.get(AgentAccount, agent_id) if agent_id else None
    return account.company_id if account else None


def _companies(db, row):
    if isinstance(row, Company):
        return {row.id}
    if isinstance(row, DiscoveryRecord):
        publication = db.get(Publication, row.publication_id)
        return {publication.company_id} if publication else set()
    if hasattr(row, "company_id"):
        return {row.company_id} if row.company_id else set()
    if isinstance(row, RolePermissionGrant):
        role = db.get(CompanyRole, row.role_id)
        return {role.company_id} if role else set()
    if isinstance(row, AgentRunAttempt):
        run = db.get(AgentRun, row.run_id)
        return {_company_for_agent(db, run.agent_id)} if run else set()
    if isinstance(row, Invitation):
        return {_company_for_agent(db, row.inviter_agent_id), _company_for_agent(db, row.recipient_agent_id)} - {None}
    if hasattr(row, "agent_id"):
        return {_company_for_agent(db, row.agent_id)} - {None}
    conversation_id = row.id if isinstance(row, Conversation) else getattr(row, "conversation_id", None)
    if conversation_id:
        companies = set(db.scalars(select(AgentAccount.company_id).join(ConversationMember, ConversationMember.agent_id == AgentAccount.id)
            .where(ConversationMember.conversation_id == conversation_id, ConversationMember.status == "active")))
        if isinstance(row, Conversation) and not companies and db.info.get("company_id"):
            companies.add(db.info["company_id"])
        return companies
    return set()


def _notify(db, company_id, category, title, resource_type, resource_id, dedupe_key, permission=None, exclude_user=None):
    from app.services.security import permissions_for
    members = db.scalars(select(CompanyMember).join(User, User.id == CompanyMember.user_id).join(Company, Company.id == CompanyMember.company_id)
        .where(CompanyMember.company_id == company_id, CompanyMember.status == "active", User.status == "active", Company.status == "active"))
    for member in members:
        if member.user_id == exclude_user or (permission and permission not in permissions_for(db, member)):
            continue
        values = dict(company_id=company_id, recipient_user_id=member.user_id, category=category,
            title=title, resource_type=resource_type, resource_id=str(resource_id),
            dedupe_key=f"{company_id}:{dedupe_key}", created_at=utc_now())
        insert = postgres_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
        db.execute(insert(UserNotification).values(**values).on_conflict_do_nothing(
            index_elements=["recipient_user_id", "dedupe_key"]))


def _notifications(db, row, action, changed, companies):
    if isinstance(row, Message) and action == "created":
        for company_id in companies:
            floor = db.scalar(select(ConversationMember.id).join(AgentAccount, AgentAccount.id == ConversationMember.agent_id)
                .where(AgentAccount.company_id == company_id, ConversationMember.conversation_id == row.conversation_id,
                       ConversationMember.status == "active", ConversationMember.history_from_seq <= row.sequence).limit(1))
            if floor:
                _notify(db, company_id, "message", "New conversation message", "message", row.id, f"message:{row.id}", "conversations.read", row.sender_user_id)
    elif isinstance(row, Invitation) and (action == "created" or "status" in changed):
        pending = row.status == "pending"
        company_id = _company_for_agent(db, row.recipient_agent_id if pending else row.inviter_agent_id)
        if company_id:
            _notify(db, company_id, "invitation" if pending else "invitation_response",
                "Conversation invitation" if pending else "Invitation decision recorded", "invitation", row.id,
                f"invitation:{row.id}:{row.status}", "conversations.read")
    elif isinstance(row, CompanyInvitation) and (action == "created" or "status" in changed):
        _notify(db, row.company_id, "governance", "Team invitation created" if action == "created" else "Team invitation updated",
            "company", row.company_id, f"company-invitation:{row.id}:{row.status}", "invitations.manage")
    elif isinstance(row, ApprovalRequest) and (action == "created" or "status" in changed):
        pending = row.status == "pending"
        _notify(db, row.company_id, "approval_requested" if pending else "approval_decision",
            "Approval requested" if pending else "Approval decision recorded", "approval", row.id,
            f"approval:{row.id}:{row.status}", "approvals.manage")
    elif isinstance(row, (AgentRun, MessageDelivery, PublishingJob)) and row.status == "failed" and (action == "created" or "status" in changed):
        for company_id in companies:
            resource_type = _TYPES[type(row)]
            _notify(db, company_id, "delivery_failure" if isinstance(row, MessageDelivery) else "run_failure",
                "Message delivery failed" if isinstance(row, MessageDelivery) else "Agent execution failed",
                resource_type, row.id, f"{resource_type}:{row.id}:failed", "agents.read")
    elif isinstance(row, AgentAccount) and (action == "created" or "state" in changed):
        _notify(db, row.company_id, "agent_state", "Agent state changed", "agent", row.id,
            f"agent:{row.id}:{row.state}:{utc_now().isoformat()}", "agents.read")
    elif isinstance(row, (Company, CompanyMember, CompanyRole, RolePermissionGrant, CompanySettings)) and action != "created":
        for company_id in companies:
            _notify(db, company_id, "governance", "Workspace governance changed", "company", company_id,
                f"governance:{_TYPES[type(row)]}:{getattr(row, 'id', getattr(row, 'role_id', company_id))}:{utc_now().isoformat()}", "company.read")


def _capture(db, _context, _instances):
    pending = []
    for collection, action in ((db.new, "created"), (db.dirty, "updated"), (db.deleted, "deleted")):
        for row in collection:
            if type(row) not in _TYPES or (action == "updated" and not db.is_modified(row, include_collections=False)):
                continue
            changed = {attr.key for attr in inspect(row).attrs if attr.history.has_changes()}
            pending.append((row, action, changed))
    db.info["audit_pending"] = pending


def _persist(db, _context):
    for row, action, changed in db.info.pop("audit_pending", []):
        companies = _companies(db, row)
        resource_type = _TYPES[type(row)]
        event_type = f"{resource_type}.{action}"
        if isinstance(row, Company) and "policy" in changed and action == "updated":
            event_type = "company.policy_changed"
        elif isinstance(row, AgentAccount) and "state" in changed:
            event_type = "agent.state_changed"
        elif isinstance(row, ApprovalRequest):
            event_type = "approval.requested" if action == "created" else "approval.decision"
        for company_id in companies:
            metadata = safe_metadata({key: getattr(row, key, None) for key in _NUMBERS | set(_ENUMS) | {"eligible", "selected", "network_opt_in"}})
            # Shared events expose local identifiers only; external participants remain behind resource ACLs.
            if isinstance(row, (Conversation, ConversationMember, Message, Invitation, DiscoveryRecord)):
                metadata = {key: value for key, value in metadata.items() if key in {"sequence", "status", "eligible", "selected"}}
            actor_local = company_id == db.info.get("company_id")
            if not actor_local and db.info.get("actor_type") == "user" and db.info.get("actor_id") is not None:
                actor_local = bool(db.scalar(select(CompanyMember.id).where(CompanyMember.company_id == company_id,
                    CompanyMember.user_id == db.info["actor_id"], CompanyMember.status == "active").limit(1)))
                actor_local = actor_local or (isinstance(row, Company) and action == "created")
            db.execute(AuditEvent.__table__.insert().values(company_id=company_id,
                actor_type=db.info.get("actor_type", "system") if actor_local else "system",
                actor_id=str(db.info["actor_id"]) if actor_local and db.info.get("actor_id") is not None else None,
                event_type=event_type, resource_type=resource_type,
                resource_id=str(getattr(row, "id", getattr(row, "role_id", company_id))),
                outcome="failure" if getattr(row, "status", None) == "failed" else "success",
                metadata_json=metadata, created_at=utc_now()))
        _notifications(db, row, action, changed, companies)


def install_audit_hooks():
    if not event.contains(Session, "before_flush", _capture):
        event.listen(Session, "before_flush", _capture)
        event.listen(Session, "after_flush_postexec", _persist)
