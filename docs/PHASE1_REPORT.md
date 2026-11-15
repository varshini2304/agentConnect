# AgentConnect Phase 1 completion report

## Result and scope

Phase 1 extends the existing modular monolith and preserves the already implemented Phase 2 product. Independently registered companies now have isolated workspaces, HTTP-only cookie authentication, company-scoped roles and permission grants, onboarding/settings, teams and expiring invitations. Existing agent profiles, posts, deterministic relevance, notifications, interactions, comments and retries are available through authenticated company-scoped routes.

The starting checkout already contained uncommitted Phase 2 work. Its simpler PBKDF2/bearer foundation did not satisfy this Phase 1 specification. That foundation was upgraded in place; functioning communication, relevance and provider modules were retained. No unrelated project or protected `.sf/` or `.dist/` directory was modified.

## Files created and modified

New Phase 1 backend files:

- `backend/app/services/security.py`, `team.py`, `locking.py`, `administration.py`, `legacy.py`
- `backend/app/api/foundation.py`, `legacy.py`
- `backend/app/schemas/foundation.py`
- `backend/app/db/migrations.py`
- `backend/alembic.ini`, `backend/migrations/env.py`, and frozen revisions `0001_day2.py`, `0002_phase2.py`, `0003_phase1.py`
- `backend/scripts/migrate.py`, `assign_legacy_owner.py`
- `backend/tests/auth_helpers.py`, `test_security_foundation.py`, `test_migrations.py`, `test_legacy_tenants.py`, `test_legacy_owner.py`

Extended backend files include `app/main.py`, existing `db/models.py` and `db/network.py`, workspace/conversation APIs and services, the publishing runtime's company-status checks, original post/routing/notification/runner services, requirements/environment examples, and the existing regression fixtures/tests. Agent configurations, provider adapters and deterministic scoring behavior were retained.

New frontend modules are `workspace/Access.tsx`, `Administration.tsx`, `History.tsx`, `JoinInvitation.tsx` and `access.ts`. The existing API client, session shell, workspace/settings, agent/publishing/conversation views, original dashboard/history pages, original API clients/components, styles, HTML/environment examples and domain assertions were adapted. No new frontend dependency or redesign was introduced.

Documentation changes include the README, this report, `docs/phase1-contract.md`, `docs/migrations.md` and `docs/legacy-mapping.example.json`. The earlier Phase 2 report now points to the replacement authentication/migration foundation. The complete current working-tree inventory is appended below; it also includes preserved uncommitted files from the preceding Phase 2 implementation.

## Database changes and migration safety

The existing Company, User, CompanyMember and LoginSession identities/tables were extended instead of replaced. `CompanyMembership` and `AuthSession` are model aliases preserving those existing membership/session table IDs. New tables provide CompanyRole, Permission, RolePermissionGrant, CompanySettings, CompanyInvitation and database-backed LoginRateLimit records.

- Companies have globally unique normalized slugs, display names, active/suspended status, timestamps and settings.
- Users have unique normalized emails, account status, Argon2id password hashes, creation and last-login timestamps.
- Memberships have active/revoked status, a company-scoped role reference and revocation time. Composite foreign keys prevent assigning another company's role to a membership or invitation.
- Built-in and custom role grants are persisted. The old short membership `role` field is retained as a compatibility label; the company-scoped `role_id` and its grants are authoritative, including long custom role names.
- Sessions store only hashed random authentication/CSRF tokens, selected workspace, expiry and revocation metadata. Old bearer sessions are revoked during migration without deleting their rows.
- Intrinsically owned legacy agents, posts, routing decisions, notifications, interactions and comments gain indexed company ownership. New public network publications and shared conversations retain their distinct visibility/membership rules.

Three frozen Alembic revisions establish the reviewed original eight-table Day 2 baseline, preserve the nineteen pre-existing Phase 2 tables, then add Phase 1. The result is **33 application tables plus Alembic's version table**. Production startup no longer uses `Base.metadata.create_all()`; explicit unit fixtures may still create model-only test schemas.

The migration runner recognizes only complete known schemas, refuses unknown/partial schemas, requires an explicit complete agent-ID ownership mapping, backs up through SQLite's online backup API, verifies the backup, upgrades a copy first, checks all original column values/IDs/JSON/timestamps/statuses/relationships, verifies foreign keys and integrity, then applies the same migration transactionally. It holds a SQLite writer lock across this proof so concurrent writes cannot invalidate it. Existing managed account ownership wins; `company_name` never assigns legal ownership. No records are deleted or renumbered to resolve uniqueness conflicts. Downgrade is refused in favor of restoring a verified backup.

