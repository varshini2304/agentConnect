"""Authenticated routes for the original demo and its preserved records."""
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import Field
from sqlalchemy.orm import Session

from app.adapters.simulated_sources import InvalidSourcePayloadError, UnknownScenarioError, get_scenario, list_scenarios
from app.api.dependencies import get_response_service, get_session
from app.db.models import utc_now
from app.schemas.agent import AgentCreate, AgentPatch, AgentRead
from app.schemas.interaction import InteractionRead
from app.schemas.notification import NotificationRead
from app.schemas.post import DemoRequest, DemoResponse, PostCreate, PostDetailRead, PostFeed, PostRead
from app.services import legacy
from app.services.agent_registry import DuplicateAgentError
from app.services.agent_runner import AgentRunner, RetryNotAllowedError
from app.services.orchestration import run_post_workflow
from app.services.security import permissions_for, require_permission
from app.services.workspace import Principal, current_principal, fake_available

router = APIRouter(tags=["legacy"])


class ScopedDemoRequest(DemoRequest):
    author_agent_id: int | None = Field(default=None, gt=0)


@router.get("/dashboard")
def read_dashboard(db: Session = Depends(get_session), principal: Principal = Depends(current_principal)):
    member = require_permission(db, principal, "company.read")
    return legacy.dashboard(db, principal.company.id, permissions_for(db, member))


@router.get("/legacy/agents", response_model=list[AgentRead])
def read_agents(db: Session = Depends(get_session), principal: Principal = Depends(current_principal)):
    require_permission(db, principal, "agents.read")
    return [legacy.agent_read(db, agent) for agent in legacy.list_agents(db, principal.company.id)]


@router.get("/legacy/agents/{agent_id}", response_model=AgentRead)
def read_agent(agent_id: int, db: Session = Depends(get_session), principal: Principal = Depends(current_principal)):
    require_permission(db, principal, "agents.read")
    agent = legacy.get_agent(db, principal.company.id, agent_id)
    if agent is None:
        raise HTTPException(404, "Agent not found")
    return legacy.agent_read(db, agent)


@router.post("/legacy/agents", response_model=AgentRead, status_code=status.HTTP_201_CREATED)
def create_agent(payload: AgentCreate, db: Session = Depends(get_session), principal: Principal = Depends(current_principal)):
    require_permission(db, principal, "agents.manage")
    try:
        agent = legacy.register_agent(db, principal, payload)
    except DuplicateAgentError as exc:
        raise HTTPException(409, "Agent slug already exists") from exc
    return legacy.agent_read(db, agent)


@router.patch("/legacy/agents/{agent_id}", response_model=AgentRead)
def patch_agent(agent_id: int, payload: AgentPatch, request: Request, db: Session = Depends(get_session),
                principal: Principal = Depends(current_principal)):
    require_permission(db, principal, "agents.manage")
    agent = legacy.get_agent(db, principal.company.id, agent_id)
    if agent is None:
        raise HTTPException(404, "Agent not found")
    try:
        return legacy.agent_read(db, legacy.update_agent(db, principal, agent_id, payload, allow_fake=fake_available(request)))
    except DuplicateAgentError as exc:
        raise HTTPException(409, "Agent update conflicts with stored data") from exc


@router.get("/posts", response_model=PostFeed)
def read_posts(limit: int = Query(default=20, ge=1, le=100), offset: int = Query(default=0, ge=0),
               db: Session = Depends(get_session), principal: Principal = Depends(current_principal)):
    require_permission(db, principal, "posts.read")
    return PostFeed(items=[legacy.post_read(db, post) for post in legacy.list_posts(db, principal.company.id, limit, offset)],
                    limit=limit, offset=offset)


@router.get("/posts/{post_id}", response_model=PostDetailRead)
def read_post(post_id: int, db: Session = Depends(get_session), principal: Principal = Depends(current_principal)):
    require_permission(db, principal, "posts.read")
    detail = legacy.get_post_detail(db, principal.company.id, post_id)
    if detail is None:
        raise HTTPException(404, "Post not found")
    return detail


@router.post("/posts", response_model=PostRead, status_code=status.HTTP_201_CREATED)
def publish_post(payload: PostCreate, response: Response, db: Session = Depends(get_session),
                 principal: Principal = Depends(current_principal), response_service=Depends(get_response_service)):
    require_permission(db, principal, "posts.publish")
    if legacy.get_agent(db, principal.company.id, payload.author_agent_id) is None:
        raise HTTPException(404, "Author agent not found")
    post, created = legacy.publish_post(db, principal, payload)
    run_post_workflow(db, post, response_service)
    if not created:
        response.status_code = status.HTTP_200_OK
    return legacy.post_read(db, post)


