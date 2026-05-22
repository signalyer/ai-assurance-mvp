"""HMAC-SHA-256 request signer for the SignalLayer CLI.

Signature input (newline-delimited):
    {timestamp}\\n{METHOD}\\n{path}\\n{sha256_hex(body)}

Headers produced:
    X-SL-Key-Id      — key identifier
    X-SL-Timestamp   — Unix timestamp (seconds, UTC, as string)
    X-SL-Nonce       — random hex nonce (32 chars)
    X-SL-Signature   — HMAC-SHA-256 hex digest

NEVER log or print the api_key, nonce+key combination, or raw signature.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from typing import Final

# Drift tolerance in seconds — must match middleware/hmac_auth.py
DRIFT_TOLERANCE_S: Final[int] = 300


def _sha256_hex(data: bytes) -> str:
    """Return hex-encoded SHA-256 digest of data."""
    return hashlib.sha256(data).hexdigest()


def sign_request(
    *,
    method: str,
    path: str,
    body: bytes,
    api_key: str,
    key_id: str,
) -> dict[str, str]:
    """Produce HMAC-SHA-256 signature headers for an outgoing request.

    Args:
        method:  HTTP method in UPPER CASE (e.g. "GET", "POST").
        path:    URL path including query string (e.g. "/api/sdk/gate/check/sys-001").
        body:    Raw request body bytes. Pass b"" for bodyless requests.
        api_key: HMAC secret — never logged.
        key_id:  Key identifier included in X-SL-Key-Id header.

    Returns:
        Dict of header name → value to merge into the outgoing request.
    """
    ts = str(int(time.time()))
    nonce = secrets.token_hex(16)
    body_hash = _sha256_hex(body)

    signing_input = f"{ts}\n{method.upper()}\n{path}\n{body_hash}"
    signature = hmac.new(
        api_key.encode("utf-8"),
        signing_input.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return {
        "X-SL-Key-Id": key_id,
        "X-SL-Timestamp": ts,
        "X-SL-Nonce": nonce,
        "X-SL-Signature": signature,
    }
