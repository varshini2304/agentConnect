"""Alembic upgrades with verified backups and copy-first data checks."""
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import uuid

from alembic import command
from alembic.config import Config
from sqlalchemy import DateTime, Engine, MetaData, create_engine, inspect, select, text


BACKEND = Path(__file__).resolve().parents[2]
HEAD = '0007_remove_legacy_post_source_uniqueness'


class MigrationError(RuntimeError):
    pass


def _config(connection, legacy_mapping=None):
    config = Config(str(BACKEND / 'alembic.ini'))
    config.set_main_option('script_location', str(BACKEND / 'migrations'))
    config.attributes['connection'] = connection
    config.attributes['legacy_mapping'] = legacy_mapping
    return config


def _schema(connection):
    inspector = inspect(connection)
    result = {}
    for table in inspector.get_table_names():
        if table == 'alembic_version':
            continue
        primary = set(inspector.get_pk_constraint(table)['constrained_columns'])
        columns = {(column['name'], column['type']._type_affinity.__name__, column['nullable'], column['name'] in primary) for column in inspector.get_columns(table)}
        unique = {tuple(item['column_names']) for item in inspector.get_unique_constraints(table)}
        unique.update(tuple(item['column_names']) for item in inspector.get_indexes(table) if item['unique'])
        foreign = {(tuple(item['constrained_columns']), item['referred_table'], tuple(item['referred_columns']), item['options'].get('ondelete')) for item in inspector.get_foreign_keys(table)}
        checks = {_check_sql(item['sqltext']) for item in inspector.get_check_constraints(table)}
        indexes = {(tuple(item['column_names']), bool(item['unique'])) for item in inspector.get_indexes(table) if not item['unique']}
        result[table] = (columns, unique, foreign, checks, indexes)
    return result


def _check_sql(sql):
    # PostgreSQL reflects IN checks as ANY(ARRAY[...]) with explicit type casts.
    sql = re.sub(r'::(?:character varying|double precision|integer|text|numeric)(?:\[\])?', '', sql.lower())
    sql = ''.join(sql.split()).replace('=any', 'in').replace('array[', '[')
    return sql.translate(str.maketrans('', '', '()[]'))


@lru_cache(maxsize=4)
def _expected_schema(revision):
    engine = create_engine('sqlite://')
    try:
        with engine.begin() as connection:
            command.upgrade(_config(connection), revision)
            return _schema(connection)
    finally:
        engine.dispose()


def _upgrade(connection, legacy_mapping=None):
    if connection.dialect.name == 'postgresql':
        return _upgrade_postgres(connection)
    if connection.dialect.name != 'sqlite':
        raise MigrationError('The verified migration runner currently supports SQLite only.')
    current_schema = _schema(connection)
    config = _config(connection, legacy_mapping)
    tables = set(inspect(connection).get_table_names())
    revision = connection.scalar(text('SELECT version_num FROM alembic_version')) if 'alembic_version' in tables else None
    if revision is None and current_schema:
        match = next((name for name in ('0001_day2', '0002_phase2') if current_schema == _expected_schema(name)), None)
        if match is None:
            raise MigrationError('Unrecognized existing schema; no tables were reset. Review its differences before stamping.')
        command.stamp(config, match)
    elif revision is not None:
        if revision not in ('0001_day2', '0002_phase2', '0003_phase1', '0004_governance',
                            '0005_demo_source_id', '0006_publication_sources', HEAD):
            raise MigrationError('Unknown Alembic revision; operator review required.')
        if current_schema != _expected_schema(revision):
            raise MigrationError('Database schema differs from its recorded Alembic revision.')
    command.upgrade(config, 'head')
    if _schema(connection) != _expected_schema(HEAD):
        raise MigrationError('Upgraded schema failed validation.')
    if connection.exec_driver_sql('PRAGMA foreign_key_check').all():
        raise MigrationError('SQLite foreign key verification failed.')
    if connection.exec_driver_sql('PRAGMA integrity_check').scalar_one() != 'ok':
        raise MigrationError('SQLite integrity verification failed.')


def _needs_upgrade(connection):
    if 'alembic_version' not in inspect(connection).get_table_names():
        return True
    return connection.scalar(text('SELECT version_num FROM alembic_version')) != HEAD


