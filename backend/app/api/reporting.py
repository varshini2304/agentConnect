"""Company reports, audit history and a resource-authorized personal inbox."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_session
from app.db.models import utc_now
from app.db.network import AuditEvent, UserNotification
from app.services import reporting as service
from app.services.security import Principal, current_principal, require_permission

router = APIRouter(tags=["reporting"])


@router.get("/company/dashboard")
def dashboard(principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    return service.dashboard(db, principal)


@router.get("/company/analytics")
def analytics(days: int = Query(7, ge=1, le=365), principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    return service.analytics(db, principal, days)


@router.get("/audit")
def audit(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), event_type: str | None = Query(None, max_length=100),
          search: str | None = Query(None, max_length=200), principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    require_permission(db, principal, "settings.manage")
    query = select(AuditEvent).where(AuditEvent.company_id == principal.company.id)
    if event_type:
        query = query.where(AuditEvent.event_type == event_type)
    if search:
        query = query.where(or_(AuditEvent.event_type.icontains(search, autoescape=True), AuditEvent.resource_type.icontains(search, autoescape=True)))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).offset(offset).limit(limit))
    return {"items": [service.audit_data(row) for row in rows], "total": total, "offset": offset, "limit": limit}


@router.get("/user-notifications")
def notifications(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), category: str | None = Query(None, max_length=40),
                  unread: bool | None = None, search: str | None = Query(None, max_length=200),
                  principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    rows = service.notifications(db, principal, category, unread, search)
    return {"items": [service.notification_data(db, row) for row in rows[offset:offset + limit]], "total": len(rows), "offset": offset, "limit": limit}


@router.post("/user-notifications/read-all")
def read_all(principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    rows = service.notifications(db, principal, unread=True)
    now = utc_now()
    for row in rows:
        row.read_at = now
    db.commit()
    return {"updated": len(rows)}


@router.post("/user-notifications/{notification_id}/read")
def read(notification_id: int, principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    row = db.get(UserNotification, notification_id)
    if row is None or not service.notification_visible(db, principal, row, service.granted(db, principal)):
        raise HTTPException(404, "Notification not found")
    row.read_at = row.read_at or utc_now()
    db.commit()
    return service.notification_data(db, row)


@router.get("/workspace/agents/{agent_id}/activity")
def activity(agent_id: int, principal: Principal = Depends(current_principal), db: Session = Depends(get_session)):
    return service.activity(db, principal, agent_id)
