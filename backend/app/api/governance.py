"""Company governance and auditable human review endpoints."""
from fastapi import APIRouter, Depends, Query
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_session
from app.db.models import Agent, utc_now
from app.db.network import AgentAccount, ApprovalRequest
from app.schemas.network import CompanyPolicy, StrictModel
from app.services import approvals
from app.services.locking import lock_runtime
from app.services.security import Principal, current_principal, require_permission

router = APIRouter(tags=["governance"])


class GovernanceInput(StrictModel):
    network_opt_in: bool
    policy: CompanyPolicy
    expected_policy_version: int | None = Field(default=None, ge=1)


class ReviewInput(StrictModel):
    approve: bool
    comments: str = Field(default="", max_length=1000)


class EmergencyInput(StrictModel):
    reason: str = Field(min_length=1, max_length=500)


def governance_data(company):
    return {"company_id": company.id, "policy_version": company.policy_version,
            "network_opt_in": company.network_opt_in, "policy": CompanyPolicy.model_validate(company.policy).model_dump()}


@router.get("/governance")
def governance(principal: Principal = Depends(current_principal)):
    return governance_data(principal.company)


@router.put("/governance")
def update(payload: GovernanceInput, principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    lock_runtime(db)
    require_permission(db, principal, "settings.manage")
    if payload.expected_policy_version is not None and payload.expected_policy_version != principal.company.policy_version:
        from fastapi import HTTPException
        raise HTTPException(409, "Company policy changed; refresh before saving")
    principal.company.policy = payload.policy.model_dump()
    principal.company.network_opt_in = payload.network_opt_in
    principal.company.policy_version += 1
    principal.company.updated_at = utc_now()
    db.commit()
    return governance_data(principal.company)


@router.post("/governance/emergency-pause")
def emergency(payload: EmergencyInput, principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    lock_runtime(db)
    require_permission(db, principal, "settings.manage")
    principal.company.policy = {**principal.company.policy, "emergency_paused": True}
    principal.company.policy_version += 1
    count = 0
    for account in db.scalars(select(AgentAccount).where(AgentAccount.company_id == principal.company.id, AgentAccount.state == "active")):
        account.state = "paused"
        db.get(Agent, account.id).is_active = False
        count += 1
    from app.services.audit import record_event
    record_event(db, "governance.emergency_pause", "company", principal.company.id, company_id=principal.company.id, metadata={"paused_agents": count})
    db.commit()
    return {"paused_agents": count, **governance_data(principal.company)}


@router.get("/governance/approvals")
def approval_list(status: str | None = Query(None, max_length=20), offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100), principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    require_permission(db, principal, "approvals.manage")
    lock_runtime(db)
    for row in db.scalars(select(ApprovalRequest).where(ApprovalRequest.company_id == principal.company.id, ApprovalRequest.status == "pending")):
        approvals.expire(db, row)
    db.flush()
    query = select(ApprovalRequest).where(ApprovalRequest.company_id == principal.company.id)
    if status:
        query = query.where(ApprovalRequest.status == status)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    from app.services.reporting import approval_visible, granted
    permissions = granted(db, principal)
    authorized = [row for row in db.scalars(query.order_by(ApprovalRequest.id.desc())) if approval_visible(db, principal, row, permissions)]
    total = len(authorized)
    rows = authorized[offset:offset + limit]
    db.commit()
    return {"items": [approvals.data(row) for row in rows], "total": total, "offset": offset, "limit": limit}


@router.get("/governance/approvals/{approval_id}")
def approval_detail(approval_id: int, principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    lock_runtime(db)
    row = approvals.owned(db, principal, approval_id)
    approvals.expire(db, row)
    db.commit()
    return approvals.data(row)


@router.post("/governance/approvals/{approval_id}/review")
def review(approval_id: int, payload: ReviewInput, principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    row = approvals.review(db, principal, approvals.owned(db, principal, approval_id), approve=payload.approve, comments=payload.comments)
    db.commit()
    return approvals.data(row)


@router.post("/governance/approvals/{approval_id}/cancel")
def cancel(approval_id: int, principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    row = approvals.cancel(db, principal, approvals.owned(db, principal, approval_id))
    db.commit()
    return approvals.data(row)
