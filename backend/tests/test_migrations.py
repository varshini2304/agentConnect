"""Real SQLite copy upgrades preserve historical identities and ownership."""
from pathlib import Path
import json
import sqlite3

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


BACKEND = Path(__file__).resolve().parents[1]


def revision(engine, target):
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, target)


def day2(engine):
    revision(engine, "0001_day2")
    with engine.begin() as db:
        for agent_id, slug in ((41, "first"), (72, "second")):
            db.execute(text("INSERT INTO agents VALUES (:id,:slug,'Same historical name','Scout','Energy','Original description',1,'2025-01-02 03:04:05')"), {"id": agent_id, "slug": slug})
        db.execute(text("INSERT INTO agent_interests VALUES (5,41,'keyword','solar',2.5)"))
        db.execute(text("INSERT INTO agent_relationships VALUES (8,41,72,'partner',1.25)"))
        db.execute(text("INSERT INTO posts VALUES (9,41,'Preserve title','Secret historical content','energy','hash1','manual','original','2025-01-02 03:04:05')"))
        db.exec_driver_sql("INSERT INTO routing_decisions VALUES (10,9,72,0.9,1,1,'{\"original\":true}','2025-01-02 03:04:06')")
        db.exec_driver_sql("INSERT INTO notifications VALUES (11,9,72,0.9,'{\"original\":true}','completed','2025-01-02 03:04:06',NULL)")
        db.exec_driver_sql("INSERT INTO agent_interactions VALUES (12,9,72,11,'responded','{\"original\":true}',NULL,'2025-01-02 03:04:07','2025-01-02 03:04:08')")
        db.execute(text("INSERT INTO comments VALUES (13,9,72,12,'Original comment','2025-01-02 03:04:08')"))


def rows(engine):
    with engine.connect() as db:
        return {table: [dict(row) for row in db.execute(text(f'SELECT * FROM "{table}" ORDER BY 1')).mappings()] for table in inspect(db).get_table_names() if table != "alembic_version"}


def test_fresh_database_and_idempotent_upgrade(tmp_path):
    from app.db.migrations import upgrade_database
    engine = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    upgrade_database(engine)
    first = rows(engine)
    assert {"agents", "company_roles", "permissions", "company_settings", "company_invitations", "login_rate_limits"} <= first.keys()
    assert first['runtime_mutex'] == [{'id': 1, 'value': 0}]
    upgrade_database(engine)
    assert rows(engine) == first


def test_populated_day2_preserves_all_original_columns_and_links(tmp_path):
    from app.db.migrations import migrate_sqlite_file, verify_sqlite_file
    path = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{path}")
    day2(engine)
    original = rows(engine)
    engine.dispose()
    result = migrate_sqlite_file(path, legacy_mapping={41: "agentconnect-legacy", 72: "agentconnect-legacy"}, backup_dir=tmp_path / "backups", apply=True)
    assert result["applied"] is True
    assert verify_sqlite_file(Path(result["backup"]))["integrity_check"] == "ok"
    current = rows(engine)
    for table, records in original.items():
        assert [{key: row[key] for key in records[0]} for row in current[table]] == records
    with engine.connect() as db:
        legacy = db.scalar(text("SELECT id FROM companies WHERE slug='agentconnect-legacy'"))
        for table in ("agents", "posts", "routing_decisions", "notifications", "agent_interactions", "comments"):
            assert db.scalar(text(f"SELECT COUNT(*) FROM {table} WHERE company_id IS NULL OR company_id != :company"), {"company": legacy}) == 0
        assert db.scalar(text("SELECT COUNT(*) FROM agent_accounts")) == 2
        assert db.scalar(text("SELECT COUNT(*) FROM agent_versions")) == 2
        from app.schemas.network import AgentConfig
        config = json.loads(db.scalar(text('SELECT config FROM agent_versions ORDER BY id LIMIT 1')))
        normalized = AgentConfig.model_validate(config).model_dump()
        assert {key: normalized[key] for key in config} == config
        assert db.scalar(text("SELECT COUNT(*) FROM company_members")) == 0
        assert db.scalar(text("SELECT status FROM users")) == "disabled"
        assert db.execute(text("PRAGMA foreign_key_check")).all() == []
    manifest_text = Path(result["manifest"]).read_text()
    assert "Secret historical content" not in manifest_text
    assert "Original comment" not in manifest_text
    assert "password_hash" not in manifest_text


def test_unowned_agents_require_complete_explicit_mapping_and_leave_source_unchanged(tmp_path):
    from app.db.migrations import MigrationError, migrate_sqlite_file
    path = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{path}")
    day2(engine)
    original = rows(engine)
    with pytest.raises(MigrationError, match="mapping"):
        migrate_sqlite_file(path, legacy_mapping={41: "agentconnect-legacy"}, backup_dir=tmp_path / "backups", apply=True)
    assert rows(engine) == original


