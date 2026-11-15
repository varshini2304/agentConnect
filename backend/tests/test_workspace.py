"""Real database/API checks for tenant boundaries and the managed workspace."""
from datetime import timedelta

import pytest
from auth_helpers import CookieClient as TestClient, cookie_headers
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, utc_now
from app.db.network import AgentAccount, LoginSession, Publication, RuntimeMutex, User
from app.main import create_app


@pytest.fixture
def workspace(monkeypatch):
    monkeypatch.setenv("AGENTCONNECT_ENABLE_FAKE", "true")
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)
    with sessions() as db:
        db.add(RuntimeMutex(id=1, value=0))
        db.commit()
    app = create_app(db_engine=engine, session_factory=sessions, initialize_database=False)
    with TestClient(app) as client:
        yield client, sessions
    engine.dispose()


def register(client, label="Acme"):
    response = client.post("/api/auth/register", json={
        "company_name": label, "email": f"{label.lower()}@example.com",
        "password": "correct horse battery staple", "name": f"{label} Owner",
    })
    assert response.status_code == 201, response.text
    data = response.json()
    return cookie_headers(client, data["companies"][0]["id"]), data


def config(**changes):
    return {"name": "Payments assistant", "description": "Payment offers and checkout",
            "role": "Partnerships", "domain": "Payments", "purpose": "Discover useful offers",
            "categories": ["offers"], "keywords": ["cashback"], "allow_public": True,
            "provider": "fake", "model": "deterministic", **changes}


def agent(client, headers, slug="assistant", **changes):
    response = client.post("/api/agents", headers=headers, json={"slug": slug, "config": config(**changes)})
    assert response.status_code == 201, response.text
    return response.json()


def activate(client, headers, managed):
    response = client.post(f"/api/agents/{managed['id']}/lifecycle", headers=headers, json={"state": "active"})
    assert response.status_code == 200, response.text
    return response.json()


def opt_in(client, headers, **policy):
    response = client.patch("/api/companies/current", headers=headers, json={"network_opt_in": True, "policy": policy})
    assert response.status_code == 200, response.text


def publication(client, headers, **changes):
    response = client.post("/api/publications", headers=headers, json={
        "title": "Cashback campaign", "content": "Launch cashback offers for merchants",
        "category": "offers", "visibility": "network", "status": "published",
        "idempotency_key": "campaign-1", **changes,
    })
    assert response.status_code == 201, response.text
    return response.json()


def test_sessions_are_hashed_expire_and_revoke(workspace):
    client, sessions = workspace
    headers, data = register(client)
    assert client.get("/api/auth/me", headers=headers).json()["user"]["email"] == "acme@example.com"
    with sessions() as db:
        user = db.scalar(select(User))
        saved = db.scalar(select(LoginSession))
        assert user.password_hash != "correct horse battery staple"
        assert saved.token_hash not in headers["Cookie"]
        saved.expires_at = utc_now() - timedelta(seconds=1)
        db.commit()
    assert client.get("/api/auth/me", headers=headers).status_code == 401
    login = client.post("/api/auth/login", json={"email": " ACME@example.com ", "password": "correct horse battery staple"})
    assert login.status_code == 200
    headers = cookie_headers(client, login.json()["selected_company_id"])
    assert client.post("/api/auth/logout", headers=headers).status_code == 200
    assert client.get("/api/auth/me", headers=headers).status_code == 401
    assert client.post("/api/auth/login", json={"email": "acme@example.com", "password": "wrong"}).status_code == 401


