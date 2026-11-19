"""
API-level integration tests — exercise the real FastAPI app (register,
login, protected-route rejection, case create/ingest/graph, password
reset, and OTP login) via an in-process TestClient, backed by a throwaway
SQLite DB and app-data directory (see conftest.py).

Uses TestClient as a context manager (`with TestClient(app) as client`) —
required for FastAPI's lifespan startup handler (which creates DB tables)
to actually run; a bare `TestClient(app)` silently skips lifespan events.

Password-reset and OTP tests read the actual token/code out of the dev
email backend's outbox file (see src/utils/email_service.py) rather than
just checking the generic API response — this exercises the full,
real flow end-to-end, not just "it returned 200".
"""

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.rate_limit import limiter
from src.utils.config import get_app_data_dir


@pytest.fixture(scope="module")
def client():
    # The test suite legitimately registers/logs in far more than 5-10
    # times/minute (real accounts per test, run in seconds) — that's the
    # rate limiter correctly doing its job against a *real* client, not a
    # bug. Disable it for this session rather than weakening the actual
    # limits in src/api/routes/auth.py to accommodate test volume.
    limiter.enabled = False
    with TestClient(app) as c:
        yield c
    limiter.enabled = True


def _unique_username() -> str:
    return f"pytest_{uuid.uuid4().hex[:8]}"


def _register(client, username=None, password="TestPassword123!"):
    username = username or _unique_username()
    email = f"{username}@example.com"
    resp = client.post(
        "/auth/register",
        json={"username": username, "email": email, "password": password},
    )
    return username, email, resp


def _latest_outbox_email_to(email: str) -> dict:
    """Read the most recent dev-mode 'sent' email to a given address."""
    outbox_path = get_app_data_dir() / "dev_email_outbox.jsonl"
    matching = []
    with open(outbox_path) as f:
        for line in f:
            record = json.loads(line)
            if record["to"] == email:
                matching.append(record)
    assert matching, f"No dev-outbox email found for {email}"
    return matching[-1]