def test_current_phase2_accounts_preserve_company_and_revoke_bearer_sessions(tmp_path):
    from app.db.migrations import upgrade_database
    engine = create_engine(f"sqlite:///{tmp_path / 'phase2.db'}")
    day2(engine)
    revision(engine, "0002_phase2")
    with engine.begin() as db:
        db.exec_driver_sql("INSERT INTO companies VALUES (91,'Real Company',1,'{\"keep\":true}',7,'2025-02-01 00:00:00')")
        db.execute(text("INSERT INTO users VALUES (92,'existing@example.com','Existing','preserved-hash')"))
        db.execute(text("INSERT INTO company_members VALUES (93,91,92,'owner')"))
        db.execute(text("INSERT INTO login_sessions VALUES ('old-bearer-hash',92,'2030-01-01 00:00:00')"))
        db.execute(text("INSERT INTO agent_accounts VALUES (41,91,'managed-first','active',NULL,NULL,'2025-02-01 00:00:00')"))
        db.exec_driver_sql("INSERT INTO agent_versions VALUES (94,41,1,'{\"original\":true}',92,'2025-02-01 00:00:01')")
        db.exec_driver_sql('UPDATE agent_accounts SET active_version_id=94, config_version_id=94 WHERE id=41')
        db.exec_driver_sql("INSERT INTO knowledge_sources VALUES (95,91,41,92,'Original knowledge','Private knowledge content','private',NULL,NULL,'2025-02-01 00:00:02')")
        db.exec_driver_sql("INSERT INTO publications VALUES (96,91,'human',92,41,'Original publication','Original publication content','energy','network','published','original-pub','original-hash',94,7,'2025-02-01 00:00:03','2025-02-01 00:00:04')")
        db.exec_driver_sql("INSERT INTO discovery_records VALUES (97,96,41,91,'Original name',1,1,0.8,'Original reason','{\"original\":true}','{\"original\":true}')")
        db.exec_driver_sql("INSERT INTO publishing_jobs VALUES (98,91,41,92,94,7,'Original title','Original brief','energy','network','original-job','failed',3,'[{\"error\":\"original\"}]','2025-02-01 00:00:05',NULL,NULL,'original-error',96,'2025-02-01 00:00:05')")
        db.exec_driver_sql('INSERT INTO runtime_mutex VALUES (1,7)')
        db.exec_driver_sql("INSERT INTO conversations VALUES (99,'direct','Original conversation','active',92,96,'original-conversation',1,'2025-02-01 00:00:06')")
        db.exec_driver_sql("INSERT INTO conversation_members VALUES (100,99,41,94,'active',1,'2025-02-01 00:00:07',NULL)")
        db.exec_driver_sql("INSERT INTO invitations VALUES (101,99,41,72,'pending',1,'2025-02-01 00:00:08')")
        db.exec_driver_sql("INSERT INTO messages VALUES (102,99,1,41,92,'human','Original message',0,'original-message','2025-02-01 00:00:09')")
        db.exec_driver_sql("INSERT INTO message_deliveries VALUES (103,102,41,'failed',3,'2025-02-01 00:00:10',NULL,NULL,'original-error')")
        db.exec_driver_sql("INSERT INTO agent_runs VALUES (104,103,41,94,7,'failed','skip','Original reason','fake','original-model','2025-02-01 00:00:11')")
        db.exec_driver_sql("INSERT INTO agent_run_attempts VALUES (105,104,1,'failed','original-error',7,'2025-02-01 00:00:12','2025-02-01 00:00:13')")
        db.exec_driver_sql("INSERT INTO run_approvals VALUES (106,104,99,41,'pending','Original approval content','Original reason')")
    original = rows(engine)
    upgrade_database(engine, legacy_mapping={72: "agentconnect-legacy"})
    with engine.connect() as db:
        assert db.scalar(text("SELECT company_id FROM agents WHERE id=41")) == 91
        assert db.scalar(text("SELECT company_id FROM posts WHERE id=9")) == 91
        assert db.scalar(text("SELECT company_id FROM agent_accounts WHERE id=41")) == 91
        assert db.scalar(text("SELECT policy FROM companies WHERE id=91")) == '{"keep":true}'
        assert db.scalar(text("SELECT password_hash FROM users WHERE id=92")) == "preserved-hash"
        assert db.scalar(text("SELECT revoked_at FROM login_sessions")) is not None
        assert db.scalar(text("SELECT role_id FROM company_members WHERE id=93")) is not None
        assert db.scalar(text("SELECT COUNT(*) FROM company_members")) == 1
        approval = db.execute(text("SELECT company_id,agent_id,source_type,source_id,action_type,proposed_content,status FROM approval_requests")).one()
        assert tuple(approval) == (91, 41, 'run_approval', 106, 'message.reply', 'Original approval content', 'pending')
        assert db.execute(text("PRAGMA foreign_key_check")).all() == []
    first = rows(engine)
    upgrade_database(engine)
    assert rows(engine) == first
    for table, records in original.items():
        assert records
        assert all(any(all(row[key] == value for key, value in historical.items()) for row in first[table]) for historical in records)


