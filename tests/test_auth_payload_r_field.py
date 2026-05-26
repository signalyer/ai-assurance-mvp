"""Tests for the Session 49 cookie payload extension `{"u","sid","r"}`.

ADR-002 / S49 surgical edits in middleware/auth.py:
  - Login writes `r` (role) into the signed cookie.
  - require_role reads `r` directly instead of parsing the username.
  - whoami exposes `role` and derives `is_ciso` from `r`.
  - ALLOW_DEMO_AUTH=false gates POST /api/auth/login.
  - GET /api/auth/config exposes the two auth-path feature flags.

These tests run against a TestClient that mounts the auth router only,
isolating cookie-shape changes from the rest of dashboard.py.
"""

from __future__ import annotations

import bcrypt
import pytest
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient

from middleware import auth as auth_mod


TEST_PASSWORD = "demo-password-123"
TEST_SESSION_SECRET = "test-session-secret-not-prod"


@pytest.fixture
def hashed_password() -> str:
    """bcrypt hash for the canonical test password."""
    return bcrypt.hashpw(TEST_PASSWORD.encode(), bcrypt.gensalt()).decode()


@pytest.fixture
def app_with_auth(monkeypatch: pytest.MonkeyPatch, hashed_password: str) -> FastAPI:
    """Minimal FastAPI app exercising the real auth router + a guarded route."""
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("SESSION_SECRET", TEST_SESSION_SECRET)
    monkeypatch.setenv("DEMO_USER_CISO_HASH", hashed_password)
    monkeypatch.setenv("DEMO_USER_ENGINEER_HASH", hashed_password)
    monkeypatch.setenv("ALLOW_DEMO_AUTH", "true")

    app = FastAPI()
    app.include_router(auth_mod.router)

    @app.get("/protected-ciso", dependencies=[Depends(auth_mod.require_role("ciso"))])
    async def _ciso_only() -> dict:
        return {"ok": True}

    @app.get("/protected-engineer", dependencies=[Depends(auth_mod.require_role("engineer"))])
    async def _eng_only() -> dict:
        return {"ok": True}

    return app


