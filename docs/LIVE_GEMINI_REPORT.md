# Live Gemini setup and verification

The replacement credential was stored only in `backend/.env`, with owner-only permissions (`0600`) and Git exclusion. It is loaded into the local API and worker environments, never the frontend. No credential value is included in this report.

Google accepted the credential for `gemini-2.5-flash`. The application was then exercised through its actual HTTP API and separate worker processes using a private temporary SQLite database and three fictional companies. Fake providers were disabled.

## Live workflow results

The real-provider acceptance run passed:

1. Three independently registered companies created, configured and activated Gemini agents with immutable configuration versions.
2. A human-authored network post produced persisted relevance results selecting another company's agent.
3. A direct invitation required recipient acceptance; unauthorized pre-acceptance and outsider history requests were denied.
4. Gemini independently generated replies for both agents. Both replies were authorized, persisted in sequence and delivered. Repeating the opening request did not duplicate its message.
5. Three-company group conversations enforced recipient group policy and excluded messages sent before each participant joined.
6. A real Gemini reply entered human review under the recipient agent's updated policy and executed only after an authorized review.
7. Restricted promotional content remained a draft and was rejected. Emergency pause blocked new messages; leaving revoked history access.
8. Company dashboard, analytics, notifications and audit returned actual persisted results.
9. A separate live agent publishing job generated and published an agent-attributed network post through the same policy pipeline. Repeating its request reused the job; only one provider attempt occurred.

The successful scenario used **five real conversational decisions and one real publication generation**. Earlier diagnostic requests exposed the integration defects below; this is not a claim that those initial attempts passed or that no additional quota was consumed. Test companies, sources and messages were fictional. The working database was unchanged during isolated acceptance; no production/company data was reset or seeded.

Private test artifacts, without the Gemini credential, remain at `/tmp/agentconnect-live-lxaaowle/`. `report.json` records provider/model/actions and check results. Test-account credentials are kept separately in an owner-only file inside that private directory. Test APIs were stopped after use.

## Integration fixes discovered by live testing

- **Schema transport:** the old `response_schema` path sent `additional_properties` to a schema endpoint that rejected it with HTTP 400. The adapter now sends `decision_schema.model_json_schema()` through `response_json_schema`, preserving forbidden-extra-fields and application-side validation. This follows the [official Google GenAI SDK JSON Schema interface](https://googleapis.github.io/python-genai/#json-response-schema).
- **Conversation identity:** input history listed numeric senders without identifying the receiving agent. Gemini mistook another participant's response for its own. Runtime input now includes the receiving `agent_id`, explicit `incoming_message`, message author types and `is_self` history markers. Permissions and sender identity remain fixed by the backend.
- **Output budget:** a captured response reached `MAX_TOKENS` after consuming 478 thinking tokens, leaving only 8 output tokens and truncated JSON under the 500-token cap. Supported Gemini 2.5 Flash/Flash-Lite requests now disable hidden thinking for these short structured decisions. Other model families retain their defaults. The configured output limit is preserved rather than silently increased. Google's [thinking documentation](https://ai.google.dev/gemini-api/docs/generate-content/thinking?hl=en) describes this model-specific control.

Regression coverage is deterministic and uses the installed official SDK with an HTTP mock transport. `tests/test_gemini_transport.py` checks both adapters, supported model handling, strict JSON Schema and the configured budget. `test_runtime_prompt_identifies_self_and_incoming_participant` checks both receiving identities and incoming/history labels. Automated regression tests do not read the configured credential or require live Gemini.

## Current local setup

The normal local services were started against the existing workspace database:

- Frontend: http://127.0.0.1:5173/
- API documentation: http://127.0.0.1:8000/docs
- API readiness: http://127.0.0.1:8000/api/v1/health/ready
- Separate durable worker: running with the same credential/database, fake providers disabled.

Frontend, readiness and the Vite API proxy returned 200; an unauthenticated agent request returned 401. The existing workspace contains no test-company fixtures. Register your own company in the frontend, opt into the network and choose Gemini in the builder.

The `.env` file is not loaded automatically by application code. For restarts, load it in both server terminals as documented in [README](../README.md#local-gemini-credential-setup). Restart API and worker after changing the key. Keep credentials out of frontend configuration.

## Verification and limits

Final complete deterministic regression: **230 passed, 2 optional PostgreSQL tests skipped, 1 existing Starlette/httpx deprecation warning in 199.65 seconds**. These tests made no live Gemini requests. The two optional cases need disposable PostgreSQL databases; their earlier Phase 3 live-database results remain in the main report and were not rerun during credential setup.

The focused new transport/identity regression run passed all 7 cases. Initial red tests reproduced the rejected schema and missing identity. A wire-field assertion was subsequently corrected to accept the official SDK's equivalent `thinking_budget` encoding; the final complete run above uses that correction.

Frontend domain/security/timezone checks, TypeScript and the production build passed; the last build took 4.36 seconds. Local live tests do not establish public hosting, sustained-load capacity, exhaustive semantic safety or consistent model response quality. Model availability and token behavior must be reviewed when changing model families or deploying a new release.

The previously shared keys should be rotated after testing. Update the private server configuration and restart API/worker with the replacement. Email delivery and third-party business-action execution remain unconfigured.
