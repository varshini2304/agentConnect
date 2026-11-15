"""The preserved workflow shares current policy, pause and execution limits."""
import pytest
from sqlalchemy import select

from app.adapters.fake_response import FakeResponseAdapter
from app.db.models import AgentInteraction, Comment, Notification, utc_now
from app.db.network import AgentAccount, AgentVersion, Company, KnowledgeSource
from app.schemas.post import PostCreate
from app.services.agent_runner import AgentRunner
from app.services.governance import company_budget_exhausted, legacy_attempt_count
from app.services.locking import lock_runtime
from app.services.notification_service import create_selected_notifications
from app.services.post_service import create_post
from app.services.response_generation import AgentResponseService
from app.services.routing_service import evaluate_and_persist_routing
from test_legacy_tenants import RESPOND, _publish, legacy_tenants


def notification(sessions, author, title="Legacy governance", content="Review cashback payment eligibility."):
    with sessions() as db:
        post, _ = create_post(db, PostCreate(author_agent_id=author, title=title, content=content, category="merchant_promotion"))
        rows = create_selected_notifications(db, post, evaluate_and_persist_routing(db, post))
        return rows[0].id


def run(sessions, notification_id, adapter):
    with sessions() as db:
        return AgentRunner(AgentResponseService(adapter)).process_notification(db, notification_id)


def configure(sessions, ids, *, policy=None, config=None, state=None):
    with sessions() as db:
        lock_runtime(db)
        company = db.get(Company, ids[0])
        company.policy = {**company.policy, "limits": {**company.policy.get("limits", {}), "cooldown_seconds": 0}, **(policy or {})}
        account = db.get(AgentAccount, ids[3])
        if state:
            account.state = state
        if config:
            version = db.get(AgentVersion, account.active_version_id)
            version.config = {**version.config, **config}
        db.commit()


@pytest.mark.parametrize("policy,config,state", [
    ({"emergency_paused": True}, {}, None), ({"allow_replies": False}, {}, None),
    ({"allowed_actions": ["skip"]}, {}, None), ({}, {"allow_replies": False}, None),
    ({}, {"allowed_actions": ["skip"]}, None), ({}, {}, "paused"),
])
def test_legacy_governance_blocks_before_provider(legacy_tenants, policy, config, state):
    _, _, sessions, _, ids = legacy_tenants
    notification_id = notification(sessions, ids[2])
    configure(sessions, ids, policy=policy, config=config, state=state)
    adapter = FakeResponseAdapter([RESPOND])
    result = run(sessions, notification_id, adapter)
    assert result.status == "skipped"
    assert adapter.calls == []
    assert result.decision_json["attempt_history"] == []
    with sessions() as db:
        assert db.scalar(select(Comment)) is None
        assert legacy_attempt_count(db, now=utc_now(), company_id=ids[0]) == 0


@pytest.mark.parametrize("change", ["emergency", "paused", "suspended", "reply_permission"])
def test_legacy_rechecks_governance_after_provider_without_holding_lock(legacy_tenants, change):
    _, _, sessions, _, ids = legacy_tenants
    notification_id = notification(sessions, ids[2])
    with sessions() as active_session:
        class ChangePolicy(FakeResponseAdapter):
            def generate(self, *args, **kwargs):
                assert not active_session.in_transaction()
                with sessions() as changed:
                    lock_runtime(changed)
                    company = changed.get(Company, ids[0])
                    if change == "emergency":
                        company.policy = {**company.policy, "emergency_paused": True}
                    elif change == "paused":
                        changed.get(AgentAccount, ids[3]).state = "paused"
                    elif change == "suspended":
                        company.status = "suspended"
                    else:
                        company.policy = {**company.policy, "allow_replies": False}
                    changed.commit()
                return super().generate(*args, **kwargs)
        adapter = ChangePolicy([RESPOND])
        result = AgentRunner(AgentResponseService(adapter)).process_notification(active_session, notification_id)
        assert result.status == "failed"
        assert "governed conversations" in result.error.lower()
        assert "decision" not in result.decision_json
    assert len(adapter.calls) == 1
    with sessions() as db:
        assert db.scalar(select(Comment)) is None
        assert legacy_attempt_count(db, now=utc_now(), company_id=ids[0]) == 1


@pytest.mark.parametrize("restriction", ["approval", "private", "private_reason", "blocked_topic"])
def test_restricted_legacy_output_is_not_persisted(legacy_tenants, restriction):
    first, _, sessions, _, ids = legacy_tenants
    content = "Source terms state 15% off on food orders."
    notification_id = notification(sessions, ids[2], content=content)
    response = {**RESPOND, "comment": "The source terms state 15% off on food orders."}
    if restriction in {"private", "private_reason"}:
        response["comment"] = "PRIVATE_LEGACY_7326" if restriction == "private" else RESPOND["comment"]
        response["reason"] = "PRIVATE_LEGACY_7326"
        with sessions() as db:
            account = db.get(AgentAccount, ids[3])
            user_id = db.get(AgentVersion, account.active_version_id).created_by
            db.add(KnowledgeSource(company_id=ids[0], agent_id=account.id, owner_user_id=user_id,
                                   name="Private", content="PRIVATE_LEGACY_7326", visibility="private"))
            db.commit()
    elif restriction == "blocked_topic":
        configure(sessions, ids, policy={"excluded_topics": ["review eligibility"]})
        response["comment"] = "Please review eligibility before continuing."
    adapter = FakeResponseAdapter([response])
    result = run(sessions, notification_id, adapter)
    assert result.status == "failed"
    assert "governed conversations" in result.error.lower()
    assert response["comment"] not in str(result.decision_json)
    with sessions() as db:
        assert db.scalar(select(Comment)) is None


