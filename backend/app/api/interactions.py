"""Agent interaction retrieval and retry endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.api.dependencies import get_response_service, get_session
from app.db.models import AgentInteraction
from app.schemas.interaction import InteractionRead
from app.services.agent_runner import AgentRunner, RetryNotAllowedError

router = APIRouter(prefix="/api/interactions", tags=["interactions"])


@router.get("/{interaction_id}", response_model=InteractionRead)
def get_interaction(interaction_id: int, db: Session = Depends(get_session)):
    interaction = db.scalar(
        select(AgentInteraction).options(joinedload(AgentInteraction.comment))
        .where(AgentInteraction.id == interaction_id)
    )
    if interaction is None:
        raise HTTPException(status_code=404, detail="Interaction not found")
    return interaction


@router.post("/{interaction_id}/retry", response_model=InteractionRead)
def retry_interaction(
    interaction_id: int,
    db: Session = Depends(get_session),
    response_service=Depends(get_response_service),
):
    runner = AgentRunner(response_service)
    try:
        return runner.retry(db, interaction_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Interaction not found") from exc
    except RetryNotAllowedError as exc:
        raise HTTPException(
            status_code=409,
            detail="Only failed interactions can be retried",
        ) from exc
