"""Transactional company governance; membership and role changes never cross tenants."""
from datetime import timedelta
import os
import secrets

from fastapi import HTTPException
from sqlalchemy import delete, func, select

from app.db.models import utc_now
from app.db.network import Company, CompanyInvitation, CompanyMember, CompanyRole, CompanySettings, RolePermissionGrant, User
from app.schemas.network import CompanyPolicy
from app.services.locking import lock_runtime
from app.services import security


def owned_company(db, principal, company_id):
    security.require_permission(db, principal, "company.read")
    company = db.get(Company, company_id)
    if company is None or security.active_membership(db, principal.user.id, company_id) is None:
        raise HTTPException(404, "Company not found")
    return company


def actor_in(db, principal, company):
    return security.Principal(principal.user, company, principal.token_hash)


def update_company(db, principal, company, payload):
    lock_runtime(db)
    actor = actor_in(db, principal, company)
    values = payload.model_dump(exclude_unset=True)
    if values.keys() & {"name", "slug"}:
        security.require_permission(db, actor, "company.update")
    if values.keys() & {"network_opt_in", "policy"}:
        security.require_permission(db, actor, "settings.manage")
    if "slug" in values:
        slug = security.normalized_slug(values["slug"])
        if slug == "agentconnect-legacy":
            raise HTTPException(409, "Company slug is unavailable")
        duplicate = db.scalar(select(Company.id).where(Company.slug == slug, Company.id != company.id))
        if duplicate:
            raise HTTPException(409, "Company slug is unavailable")
        company.slug = slug
    if "name" in values:
        company.name = values["name"]
    if "network_opt_in" in values:
        company.network_opt_in = values["network_opt_in"]
    if "policy" in values:
        changes = payload.policy.model_dump(exclude_unset=True)
        policy = {**company.policy, **changes}
        if "limits" in changes:
            policy["limits"] = {**company.policy.get("limits", {}), **changes["limits"]}
        company.policy = CompanyPolicy.model_validate(policy).model_dump()
    if values.keys() & {"network_opt_in", "policy"}:
        company.policy_version += 1
    company.updated_at = utc_now()


def update_settings(db, principal, payload):
    lock_runtime(db)
    security.require_permission(db, principal, "settings.manage")
    row = db.get(CompanySettings, principal.company.id)
    if row is None:
        row = CompanySettings(company_id=principal.company.id)
        db.add(row)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    db.flush()


def member_data(db, member):
    user = db.get(User, member.user_id)
    role = db.get(CompanyRole, member.role_id) if member.role_id else None
    return {"id": member.id, "user_id": member.user_id, "email": user.email, "name": user.name,
        "status": member.status, "role": role.slug if role else "unassigned", "role_id": member.role_id, "created_at": member.created_at}


def list_members(db, principal):
    security.require_permission(db, principal, "members.read")
    return [member_data(db, row) for row in db.scalars(select(CompanyMember).where(CompanyMember.company_id == principal.company.id).order_by(CompanyMember.id))]


def owned_role(db, principal, role_id):
    role = db.get(CompanyRole, role_id)
    if role is None or role.company_id != principal.company.id:
        raise HTTPException(404, "Role not found")
    return role


def role_data(db, role):
    return {"id": role.id, "name": role.name, "slug": role.slug, "is_builtin": role.is_builtin,
        "permissions": sorted(db.scalars(select(RolePermissionGrant.permission_key).where(RolePermissionGrant.role_id == role.id)))}


def list_roles(db, principal):
    security.require_permission(db, principal, "roles.read")
    return [role_data(db, role) for role in db.scalars(select(CompanyRole).where(CompanyRole.company_id == principal.company.id).order_by(CompanyRole.id))]


def assignable_role(db, principal, role, *, target=None):
    actor = security.active_membership(db, principal.user.id, principal.company.id)
    actor_role = db.get(CompanyRole, actor.role_id)
    if actor_role.slug == "owner":
        return
    if role.slug == "owner" or (target and db.get(CompanyRole, target.role_id).slug == "owner"):
        raise HTTPException(403, "Only an owner may change company ownership")
    available = security.permissions_for(db, actor)
    desired = set(role_data(db, role)["permissions"])
    if not desired <= available or (target and not security.permissions_for(db, target) <= available):
        raise HTTPException(403, "A role cannot grant or manage permissions it does not hold")