def test_company_scoped_agents_version_pinning_and_foreign_access(workspace):
    client, _ = workspace
    first, _ = register(client)
    second, _ = register(client, "Other")
    assert client.get("/api/agents", headers={"Cookie": ""}).status_code == 401
    original = activate(client, first, agent(client, first))
    other = agent(client, second)
    assert original["id"] != other["id"]
    foreign = {**first, "X-Company-ID": second["X-Company-ID"]}
    assert client.get("/api/agents", headers=foreign).status_code == 403
    assert client.get(f"/api/agents/{original['id']}", headers=second).status_code == 404
    edited = client.put(f"/api/agents/{original['id']}/configuration", headers=first,
                        json={"config": config(name="Updated assistant")}).json()
    assert edited["active_version_id"] == original["active_version_id"]
    assert edited["config_version_id"] != original["active_version_id"]
    versions = client.get(f"/api/agents/{original['id']}/versions", headers=first).json()
    assert [v["version"] for v in versions] == [1, 2]
    assert client.post(f"/api/agents/{original['id']}/lifecycle", headers=first,
                       json={"state": "active", "version_id": other["config_version_id"]}).status_code == 422


def test_builder_rejects_unconfigured_provider_model_and_invalid_knowledge(workspace, monkeypatch):
    client, _ = workspace
    headers, _ = register(client)
    monkeypatch.setenv("AGENTCONNECT_ENABLE_FAKE", "false")
    response = client.post("/api/agents", headers=headers, json={"slug": "fake", "config": config()})
    assert response.status_code == 422
    response = client.post("/api/agents", headers=headers, json={"slug": "wrong", "config": config(provider="gemini", model="arbitrary")})
    assert response.status_code == 422
    monkeypatch.setenv("AGENTCONNECT_ENABLE_FAKE", "true")
    assert client.post("/api/agents", headers=headers,
                       json={"slug": "bad", "config": config(knowledge_source_ids=[999])}).status_code == 422
    assert client.post("/api/agents", headers=headers,
                       json={"slug": "empty", "config": config(name=" ")}).status_code == 422


def test_knowledge_is_owned_soft_deleted_and_cross_company_retrieval_is_shareable(workspace):
    from app.services.workspace import retrieve_knowledge

    client, sessions = workspace
    headers, _ = register(client)
    other, _ = register(client, "Other")
    managed = agent(client, headers)
    base = f"/api/agents/{managed['id']}/knowledge"
    private = client.post(base, headers=headers, json={"name": "Internal", "content": "Internal contract secret 93842", "visibility": "private"}).json()
    shared = client.post(base, headers=headers, json={"name": "Public", "content": "Published merchant information", "visibility": "shareable"}).json()
    assert "content" not in client.get(base, headers=headers).json()[0]
    assert client.get(f"{base}/{private['id']}", headers=headers).json()["content"] == "Internal contract secret 93842"
    assert client.get(f"{base}/{private['id']}", headers=other).status_code == 404
    with sessions() as db:
        assert retrieve_knowledge(db, int(headers["X-Company-ID"]), managed["id"], [private["id"], shared["id"]], cross_company=True) == [{"name": "Public", "content": "Published merchant information"}]
        assert retrieve_knowledge(db, int(other["X-Company-ID"]), managed["id"], [private["id"]]) == []
    assert client.delete(f"{base}/{private['id']}", headers=headers).status_code == 200
    assert client.get(f"{base}/{private['id']}", headers=headers).status_code == 404
    assert client.post(base, headers=headers, json={"name": "Too large", "content": "x" * 102401}).status_code == 422


def test_retrieval_bounds_combined_prompt_material(workspace):
    from app.services.workspace import retrieve_knowledge

    client, sessions = workspace
    headers, _ = register(client)
    managed = agent(client, headers)
    source = client.post(f"/api/agents/{managed['id']}/knowledge", headers=headers,
                         json={"name": "Long source", "content": "x" * 25000, "visibility": "shareable"}).json()
    with sessions() as db:
        retrieved = retrieve_knowledge(db, int(headers["X-Company-ID"]), managed["id"], [source["id"]], cross_company=True)
        assert retrieved[0]["name"] == "Long source"
        assert retrieved[0]["content"] == "x" * 20000


