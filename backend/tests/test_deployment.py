"""Worker shutdown and optional real PostgreSQL migration acceptance."""
import json
import os
import signal
import sys

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


def test_worker_sigterm_finishes_current_work_without_claiming_another(tmp_path, monkeypatch, caplog):
    from app import worker
    from app.db.migrations import upgrade_database
    engine = create_engine(f"sqlite:///{tmp_path / 'worker.db'}")
    upgrade_database(engine)
    monkeypatch.setattr(worker, 'SessionLocal', sessionmaker(bind=engine))
    monkeypatch.setattr(sys, 'argv', ['worker'])
    completed = []

    def complete(factory):
        os.kill(os.getpid(), signal.SIGTERM)
        completed.append('finished')
        return True

    monkeypatch.setattr(worker, 'run_once', complete)
    with caplog.at_level('INFO'):
        worker.main()
    assert completed == ['finished']
    assert [json.loads(record.message)['event'] for record in caplog.records] == ['worker_started', 'worker_stopped']


def test_worker_error_log_omits_exception_payload(tmp_path, monkeypatch, caplog):
    from app import worker
    from app.db.migrations import upgrade_database
    engine = create_engine(f"sqlite:///{tmp_path / 'worker.db'}")
    upgrade_database(engine)
    monkeypatch.setattr(worker, 'SessionLocal', sessionmaker(bind=engine))
    monkeypatch.setattr(sys, 'argv', ['worker', '--once'])

    def fail(factory):
        raise RuntimeError('private-provider-payload-and-key')

    monkeypatch.setattr(worker, 'run_once', fail)
    with caplog.at_level('INFO'):
        worker.main()
    assert 'private-provider' not in caplog.text
    assert 'worker_transaction_failed' in [json.loads(record.message)['event'] for record in caplog.records]


@pytest.fixture
def postgres_pair():
    source = os.getenv('AGENTCONNECT_TEST_POSTGRES_URL')
    restore = os.getenv('AGENTCONNECT_TEST_POSTGRES_RESTORE_URL')
    if not source or not restore:
        pytest.skip('Set two disposable PostgreSQL database URLs for live restore acceptance')
    engines = [create_engine(url, hide_parameters=True) for url in (source, restore)]
    for engine in engines:
        with engine.connect() as db:
            assert not db.scalar(text("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")), 'Test databases must start empty'
    yield engines
    for engine in engines:
        engine.dispose()


def test_postgres_clean_schema_and_populated_backup_restore_upgrade(postgres_pair, tmp_path):
    from app.db import network
    from app.db.migrations import HEAD, MigrationError, _schema, migrate_postgres_database, upgrade_database
    from app.db.models import Base
    source, restore = postgres_pair
    with source.begin() as db:
        from app.db.migrations import _initialize_postgres
        _initialize_postgres(db)
        assert db.scalar(text('SELECT version_num FROM alembic_version')) == '0003_phase1'
        db.execute(text("INSERT INTO users (email,name,password_hash,status,created_at) VALUES ('saved@example.test','Saved','historical-sensitive-hash','active',CURRENT_TIMESTAMP)"))
    with pytest.raises(MigrationError, match='verified'):
        upgrade_database(source)
    result = migrate_postgres_database(source, restore, backup_dir=tmp_path, apply=True)
    assert result['applied'] is True
    assert result['revision'] == HEAD
    with source.connect() as db, restore.connect() as copy:
        assert db.scalar(text('SELECT password_hash FROM users')) == 'historical-sensitive-hash'
        assert copy.scalar(text('SELECT password_hash FROM users')) == 'historical-sensitive-hash'
        assert _schema(db) == _schema(copy)
        schema = _schema(db)
    upgrade_database(source)
    # A separate schema lets the application declare its own tables without altering source data.
    with source.begin() as db:
        db.exec_driver_sql('CREATE SCHEMA model_parity')
        db.exec_driver_sql('SET LOCAL search_path TO model_parity')
        Base.metadata.create_all(db)
        assert _schema(db) == schema
    assert 'historical-sensitive-hash' not in open(result['manifest']).read()
    assert os.stat(result['backup']).st_mode & 0o777 == 0o600


def test_postgres_runner_refuses_source_as_restore_target():
    from app.db.migrations import MigrationError, migrate_postgres_database
    engine = create_engine('postgresql+psycopg://unused:secret@127.0.0.1:1/source')
    with pytest.raises(MigrationError, match='different'):
        migrate_postgres_database(engine, engine, backup_dir='/tmp')
