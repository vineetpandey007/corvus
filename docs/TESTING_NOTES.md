# Testing Notes

Transparency on what's actually been verified in this codebase, and how —
so you know what you're building on top of versus what you should still
check yourself.

## What Was Verified

1. **All dependencies install cleanly** in a fresh virtualenv from
   `requirements.txt` (Python 3.12).
2. **16 pytest tests pass**, covering:
   - Stylometry feature extraction and author-matching (unit)
   - Identity graph building, correlation strengthening, wallet-address
     regex extraction, username fuzzy-matching (unit)
   - Full API integration: health check, register, login, wrong-password
     rejection (401), unauthenticated access rejection (401), and a
     complete case workflow — create case → ingest posts → verify graph →
     verify decrypted posts → **confirm a second analyst cannot access the
     first analyst's case (404)**
3. **The real FastAPI server boots under uvicorn** (not just the test
   client) and was exercised with live curl requests: register, login,
   wrong-password login, create case, ingest sample posts, retrieve graph,
   retrieve decrypted posts, and an unauthenticated request correctly
   rejected.
4. **The encryption module** was verified with a real encrypt→decrypt
   round-trip, and separately verified that data stored via the API comes
   back decrypted correctly through `GET /cases/{id}/posts`.
5. **The demo pipeline script** (`scripts/run_pipeline.py`) runs
   end-to-end on the sample dataset and produces a correct JSON graph and
   a readable PNG visualization.
6. **The admin-creation script** (`scripts/create_admin.py`) was run and
   confirmed to create an admin-role account.
7. **The Bitcoin wallet tracer's failure path** was verified directly: in
   this sandboxed dev environment, the block-explorer API is network-
   blocked, and the tracer was confirmed to catch that failure gracefully
   (returns a labeled error result in ~0.1s) rather than crashing or
   hanging through the full retry/backoff cycle.
8. **The frontend actually builds**: `npm install` and `npm run build`
   both complete successfully, producing a working static bundle.

## Desktop Application — What Was Verified

9. **The dead-dependency cleanup was verified, not assumed**: `nltk`,
   `web3`, `pandas`, and `plotly` were all confirmed (via grep across the
   entire `src/` tree) to be listed in `requirements.txt` but never
   actually imported anywhere in application code. Removed, then
   re-verified with a full clean-venv install + 16/16 pytest pass.
10. **Three real cross-platform path bugs were found and fixed** before
    building the desktop app:
    - The audit log and SQLite DB paths resolved relative to the
      project's source directory. In a PyInstaller-frozen app, that
      directory is a temporary extraction folder wiped after every
      process exit — this would have silently lost the entire database
      and audit trail on every app restart. Fixed with a new
      `get_app_data_dir()` helper (`src/utils/config.py`) that respects
      an `APP_DATA_DIR` environment variable, which the Electron shell
      sets to the OS's real per-user app-data directory.
    - `src/identity_graph/pgp_correlator.py` hardcoded `/tmp/sih_gnupg`
      as its GPG scratch directory — `/tmp` doesn't reliably exist on
      Windows. Fixed to use `tempfile.gettempdir()`.
    - Verified the `APP_DATA_DIR` fix directly: ran the app with it set
      to a throwaway directory and confirmed both `app.db` and
      `audit_log.jsonl` were created there, with correct audit content.
11. **The PyInstaller-bundled backend was actually built and run**, not
    just spec'd out: `pyinstaller desktop/backend.spec` was run for real
    in a Linux dev environment, producing a working executable. That
    executable (not the plain Python script — the actual frozen binary)
    was then exercised exactly like the live-uvicorn smoke test earlier
    in this document: health check, register, login, create case, ingest
    posts (exercising the bundled spaCy model specifically, the part of
    PyInstaller bundling most likely to silently fail), and graph
    retrieval — all confirmed working against the frozen executable.
