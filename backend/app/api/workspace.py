"""Authenticated company workspaces, visual builder, and network feed."""
import re
from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field, StringConstraints, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import get_session
from app.core.config import get_gemini_model
from app.db.models import utc_now
from app.db.network import AgentAccount, AgentVersion, Company, DiscoveryRecord, KnowledgeSource, LoginSession, Publication, PublishingJob, User
from app.schemas.network import AgentConfig, CompanyPolicy, StrictModel
from app.services import workspace as service
from app.services.workspace import Principal, current_principal

router = APIRouter( tags=["workspace"])


class AgentInput(StrictModel):
    slug: str = Field(min_length=1, max_length=80)
    config: AgentConfig

    @field_validator("slug")
    @classmethod
    def slug_format(cls, value):
        value = value.lower()
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value):
            raise ValueError("Use letters, numbers, and hyphens for the slug")
        return value


class ConfigInput(StrictModel):
    config: AgentConfig


class LifecycleInput(StrictModel):
    state: Literal["draft", "active", "paused", "disabled", "archived"]
    version_id: int | None = Field(default=None, gt=0)


class KnowledgeInput(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=102400)
    visibility: Literal["private", "shareable"] = "private"
    source_url: str | None = Field(default=None, max_length=2000)

    @field_validator("content")
    @classmethod
    def byte_limit(cls, value):
        if len(value.encode()) > 102400:
            raise ValueError("Knowledge source exceeds 100KB")
        return value

    @field_validator("source_url")
    @classmethod
    def source_metadata(cls, value):
        if value is not None:
            parts = urlsplit(value)
            if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
                raise ValueError("Source URL must be an HTTP or HTTPS URL without credentials")
        return value


class PublicationInput(StrictModel):
    agent_id: int | None = Field(default=None, gt=0)
    title: str = Field(min_length=1, max_length=240)
    content: str = Field(min_length=1, max_length=20000)
    category: str = Field(min_length=1, max_length=80)
    visibility: Literal["network", "company"]
    status: Literal["draft", "published"] = "draft"
    idempotency_key: str = Field(min_length=1, max_length=100)


class PublishingJobInput(StrictModel):
    title: str = Field(min_length=1, max_length=240)
    brief: str = Field(min_length=1, max_length=4000)
    category: str = Field(min_length=1, max_length=80)
    visibility: Literal["network", "company"] = "network"
    idempotency_key: str = Field(min_length=1, max_length=100)


def commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A record with these details already exists") from None


@router.get("/platform")
def platform(request: Request, principal: Principal = Depends(current_principal)):
    providers = {"gemini": [get_gemini_model()]}
    if service.fake_available(request):
        providers["fake"] = ["deterministic"]
    return {"providers": providers, "limits": service.platform_limits()}


