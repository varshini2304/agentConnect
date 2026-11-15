"""Legacy access requires an explicit local operator decision after verified backup."""
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db.models import Agent, Post
from app.db.network import Company, CompanyMember, CompanyRole, User
from app.db.migrations import migrate_sqlite_file, verify_sqlite_file
from app.services.security import create_company, hash_password
from test_migrations import day2


def test_legacy_owner_assignment_is_reviewed_backed_up_and_idempotent(tmp_path):
    from app.services.administration import assign_legacy_owner
    path = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{path}")
    day2(engine)
    migrate_sqlite_file(path, legacy_mapping={41: "agentconnect-legacy", 72: "agentconnect-legacy"}, apply=True)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
        user = User(email="reviewed-owner@example.test", name="Reviewed owner", password_hash=hash_password("correct horse battery staple"))
        db.add(user); db.flush()
        create_company(db, user, "Independent company")
        db.commit()
        uid = user.id
    with pytest.raises(ValueError, match="review"):
        assign_legacy_owner(engine, "reviewed-owner@example.test", reviewed=False)
    result = assign_legacy_owner(engine, " REVIEWED-OWNER@example.test ", reviewed=True)
    assert verify_sqlite_file(result["backup"])["integrity_check"] == "ok"
    with sessions() as db:
        legacy = db.scalar(select(Company).where(Company.slug == "agentconnect-legacy"))
        member = db.scalar(select(CompanyMember).where(CompanyMember.user_id == uid, CompanyMember.company_id == legacy.id))
        assert member.status == "active" and db.get(CompanyRole, member.role_id).slug == "owner"
        assert db.get(Agent, 41).company_id == legacy.id
        assert db.get(Post, 9).content == "Secret historical content"
    assert assign_legacy_owner(engine, "reviewed-owner@example.test", reviewed=True)["membership_id"] == result["membership_id"]
    with pytest.raises(ValueError, match="active"):
        assign_legacy_owner(engine, "missing@example.test", reviewed=True)
    engine.dispose()
