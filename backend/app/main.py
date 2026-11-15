"""FastAPI app factory; optional Gemini configuration does not block startup."""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging
import json
import os
import time
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.gemini import GeminiResponseAdapter
from app.api.dependencies import get_session
from app.db.session import SessionLocal, engine as default_engine
from app.services.response_generation import AgentResponseService, ResponseAdapter


def create_app(
    db_engine: Engine | None = None,
    session_factory: sessionmaker[Session] | None = None,
    initialize_database: bool = True,
    response_adapter: ResponseAdapter | None = None,
    runtime_adapter: ResponseAdapter | None = None,
    legacy_demo: bool = False,
) -> FastAPI:
    target_engine = db_engine or default_engine
    target_sessions = session_factory or (
        SessionLocal
        if db_engine is None
        else sessionmaker(bind=target_engine, autoflush=False, expire_on_commit=False)
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        from app.services.security import validate_configuration
        validate_configuration()
        if initialize_database:
            from app.db.migrations import upgrade_database
            upgrade_database(target_engine)
        yield

    application = FastAPI(title="AgentConnect API", version="3.0.0", lifespan=lifespan)
    application.state.db_engine = target_engine
    application.state.session_factory = target_sessions
    application.state.runtime_adapter = runtime_adapter
    request_logger = logging.getLogger("agentconnect.http")
    if not request_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        request_logger.addHandler(handler)
    request_logger.setLevel(logging.INFO)
    request_logger.propagate = False
    from fastapi.middleware.cors import CORSMiddleware
    from app.core.http import RequestSizeLimit
    origins = [origin.strip().rstrip("/") for origin in os.getenv("AGENTCONNECT_TRUSTED_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173").split(",") if origin.strip() and origin.strip() != "*"]
    application.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["Content-Type", "X-CSRF-Token", "X-Company-ID"])
    application.add_middleware(RequestSizeLimit)

    @application.middleware("http")
    async def private_api_cache_policy(request, call_next):
        started = time.monotonic()
        request_id = uuid4().hex
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        request_logger.info(json.dumps({"event": "http_request", "request_id": request_id,
            "method": request.method, "status_code": response.status_code, "duration_ms": round((time.monotonic() - started) * 1000)}))
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Vary"] = ", ".join(filter(None, [response.headers.get("Vary"), "Cookie", "X-Company-ID"]))
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "no-referrer"
        return response
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
    from app.services.audit import install_audit_hooks
    install_audit_hooks()
    from app.api.governance import router as governance_router
    from app.api.foundation import router as foundation_router
    from app.api.workspace import router as workspace_router
    from app.api.conversations import router as conversations_router
    from app.api.legacy import router as legacy_router
    from app.api.reporting import router as reporting_router
    # The retained factory argument never bypasses authentication or tenant checks.
    for router in (governance_router, foundation_router, workspace_router, conversations_router, legacy_router, reporting_router):
        application.include_router(router, prefix="/api/v1")
        application.include_router(router, prefix="/api", include_in_schema=False)

    @application.get("/api/v1/health", tags=["health"])
    @application.get("/api/health", tags=["health"], include_in_schema=False)
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

    @application.get("/api/v1/health/live", tags=["health"])
    def live():
        return {"status": "ok"}

    @application.get("/api/v1/health/ready", tags=["health"])
    def ready():
        from app.db.migrations import HEAD
        try:
            with target_engine.connect() as connection:
                revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
                mutex = connection.scalar(text("SELECT count(*) FROM runtime_mutex WHERE id=1"))
                if revision != HEAD or mutex != 1:
                    raise ValueError("Schema is not current")
        except Exception:
            raise HTTPException(503, detail={"status": "not_ready", "database": "unavailable_or_outdated"}) from None
        return {"status": "ready", "database": "ok", "schema": HEAD}

    return application


app = create_app()
