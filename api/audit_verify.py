"""FastAPI router for tamper-evident audit chain endpoints.

Exposes:
  GET /api/audit/verify?window=1000&full=false — verify the hash chain
  GET /api/audit/events?limit=100&offset=0     — paged events with hash fields

Domain logic lives in domain.audit_chain.  This layer handles HTTP concerns only.

Session 08 — AI Assurance Platform.
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/audit", tags=["audit"])

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
    offset: int


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
    offset: int = Query(0, ge=0, description="Number of events to skip from tail"),
) -> AuditEventsResponse:
    """Return a paged slice of the audit event log.

    Events are returned in insertion order (oldest first within the slice).
    Each event dict includes event_id, ts, event_type, hash, and prev_hash fields
    when present.  Pre-genesis events (written before Session 08) will have
    hash=null and prev_hash=null.
    """
    logger.info("list_audit_events: limit=%d offset=%d", limit, offset)
    ac = _audit_chain()

    try:
        # read_chain_tail returns the last N records; we need limit+offset
        # to support pagination from the tail, then slice the requested page.
        fetch_count = limit + offset
        raw: list[dict] = await asyncio.to_thread(
            ac.read_chain_tail,
            fetch_count,
        )
    except Exception as exc:
        logger.error("list_audit_events failed: error=%s", str(exc)[:200])
        raise HTTPException(status_code=500, detail="Failed to read audit events")

    # raw is oldest-first within the fetched tail window
    # slice: skip offset from the front of the fetched window
    sliced = raw[offset: offset + limit]

    logger.info(
        "list_audit_events: fetched=%d returned=%d",
        len(raw),
        len(sliced),
    )
    return AuditEventsResponse(
        events=sliced,
        total=len(raw),
        limit=limit,
        offset=offset,
    )
