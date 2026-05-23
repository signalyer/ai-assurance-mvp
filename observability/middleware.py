"""Request-context stamping middleware.

``RequestContextMiddleware`` assigns a unique ``X-Request-Id`` to every
inbound request.  If the client supplies an ``X-Request-Id`` header, its value
is validated against the regex ``^[A-Za-z0-9_-]{1,64}$`` before being
accepted.  Invalid values (XSS payloads, empty strings, values longer than 64
characters) are rejected: the middleware generates a fresh UUID4, uses that
instead, and emits a ``logger.warning`` once per request.  If the client omits
the header entirely, a UUID4 is generated silently.

The accepted (or generated) ID is stamped into a ``contextvars.ContextVar``
so that every log line emitted during that request carries the ID
automatically, and echoed back in the response header.

The ContextVar is always cleared in a ``finally`` block using the ``Token``
returned by ``ContextVar.set``, preventing context bleed across requests in a
single-process multi-coroutine server.

Session 11 hardening: ``X-Request-Id`` validation via compiled regex enforcing
``^[A-Za-z0-9_-]{1,64}$``; violations trigger ``logger.warning`` and
server-side UUID4 replacement.
"""
from __future__ import annotations

import logging
import re
import uuid
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from observability.structured_log import set_request_context, reset_request_context

_REQUEST_ID_HEADER = "X-Request-Id"

logger = logging.getLogger(__name__)

#: Compiled regex enforcing safe request ID values.
#: Allows alphanumerics, hyphens, and underscores, 1–64 characters.
_REQUEST_ID_RE: re.Pattern[str] = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _sanitise_request_id(raw: str | None) -> tuple[str, bool]:
    """Validate *raw* and return a safe request ID plus a ``replaced`` flag.

    If *raw* is None, empty, or fails ``_REQUEST_ID_RE``, a fresh UUID4 (hex,
    no hyphens) is generated and returned with ``replaced=True``.  Otherwise
    *raw* is returned unchanged with ``replaced=False``.

    Args:
        raw: The raw header value from the client, or None if absent.

    Returns:
        Tuple of ``(request_id, replaced)`` where *replaced* is True when a
        new UUID was generated in place of the client-supplied value.
    """
    if raw and _REQUEST_ID_RE.match(raw):
        return raw, False
    return uuid.uuid4().hex, True


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
        """Process the request: validate + stamp context, forward, echo header, clear context.

        Args:
            request:   The incoming Starlette request.
            call_next: The next middleware / route handler in the chain.

        Returns:
            The response with ``X-Request-Id`` header set to the validated ID.
        """
        raw_id: str | None = request.headers.get(_REQUEST_ID_HEADER)
        request_id, replaced = _sanitise_request_id(raw_id)

        if replaced and raw_id is not None:
            # Client supplied a value but it failed validation — log a warning
            logger.warning(
                "RequestContextMiddleware: invalid X-Request-Id rejected "
                "(len=%d, value_prefix=%r); replaced with server-generated UUID",
                len(raw_id),
                raw_id[:16],
            )

        ctx: dict[str, str] = {"request_id": request_id}
        token = set_request_context(ctx)
        try:
            response: Response = await call_next(request)
        finally:
            reset_request_context(token)

        response.headers[_REQUEST_ID_HEADER] = request_id
        return response
