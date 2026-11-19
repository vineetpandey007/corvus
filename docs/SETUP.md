# Setup Guide

Two ways to run this: **local (no Docker)** for development, or **Docker
Compose** for a one-command full stack with persistent Neo4j. Both are
covered below.

## Prerequisites

- Python 3.10+
- Node.js 18+ (for the `frontend/` dashboard)
- Docker + Docker Compose (only if using the Docker path)

---

## Option A — Local Setup (no Docker)

### 1. Backend

```bash
cd dark-web-deanonymization
python -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate

pip install -r requirements.txt
python -m spacy download en_core_web_sm
```

### 2. Required Secrets

```bash
cp .env.example .env
```

Two secrets are **required** before the API will run — generate and paste
them into `.env`:

```bash
# JWT_SECRET_KEY
python -c "import secrets; print(secrets.token_urlsafe(32))"

# ENCRYPTION_KEY
python -c "from src.utils.encryption import generate_key; print(generate_key())"
```

Everything else in `.env.example` is optional (see the table below).

| Variable | Purpose | Required? |
|---|---|---|
| `JWT_SECRET_KEY` | Signs analyst session tokens | **Yes** |
| `ENCRYPTION_KEY` | Encrypts case post text at rest | **Yes** |
| `DATABASE_URL` | Defaults to a local SQLite file | No — set for Postgres in production |
| `API_SERVICE_KEY` | Enables `X-API-Key` service auth | No |
| `BLOCKEXPLORER_API_KEY` | Etherscan key for Ethereum tracing | No — Bitcoin tracing works without any key |
| `NEO4J_URI` / `NEO4J_USER` / `NEO4J_PASSWORD` | Only if `config.yaml -> graph.backend: neo4j` | No |
| `TOR_SOCKS_PROXY` | Only for real, authorized live collection | No |
| `EMAIL_BACKEND` | `dev` (default, logs to console/file) or `smtp` — see `.env.example` for SMTP_* vars | No |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Enables "Continue with Google" | No — button shows a clean error until set |
| `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` | Enables "Continue with GitHub" | No — same |
| `BACKEND_BASE_URL` | Used to build the OAuth redirect URI | No — defaults to `http://localhost:8000` |

**Setting up Google/GitHub login** (optional):
- **Google**: [console.cloud.google.com](https://console.cloud.google.com) → APIs & Services → Credentials → Create OAuth client ID (Web application) → Authorized redirect URI: `http://localhost:8000/auth/oauth/google/callback`
- **GitHub**: [github.com/settings/developers](https://github.com/settings/developers) → OAuth Apps → New OAuth App → Authorization callback URL: `http://localhost:8000/auth/oauth/github/callback`

Paste the resulting client ID/secret pairs into `.env`. No restart-order
dependency — the login buttons work the moment the API picks up the new
`.env` values.

### 3. Run the API

```bash
uvicorn src.api.main:app --reload --port 8000
```

Visit `http://localhost:8000/docs` for interactive Swagger docs. On first
run, tables are created automatically (SQLite file at
`data/processed/app.db`).

### 4. Create Your First Account

Either register from the dashboard's `/register` page (once the frontend
is running — step 6), or via curl:

```bash
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username": "analyst01", "password": "ChangeThisPassword123!"}'
```

This returns a JWT you can use immediately, or log in again later via
`POST /auth/login`. To create an **admin**-role account instead (self-
registration always creates an `analyst`-role account by design — see the
TODO in `src/api/routes/auth.py`):

```bash
python scripts/create_admin.py --username admin --password "ChangeThisPassword123!"
```

### 5. Run the Demo Pipeline (no auth/DB needed)

```bash
python scripts/run_pipeline.py --input data/sample/sample_posts.json
```

Runs the correlation pipeline standalone and writes a JSON + PNG graph to
`data/processed/`.

### 6. Run the Frontend Dashboard

```bash
cd frontend
npm install
npm run dev
```

Runs at `http://localhost:5173`, talking to the API at
`http://localhost:8000` by default. To point elsewhere, create
`frontend/.env` with `VITE_API_BASE_URL=http://your-api-host:8000`.

### 7. Run Tests

```bash
pytest tests/ -v --cov=src
```

16 tests total: stylometry/graph/username-matching unit tests, plus full
API integration tests (auth, case creation, ingest, cross-user access
control). Tests use throwaway secrets and an isolated temp SQLite DB (see
`tests/conftest.py`) — they never touch your real `.env` or database.

---

## Option B — Docker Compose (API + Neo4j)

```bash
cp .env.example .env
# Fill in JWT_SECRET_KEY, ENCRYPTION_KEY (see step 2 above), and
# NEO4J_PASSWORD (required by docker-compose.yml)

# Also set in .env (or export before running):
#   GRAPH_BACKEND is controlled via config/config.yaml, not .env —
#   edit config/config.yaml and set graph.backend: "neo4j" first.

docker compose up --build
```

- API: `http://localhost:8000/docs`
- Neo4j browser: `http://localhost:7474` (login with `NEO4J_USER`/`NEO4J_PASSWORD`)

The frontend isn't containerized by default (it's a static build you can
serve anywhere) — run it locally per step 6 above, pointed at
`http://localhost:8000`, or build it and serve `frontend/dist/` from your
own static host / a small nginx container.

---

## Troubleshooting

- **`RuntimeError: JWT_SECRET_KEY is not set`** → you skipped step 2; the
  API refuses to issue tokens without it.
- **`RuntimeError: ENCRYPTION_KEY is not set`** → same as above, for case
  post encryption.
- **`spacy` model not found** → re-run
  `python -m spacy download en_core_web_sm`
- **`no such table: users` when running tests directly with a bare
  `TestClient(app)`** → use `with TestClient(app) as client:` (or the
  `client` fixture in `tests/conftest.py`/`tests/test_api.py`) — FastAPI's
  lifespan startup (which creates tables) only runs inside that context
  manager. This is already handled correctly in the provided tests.
- **Port 8000 already in use** → `uvicorn src.api.main:app --port 8001`
  (and update `VITE_API_BASE_URL` accordingly)
- **`NEO4J_PASSWORD` missing when using Neo4j** → `Neo4jBackend` raises a
  clear `RuntimeError` telling you to set it, or to switch
  `graph.backend` back to `"networkx"` in `config/config.yaml`.
