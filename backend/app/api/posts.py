"""Post publishing, shared feed, and full detail endpoints."""
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_response_service, get_session
from app.schemas.post import PostCreate, PostDetailRead, PostFeed, PostRead
from app.services.orchestration import run_post_workflow
from app.services.post_detail import get_post_detail
from app.services.post_service import UnknownPostAuthorError, create_post, get_post, list_posts

router = APIRouter(prefix="/api/posts", tags=["posts"])


@router.get("", response_model=PostFeed)
def read_posts(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_session),
):
    return PostFeed(items=list_posts(db, limit, offset), limit=limit, offset=offset)


@router.get("/{post_id}", response_model=PostDetailRead)
def read_post(post_id: int, db: Session = Depends(get_session)):
    detail = get_post_detail(db, post_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Post not found")
    return detail


@router.post("", response_model=PostRead, status_code=status.HTTP_201_CREATED)
def publish_post(
    payload: PostCreate,
    response: Response,
    db: Session = Depends(get_session),
    response_service=Depends(get_response_service),
):
    try:
        post, created = create_post(db, payload)
    except UnknownPostAuthorError as exc:
        raise HTTPException(status_code=404, detail="Author agent not found") from exc
    run_post_workflow(db, post, response_service)
    if not created:
        response.status_code = status.HTTP_200_OK
    return post