@router.get("/demo/scenarios")
def read_scenarios(db: Session = Depends(get_session), principal: Principal = Depends(current_principal)):
    require_permission(db, principal, "posts.read")
    agents = {legacy.public_slug(db, agent): agent for agent in legacy.list_agents(db, principal.company.id)}
    scenarios = []
    for scenario_id in list_scenarios():
        source = get_scenario(scenario_id)
        agent = agents.get(source.author_agent_slug)
        scenarios.append({"scenario_id": scenario_id, "author_agent_slug": source.author_agent_slug,
                          "title": source.title, "category": source.category, "available": agent is not None,
                          "author_agent_id": agent.id if agent else None})
    return scenarios


@router.post("/demo/run", response_model=DemoResponse, status_code=status.HTTP_201_CREATED)
def run_demo(payload: ScopedDemoRequest, response: Response, db: Session = Depends(get_session),
             principal: Principal = Depends(current_principal), response_service=Depends(get_response_service)):
    require_permission(db, principal, "posts.publish")
    require_permission(db, principal, "workflow.run")
    try:
        source = get_scenario(payload.scenario_id)
    except UnknownScenarioError as exc:
        raise HTTPException(404, "Unknown demo scenario") from exc
    except InvalidSourcePayloadError as exc:
        raise HTTPException(422, "Demo source payload is invalid") from exc
    if payload.author_agent_id:
        author = legacy.get_agent(db, principal.company.id, payload.author_agent_id)
    else:
        author = next((agent for agent in legacy.list_agents(db, principal.company.id)
                       if legacy.public_slug(db, agent) == source.author_agent_slug), None)
    if author is None:
        raise HTTPException(404, "Author agent not found in this company")
    post, created = legacy.publish_post(db, principal, PostCreate(author_agent_id=author.id, title=source.title, content=source.content,
                                              category=source.category, source_type=source.source_type, source_ref=source.source_ref))
    run_post_workflow(db, post, response_service)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return DemoResponse(scenario_id=payload.scenario_id, created=created,
                        post=legacy.get_post_detail(db, principal.company.id, post.id))


@router.get("/notifications", response_model=list[NotificationRead])
def read_notifications(limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0),
                       db: Session = Depends(get_session), principal: Principal = Depends(current_principal)):
    require_permission(db, principal, "posts.read")
    return legacy.list_notifications(db, principal.company.id, limit, offset)


@router.post("/notifications/{notification_id}/read", response_model=NotificationRead)
@router.patch("/notifications/{notification_id}/read", response_model=NotificationRead)
def mark_read(notification_id: int, db: Session = Depends(get_session), principal: Principal = Depends(current_principal)):
    require_permission(db, principal, "posts.read")
    notification = legacy.get_notification(db, principal.company.id, notification_id)
    if notification is None:
        raise HTTPException(404, "Notification not found")
    if notification.read_at is None:
        notification.read_at = utc_now()
        db.commit()
        db.refresh(notification)
    return notification


@router.get("/interactions", response_model=list[InteractionRead])
def read_interactions(limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0),
                      db: Session = Depends(get_session), principal: Principal = Depends(current_principal)):
    require_permission(db, principal, "posts.read")
    return legacy.list_interactions(db, principal.company.id, limit, offset)


@router.get("/interactions/{interaction_id}", response_model=InteractionRead)
def read_interaction(interaction_id: int, db: Session = Depends(get_session), principal: Principal = Depends(current_principal)):
    require_permission(db, principal, "posts.read")
    interaction = legacy.get_interaction(db, principal.company.id, interaction_id)
    if interaction is None:
        raise HTTPException(404, "Interaction not found")
    return legacy.interaction_read(interaction, principal.company.id)


@router.post("/interactions/{interaction_id}/retry", response_model=InteractionRead)
def retry_interaction(interaction_id: int, db: Session = Depends(get_session), principal: Principal = Depends(current_principal),
                      response_service=Depends(get_response_service)):
    require_permission(db, principal, "workflow.run")
    if legacy.get_interaction(db, principal.company.id, interaction_id) is None:
        raise HTTPException(404, "Interaction not found")
    try:
        interaction = AgentRunner(response_service).retry(db, interaction_id)
    except LookupError as exc:
        raise HTTPException(404, "Interaction not found") from exc
    except RetryNotAllowedError as exc:
        raise HTTPException(409, "Only failed interactions can be retried") from exc
    return legacy.interaction_read(interaction, principal.company.id)