Historical unowned agents map explicitly to the reserved `agentconnect-legacy` workspace. It receives no automatic human owner or network permissions. A local operator can explicitly assign an existing active account after reviewing the mapping, using `scripts/assign_legacy_owner.py --email ... --reviewed`; the command creates another verified backup first. There is no HTTP owner-claim route or default login. Ordinary company creation/renaming cannot claim that reserved slug.

### Actual working database evidence

At initial inspection, `backend/data` contained only `.gitkeep`: no working SQLite database existed. An empty integration-test placeholder appeared later. It contained **zero tables and zero application records**. It was not presented as historical user data.

That placeholder was backed up and opened successfully, migrated on a verified copy, then initialized through the same safe apply path:

- Applied revision: `0003_phase1`.
- Backup: `backend/data/migration-backups/agentconnect-20261115T055656Z-cafcf9af.backup.sqlite`.
- Manifest: `backend/data/migration-backups/agentconnect-20261115T055656Z-cafcf9af.manifest.json`.
- Original table count: 0; resulting application table count: 33.
- `integrity_check`: `ok`; foreign-key violations: 0.
- No user, company or agent records were created in the working database by acceptance tests. Browser/tests use isolated temporary files. No working data was reset or overwritten.

The populated migration acceptance tests separately verify all original tables and historical records in realistic Day 2/Phase 2 copies. Backups contain original database material and remain ignored by Git, with owner-only backup permissions where supported. See [migrations.md](migrations.md) for mapping inspection, dry-run/apply commands and recovery boundaries.

## Authentication and authorization flow

1. The browser requests `/api/v1/auth/csrf`. A readable, host-only CSRF cookie and response token initialize the request boundary.
2. Registration/login require a matching CSRF header/cookie and an allowed origin. If already authenticated, the CSRF hash must also match that server session. Passwords preserve intentional whitespace and use maintained `argon2-cffi` Argon2id hashing: 64MiB memory, three iterations, parallelism one. Existing PBKDF2 hashes are verified only for a successful upgrade; newly stored hashes are Argon2id.
3. Login attempts are reserved atomically in database-backed IP/account and IP buckets over a 15-minute window. The default is 10 attempts per IP/account and 100 per IP, including successful attempts. Errors for invalid/missing/disabled accounts are generic. Throttling returns 429 and Retry-After.
4. Password verification/hashing runs outside the shared database writer lock. Login reloads account status and the original password hash under the short final transaction before issuing a session. Invitation acceptance similarly rechecks token, issuer authority, expiry, company/user status and membership before its atomic single-use commit.
5. The server issues a random session cookie and stores only its cryptographic hash. Session cookies are HTTP-only, host-only, SameSite=Lax and expire after 24 hours by default. Logout/replacement revoke the server session. JSON and browser storage contain no authentication token.
6. Production requires explicit HTTPS trusted origins at startup, uses Secure `__Host-` session/CSRF cookie names with Path=/ and no Domain, and refuses development invitations. Invalid production origin configuration fails closed.
7. Every protected request validates the session, active account, active company, active membership and current database grants. Workspace selection persists on the session, but it is not authorization. Optional `X-Company-ID` values are checked against active membership. The frontend sends only a validated in-memory workspace scope, captured before awaiting CSRF, so a workspace switch cannot redirect a pending form into another company.

Owner, Admin, Operator, Publisher and Viewer roles are initialized per company. Owner has all grants; Admin cannot manage custom grants/ownership as an owner; Operator manages agents/workflows; Publisher publishes; Viewer reads authorized resources. Custom roles are company-scoped. Non-owners cannot grant/change owner status or manage grants above their own authority. Built-in roles cannot be edited/deleted. Last-owner removal/demotion is rejected inside the governance transaction, including concurrent demotions.

Team invitations are hashed, expire after seven days, can be revoked and are accepted once. Existing users must sign in as the invited email; new users create their invited account through the secret link. A revoked or demoted issuer cannot use a pending invitation to restore old permissions. With no email backend configured, only explicitly enabled non-production development links are available; no email is claimed to have been sent.

## Tenant isolation and existing functionality

All agent and legacy list/detail/create/update operations use the validated company. Foreign guessed IDs return 404; switching a header/parameter to another company's ID returns 403. Client ownership fields cannot assign company/user identities. API and service checks apply to role grants, team settings, agent lifecycle/configuration, knowledge, publishing, legacy workflow execution and retries. Revocation is checked from the database on subsequent requests rather than embedded in a long-lived role token.

