"""Agent registry business operations."""
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.db.models import Agent, AgentInterest
from app.schemas.agent import AgentCreate, AgentPatch


class DuplicateAgentError(Exception):
    pass


def list_agents(db: Session) -> list[Agent]:
    return list(db.scalars(select(Agent).options(selectinload(Agent.interests)).order_by(Agent.id)))


def get_agent(db: Session, agent_id: int) -> Agent | None:
    return db.scalar(select(Agent).options(selectinload(Agent.interests)).where(Agent.id == agent_id))


def get_agent_by_slug(db: Session, slug: str) -> Agent | None:
    return db.scalar(select(Agent).where(Agent.slug == slug))


def register_agent(db: Session, data: AgentCreate) -> Agent:
    agent = Agent(
        slug=data.slug, company_name=data.company_name, role=data.role,
        industry=data.industry, description=data.description, is_active=data.is_active,
        interests=[
            AgentInterest(interest_type=item.interest_type, value=item.value, weight=item.weight)
            for item in data.interests
        ],
    )
    db.add(agent)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateAgentError(data.slug) from exc
    return get_agent(db, agent.id)


def update_agent(db: Session, agent: Agent, data: AgentPatch) -> Agent:
    updates = data.model_dump(exclude_unset=True)
    interests = updates.pop("interests", None)
    for key, value in updates.items():
        setattr(agent, key, value)
    if interests is not None:
        agent.interests.clear()
        agent.interests.extend(
            AgentInterest(interest_type=item.interest_type, value=item.value, weight=item.weight)
            for item in interests
        )
    db.add(agent)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateAgentError(agent.slug) from exc
    return get_agent(db, agent.id)
