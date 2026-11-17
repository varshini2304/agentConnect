"""Database boundary for hybrid relevance scoring and explanation persistence."""
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_relevance_threshold, get_relevance_top_k
from app.db.models import Agent, AgentRelationship, Post, RoutingDecision
from app.services.embedding_service import default_embedding_service
from app.services.relevance import (
    AgentProfile, Interest, PostProfile, Relationship, RelevanceConfig, ScoringResult,
    evaluate_relevance, get_default_relevance_config,
)


def evaluate_and_persist_routing(db: Session, post: Post) -> list[ScoringResult]:
    owned_agents = select(Agent.id).where(Agent.company_id == post.company_id)
    stored_query = select(RoutingDecision).where(
        RoutingDecision.post_id == post.id, RoutingDecision.company_id == post.company_id,
        RoutingDecision.agent_id.in_(owned_agents),
    ).order_by(RoutingDecision.agent_id)
    stored = list(db.scalars(stored_query))
    if stored:
        return [ScoringResult(**row.reason_json) for row in stored]

    agents = list(db.scalars(
        select(Agent).options(selectinload(Agent.interests))
        .where(Agent.company_id == post.company_id).order_by(Agent.id)
    ))
    relationships = list(db.scalars(select(AgentRelationship).where(
        AgentRelationship.source_agent_id.in_(owned_agents),
        AgentRelationship.target_agent_id.in_(owned_agents),
    )))

    # Prepare embedding text for post and agents
    post_text = default_embedding_service.text_for_post(post.title, post.category, post.content)
    agent_embed_inputs = []
    for agent in agents:
        categories = [i.value for i in agent.interests if i.interest_type == "category"]
        keywords = [i.value for i in agent.interests if i.interest_type == "keyword"]
        agent_text = default_embedding_service.text_for_agent(
            categories=categories,
            keywords=keywords,
            role=agent.role or "",
            domain=agent.industry or "",
            description=agent.description or "",
        )
        agent_embed_inputs.append((agent.id, agent_text))

    batch_requests = [("post", post.id, post_text)] + [("agent", aid, atext) for aid, atext in agent_embed_inputs]
    embeddings_map = default_embedding_service.get_or_create_embeddings_batch(db, batch_requests)
    post_embedding = embeddings_map.get(("post", post.id))

    post_profile = PostProfile(
        id=post.id, author_agent_id=post.author_agent_id, title=post.title,
        content=post.content, category=post.category, embedding=post_embedding,
    )
    profiles = [
        AgentProfile(
            id=agent.id, name=agent.company_name, active=agent.is_active,
            interests=tuple(
                Interest(item.interest_type, item.value, item.weight)
                for item in agent.interests
            ),
            embedding=embeddings_map.get(("agent", agent.id)),
            role=agent.role or "",
            domain=agent.industry or "",
            description=agent.description or "",
        )
        for agent in agents
    ]
    relationship_profiles = [
        Relationship(row.source_agent_id, row.target_agent_id, row.relation, row.weight)
        for row in relationships
    ]
    results = evaluate_relevance(
        post_profile, profiles, relationship_profiles,
        get_default_relevance_config(),
    )
    for result in results:
        db.add(RoutingDecision(
            company_id=post.company_id, post_id=post.id, agent_id=result.agent_id, score=result.final_score,
            eligible=result.eligible, selected=result.selected, reason_json=result.to_dict(),
        ))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        stored = list(db.scalars(stored_query))
        if stored:
            return [ScoringResult(**row.reason_json) for row in stored]
        raise
    return results