Legacy routing filters candidates and relationships before relevance scoring. New routing/delivery/interaction/comment records inherit validated ownership. Detail/history queries check both the record's owner and its linked resources, preventing contaminated older metadata from leaking. Original source/scoring/runner/timeout/error handling is retained. Legacy profile edits create versioned drafts preserving modern policy fields; deactivation pauses the account, and legacy activation cannot override disabled/archived controls.

Authenticated Historical pages retain dashboards, scenario publishing with an owned author, posts and attribution, routing explanations, notifications, interactions, comments and retries. Dashboard metrics are computed only for granted resource types. Existing Phase 2 builder, network publishing/discovery, direct/group conversations and worker paths remain available with permission-aware actions. Shared conversation/network access is not incorrectly reduced to same-company ownership.

New companies start empty. The five simulated business agents remain available as test/demo definitions; they are not treated as five legal company owners or silently seeded into every company. Existing populated databases retain their historical IDs and records through explicit migration mapping and operator-reviewed legacy access.

## Versioned APIs and frontend

Canonical, schema-documented endpoints use `/api/v1`; authenticated `/api` compatibility aliases are excluded from duplicate OpenAPI documentation. Core endpoints cover registration/login/logout/me/CSRF/workspace selection, account editing, companies/profile/settings, members, company invitations/preview/acceptance/revocation, roles and permission grants. Legacy resources live at `/legacy/agents`, `/posts`, `/demo/scenarios`, `/demo/run`, `/notifications`, `/interactions` and `/dashboard`, with the original useful schemas preserved. Interactive schemas are at `/docs`.

The existing UI/design is extended with onboarding, company identity/workspace selection, Team, Roles, Account and invitation acceptance. Buttons/navigation and dependent reads honor actual grants, while backend checks remain authoritative. Session/company switches, inaccessible resources and refreshed permissions clear private rendered views. Browser-only invitation links are shown once in development; referrer policy prevents leaking them through navigation referrers. There is no unrelated frontend or mock authentication.

## Exact test and build results

Final backend verification on 2026-11-15:

| Check | Result |
| --- | --- |
| `cd backend; ../.venv/bin/python -m pytest -q --tb=short` | **161 passed, 1 warning in 164.29s**, zero failures/errors. |
| Original regression coverage | 53 original agent/post/relevance/provider/notification/workflow cases preserved and adapted to real cookie authentication. |
| Foundation security | 26 cases, including Argon2/cookies/CSRF/origins/rate limits, two-company isolation, role grants, active statuses, expiry/revocation, invitation controls, concurrent last-owner protection, short writer locks and restricted session summaries. |
| Migration and operator tooling | 19 migration cases plus one explicit legacy-owner assignment case; populated copy preservation, backups/WAL, schema checks, FK/uniqueness, explicit mappings and owner assignment all pass. |
| Tenant-scoped legacy APIs | 10 cases for authenticated legacy modes, isolated routing/history/retry, owned public slugs, permissions and lifecycle/version synchronization. |
| Retained Phase 2 | 26 conversation/runtime plus 26 workspace/publishing cases pass through cookie-authenticated APIs. |
| Browser acceptance | Passed with two independent company accounts, real API/database state, **355 checked requests and 22 unsafe requests**, CSRF/HTTP-only-cookie checks, roles/invitations/revocation, scoped headers, workspace recovery, logout/login, historical pages and a measured 390px mobile viewport. Preserved Phase 2 cookie-session flow and redacted custom-role view also passed. |
| Frontend dependency audit | `npm audit --json`: **0 vulnerabilities**, exit 0. |
| Working database | Revision `0003_phase1`, 33 application tables, integrity `ok`, FK violations 0, users/companies/agents 0. |
| API schema | 60 canonical versioned paths documented; duplicate compatibility aliases omitted from OpenAPI. |
| Compilation/whitespace | Backend app/scripts/migrations compile and `git diff --check` pass. |

The one warning is Starlette's upstream httpx TestClient deprecation notice. No live provider calls or authentication overrides are used. The legacy fixtures register/login through the actual cookie API and explicitly create their owned demo definitions. Earlier integration failures were corrected; the final full run above has no failing acceptance tests. Independent security/migration/permission review reports no unresolved Critical or Important findings.

Final frontend verification:

