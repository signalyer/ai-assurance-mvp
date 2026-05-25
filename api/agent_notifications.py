"""FastAPI SSE endpoint for Postgres LISTEN/NOTIFY agent notifications — Session 07.

Endpoint:
    GET /api/agents/{agent_id}/listen

Opens a long-lived Server-Sent Events stream backed by Postgres LISTEN on the
channel `agent_update_{agent_id}`. When domain.agent_subscribers.notify_subscribers_on_publish()
sends NOTIFY, all connected clients receive the event within <100ms.

Keep-alive: yields `: keepalive` comment every 25s to prevent proxy timeouts.
Client disconnect: connection cancels cleanly; Postgres connection is closed.

Postgres connection reuse: uses a dedicated psycopg2 connection in poll mode
(not from the SQLAlchemy pool) so LISTEN does not hold the shared pool.

OpenAPI typing — Session 38 (sweep router 14/40):
    The single GET route is an SSE stream returning StreamingResponse. Because
    the wire format is a never-ending text/event-stream (not a discrete JSON
    body), attaching a JSON response schema would be misleading and incorrect.
    The route therefore carries only an operation identifier and is intentionally
    left bare per the project's compound 26a rule for streaming responses.
    No SPA consumers query this route's schema — confirmed via grep of static/
    and team-portal/src/.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import select
import time
from collections.abc import AsyncGenerator
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["agent-notifications"])

_KEEPALIVE_INTERVAL_S = 25
_POLL_TIMEOUT_S = 1.0  # psycopg2 select() timeout per iteration


# ---------------------------------------------------------------------------
# Postgres LISTEN helper (runs in a thread pool worker)
# ---------------------------------------------------------------------------

def _get_pg_connection():  # type: ignore[return]
    """Open a dedicated psycopg2 connection for LISTEN.

    Uses DATABASE_URL env var. Raises RuntimeError if not configured.
    Raises ImportError if psycopg2 is not installed (already in requirements.txt).
    """
    import psycopg2  # type: ignore[import]

    db_url = os.getenv("DATABASE_URL", "").strip()
    if not db_url:
        raise RuntimeError("DATABASE_URL is not set; cannot open Postgres LISTEN connection")

    # autocommit must be True for LISTEN to work outside a transaction
    conn = psycopg2.connect(db_url)
    conn.set_isolation_level(0)  # ISOLATION_LEVEL_AUTOCOMMIT
    return conn


# ---------------------------------------------------------------------------
# SSE generator (async, runs in event loop — thread does the blocking poll)
# ---------------------------------------------------------------------------

async def _sse_listen_generator(agent_id: str) -> AsyncGenerator[str, None]:
    """Yield Server-Sent Events for a Postgres LISTEN channel.

    Yields:
        event: agent_update
        data: {"agent_id": "...", "new_version_id": "..."}

    or

        : keepalive

    every 25 seconds.
    """
    channel = f"agent_update_{agent_id}"
    logger.info("sse.listen.enter agent_id=%s channel=%s", agent_id, channel)

    # Open a dedicated connection in a thread (blocking I/O)
    try:
        conn = await asyncio.to_thread(_get_pg_connection)
    except RuntimeError as exc:
        # Don't leak internal exception messages to the client
        logger.error("sse.listen.pg_connect_failed agent_id=%s error=%s", agent_id, str(exc))
        yield f"event: error\ndata: {json.dumps({'error': 'Connection unavailable'})}\n\n"
        return
    except Exception as exc:
        logger.error("sse.listen.pg_connect_failed agent_id=%s error=%s", agent_id, str(exc))
        yield f"event: error\ndata: {json.dumps({'error': 'Connection unavailable'})}\n\n"
        return

    # Register LISTEN on the channel. Use psycopg2.extensions.quote_ident so the
    # identifier is safely quoted even if upstream sanitisation is ever bypassed.
    try:
        from psycopg2.extensions import quote_ident
        cur = conn.cursor()
        safe_channel = quote_ident(channel, conn)
        cur.execute(f"LISTEN {safe_channel};")  # noqa: S608 — quote_ident makes this identifier-safe
    except Exception as exc:
        logger.error("sse.listen.pg_listen_failed agent_id=%s error=%s", agent_id, str(exc))
        try:
            conn.close()
        except Exception:
            pass
        yield f"event: error\ndata: {json.dumps({'error': 'LISTEN registration failed'})}\n\n"
        return

    last_keepalive = time.monotonic()

    try:
        while True:
            # Non-blocking poll in a thread so we don't block the event loop
            try:
                notifications = await asyncio.to_thread(_poll_notifications, conn, _POLL_TIMEOUT_S)
            except asyncio.CancelledError:
                logger.info("sse.listen.cancelled agent_id=%s", agent_id)
                break
            except Exception as exc:
                logger.error("sse.listen.poll_error agent_id=%s error=%s", agent_id, str(exc)[:200])
                break

            for notify in notifications:
                payload_str = notify.payload or ""
                try:
                    payload = json.loads(payload_str) if payload_str else {}
                except json.JSONDecodeError:
                    payload = {"raw": payload_str}

                payload.setdefault("agent_id", agent_id)
                event_data = json.dumps(payload)
                logger.info(
                    "sse.listen.notify agent_id=%s channel=%s payload_len=%d",
                    agent_id,
                    channel,
                    len(event_data),
                )
                yield f"event: agent_update\ndata: {event_data}\n\n"

            # Keepalive
            now = time.monotonic()
            if now - last_keepalive >= _KEEPALIVE_INTERVAL_S:
                yield ": keepalive\n\n"
                last_keepalive = now

    except asyncio.CancelledError:
        logger.info("sse.listen.cancelled agent_id=%s (outer)", agent_id)
    finally:
        try:
            conn.close()
        except Exception:
            pass
        logger.info("sse.listen.exit agent_id=%s", agent_id)


def _poll_notifications(conn, timeout_s: float) -> list:  # type: ignore[return]
    """Poll a psycopg2 connection for LISTEN notifications.

    Runs in a thread. Returns a list of Notify objects (may be empty).
    """
    ready = select.select([conn], [], [], timeout_s)
    if ready[0]:
        conn.poll()
        notes = list(conn.notifies)
        conn.notifies.clear()
        return notes
    return []


# ---------------------------------------------------------------------------
# Sanitise agent_id for use as Postgres identifier
# ---------------------------------------------------------------------------

def _sanitise_agent_id_for_channel(agent_id: str) -> str:
    """Allow only alphanumeric, hyphens and underscores in channel name.

    Raises HTTPException 400 if the agent_id contains unsafe characters.
    """
    import re
    if not re.match(r"^[a-zA-Z0-9_\-]{1,128}$", agent_id):
        raise HTTPException(
            status_code=400,
            detail={"error": "agent_id contains invalid characters", "code": "INVALID_AGENT_ID"},
        )
    # Postgres channel identifiers: replace hyphens with underscores
    return re.sub(r"[^a-zA-Z0-9_]", "_", agent_id)


# ---------------------------------------------------------------------------
# GET /api/agents/{agent_id}/listen
# ---------------------------------------------------------------------------

@router.get("/api/agents/{agent_id}/listen", operation_id="agent_notifications_listen")
async def listen_agent_updates(agent_id: str) -> StreamingResponse:
    """Open a Server-Sent Events stream for real-time agent version notifications.

    LISTENs on Postgres channel `agent_update_{agent_id}`.
    Yields `event: agent_update` when a NOTIFY is received from the domain layer.
    Yields `: keepalive` every 25s to prevent proxy timeout.

    Client disconnect cancels the stream and closes the Postgres connection.
    """
    start = datetime.now(tz=timezone.utc)
    logger.info("sse.listen.request agent_id=%s", agent_id)

    # Validate agent_id before opening connection
    safe_id = _sanitise_agent_id_for_channel(agent_id)

    elapsed_ms = (datetime.now(tz=timezone.utc) - start).total_seconds() * 1000
    logger.info(
        "sse.listen.streaming agent_id=%s safe_id=%s setup_ms=%.1f",
        agent_id,
        safe_id,
        elapsed_ms,
    )

    return StreamingResponse(
        _sse_listen_generator(safe_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable Nginx buffering
            "Connection": "keep-alive",
        },
    )
