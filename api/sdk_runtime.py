"""SDK-facing runtime endpoints — HMAC-signed, no session cookie.

S55 #1 — closes F-008 (POC-RETROSPECTIVE.md): the platform documented
`/api/sdk/*` as the canonical HMAC-gated surface back in S09, but no
actual routes had ever been mounted under that prefix. The S53 wizard's
"Verify Signal" step polls `first_seen_at` waiting for an HMAC-signed
call from the issued key — which can never arrive without at least one
endpoint under `/api/sdk/`.

This module ships the minimum: `GET /api/sdk/health`. The HMAC middleware
(middleware/hmac_auth.py) calls `domain.sdk_keys.mark_first_seen()` for
the resolved key BEFORE dispatching to the route handler, so any 200
response on any `/api/sdk/*` path satisfies the wizard's gate.

Distinction from `/api/sdk-keys/*` (operator-facing, session-cookie auth):
- `/api/sdk-keys/*` — operator manages keys (issue, status, revoke)
- `/api/sdk/*`      — SDK-facing, HMAC-signed, agent makes governed calls
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict


router = APIRouter(prefix="/api/sdk", tags=["sdk-runtime"])


class SdkHealthOut(BaseModel):
    """Health-probe response. Stable across versions."""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    service: str = "aigovern-engine"


@router.get(
    "/health",
    response_model=SdkHealthOut,
    operation_id="sdk_runtime_health",
)
async def health() -> SdkHealthOut:
    """HMAC-signed health probe.

    Authentication is performed by HMACAuthMiddleware before this handler
    runs — the middleware also calls `domain.sdk_keys.mark_first_seen()`
    for the resolved key on success. Reaching this handler at all means
    the caller is a recognized SDK key and `first_seen_at` is now set.
    """
    return SdkHealthOut(ok=True)
