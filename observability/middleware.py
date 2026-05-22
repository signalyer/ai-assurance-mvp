"""Request-context stamping middleware.

``RequestContextMiddleware`` assigns a unique ``X-Request-Id`` to every
inbound request (generating one via ``uuid.uuid4().hex`` if the client did
not supply one), stamps it into a ``contextvars.ContextVar`` so that every
log line emitted during that request carries the ID automatically, and echoes
it back in the response header.

The ContextVar is always cleared in a ``finally`` block using the ``Token``
returned by ``ContextVar.set``, preventing context bleed across requests in a
single-process multi-coroutine server.
"""
from __future__ import annotations

import uuid
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from observability.structured_log import set_request_context, reset_request_context

_REQUEST_ID_HEADER = "X-Request-Id"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Stamp every request with a traceable ``X-Request-Id``.

    Middleware execution order note (Starlette / FastAPI):
    Add this middleware LAST (outermost) so it fires first on every request,
    before any auth or business logic middleware sees the request.
    """

    def __init__(self, app: ASGIApp) -> None:
        """Initialise the middleware wrapping *app*."""
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable[..., Response]) -> Response:
        """Process the request: stamp context, forward, echo header, clear context.

        Args:
            request:   The incoming Starlette request.
            call_next: The next middleware / route handler in the chain.

        Returns:
            The response with ``X-Request-Id`` header set.
        """
        request_id: str = (
            request.headers.get(_REQUEST_ID_HEADER)
            or uuid.uuid4().hex
        )

        ctx: dict[str, str] = {"request_id": request_id}
        token = set_request_context(ctx)
        try:
            response: Response = await call_next(request)
        finally:
            reset_request_context(token)

        response.headers[_REQUEST_ID_HEADER] = request_id
        return response
