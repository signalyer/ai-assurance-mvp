"""Usage analytics endpoints. Demo-ciso role only.

Session 41 (Tier 3 sweep, 27a polymorphic-payload exception):
    - Strict Pydantic v2 envelopes (SummaryOut, ActiveSessionsOut, EventsOut)
      with extra="forbid".
    - Nested row models (ActiveSessionRow, EventRow) use extra="allow" because
      session dicts carry variable-keyed metadata (user_agent, ip, geo enrichment)
      and event records are polymorphic by event_type (LOGIN vs PAGE_VIEW vs
      domain events). by_user / top_pages / by_country / totals are bounded
      shapes and stay strict.
    - operation_id prefix `usage_*` (no collision risk; sole usage router).
    - Consumer-coupling grep (38a): static/analytics-usage.html lines 118-120
      consumes all three endpoints. Field reads verified against the response
      shapes below — no consumer breakage.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from itsdangerous import BadSignature, URLSafeTimedSerializer
from pydantic import BaseModel, ConfigDict, Field
import os

from domain import usage_analytics as ua


router = APIRouter(prefix="/api/usage", tags=["usage"])


def _strict() -> ConfigDict:
    return ConfigDict(extra="forbid")


def _polymorphic() -> ConfigDict:
    """27a exception: row carries variable metadata (geo, UA, event-specific keys)."""
    return ConfigDict(extra="allow")


# ---------------------------------------------------------------------------
# Response models — /summary
# ---------------------------------------------------------------------------


class TotalsOut(BaseModel):
    """Aggregate counters in the summary window."""
    model_config = _strict()

    events: int
    logins: int
    page_views: int
    unique_users: int
    active_sessions: int


class ByUserRow(BaseModel):
    """Per-user activity rollup. Shape is bounded (domain.usage_analytics line 302)."""
    model_config = _strict()

    user: str
    logins: int
    page_views: int
    last_seen_utc: str
    last_seen_cst: str
    last_ip: str
    last_city: str


class TopPageRow(BaseModel):
    model_config = _strict()
    path: str
    views: int


class ByCountryRow(BaseModel):
    model_config = _strict()
    country: str
    events: int


class SummaryOut(BaseModel):
    """Response envelope for GET /api/usage/summary."""
    model_config = _strict()

    window_days: int
    now_cst: str
    totals: TotalsOut
    by_user: list[ByUserRow]
    top_pages: list[TopPageRow]
    by_country: list[ByCountryRow]


# ---------------------------------------------------------------------------
# Response models — /active-sessions
# ---------------------------------------------------------------------------


class ActiveSessionRow(BaseModel):
    """One active session.

    `extra="allow"` because the underlying session dict carries variable
    metadata (user_agent, ip, geo enrichment, started_at_utc, etc.) that
    we don't want to drop. Explicit fields cover the read-paths in
    static/analytics-usage.html.
    """
    model_config = _polymorphic()

    session_id: str | None = None
    user: str | None = None
    last_activity_utc: str | None = None
    last_activity_cst: str | None = None
    started_at_cst: str | None = None
    idle_seconds: int | None = None
    expires_in_seconds: int | None = None


class ActiveSessionsOut(BaseModel):
    model_config = _strict()

    now_cst: str
    inactivity_timeout_seconds: int
    count: int
    sessions: list[ActiveSessionRow]


# ---------------------------------------------------------------------------
# Response models — /events
# ---------------------------------------------------------------------------


class EventRow(BaseModel):
    """One audit event (JSONL record).

    `extra="allow"` because events are polymorphic by event_type — LOGIN
    carries ip/city/region/country/user_agent; PAGE_VIEW carries path;
    domain events carry their own payload. Explicit fields are the common
    superset read by static/analytics-usage.html.
    """
    model_config = _polymorphic()

    ts_utc: str | None = None
    ts_cst: str | None = None
    event: str | None = None
    user: str | None = None


class EventsOut(BaseModel):
    model_config = _strict()

    now_cst: str
    window_days: int
    count: int
    events: list[EventRow]


# ---------------------------------------------------------------------------
# Session auth helpers (unchanged from S39)
# ---------------------------------------------------------------------------


def _current_user(request: Request) -> str | None:
    token = request.cookies.get("aigovern_session")
    if not token:
        return None
    secret = os.getenv("SESSION_SECRET", "")
    if not secret:
        return None
    try:
        data = URLSafeTimedSerializer(secret, salt="aigovern-session-v1").loads(
            token, max_age=ua.INACTIVITY_TIMEOUT_S
        )
    except BadSignature:
        return None
    if not isinstance(data, dict):
        return None
    sid = data.get("sid")
    user = data.get("u")
    if not sid or not user or not ua.is_session_active(sid):
        return None
    return user


def _require_ciso(request: Request) -> str:
    user = _current_user(request)
    if user != "demo-ciso":
        raise HTTPException(status_code=403, detail="Analytics is restricted to demo-ciso.")
    return user


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/summary",
    response_model=SummaryOut,
    operation_id="usage_get_summary",
)
async def get_summary(request: Request, days: int = Query(7, ge=1, le=90)) -> SummaryOut:
    """Aggregate usage summary over the last N days."""
    _require_ciso(request)
    raw: dict[str, Any] = ua.summary(days=days)
    return SummaryOut(**raw)


@router.get(
    "/active-sessions",
    response_model=ActiveSessionsOut,
    operation_id="usage_get_active_sessions",
)
async def get_active_sessions(request: Request) -> ActiveSessionsOut:
    """All sessions whose last activity is within the inactivity window."""
    _require_ciso(request)
    sessions = ua.active_sessions()
    return ActiveSessionsOut(
        now_cst=ua.format_cst(ua._utc_iso()),
        inactivity_timeout_seconds=ua.INACTIVITY_TIMEOUT_S,
        count=len(sessions),
        sessions=[ActiveSessionRow(**s) for s in sessions],
    )


@router.get(
    "/events",
    response_model=EventsOut,
    operation_id="usage_get_events",
)
async def get_events(
    request: Request,
    days: int = Query(7, ge=1, le=90),
    event: str = Query("", description="Filter by event type, e.g. LOGIN"),
    user: str = Query("", description="Filter by username"),
    limit: int = Query(500, ge=1, le=5000),
) -> EventsOut:
    """Recent audit events, optionally filtered by event type or user."""
    _require_ciso(request)
    events = ua.read_events(days=days)
    if event:
        events = [e for e in events if e.get("event") == event.upper()]
    if user:
        events = [e for e in events if e.get("user") == user]
    sliced = events[:limit]
    return EventsOut(
        now_cst=ua.format_cst(ua._utc_iso()),
        window_days=days,
        count=len(sliced),
        events=[EventRow(**e) for e in sliced],
    )
