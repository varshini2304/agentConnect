"""Cookie authentication and company permissions; no client-selected identity is trusted."""
from dataclasses import dataclass
from datetime import timedelta, timezone
import hashlib
import hmac
import os
import re
import secrets
import unicodedata
from urllib.parse import urlsplit

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, Header, HTTPException, Request, Response
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.api.dependencies import get_session
from app.db.models import utc_now
from app.db.network import (
    Company, CompanyMember, CompanyRole, CompanySettings, LoginRateLimit,
    LoginSession, Permission, RolePermissionGrant, RuntimeMutex, User,
)
from app.schemas.network import CompanyPolicy
from app.services.locking import lock_runtime

PERMISSIONS = {
    "company.read": "Read company workspace", "company.update": "Edit company profile",
    "settings.manage": "Manage company settings and policies", "members.read": "Read team members",
    "members.manage": "Assign roles and revoke memberships", "invitations.manage": "Manage team invitations",
    "roles.read": "Read roles and permissions", "roles.manage": "Manage custom roles and grants",
    "agents.read": "Read owned agents", "agents.manage": "Create and configure owned agents",
    "knowledge.read": "Read company knowledge", "knowledge.manage": "Manage company knowledge",
    "posts.read": "Read authorized posts and workflow history", "posts.publish": "Publish company updates",
    "workflow.run": "Run demos and retry workflows", "discovery.read": "Discover opted-in agents",
    "conversations.read": "Read authorized conversations and decisions",
    "conversations.manage": "Manage agent conversations and invitations",
    "approvals.manage": "Resolve agent decisions requiring approval",
}
READ = {"company.read", "members.read", "roles.read", "agents.read", "knowledge.read", "posts.read", "discovery.read", "conversations.read"}
ROLE_PERMISSIONS = {
    "owner": set(PERMISSIONS), "admin": set(PERMISSIONS) - {"roles.manage"},
    "operator": READ | {"agents.manage", "knowledge.manage", "workflow.run", "conversations.manage", "approvals.manage"},
    "publisher": READ | {"posts.publish"}, "viewer": READ,
}
PASSWORDS = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=1, type=Type.ID)
# A real Argon2 hash keeps unknown-account verification on the same maintained implementation.
DUMMY_HASH = PASSWORDS.hash(secrets.token_urlsafe(32))
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@dataclass(frozen=True)
class Principal:
    user: User
    company: Company
    token_hash: str


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def production() -> bool:
    return os.getenv("AGENTCONNECT_ENV", "development").casefold() == "production"


def cookie_secure() -> bool:
    return production() or os.getenv("AGENTCONNECT_COOKIE_SECURE", "false").casefold() == "true"


def validate_configuration():
    if os.getenv("AGENTCONNECT_ENV", "development").casefold() not in {"development", "test", "production"}:
        raise RuntimeError("AGENTCONNECT_ENV must be development, test or production")
    if production():
        origins = [v.strip() for v in os.getenv("AGENTCONNECT_TRUSTED_ORIGINS", "").split(",") if v.strip()]
        if not origins:
            raise RuntimeError("Production requires explicit HTTPS trusted origins")
        for origin in origins:
            url = urlsplit(origin)
            if url.scheme != "https" or not url.hostname or url.username or url.password or url.path not in ("", "/") or url.query or url.fragment:
                raise RuntimeError("Production trusted origins must be HTTPS origins without paths or credentials")


def cookie_names():
    prefix = "__Host-" if cookie_secure() else ""
    return prefix + "agentconnect_session", prefix + "agentconnect_csrf"


def check_origin(request: Request):
    origin = request.headers.get("origin")
    allowed = {v.strip().rstrip("/") for v in os.getenv("AGENTCONNECT_TRUSTED_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173").split(",") if v.strip()}
    allowed.add(str(request.base_url).rstrip("/"))
    if origin and origin.rstrip("/") not in allowed:
        raise HTTPException(403, "Request origin is not allowed")
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "Cross-site requests are not allowed")


def csrf_guard(request: Request, session: LoginSession | None = None):
    check_origin(request)
    token = request.headers.get("x-csrf-token", "")
    cookie = request.cookies.get(cookie_names()[1], "")
    if not token or len(token) > 256 or not cookie or not hmac.compare_digest(token, cookie):
        raise HTTPException(403, "CSRF token is missing or invalid")
    if session is not None and not hmac.compare_digest(digest(token), session.csrf_token_hash):
        raise HTTPException(403, "CSRF token is missing or invalid")


