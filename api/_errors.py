"""Global exception handlers for the FastAPI app.

Wires typed error contracts per docs/plans/SESSION-13-api-typing-audit.md §1.2.

    - 409 -> ConflictDetail (for governance-typed conflicts)
    - 500 -> ServerErrorDetail (with trace_id from App Insights + request_id)
    - 4xx default -> FastAPI default {detail: str} (unchanged; Schemathesis understands it)

Routers raise:
    - HTTPException(status_code=409, detail=ConflictDetail(...).model_dump()) for typed 409s
    - HTTPException(status_code=400|401|403|404, detail="...") for plain errors
    - any unhandled exception -> caught here -> 500 ServerErrorDetail
"""
from __future__ import annotations

import logging
import os
import uuid
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


def _current_request_id(request: Request) -> str:
    """Pull request_id from RequestContextMiddleware ContextVar, falling back to a fresh uuid.

    The middleware stamps X-Request-Id; if it's not present (e.g. middleware not loaded
    in test), generate one inline so the response is still self-describing.
    """
    header = request.headers.get("x-request-id")
    if header:
        return header
    # Try contextvar from observability.middleware
    try:
        from observability.middleware import current_request_id  # type: ignore
        rid = current_request_id()
        if rid:
            return rid
    except ImportError:
        pass
    return str(uuid.uuid4())


def _current_trace_id(request: Request) -> str:
    """Pull App Insights operation_Id (== Langfuse trace_id by convention).

    Falls back to a fresh uuid so the 500 body is always typed. App Insights
    correlates by operation_Id when the X-Request-Id header propagates.
    """
    header = request.headers.get("traceparent") or request.headers.get("x-trace-id")
    if header:
        # W3C traceparent is "00-{traceid}-{spanid}-{flags}"; extract traceid
        parts = header.split("-")
        if len(parts) >= 3 and len(parts[1]) == 32:
            return parts[1]
        return header
    return str(uuid.uuid4())


async def server_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all 500 handler returning typed ServerErrorDetail.

    Never echoes stack trace or exc.args (may contain secrets). Logs the full
    exception server-side with request_id + trace_id for correlation.
    """
    request_id = _current_request_id(request)
    trace_id = _current_trace_id(request)

    # Log server-side with full context for App Insights correlation
    logger.error(
        "unhandled_exception path=%s method=%s request_id=%s trace_id=%s exc=%s",
        request.url.path,
        request.method,
        request_id,
        trace_id,
        type(exc).__name__,
        exc_info=True,
    )

    is_prod = os.environ.get("WEBSITE_SITE_NAME", "").startswith("app-aigovern")
    public_detail = (
        "Internal server error. Correlate with trace_id in App Insights."
        if is_prod
        else f"Internal server error: {type(exc).__name__}"
    )

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": public_detail,
            "trace_id": trace_id,
            "request_id": request_id,
        },
    )


def register_error_handlers(app: FastAPI) -> None:
    """Install global exception handlers on the FastAPI app.

    Call once in dashboard.py after `app = FastAPI(...)`. Idempotent.

    HTTPException (4xx) handlers are left to FastAPI's default -- those return
    {detail: str|object} which routers control via the `detail=` kwarg. Typed
    409 bodies are achieved by passing detail=ConflictDetail(...).model_dump()
    from the router itself.
    """
    app.add_exception_handler(Exception, server_error_handler)