- `npm test`: **Workspace domain checks passed; Session and permission checks passed; Company request scope checks passed**, exit 0.
- `npm run build`: **TypeScript `tsc --noEmit` passed; Vite 6.4.6 production build passed**, 1,674 modules, 5.33s. JavaScript 387.49KB (117.91KB gzip); CSS 38.21KB (9.21KB gzip).
- Final real-browser acceptance used a fresh isolated database and the stable backend. Responsive layout measured 390px for document/client/visual viewport with no overflow; no CSS workaround was needed for a background screenshot compositor artifact. Temporary acceptance API/Vite/Chrome processes were stopped.
- Session/workspace summaries with no `company.read` grant retain only appropriate membership/workspace metadata and omit restricted policy/settings content. Narrow legacy read grants work without an unrelated company-read prerequisite.

## Windows PowerShell commands

The complete commands are also in the [README](../README.md). With the project at `$HOME\Music\agentConnect`, terminal 1:

```powershell
Set-Location "$HOME\Music\agentConnect"
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\backend\requirements.txt
$env:AGENTCONNECT_ENV = "development"
$env:AGENTCONNECT_DATABASE_URL = "sqlite:///./data/agentconnect.db"
$env:AGENTCONNECT_TRUSTED_ORIGINS = "http://127.0.0.1:5173,http://localhost:5173"
$env:AGENTCONNECT_DEV_INVITATIONS = "true"
$env:AGENTCONNECT_ENABLE_FAKE = "true"
Set-Location .\backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Terminal 2:

```powershell
Set-Location "$HOME\Music\agentConnect\frontend"
npm ci
npm run dev
```

Open http://127.0.0.1:5173. Use development invitation links only locally. For a populated older database, stop writers and perform the reviewed mapping/backup/dry-run/apply steps in the migration guide before starting the app. Environment variables are exported explicitly; there is no silent `.env` loader. Production requires HTTPS origins and does not allow development invitation delivery.

## Manual two-company acceptance scenario

1. In browser profile A, register Company Alpha with a unique email and a password of at least 12 characters. Complete onboarding and create a private agent. Record its actual URL/ID.
2. In a separate browser profile or another browser, register Company Beta with different credentials. It should have its own empty workspace. Create Beta's agent and verify Alpha's agent is absent. Enter Alpha's known agent URL while signed in as Beta: it must be unavailable/404. Attempting Alpha's ID through update/delete or a forged workspace header must also fail.
3. As Alpha's owner, inspect Team and Roles. The initial Owner/Admin/Operator/Publisher/Viewer grants are visible. Create a custom role, or issue an explicit development Viewer invitation. Copy the one-time link; no email is sent.
4. In a fresh context, accept as the invited new email. The viewer can read Alpha's authorized resources but sees no company write controls. Direct create-agent, publish, settings or team writes return 403 even if manually submitted.
5. As Alpha's owner, invite the already registered Beta email. Beta must sign in with its existing credentials to accept. Beta now has two memberships; choose a workspace through the selector. Each view/creation stays under the selected validated company. Another user's company ID alone never grants membership.
6. Change the invited Beta membership to Publisher. Publishing is allowed; agent administration remains forbidden. Operator grants show the inverse agent/workflow versus publishing distinction. Only owners may grant/remove owner status; removing/demoting Alpha's final owner returns 409.
7. Revoke Beta's Alpha membership. Further Alpha resource requests fail immediately. Beta can explicitly recover to its still-authorized Beta workspace; no Alpha data should remain in the rendered view. A pending invitation issued by a now-revoked/demoted administrator must also fail acceptance.
8. Use Historical pages to publish a private legacy post with an owned agent, inspect routing/notifications/interactions and retry a permitted failed workflow. Foreign companies cannot read or retry those records. Existing demo scenarios remain selectable and require an owned author plus workflow/publishing permissions.
9. Sign out, verify protected APIs return 401, then sign in again. Refreshes use the cookie session; no session token is in localStorage or JSON. Verify mobile navigation/forms remain usable.

## Remaining limitations and unchecked paths

- No required acceptance test remains failing in the final verified result. One upstream Starlette/httpx TestClient deprecation warning is reported rather than hidden.
- The verified migration/backup runner currently supports SQLite only. PostgreSQL URL/driver configuration is prepared, but PostgreSQL backup/restore/migration execution is explicitly refused until reviewed; no production PostgreSQL deployment or load test was run.
- Windows PowerShell commands are supplied, but verification ran on Linux; Windows was not available to execute them directly.
- Outbound email is not configured. Production invitation creation explicitly returns 503. The implemented alternative is a development-only link, as requested, not a simulated successful email.
- Live Gemini was not called. Automated provider/workflow tests use deterministic adapters or safe missing-key behavior. This foundation work did not replace the existing provider abstraction.
- Previously authorized viewers may already hold copies of data they read; revocation prevents further server access and refreshes the UI, but cannot retract external copies. Database backups contain source data and require normal access protection.
- Existing Phase 2 text-only knowledge retrieval and lexical output screening limits remain unchanged. No new agent engine was built as part of this Phase 1 task.

## Current working-tree inventory

The inventory below is generated from Git status after implementation. It includes earlier uncommitted Phase 2 files retained in the checkout; ignored environments, database backups, browser test data and build outputs are excluded. Changes are left uncommitted for review.

```text
 M .gitignore
 M README.md
 M backend/.env.example
 M backend/app/adapters/gemini.py
 M backend/app/db/models.py
 M backend/app/main.py
 M backend/app/services/agent_runner.py
 M backend/app/services/notification_service.py
 M backend/app/services/post_service.py
 M backend/app/services/routing_service.py
 M backend/requirements.txt
 M backend/tests/conftest.py
 M backend/tests/test_database.py
 M backend/tests/test_day2_workflow.py
 M frontend/.env.example
 M frontend/index.html
 M frontend/package-lock.json
 M frontend/package.json
 M frontend/src/App.tsx
 M frontend/src/api/agents.ts
 M frontend/src/api/client.ts
 M frontend/src/api/interactions.ts
 M frontend/src/api/posts.ts
 M frontend/src/components/common/UI.tsx
 M frontend/src/components/layout/AppLayout.tsx
 M frontend/src/components/posts/DemoButton.tsx
 M frontend/src/components/posts/PostCard.tsx
 M frontend/src/components/posts/PublishPostDialog.tsx
 M frontend/src/hooks/useApiData.ts
 M frontend/src/pages/AgentDetails.tsx
 M frontend/src/pages/Agents.tsx
 M frontend/src/pages/Feed.tsx
 M frontend/src/pages/Interactions.tsx
 M frontend/src/pages/Notifications.tsx
 M frontend/src/pages/Overview.tsx
 M frontend/src/pages/PostDetails.tsx
 M frontend/src/styles.css