def test_network_publications_require_opt_in_and_prevent_private_source_disclosure(workspace):
    client, _ = workspace
    headers, _ = register(client)
    other, _ = register(client, "Other")
    managed = agent(client, headers)
    secret = "Internal contract secret 93842"
    client.post(f"/api/agents/{managed['id']}/knowledge", headers=headers, json={"name": "Internal", "content": secret})
    opt_in(client, headers)
    denied = client.post("/api/publications", headers=headers, json={"title": "Leak", "content": secret, "category": "offers", "visibility": "network", "status": "published", "idempotency_key": "leak"})
    assert denied.status_code == 422
    item = publication(client, headers)
    assert client.get(f"/api/publications/{item['id']}", headers=other).status_code == 404
    opt_in(client, other)
    assert client.get(f"/api/publications/{item['id']}", headers=other).status_code == 200
    assert client.post(f"/api/publications/{item['id']}/discover", headers=other).status_code == 404
    assert publication(client, headers)["id"] == item["id"]


def test_discovery_persists_authorization_exclusions_without_private_config(workspace):
    client, sessions = workspace
    headers, _ = register(client)
    other, _ = register(client, "Other")
    hidden, _ = register(client, "Hidden")
    opt_in(client, headers)
    opt_in(client, other)
    source = activate(client, headers, agent(client, headers))
    target = activate(client, other, agent(client, other, excluded_topics=["SECRET_EXCLUSION"]))
    topical = activate(client, other, agent(client, other, slug="excluded", excluded_topics=["cashback"]))
    excluded = activate(client, hidden, agent(client, hidden, name="PRIVATE_AGENT_NAME", excluded_topics=["PRIVATE_TERM"]))
    item = publication(client, headers, agent_id=source["id"])
    response = client.post(f"/api/publications/{item['id']}/discover", headers=headers)
    assert response.status_code == 200, response.text
    results = response.json()
    target_result = next(r for r in results if r["agent_id"] == target["id"])
    assert target_result["selected"] is True
    assert excluded["id"] not in {row["agent_id"] for row in results}
    assert "PRIVATE_AGENT_NAME" not in response.text and "PRIVATE_TERM" not in response.text
    assert "matched exclusion term" not in response.text
    assert client.get(f"/api/publications/{item['id']}/discovery", headers=headers).json() == results
    with sessions() as db:
        assert db.get(AgentAccount, target["id"]).state == "active"
        assert db.scalar(select(Publication)).id == item["id"]
        from app.db.network import DiscoveryRecord
        audits = {row.agent_id: row.audit_json for row in db.scalars(select(DiscoveryRecord))}
        assert audits[target["id"]]["stage"] == "relevance"
        assert audits[target["id"]]["selected"] is True
        assert audits[excluded["id"]]["stage"] == "authorization"
        assert audits[excluded["id"]]["company_network_opt_in"] is False
        assert audits[topical["id"]]["eligible"] is False
        assert "matched exclusion term: cashback" in audits[topical["id"]]["explanation"]


def test_limits_combine_platform_company_and_agent_without_escalation(workspace, monkeypatch):
    from app.services.workspace import effective_limits

    monkeypatch.setenv("AGENTCONNECT_LIMITS", '{"daily_runs":40,"cooldown_seconds":60}')
    limits = effective_limits({"limits": {"daily_runs": 90, "cooldown_seconds": 30}}, {"limits": {"daily_runs": 20, "cooldown_seconds": 120}})
    assert limits["daily_runs"] == 20
    assert limits["cooldown_seconds"] == 120