def session_for(request: Request, db: Session, required=True):
    token = request.cookies.get(cookie_names()[0], "")
    session = db.get(LoginSession, digest(token)) if token and len(token) <= 256 else None
    user = db.get(User, session.user_id) if session else None
    if (session is None or session.revoked_at is not None or aware(session.expires_at) <= utc_now()
            or user is None or user.status != "active"):
        if required:
            raise HTTPException(401, "Authentication required")
        return None, None
    if request.method in UNSAFE_METHODS:
        csrf_guard(request, session)
    return session, user


def csrf_token(request: Request, response: Response, db: Session):
    check_origin(request)
    session, _ = session_for(request, db, required=False)
    token = request.cookies.get(cookie_names()[1], "")
    if not token or len(token) > 256 or (session and digest(token) != session.csrf_token_hash):
        token = secrets.token_urlsafe(32)
        if session:
            session.csrf_token_hash = digest(token)
            db.commit()
    response.set_cookie(cookie_names()[1], token, httponly=False, secure=cookie_secure(), samesite="lax", path="/", max_age=86400)
    return {"csrf_token": token}


def hash_password(password: str) -> str:
    return PASSWORDS.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    if encoded.startswith("pbkdf2_sha256$"):
        # Existing hashes are accepted once for an Argon2id upgrade on successful login.
        try:
            _, iterations, salt, expected = encoded.split("$")
            actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations)).hex()
            return hmac.compare_digest(actual, expected)
        except (TypeError, ValueError):
            return False
    try:
        return PASSWORDS.verify(encoded, password)
    except (VerificationError, InvalidHashError):
        return False


def seed_roles(db: Session, company: Company):
    for key, description in PERMISSIONS.items():
        if db.get(Permission, key) is None:
            db.add(Permission(key=key, description=description))
    db.flush()
    for slug, grants in ROLE_PERMISSIONS.items():
        role = db.scalar(select(CompanyRole).where(CompanyRole.company_id == company.id, CompanyRole.slug == slug))
        if role is None:
            role = CompanyRole(company_id=company.id, name=slug.title(), slug=slug, is_builtin=True)
            db.add(role)
            db.flush()
            db.add_all(RolePermissionGrant(role_id=role.id, permission_key=key) for key in sorted(grants))
    db.flush()


