"""Builds complete post detail responses from persisted Day 2 records."""
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.db.models import AgentInteraction, Comment, Notification, Post, RoutingDecision
from app.schemas.interaction import CommentRead, InteractionRead
from app.schemas.notification import AgentSummary, NotificationRead, RoutingDecisionRead
from app.schemas.post import PostDetailRead, PostRead


def get_post_detail(db: Session, post_id: int) -> PostDetailRead | None:
    post = db.scalar(select(Post).options(joinedload(Post.author)).where(Post.id == post_id))
    if post is None:
        return None
    routing = list(db.scalars(
        select(RoutingDecision).options(joinedload(RoutingDecision.agent))
        .where(RoutingDecision.post_id == post_id).order_by(RoutingDecision.agent_id)
    ))
    notifications = list(db.scalars(
        select(Notification).options(joinedload(Notification.recipient))
        .where(Notification.post_id == post_id).order_by(Notification.id)
    ))
    interactions = list(db.scalars(
        select(AgentInteraction).options(joinedload(AgentInteraction.comment))
        .where(AgentInteraction.post_id == post_id).order_by(AgentInteraction.agent_id)
    ))
    comments = list(db.scalars(
        select(Comment).where(Comment.post_id == post_id).order_by(Comment.created_at, Comment.id)
    ))
    selected_agents = {}
    for notification in notifications:
        selected_agents[notification.recipient_agent_id] = notification.recipient

    base = PostRead.model_validate(post).model_dump()
    return PostDetailRead(
        **base,
        routing_decisions=[RoutingDecisionRead.model_validate(row) for row in routing],
        selected_recipients=[
            AgentSummary(id=agent.id, slug=agent.slug, company_name=agent.company_name)
            for agent in selected_agents.values()
        ],
        notifications=[NotificationRead.model_validate(row) for row in notifications],
        interactions=[InteractionRead.model_validate(row) for row in interactions],
        comments=[CommentRead.model_validate(row) for row in comments],
    )
