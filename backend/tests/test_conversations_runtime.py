"""Product acceptance tests: persisted cross-company decisions, never live LLM calls."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json

from auth_helpers import CookieClient as TestClient, cookie_headers
import pytest
from sqlalchemy import select, func

from app.adapters.fake_response import FakeResponseAdapter
from app.adapters.gemini import MissingApiKeyError, ProviderTimeoutError
from app.db.models import utc_now
from app.db.network import (
    AgentAccount, AgentRun, AgentRunAttempt, ConversationMember, Message,
    MessageDelivery, RuntimeMutex,
)
from app.db.session import make_engine
from app.main import create_app


REPLY = {"action": "reply", "reason": "A relevant next step is available.", "content": "Please review the published eligibility details."}


@pytest.fixture
def product(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTCONNECT_ENABLE_FAKE", "true")
    engine = make_engine(f"sqlite:///{tmp_path / 'product.db'}")
    adapter = FakeResponseAdapter({i: REPLY for i in range(1, 30)})
    app = create_app(db_engine=engine, runtime_adapter=adapter)
    with TestClient(app) as client:
        yield client, app, adapter
    engine.dispose()


def register(client, label, opt_in=True):
    result = client.post("/api/auth/register", json={"company_name": label, "name": label + " owner", "email": label.lower() + "@example.test", "password": "correct horse battery staple"})
    assert result.status_code == 201, result.text
    data = result.json()
    headers = cookie_headers(client, data["companies"][0]["id"])
    assert client.patch("/api/companies/current", headers=headers, json={"network_opt_in": opt_in}).status_code == 200
    return headers


def agent(client, headers, label, **config):
    cfg = {"name": label, "description": label + " business agent", "role": "Business discovery", "domain": "commerce", "purpose": "Discuss public payment eligibility", "categories": ["payments"], "keywords": ["cashback", "payments"], "allow_public": True, "allowed_publishing_categories": ["payments"], "provider": "fake", "model": "deterministic", **config}
    response = client.post("/api/agents", headers=headers, json={"slug": "business", "config": cfg})
    assert response.status_code == 201, response.text
    row = response.json()
    response = client.post(f"/api/agents/{row['id']}/lifecycle", headers=headers, json={"state": "active"})
    assert response.status_code == 200, response.text
    return response.json()


def pair(product, **b_config):
    client, app, adapter = product
    ha, hb = register(client, "Swiggy"), register(client, "PhonePe")
    a, b = agent(client, ha, "Swiggy"), agent(client, hb, "PhonePe", **b_config)
    return ha, hb, a, b


def conversation(client, headers, a, b=None, kind="direct", key="conversation"):
    payload = {"kind": kind, "title": "Payment discussion", "agent_id": a["id"], "idempotency_key": key}
    if b:
        payload["recipient_agent_id"] = b["id"]
    r = client.post("/api/conversations", headers=headers, json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def accept(client, headers, conversation_id):
    invitation = next(i for i in client.get("/api/invitations", headers=headers).json() if i["conversation_id"] == conversation_id and i["status"] == "pending")
    r = client.post(f"/api/invitations/{invitation['id']}/respond", headers=headers, json={"accept": True})
    assert r.status_code == 200, r.text
    return r.json()


def send(client, headers, cid, aid, text="Discuss payments and cashback eligibility.", key="opening"):
    r = client.post(f"/api/conversations/{cid}/messages", headers=headers, json={"agent_id": aid, "content": text, "idempotency_key": key})
    assert r.status_code == 201, r.text
    return r.json()


def test_anonymous_default_has_no_legacy_write_bypass(product):
    client, _, _ = product
    assert client.get("/api/agents").status_code == 401
    assert client.post("/api/demo/run", json={"scenario_id": "swiggy-diwali-promotion"}).status_code == 401
    assert client.post("/api/posts", json={}).status_code == 401


def test_runtime_prompt_identifies_self_and_incoming_participant(product):
    from app.services.runtime import claim_work, finish_work
    client, app, _ = product
    ha, hb, a, b = pair(product)
    conv = conversation(client, ha, a, b)
    accept(client, hb, conv['id'])
    opening = send(client, ha, conv['id'], a['id'])
    work = claim_work(app.state.session_factory)
    prompt = json.loads(work.prompt)
    assert prompt['agent_id'] == b['id']
    assert prompt['incoming_message']['id'] == opening['id']
    assert prompt['incoming_message']['sender_agent_id'] == a['id']
    assert prompt['history'][-1]['is_self'] is False
    assert prompt['history'][-1]['author_type'] == 'human'
    assert finish_work(app.state.session_factory, work, REPLY)
    next_work = claim_work(app.state.session_factory)
    next_prompt = json.loads(next_work.prompt)
    assert next_prompt['agent_id'] == a['id']
    assert next_prompt['incoming_message']['sender_agent_id'] == b['id']
    assert next_prompt['history'][-1]['is_self'] is False
    assert next_prompt['history'][0]['is_self'] is True


def test_swiggy_phonepe_discovery_and_bounded_independent_conversation(product):
    from app.services.runtime import run_once
    client, app, adapter = product
    ha, hb, a, b = pair(product)
    post = client.post("/api/publications", headers=ha, json={"agent_id": a["id"], "title": "Payments eligibility", "content": "Public payments and cashback eligibility discussion.", "category": "payments", "visibility": "network", "status": "published", "idempotency_key": "announcement"})
    assert post.status_code == 201, post.text
    routing = client.post(f"/api/publications/{post.json()['id']}/discover", headers=ha).json()
    selected = next(x for x in routing if x["agent_id"] == b["id"])
    assert selected["selected"] and selected["explanation"] and selected["signals"]
    conv = conversation(client, ha, a, b)
    assert client.get(f"/api/conversations/{conv['id']}", headers=hb).status_code == 404
    accept(client, hb, conv["id"])
    opening = send(client, ha, conv["id"], a["id"])
    assert send(client, ha, conv["id"], a["id"])["id"] == opening["id"]
    now = utc_now()
    for i in range(12):
        run_once(app.state.session_factory, adapter, now=now + timedelta(seconds=31 * i))
    messages = client.get(f"/api/conversations/{conv['id']}/messages", headers=ha).json()["items"]
    assert len(messages) == 7  # one human message + three actual replies from each agent
    assert [m["sequence"] for m in messages] == list(range(1, 8))
    assert [m["sender_agent_id"] for m in messages[1:3]] == [b["id"], a["id"]]
    assert all(m["reply_depth"] <= 6 for m in messages)
    runs = client.get(f"/api/conversations/{conv['id']}/runs", headers=ha).json()
    assert runs and all(r["agent_id"] == a["id"] and r["config_version_id"] == a["active_version_id"] for r in runs)
    assert all(r["provider"] == "fake" and r["attempts"] for r in runs)
    hc = register(client, "Outsider")
    assert client.get(f"/api/conversations/{conv['id']}/messages", headers=hc).status_code == 404
    assert client.get(f"/api/agents/{a['id']}", headers=hb).status_code == 404


def test_group_invitation_policy_and_history_boundary(product):
    client, app, _ = product
    ha, hb, a, b = pair(product)
    hc = register(client, "Third")
    c = agent(client, hc, "Third")
    conv = conversation(client, ha, a, kind="group")
    send(client, ha, conv["id"], a["id"], "Earlier private discussion.")
    assert client.post(f"/api/conversations/{conv['id']}/invitations", headers=hc, json={"inviter_agent_id": c["id"], "recipient_agent_id": b["id"]}).status_code == 404
    inv = client.post(f"/api/conversations/{conv['id']}/invitations", headers=ha, json={"inviter_agent_id": a["id"], "recipient_agent_id": b["id"]})
    assert inv.status_code == 201
    assert client.post(f"/api/invitations/{inv.json()['id']}/respond", headers=ha, json={"accept": True}).status_code == 404
    accept(client, hb, conv["id"])
    assert client.get(f"/api/conversations/{conv['id']}/messages", headers=hb).json()["items"] == []
    send(client, ha, conv["id"], a["id"], "New shared discussion.", "new")
    assert len(client.get(f"/api/conversations/{conv['id']}/messages", headers=hb).json()["items"]) == 1
    assert client.patch("/api/companies/current", headers=hc, json={"policy": {"allow_group": False}}).status_code == 200
    assert client.post(f"/api/conversations/{conv['id']}/invitations", headers=hb, json={"inviter_agent_id": b["id"], "recipient_agent_id": c["id"]}).status_code == 403
    assert client.patch("/api/companies/current", headers=hc, json={"policy": {"allow_group": True}}).status_code == 200
    assert client.post(f"/api/conversations/{conv['id']}/invitations", headers=hb, json={"inviter_agent_id": b["id"], "recipient_agent_id": c["id"]}).status_code == 201
    accept(client, hc, conv["id"])
    assert client.get(f"/api/conversations/{conv['id']}/messages", headers=hc).json()["items"] == []
    assert client.post(f"/api/conversations/{conv['id']}/leave", headers=hb, json={"agent_id": b["id"]}).status_code == 200
    assert client.get(f"/api/conversations/{conv['id']}/messages", headers=hb).status_code == 404
    with app.state.session_factory() as db:
        member = db.scalar(select(ConversationMember).where(ConversationMember.agent_id == b["id"]))
        assert member.status == "left" and member.left_at


def test_pinned_version_and_emergency_pause(product):
    from app.services.runtime import run_once
    client, app, adapter = product
    ha, hb, a, b = pair(product)
    conv = conversation(client, ha, a, b)
    accept(client, hb, conv["id"])
    send(client, ha, conv["id"], a["id"])
    edited = client.put(f"/api/agents/{b['id']}/configuration", headers=hb, json={"config": {**b["config"], "tone": "friendly"}})
    assert edited.status_code == 200
    assert edited.json()["active_version_id"] == b["active_version_id"]
    assert client.post(f"/api/agents/{b['id']}/lifecycle", headers=hb, json={"state": "active", "version_id": edited.json()["config_version_id"]}).status_code == 200
    run_once(app.state.session_factory, adapter)
    runs = client.get(f"/api/conversations/{conv['id']}/runs", headers=hb).json()
    assert runs[0]["config_version_id"] == b["active_version_id"]
    client.post(f"/api/agents/{a['id']}/lifecycle", headers=ha, json={"state": "paused"})
    run_once(app.state.session_factory, adapter, now=utc_now() + timedelta(seconds=31))
    messages = client.get(f"/api/conversations/{conv['id']}/messages", headers=ha).json()["items"]
    assert len(messages) == 2


@pytest.mark.parametrize("result,error", [(MissingApiKeyError(), "missing_api_key"), (ProviderTimeoutError(), "provider_timeout"), ({"action": "reply", "reason": "Bad", "content": "We guarantee a cashback reward."}, "policy_rejected"), ({"action": "steal_secrets", "reason": "Bad"}, "invalid_decision")])
def test_provider_failure_and_policy_rejection_never_send(product, result, error):
    from app.services.runtime import run_once
    client, app, _ = product
    ha, hb, a, b = pair(product, excluded_topics=["guarantee"])
    conv = conversation(client, ha, a, b)
    accept(client, hb, conv["id"])
    send(client, ha, conv["id"], a["id"])
    adapter = FakeResponseAdapter([result] * 4)
    for i in range(5):
        run_once(app.state.session_factory, adapter, now=utc_now() + timedelta(seconds=120 * i))
    with app.state.session_factory() as db:
        assert db.scalar(select(func.count(Message.id))) == 1
        delivery = db.scalar(select(MessageDelivery))
        assert delivery.status == "failed" and delivery.error == error
        assert delivery.attempts <= 4


def test_private_knowledge_absent_from_cross_company_context(product):
    from app.services.runtime import run_once
    client, app, adapter = product
    ha, hb, a, b = pair(product)
    private = client.post(f"/api/agents/{b['id']}/knowledge", headers=hb, json={"name": "internal.txt", "content": "SECRET-PHONEPE-STRATEGY-742", "visibility": "private"})
    shared = client.post(f"/api/agents/{b['id']}/knowledge", headers=hb, json={"name": "public.txt", "content": "Public eligibility review guidance", "visibility": "shareable"})
    ids = [private.json()["id"], shared.json()["id"]]
    cfg = {**b["config"], "knowledge_source_ids": ids}
    edited = client.put(f"/api/agents/{b['id']}/configuration", headers=hb, json={"config": cfg}).json()
    client.post(f"/api/agents/{b['id']}/lifecycle", headers=hb, json={"state": "active", "version_id": edited["config_version_id"]})
    conv = conversation(client, ha, a, b)
    accept(client, hb, conv["id"])
    send(client, ha, conv["id"], a["id"])
    run_once(app.state.session_factory, adapter)
    assert "SECRET-PHONEPE" not in json.dumps(adapter.calls)
    assert "Public eligibility review guidance" in json.dumps(adapter.calls)
    assert client.get(f"/api/agents/{b['id']}/knowledge/{ids[0]}", headers=ha).status_code == 404


def test_duplicate_claim_and_abandoned_lease_recovery(product):
    from app.services.runtime import claim_work, run_once, finish_work
    client, app, adapter = product
    ha, hb, a, b = pair(product)
    conv = conversation(client, ha, a, b)
    accept(client, hb, conv["id"])
    send(client, ha, conv["id"], a["id"])
    now = utc_now()
    work = claim_work(app.state.session_factory, now)
    assert work and claim_work(app.state.session_factory, now) is None
    assert run_once(app.state.session_factory, adapter, now=now + timedelta(seconds=100))
    assert not finish_work(app.state.session_factory, work, REPLY, now=now + timedelta(seconds=101))
    with app.state.session_factory() as db:
        attempts = list(db.scalars(select(AgentRunAttempt).order_by(AgentRunAttempt.id)))
        assert attempts[0].status == "abandoned"
        assert attempts[1].status == "completed"
        assert db.scalar(select(func.count(Message.id))) == 2


def test_parallel_final_turn_reservations_are_atomic(product):
    from app.services.runtime import claim_work, finish_work
    client, app, _ = product
    ha, hb, a, b = pair(product, limits={"max_agent_messages": 1})
    conv = conversation(client, ha, a, b)
    accept(client, hb, conv["id"])
    send(client, ha, conv["id"], a["id"], key="first")
    send(client, ha, conv["id"], a["id"], key="second")
    now = utc_now()
    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = list(executor.map(lambda _: claim_work(app.state.session_factory, now), range(2)))
    valid = [w for w in claims if w]
    assert len(valid) == 1
    assert finish_work(app.state.session_factory, valid[0], REPLY, now=now)
    with app.state.session_factory() as db:
        assert db.scalar(select(func.count(Message.id)).where(Message.author_type == "agent", Message.sender_agent_id == b["id"])) == 1


def test_human_approval_and_disallowed_actions(product):
    from app.services.runtime import run_once
    client, app, _ = product
    ha, hb, a, b = pair(product, require_approval=True)
    conv = conversation(client, ha, a, b)
    accept(client, hb, conv["id"])
    send(client, ha, conv["id"], a["id"])
    run_once(app.state.session_factory, FakeResponseAdapter([REPLY]))
    pending = client.get("/api/approvals", headers=hb).json()
    assert len(pending) == 1
    assert client.post(f"/api/approvals/{pending[0]['id']}/respond", headers=ha, json={"accept": True}).status_code == 404
    assert client.post(f"/api/approvals/{pending[0]['id']}/respond", headers=hb, json={"accept": True}).status_code == 200
    assert len(client.get(f"/api/conversations/{conv['id']}/messages", headers=ha).json()["items"]) == 2


def test_pause_between_claim_and_persist_revokes_reply(product):
    from app.services.runtime import claim_work, finish_work
    client, app, _ = product
    ha, hb, a, b = pair(product)
    conv = conversation(client, ha, a, b)
    accept(client, hb, conv["id"])
    send(client, ha, conv["id"], a["id"])
    work = claim_work(app.state.session_factory)
    assert work
    assert client.post(f"/api/agents/{b['id']}/lifecycle", headers=hb, json={"state": "disabled"}).status_code == 200
    assert finish_work(app.state.session_factory, work, REPLY)
    assert len(client.get(f"/api/conversations/{conv['id']}/messages", headers=ha).json()["items"]) == 1


@pytest.mark.parametrize("action", ["skip", "end_conversation"])
def test_non_reply_decisions_consume_no_sent_turns(product, action):
    from app.services.runtime import run_once
    client, app, _ = product
    ha, hb, a, b = pair(product)
    conv = conversation(client, ha, a, b)
    accept(client, hb, conv["id"])
    send(client, ha, conv["id"], a["id"])
    assert run_once(app.state.session_factory, FakeResponseAdapter([{"action": action, "reason": "No further contribution needed."}]))
    with app.state.session_factory() as db:
        assert db.scalar(select(func.count(Message.id)).where(Message.author_type == "agent")) == 0
        run = db.scalar(select(AgentRun))
        assert run.action == action
    if action == "end_conversation":
        assert client.get(f"/api/conversations/{conv['id']}/messages", headers=hb).status_code == 404


def test_company_policy_change_during_execution_and_rejoin_revoke_old_context(product):
    from app.services.runtime import claim_work, finish_work
    client, app, _ = product
    ha, hb, a, b = pair(product)
    conv = conversation(client, ha, a, b)
    accept(client, hb, conv["id"])
    send(client, ha, conv["id"], a["id"])
    work = claim_work(app.state.session_factory)
    assert work
    assert client.patch("/api/companies/current", headers=hb, json={"policy": {"allow_direct": False}}).status_code == 200
    assert finish_work(app.state.session_factory, work, REPLY)
    assert len(client.get(f"/api/conversations/{conv['id']}/messages", headers=ha).json()["items"]) == 1


def test_runtime_action_permissions_and_execution_budget(product):
    from app.services.runtime import run_once
    client, app, _ = product
    ha, hb, a, b = pair(product, allowed_actions=["skip"])
    conv = conversation(client, ha, a, b)
    accept(client, hb, conv["id"])
    send(client, ha, conv["id"], a["id"])
    assert run_once(app.state.session_factory, FakeResponseAdapter([REPLY]))
    with app.state.session_factory() as db:
        delivery = db.scalar(select(MessageDelivery))
        assert delivery.error == "policy_rejected"
        assert db.scalar(select(func.count(Message.id))) == 1


def test_deterministic_provider_timeout_and_invalid_schema(product):
    from app.services.runtime import run_once
    client, app, _ = product
    ha, hb, a, b = pair(product, limits={"timeout_seconds": 0.05, "max_retries": 0})
    conv = conversation(client, ha, a, b)
    accept(client, hb, conv["id"])
    send(client, ha, conv["id"], a["id"])
    import threading
    release = threading.Event()
    class SlowAdapter:
        provider_name = "fake"
        def generate(self, *args, **kwargs):
            release.wait(1)
            return REPLY
    assert run_once(app.state.session_factory, SlowAdapter())
    release.set()
    with app.state.session_factory() as db:
        assert db.scalar(select(MessageDelivery)).error == "provider_timeout"
        assert db.scalar(select(func.count(Message.id))) == 1


@pytest.mark.parametrize("restriction", ["blocked_company_ids", "excluded_topics"])
def test_new_active_restrictions_apply_to_pinned_runs(product, restriction):
    from app.services.runtime import claim_work, finish_work
    client, app, _ = product
    ha, hb, a, b = pair(product)
    conv = conversation(client, ha, a, b)
    accept(client, hb, conv["id"])
    send(client, ha, conv["id"], a["id"])
    work = claim_work(app.state.session_factory)
    cfg = {**b["config"], restriction: [a["company_id"]] if restriction == "blocked_company_ids" else ["copper"]}
    draft = client.put(f"/api/agents/{b['id']}/configuration", headers=hb, json={"config": cfg}).json()
    assert client.post(f"/api/agents/{b['id']}/lifecycle", headers=hb, json={"state": "active", "version_id": draft["config_version_id"]}).status_code == 200
    assert finish_work(app.state.session_factory, work, {**REPLY, "content": "Please review copper documentation."})
    with app.state.session_factory() as db:
        assert db.scalar(select(func.count(Message.id))) == 1


def test_pending_approval_does_not_survive_leave_and_rejoin(product):
    from app.services.runtime import run_once
    client, app, _ = product
    ha, hb, a, b = pair(product, require_approval=True)
    conv = conversation(client, ha, a, b)
    accept(client, hb, conv["id"])
    send(client, ha, conv["id"], a["id"])
    run_once(app.state.session_factory, FakeResponseAdapter([REPLY]))
    approval = client.get("/api/approvals", headers=hb).json()[0]
    client.post(f"/api/conversations/{conv['id']}/leave", headers=hb, json={"agent_id": b["id"]})
    send(client, ha, conv["id"], a["id"], key="after-leave")
    assert client.post(f"/api/conversations/{conv['id']}/invitations", headers=ha, json={"inviter_agent_id": a["id"], "recipient_agent_id": b["id"]}).status_code == 201
    accept(client, hb, conv["id"])
    assert client.get("/api/approvals", headers=hb).json() == []
    assert client.post(f"/api/approvals/{approval['id']}/respond", headers=hb, json={"accept": True}).status_code in (403, 409)


def test_approval_respects_another_workers_reserved_final_slot(product):
    from app.services.runtime import claim_work, run_once
    client, app, _ = product
    ha, hb, a, b = pair(product, require_approval=True, limits={"max_conversation_messages": 3})
    conv = conversation(client, ha, a, b)
    accept(client, hb, conv["id"])
    send(client, ha, conv["id"], a["id"])
    run_once(app.state.session_factory, FakeResponseAdapter([REPLY]))
    approval = client.get("/api/approvals", headers=hb).json()[0]
    send(client, hb, conv["id"], b["id"], key="new-input")
    assert claim_work(app.state.session_factory)
    r = client.post(f"/api/approvals/{approval['id']}/respond", headers=hb, json={"accept": True})
    assert r.status_code == 409, r.text


def test_group_capacity_and_automatic_policy_acceptance(product):
    client, app, _ = product
    ha, hb, a, b = pair(product, limits={"max_participants": 2})
    hc = register(client, "Third")
    c = agent(client, hc, "Third")
    assert client.patch("/api/companies/current", headers=hb, json={"policy": {"require_invitation_approval": False}}).status_code == 200
    conv = conversation(client, ha, a, kind="group")
    invited = client.post(f"/api/conversations/{conv['id']}/invitations", headers=ha, json={"inviter_agent_id": a["id"], "recipient_agent_id": b["id"]})
    assert invited.status_code == 201 and invited.json()["status"] == "accepted"
    proposal = client.post(f"/api/conversations/{conv['id']}/invitations", headers=hb, json={"inviter_agent_id": b["id"], "recipient_agent_id": c["id"]})
    assert proposal.status_code == 201
    assert client.post(f"/api/invitations/{proposal.json()['id']}/respond", headers=hc, json={"accept": True}).status_code == 409


def test_cooldown_daily_budget_and_concurrent_runs(product):
    from app.services.runtime import claim_work, finish_work
    client, app, _ = product
    ha, hb, a, b = pair(product, limits={"max_concurrent_runs": 1, "daily_runs": 1})
    conv = conversation(client, ha, a, b)
    accept(client, hb, conv["id"])
    send(client, ha, conv["id"], a["id"], key="one")
    send(client, ha, conv["id"], a["id"], key="two")
    now = utc_now()
    work = claim_work(app.state.session_factory, now)
    assert work and claim_work(app.state.session_factory, now) is None
    assert finish_work(app.state.session_factory, work, REPLY, now=now)
    with app.state.session_factory() as db:
        first_reply_delivery = db.scalar(select(MessageDelivery).where(MessageDelivery.agent_id == a["id"]))
        first_reply_delivery.status = "completed"
        db.commit()
    assert claim_work(app.state.session_factory, now + timedelta(seconds=2)) is None
    assert claim_work(app.state.session_factory, now + timedelta(seconds=31)) is None
    with app.state.session_factory() as db:
        waiting = db.scalar(select(MessageDelivery).where(MessageDelivery.agent_id == b["id"], MessageDelivery.status == "pending"))
        assert waiting.error == "daily_budget"


def test_discussion_topic_allowlist_is_enforced_by_backend(product):
    from app.services.runtime import run_once
    client, app, _ = product
    ha, hb, a, b = pair(product, discussion_topics=["payments"])
    conv = conversation(client, ha, a, b)
    accept(client, hb, conv["id"])
    send(client, ha, conv["id"], a["id"], text="Discuss weather forecasts.")
    assert run_once(app.state.session_factory, FakeResponseAdapter([REPLY]))
    with app.state.session_factory() as db:
        assert db.scalar(select(func.count(Message.id))) == 1
        assert db.scalar(select(MessageDelivery)).error == "policy_rejected"


def test_suspended_peer_company_cannot_receive_new_conversation_messages(product):
    from app.db.network import Company
    client, app, _ = product
    ha, hb, a, b = pair(product)
    conv = conversation(client, ha, a, b)
    accept(client, hb, conv["id"])
    with app.state.session_factory() as db:
        db.get(Company, b["company_id"]).status = "suspended"
        db.commit()
    result = client.post(f"/api/conversations/{conv['id']}/messages", headers=ha, json={"agent_id": a["id"], "content": "New message", "idempotency_key": "blocked-peer"})
    assert result.status_code == 403