def _login(client: TestClient, username: str) -> dict:
    """Helper: log in via the form endpoint, return response JSON."""
    resp = client.post(
        "/api/auth/login",
        data={"username": username, "password": TEST_PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Login writes `r` into the cookie payload
# ---------------------------------------------------------------------------


def test_bcrypt_login_writes_r_field_for_ciso(app_with_auth: FastAPI) -> None:
    client = TestClient(app_with_auth, base_url="https://testserver")
    _login(client, "demo-ciso")

    # Decode the cookie via the same serializer the login endpoint used.
    token = client.cookies.get(auth_mod.SESSION_COOKIE)
    assert token, "expected session cookie to be set"
    payload = auth_mod._serializer().loads(token)

    assert payload["u"] == "demo-ciso"
    assert payload["r"] == "ciso"
    assert "sid" in payload


def test_bcrypt_login_writes_r_field_for_engineer(app_with_auth: FastAPI) -> None:
    client = TestClient(app_with_auth, base_url="https://testserver")
    _login(client, "demo-engineer")

    token = client.cookies.get(auth_mod.SESSION_COOKIE)
    payload = auth_mod._serializer().loads(token)
    assert payload["u"] == "demo-engineer"
    assert payload["r"] == "engineer"


# ---------------------------------------------------------------------------
# require_role reads `r` (not username)
# ---------------------------------------------------------------------------


def test_require_role_allows_matching_r(app_with_auth: FastAPI) -> None:
    client = TestClient(app_with_auth, base_url="https://testserver")
    _login(client, "demo-ciso")
    resp = client.get("/protected-ciso")
    assert resp.status_code == 200


def test_require_role_rejects_wrong_r(app_with_auth: FastAPI) -> None:
    client = TestClient(app_with_auth, base_url="https://testserver")
    _login(client, "demo-engineer")
    resp = client.get("/protected-ciso")
    assert resp.status_code == 403
    assert resp.json()["detail"] == "insufficient_role"


def test_require_role_rejects_missing_cookie(app_with_auth: FastAPI) -> None:
    client = TestClient(app_with_auth, base_url="https://testserver")
    resp = client.get("/protected-ciso")
    assert resp.status_code == 401


def test_require_role_rejects_cookie_without_r_field(app_with_auth: FastAPI) -> None:
    """Old-shape cookie (pre-S49, no `r` field) → 401, not silent allow."""
    client = TestClient(app_with_auth, base_url="https://testserver")
    # Forge a cookie in the old shape (missing `r`).
    legacy_token = auth_mod._serializer().dumps({"u": "demo-ciso", "sid": "fake-sid"})
    client.cookies.set(auth_mod.SESSION_COOKIE, legacy_token)
    resp = client.get("/protected-ciso")
    assert resp.status_code == 401


def test_middleware_refresh_preserves_r_field(
    app_with_auth: FastAPI, hashed_password: str
) -> None:
    """SessionAuthMiddleware.dispatch re-signs the cookie on every request to
    slide the TTL. Regression guard: that refresh must preserve every field in
    the payload — most importantly `r`, which was added in Session 49.

    Hot-bug history: the initial S49 patch wrote only `{u, sid}` in the
    refresh path, stripping `r` on the very next authenticated request. The
    OIDC callback would issue a valid cookie with role=ciso; the user's
    first page load (findings, which doesn't gate via require_role) would
    succeed but rewrite the cookie without `r`; the next page load on a
    require_role-gated endpoint (audit events) would 401 with
    "unauthorized" — confusing because the user IS authenticated.
    """
    app = app_with_auth
    # Mount the middleware so refresh runs end-to-end.
    app.add_middleware(auth_mod.SessionAuthMiddleware)

    @app.get("/refresh-probe")
    async def _probe() -> dict:
        return {"ok": True}

    client = TestClient(app, base_url="https://testserver")
    _login(client, "demo-ciso")
    # The login response set the cookie with r=ciso. Make ONE authenticated
    # request — this triggers SessionAuthMiddleware to refresh the cookie.
    resp = client.get("/refresh-probe")
    assert resp.status_code == 200

    # The refreshed cookie must still carry `r`.
    refreshed_token = client.cookies.get(auth_mod.SESSION_COOKIE)
    refreshed = auth_mod._serializer().loads(refreshed_token)
    assert refreshed.get("r") == "ciso", (
        f"refresh path stripped `r` from cookie payload — got: {refreshed!r}"
    )

    # And the next gated call should still work.
    resp = client.get("/protected-ciso")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# whoami exposes role and derives is_ciso from r
# ---------------------------------------------------------------------------


def test_whoami_returns_role_field(app_with_auth: FastAPI) -> None:
    client = TestClient(app_with_auth, base_url="https://testserver")
    _login(client, "demo-ciso")
    resp = client.get("/api/auth/whoami")
    assert resp.status_code == 200
    body = resp.json()
    assert body["role"] == "ciso"
    assert body["is_ciso"] is True


def test_whoami_is_ciso_false_for_engineer(app_with_auth: FastAPI) -> None:
    client = TestClient(app_with_auth, base_url="https://testserver")
    _login(client, "demo-engineer")
    body = client.get("/api/auth/whoami").json()
    assert body["role"] == "engineer"
    assert body["is_ciso"] is False


# ---------------------------------------------------------------------------
# ALLOW_DEMO_AUTH gate
# ---------------------------------------------------------------------------


def test_login_returns_403_when_demo_auth_disabled(
    app_with_auth: FastAPI, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALLOW_DEMO_AUTH", "false")
    client = TestClient(app_with_auth, base_url="https://testserver")
    resp = client.post(
        "/api/auth/login",
        data={"username": "demo-ciso", "password": TEST_PASSWORD},
    )
    assert resp.status_code == 403
    assert resp.json() == {"error": "demo_auth_disabled"}


def test_login_still_works_when_demo_auth_explicitly_true(
    app_with_auth: FastAPI, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sanity: setting the env to "true" doesn't accidentally gate the path off."""
    monkeypatch.setenv("ALLOW_DEMO_AUTH", "true")
    client = TestClient(app_with_auth, base_url="https://testserver")
    _login(client, "demo-ciso")  # asserts 200 internally


# ---------------------------------------------------------------------------
# /api/auth/config feature-flag endpoint
# ---------------------------------------------------------------------------


def test_auth_config_reports_demo_enabled_oidc_disabled(
    app_with_auth: FastAPI, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OIDC_TENANT_ID", raising=False)
    monkeypatch.delenv("OIDC_CLIENT_ID", raising=False)
    monkeypatch.delenv("OIDC_CLIENT_SECRET", raising=False)
    client = TestClient(app_with_auth, base_url="https://testserver")
    body = client.get("/api/auth/config").json()
    assert body == {"allow_demo_auth": True, "oidc_enabled": False}


def test_auth_config_reports_oidc_enabled_when_env_present(
    app_with_auth: FastAPI, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OIDC_TENANT_ID", "tenant-guid")
    monkeypatch.setenv("OIDC_CLIENT_ID", "client-guid")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "secret")
    client = TestClient(app_with_auth, base_url="https://testserver")
    body = client.get("/api/auth/config").json()
    assert body["oidc_enabled"] is True


def test_auth_config_reports_demo_disabled(
    app_with_auth: FastAPI, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALLOW_DEMO_AUTH", "false")
    client = TestClient(app_with_auth, base_url="https://testserver")
    body = client.get("/api/auth/config").json()
    assert body["allow_demo_auth"] is False
