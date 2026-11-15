"""Tenant authorization, versioned builder data, and network publications."""
from datetime import timedelta, timezone
import hashlib
import json
import os
from uuid import uuid4

from fastapi import Depends, Header, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.api.dependencies import get_session
from app.core.config import get_gemini_model, get_relevance_threshold, get_relevance_top_k
from app.db.models import Agent, utc_now
from app.db.network import (
    AgentAccount, AgentVersion, Company, CompanyMember, DiscoveryRecord,
    KnowledgeSource, LoginSession, Publication, RuntimeMutex, User,
)
from app.schemas.network import AgentConfig, CompanyPolicy, Limits
from app.services.relevance import (
    AgentProfile, Interest, PostProfile, Relationship, RelevanceConfig,
    evaluate_relevance, normalize,
)


from app.services.locking import lock_runtime
from app.services.security import (
    Principal, current_principal, require_permission, hash_password, verify_password,
    create_company, companies_for, company_data, identity_data, issue_session,
)


def platform_limits() -> dict:
    defaults = Limits().model_dump()
    configured = json.loads(os.getenv("AGENTCONNECT_LIMITS", "{}"))
    # Validate operator configuration as strictly as builder inputs.
    return Limits.model_validate({**defaults, **configured}).model_dump()


def effective_limits(config: dict, company_policy: dict) -> dict:
    platform = platform_limits()
    agent = config.get("limits", {})
    company = (company_policy or {}).get("limits", {})
    return {key: (max if key == "cooldown_seconds" else min)(value, agent.get(key, value), company.get(key, value))
            for key, value in platform.items()}


def fake_available(request: Request) -> bool:
    return os.getenv("AGENTCONNECT_ENABLE_FAKE", "").lower() == "true" or getattr(getattr(request.app.state, "runtime_adapter", None), "provider_name", None) == "fake"


def owner_agent(db: Session, principal: Principal, agent_id: int) -> AgentAccount:
    account = db.get(AgentAccount, agent_id)
    if account is None or account.company_id != principal.company.id:
        raise HTTPException(404, "Agent not found")
    return account


def config_for(db: Session, account: AgentAccount, active: bool = False) -> dict:
    version_id = account.active_version_id if active else account.config_version_id
    version = db.get(AgentVersion, version_id) if version_id is not None else None
    if version is None or version.agent_id != account.id:
        return {}
    return version.config


def validate_config(db: Session, principal: Principal, config: AgentConfig | dict, *, agent_id: int | None, allow_fake: bool) -> dict:
    try:
        parsed = config if isinstance(config, AgentConfig) else AgentConfig.model_validate(config)
    except ValidationError:
        raise HTTPException(422, "Invalid agent configuration") from None
    values = parsed.model_dump()
    if values["provider"] == "fake":
        if not allow_fake or values["model"] != "deterministic":
            raise HTTPException(422, "Provider or model is not enabled")
    elif values["model"] != get_gemini_model():
        raise HTTPException(422, "Provider or model is not enabled")
    ids = set(values["knowledge_source_ids"])
    if ids:
        owned = set(db.scalars(select(KnowledgeSource.id).where(
            KnowledgeSource.id.in_(ids), KnowledgeSource.company_id == principal.company.id,
            KnowledgeSource.agent_id == agent_id, KnowledgeSource.deleted_at.is_(None)))) if agent_id else set()
        if owned != ids:
            raise HTTPException(422, "Knowledge sources must belong to this agent and workspace")
    return values


def agent_data(db: Session, account: AgentAccount) -> dict:
    company = db.get(Company, account.company_id)
    return {"id": account.id, "company_id": account.company_id, "company_name": company.name,
            "slug": account.slug, "state": account.state, "active_version_id": account.active_version_id,
            "config_version_id": account.config_version_id, "config": config_for(db, account), "created_at": account.created_at}


def public_profile(db: Session, account: AgentAccount) -> dict:
    config = config_for(db, account, active=True)
    company = db.get(Company, account.company_id)
    return {"id": account.id, "company_id": company.id, "company_name": company.name, "slug": account.slug,
            **{key: config.get(key, "") for key in ("name", "description", "role", "domain", "avatar")}}