def upgrade_database(engine: Engine, *, legacy_mapping=None):
    """Initialize fresh engines; existing files always get backup and copy validation."""
    if engine.dialect.name == 'postgresql':
        with engine.begin() as connection:
            if _schema(connection) and _needs_upgrade(connection):
                raise MigrationError('Existing PostgreSQL databases require the verified migrate_postgres.py backup/restore runner.')
            _upgrade_postgres(connection)
        return
    if engine.dialect.name != 'sqlite':
        raise MigrationError('Only SQLite and PostgreSQL migrations are supported.')
    with engine.connect() as connection:
        existing = bool(_schema(connection))
        pending = _needs_upgrade(connection)
    database = engine.url.database
    if existing and pending and database not in (None, '', ':memory:'):
        migrate_sqlite_file(Path(database), legacy_mapping=legacy_mapping, backup_dir=Path(database).resolve().parent / 'migration-backups', apply=True)
        return
    with engine.connect() as connection:
        connection.exec_driver_sql('PRAGMA foreign_keys=ON')
        connection.commit()
        try:
            connection.exec_driver_sql('BEGIN IMMEDIATE')
            _upgrade(connection, legacy_mapping)
            connection.commit()
        except Exception:
            connection.rollback()
            raise


def _initialize_postgres(connection):
    """Fresh PostgreSQL baseline comes only from the immutable SQLite revisions."""
    frozen = create_engine('sqlite://')
    try:
        with frozen.begin() as source:
            command.upgrade(_config(source), '0003_phase1')
            metadata = MetaData()
            metadata.reflect(source, only=list(_expected_schema('0003_phase1')))
            for table in metadata.tables.values():
                for column in table.columns:
                    column.type = column.type.as_generic()
                    if isinstance(column.type, DateTime):
                        column.type = DateTime(timezone=True)
            metadata.create_all(connection)
            for table in metadata.tables.values():
                records = source.execute(select(table)).mappings().all()
                if records:
                    connection.execute(table.insert(), records)
        command.stamp(_config(connection), '0003_phase1')
    finally:
        frozen.dispose()


def _upgrade_postgres(connection):
    if connection.scalar(text('SELECT current_schema()')) != 'public':
        raise MigrationError('PostgreSQL migration requires the public application schema.')
    if not _schema(connection):
        _initialize_postgres(connection)
    tables = inspect(connection).get_table_names()
    revision = connection.scalar(text('SELECT version_num FROM alembic_version')) if 'alembic_version' in tables else None
    if revision not in ('0003_phase1', HEAD):
        raise MigrationError('PostgreSQL supports the frozen Phase 1 baseline and later revisions; upgrade historic SQLite before moving it.')
    if _schema(connection) != _expected_schema(revision):
        raise MigrationError('PostgreSQL schema differs from its recorded Alembic revision.')
    command.upgrade(_config(connection), HEAD)
    if _schema(connection) != _expected_schema(HEAD):
        raise MigrationError('Upgraded PostgreSQL schema failed validation.')


def _postgres_tool(name, engine, arguments):
    url = engine.url
    env = {key: value for key, value in os.environ.items() if not key.startswith('PG')}
    for key, value in {'PGHOST': url.host, 'PGPORT': str(url.port or 5432), 'PGDATABASE': url.database, 'PGUSER': url.username, 'PGPASSWORD': url.password}.items():
        if value is not None:
            env[key] = value
    for option in ('sslmode', 'sslrootcert', 'sslcert', 'sslkey'):
        if option in url.query:
            env['PG' + option.upper()] = str(url.query[option])
    try:
        subprocess.run([name, '--no-password', *arguments], env=env, capture_output=True, check=True, timeout=300)
    except (OSError, subprocess.SubprocessError):
        raise MigrationError(f'{name} failed; check PostgreSQL client version, access and protected connection settings.') from None


def _postgres_snapshot(connection):
    quote = connection.dialect.identifier_preparer.quote
    return {table: ([column['name'] for column in inspect(connection).get_columns(table)], Counter(_digest(row) for row in connection.exec_driver_sql(f'SELECT * FROM {quote(table)}'))) for table in _schema(connection)}


def _assert_postgres_preserved(before, connection):
    quote = connection.dialect.identifier_preparer.quote
    for table, (columns, records) in before.items():
        selected = ','.join(quote(column) for column in columns)
        actual = Counter(_digest(row) for row in connection.exec_driver_sql(f'SELECT {selected} FROM {quote(table)}'))
        if records - actual:
            raise MigrationError(f'Historical data preservation failed for {table}.')