def change_member(db, principal, member_id, role_id=None, *, revoke=False):
    lock_runtime(db)
    security.require_permission(db, principal, "members.manage")
    member = db.get(CompanyMember, member_id)
    if member is None or member.company_id != principal.company.id:
        raise HTTPException(404, "Membership not found")
    current_role = db.get(CompanyRole, member.role_id)
    desired = owned_role(db, principal, role_id) if role_id else current_role
    assignable_role(db, principal, desired, target=member)
    if current_role.slug == "owner" and member.status == "active" and (revoke or desired.slug != "owner"):
        owners = db.scalar(select(func.count(CompanyMember.id)).join(CompanyRole, CompanyRole.id == CompanyMember.role_id)
            .join(User, User.id == CompanyMember.user_id).where(CompanyMember.company_id == principal.company.id,
                CompanyMember.status == "active", CompanyRole.slug == "owner", User.status == "active"))
        if owners <= 1:
            raise HTTPException(409, "The last company owner cannot be removed or demoted")
    if revoke:
        member.status, member.revoked_at = "revoked", utc_now()
    else:
        # role_id is authoritative; keep the old VARCHAR(20) label compatible.
        member.role_id, member.role = desired.id, desired.slug if desired.is_builtin else "custom"
    db.flush()
    return member


def save_role(db, principal, payload, role_id=None):
    lock_runtime(db)
    actor = security.require_permission(db, principal, "roles.manage")
    role = owned_role(db, principal, role_id) if role_id else None
    if role and role.is_builtin:
        raise HTTPException(409, "Built-in roles are immutable; create a custom role")
    keys = set(payload.permissions)
    if not keys <= security.PERMISSIONS.keys() or not keys <= security.permissions_for(db, actor):
        raise HTTPException(403, "Unknown or unauthorized permission grants")
    if role is None:
        slug = security.normalized_slug(payload.name)
        if db.scalar(select(CompanyRole.id).where(CompanyRole.company_id == principal.company.id, CompanyRole.slug == slug)):
            raise HTTPException(409, "Role name is already in use")
        role = CompanyRole(company_id=principal.company.id, name=payload.name, slug=slug, is_builtin=False)
        db.add(role); db.flush()
    else:
        from app.services.audit import record_event
        record_event(db, "role.permissions_changed", "role", role.id, company_id=principal.company.id)
        role.name = payload.name
        db.execute(delete(RolePermissionGrant).where(RolePermissionGrant.role_id == role.id))
    db.add_all(RolePermissionGrant(role_id=role.id, permission_key=key) for key in sorted(keys))
    db.flush()
    return role


def delete_role(db, principal, role_id):
    lock_runtime(db)
    security.require_permission(db, principal, "roles.manage")
    role = owned_role(db, principal, role_id)
    if role.is_builtin or db.scalar(select(CompanyMember.id).where(CompanyMember.role_id == role.id).limit(1)) or db.scalar(select(CompanyInvitation.id).where(CompanyInvitation.role_id == role.id).limit(1)):
        raise HTTPException(409, "Built-in or referenced roles cannot be deleted")
    db.execute(delete(RolePermissionGrant).where(RolePermissionGrant.role_id == role.id))
    db.delete(role)


def invitation_data(db, invitation):
    role = db.get(CompanyRole, invitation.role_id)
    status = invitation.status
    if status == "pending" and security.aware(invitation.expires_at) <= utc_now():
        status = "expired"
    return {"id": invitation.id, "email": invitation.email, "role_id": role.id, "role": role.slug,
        "status": status, "expires_at": invitation.expires_at}