def create_agent(db: Session, principal: Principal, slug: str, config: AgentConfig, allow_fake: bool) -> AgentAccount:
    lock_runtime(db)
    require_permission(db, principal, "agents.manage")
    values = validate_config(db, principal, config, agent_id=None, allow_fake=allow_fake)
    if db.scalar(select(AgentAccount).where(AgentAccount.company_id == principal.company.id, AgentAccount.slug == slug)):
        raise HTTPException(409, "Agent slug already exists in this workspace")
    legacy = Agent(company_id=principal.company.id, slug=f"managed-{uuid4().hex}", company_name=principal.company.name,
                   role=values["role"], industry=values["domain"], description=values["description"], is_active=False)
    db.add(legacy)
    db.flush()
    account = AgentAccount(id=legacy.id, company_id=principal.company.id, slug=slug, state="draft")
    db.add(account)
    db.flush()
    version = AgentVersion(agent_id=account.id, version=1, config=values, created_by=principal.user.id)
    db.add(version)
    db.flush()
    account.config_version_id = version.id
    db.flush()
    return account


def save_version(db: Session, principal: Principal, account: AgentAccount, config: AgentConfig, allow_fake: bool) -> AgentVersion:
    lock_runtime(db)
    require_permission(db, principal, "agents.manage")
    db.refresh(account)
    values = validate_config(db, principal, config, agent_id=account.id, allow_fake=allow_fake)
    latest = db.scalar(select(AgentVersion.version).where(AgentVersion.agent_id == account.id).order_by(AgentVersion.version.desc())) or 0
    version = AgentVersion(agent_id=account.id, version=latest + 1, config=values, created_by=principal.user.id)
    db.add(version)
    db.flush()
    account.config_version_id = version.id
    return version


def set_lifecycle(db: Session, principal: Principal, account: AgentAccount, state: str, version_id: int | None, allow_fake: bool) -> None:
    lock_runtime(db)
    require_permission(db, principal, "agents.manage")
    db.refresh(account)
    if state == "active":
        if principal.company.policy.get("emergency_paused", False):
            raise HTTPException(403, "Clear the company emergency pause before activating agents")
        selected_id = version_id or account.config_version_id
        version = db.get(AgentVersion, selected_id) if selected_id else None
        if version is None or version.agent_id != account.id:
            raise HTTPException(422, "Configuration version does not belong to this agent")
        validate_config(db, principal, version.config, agent_id=account.id, allow_fake=allow_fake)
        account.active_version_id = version.id
    account.state = state
    legacy = db.get(Agent, account.id)
    legacy.is_active = state == "active"
    db.flush()


def retrieve_knowledge(db: Session, company_id: int, agent_id: int, source_ids: list[int], cross_company: bool = False) -> list[dict]:
    company = db.get(Company, company_id)
    account = db.get(AgentAccount, agent_id)
    if (not source_ids or company is None or company.status != "active" or account is None or account.company_id != company_id
            or not company.policy.get("allow_knowledge", True) or company.policy.get("emergency_paused", False)
            or not config_for(db, account, active=True).get("allow_knowledge", True)):
        return []
    query = select(KnowledgeSource).join(AgentAccount, AgentAccount.id == KnowledgeSource.agent_id).where(
        KnowledgeSource.id.in_(source_ids), KnowledgeSource.company_id == company_id,
        KnowledgeSource.agent_id == agent_id, AgentAccount.company_id == company_id,
        KnowledgeSource.deleted_at.is_(None))
    if cross_company:
        query = query.where(KnowledgeSource.visibility == "shareable")
    retrieved, remaining = [], 20_000
    for source in db.scalars(query.order_by(KnowledgeSource.id)):
        if remaining <= 0:
            break
        content = source.content[:remaining]
        retrieved.append({"name": source.name, "content": content})
        remaining -= len(content)
    return retrieved


def knowledge_data(source: KnowledgeSource, include_content: bool = False) -> dict:
    result = {"id": source.id, "name": source.name, "visibility": source.visibility,
              "source_url": source.source_url, "created_at": source.created_at}
    if include_content:
        result["content"] = source.content
    return result


