# Phase 1 implementation contract and ledger

User authorized direct implementation of secure company foundation in the existing checkout, preserving all existing Phase 2 work and historical demo functionality. Do not touch .sf, .dist or unrelated projects. The default backend/data directory contains no database; no working database has been reset or overwritten.

## Implementation choices

- Extend existing Company/User/CompanyMember/LoginSession models rather than replacing identities. Alias CompanyMembership and AuthSession for public terminology. Add company roles, permissions, grants, settings and invitations.
- Replace browser bearer tokens with Argon2id and opaque HTTP-only cookie sessions. Never return session tokens in JSON or save them in browser storage. Existing PBKDF2 hashes are verified only to upgrade to Argon2id on successful login; existing sessions are revoked by the migration.
- CSRF: GET /api/v1/auth/csrf sets a readable host-only CSRF cookie and returns {csrf_token}; every unsafe cookie request, including login/register, requires matching X-CSRF-Token plus matching session-bound hash after login. Reject disallowed Origin. Cookie production mode requires Secure, SameSite=lax, Path=/, no Domain and __Host- names. Production origins explicitly configured. Backend permission checks are authoritative.
- Versioned routes /api/v1, keeping authenticated /api aliases for Phase 2 callers during transition. Frontend uses /api/v1. GET /auth/me returns user, companies with own role+permissions, selected_company_id, csrf_token. A selected company is validated against active membership for every request. Workspace selection POST /auth/workspace {company_id} persists in session; optional X-Company-ID is always checked, never trusted.
- Preserve deterministic relevance/adapter/runner modules. Expose legacy posts/demo/notifications/interactions through tenant-scoped, permission-checked product routes and a dashboard, preserving IDs and historical relationships.

## API shapes

Auth registration input remains {company_name,name,email,password,company_slug?}; response {user:{id,email,name,status,created_at,last_login_at}, companies:[CompanySummary], selected_company_id, csrf_token}; login input {email,password}. No `token` field. POST /auth/logout revokes and clears cookies. GET /auth/csrf works anonymously. HTTP 401 generic auth failures, 429 throttling with Retry-After, 403 insufficient permission/CSRF, 404 foreign resource IDs.

CompanySummary: {id,name,slug,status,created_at,updated_at,network_opt_in,policy,policy_version,role,role_id,permissions:string[],settings:{description,website,industry,onboarding_complete}}.

- GET/POST /companies {name,slug?}; GET/PATCH /companies/{id}; GET/PATCH /companies/current (accept existing network_opt_in/policy plus name/slug); GET/PUT /companies/current/settings {description?,website?,industry?,onboarding_complete?}; GET/PATCH /account {name?}.
- GET /members -> [{id,user_id,email,name,status,role,role_id,created_at}]; PATCH /members/{id} {role_id}; DELETE /members/{id} revokes. Only owners may grant/remove/demote owner memberships; never last owner. A revoke removes future access immediately.
- GET/POST /company-invitations; POST {email,role_id}; return {id,email,role_id,role,status,expires_at,delivery:'development_link'|'not_configured',development_token?:string}. Default no delivery means503 unless explicit AGENTCONNECT_DEV_INVITATIONS=true AND nonproduction; never pretend mail sent. GET list never returns token. POST /company-invitations/{id}/revoke.
- POST /company-invitations/accept {token,name?,password?}; cookie-authenticated existing user must match normalized invited email, otherwise registering invited new user requires name+12char password; atomically single-use+expiry; issues fresh cookie session and selects company. GET /company-invitations/preview?token=... -> {company_name,email,expires_at,role}; no private company data.
- GET /permissions -> [{key,description}]; GET/POST /roles; POST {name,permissions:string[]}; PUT /roles/{id} {name,permissions}; DELETE /roles/{id}. Builtin roles immutable; custom roles company-scoped and assignable. Only owners/roles.manage may manage custom grants; members.manage cannot grant owner unless actor is owner. Last-owner invariant serialized under database mutex.

## Permission catalog and initial roles

company.read, company.update, settings.manage, members.read, members.manage, invitations.manage, roles.read, roles.manage, agents.read, agents.manage, knowledge.read, knowledge.manage, posts.read, posts.publish, workflow.run, discovery.read, conversations.read, conversations.manage, approvals.manage.