def test_autonomous_publishing_requires_category_and_approval_and_http_cannot_spoof_author(workspace):
    from app.db.network import Company
    from app.services.workspace import Principal, publish

    client, sessions = workspace
    headers, identity = register(client)
    opt_in(client, headers, require_publish_approval=True)
    managed = activate(client, headers, agent(client, headers, allowed_publishing_categories=["offers"]))
    body = {"agent_id": managed["id"], "title": "Offer", "content": "Cashback for merchants",
            "category": "offers", "visibility": "network", "status": "published", "idempotency_key": "auto-1"}
    assert client.post("/api/publications", headers=headers, json={**body, "author_type": "agent"}).status_code == 422
    with sessions() as db:
        principal = Principal(db.get(User, identity["user"]["id"]), db.get(Company, int(headers["X-Company-ID"])), "")
        item = publish(db, principal, body, autonomous=True)
        db.commit()
        assert item.author_type == "agent" and item.status == "draft" and item.user_id is None
        item_id = item.id
    approved = client.post(f"/api/publications/{item_id}/publish", headers=headers)
    assert approved.status_code == 200 and approved.json()["status"] == "published"
    client.patch("/api/companies/current", headers=headers, json={"policy": {"allow_public": False}})
    with sessions() as db:
        principal = Principal(db.get(User, identity["user"]["id"]), db.get(Company, int(headers["X-Company-ID"])), "")
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as denied:
            publish(db, principal, {**body, "idempotency_key": "auto-2"}, autonomous=True)
        assert denied.value.status_code == 403


def test_saved_discovery_redacts_an_agent_after_network_opt_out(workspace):
    client, _ = workspace
    headers, _ = register(client)
    other, _ = register(client, "Other")
    opt_in(client, headers)
    opt_in(client, other)
    source = activate(client, headers, agent(client, headers))
    target = activate(client, other, agent(client, other, name="Previously public assistant"))
    item = publication(client, headers, agent_id=source["id"])
    client.post(f"/api/publications/{item['id']}/discover", headers=headers)
    client.patch("/api/companies/current", headers=other, json={"network_opt_in": False})
    response = client.get(f"/api/publications/{item['id']}/discovery", headers=headers)
    assert "Previously public assistant" not in response.text
    assert target["id"] not in {row["agent_id"] for row in response.json()}


def test_password_preserves_spaces(workspace):
    client, _ = workspace
    password = "  twelve characters  "
    assert client.post("/api/auth/register", json={"company_name": "Acme", "email": "acme@example.com", "password": password, "name": "Owner"}).status_code == 201
    assert client.post("/api/auth/login", json={"email": "acme@example.com", "password": password}).status_code == 200
    assert client.post("/api/auth/login", json={"email": "acme@example.com", "password": password.strip()}).status_code == 401


def test_runtime_lock_fails_closed_when_uninitialized(workspace):
    from fastapi import HTTPException
    from app.services.workspace import lock_runtime

    _, sessions = workspace
    with sessions() as db:
        db.delete(db.get(RuntimeMutex, 1))
        db.commit()
        with pytest.raises(HTTPException) as denied:
            lock_runtime(db)
        assert denied.value.status_code == 503


def queue_publication(client, headers, managed, key="publish-1"):
    response = client.post(f"/api/agents/{managed['id']}/publishing-jobs", headers=headers, json={
        "title": "Cashback eligibility", "brief": "Discuss public cashback eligibility for merchants",
        "category": "offers", "visibility": "network", "idempotency_key": key,
    })
    assert response.status_code == 201, response.text
    return response.json()


def test_publishing_job_generates_agent_authored_publication_once(workspace):
    from app.adapters.fake_response import FakeResponseAdapter

    client, sessions = workspace
    headers, _ = register(client)
    opt_in(client, headers)
    managed = activate(client, headers, agent(client, headers, allowed_publishing_categories=["offers"]))
    private = client.post(f"/api/agents/{managed['id']}/knowledge", headers=headers,
                          json={"name": "Private source", "content": "Secret number PRIVATE_9183"}).json()
    shared = client.post(f"/api/agents/{managed['id']}/knowledge", headers=headers,
                         json={"name": "Public source", "content": "Public eligibility facts", "visibility": "shareable"}).json()
    client.put(f"/api/agents/{managed['id']}/configuration", headers=headers,
               json={"config": config(allowed_publishing_categories=["offers"], knowledge_source_ids=[private["id"], shared["id"]])})
    managed = activate(client, headers, managed)
    job = queue_publication(client, headers, managed)
    assert queue_publication(client, headers, managed)["id"] == job["id"]
    from app.services.publishing_runtime import run_publication_once
    adapter = FakeResponseAdapter([{"action": "reply", "reason": "Useful public update", "content": "Review public cashback eligibility before proceeding."}])
    assert run_publication_once(sessions, adapter)
    assert not run_publication_once(sessions, adapter)
    assert len(adapter.calls) == 1
    assert "PRIVATE_9183" not in adapter.calls[0]["prompt"]
    assert "Public eligibility facts" in adapter.calls[0]["prompt"]
    saved = client.get("/api/publishing-jobs", headers=headers).json()[0]
    assert saved["status"] == "completed" and saved["attempts"] == 1
    item = client.get(f"/api/publications/{saved['publication_id']}", headers=headers).json()
    assert item["author_type"] == "agent" and item["status"] == "published"
    assert item["config_version_id"] == managed["active_version_id"]
    assert saved["attempt_history"][0]["status"] == "completed"


