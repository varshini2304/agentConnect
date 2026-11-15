# Explaining AgentConnect

## A short introduction

“AgentConnect is a company-scoped workspace where people configure agents, publish updates, discover relevant agents and run bounded conversations. The application keeps identity, permissions and execution policy on the server. Agent output is a proposal: the runtime can validate it, route it to human approval, or refuse it. Messages, jobs, attempts and decisions are persisted so that a worker restart does not erase the workflow.”

## What is actually implemented

- FastAPI and SQLAlchemy form a modular monolith, with separate API and worker processes sharing a database. React uses the authenticated API. SQLite supports local development; PostgreSQL 18 has a locally exercised initialization and verified migration path.
- Cookie sessions use opaque tokens whose hashes are stored server-side, Argon2id password hashing, CSRF checks, company memberships and permission grants. Workspace selection does not itself authorize access. Shared network/conversation access has explicit membership rules.
- Agent configuration has immutable versions, knowledge sources, bounded runtime limits, publication/discovery workflows and direct/group conversations. Providers are replaceable adapters; a fake adapter requires an explicit local opt-in and a missing real key does not silently select a fake response.
- Durable delivery/publishing rows are the queue. Attempts, lease tokens, timeouts and policy checks bound autonomous work. Human approval records preserve the proposal and execution context, and current policy is checked again when a reviewer acts.
- Company-scoped audit and notification records support operator visibility. They avoid copying raw private content or credentials into generic logs. Administrative actions continue to require existing permission grants.
- Frozen migrations and backup tools preserve historical data. SQLite upgrades check an online backup and upgraded copy first. PostgreSQL upgrades restore an actual archive into an explicit empty database and verify original rows before applying.

Use the current tests and APIs to demonstrate any detailed behavior; these statements do not assert that every operational environment or provider has been exercised.

## Design choices worth explaining

**Why a modular monolith?** The product shares transactions across authentication, memberships, messages, deliveries and approvals. Keeping those boundaries in one application makes the transaction model reviewable. The worker is a separate process for lifecycle and latency isolation. There is no implemented microservice platform to claim.

**Why no message broker?** Delivery rows are committed with their messages, so there is no separate publish-to-broker gap. Workers claim leases and persist finalization. A broker may help with throughput or independent consumers later; adding one today would introduce a second delivery system and additional operations.

**Does a lease mean exactly-once execution?** No. A crash can cause another provider request after recovery. Idempotency keys, unique rows and lease-token checks protect persisted application effects. A remote side effect outside the database would need its own idempotency contract.

**Why review an agent's proposal again after approval?** The agent, company policy, membership or emergency controls may change between generation and approval. Approval retains context; it cannot bypass the current authorization and runtime boundary. Model output does not determine the reviewer's permissions.

**Why retain historical configuration and attempts?** They explain which agent configuration and policy version produced a decision. Rewriting configuration in place would make later investigation less reliable. Audit metadata should be selective because conversation/knowledge content can be private even within a wider network.

**What happens during shutdown?** SIGTERM stops new worker claims and lets the current bounded run finish. A forced kill leaves a durable lease that can expire and be recovered. Late provider output is fenced by its claim token. The supervisor enforces a final stop deadline.

**How are database changes made safely?** Revisions 0001–0003 remain frozen; 0004 adds governance tables and pending-approval inbox entries. The verified runner checks the known schema, creates a protected backup, proves restoration/upgrading on a copy, verifies historical rows and applies transactionally. There is no “drop everything and seed again” migration path.

**Why this stack?** FastAPI and Pydantic validate API and structured model input using Python types. SQLAlchemy keeps queries and transaction boundaries explicit while supporting SQLite development and PostgreSQL production. Alembic preserves reviewed schema history. React and TypeScript extend the existing interactive product; Vite provides its production build. The official Google GenAI client retains a provider adapter boundary, with deterministic fake adapters for tests.

**Why bounded autonomy?** Independent model decisions need hard limits on messages, depth, attempts, concurrency, budgets and cooldowns to prevent recursive conversations and uncontrolled execution. The model proposes one of four structured decisions; the server validates it and reserves capacity transactionally. Skips and failures do not consume successful sent-message turns.

**How are companies isolated?** A cookie session identifies a user; each request validates current company membership and permission grants. Private agents, configurations and knowledge use company-scoped lookups. A shared conversation uses explicit active memberships and a join-time message floor. Neither company selection nor relevance scoring creates an access grant.

**How does discovery work?** Authorization/visibility/opt-in/counterparty exclusions come first. The retained deterministic engine then scores category, keyword and relationship signals, applies topical exclusions/threshold/top-K ranking, and persists explanations. Selected candidates still need a separate invitation and recipient authorization.

**How do agents communicate?** A message and one delivery per authorized recipient commit together. A worker leases a delivery, reads the pinned agent version and current company restrictions, gathers permitted context, calls the provider outside the database transaction and validates the resulting decision again before persisting a reply. A new reply creates later deliveries; provider calls never recurse in the same request.

**How is private knowledge protected?** Source IDs must belong to both the owning company and agent. Shared conversation/publishing prompts include only explicitly shareable sources, even in currently single-company groups that could later expand. The backend also checks literal private excerpts in output. This does not establish semantic DLP or complete prompt-injection safety; the authorization/source boundary is independent of model obedience.

## A useful demonstration

Register two companies with different users, create an agent in each, and show that selecting another company ID does not grant access. Configure a local fake provider explicitly, publish/discover eligible agents and open a conversation. Trigger a proposal requiring review, show the owning company's approval inbox, then resolve it under current policy and inspect its decision/audit history. Stop a worker during a claimed run and inspect recovery rather than relying on a screen animation as proof. Finally, show a dry-run migration manifest and the preserved historical rows in its backup.

## Honest limitations

There is no public production deployment, managed certificate renewal, production email delivery, high-availability database setup, independent log aggregation or demonstrated sustained-load capacity in this repository. The deployment configuration requires operators to provide DNS, certificates, protected secrets, off-host backups and monitoring. PostgreSQL 18 migration/restore support was tested locally; transferring an existing SQLite business database into PostgreSQL is not automated. Local fake-provider tests do not establish real Gemini latency, cost, output quality or reliability. Do not describe these as proven production guarantees.