def companies_allowed(a: Company, b: Company, kind: str) -> bool:
    if (a.status != "active" or b.status != "active" or a.policy.get("emergency_paused", False) or b.policy.get("emergency_paused", False)
            or (kind == "public" and (not a.policy.get("allow_discovery", True) or not b.policy.get("allow_discovery", True)))):
        return False
    if (kind == "public" or a.id != b.id) and (not a.network_opt_in or not b.network_opt_in):
        return False
    return (a.policy.get(f"allow_{kind}", True) and b.policy.get(f"allow_{kind}", True)
            and b.id not in a.policy.get("blocked_company_ids", []) and a.id not in b.policy.get("blocked_company_ids", []))


def company_pair_allowed(db: Session, a: AgentAccount, b: AgentAccount, kind: str) -> bool:
    if kind not in ("public", "direct", "group") or a.state != "active" or b.state != "active":
        return False
    company_a = db.get(Company, a.company_id, populate_existing=True)
    company_b = db.get(Company, b.company_id, populate_existing=True)
    if not company_a or not company_b or not companies_allowed(company_a, company_b, kind):
        return False
    # Active versions are the currently approved permissions, even while a new draft is edited.
    config_a, config_b = config_for(db, a, active=True), config_for(db, b, active=True)
    return bool(config_a and config_b and config_a.get(f"allow_{kind}", False) and config_b.get(f"allow_{kind}", False)
                and b.company_id not in config_a.get("blocked_company_ids", [])
                and a.company_id not in config_b.get("blocked_company_ids", []))


def reject_private_material(db: Session, company_id: int, title: str, content: str) -> None:
    # shortcut: literal excerpts do not detect paraphrases; add dedicated DLP when semantic screening is required.
    text = normalize(f"{title} {content}")
    sources = db.scalars(select(KnowledgeSource.content).where(KnowledgeSource.company_id == company_id, KnowledgeSource.visibility == "private"))
    for source in sources:
        private = normalize(source)
        words = private.split()
        # Catch complete short secrets and overlapping excerpts from larger documents.
        phrases = [private] + [" ".join(words[index:index + 6]) for index in range(max(0, len(words) - 5))]
        if any(phrase and phrase in text for phrase in phrases):
            raise HTTPException(422, "Publication contains private knowledge source material")


def _publication_rules(db: Session, principal: Principal, payload: dict, autonomous: bool, *, approving: bool = False) -> tuple[AgentAccount | None, str]:
    db.refresh(principal.company)
    company = principal.company
    if company.status != "active":
        raise HTTPException(403, "Company access is suspended")
    account = owner_agent(db, principal, payload["agent_id"]) if payload.get("agent_id") else None
    config = config_for(db, account, active=True) if account else {}
    if autonomous and (account is None or account.state != "active" or not config):
        raise HTTPException(422, "Autonomous publishing requires an active owned agent")
    if autonomous and normalize(payload["category"]) not in {normalize(c) for c in config.get("allowed_publishing_categories", [])}:
        raise HTTPException(403, "Publishing category is not allowed")
    status = payload["status"]
    if payload["visibility"] == "network":
        if not company.network_opt_in or not company.policy.get("allow_public", True):
            raise HTTPException(403, "Workspace network publishing is disabled")
        if account and (account.state != "active" or not config.get("allow_public", False)):
            raise HTTPException(403, "Agent network publishing is disabled")
        reject_private_material(db, company.id, payload["title"], payload["content"])
    from app.services.policy import evaluate_action
    evaluation = evaluate_action(action="publication.publish" if payload["visibility"] == "network" else "publication.private", content=payload["title"] + " " + payload["content"],
        company_policy=company.policy, configs=[config] if account else [], business_category=payload["category"])
    if evaluation.disposition == "reject":
        raise HTTPException(403, "Publication is prohibited by current business policy")
    if evaluation.disposition == "approval" and not approving:
        status = "draft"
    return account, status