def test_legacy_creation_and_human_posts_respect_emergency_and_content_policy(legacy_tenants):
    first, _, sessions, _, ids = legacy_tenants
    configure(sessions, ids, policy={"emergency_paused": True})
    payload = {"slug": "emergency-agent", "company_name": "Draft", "role": "Payments", "industry": "payments", "description": "Payment information"}
    assert first.post("/api/v1/legacy/agents", json=payload).status_code == 403
    assert first.post("/api/v1/legacy/agents", json={**payload, "is_active": False}).status_code == 201
    assert _publish(first, ids[2]).status_code == 403
    configure(sessions, ids, policy={"emergency_paused": False, "excluded_topics": ["cashback"]})
    assert _publish(first, ids[2]).status_code == 403
    configure(sessions, ids, policy={"excluded_topics": []})
    with sessions() as db:
        account = db.get(AgentAccount, ids[2])
        user_id = db.get(AgentVersion, account.active_version_id).created_by
        db.add(KnowledgeSource(company_id=ids[0], agent_id=account.id, owner_user_id=user_id,
                               name="Private", content="Review cashback payment eligibility.", visibility="private"))
        db.commit()
    assert _publish(first, ids[2]).status_code == 422


def test_legacy_retries_consume_the_same_daily_company_budget(legacy_tenants):
    _, _, sessions, _, ids = legacy_tenants
    configure(sessions, ids, policy={"daily_execution_budget": 1})
    notification_id = notification(sessions, ids[2])
    adapter = FakeResponseAdapter([RuntimeError("provider failed"), RESPOND])
    failed = run(sessions, notification_id, adapter)
    assert failed.status == "failed"
    with sessions() as db:
        retried = AgentRunner(AgentResponseService(adapter)).retry(db, failed.id)
        assert retried.status == "skipped"
        assert len(retried.decision_json["attempt_history"]) == 1
        assert company_budget_exhausted(db, db.get(Company, ids[0]), utc_now())
    assert len(adapter.calls) == 1


def test_legacy_provider_reservation_blocks_overlapping_execution(legacy_tenants):
    _, _, sessions, _, ids = legacy_tenants
    configure(sessions, ids, config={"limits": {"max_concurrent_runs": 1, "cooldown_seconds": 0}})
    first = notification(sessions, ids[2], title="First execution")
    second = notification(sessions, ids[2], title="Second execution")
    blocked = FakeResponseAdapter([RESPOND])
    class Overlap(FakeResponseAdapter):
        def generate(self, *args, **kwargs):
            result = run(sessions, second, blocked)
            assert result.status == "skipped"
            assert result.decision_json["attempt_history"] == []
            return super().generate(*args, **kwargs)
    successful = run(sessions, first, Overlap([RESPOND]))
    assert successful.status == "responded"
    assert blocked.calls == []


def test_abandoned_legacy_reservation_recovers_and_fences_late_provider(legacy_tenants):
    from datetime import timedelta
    from app.services.agent_runner import recover_legacy_runs
    from app.services.governance import legacy_running_count
    _, _, sessions, _, ids = legacy_tenants
    configure(sessions, ids, config={"limits": {"max_concurrent_runs": 1, "cooldown_seconds": 0}})
    notification_id = notification(sessions, ids[2])
    replacement = FakeResponseAdapter([RESPOND])
    class Abandoned(FakeResponseAdapter):
        def generate(self, *args, **kwargs):
            with sessions() as db:
                lock_runtime(db)
                current = db.scalar(select(AgentInteraction).where(AgentInteraction.notification_id == notification_id))
                current.started_at = utc_now() - timedelta(hours=1)
                history = [dict(attempt) for attempt in current.decision_json["attempt_history"]]
                history[-1]["started_at"] = current.started_at.isoformat()
                current.decision_json = {"attempt_history": history}
                db.flush()
                recover_legacy_runs(db, utc_now())
                assert current.status == "failed"
                assert current.error.startswith("lease_expired:")
                assert current.decision_json["attempt_history"][-1]["status"] == "abandoned"
                assert legacy_running_count(db, ids[3]) == 0
                interaction_id = current.id
                db.commit()
            with sessions() as db:
                retry = AgentRunner(AgentResponseService(replacement)).retry(db, interaction_id)
                assert retry.status == "responded"
            return super().generate(*args, **kwargs)
    late = {**RESPOND, "comment": "This old response must never be persisted."}
    result = run(sessions, notification_id, Abandoned([late]))
    assert result.status == "responded"
    assert len(result.decision_json["attempt_history"]) == 2
    assert result.decision_json["attempt_history"][0]["status"] == "abandoned"
    with sessions() as db:
        assert [row.content for row in db.scalars(select(Comment))] == [RESPOND["comment"]]