def migrate_postgres_database(engine, restore_engine, *, backup_dir, apply=False):
    """Restore into an explicitly supplied empty scratch DB before any source change."""
    source_identity = (engine.url.host, engine.url.port or 5432, engine.url.database)
    restore_identity = (restore_engine.url.host, restore_engine.url.port or 5432, restore_engine.url.database)
    if source_identity == restore_identity:
        raise MigrationError('Restore target must be a different, empty PostgreSQL database.')
    if engine.dialect.name != 'postgresql' or restore_engine.dialect.name != 'postgresql':
        raise MigrationError('Source and restore URLs must both use PostgreSQL.')
    backup_dir = Path(backup_dir).resolve()
    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    suffix = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
    backup = backup_dir / f'postgres-{suffix}.backup.dump'
    manifest = backup_dir / f'postgres-{suffix}.manifest.json'
    with restore_engine.connect() as copy:
        if inspect(copy).get_table_names():
            raise MigrationError('Restore target is not empty; no tables were removed.')
    with engine.connect() as source:
        transaction = source.begin()
        try:
            if not source.scalar(text('SELECT pg_try_advisory_xact_lock(728144305)')):
                raise MigrationError('Another PostgreSQL migration holds the migration lock.')
            tables = inspect(source).get_table_names()
            if tables:
                names = ','.join(source.dialect.identifier_preparer.quote(table) for table in tables)
                source.exec_driver_sql('SET LOCAL lock_timeout = \'15s\'')
                source.exec_driver_sql(f'LOCK TABLE {names} IN SHARE MODE')
            before = _postgres_snapshot(source)
            descriptor = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
            _postgres_tool('pg_dump', engine, ['--format=custom', '--no-owner', '--no-acl', f'--file={backup}'])
            _postgres_tool('pg_restore', restore_engine, ['--exit-on-error', '--no-owner', '--no-acl', '--dbname=' + str(restore_engine.url.database), str(backup)])
            with restore_engine.begin() as copy:
                if _schema(copy) != _schema(source):
                    raise MigrationError('Restored PostgreSQL backup schema does not match the source.')
                _assert_postgres_preserved(before, copy)
                _upgrade_postgres(copy)
                _assert_postgres_preserved(before, copy)
                after = _postgres_snapshot(copy)
            if apply:
                _upgrade_postgres(source)
                _assert_postgres_preserved(before, source)
                transaction.commit()
            else:
                transaction.rollback()
        except Exception:
            transaction.rollback()
            raise
    result = {'applied': apply, 'backup': str(backup), 'manifest': str(manifest), 'source_tables': _manifest_counts(before), 'dry_run_tables': _manifest_counts(after), 'revision': HEAD, 'backup_restored': True}
    descriptor = os.open(manifest, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, 'w') as handle:
        json.dump(result, handle, indent=2)
        handle.write('\n')
    return result


def _readonly(path):
    return closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True))


