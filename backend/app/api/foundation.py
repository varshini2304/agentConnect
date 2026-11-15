"""Thin company, authentication and team API; business rules live in services."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import get_session
from app.db.models import utc_now
from app.db.network import CompanyInvitation, CompanyMember, User
from app.schemas.foundation import (
    AccountInput, CompanyInput, CompanyRead, CompanyUpdate, InvitationAccept,
    InvitationInput, InvitationRead, LoginInput, MemberInput, MemberRead, RegisterInput,
    RoleInput, RoleRead, SessionRead, SettingsInput, SettingsRead, UserRead, WorkspaceInput,
    CsrfRead, PermissionRead, InvitationPreview, OkRead,
)
from app.services import security, team
from app.services.locking import lock_runtime
from app.services.security import Principal, current_principal

router = APIRouter( tags=["foundation"])


def commit(db):
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "These details conflict with an existing record") from None


@router.get("/auth/csrf", response_model=CsrfRead)
def csrf(request: Request, response: Response, db: Session = Depends(get_session)):
    return security.csrf_token(request, response, db)


@router.post("/auth/register", response_model=SessionRead, status_code=201)
def register(payload: RegisterInput, request: Request, response: Response, db: Session = Depends(get_session)):
    return security.register(db, request, response, payload)


@router.post("/auth/login", response_model=SessionRead)
def login(payload: LoginInput, request: Request, response: Response, db: Session = Depends(get_session)):
    return security.login(db, request, response, payload)


@router.get("/auth/me", response_model=SessionRead)
def me(request: Request, db: Session = Depends(get_session)):
    session, user = security.session_for(request, db)
    return security.identity_data(db, user, session, request.cookies.get(security.cookie_names()[1], ""))


@router.post("/auth/logout", response_model=OkRead)
def logout(request: Request, response: Response, db: Session = Depends(get_session)):
    session, _ = security.session_for(request, db, required=False)
    security.csrf_guard(request, session)
    if session:
        session.revoked_at = utc_now()
        from app.services.audit import record_event
        record_event(db, "auth.logout", "user", session.user_id, company_id=session.selected_company_id,
            actor_type="user", actor_id=session.user_id)
    commit(db)
    security.clear_session(response)
    return {"ok": True}


@router.post("/auth/workspace", response_model=SessionRead)
def select_workspace(payload: WorkspaceInput, request: Request, db: Session = Depends(get_session)):
    lock_runtime(db)
    session, user = security.session_for(request, db)
    if payload.company_id not in {c["id"] for c in security.companies_for(db, user)}:
        raise HTTPException(403, "Workspace access denied")
    session.selected_company_id = payload.company_id
    commit(db)
    return security.identity_data(db, user, session, request.cookies.get(security.cookie_names()[1], ""))


@router.get("/account", response_model=UserRead)
def account(request: Request, db: Session = Depends(get_session)):
    _, user = security.session_for(request, db)
    return {key: getattr(user, key) for key in UserRead.model_fields}


@router.patch("/account", response_model=UserRead)
def update_account(payload: AccountInput, request: Request, db: Session = Depends(get_session)):
    _, user = security.session_for(request, db)
    user.name = payload.name
    commit(db)
    return {key: getattr(user, key) for key in UserRead.model_fields}


@router.get("/companies", response_model=list[CompanyRead])
def companies(request: Request, db: Session = Depends(get_session)):
    _, user = security.session_for(request, db)
    return security.companies_for(db, user)


@router.post("/companies", response_model=CompanyRead, status_code=201)
def add_company(payload: CompanyInput, request: Request, db: Session = Depends(get_session)):
    lock_runtime(db)
    _, user = security.session_for(request, db)
    company = security.create_company(db, user, payload.name, payload.slug)
    commit(db)
    return security.company_data(db, company, security.active_membership(db, user.id, company.id))


@router.get("/companies/current", response_model=CompanyRead)
def company_current(principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    return security.company_data(db, principal.company, security.active_membership(db, principal.user.id, principal.company.id))


@router.patch("/companies/current", response_model=CompanyRead)
def update_current(payload: CompanyUpdate, principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    team.update_company(db, principal, principal.company, payload)
    commit(db)
    return security.company_data(db, principal.company, security.active_membership(db, principal.user.id, principal.company.id))


@router.get("/companies/current/settings", response_model=SettingsRead)
def settings(principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    return security.settings_data(db, principal.company)


@router.put("/companies/current/settings", response_model=SettingsRead)
def update_settings(payload: SettingsInput, principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    team.update_settings(db, principal, payload)
    commit(db)
    return security.settings_data(db, principal.company)


@router.get("/companies/{company_id}", response_model=CompanyRead)
def company_detail(company_id: int, principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    company = team.owned_company(db, principal, company_id)
    actor = team.actor_in(db, principal, company)
    member = security.require_permission(db, actor, "company.read")
    return security.company_data(db, company, member)


@router.patch("/companies/{company_id}", response_model=CompanyRead)
def update_company(company_id: int, payload: CompanyUpdate, principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    company = team.owned_company(db, principal, company_id)
    team.update_company(db, principal, company, payload)
    commit(db)
    return security.company_data(db, company, security.active_membership(db, principal.user.id, company.id))


@router.get("/members", response_model=list[MemberRead])
def members(principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    return team.list_members(db, principal)


@router.patch("/members/{member_id}", response_model=MemberRead)
def member_role(member_id: int, payload: MemberInput, principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    member = team.change_member(db, principal, member_id, payload.role_id)
    commit(db)
    return team.member_data(db, member)


@router.delete("/members/{member_id}", response_model=OkRead)
def revoke_member(member_id: int, principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    team.change_member(db, principal, member_id, revoke=True)
    commit(db)
    return {"ok": True}


@router.get("/roles", response_model=list[RoleRead])
def roles(principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    return team.list_roles(db, principal)


@router.get("/permissions", response_model=list[PermissionRead])
def permissions(principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    security.require_permission(db, principal, "roles.read")
    return [{"key": key, "description": value} for key, value in security.PERMISSIONS.items()]


@router.post("/roles", response_model=RoleRead, status_code=201)
def create_role(payload: RoleInput, principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    role = team.save_role(db, principal, payload)
    commit(db)
    return team.role_data(db, role)


@router.put("/roles/{role_id}", response_model=RoleRead)
def edit_role(role_id: int, payload: RoleInput, principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    role = team.save_role(db, principal, payload, role_id)
    commit(db)
    return team.role_data(db, role)


@router.delete("/roles/{role_id}", response_model=OkRead)
def delete_role(role_id: int, principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    team.delete_role(db, principal, role_id)
    commit(db)
    return {"ok": True}


@router.get("/company-invitations", response_model=list[InvitationRead], response_model_exclude_none=True)
def company_invitations(principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    security.require_permission(db, principal, "invitations.manage")
    return [team.invitation_data(db, invitation) for invitation in db.scalars(select(CompanyInvitation).where(
        CompanyInvitation.company_id == principal.company.id).order_by(CompanyInvitation.id.desc()))]


@router.post("/company-invitations", response_model=InvitationRead, response_model_exclude_none=True, status_code=201)
def create_invitation(payload: InvitationInput, principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    data = team.create_invitation(db, principal, payload)
    commit(db)
    return data


@router.get("/company-invitations/preview", response_model=InvitationPreview)
def invitation_preview(token: str, db: Session = Depends(get_session)):
    if len(token) < 20 or len(token) > 256:
        raise HTTPException(404, "Invitation is unavailable")
    invitation = team.token_invitation(db, token)
    from app.db.network import Company, CompanyRole
    return {"company_name": db.get(Company, invitation.company_id).name, "email": invitation.email,
        "role": db.get(CompanyRole, invitation.role_id).slug, "expires_at": invitation.expires_at}


@router.post("/company-invitations/accept", response_model=SessionRead)
def accept_invitation(payload: InvitationAccept, request: Request, response: Response, db: Session = Depends(get_session)):
    return team.accept_invitation(db, request, response, payload)


@router.post("/company-invitations/{invitation_id}/revoke", response_model=InvitationRead, response_model_exclude_none=True)
def revoke_invitation(invitation_id: int, principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    lock_runtime(db)
    security.require_permission(db, principal, "invitations.manage")
    invitation = db.get(CompanyInvitation, invitation_id)
    if invitation is None or invitation.company_id != principal.company.id:
        raise HTTPException(404, "Invitation not found")
    if invitation.status == "pending":
        invitation.status, invitation.revoked_at = "revoked", utc_now()
    commit(db)
    return team.invitation_data(db, invitation)
