"""
FastAPI application entry point.

Run with:
    uvicorn src.api.main:app --reload --port 8000

Interactive docs at:
    http://localhost:8000/docs

Required before first run (see .env.example / docs/SETUP.md):
    - JWT_SECRET_KEY
    - ENCRYPTION_KEY
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from src.api.rate_limit import limiter
from src.api.routes.analysis import router as analysis_router
from src.api.routes.auth import router as auth_router
from src.api.routes.oauth import router as oauth_router
from src.api.routes.cases import router as cases_router
from src.api.routes.reports import router as reports_router
from src.api.routes.nlp import router as nlp_router
from src.db.database import init_db
from src.utils.config import load_config
from src.utils.logger import get_logger

logger = get_logger()
cfg = load_config()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("Database tables ensured. API starting up.")
    yield
    logger.info("API shutting down.")


app = FastAPI(
    title=cfg["app"]["name"],
    version=cfg["app"]["version"],
    description=(
        "Investigative correlation toolkit for authorized threat-intel "
        "analysts. See /docs for endpoints and docs/ETHICS_AND_LEGAL.md "
        "for required use guidelines."
    ),
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS: restrict to the frontend dev server / your deployed dashboard origin.
# Update allow_origins for production rather than leaving it wide open.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(oauth_router)
app.include_router(cases_router)
app.include_router(reports_router)
app.include_router(nlp_router)
app.include_router(analysis_router)


rate_limit_per_minute = cfg.get("security", {}).get("rate_limit_per_minute", 60)


@app.get("/health")
@limiter.limit(f"{rate_limit_per_minute}/minute")
def health(request: Request):
    return {"status": "ok"}


@app.get("/")
@limiter.limit(f"{rate_limit_per_minute}/minute")
def root(request: Request):
    return {
        "message": f"{cfg['app']['name']} API is running.",
        "docs": "/docs",
        "note": "Authorized investigative use only — see docs/ETHICS_AND_LEGAL.md",
    }