def verify_sqlite_file(path):
    """Read-only checks never create a missing source or mutate its schema/data."""
    path = Path(path)
    if not path.is_file():
        raise MigrationError(f'SQLite source does not exist: {path}')
    try:
        with _readonly(path) as db:
            integrity = db.execute('PRAGMA integrity_check').fetchall()
            foreign = db.execute('PRAGMA foreign_key_check').fetchall()
            if integrity != [('ok',)] or foreign:
                raise MigrationError('SQLite integrity or foreign key verification failed.')
            counts = {table: db.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")}
        return {'integrity_check': 'ok', 'foreign_key_violations': 0, 'counts': counts}
    except sqlite3.DatabaseError as exc:
        raise MigrationError('SQLite file could not be verified.') from exc


def _online_backup(source, destination):
    # Online backup captures committed WAL pages as well as the main database file.
    destination = Path(destination)
    try:
        descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
    except FileExistsError:
        raise MigrationError('Backup destination already exists.')
    with _readonly(source) as incoming, closing(sqlite3.connect(destination)) as outgoing:
        incoming.backup(outgoing)
    verify_sqlite_file(destination)


def _snapshot(path):
    with _readonly(path) as db:
        result = {}
        for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name!='alembic_version' ORDER BY name"):
            columns = [row[1] for row in db.execute(f'PRAGMA table_info("{table}")')]
            records = Counter(_digest(row) for row in db.execute(f'SELECT * FROM "{table}"'))
            result[table] = (columns, records)
        return result


def _digest(row):
    return hashlib.sha256(json.dumps(tuple(row), separators=(',', ':'), default=lambda value: value.hex() if isinstance(value, bytes) else str(value)).encode()).hexdigest()


def _assert_preserved(before, after):
    with _readonly(after) as db:
        for table, (columns, records) in before.items():
            selected = ','.join(f'"{column}"' for column in columns)
            actual = Counter(_digest(row) for row in db.execute(f'SELECT {selected} FROM "{table}"'))
            if records - actual:
                raise MigrationError(f'Historical data preservation failed for {table}.')


def _manifest_counts(snapshot):
    return {table: {'rows': sum(records.values()), 'checksum': hashlib.sha256(json.dumps(sorted(records.items())).encode()).hexdigest()} for table, (_, records) in snapshot.items()}


def migrate_sqlite_file(path, *, legacy_mapping=None, backup_dir=None, apply=False):
    """Default is dry-run. Applying repeats the proven upgrade inside a writer lock."""
    path = Path(path).resolve()
    verify_sqlite_file(path)
    backup_dir = Path(backup_dir or path.parent / 'migration-backups').resolve()
    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    suffix = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
    backup = backup_dir / f'{path.stem}-{suffix}.backup.sqlite'
    dry_run = backup_dir / f'{path.stem}-{suffix}.dry-run.sqlite'
    manifest_path = backup_dir / f'{path.stem}-{suffix}.manifest.json'
    engine = create_engine(f'sqlite:///{path}', hide_parameters=True)
    try:
        with engine.connect() as working:
            working.exec_driver_sql('PRAGMA foreign_keys=ON')
            working.commit()
            # Exclude concurrent writers from snapshot through commit; readers remain usable.
            working.exec_driver_sql('BEGIN IMMEDIATE')
            try:
                _online_backup(path, backup)
                verify_sqlite_file(backup)
                before = _snapshot(backup)
                _online_backup(backup, dry_run)
                copy_engine = create_engine(f'sqlite:///{dry_run}', hide_parameters=True)
                try:
                    with copy_engine.connect() as copy:
                        copy.exec_driver_sql('PRAGMA foreign_keys=ON')
                        copy.commit()
                        copy.exec_driver_sql('BEGIN IMMEDIATE')
                        try:
                            _upgrade(copy, legacy_mapping)
                            copy.commit()
                        except Exception:
                            copy.rollback()
                            raise
                finally:
                    copy_engine.dispose()
                dry_checks = verify_sqlite_file(dry_run)
                _assert_preserved(before, dry_run)
                if apply:
                    _upgrade(working, legacy_mapping)
                    # Check original values before commit, so any failure rolls back.
                    for table, (columns, records) in before.items():
                        selected = ','.join(f'"{column}"' for column in columns)
                        actual = Counter(_digest(row) for row in working.exec_driver_sql(f'SELECT {selected} FROM "{table}"'))
                        if records - actual:
                            raise MigrationError(f'Historical data preservation failed for {table}.')
                    working.commit()
                else:
                    working.rollback()
            except Exception:
                working.rollback()
                raise
    finally:
        engine.dispose()
    result = {'applied': apply, 'backup': str(backup), 'dry_run': str(dry_run), 'manifest': str(manifest_path), 'source_tables': _manifest_counts(before), 'dry_run_tables': _manifest_counts(_snapshot(dry_run)), 'integrity_check': dry_checks['integrity_check'], 'foreign_key_violations': dry_checks['foreign_key_violations'], 'revision': HEAD}
    manifest_path.write_text(json.dumps(result, indent=2) + '\n')
    manifest_path.chmod(0o600)
    return result


def _mapping_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate agent ID in mapping.')
        result[key] = value
    return result


def load_legacy_mapping(path):
    try:
        with Path(path).open() as handle:
            raw = json.load(handle, object_pairs_hook=_mapping_pairs)
        if not isinstance(raw, dict) or any(not isinstance(key, str) or not key.isdecimal() or int(key) <= 0 or not isinstance(value, str) or not value for key, value in raw.items()):
            raise ValueError('Expected positive agent ID keys and workspace slug string values.')
        mapping = {int(key): value for key, value in raw.items()}
        if len(mapping) != len(raw):
            raise ValueError('Duplicate normalized agent IDs.')
        return mapping
    except (OSError, ValueError) as exc:
        raise MigrationError(f'Invalid legacy mapping: {exc}') from exc
