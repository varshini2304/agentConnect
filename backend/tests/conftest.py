import pytest
from auth_helpers import LegacyClient as TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool

from app.adapters.fake_response import FakeResponseAdapter
from app.main import create_app


_FAKE_SKIP = {
    "should_respond": False,
    "reason": "The test adapter has no configured response to publish.",
    "comment": None,
}


def _default_test_adapter():
    # Startup seeds the stable initial agents with IDs 1 through 5.
    return FakeResponseAdapter({agent_id: _FAKE_SKIP for agent_id in range(1, 6)})


def _test_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    return engine


@pytest.fixture
def app_factory():
    engines = []

    def create(response_adapter=None, legacy_demo=True):
        engine = _test_engine()
        engines.append(engine)
        return create_app(
            db_engine=engine,
            response_adapter=response_adapter or _default_test_adapter(),
            legacy_demo=legacy_demo,
        )

    yield create
    for engine in engines:
        engine.dispose()


@pytest.fixture
def app(app_factory):
    return app_factory()


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client