@pytest.mark.parametrize("decision,approval,expected", [
    ({"action": "reply", "reason": "Needs review", "content": "Review cashback eligibility."}, True, "draft"),
    ({"action": "request_approval", "reason": "Needs review", "content": "Review cashback eligibility."}, False, "draft"),
    ({"action": "skip", "reason": "No useful update"}, False, None),
])
def test_publishing_decision_can_require_approval_or_skip(workspace, decision, approval, expected):
    from app.adapters.fake_response import FakeResponseAdapter

    client, sessions = workspace
    headers, _ = register(client)
    opt_in(client, headers, require_publish_approval=approval)
    managed = activate(client, headers, agent(client, headers, allowed_publishing_categories=["offers"]))
    queue_publication(client, headers, managed)
    from app.services.publishing_runtime import run_publication_once
    assert run_publication_once(sessions, FakeResponseAdapter([decision]))
    items = client.get("/api/publications", headers=headers).json()
    assert len(items) == (1 if expected else 0)
    if expected:
        assert items[0]["status"] == expected


def test_publishing_job_rechecks_disable_after_provider_and_sanitizes_errors(workspace):
    from app.adapters.fake_response import FakeResponseAdapter

    client, sessions = workspace
    headers, _ = register(client)
    opt_in(client, headers)
    managed = activate(client, headers, agent(client, headers, allowed_publishing_categories=["offers"]))
    queue_publication(client, headers, managed)
    from app.services.publishing_runtime import run_publication_once

    class PausingAdapter(FakeResponseAdapter):
        def generate(self, *args, **kwargs):
            with sessions() as db:
                db.get(AgentAccount, managed["id"]).state = "disabled"
                db.commit()
            return {"action": "reply", "reason": "Useful update", "content": "Review public cashback eligibility."}

    assert run_publication_once(sessions, PausingAdapter())
    assert client.get("/api/publications", headers=headers).json() == []
    saved = client.get("/api/publishing-jobs", headers=headers).json()[0]
    assert saved["status"] in ("skipped", "failed") and saved["error"] == "publishing_prohibited"
    activate(client, headers, managed)
    queue_publication(client, headers, managed, "publish-2")
    assert run_publication_once(sessions, FakeResponseAdapter([RuntimeError("SECRET_API_KEY")]))
    assert "SECRET_API_KEY" not in client.get("/api/publishing-jobs", headers=headers).text


def test_publishing_lease_is_fenced_and_recovered(workspace):
    from app.adapters.fake_response import FakeResponseAdapter

    client, sessions = workspace
    headers, _ = register(client)
    opt_in(client, headers)
    managed = activate(client, headers, agent(client, headers, allowed_publishing_categories=["offers"]))
    queue_publication(client, headers, managed)
    from app.services.publishing_runtime import claim_publication, finish_publication, run_publication_once
    now = utc_now()
    work = claim_publication(sessions, now)
    assert work is not None
    assert claim_publication(sessions, now) is None
    later = now + timedelta(seconds=60)
    adapter = FakeResponseAdapter([{"action": "reply", "reason": "Useful update", "content": "Review cashback eligibility."}])
    assert run_publication_once(sessions, adapter, now=later)
    assert not finish_publication(sessions, work, {"action": "reply", "reason": "Late", "content": "Late duplicate"}, now=later)
    saved = client.get("/api/publishing-jobs", headers=headers).json()[0]
    assert saved["attempts"] == 2 and saved["attempt_history"][0]["status"] == "abandoned"
    assert len(client.get("/api/publications", headers=headers).json()) == 1


