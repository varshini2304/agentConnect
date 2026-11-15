"""Local operator tooling; deliberately not exposed through an HTTP route."""
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.db.migrations import migrate_sqlite_file
from app.db.network import Company, CompanyMember, CompanyRole, User
from app.services.locking import lock_runtime


def assign_legacy_owner(engine, email, *, reviewed=False):
    if not reviewed:
        raise ValueError("Explicit operator review is required before assigning legacy ownership")
    if engine.dialect.name != "sqlite" or not engine.url.database or not Path(engine.url.database).is_file():
        raise ValueError("An existing migrated SQLite database is required")
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    normalized = email.strip().casefold()
    with sessions() as db:
        user = db.scalar(select(User).where(User.email == normalized, User.status == "active"))
        company = db.scalar(select(Company).where(Company.slug == "agentconnect-legacy", Company.status == "active"))
        if user is None or company is None:
            raise ValueError("The reviewed user and legacy company must both be active and already exist")
    backup = migrate_sqlite_file(engine.url.database, apply=False)
    from app.services.audit import install_audit_hooks, record_event
    install_audit_hooks()
    with sessions() as db, db.begin():
        lock_runtime(db)
        user = db.scalar(select(User).where(User.email == normalized, User.status == "active"))
        company = db.scalar(select(Company).where(Company.slug == "agentconnect-legacy", Company.status == "active"))
        if user is None or company is None:
            raise ValueError("The reviewed user and legacy company must still be active")
        role = db.scalar(select(CompanyRole).where(CompanyRole.company_id == company.id, CompanyRole.slug == "owner"))
        if role is None:
            raise ValueError("Legacy workspace roles have not been migrated")
        member = db.scalar(select(CompanyMember).where(CompanyMember.company_id == company.id, CompanyMember.user_id == user.id))
        if member is None:
            member = CompanyMember(company_id=company.id, user_id=user.id)
            db.add(member)
        member.role_id, member.role, member.status, member.revoked_at = role.id, "owner", "active", None
        db.info.update(company_id=company.id, actor_type="operator")
        db.flush()
        record_event(db, "administration.legacy_owner_assigned", "company_member", member.id, company_id=company.id, actor_type="operator")
        return {"company_id": company.id, "user_id": user.id, "membership_id": member.id, "backup": backup["backup"]}
