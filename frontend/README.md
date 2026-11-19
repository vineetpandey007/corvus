# Analyst Dashboard (React + Vite)

A working dashboard for the identity-correlation API: analyst login/
registration, case management, a post-ingestion form, and an interactive
identity graph (Cytoscape.js) with confidence-weighted, color-coded edges.

## Pages
- **/login, /register** — analyst auth (JWT stored in localStorage)
- **/cases** — create a case (with a legal-basis reference) and see your case list
- **/cases/:caseId** — three tabs:
  - **Identity Graph** — interactive graph view of all correlations found so far
  - **Ingest Posts** — add one or more alias/text posts, runs the full
    correlation pipeline (stylometry, PGP, wallet, username) on submit
  - **Case Posts** — decrypted view of everything stored for the case

## Setup

```bash
cd frontend
npm install
npm run dev
```

Runs at `http://localhost:5173` by default, talking to the API at
`http://localhost:8000`. To point at a different API URL, create
`frontend/.env`:

```
VITE_API_BASE_URL=http://localhost:8000
```

## Build for production

```bash
npm run build
```

Outputs static files to `frontend/dist/` — serve these with any static
host (nginx, Vercel, S3+CloudFront, etc.), pointed at your deployed API.

## Notes
- Auth token is stored in `localStorage` for simplicity. For a hardened
  production deployment, consider an httpOnly cookie-based session instead
  to reduce XSS token-theft risk.
- The graph legend colors map to correlation type: stylometry (blue),
  PGP key reuse (red), wallet reuse (orange), username similarity (green).
