"""Coordinates simulated source data with agent lookup and post publishing."""
from sqlalchemy.orm import Session

from app.adapters.simulated_sources import get_scenario
from app.schemas.post import PostCreate
from app.services.agent_registry import get_agent_by_slug
from app.services.post_service import UnknownPostAuthorError, create_post


class UnknownSourceAuthorError(Exception):
    pass


def ingest_scenario(db: Session, scenario_id: str):
    payload = get_scenario(scenario_id)
    agent = get_agent_by_slug(db, payload.author_agent_slug)
    if agent is None:
        raise UnknownSourceAuthorError(payload.author_agent_slug)
    try:
        return create_post(db, PostCreate(
            author_agent_id=agent.id, title=payload.title, content=payload.content,
            category=payload.category, source_type=payload.source_type, source_ref=payload.source_ref,
        ))
    except UnknownPostAuthorError as exc:
        raise UnknownSourceAuthorError(payload.author_agent_slug) from exc
