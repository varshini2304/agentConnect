"""Reporting reads measured tenant data and notifications never grant resource access."""
import json
from datetime import timedelta

from sqlalchemy import func, select

from app.db.models import utc_now
from app.db.network import AuditEvent, CompanyMember, CompanyRole, UserNotification
from test_conversations_runtime import accept, conversation, pair, product, register, send


def test_dashboard_analytics_and_audit_are_tenant_scoped(product):
    client, app, _ = product
    ha, hb, a, b = pair(product)
    conv = conversation(client, ha, a, b)
    accept(client, hb, conv["id"])
    send(client, ha, conv["id"], a["id"], "secret-message-content")
    dashboard = client.get("/api/company/dashboard", headers=hb)
    assert dashboard.status_code == 200, dashboard.text
    assert dashboard.json()["agents"] == {"total": 1, "active": 1, "paused": 0}
    assert dashboard.json()["active_conversations"] == 1
    analytics = client.get("/api/company/analytics?days=7", headers=hb).json()
    assert analytics["totals"]["messages"] == 1
    assert len(analytics["daily"]) == 7
    assert "quality" not in analytics and "cost" not in analytics
    audits = client.get("/api/audit", headers=ha).json()
    assert audits["total"] > 0
    assert all(row["company_id"] == a["company_id"] for row in audits["items"])
    assert "secret-message-content" not in json.dumps(audits)
    other = register(client, "Unrelated")
    assert client.get("/api/company/dashboard", headers=other).json()["active_conversations"] == 0
    assert client.get(f"/api/workspace/agents/{a['id']}/activity", headers=other).status_code == 404
    assert client.get("/api/company/analytics?days=366", headers=ha).status_code == 422


def test_notifications_dedupe_read_and_recheck_conversation_access(product):
    client, app, _ = product
    ha, hb, a, b = pair(product)
    conv = conversation(client, ha, a, b)
    accept(client, hb, conv["id"])
    msg = send(client, ha, conv["id"], a["id"])
    send(client, ha, conv["id"], a["id"])
    notifications = client.get("/api/user-notifications?category=message", headers=hb).json()
    assert notifications["total"] == 1
    item = notifications["items"][0]
    assert item["resource_id"] == str(msg["id"])
    assert client.post(f"/api/user-notifications/{item['id']}/read", headers=ha).status_code == 404
    assert client.post(f"/api/user-notifications/{item['id']}/read", headers=hb).status_code == 200
    assert client.get("/api/user-notifications?category=message&unread=true", headers=hb).json()["total"] == 0
    assert client.post(f"/api/conversations/{conv['id']}/leave", headers=hb, json={"agent_id": b["id"]}).status_code == 200
    assert client.get("/api/user-notifications?category=message", headers=hb).json()["total"] == 0
    assert client.post(f"/api/user-notifications/{item['id']}/read", headers=hb).status_code == 404
    activity = client.get(f"/api/workspace/agents/{b['id']}/activity", headers=hb).json()
    assert activity["messages"] == [] and activity["conversations"] == []


def test_audit_is_transactional_and_drops_sensitive_metadata(product):
    from app.services.audit import record_event
    client, app, _ = product
    headers = register(client, "Audit")
    company_id = int(headers["X-Company-ID"])
    with app.state.session_factory() as db:
        record_event(db, "test.safe", "company", company_id, company_id=company_id,
                     metadata={"content": "secret", "config": {"token": "secret"}, "status": "active"})
        db.commit()
        row = db.scalar(select(AuditEvent).where(AuditEvent.event_type == "test.safe"))
        assert row.metadata_json == {"status": "active"}
        record_event(db, "test.rollback", "company", company_id, company_id=company_id)
        db.flush()
        db.rollback()
        assert db.scalar(select(func.count(AuditEvent.id)).where(AuditEvent.event_type == "test.rollback")) == 0
        member = db.scalar(select(CompanyMember).where(CompanyMember.company_id == company_id))
        member.status = "revoked"
        db.commit()
    assert client.get("/api/user-notifications", headers=headers).status_code == 403
    assert client.get("/api/audit", headers=headers).status_code == 403


def test_measured_runs_retries_and_company_budget(product, monkeypatch):
    from app.services.runtime import claim_work, finish_work
    client, app, _ = product
    ha, hb, a, b = pair(product)
    conv = conversation(client, ha, a, b)
    accept(client, hb, conv["id"])
    send(client, ha, conv["id"], a["id"])
    now = utc_now()
    first = claim_work(app.state.session_factory, now)
    assert first is not None
    assert finish_work(app.state.session_factory, first, error="provider_timeout", now=now)
    second = claim_work(app.state.session_factory, now + timedelta(seconds=3))
    assert second is not None
    assert finish_work(app.state.session_factory, second,
        {"action": "skip", "reason": "Nothing useful to add", "content": None}, now=now + timedelta(seconds=3))
    monkeypatch.setenv("AGENTCONNECT_DAILY_COMPANY_BUDGET", "9")
    report = client.get("/api/company/analytics?days=7", headers=hb).json()
    assert report["totals"]["runs"] == 2
    assert report["totals"]["retries"] == 1
    assert report["totals"]["skips"] == 1
    assert report["usage"] == {"daily_runs": 2, "daily_budget": 9, "remaining": 7}
    assert report["agents"][0]["runs"] == 2
    activity = client.get(f"/api/workspace/agents/{b['id']}/activity", headers=hb).json()
    assert len(activity["runs"]) == 1 and len(activity["runs"][0]["attempts"]) == 2


