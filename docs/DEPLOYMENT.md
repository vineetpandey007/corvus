# Deployment Guide

This project runs locally or via Docker Compose out of the box (see
`docs/SETUP.md`). Before deploying it against **real case data**, work
through this checklist — none of it is optional for a real investigation.

## 1. Secrets

- Generate fresh `JWT_SECRET_KEY` and `ENCRYPTION_KEY` values for
  production — never reuse the ones from a dev `.env` or from this repo's
  test fixtures (`tests/conftest.py` uses throwaway values on purpose).
- Store secrets in a proper secrets manager (AWS Secrets Manager, HashiCorp
  Vault, Azure Key Vault, etc.) rather than a `.env` file on a shared
  server.
- **Back up `ENCRYPTION_KEY` separately from the database.** If it's lost,
  all encrypted case-post text is permanently unrecoverable.

## 2. Database

- Switch `DATABASE_URL` to Postgres — SQLite's single-writer model doesn't
  hold up with multiple analysts hitting the API concurrently.
- Put the Postgres instance behind the same network boundary as the API
  (private subnet / VPC), not publicly reachable.
- Set up regular encrypted backups of the database (the `case_posts` table
  is already encrypted at the field level — encrypt the backup itself too,
  for defense in depth).

## 3. Graph Backend

- Switch `config/config.yaml -> graph.backend` to `"neo4j"` for anything
  beyond a single demo session — the default NetworkX backend is in-memory
  and **resets on every API restart**.
- Run Neo4j with authentication enabled (already the default in
  `docker-compose.yml`) and don't expose port 7474/7687 outside your
  private network.

## 4. Auth & Access Control

- Gate `POST /auth/register` behind an admin invite/approval flow before
  going live — see the `TODO` comment in `src/api/routes/auth.py`. Open
  self-registration is fine for a hackathon demo, not for case data.
- Rotate `JWT_SECRET_KEY` periodically; this invalidates all existing
  sessions, so plan for analysts to re-authenticate.
- Consider adding a `User.is_active` flag and an admin-only deactivation
  endpoint for offboarding analysts.
- If you expose `API_SERVICE_KEY` for automation, restrict which IPs can
  use it at the network/firewall level too — a single static key alone is
  weaker than JWT's expiry + per-user scoping.

## 5. Network & Transport

- Terminate TLS in front of the API (a reverse proxy like nginx/Caddy, or
  your cloud provider's load balancer) — never run plain HTTP in
  production, since JWTs and case data would be sent in cleartext
  otherwise.
- Update `CORSMiddleware.allow_origins` in `src/api/main.py` to your real
  deployed frontend origin — the default `localhost` list is dev-only.
- If collecting from real dark-web sources, route only that specific
  traffic through Tor (`TOR_SOCKS_PROXY`) — don't route the whole
  application through Tor, which would slow down and complicate normal API
  traffic unnecessarily.

## 6. Rate Limiting & Abuse Prevention

- The current rate limits (`config.yaml -> security.rate_limit_per_minute`,
  plus tighter login/register limits) are per-IP and in-memory — they
  reset on restart and don't share state across multiple API instances. For
  a multi-instance deployment, back slowapi with a shared Redis store
  instead (`slowapi` supports this via its `storage_uri` option).

## 7. Observability

- The current logger (`src/utils/logger.py`) writes to stderr and to the
  audit log file. In production, ship both to a centralized log system
  (CloudWatch, ELK, Datadog, etc.) rather than relying on local files that
  can be lost if the container is replaced.
- Set up alerting on repeated `401`s (possible credential stuffing) and on
  `wallet_trace` errors (possible block-explorer API key expiry/quota
  issues).

## 8. Legal & Governance

- Before onboarding real cases, get sign-off from your organization's
  legal/cyber-cell team on the framework in `docs/ETHICS_AND_LEGAL.md`.
- Decide and document a data-retention policy (how long case data stays
  in the database after a case closes) and implement a deletion job for
  it — nothing in the current codebase automatically purges old case data.

## 9. Frontend

- Build a static bundle (`npm run build` in `frontend/`) and serve
  `frontend/dist/` from a CDN or static host — don't run Vite's dev server
  in production.
- Consider moving the JWT from `localStorage` to an httpOnly cookie-based
  session if XSS risk is a concern for your deployment environment (see
  the note in `frontend/README.md`).

## 10. What's Already Handled

To be clear about what you're *not* starting from scratch on: bcrypt
password hashing, JWT auth, per-case ownership enforcement, encryption at
rest for case text, rate limiting (in-memory, single-instance), retry/
backoff on external blockchain APIs with graceful failure, a full
chain-of-custody audit log, and a working Docker Compose stack are all
already implemented and tested (see `docs/TESTING_NOTES.md`). This
checklist is about hardening a working system for real deployment, not
about building missing functionality.
