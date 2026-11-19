# Dark Web Threat Actor De-anonymization Toolkit

**Smart India Hackathon 2026 — Problem Statement #151**
Theme: Blockchain & Cybersecurity | Category: Software

A real, working investigative platform that helps threat-intel analysts and
law enforcement correlate pseudonymous dark-web identities across forums,
marketplaces, and leaked data — using OSINT correlation, stylometry,
PGP-key fingerprint matching, username similarity, and blockchain
transaction tracing. Analyst accounts, case data, and an audit trail are
all persisted; case text is encrypted at rest.

> ⚠️ **This tool does not break Tor, decrypt anything, or gain unauthorized
> access to any system.** It is a correlation/analytics layer that works on
> data an investigator is already legally authorized to collect. Read
> [`docs/ETHICS_AND_LEGAL.md`](docs/ETHICS_AND_LEGAL.md) before using or
> demoing this project.

**Status:** every module below has been installed, unit-tested, and
exercised end-to-end (register → login → create case → ingest → identity
graph) against a live running instance — see [`docs/TESTING_NOTES.md`](docs/TESTING_NOTES.md)
for exactly what was verified and how.

---

## 1. What This Toolkit Does

| Module | Purpose |
|---|---|
| `ingestion` | Collects text/posts from authorized sources (sample data, legal feeds, or a configured Tor proxy) |
| `stylometry` | Extracts writing-style fingerprints and scores similarity between two authors' texts |
| `identity_graph` | Correlates aliases via PGP key reuse, wallet reuse, and username similarity, and stores the result in a pluggable graph backend |
| `blockchain` | Traces public on-chain wallet activity (Ethereum + Bitcoin) for reused-address patterns, with retry/backoff and graceful failure handling |
| `db` | Persistent analyst accounts and case metadata (SQLAlchemy, SQLite by default / Postgres-ready) |
| `api` | FastAPI backend: JWT auth (password, email/OTP login, Google/GitHub OAuth), rate limiting, encrypted case storage, REST endpoints for everything above |
| `reporting` | Bullet-point case report generation (JSON/TXT/PDF) |
| `frontend` | A real React + Vite dashboard: home page, login (password/OTP/Google/GitHub), case management, post ingestion, interactive identity graph with PNG/JPG export, and a case report tab with TXT/PDF export |
| `visualization` | Graph JSON/PNG export helpers used by the backend and demo scripts |

## 2. Folder Structure

```
dark-web-deanonymization/
├── README.md
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .dockerignore
├── .env.example
├── .gitignore
├── LICENSE
├── config/
│   └── config.yaml
├── docs/
│   ├── ARCHITECTURE.md
│   ├── ETHICS_AND_LEGAL.md
│   ├── SETUP.md
│   ├── API.md
│   ├── DEPLOYMENT.md
│   ├── TESTING_NOTES.md
│   └── MODULE_REFERENCE.md
├── data/
│   ├── raw/, processed/      # gitignored — real data never committed
│   └── sample/                # small synthetic sample dataset for demos
├── src/
│   ├── ingestion/              # data collection modules
│   ├── stylometry/             # writing-style feature extraction + matching
│   ├── identity_graph/         # PGP/wallet/username correlation + pluggable graph backend
│   ├── blockchain/             # Ethereum + Bitcoin wallet tracing
│   ├── db/                     # SQLAlchemy models + session management
│   ├── api/                    # FastAPI app, auth, routes
│   ├── visualization/          # graph export helpers
│   └── utils/                  # config loader, logger, encryption, app-data-dir resolution
├── frontend/                    # React + Vite analyst dashboard (fully implemented)
├── desktop/                      # Electron + PyInstaller desktop app (see desktop/README.md)
├── tests/                       # pytest unit + API integration tests (16 tests, all passing)
└── scripts/                     # pipeline runner, admin-account creator
```

## 3. Quick Start (local, no Docker)

```bash
git clone <your-fork-url>
cd dark-web-deanonymization

python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt
python -m spacy download en_core_web_sm

cp .env.example .env
# Generate and fill in the two REQUIRED secrets:
python -c "import secrets; print(secrets.token_urlsafe(32))"            # -> JWT_SECRET_KEY
python -c "from src.utils.encryption import generate_key; print(generate_key())"  # -> ENCRYPTION_KEY

uvicorn src.api.main:app --reload --port 8000
# API docs: http://localhost:8000/docs
```

In a second terminal:
```bash
cd frontend
npm install
npm run dev
# Dashboard: http://localhost:5173
```