def test_dry_run_leaves_working_file_unchanged_and_creates_verified_copy(tmp_path):
    from app.db.migrations import migrate_sqlite_file
    path = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{path}")
    day2(engine)
    original = rows(engine)
    result = migrate_sqlite_file(path, legacy_mapping={41: "agentconnect-legacy", 72: "agentconnect-legacy"}, backup_dir=tmp_path / "backups")
    assert result["applied"] is False
    assert rows(engine) == original
    copy = create_engine(f"sqlite:///{result['dry_run']}")
    assert "company_roles" in inspect(copy).get_table_names()
    assert "company_roles" not in inspect(engine).get_table_names()


def test_corrupt_database_or_backup_rejected(tmp_path):
    from app.db.migrations import MigrationError, verify_sqlite_file
    corrupt = tmp_path / "corrupt.db"
    corrupt.write_bytes(b"not a sqlite database")
    with pytest.raises(MigrationError, match="SQLite"):
        verify_sqlite_file(corrupt)


def test_mapping_rejects_conflicting_managed_owner(tmp_path):
    from app.db.migrations import MigrationError, upgrade_database
    engine = create_engine(f"sqlite:///{tmp_path / 'phase2.db'}")
    day2(engine)
    revision(engine, "0002_phase2")
    with engine.begin() as db:
        db.execute(text("INSERT INTO companies VALUES (91,'Real Company',0,'{}',1,'2025-02-01')"))
        db.execute(text("INSERT INTO agent_accounts VALUES (41,91,'managed-first','draft',NULL,NULL,'2025-02-01')"))
    original = rows(engine)
    with pytest.raises(MigrationError, match="ownership"):
        upgrade_database(engine, legacy_mapping={41: "agentconnect-legacy", 72: "agentconnect-legacy"})
    assert rows(engine) == original


@pytest.mark.parametrize('target', ['0001_day2', '0002_phase2'])
def test_unstamped_existing_schema_is_validated_before_stamping(tmp_path, target):
    from app.db.migrations import upgrade_database
    engine = create_engine(f"sqlite:///{tmp_path / 'unstamped.db'}")
    day2(engine)
    revision(engine, target)
    with engine.begin() as db:
        db.exec_driver_sql('DROP TABLE alembic_version')
    upgrade_database(engine, legacy_mapping={41: 'agentconnect-legacy', 72: 'agentconnect-legacy'})
    with engine.connect() as db:
        from app.db.migrations import HEAD
        assert db.scalar(text('SELECT version_num FROM alembic_version')) == HEAD
        assert db.scalar(text('SELECT COUNT(*) FROM agents')) == 2


def test_unrecognized_schema_is_not_stamped_or_changed(tmp_path):
    from app.db.migrations import MigrationError, upgrade_database
    engine = create_engine(f"sqlite:///{tmp_path / 'unknown.db'}")
    day2(engine)
    with engine.begin() as db:
        db.exec_driver_sql('DROP TABLE alembic_version')
        db.exec_driver_sql('ALTER TABLE agents ADD COLUMN unexpected TEXT')
    original = rows(engine)
    with pytest.raises(MigrationError, match='Unrecognized'):
        upgrade_database(engine, legacy_mapping={41: 'agentconnect-legacy', 72: 'agentconnect-legacy'})
    assert rows(engine) == original
    assert 'alembic_version' not in inspect(engine).get_table_names()


def test_wal_backup_contains_committed_pages(tmp_path):
    from app.db.migrations import migrate_sqlite_file
    path = tmp_path / 'wal.db'
    engine = create_engine(f'sqlite:///{path}')
    day2(engine)
    with sqlite3.connect(path) as writer:
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute('PRAGMA wal_autocheckpoint=0')
        writer.execute("UPDATE posts SET title='Committed WAL title' WHERE id=9")
        writer.commit()
        assert Path(str(path) + '-wal').stat().st_size > 0
        result = migrate_sqlite_file(path, legacy_mapping={41: 'agentconnect-legacy', 72: 'agentconnect-legacy'}, backup_dir=tmp_path / 'backups')
        with sqlite3.connect(result['backup']) as backup:
            assert backup.execute('SELECT title FROM posts WHERE id=9').fetchone()[0] == 'Committed WAL title'