def test_approval_notifications_only_for_reviewers_and_no_sensitive_payload(product):
    from app.db.network import ApprovalRequest
    client, app, _ = product
    ha, hb, a, b = pair(product)
    owner_id = client.get("/api/auth/me", headers=ha).json()["user"]["id"]
    other_user_id = client.get("/api/auth/me", headers=hb).json()["user"]["id"]
    publication = client.post("/api/publications", headers=ha, json={"title": "Private draft", "content": "Draft content", "category": "payments",
        "visibility": "company", "status": "draft", "idempotency_key": "approval-source"})
    assert publication.status_code == 201
    with app.state.session_factory() as db:
        viewer_role = db.scalar(select(CompanyRole).where(CompanyRole.company_id == a["company_id"], CompanyRole.slug == "viewer"))
        db.add(CompanyMember(company_id=a["company_id"], user_id=other_user_id, role_id=viewer_role.id, role="viewer", status="active"))
        approval = ApprovalRequest(company_id=a["company_id"], agent_id=a["id"], requesting_user_id=owner_id,
            action_type="publication.publish", source_type="publication", source_id=publication.json()["id"],
            proposed_content="secret-proposed-content", reason="secret-review-reason", category="financial_claim",
            triggered_policy=["platform.category.financial_claim"], config_version_id=a["active_version_id"],
            policy_version=1, expires_at=utc_now() + timedelta(days=1))
        db.add(approval)
        db.commit()
        recipients = list(db.scalars(select(UserNotification.recipient_user_id).where(UserNotification.category == "approval_requested")))
        assert recipients == [owner_id]
        audit = json.dumps([row.metadata_json for row in db.scalars(select(AuditEvent))])
        assert "secret-proposed-content" not in audit and "secret-review-reason" not in audit
        approval.status = "rejected"
        db.commit()
        assert db.scalar(select(func.count(UserNotification.id)).where(UserNotification.category == "approval_decision")) == 1
    viewer = {**hb, "X-Company-ID": str(a["company_id"])}
    assert client.get("/api/user-notifications?category=approval_requested", headers=viewer).json()["total"] == 0
    assert client.get("/api/audit", headers=viewer).status_code == 403
    assert client.get("/api/user-notifications?category=approval_requested", headers=ha).json()["total"] == 1


def test_history_floor_hides_earlier_notifications_and_activity(product):
    from app.db.network import ConversationMember
    client, app, _ = product
    ha, hb, a, b = pair(product)
    conv = conversation(client, ha, a, b)
    accept(client, hb, conv["id"])
    first = send(client, ha, conv["id"], a["id"], key="first")
    second = send(client, ha, conv["id"], a["id"], key="second")
    with app.state.session_factory() as db:
        member = db.scalar(select(ConversationMember).where(ConversationMember.conversation_id == conv["id"], ConversationMember.agent_id == b["id"]))
        member.history_from_seq = second["sequence"]
        db.commit()
    inbox = client.get("/api/user-notifications?category=message", headers=hb).json()
    assert [item["resource_id"] for item in inbox["items"]] == [str(second["id"])]
    activity = client.get(f"/api/workspace/agents/{b['id']}/activity", headers=hb).json()
    assert [message["id"] for message in activity["messages"]] == [second["id"]]
    assert first["id"] != second["id"]
    assert client.post("/api/user-notifications/read-all", headers=hb).status_code == 200
    with app.state.session_factory() as db:
        hidden = db.scalar(select(UserNotification).where(UserNotification.resource_type == "message", UserNotification.resource_id == str(first["id"]),
            UserNotification.company_id == b["company_id"]))
        assert hidden.read_at is None


def test_failure_notifications_and_shared_audit_hide_foreign_actor_and_content(product):
    from app.services.runtime import claim_work, finish_work
    client, app, _ = product
    ha, hb, a, b = pair(product)
    conv = conversation(client, ha, a, b)
    accept(client, hb, conv["id"])
    send(client, ha, conv["id"], a["id"], text="confidential-content-never-copy-to-audit")
    owner_event = client.get("/api/audit?event_type=message.created", headers=ha).json()["items"][0]
    peer_event = client.get("/api/audit?event_type=message.created", headers=hb).json()["items"][0]
    assert owner_event["actor_type"] == "user" and owner_event["actor_id"] is not None
    assert peer_event["actor_type"] == "system" and peer_event["actor_id"] is None
    work = claim_work(app.state.session_factory)
    assert work is not None
    assert finish_work(app.state.session_factory, work, error="missing_api_key")
    dashboard = client.get("/api/company/dashboard", headers=hb).json()
    assert dashboard["failed_executions"] == 1
    for category in ("run_failure", "delivery_failure"):
        inbox = client.get(f"/api/user-notifications?category={category}", headers=hb).json()
        assert inbox["total"] == 1
        assert inbox["items"][0]["agent_id"] == b["id"]
        assert "missing_api_key" not in json.dumps(inbox)
    events = client.get("/api/audit", headers=hb).json()
    assert "confidential-content-never-copy-to-audit" not in json.dumps(events)
    assert "missing_api_key" not in json.dumps(events)


def test_team_invitation_governance_notifications_contain_no_email_or_token(product, monkeypatch):
    monkeypatch.setenv("AGENTCONNECT_DEV_INVITATIONS", "true")
    client, _, _ = product
    headers = register(client, "Team")
    viewer = next(role for role in client.get("/api/roles", headers=headers).json() if role["slug"] == "viewer")
    created = client.post("/api/company-invitations", headers=headers, json={"email": "private-invitee@example.test", "role_id": viewer["id"]})
    assert created.status_code == 201, created.text
    assert client.post(f"/api/company-invitations/{created.json()['id']}/revoke", headers=headers).status_code == 200
    inbox = client.get("/api/user-notifications?category=governance&search=Team%20invitation", headers=headers).json()
    assert inbox["total"] == 2
    encoded = json.dumps(inbox)
    assert "private-invitee" not in encoded and created.json()["development_token"] not in encoded
