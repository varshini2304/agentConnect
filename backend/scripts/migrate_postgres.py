"""Verified PostgreSQL migration with an explicit empty restore database."""
import argparse
import json
import os
from pathlib import Path
import sys

from sqlalchemy import create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.migrations import MigrationError, migrate_postgres_database, upgrade_database


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup-dir', type=Path, default=Path('backups'))
    parser.add_argument('--apply', action='store_true', help='Apply after restoring and upgrading the verified backup.')
    parser.add_argument('--initialize', action='store_true', help='Initialize a fresh database; refuses existing pending migrations.')
    args = parser.parse_args()
    source_url = os.getenv('AGENTCONNECT_DATABASE_URL', '')
    restore_url = os.getenv('AGENTCONNECT_RESTORE_DATABASE_URL', '')
    if not source_url.startswith('postgresql+psycopg://') or (not args.initialize and not restore_url.startswith('postgresql+psycopg://')):
        parser.error('Set PostgreSQL psycopg URLs in AGENTCONNECT_DATABASE_URL and AGENTCONNECT_RESTORE_DATABASE_URL (restore URL is not needed for --initialize).')
    engine = create_engine(source_url, hide_parameters=True)
    restore = create_engine(restore_url, hide_parameters=True) if not args.initialize else None
    try:
        if args.initialize:
            upgrade_database(engine)
            print(json.dumps({'initialized': True}))
        else:
            print(json.dumps(migrate_postgres_database(engine, restore, backup_dir=args.backup_dir, apply=args.apply), indent=2))
    except Exception:
        parser.exit(1, 'Migration refused; inspect database availability, schema, backup/restore permissions and protected configuration. No source reset was performed.\n')
    finally:
        engine.dispose()
        if restore is not None:
            restore.dispose()


if __name__ == '__main__':
    main()
