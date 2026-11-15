"""Company-owned views of the preserved demo records and workflows."""
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.config import get_gemini_model
from app.db.models import Agent, AgentInteraction, AgentInterest, Comment, Notification, Post, RoutingDecision
from app.db.network import AgentAccount, AgentVersion
from app.schemas.agent import AgentCreate, AgentPatch, AgentRead
from app.schemas.interaction import CommentRead, InteractionRead
from app.schemas.notification import AgentSummary, NotificationRead, RoutingDecisionRead
from app.schemas.post import PostDetailRead, PostRead
from app.schemas.network import AgentConfig
from app.services.agent_registry import DuplicateAgentError
from app.services.locking import lock_runtime
from app.services.security import Principal, require_permission


def agent_query(company_id: int):
    return select(Agent).where(Agent.company_id == company_id)


def post_query(company_id: int):
    return select(Post).where(Post.company_id == company_id,
                              Post.author_agent_id.in_(agent_query(company_id).with_only_columns(Agent.id)))


def notification_query(company_id: int):
    return select(Notification).where(
        Notification.company_id == company_id,
        Notification.recipient_agent_id.in_(agent_query(company_id).with_only_columns(Agent.id)),
        Notification.post_id.in_(post_query(company_id).with_only_columns(Post.id)),
    )


def interaction_query(company_id: int):
    return select(AgentInteraction).join(Notification, Notification.id == AgentInteraction.notification_id).where(
        AgentInteraction.company_id == company_id,
        AgentInteraction.agent_id == Notification.recipient_agent_id,
        AgentInteraction.post_id == Notification.post_id,
        Notification.id.in_(notification_query(company_id).with_only_columns(Notification.id)),
    )


def public_slug(db: Session, agent: Agent) -> str:
    account = db.get(AgentAccount, agent.id)
    return account.slug if account and account.company_id == agent.company_id else agent.slug


def agent_read(db: Session, agent: Agent) -> AgentRead:
    result = AgentRead.model_validate(agent)
    result.slug = public_slug(db, agent)
    return result


def post_read(db: Session, post: Post) -> PostRead:
    result = PostRead.model_validate(post)
    result.author.slug = public_slug(db, post.author)
    return result


def _profile_config(agent: Agent) -> dict:
    return AgentConfig(name=agent.company_name, description=agent.description, role=agent.role,
                       domain=agent.industry, purpose=agent.description, discoverable=False, model=get_gemini_model(),
                       categories=[item.value for item in agent.interests if item.interest_type == "category"],
                       keywords=[item.value for item in agent.interests if item.interest_type == "keyword"],
                       excluded_topics=[item.value for item in agent.interests if item.interest_type == "exclude"]).model_dump()


def register_agent(db: Session, principal: Principal, data: AgentCreate) -> Agent:
    lock_runtime(db)
    require_permission(db, principal, "agents.manage")
    company_id, user_id = principal.company.id, principal.user.id
    if data.is_active and principal.company.policy.get("emergency_paused", False):
        raise HTTPException(403, "Clear the company emergency pause before activating agents")
    if db.scalar(select(AgentAccount.id).where(AgentAccount.company_id == company_id, AgentAccount.slug == data.slug)):
        raise DuplicateAgentError(data.slug)
    slug = data.slug
    if db.scalar(select(Agent.id).where(Agent.slug == slug)):
        slug = f"legacy-{uuid4().hex}"
    agent = Agent(company_id=company_id, **data.model_dump(exclude={"slug", "interests"}), slug=slug,
                  interests=[AgentInterest(**item.model_dump()) for item in data.interests])
    try:
        db.add(agent)
        db.flush()
        account = AgentAccount(id=agent.id, company_id=company_id, slug=data.slug,
                               state="active" if agent.is_active else "draft")
        db.add(account)
        db.flush()
        version = AgentVersion(agent_id=agent.id, version=1, config=_profile_config(agent), created_by=user_id)
        db.add(version)
        db.flush()
        account.config_version_id = version.id
        if agent.is_active:
            account.active_version_id = version.id
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateAgentError(data.slug) from exc
    return get_agent(db, company_id, agent.id)


