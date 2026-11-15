# Deployment and recovery

AgentConnect is a FastAPI/SQLAlchemy modular monolith, a separate database-backed worker, and a static React frontend. The deployment files run PostgreSQL 18, the API, the worker and an nginx HTTPS proxy. No broker is required: committed deliveries and publishing jobs are the durable queue. This is deployment configuration and locally tested migration support; it does not mean a public production service has been deployed.

## Fresh host

Use Docker with Compose, DNS for your hostname, and a certificate issued for that hostname. Run commands from the repository root; older installations expose `docker-compose` instead of `docker compose`.

1. Copy `deployment/.env.example` to `deployment/.env`. Generate two different URL-safe passwords, for example with `openssl rand -hex 32`. Set the explicit `https://your-hostname` trusted origin. Keep this file private and outside source control. The database administrator password and application password are separate; the application database role cannot create roles/databases or act as a superuser.
2. Put the certificate chain in `deployment/certs/fullchain.pem` and its private key in `deployment/certs/privkey.pem`. Protect the private key and arrange renewal. The proxy terminates TLS, redirects HTTP to HTTPS and serves `/api/` through the API on the same origin. Only ports 80 and 443 are published; PostgreSQL and the API remain on the Compose network.
3. Run `docker compose --env-file deployment/.env -p agentconnect -f deployment/compose.yaml config --quiet`, then `docker compose --env-file deployment/.env -p agentconnect -f deployment/compose.yaml up --build -d`. PostgreSQL creates the application role once on a new volume. The migration service initializes only a fresh database or validates an existing head; an existing pending upgrade requires the operator path below.
4. Check `docker compose --env-file deployment/.env -p agentconnect -f deployment/compose.yaml ps`, then `curl --fail https://your-hostname/api/v1/health/ready`. Register a company through the browser. Newly registered companies start empty. Real provider calls need an explicit Gemini key; fake providers are disabled in this production configuration.

Production configuration requires explicit HTTPS trusted origins and Secure, HTTP-only session cookies. Keep every externally accepted hostname in that origin list. The API trusts forwarded headers because the supplied network exposes it only through nginx; preserve that boundary if adapting this configuration. Production invitation email delivery is not configured. Build context exclusions prevent local databases, certificates, secrets and environments from entering the image. Review and pin approved image digests for your own release process.

