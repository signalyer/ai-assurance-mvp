"""Usage analytics endpoints. Demo-ciso role only."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from itsdangerous import BadSignature, URLSafeTimedSerializer
import os

from domain import usage_analytics as ua


router = APIRouter(prefix="/api/usage", tags=["usage"])


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


@router.get("/summary")
async def get_summary(request: Request, days: int = Query(7, ge=1, le=90)) -> dict:
    _require_ciso(request)
    return ua.summary(days=days)


@router.get("/active-sessions")
async def get_active_sessions(request: Request) -> dict:
    _require_ciso(request)
    sessions = ua.active_sessions()
    return {
        "now_cst": ua.format_cst(ua._utc_iso()),
        "inactivity_timeout_seconds": ua.INACTIVITY_TIMEOUT_S,
        "count": len(sessions),
        "sessions": sessions,
    }


@router.get("/events")
async def get_events(
    request: Request,
    days: int = Query(7, ge=1, le=90),
    event: str = Query("", description="Filter by event type, e.g. LOGIN"),
    user: str = Query("", description="Filter by username"),
    limit: int = Query(500, ge=1, le=5000),
) -> dict:
    _require_ciso(request)
    events = ua.read_events(days=days)
    if event:
        events = [e for e in events if e.get("event") == event.upper()]
    if user:
        events = [e for e in events if e.get("user") == user]
    return {
        "now_cst": ua.format_cst(ua._utc_iso()),
        "window_days": days,
        "count": len(events),
        "events": events[:limit],
    }
