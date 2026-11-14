"""Agent registry endpoints."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_session
from app.schemas.agent import AgentCreate, AgentPatch, AgentRead
from app.services.agent_registry import (
    DuplicateAgentError,
    get_agent,
    list_agents,
    register_agent,
    update_agent,
)

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.get("", response_model=list[AgentRead])
def read_agents(db: Session = Depends(get_session)):
    return list_agents(db)


@router.get("/{agent_id}", response_model=AgentRead)
def read_agent(agent_id: int, db: Session = Depends(get_session)):
    agent = get_agent(db, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.post("", response_model=AgentRead, status_code=status.HTTP_201_CREATED)
def create_agent(payload: AgentCreate, db: Session = Depends(get_session)):
    try:
        return register_agent(db, payload)
    except DuplicateAgentError as exc:
        raise HTTPException(status_code=409, detail="Agent slug already exists") from exc


@router.patch("/{agent_id}", response_model=AgentRead)
def patch_agent(agent_id: int, payload: AgentPatch, db: Session = Depends(get_session)):
    agent = get_agent(db, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    try:
        return update_agent(db, agent, payload)
    except DuplicateAgentError as exc:
        raise HTTPException(status_code=409, detail="Agent update conflicts with stored data") from exc
