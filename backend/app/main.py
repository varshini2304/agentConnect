"""FastAPI app factory; optional Gemini configuration does not block startup."""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.gemini import GeminiResponseAdapter
from app.api.agents import router as agents_router
from app.api.dependencies import get_session
from app.api.demo import router as demo_router
from app.api.interactions import router as interactions_router
from app.api.notifications import router as notifications_router
from app.api.posts import router as posts_router
from app.db.models import Base
from app.db.seed import seed_agents
from app.db.session import SessionLocal, engine as default_engine
from app.services.response_generation import AgentResponseService, ResponseAdapter


def create_app(
    db_engine: Engine | None = None,
    session_factory: sessionmaker[Session] | None = None,
    initialize_database: bool = True,
    response_adapter: ResponseAdapter | None = None,
) -> FastAPI:
    target_engine = db_engine or default_engine
    target_sessions = session_factory or (
        SessionLocal
        if db_engine is None
        else sessionmaker(bind=target_engine, autoflush=False, expire_on_commit=False)
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if initialize_database:
            Base.metadata.create_all(bind=target_engine)
            with target_sessions() as db:
                seed_agents(db)
        yield

    application = FastAPI(title="AgentConnect API", version="0.2.0", lifespan=lifespan)
    application.state.db_engine = target_engine
    application.state.session_factory = target_sessions
    application.state.response_service = AgentResponseService(
        response_adapter or GeminiResponseAdapter()
    )

    def session_override():
        db = target_sessions()
        try:
            yield db
        finally:
            db.close()

    application.dependency_overrides[get_session] = session_override
    application.include_router(agents_router)
    application.include_router(posts_router)
    application.include_router(demo_router)
    application.include_router(notifications_router)
    application.include_router(interactions_router)

    @application.get("/api/health", tags=["health"])
    def health():
        try:
            with target_engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail={"status": "error", "database": "unavailable"},
            ) from exc
        return {"status": "ok", "database": "ok"}

    return application


app = create_app()
