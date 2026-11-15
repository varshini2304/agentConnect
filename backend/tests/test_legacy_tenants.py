"""Authenticated legacy workflows must stay within the selected company."""
from contextlib import ExitStack

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.adapters.fake_response import FakeResponseAdapter
from app.db.models import Agent, AgentInteraction, AgentInterest, Comment, Notification, RoutingDecision
from app.db.network import AgentAccount, CompanyMember, CompanyRole
from app.main import create_app
from app.services.response_generation import AgentResponseService


RESPOND = {"should_respond": True, "reason": "A useful payment eligibility detail is available.",
           "comment": "Please review the payment offer eligibility terms."}


@pytest.mark.parametrize("legacy_demo", [False, True])
def test_legacy_product_routes_require_authentication(legacy_demo):
    app = create_app(initialize_database=False, legacy_demo=legacy_demo)
    with TestClient(app) as client:
        for prefix in ("/api", "/api/v1"):
            for path in ("/posts", "/dashboard", "/legacy/agents", "/notifications", "/interactions"):
                assert client.get(prefix + path).status_code == 401, path


def _register(client, label):
    csrf = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    response = client.post("/api/v1/auth/register", headers={"X-CSRF-Token": csrf}, json={
        "company_name": label, "name": f"{label} Owner", "email": f"{label.lower()}@example.com",
        "password": "correct horse battery staple",
    })
    assert response.status_code == 201, response.text
    identity = response.json()
    client.headers["X-CSRF-Token"] = identity["csrf_token"]
    return identity["selected_company_id"]


