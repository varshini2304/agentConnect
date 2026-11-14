"""Database boundary for pure relevance scoring and explanation persistence."""
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_relevance_threshold, get_relevance_top_k
from app.db.models import Agent, AgentRelationship, Post, RoutingDecision
from app.services.relevance import (
    AgentProfile, Interest, PostProfile, Relationship, RelevanceConfig, ScoringResult,
    evaluate_relevance,
)


def evaluate_and_persist_routing(db: Session, post: Post) -> list[ScoringResult]:
    stored = list(db.scalars(
        select(RoutingDecision).where(RoutingDecision.post_id == post.id)
        .order_by(RoutingDecision.agent_id)
    ))
    if stored:
        return [ScoringResult(**row.reason_json) for row in stored]

    agents = list(db.scalars(
        select(Agent).options(selectinload(Agent.interests)).order_by(Agent.id)
    ))
    relationships = list(db.scalars(select(AgentRelationship)))
    post_profile = PostProfile(
        id=post.id, author_agent_id=post.author_agent_id, title=post.title,
        content=post.content, category=post.category,
    )
    profiles = [
        AgentProfile(
            id=agent.id, name=agent.company_name, active=agent.is_active,
            interests=tuple(
                Interest(item.interest_type, item.value, item.weight)
                for item in agent.interests
            ),
        )
        for agent in agents
    ]
    relationship_profiles = [
        Relationship(row.source_agent_id, row.target_agent_id, row.relation, row.weight)
        for row in relationships
    ]
    results = evaluate_relevance(
        post_profile, profiles, relationship_profiles,
        RelevanceConfig(get_relevance_threshold(), get_relevance_top_k()),
    )
    for result in results:
        db.add(RoutingDecision(
            post_id=post.id, agent_id=result.agent_id, score=result.final_score,
            eligible=result.eligible, selected=result.selected, reason_json=result.to_dict(),
        ))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        stored = list(db.scalars(
            select(RoutingDecision).where(RoutingDecision.post_id == post.id)
            .order_by(RoutingDecision.agent_id)
        ))
        if stored:
            return [ScoringResult(**row.reason_json) for row in stored]
        raise
    return results