Register your first analyst account from the dashboard's Register page, or
via curl:
```bash
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username": "analyst01", "password": "ChangeThisPassword123!"}'
```

Full setup (including Docker and Neo4j) is in [`docs/SETUP.md`](docs/SETUP.md).

## 4. Desktop Application (Windows / macOS / Linux)

The same backend and frontend also package into a self-contained desktop
app (Electron shell + the Python backend bundled inside via PyInstaller —
no separate Python install needed by the end user). See
[`desktop/README.md`](desktop/README.md) for full build instructions.

```bash
cd desktop
npm install
npm run build:backend    # PyInstaller — run on the target OS, no cross-compiling
npm run build:frontend
npm start                # try it unpackaged first
npm run dist:win          # or dist:mac / dist:linux — produces the installer
```

The full Electron + bundled-backend flow (spawn → health check → load
dashboard) has been built and verified end-to-end on Linux, including
screenshots of the running app — see `docs/TESTING_NOTES.md`. The actual
Windows `.exe` / macOS `.dmg` builds need to be produced by running the
build on those OSes directly (PyInstaller/electron-builder don't
cross-compile) — that hasn't been done yet, and `desktop/README.md`'s
"Known limitations" section is explicit about exactly what is and isn't
confirmed working.

## 5. Run the Demo Pipeline on Sample Data (no auth/DB needed)

```bash
python scripts/run_pipeline.py --input data/sample/sample_posts.json
```

Runs the full correlation pipeline on synthetic sample posts and writes a
JSON + PNG identity graph to `data/processed/` — useful for a quick
sanity check or a judge-facing demo that doesn't need the full stack up.

## 6. Run Tests

```bash
pytest tests/ -v --cov=src
```

16 tests: unit tests for stylometry/graph/username-matching, plus full API
integration tests (register, login, wrong-password rejection, auth-required
enforcement, and a complete case workflow with cross-user access-control
checks). All passing as of the last update — see `docs/TESTING_NOTES.md`.

## 7. Architecture

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full data-flow
diagram and design rationale.

## 8. Tech Stack

- **Backend:** Python 3.11+, FastAPI, Uvicorn, SQLAlchemy
- **Auth:** JWT (python-jose) + bcrypt password hashing + optional service API key
- **NLP/ML:** spaCy, NLTK, scikit-learn
- **Fuzzy/phonetic matching:** rapidfuzz, jellyfish
- **Graph:** NetworkX (in-memory, default) / Neo4j (persistent, optional)
- **Blockchain:** Etherscan REST API (Ethereum), Blockstream Esplora API (Bitcoin) — plain HTTP, no web3.py needed
- **Resilience:** tenacity (retry/backoff), slowapi (rate limiting)
- **Security:** Fernet (cryptography) field-level encryption at rest
- **Frontend:** React 18, Vite, Cytoscape.js, React Router, Axios
- **Testing:** pytest, pytest-cov, FastAPI TestClient
- **Deployment:** Docker, docker-compose (API + Neo4j)

All dependencies are open source (MIT / BSD / Apache-2.0 licensed).

## 9. Security & Robustness Features

- Passwords hashed with bcrypt (never stored/logged in plaintext)
- JWT-based session auth + optional static API key for service calls
- Case post text encrypted at rest (Fernet/AES) — decrypted only in-memory when an authenticated analyst requests it
- Per-case ownership enforcement (one analyst cannot read another's case — enforced and tested)
- Rate limiting on the API generally, with tighter limits on login/register to slow brute-force attempts
- Retry with exponential backoff on external blockchain API calls, with graceful (non-crashing) failure when those APIs are unreachable or rate-limited
- Full chain-of-custody audit log (`data/processed/audit_log.jsonl`) for every ingest/correlation/trace action
- Pluggable graph backend: in-memory NetworkX for demos, Neo4j for persistent multi-analyst deployments

## 10. Ethical & Legal Use

This project is built strictly as an **authorized investigative aid**. See
[`docs/ETHICS_AND_LEGAL.md`](docs/ETHICS_AND_LEGAL.md) for scope
limitations, chain-of-custody requirements, and data-retention guidelines.
SIH judges on this problem statement will specifically look for these
guardrails — treat this document as part of the deliverable, not an
afterthought.

## 11. Team & Submission Notes

- Replace this section with your team name, members, and SIH team ID.
- Attach your architecture diagram and demo video link here before final
  submission.

## 12. License

Licensed under the [MIT License](LICENSE) — see file for details.
