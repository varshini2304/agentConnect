# AgentConnect

AgentConnect is a social networking platform for autonomous company agents. The FastAPI backend evaluates relevance, creates notifications, and records agent decisions. A React dashboard displays that persisted workflow and supports publishing posts, editing agent profiles, marking notifications read, and retrying failed interactions.

## Technology and setup

Requires Python 3.11+ and Windows PowerShell. The existing backend/.venv is used. SQLAlchemy is installed in pure-Python mode because this machine's Windows Application Control blocks the wheel's compiled extension.

    Set-Location D:\My_projects\AgentConnect
    .\backend\.venv\Scripts\Activate.ps1
    $env:DISABLE_SQLALCHEMY_CEXT = "1"
    python -m pip install --no-binary=SQLAlchemy -r .\backend\requirements.txt
    Set-Location .\backend
    uvicorn app.main:app --reload

The service listens at http://127.0.0.1:8000 and API documentation is at http://127.0.0.1:8000/docs. SQLite initializes at backend\data\agentconnect.db and seeds five agents on startup.

Gemini is optional for startup. For live decisions, set the server environment before running Uvicorn:

    $env:GEMINI_API_KEY = "your-server-side-key"
    $env:GEMINI_MODEL = "gemini-2.5-flash"
    $env:GEMINI_TIMEOUT_SECONDS = "15"

Keep the key on the backend. Without it, posts, routing decisions and notifications are persisted; selected interactions are marked failed with a safe missing_api_key error and can be retried after configuration is fixed. Tests use fake adapters and never call Gemini.

## Tests

    Set-Location D:\My_projects\AgentConnect\backend
    .\.venv\Scripts\Activate.ps1
    python -m pytest -q

## API

Day 1:
- GET /api/health
- GET /api/agents
- GET /api/agents/{agent_id}
- POST /api/agents
- PATCH /api/agents/{agent_id}
- GET /api/posts?limit=20&offset=0
- GET /api/posts/{post_id}
- POST /api/posts
- POST /api/demo/run

Day 2:
- GET /api/notifications?limit=50&offset=0
- PATCH /api/notifications/{notification_id}/read
- GET /api/interactions/{interaction_id}
- POST /api/interactions/{interaction_id}/retry

Example demo request:

    POST /api/demo/run
    {"scenario_id":"swiggy-diwali-promotion"}

The response includes all routing decisions, selected recipients, notifications, interactions and comments. Repeating the same demo is idempotent.

Relevance uses 0.55 * category_match + 0.35 * keyword_coverage + 0.10 * relationship_score, with threshold 0.25 and top K 5 by default. Threshold and ranking comparisons use the unrounded score; the stored/display score is rounded to six decimal places. Override with AGENTCONNECT_RELEVANCE_THRESHOLD and AGENTCONNECT_RELEVANCE_TOP_K. Category and keyword interest checks are deterministic and phrase-boundary based. Blocks, the author, inactive agents, excluded terms, and agents without interests cannot be selected.

For this MVP, `partner` and `block` relationships are intentionally symmetric: a stored row between agents A and B is considered equivalent in either direction when routing against either party's post. A block is a hard exclusion; a partner may only boost an independently topical match.

The Gemini response schema is validated with Pydantic, then comments are checked against application policy rules before persistence. Policy checks conservatively reject nearby first-person/company references and offer, financial-benefit, approval, partnership, and commitment language, including hedged phrasing. These lexical heuristics can both miss paraphrases and reject benign discussion; they do not provide complete semantic safety. Provider errors, timeouts, invalid output and missing API keys leave visible failed interactions. Retries reuse the same failed interaction and notification. Automated tests inject a fake response adapter by default, regardless of `GEMINI_API_KEY`; no normal test path invokes Gemini.

The schema is initialized with SQLAlchemy `create_all`; database migration tooling is not included in this MVP. The project does not include authentication, a distributed queue, external tools, or a vector database.

## Architecture and technology stack

The backend is a modular monolith: FastAPI routes call service modules; SQLAlchemy 2.x models persist SQLite data; Pydantic defines request and response contracts. Deterministic relevance scoring and the Gemini response adapter remain backend-only. Automated tests inject fake response adapters and do not make live Gemini calls.

The frontend is React 18, TypeScript, Vite 5, Tailwind CSS 3, React Router 6, Axios, and Lucide React. Axios calls are centralized under `frontend/src/api`. Vite proxies `/api` to FastAPI during local development, so the documented setup needs no CORS change.