def publish(db: Session, principal: Principal, payload, autonomous: bool = False, *, approval_requested: bool = False) -> Publication:
    values = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload)
    lock_runtime(db)
    if not autonomous:
        require_permission(db, principal, "posts.publish")
    account, status = _publication_rules(db, principal, values, autonomous)
    author_type = "agent" if autonomous else "human"
    content_hash = hashlib.sha256(json.dumps({key: values.get(key) for key in ("agent_id", "title", "content", "category", "visibility")}, sort_keys=True).encode()).hexdigest()
    previous = db.scalar(select(Publication).where(Publication.company_id == principal.company.id,
                                                 Publication.idempotency_key == values["idempotency_key"]))
    if previous:
        if previous.content_hash != content_hash or previous.author_type != author_type:
            raise HTTPException(409, "Idempotency key is already used by different content")
        return previous
    duplicate = db.scalar(select(Publication).where(Publication.company_id == principal.company.id, Publication.content_hash == content_hash))
    if duplicate:
        return duplicate
    publication = Publication(company_id=principal.company.id, author_type=author_type,
                              user_id=None if autonomous else principal.user.id, agent_id=account.id if account else None,
                              **{key: values[key] for key in ("title", "content", "category", "visibility", "idempotency_key")},
                              status=status, content_hash=content_hash, config_version_id=account.active_version_id if account else None,
                              policy_version=principal.company.policy_version,
                              published_at=utc_now() if status == "published" else None)
    db.add(publication)
    db.flush()
    from app.services.policy import evaluate_action
    config = config_for(db, account, active=True) if account else {}
    evaluation = evaluate_action(action="publication.publish" if publication.visibility == "network" else "publication.private", content=publication.title + " " + publication.content,
        company_policy=principal.company.policy, configs=[config] if account else [], business_category=publication.category,
        requested_approval=approval_requested)
    if evaluation.disposition == "approval":
        publication.status, publication.published_at = "draft", None
        from app.services.approvals import request_approval
        request_approval(db, company_id=publication.company_id, agent_id=publication.agent_id, requesting_user_id=publication.user_id,
            action_type="publication.publish", source_type="publication", source_id=publication.id, content=publication.content,
            evaluation=evaluation, config_version_id=publication.config_version_id, policy_version=publication.policy_version)
    return publication


def publication_visible(db: Session, principal: Principal, publication: Publication) -> bool:
    if publication.company_id == principal.company.id:
        return True
    company = db.get(Company, publication.company_id)
    if publication.visibility != "network" or publication.status != "published" or not companies_allowed(principal.company, company, "public"):
        return False
    if publication.agent_id:
        account = db.get(AgentAccount, publication.agent_id)
        config = config_for(db, account, active=True)
        return (account.state == "active" and config.get("allow_public", False)
                and principal.company.id not in config.get("blocked_company_ids", []))
    return True


def owner_publication(db: Session, principal: Principal, publication_id: int) -> Publication:
    publication = db.get(Publication, publication_id)
    if publication is None or publication.company_id != principal.company.id:
        raise HTTPException(404, "Publication not found")
    return publication


def publication_data(db: Session, publication: Publication) -> dict:
    from app.db.network import ApprovalRequest
    approval = db.scalar(select(ApprovalRequest).where(ApprovalRequest.source_type == "publication", ApprovalRequest.source_id == publication.id)) if publication.status == "draft" else None
    return {"approval_request_id": approval.id if approval else None, "approval_status": approval.status if approval else None, "id": publication.id, "company_id": publication.company_id,
            "company_name": db.get(Company, publication.company_id).name,
            **{key: getattr(publication, key) for key in ("author_type", "user_id", "agent_id", "title", "content", "category", "visibility", "status", "config_version_id", "policy_version", "created_at", "published_at")}}