def normalized_slug(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().casefold()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")[:90]
    if not value:
        raise HTTPException(422, "Company slug must contain letters or numbers")
    return value


def create_company(db: Session, user: User, name: str, slug: str | None = None) -> Company:
    desired = normalized_slug(slug or name)
    if desired == "agentconnect-legacy":
        raise HTTPException(409, "Company slug is unavailable")
    if db.scalar(select(Company.id).where(Company.slug == desired)):
        if slug:
            raise HTTPException(409, "Company slug is unavailable")
        desired += "-" + secrets.token_hex(4)
    company = Company(name=name, slug=desired, policy=CompanyPolicy().model_dump())
    db.add(company)
    db.flush()
    seed_roles(db, company)
    owner = db.scalar(select(CompanyRole).where(CompanyRole.company_id == company.id, CompanyRole.slug == "owner"))
    db.add(CompanySettings(company_id=company.id))
    db.add(CompanyMember(company_id=company.id, user_id=user.id, role="owner", role_id=owner.id))
    db.flush()
    return company


def active_membership(db: Session, user_id, company_id):
    return db.scalar(select(CompanyMember).where(CompanyMember.user_id == user_id,
        CompanyMember.company_id == company_id, CompanyMember.status == "active").execution_options(populate_existing=True))


def permissions_for(db: Session, membership: CompanyMember) -> set[str]:
    if membership.role_id is None:
        return set()
    role = db.get(CompanyRole, membership.role_id, populate_existing=True)
    if role is None or role.company_id != membership.company_id:
        return set()
    return set(db.scalars(select(RolePermissionGrant.permission_key).where(RolePermissionGrant.role_id == role.id)))


def require_permission(db: Session, principal: Principal, key: str):
    company = db.get(Company, principal.company.id, populate_existing=True)
    user = db.get(User, principal.user.id, populate_existing=True)
    member = active_membership(db, user.id, company.id) if company and user else None
    if not member or company.status != "active" or user.status != "active":
        raise HTTPException(403, "Workspace access denied")
    if principal.token_hash:
        session = db.get(LoginSession, principal.token_hash, populate_existing=True)
        if session is None or session.revoked_at or aware(session.expires_at) <= utc_now():
            raise HTTPException(401, "Authentication required")
    if key not in permissions_for(db, member):
        raise HTTPException(403, "This role does not have the required permission")
    return member


def request_permission(request: Request) -> str | None:
    path = request.url.path.removeprefix("/api/v1").removeprefix("/api")
    read = request.method == "GET"
    if path.startswith("/user-notifications"):
        return None
    if path.startswith("/audit"):
        return "settings.manage"
    if path.startswith("/workspace/agents"):
        return "agents.read"
    if path.startswith("/governance/approvals"):
        return "approvals.manage"
    if path.startswith("/governance"):
        return "company.read" if read else "settings.manage"
    if path.startswith("/members"):
        return "members.read" if read else "members.manage"
    if path.startswith(("/roles", "/permissions")):
        return "roles.read" if read else "roles.manage"
    if path.startswith("/company-invitations"):
        return "invitations.manage"
    if path.startswith("/companies") and not read:
        return None  # Profile and policy fields have distinct checks in the service.
    if path.startswith("/agents"):
        if "/knowledge" in path:
            return "knowledge.read" if read else "knowledge.manage"
        if "/publishing-jobs" in path:
            return "posts.publish"
        return "agents.read" if read else "agents.manage"
    if path.startswith("/publications"):
        if path.endswith(("/discovery", "/discover")):
            return "discovery.read"
        return "posts.read" if read else "posts.publish"
    if path.startswith("/registry"):
        return "discovery.read"
    if path.startswith(("/conversations", "/invitations")):
        return "conversations.read" if read else "conversations.manage"
    if path.startswith("/approvals"):
        return "approvals.manage"
    if path.startswith("/publishing-jobs"):
        return "posts.read"
    if path.startswith("/legacy/agents"):
        return "agents.read" if read else "agents.manage"
    if path.startswith("/posts"):
        return "posts.read" if read else "posts.publish"
    if path.startswith("/notifications"):
        return "posts.read"
    if path.startswith(("/interactions", "/demo")):
        return "posts.read" if read else "workflow.run"
    return "company.read"


def current_principal(request: Request, db: Session = Depends(get_session), x_company_id: str | None = Header(None)) -> Principal:
    session, user = session_for(request, db)
    company_id = session.selected_company_id
    if x_company_id is not None:
        try:
            company_id = int(x_company_id)
        except ValueError:
            raise HTTPException(403, "Workspace access denied") from None
    if company_id is None:
        raise HTTPException(403, "Select an authorized workspace")
    company = db.get(Company, company_id)
    if company is None or company.status != "active" or active_membership(db, user.id, company_id) is None:
        raise HTTPException(403, "Workspace access denied")
    principal = Principal(user, company, session.token_hash)
    permission = request_permission(request)
    if permission:
        require_permission(db, principal, permission)
    db.info.update(company_id=company.id, actor_type="user", actor_id=user.id)
    if request.method in UNSAFE_METHODS:
        write_rate_limit(db, principal)
    return principal


def write_rate_limit(db, principal):
    now = utc_now()
    lock_runtime(db)
    key = digest(f"company-write:{principal.company.id}:{principal.user.id}")
    row = db.get(LoginRateLimit, key)
    if row is None:
        row = LoginRateLimit(key=key, window_started_at=now, attempts=0)
        db.add(row)
    elif aware(row.window_started_at) + timedelta(minutes=15) <= now:
        row.window_started_at, row.attempts = now, 0
    maximum = max(1, int(os.getenv("AGENTCONNECT_WRITE_ATTEMPTS", "600")))
    if row.attempts >= maximum:
        raise HTTPException(429, "Too many workspace changes. Try again later.", headers={"Retry-After": "900"})
    row.attempts += 1
    db.commit()  # Failed actions still consume a request slot, without holding the worker lock.


def settings_data(db, company):
    settings = db.get(CompanySettings, company.id)
    return {key: getattr(settings, key) if settings else (False if key == "onboarding_complete" else "") for key in ("description", "website", "industry", "onboarding_complete")}


def company_data(db, company: Company, member: CompanyMember):
    role = db.get(CompanyRole, member.role_id) if member.role_id else None
    permissions = permissions_for(db, member)
    readable = "company.read" in permissions
    return {"id": company.id, "name": company.name, "slug": company.slug, "status": company.status,
        "created_at": company.created_at, "updated_at": company.updated_at,
        "network_opt_in": company.network_opt_in, "policy": company.policy if readable else {}, "policy_version": company.policy_version,
        "role": role.slug if role else "unassigned", "role_id": member.role_id,
        "permissions": sorted(permissions), "settings": settings_data(db, company) if readable else {
            "description": "", "website": "", "industry": "", "onboarding_complete": False}}


def companies_for(db, user):
    memberships = db.scalars(select(CompanyMember).join(Company, Company.id == CompanyMember.company_id).where(
        CompanyMember.user_id == user.id, CompanyMember.status == "active", Company.status == "active").order_by(Company.id))
    return [company_data(db, db.get(Company, member.company_id), member) for member in memberships]


def identity_data(db, user, session, csrf=""):
    return {"user": {k: getattr(user, k) for k in ("id", "email", "name", "status", "created_at", "last_login_at")},
        "companies": companies_for(db, user), "selected_company_id": session.selected_company_id, "csrf_token": csrf}


def issue_session(db, user, response, company_id=None):
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    seconds = min(168, max(1, int(os.getenv("AGENTCONNECT_SESSION_HOURS", "24")))) * 3600
    if company_id is None:
        memberships = companies_for(db, user)
        company_id = memberships[0]["id"] if memberships else None
    session = LoginSession(token_hash=digest(token), user_id=user.id, selected_company_id=company_id,
        csrf_token_hash=digest(csrf), expires_at=utc_now() + timedelta(seconds=seconds))
    db.add(session)
    session_name, csrf_name = cookie_names()
    response.set_cookie(session_name, token, httponly=True, secure=cookie_secure(), samesite="lax", path="/", max_age=seconds)
    response.set_cookie(csrf_name, csrf, httponly=False, secure=cookie_secure(), samesite="lax", path="/", max_age=seconds)
    return session, csrf


def clear_session(response):
    for name in cookie_names():
        response.delete_cookie(name, secure=cookie_secure(), httponly=name.endswith("session"), samesite="lax", path="/")


def rate_limit(db, request, email, *, failed=False):
    now = utc_now()
    address = request.client.host if request.client else "unknown"
    window = timedelta(minutes=15)
    limit = max(1, int(os.getenv("AGENTCONNECT_LOGIN_ATTEMPTS", "10")))
    for label, maximum in ((address + ":" + email, limit), (address, limit * 10)):
        key = digest(label)
        row = db.get(LoginRateLimit, key)
        if row is None:
            row = LoginRateLimit(key=key, window_started_at=now, attempts=0)
            db.add(row)
            db.flush()
        if aware(row.window_started_at) + window <= now:
            row.window_started_at, row.attempts = now, 0
        if not failed and row.attempts >= maximum:
            seconds = max(1, int((aware(row.window_started_at) + window - now).total_seconds()))
            raise HTTPException(429, "Too many authentication attempts. Try again later.", headers={"Retry-After": str(seconds)})
        if failed:
            row.attempts += 1


def register(db, request, response, payload):
    previous, _ = session_for(request, db, required=False)
    csrf_guard(request, previous)
    password_hash = hash_password(payload.password)
    lock_runtime(db)
    if db.scalar(select(User.id).where(User.email == payload.email)):
        raise HTTPException(409, "An account with these details already exists")
    user = User(email=payload.email, name=payload.name, password_hash=password_hash, last_login_at=utc_now())
    db.add(user); db.flush()
    db.info.update(actor_type="user", actor_id=user.id)
    company = create_company(db, user, payload.company_name, payload.company_slug)
    db.info["company_id"] = company.id
    from app.services.audit import record_event
    record_event(db, "company.registered", "company", company.id, company_id=company.id)
    session, csrf = issue_session(db, user, response, company.id)
    db.commit()
    return identity_data(db, user, session, csrf)


def login(db, request, response, payload):
    previous, _ = session_for(request, db, required=False)
    csrf_guard(request, previous)
    lock_runtime(db)
    rate_limit(db, request, payload.email)
    rate_limit(db, request, payload.email, failed=True)
    db.commit()  # Reserve the attempt, then release the shared writer lock before Argon2 work.
    user = db.scalar(select(User).where(User.email == payload.email))
    user_id = user.id if user else None
    encoded = user.password_hash if user else DUMMY_HASH
    status = user.status if user else None
    db.rollback()
    valid = verify_password(payload.password, encoded)
    if user_id is None or status != "active" or not valid:
        from app.services.audit import record_event
        record_event(db, "auth.login", "user", None, outcome="rejected", actor_type="anonymous")
        db.commit()
        raise HTTPException(401, "Invalid email or password")
    replacement = hash_password(payload.password) if not encoded.startswith("$argon2id$") or PASSWORDS.check_needs_rehash(encoded) else None
    lock_runtime(db)
    user = db.get(User, user_id, populate_existing=True)
    if user is None or user.status != "active" or not hmac.compare_digest(user.password_hash, encoded):
        raise HTTPException(401, "Invalid email or password")
    if replacement:
        user.password_hash = replacement
    user.last_login_at = utc_now()
    previous, _ = session_for(request, db, required=False)
    if previous:
        previous.revoked_at = utc_now()
    session, csrf = issue_session(db, user, response)
    from app.services.audit import record_event
    record_event(db, "auth.login", "user", user.id, company_id=session.selected_company_id,
        actor_type="user", actor_id=user.id)
    db.commit()
    return identity_data(db, user, session, csrf)
