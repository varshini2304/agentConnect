"""Independent Phase 3 boundary regressions; fake providers and isolated databases only."""
from datetime import timedelta
import pytest
from sqlalchemy import select

from auth_helpers import cookie_headers
from test_conversations_runtime import product, pair, conversation, accept
from test_governance import policy, pending_reply
from app.db.models import utc_now
from app.db.network import ApprovalRequest, Message, Publication, RunApproval
from app.services.policy import evaluate_action


def test_preexisting_draft_does_not_bypass_new_approval_requirement(product, monkeypatch):
    monkeypatch.setenv("AGENTCONNECT_DEV_INVITATIONS", "true")
    client, app, _ = product
    ha, hb, a, b = pair(product)
    created = client.post("/api/publications", headers=ha, json={
        "title": "Operational documentation", "content": "A general documentation update.",
        "category": "payments", "visibility": "network", "status": "draft", "idempotency_key": "review-old-draft",
    })
    assert created.status_code == 201, created.text
    assert created.json()["approval_request_id"] is None
    policy(client, ha, require_publish_approval=True)
    roles = client.get("/api/roles", headers=ha).json()
    publisher = next(row for row in roles if row["slug"] == "publisher")
    invited = client.post("/api/company-invitations", headers=ha, json={"email": "phonepe@example.test", "role_id": publisher["id"]})
    assert invited.status_code == 201, invited.text
    joined = client.post("/api/company-invitations/accept", headers=hb, json={"token": invited.json()["development_token"]})
    assert joined.status_code == 200, joined.text
    hp = cookie_headers(client, a["company_id"])
    assert "approvals.manage" not in next(c for c in joined.json()["companies"] if c["id"] == a["company_id"])["permissions"]
    response = client.post(f"/api/publications/{created.json()['id']}/publish", headers=hp)
    with app.state.session_factory() as db:
        assert db.get(Publication, created.json()["id"]).status == "draft", response.text


def test_legacy_approval_rejection_cannot_read_removed_conversation_context(product):
    client, _, _ = product
    ha, hb, a, b, conv, approval = pending_reply(product)
    legacy_id = approval["source_id"]
    left = client.post(f"/api/conversations/{conv['id']}/leave", headers=hb, json={"agent_id": b["id"]})
    assert left.status_code == 200, left.text
    assert client.get(f"/api/governance/approvals/{approval['id']}", headers=hb).status_code == 404
    result = client.post(f"/api/approvals/{legacy_id}/respond", headers=hb, json={"accept": False})
    assert result.status_code in (403, 404, 409), result.text


@pytest.mark.parametrize("content,restricted", [
    ("We agree to offer 20% cashback today.", "promotional_offer"),
    ("Please transfer funds; we guarantee a 12% return.", "financial_claim"),
])
def test_secondary_classification_cannot_bypass_a_restricted_category(content, restricted):
    result = evaluate_action(action="message.reply", content=content,
        company_policy={"restricted_categories": [restricted]}, configs=[{}])
    assert result.disposition == "reject", result


def test_manual_restricted_message_cannot_bypass_human_review(product):
    client, app, _ = product
    ha, hb, a, b = pair(product)
    conv = conversation(client, ha, a, b)
    accept(client, hb, conv["id"])
    response = client.post(f"/api/conversations/{conv['id']}/messages", headers=ha, json={
        "agent_id": a["id"], "content": "Get 20% cashback today.", "idempotency_key": "manual-policy-bypass",
    })
    assert response.status_code == 403, response.text


def test_resolved_legacy_approval_cannot_be_resurrected_without_unified_record(product):
    client, app, _ = product
    ha, hb, a, b, conv, approval = pending_reply(product)
    rejected = client.post(f"/api/governance/approvals/{approval['id']}/review", headers=hb, json={"approve": False})
    assert rejected.status_code == 200 and rejected.json()["status"] == "rejected"
    # Phase 3 only migrates pending legacy approvals; model an old resolved row.
    with app.state.session_factory.begin() as db:
        db.delete(db.get(ApprovalRequest, approval["id"]))
    response = client.post(f"/api/approvals/{approval['source_id']}/respond", headers=hb, json={"accept": True})
    with app.state.session_factory() as db:
        assert db.get(RunApproval, approval["source_id"]).status == "rejected", response.text
        assert len(list(db.scalars(select(Message).where(Message.conversation_id == conv["id"])))) == 1


def test_stale_expiry_read_cannot_overwrite_an_executed_approval(product):
    from app.services.approvals import aware, expire
    client, app, _ = product
    ha, hb, a, b, conv, approval = pending_reply(product)
    with app.state.session_factory.begin() as db:
        db.get(ApprovalRequest, approval["id"]).expires_at = utc_now() + timedelta(seconds=3)
    with app.state.session_factory() as stale:
        old = stale.get(ApprovalRequest, approval["id"])
        deadline = aware(old.expires_at)
        executed = client.post(f"/api/governance/approvals/{approval['id']}/review", headers=hb, json={"approve": True})
        assert executed.status_code == 200 and executed.json()["status"] == "executed", executed.text
        # An inbox GET loaded pending before review, then resumes past the deadline.
        expire(stale, old, now=deadline + timedelta(seconds=1))
        stale.commit()
    with app.state.session_factory() as db:
        assert db.get(ApprovalRequest, approval["id"]).status == "executed"
        assert db.get(RunApproval, approval["source_id"]).status == "accepted"