12. **The full Electron app was run end-to-end**, not just reviewed as
    code: using `Xvfb` (a virtual X11 display) in the same Linux dev
    environment, `electron .` was launched for real. The main process
    spawned the PyInstaller-built backend as an actual child process
    (confirmed via `ps aux` showing the `dwta-backend` process spawned
    under Electron's process tree), polled `/health` until it returned
    `200`, closed the splash screen, and loaded the built React frontend
    via `file://`. **Screenshots of the running app window** (captured
    with ImageMagick's `import` against the virtual display) confirm the
    login page renders correctly — full dark theme, form layout,
    autofocus — proving the `vite.config.js` relative-path fix and the
    `BrowserRouter` → `HashRouter` swap (both required for `file://` to
    work at all) are correct, not just plausible-sounding.

## Desktop Application — What Was NOT Verified

- **No real Windows or macOS build.** PyInstaller and electron-builder
  both require building on the actual target OS — everything above was
  verified on Linux. The `.spec` and `package.json` build config are
  correct by inspection and follow the same patterns as the Linux build
  that *was* verified, but "the Windows build" as an artifact has not
  been produced or run. See `desktop/README.md`'s "Known limitations"
  section.
- **No UI interaction was automated** (no simulated typing/clicking
  through the register → login → create case → ingest flow inside the
  actual Electron window). The screenshot confirms the app *renders*
  correctly; the underlying register/login/case/ingest logic was
  separately confirmed working against the same frozen backend
  executable via curl (see point 11) — but those are two different
  tests, not one combined proof that clicking through the real UI works.
- **`python-gnupg`'s runtime dependency on a real `gpg` binary** is not
  resolved by the PyInstaller bundle — see `desktop/README.md`.
- **No code signing, no auto-update mechanism.**

## Reporting/Export & Auth Expansion — What Was Verified

Both built in response to a feature request, each exercised through real
browser automation (Playwright + headless Chromium), not just written:

- **Reports & export (home page, bullet-point case report, TXT/PDF/PNG/JPG
  export)**: registered → created a case → ingested posts → viewed the
  Report tab → downloaded all four export formats, all via real clicks in
  a real browser. The PDF was additionally rendered to an image
  (`pdftoppm`) to visually confirm correct layout, not just "a file
  downloaded."
- **Email-based login, forgot/reset password, OTP login** (dev-mode email
  backend): registered with an email → requested a password reset →
  extracted the real token from the dev email outbox file → reset the
  password → confirmed the **old password no longer works** and the
  **new one does** → requested an OTP → extracted the real code from the
  outbox → verified it → confirmed login succeeded. All through the
  actual UI, reading the actual dev-mode "sent" email, not a mocked
  shortcut.
- 14 new pytest tests covering these flows server-side (token/code
  single-use enforcement, expiry, wrong-code rejection, generic
  non-enumerating responses on forgot-password/OTP-request) — 30/30
  tests passing overall.

**Three real bugs found and fixed during this work:**
1. **Timezone-naive vs. timezone-aware datetime comparison** — SQLite
   returns naive `datetime` objects even for values stored as UTC-aware;
   comparing `reset_token.expires_at < datetime.now(timezone.utc)` raised
   `TypeError` on every reset/OTP check. Fixed with a small `_as_utc()`
   normalizer in `src/api/routes/auth.py`.
2. **The rate limiter correctly blocked rapid test-suite registration** —
   not an app bug, but it broke the test suite itself (many registrations
   in seconds). Fixed by disabling `slowapi`'s limiter for the test
   session rather than weakening the real limits.
3. **CORS origin mismatch during manual verification** — `localhost` and
   `127.0.0.1` are different origins to a browser even on the same port;
   using the wrong one in a test script produced a CORS rejection that
   looked like a backend failure. Resolved by matching the test's origin
   to `main.py`'s CORS whitelist — a reminder that `docs/DEPLOYMENT.md`'s
   note about updating that whitelist for production is a real, specific
   gotcha, not boilerplate advice.

## NLP Queries & Suggestions — What Was Verified

Rule-based, not LLM-backed (deliberate choice — no hallucination risk,
no API key needed). Fully testable since there's no external dependency:
13 new unit tests covering intent matching (summary, strongest/weakest
finding, named-alias connections, type filtering, isolated aliases,
unrecognized-query fallback) and suggestion rules, plus an API
integration check. One real bug caught by the integration test: the
summary intent matched "summary" but not "summarize" (not a substring of
each other) — a query phrased as a verb fell through to the fallback
handler. Fixed by matching on the "summar" stem. Also verified via actual
browser automation: asked a question, clicked a suggested follow-up chip,
confirmed the suggestions panel correctly identified the case's specific
aliases and highest-confidence pair by name.

## OAuth (Google / GitHub) — What Was Verified, and What Genuinely Can't Be

A real end-to-end OAuth test (clicking through Google's or GitHub's actual
consent screen) is not possible in this environment — it requires a real
registered OAuth app and live network access to `accounts.google.com` /
`github.com`, neither of which is available here. Being explicit about
that boundary rather than implying full coverage:

**What WAS verified, for real:**
- CSRF state-token generation, verification, and rejection of tampered/
  wrong-purpose tokens
- The clean `501` "not configured" error path when no credentials are set
  (the real condition this app ships in until you add your own)
- The callback's error-redirect behavior on missing/invalid state
- With fake-but-present credentials, the login route redirects to the
  **real** `accounts.google.com` authorize URL with correctly-formed
  query parameters (client_id, redirect_uri, state) — confirms the URL-
  building logic is correct up to the point of actually needing a real,
  registered app to go further
- Find-or-create and account-linking logic, called directly with a fake
  provider profile (the one piece that's genuinely untestable without
  live credentials is the HTTP round-trip to fetch that profile from
  Google/GitHub — everything downstream of receiving it was tested)
- The frontend "Continue with Google" button, clicked for real in a
  headless browser, confirmed to navigate to the correct backend route
  and receive the expected not-configured response

**What was NOT, and cannot be, verified here:** an actual successful
login via a real Google or GitHub account. Register real OAuth apps per
`docs/SETUP.md`, set the credentials, and click through it yourself
before relying on this for a live demo.

## Two Real Bugs Were Found and Fixed During This Work

Documented here rather than swept under the rug:

1. **passlib + bcrypt incompatibility** — the original auth implementation
   used `passlib[bcrypt]`, which crashes on every password hash with newer
   `bcrypt` (4.x+) due to a known version-detection bug in passlib (last
   released 2020, effectively unmaintained). **Fix:** switched to calling
   `bcrypt` directly, which sidesteps the issue entirely. Verified via a
   full register/login cycle after the fix.
2. **FastAPI lifespan events silently skipped in tests** — `TestClient(app)`
   used without the `with` context-manager form does not run FastAPI's
   startup lifespan handler, so the database tables were never created and
   every DB-touching test failed with `no such table: users`. **Fix:**
   migrated from the deprecated `@app.on_event("startup")` to the modern
   `lifespan` context-manager pattern, and updated tests to use
   `with TestClient(app) as client:` (see `tests/test_api.py`). Verified
   both via the test suite and via a separate live-uvicorn smoke test.

## What Was NOT Verified (be aware before relying on it)

- **Neo4j backend** (`src/identity_graph/neo4j_backend.py`) — written
  against the real `neo4j` Python driver API and syntax-checked, but
  **not** run against a live Neo4j instance (no Neo4j server available in
  this environment). Test it yourself with `docker compose up` before
  relying on it for a real deployment.
- **Ethereum wallet tracing** — `api.etherscan.io` is not reachable from
  this environment either, so the success path (with a real API key) was
  not exercised live. The code path mirrors the already-verified Bitcoin
  tracer's structure and the Ethereum error-handling path is covered by
  the same graceful-failure logic, but get your own Etherscan API key and
  test a real lookup before depending on it.
- **Frontend runtime behavior in a browser** — `npm run build` succeeds
  (proving the code compiles and bundles correctly), but the dashboard was
  not exercised in an actual browser against a running API in this
  environment. Run `npm run dev` yourself and click through the login →
  create case → ingest → graph flow before a live demo.
- **Docker Compose stack** — `Dockerfile` and `docker-compose.yml` are
  written correctly to the best of standard practice, but `docker compose
  up` was not run in this environment. Test it locally before relying on
  it for judging day.
- **Rate limiting under real concurrent load** — the slowapi integration
  is wired in and the code path is correct, but it wasn't load-tested.

## Recommended Next Verification Steps (for you to run)

```bash
# 1. Confirm Docker stack works
docker compose up --build
curl http://localhost:8000/health

# 2. Confirm Neo4j backend works
#    (after editing config/config.yaml -> graph.backend: "neo4j")
python scripts/run_pipeline.py --input data/sample/sample_posts.json

# 3. Confirm frontend works against a live API in a real browser
cd frontend && npm run dev
# then click through login -> create case -> ingest -> graph view

# 4. Get a free Etherscan API key and test a real Ethereum trace
curl -X POST http://localhost:8000/trace/wallet \
  -H "Authorization: Bearer <your-token>" \
  -H "Content-Type: application/json" \
  -d '{"address": "0x...", "chain": "ethereum"}'
```