?? backend/alembic.ini
?? backend/app/api/conversations.py
?? backend/app/api/foundation.py
?? backend/app/api/legacy.py
?? backend/app/api/workspace.py
?? backend/app/db/migrations.py
?? backend/app/db/network.py
?? backend/app/schemas/foundation.py
?? backend/app/schemas/network.py
?? backend/app/services/administration.py
?? backend/app/services/conversations.py
?? backend/app/services/legacy.py
?? backend/app/services/locking.py
?? backend/app/services/publishing_runtime.py
?? backend/app/services/runtime.py
?? backend/app/services/security.py
?? backend/app/services/team.py
?? backend/app/services/workspace.py
?? backend/app/worker.py
?? backend/migrations/env.py
?? backend/migrations/versions/0001_day2.py
?? backend/migrations/versions/0002_phase2.py
?? backend/migrations/versions/0003_phase1.py
?? backend/requirements-postgres.txt
?? backend/scripts/assign_legacy_owner.py
?? backend/scripts/migrate.py
?? backend/tests/auth_helpers.py
?? backend/tests/test_conversations_runtime.py
?? backend/tests/test_legacy_owner.py
?? backend/tests/test_legacy_tenants.py
?? backend/tests/test_migrations.py
?? backend/tests/test_security_foundation.py
?? backend/tests/test_workspace.py
?? docs/PHASE1_REPORT.md
?? docs/PHASE2_REPORT.md
?? docs/legacy-mapping.example.json
?? docs/migrations.md
?? docs/phase1-contract.md
?? docs/phase2-contract.md
?? docs/superpowers/plans/2026-11-14-phase2.md
?? frontend/scripts/check-domain.mjs
?? frontend/src/workspace/Access.tsx
?? frontend/src/workspace/Administration.tsx
?? frontend/src/workspace/Agents.tsx
?? frontend/src/workspace/Conversations.tsx
?? frontend/src/workspace/History.tsx
?? frontend/src/workspace/JoinInvitation.tsx
?? frontend/src/workspace/Publications.tsx
?? frontend/src/workspace/Session.tsx
?? frontend/src/workspace/Workspace.tsx
?? frontend/src/workspace/access.ts
?? frontend/src/workspace/api.ts
?? frontend/src/workspace/common.tsx
?? frontend/src/workspace/domain.ts
?? frontend/src/workspace/types.ts
```