def test_composite_tenant_fk_and_historical_unique_constraints_hold(tmp_path):
    from app.db.migrations import upgrade_database
    from sqlalchemy.exc import IntegrityError
    engine = create_engine(f"sqlite:///{tmp_path / 'constraints.db'}")
    upgrade_database(engine)
    with engine.connect() as db:
        db.exec_driver_sql('PRAGMA foreign_keys=ON')
        db.exec_driver_sql("INSERT INTO companies VALUES (1,'First',0,'{}',1,'2025-01-01','first','active','2025-01-01'), (2,'Second',0,'{}',1,'2025-01-01','second','active','2025-01-01')")
        db.exec_driver_sql("INSERT INTO users VALUES (1,'one@example.com','One','hash','active','2025-01-01',NULL)")
        db.exec_driver_sql("INSERT INTO company_roles VALUES (1,1,'Owner','owner',1,'2025-01-01')")
        db.commit()
        with pytest.raises(IntegrityError):
            db.exec_driver_sql("INSERT INTO company_members VALUES (1,2,1,'owner',1,'active','2025-01-01',NULL)")
        db.rollback()
        with pytest.raises(IntegrityError):
            db.exec_driver_sql("INSERT INTO companies VALUES (3,'Duplicate',0,'{}',1,'2025-01-01','first','active','2025-01-01')")
        db.rollback()


@pytest.mark.parametrize('content', ['{"41":"agentconnect-legacy","41":"other"}', '{"41":"agentconnect-legacy","041":"other"}', '[]', '{"-1":"agentconnect-legacy"}', '{"41":null}'])
def test_mapping_file_rejects_duplicates_or_invalid_shape(tmp_path, content):
    from app.db.migrations import MigrationError, load_legacy_mapping
    path = tmp_path / 'mapping.json'
    path.write_text(content)
    with pytest.raises(MigrationError, match='mapping'):
        load_legacy_mapping(path)


def test_corrupt_backup_stops_before_apply(tmp_path, monkeypatch):
    from app.db import migrations
    path = tmp_path / 'legacy.db'
    engine = create_engine(f'sqlite:///{path}')
    day2(engine)
    original = rows(engine)
    backup = migrations._online_backup

    def corrupt_copy(source, destination):
        backup(source, destination)
        Path(destination).write_bytes(b'corrupt backup')

    monkeypatch.setattr(migrations, '_online_backup', corrupt_copy)
    with pytest.raises(migrations.MigrationError, match='SQLite'):
        migrations.migrate_sqlite_file(path, legacy_mapping={41: 'agentconnect-legacy', 72: 'agentconnect-legacy'}, backup_dir=tmp_path / 'backups', apply=True)
    assert rows(engine) == original


def test_frozen_schema_matches_application_models():
    from app.db import network  # Register all tenant and governance tables.
    from app.db.models import Base
    from app.db.migrations import HEAD, _expected_schema, _schema
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with engine.connect() as db:
        assert _schema(db) == _expected_schema(HEAD)


def test_governance_upgrade_preserves_populated_phase1_and_dry_run(tmp_path):
    from app.db.migrations import HEAD, migrate_sqlite_file, verify_sqlite_file
    path = tmp_path / 'phase1.db'
    engine = create_engine(f'sqlite:///{path}')
    day2(engine)
    config = Config(str(BACKEND / 'alembic.ini'))
    config.set_main_option('script_location', str(BACKEND / 'migrations'))
    config.attributes['legacy_mapping'] = {41: 'agentconnect-legacy', 72: 'agentconnect-legacy'}
    with engine.begin() as db:
        config.attributes['connection'] = db
        command.upgrade(config, '0003_phase1')
        db.exec_driver_sql("UPDATE users SET password_hash='unchanged-sensitive-hash'")
    original = rows(engine)
    dry = migrate_sqlite_file(path, backup_dir=tmp_path / 'backups')
    assert rows(engine) == original
    assert 'approval_requests' not in inspect(engine).get_table_names()
    copy = create_engine(f"sqlite:///{dry['dry_run']}")
    assert {'approval_requests', 'audit_events', 'user_notifications'} <= set(inspect(copy).get_table_names())
    applied = migrate_sqlite_file(path, backup_dir=tmp_path / 'backups', apply=True)
    current = rows(engine)
    for table, records in original.items():
        assert current[table] == records
    assert HEAD == '0007_remove_legacy_post_source_uniqueness'
    assert verify_sqlite_file(path)['foreign_key_violations'] == 0
    assert rows(create_engine(f"sqlite:///{applied['backup']}")) == original
    assert 'unchanged-sensitive-hash' not in Path(applied['manifest']).read_text()
