"""Simulated source publishing and complete workflow endpoint."""
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.adapters.simulated_sources import InvalidSourcePayloadError, UnknownScenarioError
from app.api.dependencies import get_response_service, get_session
from app.schemas.post import DemoRequest, DemoResponse
from app.services.ingestion import UnknownSourceAuthorError, ingest_scenario
from app.services.orchestration import run_post_workflow
from app.services.post_detail import get_post_detail

router = APIRouter(prefix="/api/demo", tags=["demo"])


@router.post("/run", response_model=DemoResponse)
def run_demo(
    payload: DemoRequest,
    response: Response,
    db: Session = Depends(get_session),
    response_service=Depends(get_response_service),
):
    try:
        post, created = ingest_scenario(db, payload.scenario_id)
    except UnknownScenarioError as exc:
        raise HTTPException(status_code=404, detail="Unknown demo scenario") from exc
    except (InvalidSourcePayloadError, UnknownSourceAuthorError) as exc:
        raise HTTPException(status_code=422, detail="Demo source payload is invalid") from exc

    # Post persistence is committed by ingestion before routing or model calls begin.
    run_post_workflow(db, post, response_service)
    detail = get_post_detail(db, post.id)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return DemoResponse(scenario_id=payload.scenario_id, created=created, post=detail)