def _agent(client, slug, *, interested=False):
    response = client.post("/api/v1/legacy/agents", json={
        "slug": slug, "company_name": slug.title(), "role": "Payments", "industry": "payments",
        "description": "Payment offers", "interests": [{"interest_type": "category", "value": "merchant_promotion"}] if interested else [],
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.fixture
def legacy_tenants():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    adapter = FakeResponseAdapter([RESPOND] * 12)
    app = create_app(db_engine=engine, session_factory=sessions, response_adapter=adapter)
    with ExitStack() as stack:
        first = stack.enter_context(TestClient(app))
        second = stack.enter_context(TestClient(app))
        first_company = _register(first, "LegacyOne")
        second_company = _register(second, "LegacyTwo")
        author = _agent(first, "swiggy")
        recipient = _agent(first, "own-payments", interested=True)
        foreign_author = _agent(second, "foreign-author")
        foreign_recipient = _agent(second, "foreign-payments", interested=True)
        yield first, second, sessions, adapter, (first_company, second_company, author, recipient, foreign_author, foreign_recipient)
    engine.dispose()


def _publish(client, author, title="Payment promotion"):
    return client.post("/api/v1/posts", json={"author_agent_id": author, "title": title,
        "content": "Review cashback payment eligibility.", "category": "merchant_promotion"})


def test_posts_and_workflow_never_route_or_expose_other_tenant(legacy_tenants):
    first, second, sessions, adapter, ids = legacy_tenants
    company, other_company, author, recipient, foreign_author, foreign_recipient = ids
    response = _publish(first, author)
    assert response.status_code == 201, response.text
    post_id = response.json()["id"]
    detail = first.get(f"/api/v1/posts/{post_id}").json()
    assert {row["agent_id"] for row in detail["routing_decisions"]} == {author, recipient}
    assert {row["recipient_agent_id"] for row in detail["notifications"]} == {recipient}
    assert {row["agent_id"] for row in detail["interactions"]} == {recipient}
    assert {row["agent_id"] for row in adapter.calls} == {recipient}
    assert second.get("/api/v1/posts").json()["items"] == []
    assert second.get(f"/api/v1/posts/{post_id}").status_code == 404
    assert _publish(second, author).status_code == 404
    assert first.get(f"/api/v1/legacy/agents/{foreign_author}").status_code == 404
    assert first.patch(f"/api/v1/legacy/agents/{foreign_author}", json={"is_active": False}).status_code == 404
    assert {row["id"] for row in first.get("/api/v1/legacy/agents").json()} == {author, recipient}
    notification_id = detail["notifications"][0]["id"]
    interaction_id = detail["interactions"][0]["id"]
    assert second.get("/api/v1/notifications").json() == []
    assert second.get("/api/v1/interactions").json() == []
    assert second.patch(f"/api/v1/notifications/{notification_id}/read").status_code == 404
    assert second.post(f"/api/v1/notifications/{notification_id}/read").status_code == 404
    assert second.get(f"/api/v1/interactions/{interaction_id}").status_code == 404
    assert second.post(f"/api/v1/interactions/{interaction_id}/retry").status_code == 404
    assert first.patch(f"/api/v1/notifications/{notification_id}/read").json()["read_at"]
    counts = first.get("/api/v1/dashboard").json()
    assert (counts["agents"], counts["posts"], counts["notifications"], counts["interactions"]) == (2, 1, 1, 1)
    with sessions() as db:
        for model in (Notification, AgentInteraction, RoutingDecision, Comment):
            assert {row.company_id for row in db.scalars(select(model))} == {company}


def test_demo_resolves_author_only_from_owned_agents_and_remains_idempotent(legacy_tenants):
    first, second, _, adapter, ids = legacy_tenants
    author = ids[2]
    response = first.post("/api/v1/demo/run", json={"scenario_id": "swiggy-diwali-promotion"})
    assert response.status_code == 201, response.text
    post = response.json()["post"]
    assert post["author_agent_id"] == author
    assert post["source_ref"] == "scenario:swiggy-diwali-promotion"
    assert second.post("/api/v1/demo/run", json={"scenario_id": "swiggy-diwali-promotion"}).status_code == 404
    assert second.post("/api/v1/demo/run", json={"scenario_id": "swiggy-diwali-promotion", "author_agent_id": author}).status_code == 404
    repeated = first.post("/api/v1/demo/run", json={"scenario_id": "swiggy-diwali-promotion"})
    assert repeated.status_code == 200
    assert repeated.json()["post"]["id"] == post["id"]
    assert len(adapter.calls) == 1
    selected = second.post("/api/v1/demo/run", json={"scenario_id": "swiggy-diwali-promotion", "author_agent_id": ids[4]})
    assert selected.status_code == 201, selected.text
    assert selected.json()["post"]["author_agent_id"] == ids[4]
    assert {call["agent_id"] for call in adapter.calls} == {ids[3], ids[5]}


def test_post_detail_hides_historical_foreign_routing_metadata(legacy_tenants):
    first, _, sessions, _, ids = legacy_tenants
    company, other_company, author, _, _, foreign_recipient = ids
    published = _publish(first, author)
    post_id = published.json()["id"]
    with sessions() as db:
        routing = RoutingDecision(company_id=other_company, post_id=post_id, agent_id=foreign_recipient,
            score=0.9, eligible=True, selected=True, reason_json={"secret": "foreign routing audit"})
        notification = Notification(company_id=other_company, post_id=post_id, recipient_agent_id=foreign_recipient,
            score=0.9, reason_json={"secret": "foreign notification audit"}, status="failed")
        db.add_all([routing, notification])
        db.flush()
        interaction = AgentInteraction(company_id=other_company, post_id=post_id, agent_id=foreign_recipient,
            notification_id=notification.id, status="failed", decision_json={"secret": "foreign model output"})
        db.add(interaction)
        db.flush()
        db.add(Comment(company_id=other_company, post_id=post_id, agent_id=foreign_recipient,
            interaction_id=interaction.id, content="Foreign private comment"))
        db.commit()
    detail = first.get(f"/api/v1/posts/{post_id}")
    assert detail.status_code == 200
    assert "foreign" not in detail.text.lower()
    # Incorrect tenant metadata must not override an agent's intrinsic owner.
    with sessions() as db:
        db.scalar(select(RoutingDecision).where(RoutingDecision.agent_id == foreign_recipient)).company_id = company
        db.scalar(select(Notification).where(Notification.recipient_agent_id == foreign_recipient)).company_id = company
        db.scalar(select(AgentInteraction).where(AgentInteraction.agent_id == foreign_recipient)).company_id = company
        db.scalar(select(Comment).where(Comment.agent_id == foreign_recipient)).company_id = company
        db.commit()
    assert "foreign" not in first.get(f"/api/v1/posts/{post_id}").text.lower()


def test_failed_interaction_retry_preserves_tenant_and_policy_boundary(legacy_tenants):
    first, second, sessions, _, ids = legacy_tenants
    adapter = FakeResponseAdapter([RuntimeError("provider unavailable"), RESPOND])
    first.app.state.response_service = AgentResponseService(adapter)
    post_id = _publish(first, ids[2]).json()["id"]
    interaction = first.get(f"/api/v1/posts/{post_id}").json()["interactions"][0]
    assert interaction["status"] == "failed"
    assert first.get("/api/v1/dashboard").json()["failed_interactions"] == 1
    assert second.post(f"/api/v1/interactions/{interaction['id']}/retry").status_code == 404
    assert len(adapter.calls) == 1
    retry = first.post(f"/api/v1/interactions/{interaction['id']}/retry")
    assert retry.status_code == 200, retry.text
    assert retry.json()["status"] == "responded"
    assert len(adapter.calls) == 2
    with sessions() as db:
        assert db.get(AgentInteraction, interaction["id"]).company_id == ids[0]
        assert db.scalar(select(Comment)).company_id == ids[0]
    assert first.post(f"/api/v1/interactions/{interaction['id']}/retry").status_code == 409


def test_legacy_permissions_are_checked_fresh_and_publisher_can_publish(legacy_tenants):
    first, _, sessions, _, ids = legacy_tenants
    company, _, author, recipient, _, _ = ids
    with sessions() as db:
        membership = db.scalar(select(CompanyMember).where(CompanyMember.company_id == company))
        publisher = db.scalar(select(CompanyRole).where(CompanyRole.company_id == company, CompanyRole.slug == "publisher"))
        membership.role_id, membership.role = publisher.id, publisher.slug
        db.commit()
    assert _publish(first, author).status_code == 201
    assert first.get("/api/v1/posts").status_code == 200
    assert first.patch(f"/api/v1/legacy/agents/{recipient}", json={"is_active": False}).status_code == 403
    assert first.post("/api/v1/demo/run", json={"scenario_id": "swiggy-diwali-promotion"}).status_code == 403
    with sessions() as db:
        membership = db.scalar(select(CompanyMember).where(CompanyMember.company_id == company))
        viewer = db.scalar(select(CompanyRole).where(CompanyRole.company_id == company, CompanyRole.slug == "viewer"))
        membership.role_id, membership.role = viewer.id, viewer.slug
        db.commit()
    assert _publish(first, author, "Viewer denied").status_code == 403


def test_legacy_registration_scopes_public_slug_and_wraps_identity_atomically(legacy_tenants):
    first, second, sessions, _, ids = legacy_tenants
    payload = {"slug": "shared-agent", "company_name": "Shared Agent", "role": "Payments", "industry": "payments",
               "description": "Payment offers", "interests": [{"interest_type": "category", "value": "merchant_promotion"}]}
    created = first.post("/api/v1/legacy/agents", json=payload)
    other = second.post("/api/v1/legacy/agents", json=payload)
    assert created.status_code == other.status_code == 201
    assert created.json()["slug"] == other.json()["slug"] == "shared-agent"
    assert created.json()["id"] != other.json()["id"]
    assert first.post("/api/v1/legacy/agents", json=payload).status_code == 409
    assert second.get(f"/api/v1/legacy/agents/{created.json()['id']}").status_code == 404
    assert first.get(f"/api/v1/legacy/agents/{created.json()['id']}").json()["slug"] == "shared-agent"
    with sessions() as db:
        from app.db.network import AgentVersion
        for company, response in [(ids[0], created), (ids[1], other)]:
            agent_id = response.json()["id"]
            identity = db.get(Agent, agent_id)
            account = db.get(AgentAccount, agent_id)
            version = db.get(AgentVersion, account.config_version_id)
            assert identity.company_id == account.company_id == company
            assert version.agent_id == identity.id
            assert version.config["allow_public"] is False
            assert version.config["categories"] == ["merchant_promotion"]
    post = _publish(second, other.json()["id"], "Public slug display")
    assert post.status_code == 201
    assert post.json()["author"]["slug"] == "shared-agent"
    updated = first.patch(f"/api/v1/legacy/agents/{created.json()['id']}", json={"interests": payload["interests"]})
    assert updated.status_code == 200, updated.text
    assert [item["value"] for item in updated.json()["interests"]] == ["merchant_promotion"]


def test_legacy_patch_pauses_wrapper_and_keeps_configuration_history(legacy_tenants):
    first, _, sessions, _, _ = legacy_tenants
    created = first.post("/api/v1/legacy/agents", json={"slug": "versioned-legacy", "company_name": "Original",
        "role": "Payments", "industry": "payments", "description": "Original profile", "interests": []}).json()
    agent_id = created["id"]
    with sessions() as db:
        from app.db.network import AgentVersion
        account = db.get(AgentAccount, agent_id)
        original_version = account.active_version_id
        original = db.get(AgentVersion, original_version)
        original.config = {**original.config, "must_not_do": ["financial commitments"], "require_approval": True}
        db.commit()
    changed = first.patch(f"/api/v1/legacy/agents/{agent_id}", json={"description": "Updated profile", "is_active": False})
    assert changed.status_code == 200, changed.text
    with sessions() as db:
        account = db.get(AgentAccount, agent_id)
        assert account.state == "paused"
        assert account.active_version_id == original_version
        assert account.config_version_id != original_version
        assert db.get(AgentVersion, original_version).config["description"] == "Original profile"
        draft = db.get(AgentVersion, account.config_version_id)
        assert draft.config["description"] == "Updated profile"
        assert draft.config["require_approval"] is True
        assert draft.config["must_not_do"] == ["financial commitments"]
    resumed = first.patch(f"/api/v1/legacy/agents/{agent_id}", json={"description": "Latest draft", "is_active": True})
    assert resumed.status_code == 200, resumed.text
    with sessions() as db:
        account = db.get(AgentAccount, agent_id)
        assert account.state == "active" and account.active_version_id == original_version
        assert db.get(AgentVersion, account.config_version_id).config["description"] == "Latest draft"
        account.state = "disabled"
        db.get(Agent, agent_id).is_active = False
        db.commit()
    assert first.patch(f"/api/v1/legacy/agents/{agent_id}", json={"is_active": True}).status_code == 409
    assert first.get(f"/api/v1/legacy/agents/{agent_id}").json()["is_active"] is False


def test_dashboard_does_not_disclose_counts_without_read_permissions(legacy_tenants):
    first, _, sessions, _, ids = legacy_tenants
    assert _publish(first, ids[2]).status_code == 201
    with sessions() as db:
        from app.db.network import RolePermissionGrant
        role = CompanyRole(company_id=ids[0], name="Company access", slug="company-access")
        db.add(role)
        db.flush()
        db.add(RolePermissionGrant(role_id=role.id, permission_key="company.read"))
        member = db.scalar(select(CompanyMember).where(CompanyMember.company_id == ids[0]))
        member.role_id, member.role = role.id, role.slug
        db.commit()
    response = first.get("/api/v1/dashboard")
    assert response.status_code == 200, response.text
    assert response.json()["agents"] == response.json()["posts"] == response.json()["notifications"] == 0
    assert first.get("/api/v1/posts").status_code == 403
