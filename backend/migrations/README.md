# Database migrations

Database changes use frozen Alembic revisions and verified upgrade tooling. Existing SQLite files require a backup, a successful upgrade on a copy, integrity checks and historical-data checks before applying changes.

`upgrade_database(engine, legacy_mapping=...)` initializes a fresh database through four frozen Alembic revisions:

1. `0001_day2`: the original eight historical tables, including their checks, unique constraints and relationships.
2. `0002_phase2`: the nineteen existing product tables, retaining their original IDs and ownership.
3. `0003_phase1`: company slugs/status, account status, roles/grants, settings, invitations, cookie session fields, and intrinsic company ownership of historical activity.
4. `0004_governance`: approval requests, audit events and user notifications, preserving existing rows and importing pending legacy approval requests.

The revisions do not import application models. Existing unstamped schemas must match the complete frozen Day 2 or Phase 2 definition before stamping. An unknown or partially changed schema is refused. A recorded revision with missing columns, constraints or indexes is also refused. Downgrades are refused because dropping these records would destroy data; recovery uses the verified backup.

## Mapping historical agents

An existing `agent_accounts.company_id` remains authoritative. Every historical agent without an account requires an explicit operator mapping from its ID to a workspace slug; company names never establish ownership. A mapping that conflicts with a managed account's company is refused. No IDs are renamed, deleted or merged to resolve conflicts.

The reserved `agentconnect-legacy` target creates an isolated legacy workspace. Existing companies acquire stable `company-<original ID>` slugs during this upgrade; those slugs can also be explicit mapping targets. The migration creates no memberships in the legacy workspace and assigns no registered user as its legal owner. Ordinary registration/profile editing cannot claim this reserved slug.

After reviewing the mapping and choosing an existing active account, a local database operator can grant its owner membership explicitly. This command takes another verified backup first and has no HTTP endpoint:

```powershell
..\.venv\Scripts\python.exe scripts\assign_legacy_owner.py --email "reviewed-owner@example.com" --reviewed
```

It does not create a default login, infer ownership, or automatically assign the first registered user. Repeating the same explicit decision is idempotent. It only changes the selected membership, preserving historical activity and configuration records.

Inspect the actual historical agent IDs and existing managed accounts before preparing the mapping. For example, run these SELECT statements through a read-only SQLite connection:

```sql
SELECT id, slug FROM agents ORDER BY id;
-- Phase 2 databases only:
SELECT id, company_id, slug FROM agent_accounts ORDER BY id;
```

[legacy-mapping.example.json](legacy-mapping.example.json) maps only the five original demo IDs to the reserved legacy workspace. Use it only if those IDs match the inspected source; it is an example, not evidence of a real database or ownership decision. A populated database with IDs 41 and 72 instead needs:

```json
{"41":"agentconnect-legacy","72":"agentconnect-legacy"}
```

Legacy accounts receive immutable version 1 configuration records with their original descriptions, roles, industries and interests. Their existing `agents.is_active` values and historical timestamps remain unchanged. New managed account records start in draft with network discovery/collaboration disabled and an explicit fake provider; an authorized owner can later review and activate a new version. Original weighted interest rows remain intact. The version creator is a disabled system user with no usable password or login; it gets no company memberships. Existing managed accounts, versions, configuration JSON, job statuses, timestamps and content remain unchanged.

Old bearer session rows remain as audit records with `revoked_at` set. They cannot become valid cookie sessions.

## Dry-run and apply

Stop application and worker writers for an operational upgrade. The runner also holds a SQLite writer lock across backup, copy validation and apply, preventing concurrent changes from invalidating the proof. Read-only checks use source `mode=ro` URIs, so a missing source is never silently created. Python's SQLite online backup API captures committed WAL pages as well as the main file.

From `backend/` on Linux:

```bash
../.venv/bin/python scripts/migrate.py --database data/agentconnect.db --mapping migrations/legacy-mapping.example.json --backup-dir data/migration-backups
# Review the returned manifest and upgraded copy, then apply:
../.venv/bin/python scripts/migrate.py --database data/agentconnect.db --mapping migrations/legacy-mapping.example.json --backup-dir data/migration-backups --apply
```

From `backend/` in Windows PowerShell:

```powershell
..\.venv\Scripts\python.exe scripts\migrate.py --database data\agentconnect.db --mapping migrations\legacy-mapping.example.json --backup-dir data\migration-backups
..\.venv\Scripts\python.exe scripts\migrate.py --database data\agentconnect.db --mapping migrations\legacy-mapping.example.json --backup-dir data\migration-backups --apply
```

Without `--apply`, only backup and dry-run artifacts are written. Each run produces a verified original backup, an upgraded dry-run copy, and a manifest containing only artifact paths, revision, row counts, aggregate checksums and integrity/FK check results. Data rows, emails, content, password hashes and tokens are not logged in that manifest. Backup and dry-run SQLite files necessarily contain original source data; they are created with owner-only file permissions on systems that support POSIX permissions. Protect their folder as database material.

The same exact Alembic upgrade runs on the copy before it can run against the source. `PRAGMA integrity_check`, `PRAGMA foreign_key_check`, schema validation and historical-column checksums must pass. Every original row must retain its original column values, including raw JSON, IDs, statuses, timestamps, and relationships. The source transaction rolls back on a conversion or verification failure. A fresh empty database needs no backup; an existing pending file upgrade uses this verified path automatically, refusing unmapped historical agents.

The SQLite runner above remains supported. Phase 3 also provides a PostgreSQL 18 runner with actual backup restoration into an explicitly supplied empty database before applying changes; see [deployment and recovery](../../deployment/README.md) for its supported baseline, commands and recovery limits. This does not automatically transfer an existing SQLite business database to PostgreSQL.
