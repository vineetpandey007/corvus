"""
FastAPI application entry point — hardened with startup secret validation,
configurable CORS, and forensic security headers.
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from src.api.rate_limit import limiter
from src.api.routes.analysis import router as analysis_router
from src.api.routes.auth import router as auth_router
from src.api.routes.cases import router as cases_router
from src.api.routes.nlp import router as nlp_router
from src.api.routes.oauth import router as oauth_router
from src.api.routes.reports import router as reports_router
from src.db.database import init_db
from src.utils.config import load_config
from src.utils.encryption import validate_encryption_config
from src.utils.logger import get_logger

logger = get_logger()
cfg = load_config()


def _validate_startup_secrets() -> None:
    """Fail fast at boot if required cryptographic keys are missing or invalid."""
    if os.environ.get("TESTING") == "1":
        return

    validate_encryption_config()

    jwt_secret = os.environ.get("JWT_SECRET_KEY", "").strip()
    if not jwt_secret:
        raise RuntimeError(
            "JWT_SECRET_KEY is not set in the environment. Generate one with "
            "`python -c \"import secrets; print(secrets.token_urlsafe(32))\"`."
        )
    if len(jwt_secret) < 32:
        logger.warning("JWT_SECRET_KEY is shorter than 32 characters — rotate to a stronger secret.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _validate_startup_secrets()
    init_db()
    logger.info("Cryptographic configuration verified and database initialized.")
    yield
    logger.info("API shutting down.")


is_production = os.environ.get("ENV", "development").lower() == "production"

app = FastAPI(
    title=cfg["app"]["name"],
    version=cfg["app"]["version"],
    description=(
        "Investigative correlation toolkit for authorized threat-intel "
        "analysts. See /docs for endpoints and docs/ETHICS_AND_LEGAL.md "
        "for required use guidelines."
    ),
    docs_url=None if is_production else "/docs",
    redoc_url=None if is_production else "/redoc",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS: configurable via ALLOWED_ORIGINS comma-separated env var
_raw_origins = os.environ.get("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000")
_allowed_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    if not request.url.path.startswith(("/docs", "/redoc", "/openapi.json")):
        response.headers["Cache-Control"] = "no-store"
    if is_production:
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    return response


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
        "docs": None if is_production else "/docs",
        "note": "Authorized investigative use only — see docs/ETHICS_AND_LEGAL.md",
    }