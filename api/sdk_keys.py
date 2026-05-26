"""SDK API-key management endpoints (NOT HMAC-gated).

Session 53. These routes are session-cookie authed (live in the same
SPA session as the operator who registered the AI system). They issue
keys, list them, revoke them, and surface the first-signal polling
endpoint that the onboarding wizard's Verify step consumes.

Distinction from `/api/sdk/*` (HMAC-gated, S09):
- `/api/sdk-keys/*` — operator-facing, session-cookie auth, manages keys.
- `/api/sdk/*`      — SDK-facing, HMAC-signed, makes governed AI calls.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from domain import sdk_keys as _sdk_keys_dom
from domain.repository import list_ai_systems as _list_ai_systems
from middleware.data_mode import filter_by_mode, get_data_mode


router = APIRouter(prefix="/api/sdk-keys", tags=["sdk-keys"])


# ---------------------------------------------------------------------------
# Response / request models
# ---------------------------------------------------------------------------


class IssueRequest(BaseModel):
    """Body for POST /api/sdk-keys."""

    model_config = ConfigDict(extra="forbid")

    ai_system_id: str = Field(..., description="Parent AI system this key belongs to.")


class IssuedKeyOut(BaseModel):
    """Response shape for POST /api/sdk-keys — contains the plaintext secret ONCE.

    The secret is never recoverable after this response is returned. The
    SPA wizard must surface it to the user immediately and discard it
    from memory after display.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    key_id: str
    hmac_secret: str = Field(
        ..., description="Plaintext HMAC secret. Shown ONCE; never stored, never returned again."
    )
    ai_system_id: str
    data_source: str
    issued_by: str
    issued_at: str