def update_agent(db: Session, principal: Principal, agent_id: int, data: AgentPatch, *, allow_fake: bool) -> Agent:
    from app.services.workspace import config_for, set_lifecycle

    lock_runtime(db)
    require_permission(db, principal, "agents.manage")
    agent = get_agent(db, principal.company.id, agent_id)
    if agent is None:
        raise HTTPException(404, "Agent not found")
    account = db.get(AgentAccount, agent_id)
    if account is not None and account.company_id != principal.company.id:
        raise HTTPException(404, "Agent not found")
    if data.is_active is True and account and account.state in {"disabled", "archived"}:
        raise HTTPException(409, "Use the agent lifecycle controls to reactivate this agent")
    try:
        updates = data.model_dump(exclude_unset=True)
        interests = updates.pop("interests", None)
        for key, value in updates.items():
            setattr(agent, key, value)
        if interests is not None:
            agent.interests.clear()
            # Delete old interests before reinserting the same unique keys.
            db.flush()
            agent.interests.extend(AgentInterest(**item) for item in interests)
        if account is not None:
            profile_fields = set(updates) - {"is_active"}
            if profile_fields or interests is not None:
                values = dict(config_for(db, account) or _profile_config(agent))
                for legacy_name, config_name in (("company_name", "name"), ("description", "description"),
                                                  ("role", "role"), ("industry", "domain")):
                    if legacy_name in profile_fields:
                        values[config_name] = updates[legacy_name]
                if interests is not None:
                    values.update({key: [item.value for item in agent.interests if item.interest_type == kind]
                                   for key, kind in (("categories", "category"), ("keywords", "keyword"), ("excluded_topics", "exclude"))})
                latest = db.scalar(select(func.max(AgentVersion.version)).where(AgentVersion.agent_id == agent_id)) or 0
                version = AgentVersion(agent_id=agent_id, version=latest + 1,
                                       config=AgentConfig.model_validate(values).model_dump(), created_by=principal.user.id)
                db.add(version)
                db.flush()
                account.config_version_id = version.id
            if data.is_active is False and account.state not in {"disabled", "archived"}:
                account.state = "paused"
            elif data.is_active is True:
                db.flush()
                set_lifecycle(db, principal, account, "active", account.active_version_id or account.config_version_id, allow_fake)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateAgentError(agent.slug) from exc
    return get_agent(db, principal.company.id, agent_id)


def list_agents(db: Session, company_id: int) -> list[Agent]:
    return list(db.scalars(agent_query(company_id).options(selectinload(Agent.interests)).order_by(Agent.id)))


def get_agent(db: Session, company_id: int, agent_id: int) -> Agent | None:
    return db.scalar(agent_query(company_id).options(selectinload(Agent.interests)).where(Agent.id == agent_id))



def publish_post(db: Session, principal: Principal, data):
    from app.services.policy import evaluate_action
    from app.services.post_service import create_post
    from app.services.workspace import reject_private_material

    lock_runtime(db)
    require_permission(db, principal, "posts.publish")
    if get_agent(db, principal.company.id, data.author_agent_id) is None:
        raise HTTPException(404, "Author agent not found")
    reject_private_material(db, principal.company.id, data.title, data.content)
    evaluation = evaluate_action(action="publication.private", content=data.title + " " + data.content,
        company_policy=principal.company.policy, configs=[], business_category=data.category)
    if evaluation.disposition == "reject":
        raise HTTPException(403, "Company policy prohibits this post; use governed publications for review")
    return create_post(db, data)

def list_posts(db: Session, company_id: int, limit: int, offset: int) -> list[Post]:
    return list(db.scalars(post_query(company_id).options(joinedload(Post.author))
                          .order_by(Post.created_at.desc(), Post.id.desc()).limit(limit).offset(offset)))