def create_invitation(db, principal, payload):
    lock_runtime(db)
    security.require_permission(db, principal, "invitations.manage")
    role = owned_role(db, principal, payload.role_id)
    assignable_role(db, principal, role)
    if security.production() or os.getenv("AGENTCONNECT_DEV_INVITATIONS", "false").casefold() != "true":
        raise HTTPException(503, "Invitation delivery is not configured; use an explicitly enabled development link locally")
    user = db.scalar(select(User).where(User.email == payload.email))
    if user and security.active_membership(db, user.id, principal.company.id):
        raise HTTPException(409, "This user already has active workspace access")
    pending = db.scalars(select(CompanyInvitation).where(CompanyInvitation.company_id == principal.company.id,
        CompanyInvitation.email == payload.email, CompanyInvitation.status == "pending"))
    for previous in pending:
        previous.status, previous.revoked_at = "revoked", utc_now()
    token = secrets.token_urlsafe(32)
    invitation = CompanyInvitation(company_id=principal.company.id, email=payload.email, role_id=role.id,
        token_hash=security.digest(token), created_by=principal.user.id, expires_at=utc_now() + timedelta(days=7))
    db.add(invitation); db.flush()
    return {**invitation_data(db, invitation), "delivery": "development_link", "development_token": token}


def token_invitation(db, token):
    invitation = db.scalar(select(CompanyInvitation).where(CompanyInvitation.token_hash == security.digest(token)))
    if invitation is None:
        raise HTTPException(404, "Invitation is unavailable")
    company = db.get(Company, invitation.company_id)
    if invitation.status != "pending" or company.status != "active":
        raise HTTPException(409, "Invitation is unavailable")
    if security.aware(invitation.expires_at) <= utc_now():
        raise HTTPException(410, "Invitation has expired")
    issuer = db.get(User, invitation.created_by)
    if issuer is None:
        raise HTTPException(409, "Invitation is no longer authorized")
    principal = security.Principal(issuer, company, "")
    try:
        security.require_permission(db, principal, "invitations.manage")
        assignable_role(db, principal, owned_role(db, principal, invitation.role_id))
    except HTTPException:
        raise HTTPException(409, "Invitation is no longer authorized; request a new invitation") from None
    return invitation


def accept_invitation(db, request, response, payload):
    security.csrf_guard(request)
    preflight = token_invitation(db, payload.token)
    needs_account = db.scalar(select(User.id).where(User.email == preflight.email)) is None
    if needs_account and (not payload.name or not payload.password):
        raise HTTPException(422, "Name and a password of at least 12 characters are required")
    db.rollback()
    encoded = security.hash_password(payload.password) if needs_account else None
    lock_runtime(db)
    invitation = token_invitation(db, payload.token)
    previous_session, signed_in = security.session_for(request, db, required=False)
    if signed_in and signed_in.email != invitation.email:
        raise HTTPException(403, "Sign out and use the invited email address")
    user = db.scalar(select(User).where(User.email == invitation.email))
    if user and (signed_in is None or signed_in.id != user.id):
        raise HTTPException(401, "Sign in with the invited email address")
    if user is None:
        if encoded is None:
            raise HTTPException(409, "The invited account changed; review the invitation again")
        user = User(email=invitation.email, name=payload.name, password_hash=encoded)
        db.add(user); db.flush()
    if user.status != "active":
        raise HTTPException(403, "Account access denied")
    role = db.get(CompanyRole, invitation.role_id)
    if role is None or role.company_id != invitation.company_id:
        raise HTTPException(409, "Invitation role is unavailable")
    member = db.scalar(select(CompanyMember).where(CompanyMember.user_id == user.id, CompanyMember.company_id == invitation.company_id))
    if member and member.status == "active":
        raise HTTPException(409, "Workspace membership already exists")
    if member is None:
        member = CompanyMember(user_id=user.id, company_id=invitation.company_id)
        db.add(member)
    member.role_id, member.role, member.status, member.revoked_at = role.id, role.slug if role.is_builtin else "custom", "active", None
    invitation.status, invitation.accepted_at = "accepted", utc_now()
    user.last_login_at = utc_now()
    if previous_session:
        previous_session.revoked_at = utc_now()
    session, csrf = security.issue_session(db, user, response, invitation.company_id)
    db.commit()
    return security.identity_data(db, user, session, csrf)