def test_publishing_pins_approval_config_and_rechecks_new_category_permissions(workspace):
    from app.adapters.fake_response import FakeResponseAdapter
    from app.services.publishing_runtime import run_publication_once

    client, sessions = workspace
    headers, _ = register(client)
    opt_in(client, headers)
    managed = activate(client, headers, agent(client, headers, allowed_publishing_categories=["offers"], require_approval=True))
    queued = queue_publication(client, headers, managed)
    client.put(f"/api/agents/{managed['id']}/configuration", headers=headers,
               json={"config": config(allowed_publishing_categories=["offers"], require_approval=False)})
    activate(client, headers, managed)
    reply = {"action": "reply", "reason": "Useful update", "content": "Review cashback eligibility."}
    assert run_publication_once(sessions, FakeResponseAdapter([reply]))
    item = client.get("/api/publications", headers=headers).json()[0]
    assert item["status"] == "draft" and item["config_version_id"] == queued["config_version_id"]
    queue_publication(client, headers, managed, "publish-2")
    client.put(f"/api/agents/{managed['id']}/configuration", headers=headers,
               json={"config": config(allowed_publishing_categories=[])})
    activate(client, headers, managed)
    adapter = FakeResponseAdapter([reply])
    assert not run_publication_once(sessions, adapter)
    assert adapter.calls == []
    assert client.get("/api/publishing-jobs", headers=headers).json()[0]["status"] == "skipped"


def test_publishing_claims_respect_concurrent_and_daily_budget(workspace):
    from app.adapters.fake_response import FakeResponseAdapter
    from app.services.publishing_runtime import claim_publication, finish_publication, run_publication_once

    client, sessions = workspace
    headers, _ = register(client)
    opt_in(client, headers)
    managed = activate(client, headers, agent(client, headers, allowed_publishing_categories=["offers"],
                                              limits={"daily_runs": 1, "max_concurrent_runs": 1}))
    queue_publication(client, headers, managed)
    queue_publication(client, headers, managed, "publish-2")
    now = utc_now()
    first = claim_publication(sessions, now)
    assert first is not None and claim_publication(sessions, now) is None
    assert finish_publication(sessions, first, {"action": "skip", "reason": "No useful update"}, now=now)
    assert claim_publication(sessions, now + timedelta(seconds=2)) is None
    jobs = client.get("/api/publishing-jobs", headers=headers).json()
    assert jobs[0]["error"] == "daily_budget"
    assert run_publication_once(sessions, FakeResponseAdapter([{"action": "skip", "reason": "No useful update"}]), now=now + timedelta(days=1))


def test_publishing_jobs_reject_private_brief_and_other_company_access(workspace):
    client, _ = workspace
    headers, _ = register(client)
    other, _ = register(client, "Other")
    opt_in(client, headers)
    managed = activate(client, headers, agent(client, headers, allowed_publishing_categories=["offers"]))
    client.post(f"/api/agents/{managed['id']}/knowledge", headers=headers,
                json={"name": "Private source", "content": "Internal secret code PRIVATE_9183"})
    payload = {"title": "Secret", "brief": "Internal secret code PRIVATE_9183", "category": "offers", "visibility": "network", "idempotency_key": "leak"}
    assert client.post(f"/api/agents/{managed['id']}/publishing-jobs", headers=headers, json=payload).status_code == 422
    assert client.post(f"/api/agents/{managed['id']}/publishing-jobs", headers=other, json=payload).status_code == 404
    queue_publication(client, headers, managed)
    assert client.get("/api/publishing-jobs", headers=other).json() == []


