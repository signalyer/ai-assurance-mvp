"""Tests for api/sdk_episodes.py — POST /api/sdk/episodes.

S71 Block A. Integration via FastAPI TestClient with HMACAuthMiddleware
applied; ``domain.agent_memory.write_episode`` is monkey-patched so the
test never touches Postgres.

Reuses the HMAC signing helper from ``test_hmac_auth.py`` byte-for-byte
to confirm the SDK middleware contract holds end-to-end on this new
route, not just the dedicated middleware tests.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets as _secrets
import time
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.sdk_episodes import router as sdk_episodes_router
from middleware.hmac_auth import HMACAuthMiddleware

TEST_SECRET = "test-secret-do-not-use-in-prod"
TEST_KEY_ID = "test-key-id"


def _build_app(write_impl) -> FastAPI:
    """Spin up a minimal app with HMAC middleware + the SDK episodes router.

    Args:
        write_impl: callable used to replace ``domain.agent_memory.write_episode``
            inside the router module. Must accept the same kwargs and either
            return a string episode_id or raise.
    """
    # The router imports write_episode at module load; patch the bound name.
    import api.sdk_episodes as mod
    mod.write_episode = write_impl  # type: ignore[attr-defined]

    app = FastAPI()
    app.add_middleware(HMACAuthMiddleware)
    app.include_router(sdk_episodes_router)
    return app


def _sign(method: str, path: str, body: bytes) -> dict[str, str]:
    """Produce a valid HMAC header set for the test key + secret."""
    ts = str(int(time.time()))
    nonce = _secrets.token_hex(16)
    body_hash = hashlib.sha256(body).hexdigest()
    signing_input = f"{ts}\n{method.upper()}\n{path}\n{body_hash}"
    sig = hmac.new(
        TEST_SECRET.encode("utf-8"),
        signing_input.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return {
        "X-SL-Key-Id": TEST_KEY_ID,
        "X-SL-Timestamp": ts,
        "X-SL-Nonce": nonce,
        "X-SL-Signature": sig,
        "Content-Type": "application/json",
    }


@pytest.fixture(autouse=True)
def _hmac_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provide a known HMAC secret + reset nonce cache between tests."""
    monkeypatch.setenv("SL_HMAC_SECRET", TEST_SECRET)
    from middleware import hmac_auth
    hmac_auth._SECRET = TEST_SECRET.encode("utf-8")
    hmac_auth._nonce_cache.clear()


def test_post_episode_signed_returns_201_with_id() -> None:
    """Happy path: signed POST returns 201 + episode_id from the backend."""
    captured: dict[str, Any] = {}

    def fake_write(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "ep-fake-001"

    app = _build_app(fake_write)
    client = TestClient(app, raise_server_exceptions=True)
    body = {
        "workload_id": "azure-architect",
        "prompt": "scrubbed prompt text",
        "response": "scrubbed response text",
        "outcome": "success",
        "metadata": {"vault_id": "v-1", "trace_id": "t-1"},
    }
    body_bytes = json.dumps(body).encode()
    headers = _sign("POST", "/api/sdk/episodes", body_bytes)

    resp = client.post("/api/sdk/episodes", content=body_bytes, headers=headers)

    assert resp.status_code == 201, resp.text
    assert resp.json() == {"episode_id": "ep-fake-001"}
    assert captured["workload_id"] == "azure-architect"
    assert captured["outcome"] == "success"
    assert captured["metadata"]["vault_id"] == "v-1"


def test_post_episode_unsigned_returns_401() -> None:
    """No HMAC headers → 401 from the middleware (route never runs)."""
    app = _build_app(lambda **_: "should-not-be-called")
    client = TestClient(app, raise_server_exceptions=False)

    body = json.dumps({
        "workload_id": "azure-architect",
        "prompt": "p",
        "response": "r",
        "outcome": "success",
    }).encode()

    resp = client.post("/api/sdk/episodes", content=body)
    assert resp.status_code == 401


def test_invalid_outcome_returns_400() -> None:
    """outcome must be in the canonical set; anything else → 400 (pre-write)."""
    called = False

    def fake_write(**_: Any) -> str:
        nonlocal called
        called = True
        return "should-not-be-called"

    app = _build_app(fake_write)
    client = TestClient(app, raise_server_exceptions=True)
    body = {
        "workload_id": "azure-architect",
        "prompt": "p",
        "response": "r",
        "outcome": "bogus",
    }
    body_bytes = json.dumps(body).encode()
    headers = _sign("POST", "/api/sdk/episodes", body_bytes)
    resp = client.post("/api/sdk/episodes", content=body_bytes, headers=headers)

    assert resp.status_code == 400
    assert called is False


def test_value_error_from_backend_returns_400() -> None:
    """SCRUBBER_ENABLED=true + missing vault_id raises ValueError → 400."""
    def fake_write(**_: Any) -> str:
        raise ValueError("metadata is missing 'vault_id'")

    app = _build_app(fake_write)
    client = TestClient(app, raise_server_exceptions=True)
    body = {
        "workload_id": "azure-architect",
        "prompt": "p",
        "response": "r",
        "outcome": "success",
    }
    body_bytes = json.dumps(body).encode()
    headers = _sign("POST", "/api/sdk/episodes", body_bytes)
    resp = client.post("/api/sdk/episodes", content=body_bytes, headers=headers)

    assert resp.status_code == 400
    assert "vault_id" in resp.json()["detail"]


def test_backend_exception_returns_500() -> None:
    """Generic DB failure → 500 with opaque detail (no leak)."""
    def fake_write(**_: Any) -> str:
        raise RuntimeError("connection timed out after 5s")

    app = _build_app(fake_write)
    client = TestClient(app, raise_server_exceptions=False)
    body = {
        "workload_id": "azure-architect",
        "prompt": "p",
        "response": "r",
        "outcome": "success",
    }
    body_bytes = json.dumps(body).encode()
    headers = _sign("POST", "/api/sdk/episodes", body_bytes)
    resp = client.post("/api/sdk/episodes", content=body_bytes, headers=headers)

    assert resp.status_code == 500
    # Opaque: never leaks the underlying timeout message.
    assert resp.json()["detail"] == "episode_write_failed"
