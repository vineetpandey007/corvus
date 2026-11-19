"""
Google / GitHub OAuth login routes.

GET /auth/oauth/{provider}/login     -> redirects the browser to the
                                         provider's consent screen
GET /auth/oauth/{provider}/callback  -> provider redirects back here with
                                         ?code=...&state=...; this
                                         exchanges the code, finds-or-
                                         creates a local User, issues our
                                         own JWT, and redirects to the
                                         frontend with it

Both routes return a clean error (not a 500) when the requested
provider's credentials aren't configured in .env — the app runs fine
without them; OAuth just stays inactive until GOOGLE_CLIENT_ID/SECRET or
GITHUB_CLIENT_ID/SECRET are set. See docs/SETUP.md.
"""

import secrets as pysecrets

import requests as requests_lib
from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from src.db.database import SessionLocal
from src.db.models import User, UserRole
from src.api.auth import create_access_token, hash_password
from src.api.oauth_providers import (
    PROVIDERS,
    create_state_token,
    verify_state_token,
    build_authorize_url,
    exchange_code_for_token,
    fetch_profile,
)
from src.utils.config import load_config
from src.utils.logger import audit_log, get_logger

router = APIRouter(prefix="/auth/oauth", tags=["oauth"])
logger = get_logger()

FRONTEND_BASE_URL = load_config().get("app", {}).get("frontend_base_url", "http://localhost:5173")


def _get_provider(provider: str):
    config = PROVIDERS.get(provider)
    if not config:
        raise HTTPException(status_code=404, detail=f"Unknown OAuth provider: {provider}")
    return config


@router.get("/{provider}/login")
def oauth_login(provider: str):
    config = _get_provider(provider)
    if not config.is_configured:
        raise HTTPException(
            status_code=501,
            detail=(
                f"{config.name.title()} login isn't configured on this server — "
                f"set {config.client_id_env} and {config.client_secret_env} in .env."
            ),
        )
    state = create_state_token()
    return RedirectResponse(build_authorize_url(config, state))


@router.get("/{provider}/callback")
def oauth_callback(provider: str, code: str = None, state: str = None, error: str = None):
    config = _get_provider(provider)

    if error:
        return RedirectResponse(f"{FRONTEND_BASE_URL}/#/login?oauth_error={error}")
    if not code or not state or not verify_state_token(state):
        return RedirectResponse(f"{FRONTEND_BASE_URL}/#/login?oauth_error=invalid_state")
    if not config.is_configured:
        raise HTTPException(status_code=501, detail=f"{config.name.title()} login isn't configured on this server.")

    try:
        access_token = exchange_code_for_token(config, code)
        profile = fetch_profile(config, access_token)
    except (requests_lib.RequestException, ValueError, KeyError) as e:
        logger.error(f"OAuth callback failed for {provider}: {e}")
        return RedirectResponse(f"{FRONTEND_BASE_URL}/#/login?oauth_error=provider_error")

    db: Session = SessionLocal()
    try:
        user = _find_or_create_user(db, provider, profile)
        jwt_token = create_access_token(subject=user.username, role=user.role.value)
        audit_log(action="oauth_login", actor=user.username, details={"provider": provider})
    finally:
        db.close()

    return RedirectResponse(f"{FRONTEND_BASE_URL}/#/oauth-callback?token={jwt_token}")


def _find_or_create_user(db: Session, provider: str, profile) -> User:
    oauth_subject = f"{provider}:{profile.subject}"

    user = db.query(User).filter(User.oauth_subject == oauth_subject).first()
    if user:
        return user

    # Link to an existing account with the same (verified-by-provider) email
    if profile.email:
        user = db.query(User).filter(User.email == profile.email).first()
        if user:
            user.oauth_provider = provider
            user.oauth_subject = oauth_subject
            db.commit()
            db.refresh(user)
            return user

    username = _unique_username(db, profile.suggested_username)
    user = User(
        username=username,
        email=profile.email,
        # OAuth-only accounts still get a real (random, never-disclosed)
        # password hash rather than a nullable column — see models.py.
        hashed_password=hash_password(pysecrets.token_urlsafe(32)),
        role=UserRole.analyst,
        oauth_provider=provider,
        oauth_subject=oauth_subject,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _unique_username(db: Session, base: str) -> str:
    base = (base or "user").lower().replace(" ", "_")[:50] or "user"
    candidate = base
    suffix = 1
    while db.query(User).filter(User.username == candidate).first():
        suffix += 1
        candidate = f"{base}{suffix}"
    return candidate
