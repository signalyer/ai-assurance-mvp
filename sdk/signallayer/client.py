"""HTTP client for the SignalLayer platform API.

Provides HMAC-SHA-256 request signing, exponential-backoff retries, and a
typed ``Result[T]`` return union so callers never have to catch raw exceptions
for expected API error states.

Signing scheme (headers added to every request):
    X-SL-Key-Id      : key_id portion of the api_key (everything before the first ':')
    X-SL-Timestamp   : RFC-3339 UTC timestamp (seconds precision)
    X-SL-Nonce       : 16-byte random hex string
    X-SL-Signature   : HMAC-SHA-256 over ``ts:method:path:body_sha256`` (hex digest)

The HMAC secret is the portion of the api_key after the first ':'.  If the
api_key contains no ':', the full api_key is used as both key_id and secret
(dev/test mode).

NEVER log or print the api_key or HMAC secret.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import time
from dataclasses import dataclass
from typing import Generic, TypeVar

import httpx

from .errors import AuthError, PolicyDeniedError, SignalLayerError

logger = logging.getLogger(__name__)

T = TypeVar("T")

# ---------------------------------------------------------------------------
# Typed result union
# ---------------------------------------------------------------------------


@dataclass
class Ok(Generic[T]):
    """Successful result wrapper.

    Attributes:
        value: The deserialized response payload.
        status_code: HTTP status code returned by the server.
    """

    value: T
    status_code: int = 200


@dataclass
class Err:
    """Error result wrapper.

    Attributes:
        error: The exception that caused the failure.
        status_code: HTTP status code (0 if the error occurred before a response).
        message: Short human-readable summary.
    """

    error: SignalLayerError
    status_code: int = 0
    message: str = ""

    def __post_init__(self) -> None:
        """Populate message from error if not provided explicitly."""
        if not self.message:
            self.message = str(self.error)


Result = Ok[T] | Err  # type alias consumed by callers

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_RETRY_BASE_DELAY_S: float = 0.5
_RETRY_MAX_ATTEMPTS: int = 3
_RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})


def _sign_request(
    *,
    key_id: str,
    secret: str,
    method: str,
    path: str,
    body: bytes,
    ts: str,
    nonce: str,
) -> str:
    """Produce an HMAC-SHA-256 signature for the request.

    The signed string is ``ts\nMETHOD\npath\nsha256(body)`` (newline-delimited)
    where ``sha256(body)`` is the lower-case hex digest of the raw request body
    bytes. This canonical string MUST match ``middleware/hmac_auth.py`` and
    ``cli/sl/auth.py`` exactly — any change here must be made in all three.

    Args:
        key_id: Public key identifier (not used in the MAC itself).
        secret: HMAC secret (never logged).
        method: HTTP method in upper-case (e.g. ``"POST"``).
        path: Request path including query string (e.g. ``"/api/health"``).
        body: Raw request body bytes (empty bytes for requests with no body).
        ts: Unix-epoch integer timestamp as a string (e.g. ``"1716364800"``).
        nonce: Random hex nonce for replay prevention.

    Returns:
        Lower-case hex HMAC-SHA-256 digest.
    """
    body_sha256 = hashlib.sha256(body).hexdigest()
    message = f"{ts}\n{method.upper()}\n{path}\n{body_sha256}".encode()
    mac = hmac.new(secret.encode(), message, hashlib.sha256)
    return mac.hexdigest()


def _parse_key(api_key: str) -> tuple[str, str]:
    """Split ``api_key`` into ``(key_id, secret)``.

    If the key contains no ``:`` separator both parts are the full key (dev mode).

    Args:
        api_key: Raw API key string.

    Returns:
        Tuple of ``(key_id, secret)``.
    """
    if ":" in api_key:
        key_id, secret = api_key.split(":", 1)
        return key_id, secret
    return api_key, api_key


def _map_status_to_error(status_code: int, body_text: str) -> SignalLayerError:
    """Convert an HTTP status code to a typed SDK error.

    Args:
        status_code: HTTP response status.
        body_text: Raw response body for inclusion in the error message.

    Returns:
        An appropriate ``SignalLayerError`` subclass instance.
    """
    if status_code == 401:
        return AuthError(f"Authentication failed ({status_code}): {body_text[:200]}")
    if status_code == 403:
        return PolicyDeniedError(f"Policy denied ({status_code}): {body_text[:200]}")
    return SignalLayerError(
        f"Platform returned {status_code}: {body_text[:200]}",
        status_code=status_code,
    )


# ---------------------------------------------------------------------------
# Public client
# ---------------------------------------------------------------------------


class SignalLayerClient:
    """Synchronous HTTP client for the SignalLayer platform API.

    Handles HMAC signing, retries with exponential backoff, and converts
    HTTP error responses into typed ``Result`` values.

    Args:
        api_key: API key in the format ``key_id:secret`` (or bare key in dev mode).
        base_url: Base URL of the platform (e.g. ``"https://aigovern.sandboxhub.co"``).
        tenant: Optional tenant identifier injected into every request header.
        timeout_s: Per-request timeout in seconds (default: 30).
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        tenant: str | None = None,
        timeout_s: float = 30.0,
        key_id: str | None = None,
    ) -> None:
        """Initialise client.  Never logs api_key or secret.

        When ``key_id`` is provided explicitly, it overrides the key_id
        portion parsed from ``api_key``. This supports the S53 per-system
        key model where the wizard issues a ``slk_*`` key_id separately
        from the HMAC secret, and the snippet passes both to ``init()``.
        """
        parsed_id, self._secret = _parse_key(api_key)
        self._key_id = key_id or parsed_id
        self._base_url = base_url.rstrip("/")
        self._tenant = tenant
        self._timeout = httpx.Timeout(timeout_s)
        logger.info(
            "SignalLayerClient initialised",
            extra={"key_id": self._key_id, "base_url": self._base_url, "tenant": tenant},
        )

    # ------------------------------------------------------------------
    # Public request helpers
    # ------------------------------------------------------------------

    def get(self, path: str, params: dict | None = None) -> Result[dict]:
        """Send a signed GET request.

        Args:
            path: API path (e.g. ``"/api/health"``).
            params: Optional query parameters.

        Returns:
            ``Ok[dict]`` on success or ``Err`` on failure.
        """
        return self._request("GET", path, params=params)

    def post(self, path: str, json_body: dict | None = None) -> Result[dict]:
        """Send a signed POST request with a JSON body.

        Args:
            path: API path.
            json_body: Dict to serialise as JSON request body.

        Returns:
            ``Ok[dict]`` on success or ``Err`` on failure.
        """
        return self._request("POST", path, json_body=json_body)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_headers(
        self,
        method: str,
        path: str,
        body: bytes,
    ) -> dict[str, str]:
        """Construct HMAC-signed request headers.

        Args:
            method: HTTP method (upper-case).
            path: Request path.
            body: Raw body bytes.

        Returns:
            Dict of headers to merge into the request.
        """
        ts = str(int(time.time()))
        nonce = secrets.token_hex(16)
        sig = _sign_request(
            key_id=self._key_id,
            secret=self._secret,
            method=method,
            path=path,
            body=body,
            ts=ts,
            nonce=nonce,
        )
        headers: dict[str, str] = {
            "X-SL-Key-Id": self._key_id,
            "X-SL-Timestamp": ts,
            "X-SL-Nonce": nonce,
            "X-SL-Signature": sig,
            "Content-Type": "application/json",
        }
        if self._tenant:
            headers["X-SL-Tenant"] = self._tenant
        return headers

    def _request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        json_body: dict | None = None,
    ) -> Result[dict]:
        """Execute a signed HTTP request with exponential-backoff retries.

        Args:
            method: HTTP method string.
            path: API path (must start with ``/``).
            params: Optional query parameters.
            json_body: Optional JSON payload dict.

        Returns:
            ``Ok[dict]`` or ``Err``.
        """
        url = f"{self._base_url}{path}"
        import json as _json

        body_bytes = _json.dumps(json_body).encode() if json_body else b""

        attempt = 0
        last_result: Result[dict] | None = None

        while attempt < _RETRY_MAX_ATTEMPTS:
            attempt += 1
            t_start = time.monotonic()

            headers = self._build_headers(method, path, body_bytes)

            try:
                with httpx.Client(timeout=self._timeout) as http:
                    response = http.request(
                        method,
                        url,
                        headers=headers,
                        params=params,
                        content=body_bytes if body_bytes else None,
                    )
            except httpx.RequestError as exc:
                duration_ms = int((time.monotonic() - t_start) * 1000)
                logger.warning(
                    "SignalLayerClient request error (attempt %d/%d): %s — %.0fms",
                    attempt,
                    _RETRY_MAX_ATTEMPTS,
                    type(exc).__name__,
                    duration_ms,
                )
                last_result = Err(
                    error=SignalLayerError(f"Network error: {exc}"),
                    status_code=0,
                )
                _exponential_sleep(attempt)
                continue

            duration_ms = int((time.monotonic() - t_start) * 1000)
            status = response.status_code

            if status < 300:
                try:
                    payload: dict = response.json()
                except Exception:
                    payload = {"raw": response.text}
                logger.info(
                    "SignalLayerClient %s %s → %d (%.0fms)",
                    method,
                    path,
                    status,
                    duration_ms,
                )
                return Ok(value=payload, status_code=status)

            if status in _RETRYABLE_STATUS_CODES and attempt < _RETRY_MAX_ATTEMPTS:
                logger.warning(
                    "SignalLayerClient %s %s → %d (attempt %d/%d, retrying)",
                    method,
                    path,
                    status,
                    attempt,
                    _RETRY_MAX_ATTEMPTS,
                )
                last_result = Err(
                    error=_map_status_to_error(status, response.text),
                    status_code=status,
                )
                _exponential_sleep(attempt)
                continue

            # Non-retryable error
            err = _map_status_to_error(status, response.text)
            logger.error(
                "SignalLayerClient %s %s → %d (%.0fms): %s",
                method,
                path,
                status,
                duration_ms,
                str(err)[:200],
            )
            return Err(error=err, status_code=status)

        # Exhausted retries
        assert last_result is not None
        return last_result


def _exponential_sleep(attempt: int) -> None:
    """Sleep with exponential backoff (no jitter for testability).

    Args:
        attempt: Current attempt number (1-based).
    """
    delay = _RETRY_BASE_DELAY_S * (2 ** (attempt - 1))
    time.sleep(delay)
