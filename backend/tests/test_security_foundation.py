"""Real cookie, permission and tenant boundary acceptance checks."""
from contextlib import ExitStack
from datetime import timedelta

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from app.db.models import utc_now
from app.db.network import CompanyMember, LoginSession, User
from app.db.session import make_engine
from app.main import create_app


@pytest.fixture
def foundation(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTCONNECT_DEV_INVITATIONS", "true")
    monkeypatch.setenv("AGENTCONNECT_ENABLE_FAKE", "true")
    monkeypatch.setenv("AGENTCONNECT_LOGIN_ATTEMPTS", "3")
    engine = make_engine(f"sqlite:///{tmp_path / 'foundation.db'}")
    app = create_app(db_engine=engine)
    with ExitStack() as stack:
        def client():
            return stack.enter_context(TestClient(app))
        yield client, app
    engine.dispose()


def csrf(client):
    response = client.get("/api/v1/auth/csrf")
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def write(client, method, path, payload=None, **kwargs):
    return client.request(method, "/api/v1" + path, json=payload, headers={**csrf(client), **kwargs.pop("headers", {})}, **kwargs)


def register(client, label="Alpha"):
    response = write(client, "POST", "/auth/register", {"name": label + " owner", "company_name": label, "email": label.casefold() + "@example.test", "password": "correct horse battery staple"})
    assert response.status_code == 201, response.text
    assert "token" not in response.json()
    return response.json()


def role(client, slug):
    response = client.get("/api/v1/roles")
    assert response.status_code == 200, response.text
    return next(r for r in response.json() if r["slug"] == slug)


def invite(owner, email, slug="viewer"):
    response = write(owner, "POST", "/company-invitations", {"email": email, "role_id": role(owner, slug)["id"]})
    assert response.status_code == 201, response.text
    assert response.json()["delivery"] == "development_link"
    return response.json()


def accept(client, invitation, name="Invited member"):
    response = write(client, "POST", "/company-invitations/accept", {"token": invitation["development_token"], "name": name, "password": "another secure password"})
    assert response.status_code == 200, response.text
    return response.json()


def test_cookie_argon_registration_csrf_login_and_logout(foundation):
    factory, app = foundation
    client = factory()
    data = register(client)
    cookie = client.cookies.get("agentconnect_session")
    assert cookie and len(cookie) >= 32
    assert "posts.publish" in data["companies"][0]["permissions"]
    assert data["companies"][0]["slug"] == "alpha"
    with app.state.session_factory() as db:
        user = db.scalar(select(User))
        session = db.scalar(select(LoginSession))
        assert user.password_hash.startswith("$argon2id$")
        assert session.token_hash != cookie and session.csrf_token_hash != client.cookies.get("agentconnect_csrf")
        assert user.last_login_at and user.created_at
    assert client.post("/api/v1/companies", json={"name": "No csrf"}).status_code == 403
    assert write(client, "POST", "/companies", {"name": "Evil origin"}, headers={"Origin": "https://evil.example"}).status_code == 403
    assert write(client, "POST", "/auth/logout").status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401
    result = write(client, "POST", "/auth/login", {"email": " ALPHA@example.test ", "password": "correct horse battery staple"})
    assert result.status_code == 200 and "token" not in result.json()
    session_header = next(h for h in result.headers.get_list("set-cookie") if "agentconnect_session=" in h)
    assert "HttpOnly" in session_header and "SameSite=lax" in session_header and "Path=/" in session_header
    client.cookies.set("agentconnect_session", cookie)
    assert client.get("/api/v1/auth/me").status_code == 401


def test_duplicate_normalized_email_and_generic_rate_limited_login(foundation):
    factory, _ = foundation
    first, second = factory(), factory()
    register(first)
    duplicate = write(second, "POST", "/auth/register", {"name": "Other", "company_name": "Other", "email": " ALPHA@EXAMPLE.TEST ", "password": "different secure password"})
    assert duplicate.status_code == 409
    responses = [write(second, "POST", "/auth/login", {"email": "alpha@example.test", "password": "incorrect"}) for _ in range(4)]
    assert [r.status_code for r in responses] == [401, 401, 401, 429]
    assert responses[-1].headers.get("Retry-After")
    missing = write(first, "POST", "/auth/login", {"email": "missing@example.test", "password": "incorrect"})
    assert missing.status_code == 401 and missing.json() == responses[0].json()


def test_expired_session_and_disabled_accounts_or_suspended_companies(foundation):
    factory, app = foundation
    client = factory()
    data = register(client)
    with app.state.session_factory() as db:
        db.scalar(select(LoginSession)).expires_at = utc_now() - timedelta(seconds=1)
        db.commit()
    assert client.get("/api/v1/agents").status_code == 401
    assert write(client, "POST", "/auth/login", {"email": "alpha@example.test", "password": "correct horse battery staple"}).status_code == 200
    with app.state.session_factory() as db:
        db.scalar(select(User)).status = "disabled"
        db.commit()
    assert client.get("/api/v1/agents").status_code == 401


def test_two_tenants_and_membership_revocation(foundation):
    factory, _ = foundation
    a, b, viewer = factory(), factory(), factory()
    company_a, company_b = register(a, "Alpha"), register(b, "Beta")
    payload = {"slug": "assistant", "config": {"name": "Alpha helper", "description": "Private Alpha agent", "role": "Helper", "domain": "Commerce", "purpose": "Help the company", "provider": "fake", "model": "deterministic"}}
    own = write(a, "POST", "/agents", payload)
    assert own.status_code == 201, own.text
    aid = own.json()["id"]
    assert b.get("/api/v1/agents").json() == []
    assert b.get(f"/api/v1/agents/{aid}").status_code == 404
    assert write(b, "PUT", f"/agents/{aid}/configuration", {"config": payload["config"]}).status_code == 404
    assert write(b, "DELETE", f"/agents/{aid}").status_code == 404
    assert b.get("/api/v1/agents", headers={"X-Company-ID": str(company_a["selected_company_id"])}).status_code == 403
    assert write(b, "POST", "/auth/workspace", {"company_id": company_a["selected_company_id"]}).status_code == 403
    invitation = invite(a, "viewer@example.test")
    joined = accept(viewer, invitation)
    assert joined["selected_company_id"] == company_a["selected_company_id"]
    assert viewer.get(f"/api/v1/agents/{aid}").status_code == 200
    assert write(viewer, "POST", "/agents", payload).status_code == 403
    assert write(viewer, "POST", "/publications", {"title": "Denied", "content": "Denied", "category": "news", "visibility": "company", "idempotency_key": "denied"}).status_code == 403
    assert write(viewer, "POST", "/company-invitations", {"email": "friend@example.test", "role_id": role(a, "viewer")["id"]}).status_code == 403
    member = next(m for m in a.get("/api/v1/members").json() if m["email"] == "viewer@example.test")
    assert write(a, "DELETE", f"/members/{member['id']}").status_code == 200
    assert viewer.get("/api/v1/agents").status_code in (401, 403)


def test_invitation_single_use_expiry_and_last_owner(foundation):
    factory, app = foundation
    owner, joined, other = factory(), factory(), factory()
    register(owner)
    invitation = invite(owner, "joined@example.test")
    accept(joined, invitation)
    assert write(other, "POST", "/company-invitations/accept", {"token": invitation["development_token"], "name": "Replay", "password": "another secure password"}).status_code in (400, 404, 409, 410)
    expired = invite(owner, "expired@example.test")
    from app.db.network import CompanyInvitation
    with app.state.session_factory() as db:
        db.get(CompanyInvitation, expired["id"]).expires_at = utc_now() - timedelta(seconds=1)
        db.commit()
    assert write(other, "POST", "/company-invitations/accept", {"token": expired["development_token"], "name": "Expired", "password": "another secure password"}).status_code == 410
    current_owner = next(m for m in owner.get("/api/v1/members").json() if m["role"] == "owner")
    assert write(owner, "DELETE", f"/members/{current_owner['id']}").status_code == 409
    assert write(owner, "PATCH", f"/members/{current_owner['id']}", {"role_id": role(owner, "viewer")["id"]}).status_code == 409


def test_custom_company_roles_and_no_foreign_grants(foundation):
    factory, app = foundation
    a, b, member = factory(), factory(), factory()
    register(a, "Alpha"); register(b, "Beta")
    custom = write(a, "POST", "/roles", {"name": "Audit team permissions", "permissions": ["company.read", "agents.read", "posts.read", "roles.read", "members.read"]})
    assert custom.status_code == 201, custom.text
    assert write(b, "PUT", f"/roles/{custom.json()['id']}", {"name": "Stolen", "permissions": ["roles.manage"]}).status_code == 404
    assert write(a, "PUT", f"/roles/{role(a, 'owner')['id']}", {"name": "Owner", "permissions": []}).status_code in (403, 409)
    invitation = write(a, "POST", "/company-invitations", {"email": "auditor@example.test", "role_id": custom.json()["id"]}).json()
    accept(member, invitation)
    with app.state.session_factory() as db:
        membership = db.scalar(select(CompanyMember).where(CompanyMember.role_id == custom.json()["id"]))
        assert len(membership.role) <= 20  # Existing compatibility column is VARCHAR(20).
    assert member.get("/api/v1/agents").status_code == 200
    assert write(member, "POST", "/companies/current/settings", {}).status_code in (403, 405)
    assert write(member, "PUT", "/companies/current/settings", {"description": "Denied"}).status_code == 403
    assert write(member, "PATCH", "/companies/current", {}).status_code == 422


def test_invitation_delivery_is_explicitly_development_only(foundation, monkeypatch):
    factory, _ = foundation
    client = factory(); register(client)
    rid = role(client, "viewer")["id"]
    monkeypatch.setenv("AGENTCONNECT_DEV_INVITATIONS", "false")
    response = write(client, "POST", "/company-invitations", {"email": "one@example.test", "role_id": rid})
    assert response.status_code == 503 and "sent" not in response.text.casefold()


def test_cookie_registration_requires_pre_auth_csrf(foundation):
    factory, _ = foundation
    client = factory()
    response = client.post("/api/v1/auth/register", json={"name": "Owner", "company_name": "Company", "email": "owner@example.test", "password": "correct horse battery staple"})
    assert response.status_code == 403


def test_suspended_company_and_workspace_selection_are_revalidated(foundation):
    from app.db.network import Company
    factory, app = foundation
    client = factory(); identity = register(client)
    first = identity["selected_company_id"]
    second = write(client, "POST", "/companies", {"name": "Second workspace"}).json()["id"]
    assert write(client, "POST", "/auth/workspace", {"company_id": second}).status_code == 200
    assert client.get("/api/v1/auth/me").json()["selected_company_id"] == second
    with app.state.session_factory() as db:
        db.get(Company, second).status = "suspended"
        db.commit()
    assert client.get("/api/v1/agents").status_code == 403
    assert write(client, "POST", "/auth/workspace", {"company_id": second}).status_code == 403
    assert write(client, "POST", "/auth/workspace", {"company_id": first}).status_code == 200
    assert client.get("/api/v1/agents").status_code == 200


def test_admin_cannot_grant_or_remove_company_ownership(foundation):
    factory, _ = foundation
    owner, admin = factory(), factory()
    register(owner)
    accept(admin, invite(owner, "admin@example.test", "admin"))
    owner_role = role(owner, "owner")["id"]
    owner_member = next(m for m in owner.get("/api/v1/members").json() if m["role"] == "owner")
    assert write(admin, "POST", "/company-invitations", {"email": "takeover@example.test", "role_id": owner_role}).status_code == 403
    assert write(admin, "DELETE", f"/members/{owner_member['id']}").status_code == 403
    assert write(admin, "POST", "/roles", {"name": "Escalation", "permissions": ["roles.manage"]}).status_code == 403


@pytest.mark.parametrize("slug,can_publish,can_manage", [("publisher", True, False), ("operator", False, True)])
def test_publisher_and_operator_have_distinct_backend_grants(foundation, slug, can_publish, can_manage):
    factory, _ = foundation
    owner, member = factory(), factory(); register(owner)
    accept(member, invite(owner, slug + "@example.test", slug))
    publication = write(member, "POST", "/publications", {"title": "Company news", "content": "Internal update", "category": "news", "visibility": "company", "idempotency_key": "matrix"})
    assert publication.status_code == (201 if can_publish else 403)
    payload = {"slug": "helper", "config": {"name": "Helper", "description": "Company helper", "role": "Helper", "domain": "Commerce", "purpose": "Assist the company", "provider": "fake", "model": "deterministic"}}
    created = write(member, "POST", "/agents", payload)
    assert created.status_code == (201 if can_manage else 403)


def test_existing_invited_user_requires_matching_signed_in_account(foundation):
    factory, app = foundation
    a, b, stranger, anonymous = factory(), factory(), factory(), factory()
    alpha, beta = register(a, "Alpha"), register(b, "Beta")
    register(stranger, "Stranger")
    invitation = invite(a, "beta@example.test", "publisher")
    assert write(anonymous, "POST", "/company-invitations/accept", {"token": invitation["development_token"]}).status_code == 401
    assert write(stranger, "POST", "/company-invitations/accept", {"token": invitation["development_token"]}).status_code == 403
    joined = write(b, "POST", "/company-invitations/accept", {"token": invitation["development_token"]})
    assert joined.status_code == 200, joined.text
    assert joined.json()["selected_company_id"] == alpha["selected_company_id"]
    assert {company["id"] for company in joined.json()["companies"]} == {alpha["selected_company_id"], beta["selected_company_id"]}
    from app.db.network import CompanyInvitation
    with app.state.session_factory() as db:
        row = db.get(CompanyInvitation, invitation["id"])
        assert row.token_hash != invitation["development_token"] and row.accepted_at and row.status == "accepted"


def test_secure_production_cookies_and_no_development_invitation_bypass(foundation, monkeypatch):
    factory, app = foundation
    monkeypatch.setenv("AGENTCONNECT_ENV", "production")
    monkeypatch.setenv("AGENTCONNECT_TRUSTED_ORIGINS", "https://testserver")
    with TestClient(app, base_url="https://testserver") as client:
        response = write(client, "POST", "/auth/register", {"name": "Owner", "company_name": "Production", "email": "production@example.test", "password": "correct horse battery staple"})
        assert response.status_code == 201
        cookie = next(h for h in response.headers.get_list("set-cookie") if "__Host-agentconnect_session=" in h)
        assert "Secure" in cookie and "HttpOnly" in cookie and "Domain=" not in cookie
        rid = role(client, "viewer")["id"]
        assert write(client, "POST", "/company-invitations", {"email": "test@example.test", "role_id": rid}).status_code == 503


def test_csrf_is_bound_to_session_and_bearer_tokens_are_rejected(foundation):
    factory, _ = foundation
    a, b, anonymous = factory(), factory(), factory()
    register(a, "Alpha"); register(b, "Beta")
    csrf_b = b.cookies.get("agentconnect_csrf")
    assert a.post("/api/v1/companies", json={"name": "Wrong csrf"}, headers={"Cookie": "agentconnect_session=" + a.cookies.get("agentconnect_session") + "; agentconnect_csrf=" + csrf_b, "X-CSRF-Token": csrf_b}).status_code == 403
    assert anonymous.get("/api/v1/agents", headers={"Authorization": "Bearer " + a.cookies.get("agentconnect_session")}).status_code == 401


def test_legacy_password_is_upgraded_to_argon2id_on_successful_login(foundation):
    import hashlib
    factory, app = foundation
    client = factory(); identity = register(client)
    salt = "1234abcd"
    value = hashlib.pbkdf2_hmac("sha256", b"correct horse battery staple", bytes.fromhex(salt), 600000).hex()
    with app.state.session_factory() as db:
        db.get(User, identity["user"]["id"]).password_hash = f"pbkdf2_sha256$600000${salt}${value}"
        db.commit()
    result = write(client, "POST", "/auth/login", {"email": "alpha@example.test", "password": "correct horse battery staple"})
    assert result.status_code == 200
    with app.state.session_factory() as db:
        assert db.get(User, identity["user"]["id"]).password_hash.startswith("$argon2id$")


def test_legacy_workspace_slug_is_reserved_for_reviewed_migrations(foundation):
    factory, _ = foundation
    client = factory(); register(client)
    assert write(client, "POST", "/companies", {"name": "Claim legacy data", "slug": "agentconnect-legacy"}).status_code == 409
    assert write(client, "PATCH", "/companies/current", {"slug": "agentconnect-legacy"}).status_code == 409


@pytest.mark.parametrize("action", ["register", "login"])
def test_authentication_posts_validate_an_existing_sessions_csrf_hash(foundation, action):
    factory, _ = foundation
    a, b = factory(), factory(); register(a, "Alpha"); register(b, "Beta")
    wrong = b.cookies.get("agentconnect_csrf")
    payload = {"email": "new@example.test", "password": "correct horse battery staple", "name": "New", "company_name": "New"} if action == "register" else {"email": "alpha@example.test", "password": "incorrect"}
    response = a.post("/api/v1/auth/" + action, json=payload, headers={"Cookie": "agentconnect_session=" + a.cookies.get("agentconnect_session") + "; agentconnect_csrf=" + wrong, "X-CSRF-Token": wrong})
    assert response.status_code == 403


def test_production_startup_requires_explicit_https_origins(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTCONNECT_ENV", "production")
    monkeypatch.delenv("AGENTCONNECT_TRUSTED_ORIGINS", raising=False)
    engine = make_engine(f"sqlite:///{tmp_path / 'production.db'}")
    app = create_app(db_engine=engine)
    with pytest.raises(RuntimeError, match="origin"):
        with TestClient(app):
            pass
    engine.dispose()


def test_password_verification_does_not_hold_runtime_write_lock(foundation, monkeypatch):
    from sqlalchemy import update
    from app.db.network import RuntimeMutex
    from app.services import security
    factory, app = foundation
    client = factory(); register(client)
    original = security.verify_password
    def verify_without_blocking(password, encoded):
        with app.state.session_factory() as independent:
            independent.execute(update(RuntimeMutex).where(RuntimeMutex.id == 1).values(value=RuntimeMutex.value + 1))
            independent.commit()
        return original(password, encoded)
    monkeypatch.setattr(security, "verify_password", verify_without_blocking)
    response = write(client, "POST", "/auth/login", {"email": "alpha@example.test", "password": "correct horse battery staple"})
    assert response.status_code == 200


def test_invitee_password_hashing_does_not_hold_runtime_write_lock(foundation, monkeypatch):
    from sqlalchemy import update
    from app.db.network import RuntimeMutex
    from app.services import security
    factory, app = foundation
    owner, member = factory(), factory(); register(owner)
    invitation = invite(owner, "join@example.test")
    original = security.hash_password
    def hash_without_blocking(password):
        with app.state.session_factory() as independent:
            independent.execute(update(RuntimeMutex).where(RuntimeMutex.id == 1).values(value=RuntimeMutex.value + 1))
            independent.commit()
        return original(password)
    monkeypatch.setattr(security, "hash_password", hash_without_blocking)
    assert accept(member, invitation)["user"]["email"] == "join@example.test"


def test_parallel_owner_demotions_preserve_one_active_owner(foundation):
    from concurrent.futures import ThreadPoolExecutor
    factory, _ = foundation
    a, b = factory(), factory(); register(a)
    accept(b, invite(a, "second-owner@example.test", "owner"))
    viewer_role = role(a, "viewer")["id"]
    members = a.get("/api/v1/members").json()
    member_a = next(m for m in members if m["email"] == "alpha@example.test")
    member_b = next(m for m in members if m["email"] == "second-owner@example.test")
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(write, client, "PATCH", f"/members/{member['id']}", {"role_id": viewer_role}) for client, member in ((a, member_a), (b, member_b))]
        codes = sorted(job.result().status_code for job in jobs)
    assert codes == [200, 409]
    assert sum(m["role"] == "owner" and m["status"] == "active" for m in a.get("/api/v1/members").json()) == 1


@pytest.mark.parametrize("change", ["revoke", "demote"])
def test_pending_invitation_cannot_restore_an_issuers_revoked_permissions(foundation, change):
    factory, _ = foundation
    owner, admin, newcomer = factory(), factory(), factory(); register(owner)
    accept(admin, invite(owner, "admin@example.test", "admin"))
    invitation = invite(admin, "new-admin@example.test", "admin")
    membership = next(m for m in owner.get("/api/v1/members").json() if m["email"] == "admin@example.test")
    if change == "revoke":
        response = write(owner, "DELETE", f"/members/{membership['id']}")
    else:
        response = write(owner, "PATCH", f"/members/{membership['id']}", {"role_id": role(owner, "viewer")["id"]})
    assert response.status_code == 200
    result = write(newcomer, "POST", "/company-invitations/accept", {"token": invitation["development_token"], "name": "New admin", "password": "another secure password"})
    assert result.status_code == 409


def test_narrow_custom_grant_does_not_leak_company_settings_through_session(foundation):
    factory, _ = foundation
    owner, member = factory(), factory(); register(owner)
    assert write(owner, "PUT", "/companies/current/settings", {"description": "Restricted governance note"}).status_code == 200
    assert write(owner, "PATCH", "/companies/current", {"policy": {"approval_topics": ["Restricted approval phrase"]}}).status_code == 200
    custom = write(owner, "POST", "/roles", {"name": "Post reader", "permissions": ["posts.read"]}).json()
    invitation = write(owner, "POST", "/company-invitations", {"email": "reader@example.test", "role_id": custom["id"]}).json()
    joined = accept(member, invitation)
    assert joined["companies"][0]["name"] == "Alpha"
    for path in ("/api/v1/auth/me", "/api/v1/companies"):
        result = member.get(path)
        assert "Restricted governance note" not in result.text and "Restricted approval phrase" not in result.text
    assert member.get("/api/v1/posts").status_code == 200
    assert member.get("/api/v1/companies/current").status_code == 403
    assert member.get("/api/v1/agents").status_code == 403
