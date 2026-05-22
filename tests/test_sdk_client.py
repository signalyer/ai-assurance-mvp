"""Tests for sdk/signallayer/client.py.

Covers:
- HMAC signing produces stable output for fixed inputs
- Retry behaviour (3 attempts on 503)
- 401 response maps to AuthError
- 403 response maps to PolicyDeniedError
- Network error maps to SignalLayerError (no status code)
"""
from __future__ import annotations

import hashlib
import hmac
import sys
import time
import os
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# Ensure sdk/signallayer is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "sdk"))

import httpx

from signallayer.client import (
    Ok,
    Err,
    SignalLayerClient,
    _parse_key,
    _sign_request,
    _map_status_to_error,
)
from signallayer.errors import AuthError, PolicyDeniedError, SignalLayerError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client(api_key: str = "kid:secret") -> SignalLayerClient:
    """Return a client pointed at a fake base URL."""
    return SignalLayerClient(api_key=api_key, base_url="http://fake.local")


def _fixed_response(status_code: int, json_body: dict | None = None, text: str = "") -> MagicMock:
    """Build a mock httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = text or ""
    if json_body is not None:
        resp.json.return_value = json_body
    else:
        resp.json.side_effect = Exception("no json")
    return resp


# ---------------------------------------------------------------------------
# HMAC signing — deterministic for fixed inputs
# ---------------------------------------------------------------------------

class TestHmacSigning:
    def test_sign_request_stable(self) -> None:
        """Same inputs produce identical signature."""
        sig1 = _sign_request(
            key_id="kid",
            secret="mysecret",
            method="POST",
            path="/api/health",
            body=b'{"x":1}',
            ts="1735689600",
            nonce="aabbcc",
        )
        sig2 = _sign_request(
            key_id="kid",
            secret="mysecret",
            method="POST",
            path="/api/health",
            body=b'{"x":1}',
            ts="1735689600",
            nonce="aabbcc",
        )
        assert sig1 == sig2

    def test_sign_request_differs_on_body_change(self) -> None:
        """Different body → different signature."""
        kwargs: dict[str, Any] = dict(
            key_id="kid",
            secret="mysecret",
            method="GET",
            path="/api/x",
            ts="1735689600",
            nonce="nn",
        )
        sig_a = _sign_request(**kwargs, body=b"bodyA")
        sig_b = _sign_request(**kwargs, body=b"bodyB")
        assert sig_a != sig_b

    def test_sign_request_differs_on_ts_change(self) -> None:
        """Different timestamp → different signature."""
        kwargs: dict[str, Any] = dict(
            key_id="kid",
            secret="mysecret",
            method="GET",
            path="/api/x",
            body=b"",
            nonce="nn",
        )
        sig1 = _sign_request(**kwargs, ts="1735689600")
        sig2 = _sign_request(**kwargs, ts="1735689660")
        assert sig1 != sig2

    def test_sign_request_is_hex(self) -> None:
        """Signature is a lowercase hex string of length 64 (SHA-256)."""
        sig = _sign_request(
            key_id="kid",
            secret="s",
            method="GET",
            path="/",
            body=b"",
            ts="1735689600",
            nonce="n",
        )
        assert len(sig) == 64
        assert all(c in "0123456789abcdef" for c in sig)

    def test_sign_request_matches_manual_hmac(self) -> None:
        """Signature matches a manually computed HMAC-SHA-256."""
        body = b'{"test":true}'
        ts = "1748779200"
        method = "POST"
        path = "/api/eval"
        secret = "topsecret"
        body_sha256 = hashlib.sha256(body).hexdigest()
        message = f"{ts}\n{method}\n{path}\n{body_sha256}".encode()
        expected = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()

        result = _sign_request(
            key_id="kid",
            secret=secret,
            method=method,
            path=path,
            body=body,
            ts=ts,
            nonce="ignored_in_message",
        )
        assert result == expected

    def test_parse_key_with_colon(self) -> None:
        """key_id and secret are split on first colon."""
        key_id, secret = _parse_key("mykey:mysecret")
        assert key_id == "mykey"
        assert secret == "mysecret"

    def test_parse_key_without_colon(self) -> None:
        """Bare key → key_id == secret == full key."""
        key_id, secret = _parse_key("barekeyvalue")
        assert key_id == "barekeyvalue"
        assert secret == "barekeyvalue"

    def test_parse_key_multiple_colons(self) -> None:
        """Only the first colon is used as separator."""
        key_id, secret = _parse_key("kid:sec:extra")
        assert key_id == "kid"
        assert secret == "sec:extra"

    def test_headers_contain_required_fields(self) -> None:
        """_build_headers returns all 4 HMAC headers."""
        client = _make_client()
        headers = client._build_headers("GET", "/api/health", b"")
        assert "X-SL-Key-Id" in headers
        assert "X-SL-Timestamp" in headers
        assert "X-SL-Nonce" in headers
        assert "X-SL-Signature" in headers

    def test_headers_key_id_matches_parsed(self) -> None:
        """X-SL-Key-Id matches the key_id portion of the api_key."""
        client = _make_client(api_key="mykid:secret")
        headers = client._build_headers("GET", "/", b"")
        assert headers["X-SL-Key-Id"] == "mykid"

    def test_headers_nonce_is_unique(self) -> None:
        """Two consecutive calls produce different nonces."""
        client = _make_client()
        h1 = client._build_headers("GET", "/", b"")
        h2 = client._build_headers("GET", "/", b"")
        assert h1["X-SL-Nonce"] != h2["X-SL-Nonce"]


# ---------------------------------------------------------------------------
# Retry behaviour
# ---------------------------------------------------------------------------

class TestRetryBehaviour:
    def test_retries_on_503(self) -> None:
        """Client retries up to 3 times on 503 and returns the last Err."""
        client = _make_client()
        resp503 = _fixed_response(503, text="Service Unavailable")

        call_count = 0

        def fake_request(method: str, url: str, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            return resp503

        mock_http = MagicMock()
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_http.request = fake_request

        with patch("signallayer.client.httpx.Client", return_value=mock_http), \
             patch("signallayer.client._exponential_sleep"):
            result = client.get("/api/test")

        assert isinstance(result, Err)
        assert result.status_code == 503
        assert call_count == 3  # exactly 3 attempts

    def test_no_retry_on_400(self) -> None:
        """Client does NOT retry on 400 (non-retryable)."""
        client = _make_client()
        resp400 = _fixed_response(400, text="Bad Request")

        call_count = 0

        def fake_request(method: str, url: str, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            return resp400

        mock_http = MagicMock()
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_http.request = fake_request

        with patch("signallayer.client.httpx.Client", return_value=mock_http):
            result = client.get("/api/test")

        assert call_count == 1

    def test_success_on_second_attempt(self) -> None:
        """Returns Ok after a retried 503 that succeeds on the second try."""
        client = _make_client()
        resp503 = _fixed_response(503, text="error")
        resp200 = _fixed_response(200, json_body={"ok": True})

        responses = [resp503, resp200]
        idx = 0

        def fake_request(method: str, url: str, **kwargs: Any) -> MagicMock:
            nonlocal idx
            r = responses[idx]
            idx += 1
            return r

        mock_http = MagicMock()
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_http.request = fake_request

        with patch("signallayer.client.httpx.Client", return_value=mock_http), \
             patch("signallayer.client._exponential_sleep"):
            result = client.get("/api/test")

        assert isinstance(result, Ok)
        assert result.value == {"ok": True}


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------

class TestErrorMapping:
    def test_401_returns_auth_error(self) -> None:
        """401 response maps to AuthError."""
        client = _make_client()
        resp401 = _fixed_response(401, text="Unauthorized")

        mock_http = MagicMock()
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_http.request = MagicMock(return_value=resp401)

        with patch("signallayer.client.httpx.Client", return_value=mock_http):
            result = client.get("/api/traces")

        assert isinstance(result, Err)
        assert isinstance(result.error, AuthError)
        assert result.status_code == 401

    def test_403_returns_policy_denied_error(self) -> None:
        """403 response maps to PolicyDeniedError."""
        client = _make_client()
        resp403 = _fixed_response(403, text="Forbidden by policy")

        mock_http = MagicMock()
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_http.request = MagicMock(return_value=resp403)

        with patch("signallayer.client.httpx.Client", return_value=mock_http):
            result = client.post("/api/eval/run", json_body={"system_id": "s1"})

        assert isinstance(result, Err)
        assert isinstance(result.error, PolicyDeniedError)
        assert result.status_code == 403

    def test_200_returns_ok(self) -> None:
        """200 response returns Ok with parsed JSON."""
        client = _make_client()
        resp200 = _fixed_response(200, json_body={"status": "healthy"})

        mock_http = MagicMock()
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_http.request = MagicMock(return_value=resp200)

        with patch("signallayer.client.httpx.Client", return_value=mock_http):
            result = client.get("/api/health")

        assert isinstance(result, Ok)
        assert result.value == {"status": "healthy"}
        assert result.status_code == 200

    def test_network_error_returns_err(self) -> None:
        """httpx.RequestError maps to SignalLayerError Err with status_code=0."""
        client = _make_client()

        mock_http = MagicMock()
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_http.request = MagicMock(
            side_effect=httpx.RequestError("Connection refused", request=MagicMock())
        )

        with patch("signallayer.client.httpx.Client", return_value=mock_http), \
             patch("signallayer.client._exponential_sleep"):
            result = client.get("/api/health")

        assert isinstance(result, Err)
        assert result.status_code == 0
        assert isinstance(result.error, SignalLayerError)

    def test_map_status_401(self) -> None:
        """_map_status_to_error(401) returns AuthError."""
        err = _map_status_to_error(401, "Unauthorized")
        assert isinstance(err, AuthError)

    def test_map_status_403(self) -> None:
        """_map_status_to_error(403) returns PolicyDeniedError."""
        err = _map_status_to_error(403, "Denied")
        assert isinstance(err, PolicyDeniedError)

    def test_map_status_500(self) -> None:
        """_map_status_to_error(500) returns base SignalLayerError."""
        err = _map_status_to_error(500, "Internal server error")
        assert type(err) is SignalLayerError


# ---------------------------------------------------------------------------
# Init validation
# ---------------------------------------------------------------------------

class TestInit:
    def test_init_raises_without_api_key(self) -> None:
        """signallayer.init raises ValueError when api_key is missing."""
        import signallayer

        old_key = os.environ.pop("SL_API_KEY", None)
        try:
            with pytest.raises(ValueError, match="api_key"):
                signallayer.init(api_key=None, base_url="http://x")
        finally:
            if old_key is not None:
                os.environ["SL_API_KEY"] = old_key

    def test_init_raises_without_base_url(self) -> None:
        """signallayer.init raises ValueError when base_url is missing."""
        import signallayer

        old_url = os.environ.pop("SL_API_BASE_URL", None)
        try:
            with pytest.raises(ValueError, match="base_url"):
                signallayer.init(api_key="kid:secret", base_url=None)
        finally:
            if old_url is not None:
                os.environ["SL_API_BASE_URL"] = old_url

    def test_init_succeeds_with_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """signallayer.init reads from environment variables."""
        import signallayer

        monkeypatch.setenv("SL_API_KEY", "envkid:envsecret")
        monkeypatch.setenv("SL_API_BASE_URL", "http://env.local")
        signallayer.init()
        assert signallayer._config["base_url"] == "http://env.local"