The backend image deliberately uses the PostgreSQL image as its base so its `pg_dump` and `pg_restore` match server major 18. Its PostgreSQL server is not started in API/worker containers. PostgreSQL 18 volumes mount at `/var/lib/postgresql`, following the [official image documentation](https://hub.docker.com/_/postgres).

## Health and shutdown

`/api/v1/health/live` checks process liveness. `/api/v1/health/ready` checks database access, the expected Alembic revision and the runtime mutex; readiness fails when the schema is unavailable or stale. The worker validates the same revision and mutex before processing and installs the transactional audit hooks independently of the API process.

SIGTERM/SIGINT stop the worker from claiming another job. A current run finishes within the existing provider deadline, which is capped at 120 seconds, and then the worker exits. Compose permits 150 seconds before a forced stop. Provider threads are daemon threads and cannot hold the process open after their deadline. If the process is killed before finalization, another worker recovers the expired lease; lease tokens fence out late results. A database outage can still delay finalization until the process supervisor's stop deadline.

Worker lifecycle/errors are JSON records containing a timestamp, level and fixed event name. Exceptions, provider payloads, prompts and credentials are excluded. HTTP access logs are disabled in the supplied proxy/API commands to avoid retaining query strings. Audit history remains in the database under company permissions; it is not a replacement for host monitoring, off-host backups or incident alerting.

## SQLite upgrade

Stop API and worker writers. Existing SQLite files use online backups, writer locking, a copy upgrade, complete historical-column comparisons and integrity/foreign-key checks. Run from `backend/`:

```sh
../.venv/bin/python scripts/migrate.py --database data/agentconnect.db --backup-dir data/migration-backups
../.venv/bin/python scripts/migrate.py --database data/agentconnect.db --backup-dir data/migration-backups --apply
```

Add `--mapping ../docs/legacy-mapping.example.json` only when upgrading older unowned Day 2/Phase 2 agents, after explicitly reviewing every ownership mapping. A Phase 1 (`0003_phase1`) database requires no mapping for the additive Phase 3 migration. Originals, IDs, sessions, memberships, historical messages, attempts, JSON and timestamps remain in place. Pending legacy run approvals gain unified inbox records with a 24-hour review deadline; their original rows are retained. Draft publications are not inferred to be approval requests.

The CLI defaults to a dry run. Backups, dry-run files and manifests have restricted permissions. The manifest contains counts/checksums, not historical content or password hashes. Keep a protected off-host copy of the backup. See [the detailed legacy migration guide](migrations.md) for ownership and restore boundaries.

## PostgreSQL upgrade and backup proof

Install `backend/requirements-postgres.txt` and matching-major `pg_dump`/`pg_restore` when running outside the supplied image. PostgreSQL 18 has been exercised locally. Existing PostgreSQL databases must be at the recognized frozen Phase 1 baseline or a later supported revision. Fresh PostgreSQL initialization derives the baseline from frozen revisions 0001–0003 in an isolated in-memory SQLite database, recreates their schema using native PostgreSQL types/constraints, copies baseline seed rows, stamps 0003, then runs the additive 0004 revision. It never imports current application models to rewrite migration history. SQLite-to-PostgreSQL transfer of an existing business database is a separate reviewed data-transfer operation; changing its connection URL does not transfer data.

Stop all API and worker writers. An operator must supply a distinct **empty disposable restore database** owned by the restore user. It must contain no business data. Neither the runner nor application account needs permission to create or drop databases. Set connection strings through protected environment variables rather than command arguments:

```sh
export AGENTCONNECT_DATABASE_URL='postgresql+psycopg://app_user:URL_SAFE_PASSWORD@db:5432/agentconnect'
export AGENTCONNECT_RESTORE_DATABASE_URL='postgresql+psycopg://restore_user:URL_SAFE_PASSWORD@db:5432/agentconnect_restore'
cd backend
../.venv/bin/python scripts/migrate_postgres.py --backup-dir backups
# Review the manifest and keep the restored dry-run database for inspection.
# Provision a second empty restore database before the independent apply run.
../.venv/bin/python scripts/migrate_postgres.py --backup-dir backups --apply
```

Change `AGENTCONNECT_RESTORE_DATABASE_URL` to the newly provisioned empty database before the apply command. For containerized operation, use `docker compose run --rm --no-deps` with the backend image, an explicitly mounted writable protected backup directory, and those two environment variables. Provision the restore database through your database administrator; do not give the normal application role elevated privileges.

The runner takes a migration advisory lock and table locks that exclude writers. It creates an owner-only custom-format archive, restores it with error-on-first-failure, compares all original tables/column values, upgrades that restored copy and compares them again. Only `--apply` upgrades the source, in the held transaction. Unknown/partial schemas and nonempty restore targets are refused; no database is reset or dropped. Restore copies deliberately remain for operator inspection. Use matching backup-client and server majors: an observed PostgreSQL 18 client archive could not be restored into PostgreSQL 16 because its session settings differ. See [PostgreSQL's restore options](https://www.postgresql.org/docs/18/app-pgrestore.html).

On failure, keep writers stopped and inspect the protected backup and copy. For recovery, restore the verified archive into a newly provisioned recovery database, verify its schema/counts and application behavior, then change the application URL. For SQLite, stop every process and restore the verified backup file while preserving the failed file separately; never leave old WAL/SHM sidecars beside a restored database. Downgrades are refused because they could destroy governance history. Do not run `docker compose down -v` against a database whose data you need.

## Verification boundaries

Migration acceptance covers clean SQLite initialization, populated Day 2/Phase 2/Phase 1 copies, dry runs, corruption/refusal, WAL backups, foreign keys and application-schema parity. A separate live PostgreSQL 18 acceptance test exercises baseline initialization, a populated backup, actual `pg_restore`, copy-first upgrade/apply, idempotency and PostgreSQL application-model parity. Worker tests exercise SIGTERM during current work and payload-free JSON errors.

Local verification on 2026-11-15 also built both Docker images and started the full stack in an isolated Compose project. HTTPS readiness, real CSRF registration/login, production cookie attributes, authenticated governance/dashboard/analytics/audit/inbox endpoints, the nonsuperuser database role and clean worker SIGTERM exit were checked against PostgreSQL 18 with a temporary test certificate. These checks do not establish public hosting or certificate renewal.

Run live PostgreSQL acceptance only against two deliberately empty disposable databases:

```sh
AGENTCONNECT_TEST_POSTGRES_URL='postgresql+psycopg://test_user:TEST_PASSWORD@localhost:5432/test_source' \
AGENTCONNECT_TEST_POSTGRES_RESTORE_URL='postgresql+psycopg://test_user:TEST_PASSWORD@localhost:5432/test_restore' \
../.venv/bin/python -m pytest tests/test_deployment.py -q
```

The ordinary test run skips this test unless both URLs are supplied. Real provider availability, certificate issuance/renewal, public DNS, high availability, off-host disaster recovery, sustained load and production hosting are operator acceptance work, not claims made by these local checks.
