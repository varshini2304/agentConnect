from csv import DictWriter
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.db.network import (
    AgentAccount, Conversation, DiscoveryRecord, Invitation, Message, MessageDelivery,
    Publication,
)
from app.services.demo_csv import FIELDS, ingest_demo_csv
from app.services.runtime import run_once


@pytest.fixture
def app(app_factory):
    return app_factory(legacy_demo=False)


def _count(db, model, *filters):
    query = select(func.count(model.id))
    for condition in filters:
        query = query.where(condition)
    return db.scalar(query)


def test_startup_uses_managed_publication_discovery_and_delivery(app, client):
    factory = app.state.session_factory
    with factory() as db:
        assert _count(db, Publication, Publication.external_record_id.is_not(None)) == 5
        assert _count(db, DiscoveryRecord) == 25
        assert _count(db, DiscoveryRecord, DiscoveryRecord.selected.is_(True)) >= 2
        assert _count(db, Conversation) >= 1
        assert _count(db, Invitation, Invitation.status == "accepted") >= 1
        assert _count(db, MessageDelivery, MessageDelivery.status == "pending") >= 1
        assert db.scalar(select(func.count(AgentAccount.id))) >= 5

    before = {}
    with factory() as db:
        for model in (Publication, DiscoveryRecord, Conversation, Invitation, Message, MessageDelivery):
            before[model.__tablename__] = _count(db, model)
    assert ingest_demo_csv(factory) == 0
    with factory() as db:
        for model in (Publication, Conversation, Invitation, Message, MessageDelivery):
            assert _count(db, model) == before[model.__tablename__]


def _write_csv(path: Path, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = DictWriter(handle, fieldnames=sorted(FIELDS))
        writer.writeheader()
        writer.writerows(rows)


def _row(record_id, company="swiggy", publisher="swiggy"):
    return {
        "external_record_id": record_id, "company_slug": company,
        "publishing_agent_slug": publisher, "title": "Restaurant menu update",
        "description": "Participating restaurants share food menus and merchant promotions.",
        "category": "merchant_promotion", "published_at": "2026-11-10T10:00:00Z",
        "source_name": "Test source", "source_reference": "test/announcement",
    }


def test_valid_rows_survive_invalid_rows_and_source_identity_is_idempotent(client, app, tmp_path):
    path = tmp_path / "sample.csv"
    _write_csv(path, [
        _row("test-valid"),
        _row("test-unknown-company", company="no-such-company"),
        _row("test-unknown-publisher", publisher="no-such-agent"),
        _row("test-mismatched-publisher", company="phonepe", publisher="swiggy"),
        {**_row("test-malformed"), "published_at": "not-a-date"},
    ])
    factory = app.state.session_factory
    assert ingest_demo_csv(factory, path) == 1
    assert ingest_demo_csv(factory, path) == 0
    with factory() as db:
        assert _count(db, Publication, Publication.external_record_id == "test-valid") == 1
        for record_id in ("test-unknown-company", "test-unknown-publisher", "test-mismatched-publisher", "test-malformed"):
            assert _count(db, Publication, Publication.external_record_id == record_id) == 0


def test_missing_and_empty_csv_are_safe(client, app, tmp_path):
    missing = tmp_path / "missing.csv"
    empty = tmp_path / "empty.csv"
    empty.write_text("", encoding="utf-8")
    factory = app.state.session_factory
    assert ingest_demo_csv(factory, missing) == 0
    assert ingest_demo_csv(factory, empty) == 0


def test_worker_processes_demo_delivery_with_fake_adapter(client, app):
    class FakeAgent:
        provider_name = "fake"

        def generate(self, _system, _prompt, agent_id=None):
            return {"action": "reply", "reason": "The announcement is relevant to configured interests.",
                    "content": "The restaurant and merchant details are useful for this discussion."}

    factory = app.state.session_factory
    with factory() as db:
        before = _count(db, Message)
    assert run_once(factory, FakeAgent()) is True
    with factory() as db:
        assert _count(db, Message) == before + 1
        assert _count(db, MessageDelivery, MessageDelivery.status == "completed") >= 1
