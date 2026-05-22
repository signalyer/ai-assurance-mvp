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
"""
from __future__ import annotations

import hmac
import os

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse, Response

router = APIRouter(tags=["observability"])

_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


def _metrics_enabled() -> bool:
    """Return True only when METRICS_ENABLED env var is exactly ``"true"``."""
    return os.environ.get("METRICS_ENABLED", "").strip() == "true"


def _token_valid(provided: str) -> bool:
    """Constant-time comparison of *provided* against the configured token.

    Uses ``hmac.compare_digest`` to prevent timing-side-channel enumeration.

    Args:
        provided: The token value from the ``X-Metrics-Token`` request header.

    Returns:
        ``True`` if *provided* matches ``METRICS_TOKEN`` env var exactly.
    """
    expected = os.environ.get("METRICS_TOKEN", "")
    if not expected:
        # No token configured -- deny all access rather than allowing blank comparisons.
        return False
    return hmac.compare_digest(
        expected.encode("utf-8"),
        provided.encode("utf-8"),
    )


@router.get("/api/metrics")
async def get_metrics(request: Request) -> Response:
    """Return Prometheus exposition format metrics.

    Gate 1: ``METRICS_ENABLED=true`` must be set.
    Gate 2: ``X-Metrics-Token`` header must match ``METRICS_TOKEN`` env var
            (constant-time compare).

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
