"""FastAPI router for the Postgres event projection read-side.

Endpoints:
  GET  /api/projection/status           — lag indicator, tailer checkpoint, event counts
  POST /api/projection/replay           — replay events from a given event_id (privileged)
  GET  /api/projection/views/{view}     — paginated SELECT from a materialized table

All SQL is parameterized.  The {view} path parameter is whitelisted against
PROJECTION_VIEWS to prevent SQL injection.

Environment variables:
  DATABASE_URL   Full Postgres connection string (required for live DB use).
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projection", tags=["projection"])

_DATABASE_URL: str | None = os.getenv("DATABASE_URL")

# Allowed roles for the replay endpoint (privileged operation)
_REPLAY_ALLOWED_ROLES: frozenset[str] = frozenset(
    {"demo-ciso", "demo-risk", "demo-engineer"}
)


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class ReplayRequest(BaseModel):
    """Request body for POST /api/projection/replay."""

    model_config = ConfigDict(extra="forbid")

    from_event_id: str | None = None


class ProjectionStatusResponse(BaseModel):
    """Response body for GET /api/projection/status."""

    model_config = ConfigDict(extra="forbid")

    last_event_id: str | None
    tailer_checkpoint_offset: int
    lag_events: int
    lag_seconds: float | None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _open_pg_conn(autocommit: bool = False) -> Any:
    """Open a psycopg2 connection using DATABASE_URL.

    Args:
        autocommit: If True sets connection.autocommit = True.

    Returns:
        Open psycopg2 connection.

    Raises:
        HTTPException 503: If DATABASE_URL is not configured or connection fails.
    """
    if not _DATABASE_URL:
        raise HTTPException(status_code=503, detail="Database not configured")
    try:
        import psycopg2  # type: ignore[import]  # noqa: PLC0415

        conn = psycopg2.connect(_DATABASE_URL)
        conn.autocommit = autocommit
        return conn
    except Exception as exc:
        logger.error("api.projection: DB connection failed: %s", exc)
        raise HTTPException(status_code=503, detail="Database unavailable") from exc


def _read_tailer_checkpoint() -> dict:
    """Read data/projection_tailer_checkpoint.json.

    Returns:
        Dict with ``byte_offset`` (int) and ``last_event_id`` (str | None).
    """
    _DATA_DIR = Path(__file__).resolve().parents[1] / "data"
    cp_path = _DATA_DIR / "projection_tailer_checkpoint.json"
    if not cp_path.exists():
        return {"byte_offset": 0, "last_event_id": None}
    try:
        return json.loads(cp_path.read_text(encoding="utf-8"))
    except Exception:
        return {"byte_offset": 0, "last_event_id": None}


def _current_role(request: Request) -> str:
    """Extract the authenticated role from the session cookie.

    Args:
        request: Incoming FastAPI request.

    Returns:
        Role string, or empty string when not authenticated.
    """
    return request.session.get("role", "") if hasattr(request, "session") else ""


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/status", response_model=ProjectionStatusResponse)
async def projection_status() -> ProjectionStatusResponse:
    """Return projection lag and tailer checkpoint metadata.

    Never includes event payloads in the response.

    Returns:
        ProjectionStatusResponse with lag_events and lag_seconds.
    """
    logger.info("projection_status: entry")
    start = time.monotonic()

    from domain.projection_worker import events_line_count  # noqa: PLC0415

    checkpoint = _read_tailer_checkpoint()
    last_event_id: str | None = checkpoint.get("last_event_id")
    byte_offset: int = checkpoint.get("byte_offset", 0)

    total_lines = events_line_count()

    # Compute approximate lag as lines after checkpoint offset
    _DATA_DIR = Path(__file__).resolve().parents[1] / "data"
    events_path = _DATA_DIR / "events.jsonl"
    projected_lines = 0
    if events_path.exists() and byte_offset > 0:
        # Count lines before checkpoint offset
        with events_path.open("rb") as fh:
            content = fh.read(byte_offset)
        projected_lines = content.count(b"\n")
    elif byte_offset == 0:
        projected_lines = 0

    lag_events = max(0, total_lines - projected_lines)

    elapsed = time.monotonic() - start
    logger.info(
        "projection_status: exit lag_events=%d elapsed_ms=%.0f",
        lag_events, elapsed * 1000,
    )

    return ProjectionStatusResponse(
        last_event_id=last_event_id,
        tailer_checkpoint_offset=byte_offset,
        lag_events=lag_events,
        lag_seconds=None,  # Phase 2: compute from event timestamps
    )


@router.post("/replay")
async def projection_replay(
    body: ReplayRequest,
    request: Request,
) -> JSONResponse:
    """Replay events from events.jsonl into the Postgres projection tables.

    Privileged endpoint: requires demo-ciso, demo-risk, or demo-engineer role.
    Runs synchronously in v1 (Day 10 makes it async with a job queue).

    Args:
        body:    ReplayRequest with optional from_event_id.
        request: FastAPI request (used to check role).

    Returns:
        JSON with events_processed count.
    """
    role = _current_role(request)
    if role not in _REPLAY_ALLOWED_ROLES:
        logger.warning(
            "projection_replay: denied role=%s from_event_id=%s",
            role, body.from_event_id,
        )
        raise HTTPException(status_code=403, detail="Insufficient role for replay")

    logger.info(
        "projection_replay: entry role=%s from_event_id=%s",
        role, body.from_event_id,
    )
    start = time.monotonic()

    from domain.projection_worker import replay  # noqa: PLC0415

    try:
        count = replay(from_event_id=body.from_event_id)
    except Exception as exc:
        logger.error("projection_replay: failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="internal_error") from exc

    elapsed = time.monotonic() - start
    logger.info(
        "projection_replay: exit events_processed=%d elapsed_ms=%.0f",
        count, elapsed * 1000,
    )
    return JSONResponse(content={"events_processed": count, "from_event_id": body.from_event_id})


@router.get("/views/{view}")
async def projection_view(
    view: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
) -> JSONResponse:
    """Return a paginated slice of a projection materialized table.

    The *view* path parameter is whitelisted against PROJECTION_VIEWS to
    prevent SQL injection.  Anything not in the whitelist → 400.

    Args:
        view:      Table name — must be one of PROJECTION_VIEWS.
        page:      1-based page number.
        page_size: Rows per page (max 500).

    Returns:
        JSON with ``rows``, ``page``, ``page_size``, and ``total``.
    """
    from domain.projection import PROJECTION_VIEWS  # noqa: PLC0415

    if view not in PROJECTION_VIEWS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown view '{view}'. Must be one of: {sorted(PROJECTION_VIEWS)}",
        )

    logger.info("projection_view: entry view=%s page=%d page_size=%d", view, page, page_size)
    start = time.monotonic()

    conn = _open_pg_conn(autocommit=True)
    try:
        cur = conn.cursor()

        # Total count — table name is whitelisted above so interpolation is safe
        cur.execute(f"SELECT COUNT(*) FROM {view}")  # noqa: S608
        total: int = cur.fetchone()[0]

        offset = (page - 1) * page_size
        cur.execute(
            f"SELECT * FROM {view} LIMIT %s OFFSET %s",  # noqa: S608
            (page_size, offset),
        )
        columns = [desc[0] for desc in cur.description]
        rows = [dict(zip(columns, row)) for row in cur.fetchall()]
        cur.close()
    except Exception as exc:
        logger.error("projection_view: query failed view=%s: %s", view, exc)
        raise HTTPException(status_code=500, detail="internal_error") from exc
    finally:
        try:
            conn.close()
        except Exception:
            pass

    # Serialise JSONB columns (returned as dicts by psycopg2) to strings for JSON safety
    for row in rows:
        for k, v in row.items():
            if not isinstance(v, (str, int, float, bool, type(None))):
                row[k] = json.dumps(v, default=str)

    elapsed = time.monotonic() - start
    logger.info(
        "projection_view: exit view=%s total=%d page=%d elapsed_ms=%.0f",
        view, total, page, elapsed * 1000,
    )

    return JSONResponse(content={
        "view": view,
        "rows": rows,
        "page": page,
        "page_size": page_size,
        "total": total,
    })
