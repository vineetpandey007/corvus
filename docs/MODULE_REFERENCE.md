# Module Reference — Complete Technical Documentation

This document describes **every module in the codebase**, function by
function: what it does, its exact signature, what it depends on, what it
returns, and how it connects to the rest of the system. It reflects the
code exactly as shipped in this zip (all details cross-checked against
the actual source files, not written from memory).

For setup instructions see `docs/SETUP.md`. For system-level design
rationale see `docs/ARCHITECTURE.md`. For what has and hasn't been live-
tested see `docs/TESTING_NOTES.md`. This document is the third leg: what
each piece of code actually does, line by line.

---

## Table of Contents

1. [Project Module Map](#1-project-module-map)
2. [`src/utils/` — Config, Logging, Encryption](#2-srcutils)
3. [`src/db/` — Database Models & Sessions](#3-srcdb)
4. [`src/ingestion/` — Data Collection](#4-srcingestion)
5. [`src/stylometry/` — Writing-Style Analysis](#5-srcstylometry)
6. [`src/identity_graph/` — Correlation Engine & Graph Storage](#6-srcidentity_graph)
7. [`src/blockchain/` — Wallet Tracing](#7-srcblockchain)
8. [`src/visualization/` — Graph Export](#8-srcvisualization)
9. [`src/api/` — FastAPI Application](#9-srcapi)
10. [`frontend/` — React Dashboard](#10-frontend)
11. [`scripts/` — CLI Utilities](#11-scripts)
12. [`tests/` — Test Suite](#12-tests)
13. [Configuration Reference](#13-configuration-reference)
14. [Deployment Files](#14-deployment-files)

---

## 1. Project Module Map

```
src/
├── utils/            config loading, logging, audit trail, encryption
├── db/                SQLAlchemy models + session management
├── ingestion/         loads posts into the pipeline
├── stylometry/         writing-style feature extraction + comparison
├── identity_graph/    all correlation logic + pluggable graph storage
├── blockchain/         public on-chain wallet tracing
├── visualization/      graph → PNG / JSON export
└── api/                 FastAPI app: auth, routes, rate limiting

frontend/               React + Vite analyst dashboard
scripts/                 CLI entry points (demo pipeline, admin creation)
tests/                   pytest unit + integration tests
config/config.yaml       all tunable thresholds/settings
```

**Dependency direction** (who imports whom, top depends on bottom):

```
api/routes/*  →  api/auth, identity_graph, stylometry, blockchain, db
identity_graph/graph_builder  →  stylometry, identity_graph/{pgp,username}_correlator, identity_graph/{networkx,neo4j}_backend
everything  →  utils/{config,logger,encryption}
```

---

## 2. `src/utils/`

### 2.1 `config.py`

**Purpose:** single source of truth for loading `config/config.yaml`, cached.

| Item | Type | Details |
|---|---|---|
| `PROJECT_ROOT` | `Path` | Computed as `Path(__file__).resolve().parents[2]` — the repo root, used by every module that needs an absolute path (DB file, audit log, etc.) |
| `CONFIG_PATH` | `Path` | `PROJECT_ROOT / "config" / "config.yaml"` |
| `load_config() -> dict` | function, `@lru_cache()` | Reads and parses `config.yaml` once per process; subsequent calls return the cached dict. **Note:** because it's cached, changes to `config.yaml` require a process restart to take effect. |
| `get_env(key: str, default: str \| None = None) -> str \| None` | function | Thin wrapper over `os.environ.get()`, provided for consistency but not used elsewhere in the codebase (most modules call `os.environ.get()` directly). |

Calling `python -m src.utils.config` (or running the file directly) pretty-prints the loaded config as JSON — useful for sanity-checking config parsing.

`load_dotenv()` is called at import time (module level), so importing this module anywhere in the app guarantees `.env` has been loaded into `os.environ` before any other code runs.

### 2.2 `logger.py`

**Purpose:** two distinct logging concerns — human-readable application logs, and a separate machine-readable chain-of-custody audit trail.

| Item | Details |
|---|---|
| `get_logger()` | Returns the shared `loguru` logger instance. Configured once at import time: `logger.remove()` clears loguru's default handler, then `logger.add(sys.stderr, level=...)` re-adds one that writes to stderr at the level from `config.yaml -> app.log_level` (default `INFO`). |
| `audit_log(action: str, actor: str, details: dict) -> None` | Appends one JSON line to the audit log file. |

**`audit_log` behavior in detail:**
1. Reads `config.yaml -> audit.enabled` — if `false`, does nothing and returns immediately.
2. Resolves the log path from `config.yaml -> audit.log_path` (default `data/processed/audit_log.jsonl`), relative to `PROJECT_ROOT`.
3. Creates the parent directory if it doesn't exist.
4. Appends a JSON object with `timestamp` (ISO 8601, UTC), `action`, `actor`, `details` as one line (JSONL format — one JSON object per line, easy to `tail -f` or stream-parse).
5. Also emits a `logger.debug(...)` line with the same info, for local visibility.

**Every module that performs an investigative action calls this.** Specifically: `osint_collector.load_posts_from_json`, `forum_scraper.ForumScraper.run`, `graph_builder.IdentityGraphBuilder.build_from_posts`, `wallet_tracer.trace_wallet`, and the case routes (`create_case`, `ingest_posts`) in `api/routes/cases.py`.

### 2.3 `encryption.py`

**Purpose:** Fernet (AES-128-CBC + HMAC) field-level encryption for case post text at rest.

| Function | Signature | Behavior |
|---|---|---|
| `generate_key()` | `() -> str` | Returns a new base64-encoded Fernet key. Run once per deployment; the output goes into `.env` as `ENCRYPTION_KEY`. |
| `_get_fernet()` | `() -> Fernet` (private) | Reads `ENCRYPTION_KEY` from the environment; raises `RuntimeError` with setup instructions if unset. Not cached — a new `Fernet` object is constructed on every call (cheap operation, not a bottleneck). |
| `encrypt_text(plaintext: str)` | `-> str` | Encrypts a string, returns a base64 token (safe to store as a `Text` DB column). |
| `decrypt_text(token: str)` | `-> str` | Decrypts a token produced by `encrypt_text`. Raises `ValueError` (wrapping the underlying `cryptography.fernet.InvalidToken`) on a wrong key or tampered data — this is intentionally a generic message so it doesn't leak whether the failure was "wrong key" vs "corrupted data." |

Running the file directly (`python -m src.utils.encryption`) prints a freshly generated key to stdout, for convenience during setup.

**Where it's used:** `api/routes/cases.py::ingest_posts` calls `encrypt_text()` before writing `CasePost.text_encrypted`; `get_case_posts` calls `decrypt_text()` when an authorized analyst requests the case posts back. Plaintext only exists in process memory during these two operations — it is never written to disk unencrypted.

---

## 3. `src/db/`

### 3.1 `database.py`

**Purpose:** SQLAlchemy engine/session bootstrap.

| Item | Details |
|---|---|
| `DEFAULT_SQLITE_PATH` | `PROJECT_ROOT / "data" / "processed" / "app.db"` |
| `DATABASE_URL` | `os.environ.get("DATABASE_URL", f"sqlite:///{DEFAULT_SQLITE_PATH}")` — defaults to local SQLite, override for Postgres in production |
| `connect_args` | `{"check_same_thread": False}` only when using SQLite (required because FastAPI can use the same session across threads); empty dict otherwise |
| `engine` | The SQLAlchemy `Engine`, created once at import time |
| `SessionLocal` | A `sessionmaker` bound to `engine`, `autocommit=False`, `autoflush=False` |
| `Base` | The `declarative_base()` all models inherit from |
| `get_db()` | Generator function — FastAPI dependency. Yields a session, `finally: db.close()` guarantees cleanup even if the request raises. |
| `init_db()` | Imports `src.db.models` (to register all model classes with `Base.metadata`) then calls `Base.metadata.create_all(bind=engine)`. Safe to call repeatedly — `create_all` only creates tables that don't already exist. |

**Important gotcha documented in `docs/SETUP.md` and `docs/TESTING_NOTES.md`:** `init_db()` is called from `main.py`'s `lifespan` context manager, which only runs when the app is started properly (`uvicorn ...` or `with TestClient(app) as client:`). A bare `TestClient(app)` without the `with` block skips it, giving a `no such table` error.

### 3.2 `models.py`

Three SQLAlchemy ORM models, all inheriting from `Base` in `database.py`.

**`UserRole(str, enum.Enum)`** — `analyst` or `admin`.

**`User`** (`users` table)
| Column | Type | Notes |
|---|---|---|
| `id` | `Integer`, PK | |
| `username` | `String(64)`, unique, indexed | |
| `hashed_password` | `String(255)` | bcrypt hash, never plaintext |
| `role` | `Enum(UserRole)`, default `analyst` | |
| `created_at` | `DateTime`, default `now(UTC)` | |
| `cases` | relationship → `Case`, `back_populates="owner"` | |

**`Case`** (`cases` table)
| Column | Type | Notes |
|---|---|---|
| `id` | `Integer`, PK | internal numeric ID |
| `case_id` | `String(64)`, unique, indexed | the public-facing ID used in URLs — an 8-char UUID prefix, e.g. `10248af7` (see `routes/cases.py::create_case`) |
| `title` | `String(255)` | |
| `legal_basis` | `Text`, nullable | warrant/court-order reference — see `docs/ETHICS_AND_LEGAL.md` |
| `owner_id` | FK → `users.id` | enforces per-analyst ownership |
| `created_at` | `DateTime` | |
| `owner` | relationship → `User` | |
| `posts` | relationship → `CasePost`, `cascade="all, delete-orphan"` | deleting a case deletes its posts |

**`CasePost`** (`case_posts` table)
| Column | Type | Notes |
|---|---|---|
| `id` | `Integer`, PK | |
| `case_id` | FK → `cases.id` | |
| `alias` | `String(128)`, indexed | |
| `source` | `String(255)`, nullable | e.g. forum name/URL |
| `text_encrypted` | `Text` | **ciphertext only** — see `src/utils/encryption.py` |
| `created_at` | `DateTime` | |
| `case` | relationship → `Case` | |

Note that `case_id` (the FK column) is an internal integer, distinct from `Case.case_id` (the public string ID) — a naming overlap worth being careful about when reading the code (`CasePost.case_id` is the integer FK, `Case.case_id` is the string UUID slug).

---

## 4. `src/ingestion/`

### 4.1 `osint_collector.py`

The primary, recommended ingestion path — for sample data or any already-lawfully-obtained data export.

| Function | Signature | Behavior |
|---|---|---|
| `load_posts_from_json` | `(file_path: str, actor: str = "system") -> List[Dict]` | Reads a JSON array of `{"alias", "text", "source", "timestamp"}` objects from disk. Raises `FileNotFoundError` if the path doesn't exist. Logs an info line and writes an `audit_log(action="ingest", ...)` record on success. |
| `load_posts_from_feed` | `(feed_url: str, api_key: str, actor: str = "system") -> List[Dict]` | **Not implemented — raises `NotImplementedError`.** A placeholder documenting where a real, lawful partner threat-intel feed integration would go. Intentionally left unimplemented rather than stubbed with fake logic. |

### 4.2 `forum_scraper.py`

**Explicitly a structural template, not a ready-to-run scraper.** The `ForumScraper` class shows the *shape* of a rate-limited, Tor-routed collector without targeting any real site.

**`ForumScraper.__init__(self, target_url: str, actor: str = "system")`**
- Loads `ingestion.rate_limit_seconds_between_requests` and `ingestion.tor_proxy` from config.
- Builds a `requests.Session()` with `proxies` set to the configured Tor SOCKS proxy for both `http` and `https`.
- `target_url` is a required constructor argument (never hardcoded) — the caller must supply a specific, pre-authorized URL.

**Methods:**
| Method | Signature | Behavior |
|---|---|---|
| `fetch_page` | `(self, url: str) -> Optional[str]` | GETs the URL through the Tor-proxied session, 30s timeout. On success, sleeps `rate_limit_seconds` before returning the HTML text. On `requests.RequestException`, logs a warning and returns `None` (does not raise). |
| `parse_posts` | `(self, html: str) -> List[Dict]` | Parses HTML with BeautifulSoup using **placeholder CSS selectors** (`.post`, `.post-author`, `.post-body`, `.post-timestamp`) that the docstring explicitly says must be adapted to the real target's markup. |
| `run` | `(self) -> List[Dict]` | Orchestrates `fetch_page` → `parse_posts`, logs the count, writes an audit-log entry, returns the parsed posts (empty list if the fetch failed). |

Running the file directly just prints a reminder message — it does not attempt to scrape anything, by design.

---

## 5. `src/stylometry/`

### 5.1 `feature_extractor.py`

Computes a fixed-length numeric feature vector from a block of text, using spaCy (`en_core_web_sm`) for tokenization/POS-tagging.

**Constants:**
- `FUNCTION_WORDS` — a 34-word list (the, a, an, and, or, ... i) — standard authorship-attribution function words.
- `UNIVERSAL_POS_TAGS` — a fixed 17-tag list (`ADJ, ADP, ADV, AUX, CCONJ, DET, INTJ, NOUN, NUM, PART, PRON, PROPN, PUNCT, SCONJ, SYM, VERB, X`). **This fixed ordering is the key design detail:** it guarantees every text produces a feature vector of the same length and dimension order, which is required for cosine similarity to be meaningful between any two arbitrary texts (a bug in an earlier version used `sorted(dict.keys())` dynamically, which could silently produce mismatched vector lengths if two texts used different POS tags — this was caught and fixed during development, see `docs/TESTING_NOTES.md` history for the general pattern of issues caught this way).

**`extract_features(text: str) -> Dict[str, float]`**

Computes, in order:
1. `avg_sentence_length` — mean count of alphabetic tokens per sentence (via spaCy's `doc.sents`)
2. `avg_word_length` — mean character length of alphabetic tokens
3. `punctuation_ratio` — count of `[.,;:!?\-]` characters divided by total text length
4. `function_word_freq` — dict of `{word: frequency}` for every word in `FUNCTION_WORDS`, normalized by total word count (0.0 if absent, not omitted)
5. `pos_distribution` — dict of `{tag: frequency}` for every tag in `UNIVERSAL_POS_TAGS`, same normalization approach

All frequencies default to `0.0` (via `.get(..., 0)`) rather than omitting the key, which is what makes the fixed-length guarantee hold.

**`flatten_features(features: Dict) -> List[float]`**

Concatenates, in this exact fixed order: `[avg_sentence_length, avg_word_length, punctuation_ratio]` + one value per `FUNCTION_WORDS` entry (in list order) + one value per `UNIVERSAL_POS_TAGS` entry (in list order). Total vector length = 3 + 34 + 17 = **54 dimensions**, always.

### 5.2 `author_matcher.py`

**`compare_authors(text_a: str, text_b: str) -> Dict`**

1. Reads `stylometry.similarity_threshold` (default `0.75`) and `stylometry.min_text_length_chars` (default `200`) from config.
2. If either text is shorter than the minimum, returns immediately with `similarity_score: None`, `likely_same_author: False`, and a `warning` string — **does not attempt a comparison on insufficient data.**
3. Otherwise: extracts and flattens features for both texts, reshapes into `(1, 54)` numpy arrays, computes `sklearn.metrics.pairwise.cosine_similarity`.
4. Returns `{"similarity_score": round(score, 4), "likely_same_author": score >= threshold, "threshold_used": threshold}`.

The score is always a plain float (not a numpy type) — explicitly cast with `float(...)` for clean JSON serialization.

---

## 6. `src/identity_graph/`

This is the correlation engine — four independent signal detectors, one graph-storage abstraction with two implementations, and one orchestrator that ties them together.

### 6.1 `pgp_correlator.py`

**`extract_pgp_block(text: str) -> Optional[str]`** — regex search (`re.DOTALL`) for a `-----BEGIN PGP PUBLIC KEY BLOCK----- ... -----END PGP PUBLIC KEY BLOCK-----` span. Returns `None` if absent.

**`get_fingerprint(pgp_block: str, gpg_home: str = "/tmp/sih_gnupg") -> Optional[str]`** — imports the key block into a **throwaway** GPG keyring (`python-gnupg`) rooted at `gpg_home`, returns the resulting fingerprint. Uses a scratch keyring specifically so nothing persists across calls. Returns `None` if the import produced no fingerprint.

**`correlate(text_a: str, text_b: str) -> Dict`** — extracts a block from each text; if either is missing, returns `{"match": False, "fingerprint": None, "confidence": 0.0}` immediately (no GPG call at all). If both blocks yield the same fingerprint, returns `{"match": True, "fingerprint": fp, "confidence": 0.98}` — a fixed, very high confidence since exact key reuse is a strong deliberate-or-lazy OPSEC signal, not a coincidence.

**`extract_wallet_addresses(text: str) -> List[str]`** — regex-extracts candidate addresses:
- Bitcoin: `\b(bc1[a-z0-9]{25,39}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})\b` (bech32 + legacy/P2SH formats)
- Ethereum: `\b0x[a-fA-F0-9]{40}\b`

Returns a de-duplicated list (`list(set(...))`). This function is used two ways: (a) by `graph_builder.py` to detect **wallet reuse across two posts' text** (i.e., the same address literally appears in both), and (b) indirectly informs what gets passed to `wallet_tracer.py` for **on-chain** correlation (a separate, heavier check against the actual blockchain).

### 6.2 `username_matcher.py`

**`_normalize(alias: str) -> str`** (private) — lowercases and strips everything except `[a-z0-9]` (so `shadow_broker-99` and `ShadowBroker99` normalize identically).

**`compare_usernames(alias_a: str, alias_b: str) -> Dict`**

1. Reads `username.similarity_threshold` (default `0.82`) and `username.max_confidence` (default `0.55`) from config.
2. Normalizes both aliases; if either normalizes to an empty string, returns all-zero/`False`.
3. `lev_score` = `rapidfuzz.fuzz.ratio(norm_a, norm_b) / 100.0` (Levenshtein-based ratio, 0–1).
4. `phonetic_match` = `True` if `jellyfish.metaphone(norm_a) == jellyfish.metaphone(norm_b)` and that metaphone isn't empty. Wrapped in `try/except Exception` → `False` on any jellyfish error, so a phonetic-encoding edge case never crashes the correlation pipeline.
5. `likely_related` = `lev_score >= threshold OR phonetic_match`.
6. **Confidence capping (the important design detail):** `raw_confidence = max(lev_score, 0.6 if phonetic_match else 0.0)`, then `confidence = min(raw_confidence, max_confidence)` — i.e., **no matter how close the Levenshtein score gets, username-similarity confidence can never exceed `max_confidence` (0.55 by default)**. This is deliberate: handle similarity alone is common by coincidence and should never outweigh stylometry/PGP/wallet evidence in an analyst's judgment.

### 6.3 `graph_backend.py`

An `abc.ABC` defining the storage contract every graph backend must implement:
```python
add_alias(case_id, alias, **attrs) -> None
add_correlation(case_id, alias_a, alias_b, corr_type, confidence) -> None
to_json(case_id) -> Dict            # {"nodes": [...], "edges": [...]}
get_networkx_graph(case_id) -> nx.Graph
```
`get_networkx_graph` exists specifically so `src/visualization/graph_viz.py` can render a graph the same way regardless of which backend actually stored the data.

### 6.4 `networkx_backend.py`

`NetworkXBackend(GraphBackend)` — in-memory implementation.

- Holds `self._graphs: Dict[str, nx.Graph]`, one `networkx.Graph` per `case_id`, created lazily on first access (`_get_graph`).
- `add_alias` → `graph.add_node(alias, type="alias", **attrs)`.
- `add_correlation` → if the edge already exists, **merges** rather than overwrites: unions the `types` list and keeps `max(existing_confidence, new_confidence)`. If not, creates a new edge with `types=[corr_type]`.
- `to_json` / `get_networkx_graph` — straightforward reads.

**Resets on every process restart** — this is the tradeoff for zero setup.

### 6.5 `neo4j_backend.py`

`Neo4jBackend(GraphBackend)` — persistent implementation using the official `neo4j` Python driver.

- `__init__`: reads `NEO4J_URI` (default `bolt://localhost:7687`), `NEO4J_USER` (default `neo4j`), `NEO4J_PASSWORD` (**required** — raises `RuntimeError` with setup guidance if unset) from the environment. Opens a driver connection and calls `_ensure_constraints()`.
- `_ensure_constraints`: runs `CREATE CONSTRAINT alias_unique IF NOT EXISTS FOR (a:Alias) REQUIRE (a.case_id, a.name) IS UNIQUE` — guarantees no duplicate alias nodes per case.
- Nodes are labeled `:Alias` with `case_id` and `name` properties (case-scoping lets multiple investigations share one Neo4j instance without collision).
- `add_alias`: a `MERGE` (idempotent create-or-match) on `{case_id, name}`, then `SET a += $attrs` to merge in any extra attributes.
- `add_correlation`: a single Cypher statement that `MERGE`s both alias nodes, `MERGE`s an undirected `:CORRELATED_WITH` relationship between them, and on first creation sets `types`/`confidence`, or on a repeat correlation, **appends** the new type to the list (if not already present) and keeps the max confidence — mirroring the NetworkX backend's merge behavior exactly, just expressed in Cypher's `ON CREATE SET` / `ON MATCH SET`.
- `to_json`: two Cypher queries — one for all `:Alias` nodes in the case, one for all `:CORRELATED_WITH` edges (with `WHERE a.name < b.name` to avoid returning each undirected edge twice).
- `get_networkx_graph`: calls `to_json` then rebuilds an equivalent `nx.Graph` in memory, so downstream code never needs to know which backend actually stored the data.
- `close()`: closes the driver — not currently called automatically anywhere (no shutdown hook wired to it yet; a production deployment running Neo4j should add this to `main.py`'s `lifespan` shutdown phase).

**⚠️ Not run against a live Neo4j instance in this environment** — see `docs/TESTING_NOTES.md` for exactly what was and wasn't verified.

### 6.6 `graph_builder.py`

The orchestrator. Two pieces:

**`get_backend() -> GraphBackend`** — module-level singleton getter (`_backend_singleton` global). First call reads `config.yaml -> graph.backend` and constructs either `Neo4jBackend()` or `NetworkXBackend()`; every subsequent call in the same process returns the same instance. This is what lets the in-memory NetworkX graph survive across multiple API requests within one running process, and avoids opening a new Neo4j driver/connection pool per request.

**`IdentityGraphBuilder`** class:

| Method | Signature | Behavior |
|---|---|---|
| `__init__` | `(self, case_id: str = "default", backend: GraphBackend \| None = None)` | If no backend is passed, uses the process-wide singleton from `get_backend()`. Tests pass an explicit fresh `NetworkXBackend()` to avoid cross-test state bleed (see `tests/test_graph.py`). |
| `add_alias` | `(self, alias: str, **attrs)` | Delegates to `self.backend.add_alias(self.case_id, alias, **attrs)` |
| `add_correlation` | `(self, alias_a, alias_b, corr_type, confidence)` | Delegates similarly |
| `build_from_posts` | `(self, posts: List[Dict], actor: str = "system") -> IdentityGraphBuilder` | The main pipeline entry point — see below |
| `to_json` | `(self) -> Dict` | Delegates to backend |
| `get_networkx_graph` | `(self)` | Delegates to backend |

**`build_from_posts` in detail** — for every pair of posts `(i, j)` with `i < j` and different aliases:
1. **Stylometry**: `compare_authors(a.text, b.text)` → if `likely_same_author`, add a `"stylometry"` correlation edge with the similarity score as confidence.
2. **PGP**: `pgp_correlate(a.text, b.text)` → if `match`, add a `"pgp_key_reuse"` edge at confidence `0.98`.
3. **Wallet reuse**: intersect `extract_wallet_addresses(a.text)` and `extract_wallet_addresses(b.text)` — if any address appears in both posts' raw text, add a `"wallet_reuse"` edge at a fixed confidence of `0.9`.
4. **Username similarity** (only if `config.yaml -> username.enabled`): `compare_usernames(a.alias, b.alias)` → if `likely_related`, add a `"username_similarity"` edge at its (capped) confidence.

All aliases are added as nodes *before* the pairwise loop runs, so even an alias with zero correlations still appears in the graph (visible as an isolated node — see the sample-data demo graph, where `unrelated_user_1` appears alone). After the loop, writes one `audit_log(action="build_identity_graph", ...)` entry summarizing node/edge counts, and returns `self` for method chaining.

---

## 7. `src/blockchain/`

### 7.1 `wallet_tracer.py`

Public on-chain analysis only — Ethereum via Etherscan (needs a free API key), Bitcoin via Blockstream's Esplora API (no key needed).

**Module-level setup:**
- `requests_cache.install_cache("data/processed/blockchain_cache", expire_after=3600)` — caches every outbound HTTP GET for 1 hour, globally, for the whole process (reduces load on the public APIs and speeds up repeated demo runs).
- `_RETRYABLE = retry_if_exception_type((requests.ConnectionError, requests.Timeout))` — only network-level failures are retried; an HTTP error status (4xx/5xx, raised via `raise_for_status()`) is **not** retried, since retrying a 403/404 wastes time on an error that won't resolve itself.

**`_get(url, params=None, timeout=30) -> requests.Response`** (private) — decorated with `@retry(retry=_RETRYABLE, stop=stop_after_attempt(4), wait=wait_exponential(multiplier=1, min=1, max=15), reraise=True)`. Up to 4 attempts, exponential backoff between 1–15 seconds, re-raises the final exception if all attempts fail.

**`trace_wallet(address: str, chain: str = "ethereum", actor: str = "system") -> Dict`** — the public entry point.
1. Validates `chain in ("ethereum", "bitcoin")`, else `raise ValueError`.
2. Calls `_trace_ethereum` or `_trace_bitcoin`.
3. **Catches `(requests.RequestException, ValueError)` around that call** and, on failure, builds a graceful fallback result: `linked_addresses: []`, `cluster_confidence: 0.0`, a human-readable `notes` string naming the exception type, and `"error": True`. **This function never raises to its caller** — confirmed via a live test against a network-blocked endpoint in this environment, which returned the graceful result in ~0.1s (see `docs/TESTING_NOTES.md`).
4. Always calls `audit_log(action="wallet_trace", ...)` regardless of success/failure, then returns the result dict.

**`_trace_ethereum(address) -> Dict`** (private) — if `BLOCKEXPLORER_API_KEY` isn't set, logs a warning and returns a clearly-labeled placeholder result (empty links, `cluster_confidence: 0.0`, explanatory note) rather than failing. If a key is present, calls Etherscan's `account/txlist` action, extracts unique counterparty addresses from `from`/`to` fields via `_extract_eth_linked_addresses`, and computes `cluster_confidence = min(0.5 + 0.05 * len(linked), 0.95)` — a simple heuristic that scales confidence with how many distinct counterparties were found, capped at 0.95.

**`_trace_bitcoin(address) -> Dict`** (private) — calls Blockstream's `GET /address/{address}/txs` (no auth needed), passes the result to `_extract_btc_linked_addresses`. Same confidence formula as Ethereum.

**`_extract_btc_linked_addresses(tx_list, self_address) -> List[str]`** (private) — implements the **common-input-ownership heuristic**: for each transaction, collects the set of `vin` (input) addresses; if `self_address` is among them, every *other* input address on that same transaction is almost certainly controlled by the same operator (you can't spend from an address without its private key, so co-spending implies common control) — these are added as "linked." Additionally, when `self_address` is an input, the transaction's `vout` (output) addresses are also added as weaker "counterparty" signals (could just be a recipient/customer, not necessarily the same operator) — both are surfaced together for the analyst to weigh, not silently merged.

**`_extract_eth_linked_addresses(tx_list, self_address) -> List[str]`** (private) — simpler: just collects every distinct `from`/`to` address across the transaction list that isn't the queried address itself.

---

## 8. `src/visualization/`

### 8.1 `graph_viz.py`

Two export functions, both taking an `networkx.Graph` (obtained via `IdentityGraphBuilder.get_networkx_graph()`).

**`render_static_png(graph, output_path="data/processed/identity_graph.png") -> str`**
- Creates the output directory if needed.
- Layout: `nx.spring_layout(graph, seed=42, k=k)` where `k = 1.6 / max(len(graph.nodes) ** 0.5, 1)` — `k` scales inversely with graph size so labels don't overlap on small graphs (this was tuned during development after an initial version produced clipped/overlapping labels — see the before/after in the conversation history around `docs/TESTING_NOTES.md`'s spirit, though not separately documented there).
- Nodes drawn as blue circles (`#1f77b4`, size 1800), white labels at font size 8.
- Edge width scales with `confidence * 3`; edge labels show the comma-joined `types` list.
- Saved at 150 DPI with `bbox_inches="tight"`.
- Returns the output path.

**`export_json(graph, output_path="data/processed/identity_graph.json") -> str`**
- Same `{"nodes": [...], "edges": [...]}` shape as the API's graph endpoints (node dicts spread with all their attributes, edge dicts with `source`/`target` plus attributes).
- Written with `json.dump(..., indent=2)`. Returns the output path.

Both are used by `scripts/run_pipeline.py` for the standalone demo, and the JSON shape specifically mirrors what `GET /cases/{id}/graph` returns from the API, so the same frontend `GraphView` component logic would work against either source.

---

## 9. `src/api/`

### 9.1 `auth.py`

Core auth primitives, used by both route modules and the `get_current_user` dependency.

| Item | Details |
|---|---|
| `SECRET_KEY` | `os.environ.get("JWT_SECRET_KEY")` — module-level, read once at import |
| `ALGORITHM` | `"HS256"` (fixed) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `int(os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))` |
| `API_SERVICE_KEY` | `os.environ.get("API_SERVICE_KEY")` — optional, enables service-to-service auth |
| `oauth2_scheme` | `OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)` — `auto_error=False` so a missing token doesn't auto-raise before `get_current_user` can also check for an API key |

**`hash_password(password: str) -> str`** — encodes to UTF-8, **truncates to 72 bytes** (bcrypt's hard input limit — documented in a code comment as a deliberate defensive truncation rather than letting bcrypt raise on an over-length passphrase), hashes with `bcrypt.hashpw(pw_bytes, bcrypt.gensalt())`.

**`verify_password(plain_password: str, hashed_password: str) -> bool`** — same 72-byte truncation, then `bcrypt.checkpw(...)`.

> **Note on history:** the original implementation used `passlib[bcrypt]`, which crashed on every hash operation due to a known passlib/bcrypt version-incompatibility bug (passlib is effectively unmaintained). This was caught via live testing and fixed by calling `bcrypt` directly — see `docs/TESTING_NOTES.md` for the full incident writeup. The current code (as documented here) is the fixed version.

**`create_access_token(subject: str, role: str) -> str`** — calls `_require_secret_key()` (raises `RuntimeError` if `JWT_SECRET_KEY` unset), builds a payload `{"sub": subject, "role": role, "exp": <now + expiry>}`, signs with `jwt.encode(..., SECRET_KEY, algorithm="HS256")`.

**`decode_access_token(token: str) -> dict`** — same secret-key check, then `jwt.decode(...)`; on any `JWTError` (expired, malformed, wrong signature), raises `HTTPException(401, "Invalid or expired token")` with a `WWW-Authenticate: Bearer` header.

**`get_current_user(token=Depends(oauth2_scheme), x_api_key=Header(default=None), db=Depends(get_db)) -> User`** — the auth dependency attached to every protected route (directly or via `router = APIRouter(..., dependencies=[Depends(get_current_user)])` in `analysis.py`):
1. If `x_api_key` is provided **and** matches `API_SERVICE_KEY`, immediately returns a synthetic `User(id=0, username="service-account", role="admin")` — bypasses the database entirely for service calls.
2. Else, if no `token`, raises `401`.
3. Else, decodes the token, looks up the user by `sub` (username) in the DB, raises `401` if not found, otherwise returns the real `User` row.

**`require_admin(user=Depends(get_current_user)) -> User`** — additional dependency that raises `403` if `user.role != "admin"`. Defined but **not currently attached to any route** — available for future admin-only endpoints.

### 9.2 `rate_limit.py`

Just one line of substance: `limiter = Limiter(key_func=get_remote_address)` — a shared `slowapi.Limiter` instance, keyed by client IP. Exists as its own module specifically to avoid a circular import between `main.py` (which needs to attach it to the app) and route modules (which need to decorate individual endpoints, e.g. login, with a tighter limit).

### 9.3 `main.py`

The FastAPI application factory and top-level wiring.

**`lifespan(app: FastAPI)`** — an `@asynccontextmanager` (the modern replacement for the deprecated `@app.on_event("startup")`). Calls `init_db()` before `yield` (startup), logs a shutdown message after (shutdown). This is what makes `with TestClient(app) as client:` necessary in tests — the context-manager form is what actually triggers `lifespan` to run.

**App construction:**
- `FastAPI(title=..., version=..., description=..., lifespan=lifespan)` — title/version pulled from `config.yaml -> app`.
- `app.state.limiter = limiter` + `app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)` — wires up slowapi's rate-limit-exceeded response handling globally.
- `CORSMiddleware` — `allow_origins=["http://localhost:5173", "http://localhost:3000"]` (dev-only; `docs/DEPLOYMENT.md` flags this as something to change for production), `allow_credentials=True`, all methods/headers allowed.
- Routers included in order: `auth_router`, `cases_router`, `analysis_router`.

**Routes defined directly in `main.py`:**
- `GET /health` — rate-limited at `config.yaml -> security.rate_limit_per_minute` (default 60/min), returns `{"status": "ok"}`. No auth required.
- `GET /` — same rate limit, returns a welcome message plus a pointer to `/docs` and a reminder about `ETHICS_AND_LEGAL.md`. No auth required.

### 9.4 `routes/auth.py`

Two endpoints, both unauthenticated (that's the point) but rate-limited.

**`POST /auth/register`** — rate-limited `5/minute` per IP. Request: `{username (3-64 chars), password (min 8 chars)}` (Pydantic-validated via `Field`). Checks for an existing username (400 if taken), creates a `User` with `role=UserRole.analyst` (**always** — there is no way to self-register as admin, by design; see `scripts/create_admin.py`), commits, issues and returns a JWT. Status `201`.

**`POST /auth/login`** — rate-limited `10/minute` per IP. Looks up the user, calls `verify_password`; `401` on any mismatch (wrong username *or* wrong password get the same generic error, to avoid username enumeration). Issues and returns a JWT on success. Status `200`.

Both return the same `TokenResponse` shape: `{"access_token": str, "token_type": "bearer"}`.

There's a `TODO` comment in the file flagging that open self-registration should be gated behind an admin-approval flow before real deployment.

### 9.5 `routes/cases.py`

The main case-management workflow — five endpoints, all requiring auth via `Depends(get_current_user)`.

**`POST /cases`** → `201`. Creates a `Case` row: `case_id = str(uuid.uuid4())[:8]` (an 8-hex-character slug — collision probability is low but non-zero at scale; not currently checked for uniqueness beyond the DB's `unique=True` constraint, which would raise an `IntegrityError` on collision rather than silently retrying — worth hardening for very high case volumes), `owner_id = user.id`. Writes an audit-log entry. Returns `CaseResponse`.

**`GET /cases`** → list of `CaseResponse`, filtered to `Case.owner_id == user.id` — **an analyst only ever sees their own cases.**

**`POST /cases/{case_id}/ingest`**:
1. Looks up the case **filtered by both `case_id` and `owner_id`** — `404` if it doesn't exist *or* belongs to someone else (these two situations are deliberately indistinguishable in the response).
2. For each post in the request, creates a `CasePost` row with `text_encrypted = encrypt_text(post.text)` — encryption happens before the DB write, never after.
3. Commits all posts in one transaction.
4. Builds a plaintext list (`{"alias", "text", "source"}` per post, from the original request, not re-read/re-decrypted from the DB) and passes it to `IdentityGraphBuilder(case_id=case_id).build_from_posts(...)` — this is the only point where plaintext post text exists outside the request/response cycle, and it's transient, in-memory only, for the duration of the correlation pipeline.
5. Writes an `ingest_case_posts` audit entry.
6. Returns `{"case_id", "ingested": <count>, "graph": <full graph JSON>}` — the caller gets the updated graph immediately, no separate fetch needed.

**`GET /cases/{case_id}/graph`** — same ownership check, then returns `{"case_id", **builder.to_json()}`. Note this constructs a **new** `IdentityGraphBuilder(case_id=case_id)` — since the graph backend itself is the process-wide singleton (see §6.6), this correctly retrieves the same underlying graph data without needing to hold a builder instance across requests.

**`GET /cases/{case_id}/posts`** — same ownership check, queries all `CasePost` rows for the case, and **decrypts each one** (`decrypt_text(p.text_encrypted)`) before returning. This is the only route that ever returns case post plaintext over the API.

### 9.6 `routes/analysis.py`

Standalone, one-off correlation tools that don't require opening a case — useful for quick triage. `router = APIRouter(tags=["analysis"], dependencies=[Depends(get_current_user)])` — note the auth dependency is attached at the **router** level here (applies to every route in the file), rather than per-function like in `cases.py`.

| Endpoint | Request body | Delegates to |
|---|---|---|
| `POST /analyze/text` | `{alias_a, text_a, alias_b, text_b}` | `compare_authors()` |
| `POST /correlate/pgp` | same shape | `pgp_correlate()` |
| `POST /correlate/username` | `{alias_a, alias_b}` | `compare_usernames()` |
| `POST /trace/wallet` | `{address, chain="ethereum"}` | `trace_wallet()`, with an explicit second `Depends(get_current_user)` to get `user.username` for the audit-log actor field (the router-level dependency already enforces auth; this second one is for its return value, not for access control) |
| `GET /graph/{case_id}` | — | `IdentityGraphBuilder(case_id).to_json()` — **no DB ownership check** here (unlike `/cases/{id}/graph`), since this route only knows the case_id string, not who owns it in the DB. Documented as a quick-lookup path; `/cases/{id}/graph` is the access-controlled equivalent. |

---

## 10. `frontend/`

React 18 + Vite. No server-side rendering — a pure single-page app that talks to the FastAPI backend over REST.

### 10.1 `src/api/client.js`

- `API_BASE_URL` — from `import.meta.env.VITE_API_BASE_URL`, falling back to `http://localhost:8000`.
- `client` — an `axios` instance with a **request interceptor** that reads `access_token` from `localStorage` and attaches it as `Authorization: Bearer <token>` on every outgoing request.
- A **response interceptor**: on any `401`, clears the stored token and hard-redirects to `/login` (`window.location.href`) — a simple, global session-expiry handler.
- Three exported API groups, each a thin wrapper over the corresponding backend routes: `authApi` (`register`, `login`), `casesApi` (`list`, `create`, `ingest`, `getGraph`, `getPosts`), `analysisApi` (`compareText`, `correlatePgp`, `correlateUsername`, `traceWallet`).

### 10.2 `src/App.jsx`

Routing via `react-router-dom`. `RequireAuth` is a small wrapper component that checks `localStorage.getItem("access_token")` and redirects to `/login` if absent (client-side gating only — the real enforcement is server-side via the API's `get_current_user` dependency; this just avoids flashing protected UI before a redirect). Routes: `/login`, `/register` (both render `<Login>` with a `mode` prop), `/cases` (list, protected), `/cases/:caseId` (detail, protected), and a catch-all that redirects to `/cases`.

### 10.3 `src/pages/Login.jsx`

Single component handling both login and registration (`mode` prop switches behavior/copy). On submit, calls `authApi.register` or `authApi.login` accordingly, stores the returned `access_token` in `localStorage`, navigates to `/cases`. Displays the backend's error `detail` field on failure, or a generic fallback message.

### 10.4 `src/pages/CaseList.jsx`

Two responsibilities in one page:
1. A create-case form (`title`, `legalBasis`) that calls `casesApi.create` and, on success, navigates straight into the new case's detail page.
2. A list of the analyst's existing cases (loaded via `casesApi.list` on mount), each linking to `/cases/:caseId`.

Also has a logout button that clears the token and redirects to `/login`.

### 10.5 `src/pages/CaseDetail.jsx`

The main workspace for a single case, with three tabs (local `activeTab` state, no routing sub-paths):

- **Identity Graph tab** — renders `<GraphView graph={graph} />`.
- **Ingest Posts tab** — a dynamic form: starts with one post-draft row (`alias`, `source`, `text`), with "+ Add another post" / "Remove" controls to add/remove rows. On submit, filters out any row missing `alias` or `text`, calls `casesApi.ingest`, resets the draft form, reloads case data, and switches back to the Graph tab.
- **Case Posts tab** — a table of decrypted stored posts (`casesApi.getPosts`), showing alias/source/text/ingested-timestamp.

`loadCaseData()` fetches graph + posts in parallel via `Promise.all` on mount and after every successful ingest.

### 10.6 `src/components/GraphView.jsx`

Wraps `react-cytoscapejs`. `TYPE_COLORS` maps each correlation type to a fixed color: `stylometry` → blue `#4C6EF5`, `pgp_key_reuse` → red `#F03E3E`, `wallet_reuse` → orange `#F59F00`, `username_similarity` → green `#12B886`; anything else falls back to gray `#868E96`.

Converts the `{nodes, edges}` graph JSON into Cytoscape's `elements` array (memoized with `useMemo`, keyed on `graph`). Edge width scales with confidence (`1 + confidence * 4`), edge color is set from the **first** entry in that edge's `types` array (if an edge has multiple correlation types, only the first one's color shows — a known simplification). Uses the `cose` force-directed layout, non-animated. Renders a color-key legend below the graph. Shows a "No aliases ingested yet" message if the graph is empty or absent.

### 10.7 `src/styles.css`

A single dark-themed stylesheet (`:root` CSS custom properties for colors) covering all pages — no CSS framework/library, plain hand-written CSS. Defines the auth-page centered-card layout, the case-list layout, the tabbed case-detail layout, the post-ingest form's row grid, the posts table, and the graph container/legend.

---

## 11. `scripts/`

### 11.1 `run_pipeline.py`

Standalone CLI — runs the full correlation pipeline without needing the API/DB/auth stack at all.

Args: `--input` (required, path to a posts JSON file), `--actor` (default `"demo_analyst"`), `--case-id` (default `"demo-case-01"`).

Flow: `load_posts_from_json` → `IdentityGraphBuilder(case_id=...).build_from_posts(...)` → `get_networkx_graph()` → `export_json(...)` + `render_static_png(...)`, both written to `data/processed/`. Prints a human-readable summary of every correlation found (alias pair, types, confidence) to stdout.

Manually inserts the project root onto `sys.path` at the top of the file so it can be run directly (`python scripts/run_pipeline.py`) without needing the package installed or `PYTHONPATH` set.

### 11.2 `create_admin.py`

CLI for provisioning the first admin account (since `/auth/register` can only create `analyst`-role accounts by design).

Args: `--username` (required), `--password` (required, validated for ≥8 characters **before** touching the DB). Calls `init_db()` directly (doesn't require the API to be running), checks for an existing username (exits with an error message if taken, rather than overwriting), creates a `User` with `role=UserRole.admin`, commits.

---

## 12. `tests/`

16 tests total, split across four files, all passing as of the last verified run (see `docs/TESTING_NOTES.md` for the full verification log).

### 12.1 `conftest.py`

Runs before any test collection. Sets three environment variables via `os.environ.setdefault` (so it never overwrites a real `.env` value if one happens to already be set) **before any `src.*` module is imported**: `JWT_SECRET_KEY` (a fixed throwaway string), `ENCRYPTION_KEY` (a fixed, validly-formatted Fernet key — generated once with `Fernet.generate_key()` and hardcoded, since it must be valid base64 of the right length or `Fernet(...)` raises), `ACCESS_TOKEN_EXPIRE_MINUTES=60`. Also creates a throwaway SQLite file via `tempfile.mkstemp` and sets `DATABASE_URL` to point at it — **test runs never touch your real `.env` or `data/processed/app.db`.**

### 12.2 `test_stylometry.py`

Four unit tests against `feature_extractor` and `author_matcher` directly (no API/DB involved):
- `extract_features` returns all five expected top-level keys
- `flatten_features` produces equal-length vectors for two different texts (the fixed-vocabulary regression check)
- Two paraphrased/similar texts score `>=` an unrelated text's score against a shared anchor text
- A too-short text pair returns `similarity_score: None` plus a `warning`

### 12.3 `test_graph.py`

Eight unit tests against the identity-graph layer, each constructing an explicit fresh `NetworkXBackend()` (via a local `_new_builder()` helper) to avoid sharing state with the process-wide singleton:
- Adding an alias + correlation produces the expected edge/confidence/types
- A second correlation on the same pair **strengthens** (merges types, keeps max confidence) rather than overwriting
- `extract_wallet_addresses` correctly finds both an ETH-style and a BTC-style address in one text
- `to_json()` shape check (correct node/edge counts)
- `compare_usernames` correctly flags `"shadowbroker99"` vs `"shadow_broker_99"` as related
- `compare_usernames` correctly does **not** flag two genuinely unrelated handles
- A full `build_from_posts` run on two similar-handle aliases produces the expected 2-node graph

### 12.4 `test_api.py`

Five integration tests against the **real FastAPI app** via `TestClient`, using a `@pytest.fixture(scope="module") def client(): with TestClient(app) as c: yield c` — the `with` form is required for the `lifespan` startup handler (table creation) to actually run; this was itself the subject of a bug fix during development (see `docs/TESTING_NOTES.md`).
- Health check returns `200`/`{"status": "ok"}`
- Register + login both succeed and return a token
- Login with a wrong password → `401`
- An unauthenticated request to `/cases` → `401`
- **Full workflow**: register → create case → ingest two posts (long enough to clear the stylometry min-length check) → fetch graph (2 nodes) → fetch decrypted posts (non-empty text) → **register a second analyst and confirm they get `404` trying to read the first analyst's case** (cross-user access-control check)

Each test that needs a unique username calls a local `_unique_username()` helper (`f"pytest_{uuid.uuid4().hex[:8]}"`) so tests can run in any order without username collisions.

---

## 13. Configuration Reference

### 13.1 `config/config.yaml`

| Key | Default | Read by | Meaning |
|---|---|---|---|
| `app.name` | `"Dark Web Threat Actor De-anonymization Toolkit"` | `api/main.py` | FastAPI app title |
| `app.version` | `"0.1.0"` | `api/main.py` | FastAPI app version |
| `app.log_level` | `"INFO"` | `utils/logger.py` | loguru stderr handler level |
| `graph.backend` | `"networkx"` | `identity_graph/graph_builder.py::get_backend` | `"networkx"` or `"neo4j"` |
| `stylometry.similarity_threshold` | `0.75` | `stylometry/author_matcher.py` | cosine-similarity cutoff for `likely_same_author` |
| `stylometry.min_text_length_chars` | `200` | `stylometry/author_matcher.py` | below this, comparison is skipped with a warning |
| `username.enabled` | `true` | `identity_graph/graph_builder.py` | whether username-similarity is checked during `build_from_posts` |
| `username.similarity_threshold` | `0.82` | `identity_graph/username_matcher.py` | Levenshtein-ratio cutoff for `likely_related` |
| `username.max_confidence` | `0.55` | `identity_graph/username_matcher.py` | hard confidence ceiling for this signal |
| `security.rate_limit_per_minute` | `60` | `api/main.py` | general per-IP rate limit (`/health`, `/`) |
| `security.access_token_expire_minutes` | `60` | *(documented but not actually read — see note below)* | |
| `pgp.require_full_fingerprint_match` | `true` | *(documented but not actually read in code — `pgp_correlator.py` always requires an exact match; this key exists for future partial-match support)* | |
| `blockchain.supported_chains` | `["ethereum", "bitcoin"]` | *(documented but not enforced in code — `wallet_tracer.trace_wallet` hardcodes the same two-chain check directly rather than reading this list)* | |
| `blockchain.request_cache_ttl_seconds` | `3600` | *(documented but not actually read — `wallet_tracer.py` hardcodes `expire_after=3600` directly rather than reading this key)* | |
| `ingestion.rate_limit_seconds_between_requests` | `5` | `ingestion/forum_scraper.py` | sleep between scraper requests |
| `ingestion.tor_proxy` | `"socks5h://127.0.0.1:9050"` | `ingestion/forum_scraper.py` | SOCKS proxy for the scraper template |
| `audit.enabled` | `true` | `utils/logger.py::audit_log` | master on/off switch for audit logging |
| `audit.log_path` | `"data/processed/audit_log.jsonl"` | `utils/logger.py::audit_log` | relative to `PROJECT_ROOT` |

**Note on the three "documented but not actually read" keys above:** `security.access_token_expire_minutes`, `pgp.require_full_fingerprint_match`, and `blockchain.request_cache_ttl_seconds`/`supported_chains` exist in `config.yaml` as forward-looking documentation of intent, but the corresponding code currently reads its actual value from elsewhere (an environment variable, in the token-expiry case) or has the value hardcoded (in the PGP/blockchain cases) rather than calling `load_config()` for it. This is a real inconsistency worth cleaning up — either wire the code to read these keys, or remove them from the YAML so it doesn't imply a control that doesn't exist. Flagging it here rather than silently documenting the YAML as if it were fully wired.

### 13.2 `.env` variables

Covered in full in `docs/SETUP.md`'s table — not repeated here to avoid drift between two copies of the same table. The short version: `JWT_SECRET_KEY` and `ENCRYPTION_KEY` are required; everything else (`DATABASE_URL`, `API_SERVICE_KEY`, `BLOCKEXPLORER_API_KEY`, `NEO4J_*`, `TOR_SOCKS_PROXY`, `LOG_LEVEL`) is optional with a sensible fallback.

---

## 14. Deployment Files

### 14.1 `Dockerfile`

`python:3.12-slim` base. Installs `gnupg` (required at runtime by `python-gnupg`/`pgp_correlator.py` — it shells out to the real `gpg` binary), `build-essential` (for any package requiring compilation), `curl` (used by the `HEALTHCHECK`). Installs Python deps, downloads the spaCy model and NLTK data at build time (not at container start, so cold-start is fast). Copies the app, creates a non-root `appuser`, creates `data/processed` and `data/raw` with correct ownership. `HEALTHCHECK` hits `/health` every 30s. Default command: `uvicorn src.api.main:app --host 0.0.0.0 --port 8000`.

### 14.2 `docker-compose.yml`

Two services:
- **`api`** — builds from the local `Dockerfile`, exposes `8000`, loads `.env`, overrides `NEO4J_URI` to `bolt://neo4j:7687` (the compose-network service name, not `localhost`) so the Neo4j backend works correctly inside the compose network if `graph.backend: neo4j` is set. Mounts `./data:/app/data`. Depends on `neo4j`'s healthcheck passing first.
- **`neo4j`** — official `neo4j:5-community` image, exposes `7474` (browser UI) and `7687` (bolt). Auth pulled from `${NEO4J_USER:-neo4j}/${NEO4J_PASSWORD:?set NEO4J_PASSWORD in .env}` — the `:?` syntax means compose will **refuse to start** with a clear error if `NEO4J_PASSWORD` isn't set, rather than starting with a blank/default password. Data persisted in a named volume (`neo4j-data`).

### 14.3 `.dockerignore`

Excludes `venv/`, `node_modules/`, `__pycache__/`, `.git/`, build artifacts, real data under `data/raw`/`data/processed` (keeping the `.gitkeep` placeholders), and `.env` — the image never bakes in local secrets or generated files.

---

*This document is generated to reflect the exact state of the code in this delivery. If you modify a module, update the corresponding section here — an out-of-date reference doc is worse than none, since it actively misleads.*
