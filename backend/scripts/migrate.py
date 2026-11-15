"""Verified copy-first SQLite migration. Run from backend, or use --help."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.migrations import MigrationError, load_legacy_mapping, migrate_sqlite_file


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True, type=Path)
    parser.add_argument('--mapping', type=Path, help='Explicit JSON object mapping legacy agent IDs to workspace slugs.')
    parser.add_argument('--backup-dir', type=Path)
    parser.add_argument('--apply', action='store_true', help='Apply only after verified backup and successful copy upgrade.')
    args = parser.parse_args()
    try:
        mapping = load_legacy_mapping(args.mapping) if args.mapping else None
        result = migrate_sqlite_file(args.database, legacy_mapping=mapping, backup_dir=args.backup_dir, apply=args.apply)
    except MigrationError as exc:
        parser.exit(1, f'Migration refused: {exc}\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