def list_notifications(db: Session, company_id: int, limit: int, offset: int) -> list[Notification]:
    return list(db.scalars(notification_query(company_id)
                          .order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit).offset(offset)))


def get_notification(db: Session, company_id: int, notification_id: int) -> Notification | None:
    return db.scalar(notification_query(company_id).where(Notification.id == notification_id))


def interaction_read(row: AgentInteraction, company_id: int) -> InteractionRead:
    result = InteractionRead.model_validate(row)
    comment = row.comment
    if comment is not None and (comment.company_id != company_id or comment.agent_id != row.agent_id
                                or comment.post_id != row.post_id):
        result.comment = None
    return result


def list_interactions(db: Session, company_id: int, limit: int, offset: int) -> list[InteractionRead]:
    rows = db.scalars(interaction_query(company_id).options(joinedload(AgentInteraction.comment))
                      .order_by(AgentInteraction.started_at.desc(), AgentInteraction.id.desc()).limit(limit).offset(offset))
    return [interaction_read(row, company_id) for row in rows]


def get_interaction(db: Session, company_id: int, interaction_id: int) -> AgentInteraction | None:
    return db.scalar(interaction_query(company_id).options(joinedload(AgentInteraction.comment))
                     .where(AgentInteraction.id == interaction_id))


def get_post_detail(db: Session, company_id: int, post_id: int) -> PostDetailRead | None:
    post = db.scalar(post_query(company_id).options(joinedload(Post.author)).where(Post.id == post_id))
    if post is None:
        return None
    owned_agent_ids = agent_query(company_id).with_only_columns(Agent.id)
    routing = list(db.scalars(select(RoutingDecision).where(
        RoutingDecision.company_id == company_id, RoutingDecision.post_id == post_id,
        RoutingDecision.agent_id.in_(owned_agent_ids),
    ).order_by(RoutingDecision.agent_id)))
    notifications = list(db.scalars(notification_query(company_id).options(joinedload(Notification.recipient))
                                   .where(Notification.post_id == post_id).order_by(Notification.id)))
    interactions = list(db.scalars(interaction_query(company_id).options(joinedload(AgentInteraction.comment))
                                  .where(AgentInteraction.post_id == post_id).order_by(AgentInteraction.agent_id)))
    comments = list(db.scalars(select(Comment).join(AgentInteraction, AgentInteraction.id == Comment.interaction_id).where(
        Comment.company_id == company_id, Comment.post_id == post_id,
        Comment.agent_id == AgentInteraction.agent_id, Comment.post_id == AgentInteraction.post_id,
        Comment.interaction_id.in_(interaction_query(company_id).with_only_columns(AgentInteraction.id)),
    ).order_by(Comment.created_at, Comment.id)))
    return PostDetailRead(
        **post_read(db, post).model_dump(),
        routing_decisions=[RoutingDecisionRead.model_validate(row) for row in routing],
        selected_recipients=[AgentSummary(id=row.recipient.id, slug=public_slug(db, row.recipient),
                                         company_name=row.recipient.company_name) for row in notifications],
        notifications=[NotificationRead.model_validate(row) for row in notifications],
        interactions=[interaction_read(row, company_id) for row in interactions],
        comments=[CommentRead.model_validate(row) for row in comments],
    )


def dashboard(db: Session, company_id: int, permissions: set[str]) -> dict[str, int]:
    queries = {"agents": agent_query(company_id), "posts": post_query(company_id),
               "notifications": notification_query(company_id), "interactions": interaction_query(company_id),
               "unread_notifications": notification_query(company_id).where(Notification.read_at.is_(None)),
               "failed_interactions": interaction_query(company_id).where(AgentInteraction.status == "failed")}
    counts = {name: (db.scalar(select(func.count()).select_from(query.subquery())) or 0)
              if ("agents.read" if name == "agents" else "posts.read") in permissions else 0
              for name, query in queries.items()}
    return {**counts, **{f"total_{name}": counts[name] for name in ("agents", "posts", "notifications", "interactions")}}
