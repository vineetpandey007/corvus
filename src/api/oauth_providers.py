"""
Google / GitHub OAuth2 provider configuration and HTTP helpers.

Deliberately implemented with plain `requests` calls rather than an OAuth
client library (authlib, etc.) — the Authorization Code flow for these
two providers is a handful of REST calls, and pulling in a whole library
for that isn't worth the extra dependency weight (same reasoning that led
to removing nltk/web3/pandas/plotly earlier in this project).

CSRF protection uses a signed, short-lived JWT as the `state` parameter
(see create_state_token/verify_state_token) instead of a server-side
session — this avoids needing Starlette's SessionMiddleware (and its own
cookie-secret setup) for the one thing it would be used for here.
"""

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests
from jose import JWTError, jwt

from src.api.auth import SECRET_KEY, ALGORITHM

STATE_TOKEN_EXPIRE_MINUTES = 10


@dataclass
class OAuthProfile:
    subject: str          # provider's stable user id
    email: Optional[str]
    suggested_username: str


@dataclass
class ProviderConfig:
    name: str
    authorize_url: str
    token_url: str
    userinfo_url: str
    scope: str
    client_id_env: str
    client_secret_env: str

    @property
    def client_id(self) -> Optional[str]:
        return os.environ.get(self.client_id_env)

    @property
    def client_secret(self) -> Optional[str]:
        return os.environ.get(self.client_secret_env)

    @property
    def is_configured(self) -> bool:
        return bool(self.client_id and self.client_secret)


PROVIDERS = {
    "google": ProviderConfig(
        name="google",
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        userinfo_url="https://www.googleapis.com/oauth2/v3/userinfo",
        scope="openid email profile",
        client_id_env="GOOGLE_CLIENT_ID",
        client_secret_env="GOOGLE_CLIENT_SECRET",
    ),
    "github": ProviderConfig(
        name="github",
        authorize_url="https://github.com/login/oauth/authorize",
        token_url="https://github.com/login/oauth/access_token",
        userinfo_url="https://api.github.com/user",
        scope="read:user user:email",
        client_id_env="GITHUB_CLIENT_ID",
        client_secret_env="GITHUB_CLIENT_SECRET",
    ),
}


def get_backend_base_url() -> str:
    return os.environ.get("BACKEND_BASE_URL", "http://localhost:8000")


def get_redirect_uri(provider: str) -> str:
    return f"{get_backend_base_url()}/auth/oauth/{provider}/callback"


def create_state_token() -> str:
    """A short-lived, signed nonce used as the OAuth `state` param. Its
    own JWT signature + expiry is the CSRF protection — no server-side
    session storage needed."""
    payload = {
        "purpose": "oauth_state",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=STATE_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def verify_state_token(token: str) -> bool:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("purpose") == "oauth_state"
    except JWTError:
        return False


def build_authorize_url(provider: ProviderConfig, state: str) -> str:
    params = {
        "client_id": provider.client_id,
        "redirect_uri": get_redirect_uri(provider.name),
        "scope": provider.scope,
        "state": state,
        "response_type": "code",
    }
    if provider.name == "google":
        params["access_type"] = "online"
        params["prompt"] = "select_account"
    query = "&".join(f"{k}={requests.utils.quote(str(v))}" for k, v in params.items())
    return f"{provider.authorize_url}?{query}"


def exchange_code_for_token(provider: ProviderConfig, code: str) -> str:
    """POSTs the authorization code to the provider's token endpoint,
    returns the resulting access token. Raises requests.HTTPError on
    failure (caller is responsible for turning that into a clean 502)."""
    data = {
        "client_id": provider.client_id,
        "client_secret": provider.client_secret,
        "code": code,
        "redirect_uri": get_redirect_uri(provider.name),
        "grant_type": "authorization_code",
    }
    resp = requests.post(provider.token_url, data=data, headers={"Accept": "application/json"}, timeout=15)
    resp.raise_for_status()
    token_data = resp.json()
    if "access_token" not in token_data:
        raise ValueError(f"Token exchange response missing access_token: {token_data}")
    return token_data["access_token"]


def fetch_profile(provider: ProviderConfig, access_token: str) -> OAuthProfile:
    """Fetches the provider's userinfo endpoint and normalizes the result
    into a provider-agnostic OAuthProfile."""
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    resp = requests.get(provider.userinfo_url, headers=headers, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    if provider.name == "google":
        return OAuthProfile(
            subject=data["sub"],
            email=data.get("email"),
            suggested_username=(data.get("email", "").split("@")[0] or f"google_{data['sub'][:8]}"),
        )

    # GitHub: /user doesn't always include a (verified, non-private) email
    # — fall back to /user/emails for the primary verified one.
    email = data.get("email")
    if not email:
        email = _fetch_github_primary_email(access_token)
    return OAuthProfile(
        subject=str(data["id"]),
        email=email,
        suggested_username=data.get("login") or f"github_{data['id']}",
    )


def _fetch_github_primary_email(access_token: str) -> Optional[str]:
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    resp = requests.get("https://api.github.com/user/emails", headers=headers, timeout=15)
    if not resp.ok:
        return None
    for entry in resp.json():
        if entry.get("primary") and entry.get("verified"):
            return entry.get("email")
    return None
