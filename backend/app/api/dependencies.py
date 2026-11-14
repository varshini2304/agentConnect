"""Database and application service dependencies."""
from collections.abc import Generator

from fastapi import Request
from sqlalchemy.orm import Session

from app.db.session import SessionLocal


def get_session() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_response_service(request: Request):
    return request.app.state.response_service