def approve_publication(db: Session, principal: Principal, publication: Publication, *, reviewed: bool = False) -> None:
    lock_runtime(db)
    require_permission(db, principal, "approvals.manage" if reviewed else "posts.publish")
    from app.db.network import ApprovalRequest
    approval = db.scalar(select(ApprovalRequest).where(ApprovalRequest.source_type == "publication", ApprovalRequest.source_id == publication.id))
    if approval is not None and not reviewed:
        require_permission(db, principal, "approvals.manage")
        from app.services.approvals import review
        result = review(db, principal, approval, approve=True)
        if result.status != "executed":
            db.commit()  # Retain the audited refusal before the compatibility endpoint returns an error.
            raise HTTPException(403, "Publication approval has not executed")
        return
    if publication.status == "published":
        return
    values = {key: getattr(publication, key) for key in ("agent_id", "title", "content", "category", "visibility", "status")}
    account, _ = _publication_rules(db, principal, {**values, "status": "published"}, publication.author_type == "agent", approving=True)
    from app.services.policy import evaluate_action
    configurations = [config_for(db, account, active=True)] if account else []
    if account and publication.config_version_id:
        version = db.get(AgentVersion, publication.config_version_id)
        if version and version.agent_id == account.id:
            configurations.append(version.config)
    evaluation = evaluate_action(action="publication.publish" if publication.visibility == "network" else "publication.private",
        content=publication.title + " " + publication.content, company_policy=principal.company.policy,
        configs=configurations, business_category=publication.category)
    if evaluation.disposition == "reject":
        raise HTTPException(403, "Publication is prohibited by current business policy")
    if not reviewed and evaluation.disposition == "approval":
        from app.services.approvals import request_approval
        request_approval(db, company_id=publication.company_id, agent_id=publication.agent_id, requesting_user_id=publication.user_id,
            action_type="publication.publish", source_type="publication", source_id=publication.id, content=publication.content,
            evaluation=evaluation, config_version_id=publication.config_version_id, policy_version=principal.company.policy_version)
        return
    now = utc_now()
    if publication.author_type == "agent":
        from app.db.network import PublishingJob
        from app.schemas.network import RuntimeDecision
        from app.services.publishing_runtime import latest_output, publishing_allowed
        from app.services.response_generation import PolicyViolationError
        from app.services.runtime import combined_limits, validate_reply
        version = db.get(AgentVersion, publication.config_version_id)
        if version is None or version.agent_id != account.id:
            raise HTTPException(403, "Publication configuration is unavailable")
        config = version.config
        publishing_allowed(db, account, config, principal.company, publication.category, publication.visibility)
        job = db.scalar(select(PublishingJob).where(PublishingJob.publication_id == publication.id,
                                                  PublishingJob.config_version_id == publication.config_version_id).order_by(PublishingJob.id))
        source = f"{publication.title} {job.brief if job else ''} {publication.category}"
        try:
            decision = RuntimeDecision(action="reply", reason="Owner publication approval", content=publication.content)
            validate_reply(db, account, config, principal.company, decision, source_content=source, action="publication.publish" if publication.visibility == "network" else "publication.private", business_category=publication.category)
        except (ValidationError, PolicyViolationError):
            raise HTTPException(403, "Publication no longer satisfies agent output policy") from None
        latest = latest_output(db, account.id)
        limits = combined_limits(db, account, config, principal.company)
        if latest and latest + timedelta(seconds=limits["cooldown_seconds"]) > now:
            raise HTTPException(409, "Agent output cooldown is active")
    publication.status = "published"
    publication.published_at = now
    publication.policy_version = principal.company.policy_version


def discovery_data(record: DiscoveryRecord) -> dict:
    return {key: getattr(record, key) for key in ("agent_id", "agent_name", "company_id", "eligible", "selected", "score", "explanation", "signals")}


def discovery_allowed(db: Session, principal: Principal, publication: Publication, source: AgentAccount | None, account: AgentAccount, config: dict) -> bool:
    company = db.get(Company, account.company_id)
    return bool(publication.status == "published" and account.state == "active" and config.get("discoverable", False)
                and config.get("allow_public", False) and publication.visibility == "network"
                and companies_allowed(principal.company, company, "public")
                and principal.company.id not in config.get("blocked_company_ids", [])
                and (not source or (source.id != account.id and company_pair_allowed(db, source, account, "public"))))


def visible_discovery_data(db: Session, principal: Principal, publication: Publication, record: DiscoveryRecord) -> dict | None:
    account = db.get(AgentAccount, record.agent_id)
    source = db.get(AgentAccount, publication.agent_id) if publication.agent_id else None
    values = discovery_data(record)
    if account is None or not discovery_allowed(db, principal, publication, source, account, config_for(db, account, active=True)):
        if account is None or account.company_id != principal.company.id:
            return None
        values.update(agent_name="Unavailable agent", eligible=False, selected=False, score=0,
                      explanation="Excluded by network authorization or lifecycle policy", signals={})
    return values