@router.get("/agents")
def agents(principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    return [service.agent_data(db, account) for account in db.scalars(select(AgentAccount).where(AgentAccount.company_id == principal.company.id).order_by(AgentAccount.id))]


@router.post("/agents", status_code=201)
def add_agent(payload: AgentInput, request: Request, principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    account = service.create_agent(db, principal, payload.slug, payload.config, service.fake_available(request))
    commit(db)
    return service.agent_data(db, account)


@router.get("/agents/{agent_id}")
def get_agent(agent_id: int, principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    return service.agent_data(db, service.owner_agent(db, principal, agent_id))


@router.put("/agents/{agent_id}/configuration")
def save_configuration(agent_id: int, payload: ConfigInput, request: Request, principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    account = service.owner_agent(db, principal, agent_id)
    service.save_version(db, principal, account, payload.config, service.fake_available(request))
    commit(db)
    return service.agent_data(db, account)


@router.post("/agents/{agent_id}/lifecycle")
def lifecycle(agent_id: int, payload: LifecycleInput, request: Request, principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    account = service.owner_agent(db, principal, agent_id)
    service.set_lifecycle(db, principal, account, payload.state, payload.version_id, service.fake_available(request))
    commit(db)
    return service.agent_data(db, account)


@router.get("/agents/{agent_id}/versions")
def versions(agent_id: int, principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    service.owner_agent(db, principal, agent_id)
    return [{"id": version.id, "version": version.version, "config": version.config, "created_at": version.created_at}
            for version in db.scalars(select(AgentVersion).where(AgentVersion.agent_id == agent_id).order_by(AgentVersion.version))]


@router.delete("/agents/{agent_id}")
def archive_agent(agent_id: int, request: Request, principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    account = service.owner_agent(db, principal, agent_id)
    service.set_lifecycle(db, principal, account, "archived", None, service.fake_available(request))
    commit(db)
    return {"ok": True}


@router.post("/agents/{agent_id}/publishing-jobs", status_code=201)
def queue_publication(agent_id: int, payload: PublishingJobInput, principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    from app.services.publishing_runtime import job_data, queue_publication as queue_job
    job = queue_job(db, principal, agent_id, payload)
    commit(db)
    return job_data(job)


@router.get("/publishing-jobs")
def publishing_jobs(principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    from app.services.publishing_runtime import job_data
    return [job_data(job) for job in db.scalars(select(PublishingJob).where(PublishingJob.company_id == principal.company.id).order_by(PublishingJob.id.desc()))]


@router.get("/agents/{agent_id}/knowledge")
def knowledge(agent_id: int, principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    service.owner_agent(db, principal, agent_id)
    return [service.knowledge_data(source) for source in db.scalars(select(KnowledgeSource).where(
        KnowledgeSource.agent_id == agent_id, KnowledgeSource.company_id == principal.company.id,
        KnowledgeSource.deleted_at.is_(None)).order_by(KnowledgeSource.id))]


@router.post("/agents/{agent_id}/knowledge", status_code=201)
def add_knowledge(agent_id: int, payload: KnowledgeInput, principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    service.owner_agent(db, principal, agent_id)
    source = KnowledgeSource(company_id=principal.company.id, agent_id=agent_id, owner_user_id=principal.user.id, **payload.model_dump())
    db.add(source)
    commit(db)
    return service.knowledge_data(source)


def owned_source(db: Session, principal: Principal, agent_id: int, source_id: int) -> KnowledgeSource:
    service.owner_agent(db, principal, agent_id)
    source = db.get(KnowledgeSource, source_id)
    if not source or source.company_id != principal.company.id or source.agent_id != agent_id or source.deleted_at:
        raise HTTPException(404, "Knowledge source not found")
    return source


@router.get("/agents/{agent_id}/knowledge/{source_id}")
def get_knowledge(agent_id: int, source_id: int, principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    return service.knowledge_data(owned_source(db, principal, agent_id, source_id), include_content=True)


@router.delete("/agents/{agent_id}/knowledge/{source_id}")
def delete_knowledge(agent_id: int, source_id: int, principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    service.lock_runtime(db)
    source = owned_source(db, principal, agent_id, source_id)
    source.deleted_at = utc_now()
    commit(db)
    return {"ok": True}


@router.get("/registry")
def registry(principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    profiles = []
    for account in db.scalars(select(AgentAccount).where(AgentAccount.state == "active").order_by(AgentAccount.id)):
        company = db.get(Company, account.company_id)
        config = service.config_for(db, account, active=True)
        if (company.network_opt_in and principal.company.network_opt_in and service.companies_allowed(principal.company, company, "public")
                and config.get("discoverable") and config.get("allow_public")
                and principal.company.id not in config.get("blocked_company_ids", [])):
            profiles.append(service.public_profile(db, account))
    return profiles


@router.get("/publications")
def publications(principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    return [service.publication_data(db, item) for item in db.scalars(select(Publication).order_by(Publication.id.desc()))
            if service.publication_visible(db, principal, item)]


@router.post("/publications", status_code=201)
def add_publication(payload: PublicationInput, principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    item = service.publish(db, principal, payload)
    commit(db)
    return service.publication_data(db, item)


@router.get("/publications/{publication_id}")
def get_publication(publication_id: int, principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    item = db.get(Publication, publication_id)
    if item is None or not service.publication_visible(db, principal, item):
        raise HTTPException(404, "Publication not found")
    return service.publication_data(db, item)


@router.post("/publications/{publication_id}/publish")
def approve_publication(publication_id: int, principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    item = service.owner_publication(db, principal, publication_id)
    service.approve_publication(db, principal, item)
    commit(db)
    return service.publication_data(db, item)


@router.post("/publications/{publication_id}/discover")
def discover(publication_id: int, principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    item = service.owner_publication(db, principal, publication_id)
    records = service.discover(db, principal, item)
    commit(db)
    return [data for record in records if (data := service.visible_discovery_data(db, principal, item, record)) is not None]


@router.get("/publications/{publication_id}/discovery")
def discovery(publication_id: int, principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    publication = service.owner_publication(db, principal, publication_id)
    return [data for record in db.scalars(select(DiscoveryRecord).where(
        DiscoveryRecord.publication_id == publication_id).order_by(DiscoveryRecord.agent_id))
        if (data := service.visible_discovery_data(db, principal, publication, record)) is not None]