def test_health_check(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_register_and_login(client):
    username, email, resp = _register(client)
    assert resp.status_code == 201
    assert "access_token" in resp.json()

    resp_by_username = client.post("/auth/login", json={"identifier": username, "password": "TestPassword123!"})
    assert resp_by_username.status_code == 200

    resp_by_email = client.post("/auth/login", json={"identifier": email, "password": "TestPassword123!"})
    assert resp_by_email.status_code == 200


def test_register_duplicate_email_rejected(client):
    username1, email1, resp1 = _register(client)
    assert resp1.status_code == 201

    resp2 = client.post(
        "/auth/register",
        json={"username": _unique_username(), "email": email1, "password": "TestPassword123!"},
    )
    assert resp2.status_code == 400


def test_register_invalid_email_rejected(client):
    resp = client.post(
        "/auth/register",
        json={"username": _unique_username(), "email": "not-an-email", "password": "TestPassword123!"},
    )
    assert resp.status_code == 422


def test_login_wrong_password_rejected(client):
    username, email, _ = _register(client)
    resp = client.post("/auth/login", json={"identifier": username, "password": "WrongPassword"})
    assert resp.status_code == 401


def test_protected_route_requires_auth(client):
    resp = client.get("/cases")
    assert resp.status_code == 401


def test_forgot_password_generic_response_for_unknown_account(client):
    resp = client.post("/auth/forgot-password", json={"identifier": "no_such_user_at_all"})
    assert resp.status_code == 200
    assert "message" in resp.json()


def test_forgot_password_and_reset_flow(client):
    username, email, _ = _register(client)

    resp = client.post("/auth/forgot-password", json={"identifier": email})
    assert resp.status_code == 200

    sent_email = _latest_outbox_email_to(email)
    assert "reset-password" in sent_email["body"]

    link_line = [line for line in sent_email["body"].splitlines() if "reset-password" in line][0]
    token = link_line.strip().split("/")[-1]

    reset_resp = client.post(
        "/auth/reset-password", json={"token": token, "new_password": "BrandNewPassword456!"}
    )
    assert reset_resp.status_code == 200

    old_login = client.post("/auth/login", json={"identifier": username, "password": "TestPassword123!"})
    assert old_login.status_code == 401

    new_login = client.post("/auth/login", json={"identifier": username, "password": "BrandNewPassword456!"})
    assert new_login.status_code == 200


def test_reset_password_token_is_single_use(client):
    username, email, _ = _register(client)
    client.post("/auth/forgot-password", json={"identifier": email})
    sent_email = _latest_outbox_email_to(email)
    link_line = [line for line in sent_email["body"].splitlines() if "reset-password" in line][0]
    token = link_line.strip().split("/")[-1]

    first_use = client.post("/auth/reset-password", json={"token": token, "new_password": "FirstReset123!"})
    assert first_use.status_code == 200

    second_use = client.post("/auth/reset-password", json={"token": token, "new_password": "SecondReset123!"})
    assert second_use.status_code == 400


def test_reset_password_invalid_token_rejected(client):
    resp = client.post(
        "/auth/reset-password", json={"token": "totally-made-up-token", "new_password": "WhateverPass123!"}
    )
    assert resp.status_code == 400


def test_otp_login_flow(client):
    username, email, _ = _register(client)

    req_resp = client.post("/auth/otp/request", json={"identifier": email})
    assert req_resp.status_code == 200

    sent_email = _latest_outbox_email_to(email)
    code_line = [line for line in sent_email["body"].splitlines() if "login code is" in line][0]
    code = code_line.strip().split(":")[-1].strip()
    assert len(code) == 6 and code.isdigit()

    verify_resp = client.post("/auth/otp/verify", json={"identifier": username, "code": code})
    assert verify_resp.status_code == 200
    assert "access_token" in verify_resp.json()


def test_otp_code_is_single_use(client):
    username, email, _ = _register(client)
    client.post("/auth/otp/request", json={"identifier": email})
    sent_email = _latest_outbox_email_to(email)
    code_line = [line for line in sent_email["body"].splitlines() if "login code is" in line][0]
    code = code_line.strip().split(":")[-1].strip()

    first = client.post("/auth/otp/verify", json={"identifier": username, "code": code})
    assert first.status_code == 200

    second = client.post("/auth/otp/verify", json={"identifier": username, "code": code})
    assert second.status_code == 400


def test_otp_wrong_code_rejected(client):
    username, email, _ = _register(client)
    client.post("/auth/otp/request", json={"identifier": email})

    resp = client.post("/auth/otp/verify", json={"identifier": username, "code": "000000"})
    assert resp.status_code == 400


def test_full_case_workflow(client):
    username, email, register_resp = _register(client)
    token = register_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    case_resp = client.post(
        "/cases",
        json={"title": "Pytest Integration Case", "legal_basis": "test-ref"},
        headers=headers,
    )
    assert case_resp.status_code == 201
    case_id = case_resp.json()["case_id"]

    text_a = "This is a fairly long sample post used purely for pytest integration testing purposes and nothing else really." * 2
    text_b = "Something completely different and unrelated goes here for the second alias in this pytest integration test." * 2

    ingest_resp = client.post(
        f"/cases/{case_id}/ingest",
        json={
            "posts": [
                {"alias": "test_alias_a", "text": text_a, "source": "unit-test"},
                {"alias": "test_alias_b", "text": text_b, "source": "unit-test"},
            ]
        },
        headers=headers,
    )
    assert ingest_resp.status_code == 200
    assert ingest_resp.json()["ingested"] == 2

    graph_resp = client.get(f"/cases/{case_id}/graph", headers=headers)
    assert graph_resp.status_code == 200
    assert len(graph_resp.json()["nodes"]) == 2

    posts_resp = client.get(f"/cases/{case_id}/posts", headers=headers)
    assert posts_resp.status_code == 200
    assert posts_resp.json()[0]["text"]

    report_resp = client.get(f"/cases/{case_id}/report", headers=headers)
    assert report_resp.status_code == 200
    assert report_resp.json()["summary"]["total_aliases"] == 2

    txt_resp = client.get(f"/cases/{case_id}/export/txt", headers=headers)
    assert txt_resp.status_code == 200
    assert "CASE REPORT" in txt_resp.text

    query_resp = client.post(f"/cases/{case_id}/query", json={"query": "summarize this case"}, headers=headers)
    assert query_resp.status_code == 200
    assert "2 aliases" in query_resp.json()["answer"]

    suggestions_resp = client.get(f"/cases/{case_id}/suggestions", headers=headers)
    assert suggestions_resp.status_code == 200
    assert isinstance(suggestions_resp.json()["suggestions"], list)

    other_username, other_email, other_resp = _register(client)
    other_token = other_resp.json()["access_token"]
    forbidden_resp = client.get(
        f"/cases/{case_id}/graph", headers={"Authorization": f"Bearer {other_token}"}
    )
    assert forbidden_resp.status_code == 404