def discover(db: Session, principal: Principal, publication: Publication) -> list[DiscoveryRecord]:
    lock_runtime(db)
    require_permission(db, principal, "discovery.read")
    db.refresh(principal.company)
    source = db.get(AgentAccount, publication.agent_id) if publication.agent_id else None
    source_config = config_for(db, source, active=True) if source else {}
    allowed, denied, configs = [], [], {}
    for account in db.scalars(select(AgentAccount).order_by(AgentAccount.id)):
        config = config_for(db, account, active=True)
        if not discovery_allowed(db, principal, publication, source, account, config):
            company = db.get(Company, account.company_id)
            denied.append(DiscoveryRecord(publication_id=publication.id, agent_id=account.id, company_id=account.company_id,
                                          agent_name="Unavailable agent", eligible=False, selected=False, score=0,
                                          explanation="Excluded by network authorization or lifecycle policy", signals={},
                                          audit_json={"stage": "authorization", "state": account.state,
                                                      "company_network_opt_in": company.network_opt_in,
                                                      "company_allow_public": company.policy.get("allow_public", True),
                                                      "requester_network_opt_in": principal.company.network_opt_in,
                                                      "requester_allow_public": principal.company.policy.get("allow_public", True),
                                                      "company_pair_blocked": (company.id in principal.company.policy.get("blocked_company_ids", [])
                                                                               or principal.company.id in company.policy.get("blocked_company_ids", [])),
                                                      "company_policy_version": company.policy_version,
                                                      "config_version_id": account.active_version_id,
                                                      "agent_allow_public": config.get("allow_public", False),
                                                      "agent_discoverable": config.get("discoverable", False),
                                                      "agent_blocks_source": principal.company.id in config.get("blocked_company_ids", []),
                                                      "source_blocks_agent": account.company_id in source_config.get("blocked_company_ids", []),
                                                      "source_state": source.state if source else None,
                                                      "source_allow_public": source_config.get("allow_public", False) if source else None,
                                                      "is_publication_author": publication.agent_id == account.id,
                                                      "publication_status": publication.status,
                                                      "publication_visibility": publication.visibility,
                                                      "source_agent_id": publication.agent_id}))
            continue
        configs[account.id] = (account, config)
        interests = ([Interest("category", value) for value in config.get("categories", [])]
                     + [Interest("keyword", value) for value in dict.fromkeys(config.get("keywords", []) + config.get("topics", []))]
                     + [Interest("exclude", value) for value in config.get("excluded_topics", []) + db.get(Company, account.company_id).policy.get("excluded_topics", [])])
        allowed.append(AgentProfile(account.id, config["name"], True, tuple(interests)))
    relationships = [Relationship(publication.agent_id or 0, account.id, "partner")
                     for account, config in configs.values() if principal.company.id in config.get("partner_company_ids", [])]
    scored = evaluate_relevance(PostProfile(publication.id, publication.agent_id or 0, publication.title, publication.content, publication.category),
                                allowed, relationships, RelevanceConfig(get_relevance_threshold(), get_relevance_top_k()))
    records = denied + [DiscoveryRecord(publication_id=publication.id, agent_id=result.agent_id,
                                       company_id=configs[result.agent_id][0].company_id, agent_name=result.agent_name,
                                       eligible=result.eligible, selected=result.selected, score=result.final_score,
                                       explanation=("Excluded by topical policy" if not result.eligible else result.explanation),
                                       signals=({"category": result.category_score, "keyword": result.keyword_score,
                                                 "relationship": result.relationship_score} if result.eligible else {}),
                                       audit_json={"stage": "relevance", **result.to_dict(),
                                                   "threshold": get_relevance_threshold(), "top_k": get_relevance_top_k(),
                                                   "config_version_id": configs[result.agent_id][0].active_version_id,
                                                   "company_policy_version": db.get(Company, configs[result.agent_id][0].company_id).policy_version}) for result in scored]
    db.execute(delete(DiscoveryRecord).where(DiscoveryRecord.publication_id == publication.id))
    db.add_all(records)
    db.flush()
    return sorted(records, key=lambda record: record.agent_id)
