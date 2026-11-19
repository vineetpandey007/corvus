# System Architecture

## 1. High-Level Data Flow

```
 Analyst (browser)
        │  login / register (JWT)
        ▼
 ┌─────────────────────┐
 │  React Dashboard      │  Case list, ingest form, Cytoscape.js graph view
 │  (frontend/)           │
 └──────────┬───────────┘
            │ REST (Bearer token)
            ▼
 ┌─────────────────────┐
 │  FastAPI Backend       │  Auth (JWT/bcrypt), rate limiting, CORS
 │  (src/api)             │
 └──────────┬───────────┘
            │
   ┌────────┼─────────────────────────────┐
   ▼        ▼                             ▼
┌──────┐ ┌────────────────┐      ┌──────────────────┐
│ Auth │ │ Case Management  │      │ Standalone Tools   │
│ DB   │ │ (src/api/routes/ │      │ (analyze/text,     │
│      │ │  cases.py)        │      │  correlate/pgp,    │
└──────┘ └───────┬──────────┘      │  correlate/username,│
                  │                  │  trace/wallet)      │
                  │                  └──────────┬─────────┘
                  ▼                             │
        ┌───────────────────┐                  │
        │  Encrypted Storage  │                  │
        │  (SQLAlchemy DB:    │                  │
        │  users, cases,      │                  │
        │  case_posts —       │                  │
        │  text_encrypted     │                  │
        │  via Fernet)        │                  │
        └──────────┬─────────┘                  │
                    │  plaintext (in-memory only) │
                    ▼                             ▼
        ┌─────────────────────────────────────────────┐
        │           Correlation Pipeline                │
        │           (src/identity_graph/graph_builder)  │
        │                                                │
        │  ┌────────────┐ ┌──────────────┐ ┌──────────┐│
        │  │ Stylometry  │ │ PGP Correlator│ │ Wallet    ││
        │  │ (cosine sim │ │ (key finger-  │ │ Reuse     ││
        │  │ on style    │ │ print reuse)  │ │ (address  ││
        │  │ features)   │ │               │ │ overlap)  ││
        │  └────────────┘ └──────────────┘ └──────────┘│
        │  ┌────────────────────────────────────────┐  │
        │  │ Username Matcher (Levenshtein + phonetic)│  │
        │  └────────────────────────────────────────┘  │
        └───────────────────────┬────────────────────────┘
                                 │  weighted correlation edges
                                 ▼
                    ┌───────────────────────┐
                    │  Graph Backend           │  Pluggable:
                    │  (graph_backend.py)      │  - NetworkXBackend (in-memory, default)
                    │                            │  - Neo4jBackend (persistent)
                    └───────────────────────┘
                                 │
                                 ▼
                    JSON returned to dashboard / GET /cases/{id}/graph
```

Separately, `src/blockchain/wallet_tracer.py` queries public block-explorer
APIs (Etherscan for Ethereum, Blockstream Esplora for Bitcoin) directly —
this is public on-chain data, not part of the encrypted case-post pipeline.

## 2. Module Responsibilities

- **`src/api/auth.py` / `src/api/routes/auth.py`** — bcrypt password
  hashing, JWT issuing/verification, and a `get_current_user` dependency
  that accepts either a JWT bearer token or a static `X-API-Key` header
  for service-to-service calls.
- **`src/db/models.py`** — `User`, `Case`, `CasePost` SQLAlchemy models.
  Case ownership is enforced at the query level (`Case.owner_id == user.id`)
  so one analyst cannot read another's case — verified in
  `tests/test_api.py::test_full_case_workflow`.
- **`src/utils/encryption.py`** — Fernet field-level encryption. Post text
  is encrypted before it touches the database and decrypted only in memory
  when an authorized analyst requests it via `GET /cases/{id}/posts`.
- **`src/identity_graph/graph_backend.py`** — an abstract interface with
  two implementations: `NetworkXBackend` (in-memory, zero setup) and
  `Neo4jBackend` (persistent, Cypher-based). Selected via
  `config/config.yaml -> graph.backend`. `graph_builder.py`'s
  `IdentityGraphBuilder` is backend-agnostic — it just calls
  `add_alias`/`add_correlation` and lets the configured backend handle
  storage.
- **`src/stylometry/`** — `feature_extractor.py` computes a fixed-length
  feature vector (sentence length, word length, punctuation ratio,
  function-word frequencies, a fixed 17-tag universal POS distribution —
  fixed-length so two different texts always produce comparable vectors).
  `author_matcher.py` scores cosine similarity between two vectors.
- **`src/identity_graph/pgp_correlator.py`** — extracts PGP public-key
  blocks and fingerprints (via `python-gnupg`, using a disposable scratch
  keyring) and flags exact fingerprint reuse across aliases.
- **`src/identity_graph/username_matcher.py`** — Levenshtein similarity
  (rapidfuzz) + phonetic matching (jellyfish Metaphone). Deliberately
  capped at a lower confidence ceiling than the other signals, since
  coincidental handle similarity is common — see `config.yaml -> username`.
- **`src/blockchain/wallet_tracer.py`** — Ethereum via Etherscan (requires
  a free API key) and Bitcoin via Blockstream's public Esplora API (no
  key required, uses the co-spend/common-input-ownership heuristic). Every
  external call goes through `tenacity`-based retry with exponential
  backoff, and `trace_wallet()` never raises — a failed trace after
  retries returns a clearly-labeled `{"error": true, ...}` result instead
  of crashing the request.
- **`src/api/rate_limit.py`** — a shared `slowapi.Limiter` instance;
  general endpoints get a per-minute cap from `config.yaml`, and
  login/register get a tighter, separate limit to slow brute-force
  attempts.

## 3. Design Decisions

- **NetworkX by default, Neo4j optional:** keeps local dev/demo
  dependency-light; switching `graph.backend: neo4j` in config plus
  Neo4j credentials in `.env` (or `docker-compose up`) swaps in the
  persistent backend with no application-code changes.
- **Confidence scoring everywhere:** every correlation edge carries a
  confidence score (0–1) so no single signal is treated as ground truth —
  the frontend graph legend color-codes by signal type so an analyst can
  see at a glance which evidence linked two aliases.
- **Encryption boundary:** plaintext post text only ever exists in process
  memory during ingestion (to run the correlation pipeline) and during an
  authorized `GET /cases/{id}/posts` call; at rest, it's always ciphertext.
- **Never raise on flaky third-party APIs:** wallet tracing calls a
  public API outside our control — the design treats "block explorer is
  down" as an expected condition, not an application bug.
- **Sample-data-first demo:** `data/sample/sample_posts.json` and
  `scripts/run_pipeline.py` let the full correlation pipeline run and be
  judged without needing a live server, database, or dark-web access.
