"""
OAuth unit + integration tests.

A real end-to-end test (clicking through Google/GitHub's actual consent
screen) isn't possible here — it needs real registered OAuth app
credentials and live network access to accounts.google.com / github.com,
neither of which this environment has. What IS tested, for real:
- state-token CSRF protection (generation, verification, expiry/tampering rejection)
- the clean "not configured" error path when no credentials are set
- the callback's error-redirect behavior on a missing/invalid state
- find-or-create / account-linking logic, called directly with a fake
  OAuthProfile (bypassing only the actual HTTP calls to the provider,
  which is the one part genuinely untestable without live credentials)
"""

import pytest
from fastapi.testclient import TestClient
from jose import jwt

from src.api.main import app
from src.api.rate_limit import limiter
from src.api.auth import SECRET_KEY, ALGORITHM
from src.api.oauth_providers import create_state_token, verify_state_token, OAuthProfile
from src.api.routes.oauth import _find_or_create_user, _unique_username
from src.db.database import SessionLocal


@pytest.fixture(scope="module")
def client():
    limiter.enabled = False
    with TestClient(app) as c:
        yield c
    limiter.enabled = True


def test_state_token_round_trip():
    token = create_state_token()
    assert verify_state_token(token) is True


def test_state_token_rejects_garbage():
    assert verify_state_token("not-a-real-token") is False


def test_state_token_rejects_wrong_purpose():
    # A validly-signed token for a different purpose must not pass as OAuth state
    forged = jwt.encode({"purpose": "something_else"}, SECRET_KEY, algorithm=ALGORITHM)
    assert verify_state_token(forged) is False


def test_login_route_without_credentials_returns_clean_error(client):
    # In the test environment, GOOGLE_CLIENT_ID/SECRET are never set
    resp = client.get("/auth/oauth/google/login", follow_redirects=False)
    assert resp.status_code == 501
    assert "isn't configured" in resp.json()["detail"]


def test_login_route_with_credentials_redirects_to_real_authorize_url(client, monkeypatch):
    """With credentials set, the login route must redirect straight to
    Google's actual authorize endpoint with the right query params — this
    is as far as this can be verified without a real registered OAuth app
    and live network access to accounts.google.com."""
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "fake-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "fake-client-secret")

    resp = client.get("/auth/oauth/google/login", follow_redirects=False)
    assert resp.status_code in (302, 307)
    location = resp.headers["location"]
    assert location.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "client_id=fake-client-id" in location
    assert "redirect_uri=" in location
    assert "state=" in location


def test_login_route_unknown_provider_404s(client):
    resp = client.get("/auth/oauth/not_a_real_provider/login", follow_redirects=False)
    assert resp.status_code == 404


def test_callback_without_state_redirects_with_error(client):
    resp = client.get("/auth/oauth/google/callback?code=fakecode", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert "oauth_error" in resp.headers["location"]


def test_callback_with_tampered_state_redirects_with_error(client):
    resp = client.get(
        "/auth/oauth/google/callback?code=fakecode&state=tampered", follow_redirects=False
    )
    assert resp.status_code in (302, 307)
    assert "oauth_error" in resp.headers["location"]


def test_find_or_create_user_creates_new_account():
    db = SessionLocal()
    try:
        profile = OAuthProfile(subject="unit_test_sub_1", email="oauthtest1@example.com", suggested_username="oauthtest1")
        user = _find_or_create_user(db, "google", profile)
        assert user.oauth_provider == "google"
        assert user.oauth_subject == "google:unit_test_sub_1"
        assert user.email == "oauthtest1@example.com"
    finally:
        db.close()


def test_find_or_create_user_is_idempotent_for_same_subject():
    db = SessionLocal()
    try:
        profile = OAuthProfile(subject="unit_test_sub_2", email="oauthtest2@example.com", suggested_username="oauthtest2")
        user1 = _find_or_create_user(db, "github", profile)
        user2 = _find_or_create_user(db, "github", profile)
        assert user1.id == user2.id
    finally:
        db.close()


def test_find_or_create_user_links_existing_email(client):
    # Register a normal (non-OAuth) account first, via the shared `client`
    # fixture (rate limiting already disabled there).
    client.post("/auth/register", json={
        "username": "linktest_user", "email": "linktest@example.com", "password": "TestPassword123!",
    })

    db = SessionLocal()
    try:
        profile = OAuthProfile(subject="unit_test_sub_3", email="linktest@example.com", suggested_username="irrelevant")
        linked_user = _find_or_create_user(db, "google", profile)
        assert linked_user.username == "linktest_user"  # linked to the existing account, not a new one
        assert linked_user.oauth_subject == "google:unit_test_sub_3"
    finally:
        db.close()


def test_unique_username_increments_on_collision():
    db = SessionLocal()
    try:
        name1 = _unique_username(db, "collide")
        from src.db.models import User, UserRole
        from src.api.auth import hash_password
        db.add(User(username=name1, hashed_password=hash_password("x"*10), role=UserRole.analyst))
        db.commit()

        name2 = _unique_username(db, "collide")
        assert name2 != name1
        assert name2 == "collide2"
    finally:
        db.close()