@pytest.mark.parametrize("restriction", [
    {"must_not_do": ["cashback"]}, {"excluded_topics": ["cashback"]}, {"allowed_actions": ["skip", "request_approval"]},
])
def test_agent_publication_approval_rechecks_current_output_restrictions(workspace, restriction):
    from app.adapters.fake_response import FakeResponseAdapter
    from app.services.publishing_runtime import run_publication_once

    client, sessions = workspace
    headers, _ = register(client)
    opt_in(client, headers)
    managed = activate(client, headers, agent(client, headers, allowed_publishing_categories=["offers"], require_approval=True))
    queue_publication(client, headers, managed)
    assert run_publication_once(sessions, FakeResponseAdapter([{"action": "reply", "reason": "Needs review", "content": "Review cashback eligibility."}]))
    item = client.get("/api/publications", headers=headers).json()[0]
    client.put(f"/api/agents/{managed['id']}/configuration", headers=headers,
               json={"config": config(allowed_publishing_categories=["offers"], **restriction)})
    activate(client, headers, managed)
    assert client.post(f"/api/publications/{item['id']}/publish", headers=headers).status_code == 403
    assert client.get(f"/api/publications/{item['id']}", headers=headers).json()["status"] == "draft"


def test_duplicate_publication_preserves_original_provenance(workspace):
    from app.adapters.fake_response import FakeResponseAdapter
    from app.services.publishing_runtime import run_publication_once

    client, sessions = workspace
    headers, _ = register(client)
    opt_in(client, headers)
    managed = activate(client, headers, agent(client, headers, allowed_publishing_categories=["offers"]))
    queue_publication(client, headers, managed)
    reply = {"action": "reply", "reason": "Useful update", "content": "Review cashback eligibility."}
    now = utc_now()
    assert run_publication_once(sessions, FakeResponseAdapter([reply]), now=now)
    with sessions() as db:
        original = db.scalar(select(Publication))
        original_metadata = (original.id, original.config_version_id, original.created_at, original.published_at)
    client.put(f"/api/agents/{managed['id']}/configuration", headers=headers,
               json={"config": config(allowed_publishing_categories=["offers"], tone="friendly")})
    activate(client, headers, managed)
    queue_publication(client, headers, managed, "publish-2")
    assert run_publication_once(sessions, FakeResponseAdapter([reply]), now=now + timedelta(seconds=31))
    with sessions() as db:
        original = db.scalar(select(Publication))
        assert (original.id, original.config_version_id, original.created_at, original.published_at) == original_metadata


def test_agent_publication_approval_observes_cooldown_at_actual_publication_time(workspace):
    from app.adapters.fake_response import FakeResponseAdapter
    from app.services.publishing_runtime import latest_output, run_publication_once

    client, sessions = workspace
    headers, _ = register(client)
    opt_in(client, headers)
    managed = activate(client, headers, agent(client, headers, allowed_publishing_categories=["offers"], require_approval=True))
    for key, content in [("publish-1", "Review cashback eligibility."), ("publish-2", "Review merchant eligibility.")]:
        queue_publication(client, headers, managed, key)
        assert run_publication_once(sessions, FakeResponseAdapter([{"action": "reply", "reason": "Needs review", "content": content}]))
    with sessions() as db:
        items = list(db.scalars(select(Publication).order_by(Publication.id)))
        first_id, second_id = items[0].id, items[1].id
        items[0].created_at = utc_now() - timedelta(days=30)
        assert items[0].published_at is None
        db.commit()
    before = utc_now()
    assert client.post(f"/api/publications/{first_id}/publish", headers=headers).status_code == 200
    with sessions() as db:
        first_time = db.get(Publication, first_id).published_at
        assert latest_output(db, managed["id"]) >= before
    assert client.post(f"/api/publications/{first_id}/publish", headers=headers).status_code == 200
    assert client.post(f"/api/publications/{second_id}/publish", headers=headers).status_code == 409
    with sessions() as db:
        assert db.get(Publication, first_id).published_at == first_time
        assert db.get(Publication, second_id).status == "draft"
