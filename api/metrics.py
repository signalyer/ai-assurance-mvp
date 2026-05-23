"""Prometheus metrics exposition endpoint.

``GET /api/metrics`` returns the full Prometheus text exposition format
(``text/plain; version=0.0.4``).

Access control:
  - Returns HTTP 404 when the environment variable ``METRICS_ENABLED`` is not
    exactly ``"true"`` (case-sensitive).
  - Returns HTTP 401 when the ``X-Metrics-Token`` header is absent or does not
    match the ``METRICS_TOKEN`` environment variable (constant-time compare via
    ``hmac.compare_digest`` to prevent timing-side-channel token enumeration).
  - Returns HTTP 503 when ``prometheus_client`` is not installed.

This deliberately avoids wiring into the full session/role auth system so that
monitoring scrapers (Prometheus, Azure Monitor) can authenticate with a single
static bearer token without browser cookies.  Document the token in your
secrets store / Key Vault -- never in source.

Session 11 hardening: ``_METRICS_TOKEN`` is cached at module load (mirroring the
``_SECRET`` pattern in ``middleware/hmac_auth.py``).  When the env var is absent
at load time, ``_METRICS_TOKEN`` is ``None`` and ``_token_valid`` returns ``False``
for any input, denying all access.  Post-load env var changes have no effect on
the cached value, eliminating per-request ``os.environ`` access and the
associated TOCTOU window.
"""
from __future__ import annotations

import hmac
import os

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse, Response

router = APIRouter(tags=["observability"])

_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


def _read_metrics_token_env() -> str | None:
    """Read METRICS_TOKEN from environment ONCE at module load.

    Returns:
        The token string, or None if the variable is unset or empty.
    """
    raw = os.environ.get("METRICS_TOKEN", "").strip()
    return raw if raw else None


#: Module-level token cache — read ONCE at import, never per-request.
#: None means the env var was absent or empty at startup → deny all.
_METRICS_TOKEN: str | None = _read_metrics_token_env()


def _metrics_enabled() -> bool:
    """Return True only when METRICS_ENABLED env var is exactly ``"true"``."""
    return os.environ.get("METRICS_ENABLED", "").strip() == "true"


def _token_valid(provided: str) -> bool:
    """Constant-time comparison of *provided* against the cached module-load token.

    Uses ``hmac.compare_digest`` to prevent timing-side-channel enumeration.
    The expected token is read ONCE at module load (``_METRICS_TOKEN``) and
    never re-read from ``os.environ`` on a per-request basis.

    Args:
        provided: The token value from the ``X-Metrics-Token`` request header.

    Returns:
        ``True`` if *provided* matches the cached ``_METRICS_TOKEN`` exactly.
        ``False`` if ``_METRICS_TOKEN`` is None (env var missing at startup) or
        if the comparison fails.
    """
    if _METRICS_TOKEN is None:
        # No token configured at startup -- deny all access rather than allowing
        # blank comparisons.
        return False
    return hmac.compare_digest(
        _METRICS_TOKEN.encode("utf-8"),
        provided.encode("utf-8"),
    )


@router.get("/api/metrics")
async def get_metrics(request: Request) -> Response:
    """Return Prometheus exposition format metrics.

    Gate 1: ``METRICS_ENABLED=true`` must be set.
    Gate 2: ``X-Metrics-Token`` header must match the cached ``_METRICS_TOKEN``
            value (constant-time compare, read once at module load).

    Returns:
        - ``404`` when metrics are disabled.
        - ``401`` when the token is absent or wrong.
        - ``503`` when ``prometheus_client`` is not installed.
        - ``200`` with ``text/plain; version=0.0.4`` body when all gates pass.
    """
    if not _metrics_enabled():
        return PlainTextResponse("metrics disabled", status_code=404)

    provided_token = request.headers.get("X-Metrics-Token", "")
    if not _token_valid(provided_token):
        return PlainTextResponse("unauthorized", status_code=401)

    try:
        import prometheus_client

        output: bytes = prometheus_client.generate_latest()
        return Response(content=output, media_type=_CONTENT_TYPE)
    except ImportError:
        return PlainTextResponse("prometheus_client not installed", status_code=503)
