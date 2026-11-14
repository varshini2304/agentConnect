"""Post normalization, content hashing, duplicate detection and persistence."""
import hashlib
import json
import unicodedata

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.db.models import Agent, Post
from app.schemas.post import PostCreate


class UnknownPostAuthorError(Exception):
    pass


def _normalize_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split())


def content_hash(author_agent_id: int, title: str, content: str, category: str) -> str:
    normalized = [
        author_agent_id,
        _normalize_text(title).casefold(),
        _normalize_text(content).casefold(),
        _normalize_text(category).casefold(),
    ]
    payload = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def create_post(db: Session, data: PostCreate) -> tuple[Post, bool]:
    author = db.get(Agent, data.author_agent_id)
    if author is None:
        raise UnknownPostAuthorError(data.author_agent_id)

    title = _normalize_text(data.title)
    content = _normalize_text(data.content)
    category = _normalize_text(data.category).lower()
    digest = content_hash(author.id, title, content, category)
    existing = db.scalar(select(Post).options(joinedload(Post.author)).where(Post.content_hash == digest))
    if existing is not None:
        return existing, False

    post = Post(
        author_agent_id=author.id, title=title, content=content, category=category,
        content_hash=digest, source_type=data.source_type, source_ref=data.source_ref, author=author,
    )
    db.add(post)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        duplicate = db.scalar(select(Post).options(joinedload(Post.author)).where(Post.content_hash == digest))
        if duplicate is not None:
            return duplicate, False
        raise
    db.refresh(post)
    return post, True


def list_posts(db: Session, limit: int, offset: int) -> list[Post]:
    return list(db.scalars(
        select(Post).options(joinedload(Post.author))
        .order_by(Post.created_at.desc(), Post.id.desc()).limit(limit).offset(offset)
    ))


def get_post(db: Session, post_id: int) -> Post | None:
    return db.scalar(select(Post).options(joinedload(Post.author)).where(Post.id == post_id))