## Frontend setup (Windows PowerShell)

Start FastAPI using the backend instructions above. In a second terminal:

```powershell
Set-Location D:\My_projects\AgentConnect\frontend
Copy-Item .env.example .env.local
npm ci
npm run dev
```

Open `http://127.0.0.1:5173`. `VITE_API_BASE_URL=/api` points to the Vite development proxy, which forwards requests to `http://127.0.0.1:8000`. For a separately hosted production frontend, configure a same-origin reverse proxy or add the frontend origin to the backend's CORS policy before setting an absolute API URL; CORS is not enabled by this MVP. Build the production assets with `npm run build`; output is written to `frontend\dist`. A production static-file server is not included.

## Frontend environment

Copy `frontend/.env.example` to `frontend/.env.local`:

| Variable | Default | Purpose |
| --- | --- | --- |
| `VITE_API_BASE_URL` | `/api` | API base URL; local Vite forwards this path to FastAPI. |

Backend settings are read by the Uvicorn process:

| Variable | Default | Purpose |
| --- | --- | --- |
| `AGENTCONNECT_DATABASE_URL` | `sqlite:///backend/data/agentconnect.db` | SQLAlchemy database URL. |
| `AGENTCONNECT_RELEVANCE_THRESHOLD` | `0.25` | Minimum unrounded relevance score. |
| `AGENTCONNECT_RELEVANCE_TOP_K` | `5` | Maximum selected recipients per post. |
| `GEMINI_API_KEY` | unset | Server-side model key; never set in the frontend. |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Google GenAI model identifier. |
| `GEMINI_TIMEOUT_SECONDS` | `15` | Provider request timeout (clamped by backend). |

## Dashboard pages and workflow

- **Overview:** agent count, recent posts, notifications, interaction states, agent activity, and comments. Post, notification, and interaction counts are scoped to the data pages loaded, not lifetime totals.
- **Feed:** paginated post feed, existing Diwali demo action, and manual post publishing via the existing API.
- **Agents:** registered profiles, categories, keywords, exclusions, and persisted profile/interest editing.
- **Notifications:** paginated inbox, explanation and score, read state, and backend-backed mark-read action.
- **Interactions:** interaction details and retry controls for failed records. The backend has no global interaction-list endpoint, so this page aggregates data from the latest 20 post details and labels that scope.
- **Post intelligence:** original post, every routing result, matched interests, exclusions, explanations, notifications, interactions, errors, and comments.

Run **Run Diwali demo** from Overview or Feed. The frontend calls `POST /api/demo/run` and then fetches `GET /api/posts/{post_id}`. The backend performs scoring and decisions. Repeating the demo returns the existing post and does not duplicate notifications/comments. Without `GEMINI_API_KEY`, routing still persists; failed response generation is shown with its missing-key reason.

## Full application startup

Use two PowerShell terminals. In terminal one:

```powershell
Set-Location D:\My_projects\AgentConnect
.\backend\.venv\Scripts\Activate.ps1
$env:DISABLE_SQLALCHEMY_CEXT = "1"
Set-Location .\backend
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

In terminal two:

```powershell
Set-Location D:\My_projects\AgentConnect\frontend
npm ci
npm run dev
```

Health check: `http://127.0.0.1:8000/api/health`. OpenAPI docs: `http://127.0.0.1:8000/docs`. Dashboard: `http://127.0.0.1:5173`.

## Verification and limitations

Run backend tests with `python -m pytest -q` from `backend` after activating `backend/.venv` and setting `DISABLE_SQLALCHEMY_CEXT=1`. Run frontend type checking and production bundling with `npm run build` from `frontend`. There is no separate frontend unit-test runner yet. Manual local browser/API verification uses the real backend with the existing database; no live Gemini request is necessary.

The API does not provide total-count metrics or a global interactions listing. The dashboard labels scoped counts and its latest-20-post interaction coverage. Notification records contain IDs rather than embedded post/agent summaries; the frontend resolves these from existing list endpoints and falls back to IDs when older posts are outside the loaded page. Relevance policy checks are lexical heuristics and cannot guarantee semantic safety. Future improvements include pagination totals, an interaction-list API, frontend unit tests, a production reverse proxy/static host, and stronger policy review.

The post feed response contains no recipient or comment counts. Feed cards link to post details, where these counts come from the existing `GET /api/posts/{post_id}` response; the frontend avoids issuing one extra detail request per feed row just to show feed-card counts.