Owner: all. Admin: all except roles.manage (ownership changes still owner-only). Operator: company.read,members.read,roles.read,agents.read,agents.manage,knowledge.read,knowledge.manage,posts.read,workflow.run,discovery.read,conversations.read,conversations.manage,approvals.manage. Publisher: company.read,members.read,roles.read,agents.read,knowledge.read,posts.read,posts.publish,discovery.read,conversations.read. Viewer: company.read,members.read,roles.read,agents.read,knowledge.read,posts.read,discovery.read,conversations.read.

## Models added/extended (root owns models)

Company: slug unique, status active|suspended, updated_at. User: status active|disabled, created_at,last_login_at. CompanyMember: role_id optional FK for legacy transition, status active|revoked, created_at,revoked_at; retain role string for backwards compatibility but grants resolve via company-scoped role_id. LoginSession: csrf_token_hash, selected_company_id, created_at, revoked_at. CompanyRole: id,company_id,name,slug,is_builtin,created_at; unique(company_id,slug), unique(id,company_id). Permission: key primary key,description. RolePermissionGrant: role_id+permission_key composite PK. CompanySettings: company_id primary key,description,website,industry,onboarding_complete,updated_at. CompanyInvitation: id,company_id,email,role_id,token_hash unique,status,created_by,expires_at,created_at,accepted_at,revoked_at. LoginRateLimit: key hashed primary key,window_started_at,attempts.

Root will add intrinsic company_id columns to legacy Agent, Post, Notification, RoutingDecision, AgentInteraction and Comment, nullable only at model declaration for legacy fixture compatibility, migrations populate all existing rows and tenant APIs enforce ownership. AgentAccount uses company-scoped identity; new legacy agents are created with matching intrinsic company_id. Cross-company conversation and network Publication retain their explicit access rules.

## Work split

Root: models, Argon2/session/CSRF/rate limiting, RBAC/team service+routes, all Phase 2 endpoint permission gates, fixture/auth migration, final integration/tests/report.
Migration implementer: Alembic frozen baseline + upgrade of existing Day2 or current Phase2 databases, explicit legacy mapping, SQLite backup/verify/dry-run tool and migration acceptance tests. Own migrations and related script/tests only. No working DB mutation before copy tests.
Frontend implementer: cookie/CSRF client, role-aware shell/actions, onboarding/settings, team/invitations/roles/account and secure session/workspace selection; legacy dashboard integration after backend contract lands. Own frontend only.
Legacy implementer: authenticated company-scoped existing demo API/service and regression API tests; reuse existing runner/relevance/adapters. Own api/legacy.py, services/legacy.py, tests/test_legacy_tenants.py. Router prefix /api, root mounts at /api/v1 alias. Consume security current_principal, require_permission(db,principal,key); returns Principal with user,company,token_hash, role and permissions (role/permissions optional metadata; gate fresh DB checks).

## Verification

Failing tests first for cookie/CSRF/session/status/rate-limit behavior, independent tenants, all roles, immediate revocation, invitation expiry/single-use, last-owner and role escalation boundaries. Migration tests compare complete preserved historical rows and PRAGMA checks across upgrade on a copy, never a reset. Full suite, frontend type/build/domain checks, real browser company/team flows, independent security/migration review. Report Windows PowerShell setup and manual two-company steps. No live model calls.

## Progress

- Inspected existing Phase 2 checkout. No default working SQLite file exists. Existing implementation has no Alembic, team invitations or full RBAC; browser bearer sessions/PBKDF2 need upgrading.
- Implemented cookie/Argon2id/CSRF/rate-limited sessions, fresh DB grants, roles/team/settings/invitations and validated workspace selection; retained Phase 2 APIs with current permission/status guards.
- Preserved/authenticated the original demo pipeline and private history; existing tests now use actual cookie login/CSRF, not mock authentication.
- Frozen 3 Alembic revisions and verified copy-first/backup mapping runner; original working DB absent, later empty placeholder backed up and safely initialized (33 application tables, no user/company/agent data). Local reviewed owner-assignment command is separate from HTTP and backs up first.
- Fixed review findings: expensive password work now outside shared writer locks with final revalidation; stale invitation authority, reserved legacy namespace, empty updates and narrow-role summary redaction have regression coverage.
- Final backend suite: 161 passed, 1 upstream deprecation warning, 164.29 seconds. Frontend domain/session/scope checks and TypeScript/Vite build pass (1,674 modules, 5.33 seconds). Real browser two-company/team/role/revocation and retained Phase 2 cookie flows pass; temporary processes stopped. Dependency audit zero vulnerabilities. Final report `docs/PHASE1_REPORT.md` includes PowerShell commands, manual scenario, database proof and limitations.
