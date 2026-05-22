"""Tests for middleware/hmac_auth.py — 4 HMAC verification cases."""

from __future__ import annotations

import hashlib
import hmac
import time
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from middleware.hmac_auth import HMACAuthMiddleware, SDK_PREFIX

# ---------------------------------------------------------------------------
# Minimal test app
# ---------------------------------------------------------------------------

_test_app = FastAPI()
_test_app.add_middleware(HMACAuthMiddleware)

TEST_SECRET = "test-secret-do-not-use-in-prod"
TEST_KEY_ID = "test-key-id"


@_test_app.get("/api/sdk/test")
async def _sdk_endpoint() -> dict:
    """Protected SDK endpoint used by tests."""
    return {"ok": True}


@_test_app.post("/api/sdk/test")
async def _sdk_post_endpoint(body: dict = None) -> dict:
    """Protected SDK POST endpoint used by tests."""
    return {"ok": True, "received": body}


@_test_app.get("/api/health")
async def _health() -> dict:
    """Non-SDK endpoint — should NOT require HMAC."""
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_headers(
    method: str,
    path: str,
    body: bytes,
    secret: str = TEST_SECRET,
    ts_override: int | None = None,
    nonce_override: str | None = None,
    sig_override: str | None = None,
) -> dict[str, str]:
    """Build valid (or deliberately broken) HMAC headers."""
    import secrets as _secrets

    ts = str(ts_override if ts_override is not None else int(time.time()))
    nonce = nonce_override or _secrets.token_hex(16)
    body_hash = hashlib.sha256(body).hexdigest()
    signing_input = f"{ts}\n{method.upper()}\n{path}\n{body_hash}"

    sig = hmac.new(
        secret.encode("utf-8"),
        signing_input.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return {
        "X-SL-Key-Id": TEST_KEY_ID,
        "X-SL-Timestamp": ts,
        "X-SL-Nonce": nonce,
        "X-SL-Signature": sig_override or sig,
    }


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _patch_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inject the test secret via env var for every test."""
    monkeypatch.setenv("SL_HMAC_SECRET", TEST_SECRET)


@pytest.fixture(autouse=True)
def _clear_nonce_cache() -> None:
    """Clear nonce cache between tests to prevent replay false positives."""
    from middleware import hmac_auth
    hmac_auth._nonce_cache.clear()


def test_valid_signature_returns_200() -> None:
    """Case (a): A correctly signed request to /api/sdk/* returns 200."""
    client = TestClient(_test_app, raise_server_exceptions=True)
    headers = _make_headers("GET", "/api/sdk/test", b"")
    resp = client.get("/api/sdk/test", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True


def test_drifted_timestamp_returns_401() -> None:
    """Case (b): A timestamp > 300s in the past → 401."""
    client = TestClient(_test_app, raise_server_exceptions=True)
    old_ts = int(time.time()) - 400  # 400s ago — beyond 300s tolerance
    headers = _make_headers("GET", "/api/sdk/test", b"", ts_override=old_ts)
    resp = client.get("/api/sdk/test", headers=headers)
    assert resp.status_code == 401
    assert "unauthorized" in resp.json().get("error", "")


def test_replayed_nonce_returns_401() -> None:
    """Case (c): Sending the same nonce twice → 401 on second request."""
    from middleware import hmac_auth
    client = TestClient(_test_app, raise_server_exceptions=True)
    fixed_nonce = "aabbccddeeff00112233445566778899"

    # First request: should pass
    headers = _make_headers("GET", "/api/sdk/test", b"", nonce_override=fixed_nonce)
    resp1 = client.get("/api/sdk/test", headers=headers)
    assert resp1.status_code == 200, f"First request failed: {resp1.text}"

    # Second request with same nonce: must be rejected
    headers2 = _make_headers("GET", "/api/sdk/test", b"", nonce_override=fixed_nonce)
    resp2 = client.get("/api/sdk/test", headers=headers2)
    assert resp2.status_code == 401, f"Replay should be rejected but got {resp2.status_code}"


def test_tampered_body_returns_401() -> None:
    """Case (d): Signature was computed for different body — tampered body → 401."""
    client = TestClient(_test_app, raise_server_exceptions=True)

    original_body = b'{"data": "original"}'
    tampered_body = b'{"data": "tampered"}'

    # Sign the original body
    headers = _make_headers("POST", "/api/sdk/test", original_body)

    # Send the tampered body with the signature from the original
    resp = client.post(
        "/api/sdk/test",
        content=tampered_body,
        headers=headers,
    )
    assert resp.status_code == 401, f"Tampered body should be rejected but got {resp.status_code}"


def test_non_sdk_path_bypasses_hmac() -> None:
    """Non-/api/sdk/ paths are not guarded by HMACAuthMiddleware."""
    client = TestClient(_test_app, raise_server_exceptions=True)
    # No HMAC headers provided — should still succeed
    resp = client.get("/api/health")
    assert resp.status_code == 200


def test_missing_secret_returns_500(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing SL_HMAC_SECRET env var → 500, never 200."""
    monkeypatch.delenv("SL_HMAC_SECRET", raising=False)
    client = TestClient(_test_app, raise_server_exceptions=False)
    headers = _make_headers("GET", "/api/sdk/test", b"", secret="anything")
    resp = client.get("/api/sdk/test", headers=headers)
    assert resp.status_code == 500