class KeySummaryOut(BaseModel):
    """List-view shape — no plaintext, no hash exposed to clients."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key_id: str
    ai_system_id: str
    data_source: str
    issued_by: str
    issued_at: str
    first_seen_at: Optional[str] = None
    revoked_at: Optional[str] = None
    total_calls_24h: int = 0


class KeyListOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    keys: list[KeySummaryOut]
    total: int


class KeyStatusOut(BaseModel):
    """Polling-friendly status payload for the SPA first-signal panel."""

    model_config = ConfigDict(extra="forbid")

    key_id: str
    ai_system_id: str
    issued_at: str
    first_seen_at: Optional[str] = None
    revoked_at: Optional[str] = None
    total_calls_24h: int = 0


class RevokeOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool = True
    key_id: str
    revoked_at: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _actor_from_request(request: Request) -> str:
    """Best-effort actor extraction from the auth session.

    Falls back to `"demo-engineer"` for backward compatibility with the
    Session 16 pattern used elsewhere in the SPA.
    """
    user = None
    try:
        session = getattr(request.state, "session", None)
        if isinstance(session, dict):
            user = session.get("user")
        if user is None:
            scope_session = request.scope.get("session") if hasattr(request, "scope") else None
            if isinstance(scope_session, dict):
                user = scope_session.get("user")
    except Exception:
        user = None
    return user or "demo-engineer"


def _resolve_system_data_source(ai_system_id: str) -> str:
    """Return the parent system's `data_source` ('seed' or 'real').

    Reads from the existing repository helper. Defaults to 'seed' if the
    system can't be found (defensive: don't fail issuance on a bad join,
    but tag the key correctly when we can).
    """
    try:
        rows = _list_ai_systems()
    except Exception:
        return "seed"
    for r in rows:
        # Tolerate dict or Pydantic shape.
        rid = r.get("id") if isinstance(r, dict) else getattr(r, "id", None)
        if rid != ai_system_id:
            continue
        if isinstance(r, dict):
            return r.get("data_source") or "seed"
        return getattr(r, "data_source", None) or "seed"
    return "seed"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=IssuedKeyOut,
    operation_id="sdk_keys_issue",
    status_code=201,
)
async def issue(request: Request, body: IssueRequest) -> IssuedKeyOut:
    """Issue a new SDK key for an AI system. Secret returned ONCE."""
    if not body.ai_system_id or not body.ai_system_id.strip():
        raise HTTPException(status_code=400, detail="ai_system_id required")

    data_source = _resolve_system_data_source(body.ai_system_id)
    actor = _actor_from_request(request)

    record, plaintext = _sdk_keys_dom.issue_key(
        ai_system_id=body.ai_system_id,
        data_source=data_source,  # type: ignore[arg-type]  # narrowed Literal at runtime
        issued_by=actor,
    )

    return IssuedKeyOut(
        id=record.id,
        key_id=record.key_id,
        hmac_secret=plaintext,
        ai_system_id=record.ai_system_id,
        data_source=record.data_source,
        issued_by=record.issued_by,
        issued_at=record.issued_at.isoformat(),
    )


@router.get(
    "",
    response_model=KeyListOut,
    operation_id="sdk_keys_list",
)
async def list_(
    request: Request,
    ai_system_id: str = Query(None, description="Filter to one system's keys."),
    include_revoked: bool = Query(True, description="Include revoked keys."),
) -> KeyListOut:
    """List SDK keys. Honors X-Data-Mode (v1|v2) via the data-mode middleware.

    Note: V2 filter applies to the KEYS themselves (each key inherits
    the parent system's `data_source` at issuance). A V1 client sees all
    keys; a V2 client sees only keys issued against real-mode systems.
    """
    rows = _sdk_keys_dom.list_keys(ai_system_id=ai_system_id, include_revoked=include_revoked)
    filtered = filter_by_mode(rows, get_data_mode(request))

    out = [
        KeySummaryOut(
            id=k.id,
            key_id=k.key_id,
            ai_system_id=k.ai_system_id,
            data_source=k.data_source,
            issued_by=k.issued_by,
            issued_at=k.issued_at.isoformat() if hasattr(k.issued_at, "isoformat") else str(k.issued_at),
            first_seen_at=k.first_seen_at.isoformat() if k.first_seen_at and hasattr(k.first_seen_at, "isoformat") else (k.first_seen_at if isinstance(k.first_seen_at, str) else None),
            revoked_at=k.revoked_at.isoformat() if k.revoked_at and hasattr(k.revoked_at, "isoformat") else (k.revoked_at if isinstance(k.revoked_at, str) else None),
            total_calls_24h=k.total_calls_24h,
        )
        for k in filtered
    ]
    return KeyListOut(keys=out, total=len(out))


@router.get(
    "/{key_id}/status",
    response_model=KeyStatusOut,
    operation_id="sdk_keys_status",
)
async def status(key_id: str) -> KeyStatusOut:
    """Polling endpoint for the SPA first-signal panel.

    Returns 404 if the key doesn't exist. 200 with `first_seen_at: null`
    until the SDK has produced a trace; 200 with the timestamp once it
    has.
    """
    snap = _sdk_keys_dom.status_snapshot(key_id)
    if snap is None:
        raise HTTPException(status_code=404, detail="key not found")
    return KeyStatusOut(**snap)


@router.post(
    "/{key_id}/revoke",
    response_model=RevokeOut,
    operation_id="sdk_keys_revoke",
)
async def revoke(request: Request, key_id: str) -> RevokeOut:
    """Mark a key as revoked. Subsequent HMAC calls fail. Idempotent."""
    actor = _actor_from_request(request)
    updated = _sdk_keys_dom.revoke_key(key_id, actor=actor)
    if updated is None:
        raise HTTPException(status_code=404, detail="key not found")
    revoked_at = (
        updated.revoked_at.isoformat()
        if updated.revoked_at and hasattr(updated.revoked_at, "isoformat")
        else str(updated.revoked_at)
    )
    return RevokeOut(key_id=updated.key_id, revoked_at=revoked_at)
