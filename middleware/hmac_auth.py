"""HMAC-SHA-256 authentication middleware for /api/sdk/* endpoints.

Activates ONLY for paths starting with /api/sdk/.
All other paths pass through unchanged.

Verification steps (all must pass; any failure -> 401 with generic message):
  1. Required headers present: X-SL-Key-Id, X-SL-Timestamp, X-SL-Nonce, X-SL-Signature
  2. Timestamp drift <= DRIFT_TOLERANCE_S (300 seconds)
  3. Nonce not replayed (TTL cache evicts entries older than NONCE_CACHE_TTL_S = 600s)
  4. HMAC-SHA-256 signature matches (constant-time compare via hmac.compare_digest)

Secret resolution (S53):
  Look up the secret by X-SL-Key-Id via domain.sdk_keys first. If no
  registered key matches, fall back to the legacy single-tenant
  SL_HMAC_SECRET env var (preserves backward compat for the demo apps
  built before per-system keys existed). If neither resolves -> 401
  (or 500 if no secret is available *at all*).

  After successful HMAC verification, mark_first_seen() is called on
  the resolved key — idempotent, no-op for the env-var fallback path.

Failure policy: fail-closed.
  - Missing SL_HMAC_SECRET AND no registered key match -> 500.
  - Any verification failure -> 401, never 200.
  - Which check failed is NEVER disclosed in the response body.

Environment variables:
  SL_HMAC_SECRET    -- HMAC shared secret. Required; missing -> 500.
  STRICT_HMAC_BOOT  -- If "true", raise at import time when SL_HMAC_SECRET is absent.

Per-process nonce cache
-----------------------
The nonce cache (``_nonce_cache``) is an in-process dict keyed by nonce value.
This is safe only when the application runs as a SINGLE uvicorn worker. If you
scale to multiple workers (gunicorn or container replicas) you MUST migrate the
nonce cache to a shared Redis store; otherwise each worker maintains an
independent cache and replay protection is lost across process boundaries.
See DECISIONS.md Session 10 — Q1: Single uvicorn worker.

Session 10 hardening: secret is read ONCE at module load via ``_read_secret_env()``
and stored in ``_SECRET``. Per-request lookup is a direct local reference — no
repeated ``os.environ`` access, no TOCTOU.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
from typing import Callable

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

# Paths this middleware guards
SDK_PREFIX = "/api/sdk/"

# Maximum allowed timestamp drift in seconds
DRIFT_TOLERANCE_S: int = 300

# Nonce TTL -- entries older than this are evicted on each request
NONCE_CACHE_TTL_S: int = 600

# Hard cap on nonce cache size -- prevents memory exhaustion from a flood of
# unique-nonce requests. When exceeded the cache is fully cleared (intentional:
# we lose replay protection for the prior window but recover memory deterministically).
# NOTE: This cache is per-process. Multi-worker deploys MUST migrate to Redis or
# similar shared store; see DECISIONS.md Session 10 -- Q1.
NONCE_CACHE_MAX: int = 50_000

# Module-level nonce cache: nonce -> unix_timestamp_seen
_nonce_cache: dict[str, int] = {}


# ---------------------------------------------------------------------------
# Module-level secret -- read ONCE at import, never per-request.
# single-worker only; multi-worker requires Redis (see DECISIONS.md Session 10).
# ---------------------------------------------------------------------------


def _read_secret_env() -> bytes | None:
    """Read SL_HMAC_SECRET from environment ONCE at module load.

    Returns:
        UTF-8-encoded secret bytes, or None if the variable is unset/empty.
    """
    raw = os.environ.get("SL_HMAC_SECRET", "").strip()
    if not raw:
        return None
    return raw.encode("utf-8")


#: Module-level secret cache. Populated at import time.
#: single-worker only; multi-worker requires Redis (see DECISIONS.md Session 10).
_SECRET: bytes | None = _read_secret_env()

# Honour STRICT_HMAC_BOOT -- fail loudly at import so misconfiguration is caught
# at startup rather than silently serving 500s on every SDK request.
if os.environ.get("STRICT_HMAC_BOOT", "false").strip().lower() == "true" and _SECRET is None:
    raise RuntimeError(
        "STRICT_HMAC_BOOT=true but SL_HMAC_SECRET is not set. "
        "Set SL_HMAC_SECRET or set STRICT_HMAC_BOOT=false."
    )


def _evict_stale_nonces(now: int) -> None:
    """Remove nonce entries older than NONCE_CACHE_TTL_S from the in-memory cache.

    If the cache exceeds NONCE_CACHE_MAX entries, clear it entirely to prevent
    unbounded memory growth from a flood of unique-nonce attacker requests.

    Args:
        now: Current Unix timestamp (integer seconds).
    """
    cutoff = now - NONCE_CACHE_TTL_S
    stale = [k for k, ts in _nonce_cache.items() if ts < cutoff]
    for k in stale:
        del _nonce_cache[k]
    if len(_nonce_cache) > NONCE_CACHE_MAX:
        logger.warning(
            "HMACAuthMiddleware: nonce cache exceeded %d entries; clearing",
            NONCE_CACHE_MAX,
        )
        _nonce_cache.clear()


def _sha256_hex(data: bytes) -> str:
    """Return hex-encoded SHA-256 digest of *data*.

    Args:
        data: Raw bytes to hash.

    Returns:
        64-character lowercase hex string.
    """
    return hashlib.sha256(data).hexdigest()


class HMACAuthMiddleware(BaseHTTPMiddleware):
    """ASGI middleware that enforces HMAC-SHA-256 auth on /api/sdk/* routes."""

    def __init__(self, app: ASGIApp) -> None:
        """Initialise the middleware.

        Args:
            app: The ASGI application to wrap.
        """
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable):
        """Verify HMAC signature for SDK paths; pass all others through.

        Args:
            request:   Incoming Starlette/FastAPI request.
            call_next: Next middleware or route handler.

        Returns:
            Response from the next handler, or a 401/500 JSONResponse on auth failure.
        """
        path = request.url.path

        # Only guard SDK paths
        if not path.startswith(SDK_PREFIX):
            return await call_next(request)

        # Extract required headers
        key_id = request.headers.get("X-SL-Key-Id", "")
        ts_str = request.headers.get("X-SL-Timestamp", "")
        nonce = request.headers.get("X-SL-Nonce", "")
        provided_sig = request.headers.get("X-SL-Signature", "")

        if not (key_id and ts_str and nonce and provided_sig):
            logger.warning("HMACAuthMiddleware: missing required headers path=%s", path)
            return _generic_401()

        # S53: per-key lookup first; env-var fallback for legacy demos.
        # `_resolve_secret` returns bytes or None. None means neither a
        # registered key nor the env-var secret was usable — that's a
        # config error → 500. Otherwise the caller treats a None return
        # later as 401 (revoked key, etc.) via the matched_via flag.
        secret, matched_via = _resolve_secret_for_key(key_id)
        if secret is None:
            if matched_via == "no_config":
                logger.error(
                    "HMACAuthMiddleware: no per-key match and SL_HMAC_SECRET not configured. "
                    "Returning 500 for path=%s",
                    path,
                )
                return JSONResponse(
                    {"error": "server_configuration_error"},
                    status_code=500,
                )
            # matched_via == "revoked_or_unknown" — fail closed without disclosing why.
            return _generic_401()

        # Timestamp drift check
        try:
            ts = int(ts_str)
        except ValueError:
            logger.warning("HMACAuthMiddleware: non-integer timestamp path=%s", path)
            return _generic_401()

        now = int(time.time())
        _evict_stale_nonces(now)

        if abs(now - ts) > DRIFT_TOLERANCE_S:
            logger.warning(
                "HMACAuthMiddleware: timestamp drift=%d path=%s", abs(now - ts), path
            )
            return _generic_401()

        # Nonce replay check
        if nonce in _nonce_cache:
            logger.warning("HMACAuthMiddleware: replayed nonce path=%s", path)
            return _generic_401()

        # Read body for signature verification
        body = await request.body()
        body_hash = _sha256_hex(body)
        method = request.method.upper()
        signing_input = f"{ts_str}\n{method}\n{path}\n{body_hash}"

        expected_sig = hmac.new(
            secret,
            signing_input.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        # Constant-time comparison -- never short-circuit
        if not hmac.compare_digest(expected_sig, provided_sig):
            logger.warning("HMACAuthMiddleware: signature mismatch path=%s", path)
            return _generic_401()

        # All checks passed -- record nonce
        _nonce_cache[nonce] = now

        # S53: mark first-seen on the resolved per-key record (idempotent).
        # No-op for the env-var fallback path (key_id won't match any
        # registered key, lookup returns None inside mark_first_seen).
        if matched_via == "registered_key":
            try:
                from domain.sdk_keys import mark_first_seen as _mark_first_seen
                _mark_first_seen(key_id)
            except Exception:
                # Never fail the request because of telemetry.
                logger.exception("HMACAuthMiddleware: mark_first_seen failed key_id=%s", key_id)

        return await call_next(request)


def _generic_401() -> JSONResponse:
    """Return a generic 401 that does not disclose which check failed."""
    return JSONResponse({"error": "unauthorized"}, status_code=401)


# ---------------------------------------------------------------------------
# Secret resolution (S53)
# ---------------------------------------------------------------------------


def _resolve_secret_for_key(key_id: str) -> tuple[bytes | None, str]:
    """Resolve the HMAC secret for a given X-SL-Key-Id.

    Order of resolution:
      1. Per-key lookup via domain.sdk_keys. Match + active → secret.
         Match + revoked → (None, "revoked_or_unknown").
      2. No per-key match → fall back to env-var SL_HMAC_SECRET if set.
         Match → (env_secret, "env_fallback").
      3. Neither → (None, "no_config"), surfaces as 500.

    Returns:
        Tuple of (utf-8-encoded secret bytes or None, status string).
    """
    # Lazy import keeps middleware load order safe (domain layer pulls
    # in pydantic; middleware should stay light at import time).
    try:
        from domain.sdk_keys import get_by_key_id, lookup_secret_by_key_id
        registered = get_by_key_id(key_id)
        if registered is not None:
            # Found a registered key. If revoked, fail closed; otherwise
            # use its secret.
            if registered.revoked_at is not None:
                return None, "revoked_or_unknown"
            plain = lookup_secret_by_key_id(key_id)
            if plain is None:
                # Shouldn't happen given we just confirmed not revoked,
                # but treat defensively as unknown.
                return None, "revoked_or_unknown"
            return plain.encode("utf-8"), "registered_key"
    except Exception:
        # Domain layer transient failure (disk read, JSON parse). Don't
        # block legitimate env-var-fallback traffic just because the
        # sdk_keys store is unhappy — log and continue to fallback.
        logger.exception("HMACAuthMiddleware: per-key lookup failed; falling back to env var")

    # Env-var fallback.
    env_secret = _SECRET if _SECRET is not None else _read_secret_env()
    if env_secret is not None:
        return env_secret, "env_fallback"

    return None, "no_config"
