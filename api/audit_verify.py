"""FastAPI router for tamper-evident audit chain endpoints.

Exposes:
  GET /api/audit/verify?window=1000&full=false -- verify the hash chain
  GET /api/audit/events?limit=100&from_index=0 -- paged events with hash fields

Domain logic lives in domain.audit_chain.  This layer handles HTTP concerns only.

Session 08 -- AI Assurance Platform.
Session 10 hardening:
  - GET /api/audit/events now requires role "auditor" or "ciso"
    via Depends(require_role("auditor", "ciso")).
  - Added public_mode: bool query param.  When true, strips subject_id, reason,
    and any scrubbed_prompt field from every event payload before returning.
  - Pagination switched from tail-relative (offset from end) to absolute
    from_index (0-based index into the full ordered event list).
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from middleware.auth import require_role

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/audit", tags=["audit"])

# PII-bearing fields stripped in public_mode
_PUBLIC_MODE_STRIP_FIELDS: frozenset[str] = frozenset(
    {"subject_id", "reason", "scrubbed_prompt"}
)

# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class ChainVerifyResponse(BaseModel):
    """Response from GET /api/audit/verify."""

    model_config = ConfigDict()

    status: str  # "CLEAN" | "BROKEN"
    events_checked: int
    broken_at: str | None = None
    window_start_event_id: str | None = None


class AuditEventsResponse(BaseModel):
    """Response from GET /api/audit/events."""

    model_config = ConfigDict()

    events: list[dict]
    total: int
    limit: int
    from_index: int


# ---------------------------------------------------------------------------
# Lazy domain import helpers
# ---------------------------------------------------------------------------


def _audit_chain():
    """Lazy import of domain.audit_chain; raises 503 if unavailable."""
    try:
        import domain.audit_chain as ac  # type: ignore[import]
        return ac
    except ModuleNotFoundError as exc:
        logger.error("domain.audit_chain not available: %s", exc)
        raise HTTPException(status_code=503, detail="Audit chain domain not available")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _strip_public(event: object) -> object:
    """Return a copy of *event* with PII-bearing fields removed at any depth.

    Recursively walks nested dicts and lists, dropping any key in
    ``_PUBLIC_MODE_STRIP_FIELDS`` wherever it appears. Required because audit
    events nest PII fields inside payload sub-dicts (e.g. RTF_CASCADE_*
    embeds ``subject_id`` inside the event body).

    Args:
        event: Any JSON-serialisable value (dict, list, scalar).

    Returns:
        A deep-stripped copy with sensitive keys removed at every depth.
    """
    if isinstance(event, dict):
        return {
            k: _strip_public(v)
            for k, v in event.items()
            if k not in _PUBLIC_MODE_STRIP_FIELDS
        }
    if isinstance(event, list):
        return [_strip_public(item) for item in event]
    return event


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/verify", response_model=ChainVerifyResponse)
async def verify_chain(
    window: int = Query(1000, ge=1, le=100_000, description="Max events to check from tail"),
    full: bool = Query(False, description="Verify entire event log (overrides window)"),
) -> ChainVerifyResponse:
    """Verify the tamper-evident hash chain over recent events.

    With default window=1000 this checks the last 1000 events against their
    hash chain.  Pass full=true to verify the entire log from genesis.

    Returns status CLEAN or BROKEN.  On BROKEN, broken_at contains the
    event_id of the first hash mismatch.
    """
    logger.info("verify_chain: window=%d full=%s", window, full)
    ac = _audit_chain()

    try:
        result = await asyncio.to_thread(
            ac.verify_chain,
            window=window,
            full=full,
        )
    except Exception as exc:
        logger.error("verify_chain failed: window=%d error=%s", window, str(exc)[:200])
        raise HTTPException(status_code=500, detail=f"Chain verification failed: {exc!s}")

    logger.info(
        "verify_chain: status=%s events_checked=%d broken_at=%s",
        result.status,
        result.events_checked,
        result.broken_at,
    )
    return ChainVerifyResponse(
        status=result.status,
        events_checked=result.events_checked,
        broken_at=result.broken_at,
        window_start_event_id=result.window_start_event_id,
    )


@router.get("/events", response_model=AuditEventsResponse)
async def list_audit_events(
    limit: int = Query(100, ge=1, le=1000, description="Max events to return"),
    from_index: int = Query(0, ge=0, description="Absolute 0-based start index into the full event list"),
    public_mode: bool = Query(
        False,
        description=(
            "When true, strip subject_id, reason, and scrubbed_prompt fields "
            "from every event payload before returning."
        ),
    ),
    _role: None = Depends(require_role("auditor", "ciso")),
) -> AuditEventsResponse:
    """Return a paged slice of the audit event log.

    Pagination uses an absolute ``from_index`` (not tail-relative offset) so
    successive pages are stable as new events are appended.

    Events are returned oldest-first within the requested slice.  Each event
    dict includes event_id, ts, event_type, hash, and prev_hash fields when
    present.  Pre-genesis events (written before Session 08) will have
    hash=null and prev_hash=null.

    When ``public_mode=true``, PII-bearing fields (subject_id, reason,
    scrubbed_prompt) are stripped from every event before returning.

    Requires role: auditor or ciso.
    """
    logger.info(
        "list_audit_events: limit=%d from_index=%d public_mode=%s",
        limit, from_index, public_mode,
    )
    ac = _audit_chain()

    try:
        # read all events then slice by absolute index
        all_events: list[dict] = await asyncio.to_thread(
            ac._read_jsonl,
            ac.EVENTS_FILE,
        )
    except Exception as exc:
        logger.error("list_audit_events failed: error=%s", str(exc)[:200])
        raise HTTPException(status_code=500, detail="Failed to read audit events")

    total = len(all_events)
    sliced = all_events[from_index: from_index + limit]

    if public_mode:
        sliced = [_strip_public(ev) for ev in sliced]

    logger.info(
        "list_audit_events: total=%d from_index=%d returned=%d public_mode=%s",
        total, from_index, len(sliced), public_mode,
    )
    return AuditEventsResponse(
        events=sliced,
        total=total,
        limit=limit,
        from_index=from_index,
    )
