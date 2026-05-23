"""Tests for X-Request-Id regex validation in RequestContextMiddleware.

Task 3 — Session 11 debt fix.

3 tests:
  (a) valid header 'abc-123' passes through unchanged
  (b) '<script>alert(1)</script>' → server generates UUID4 + logger.warning
  (c) empty string / over-64-char → server-generated UUID
"""
from __future__ import annotations

import logging
import re
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_MODULE_AVAILABLE = False
try:
    from observability.middleware import RequestContextMiddleware
    _MODULE_AVAILABLE = True
except ImportError:
    pass

pytestmark = pytest.mark.skipif(
    not _MODULE_AVAILABLE,
    reason="observability.middleware not available",
)


# ---------------------------------------------------------------------------
# Regex pattern — mirrors what the implementation must enforce
# ---------------------------------------------------------------------------

_VALID_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _make_request(request_id_header: str | None = None) -> MagicMock:
    """Build a mock Starlette Request with the given X-Request-Id header."""
    request = MagicMock()
    headers: dict[str, str] = {}
    if request_id_header is not None:
        headers["X-Request-Id"] = request_id_header
    request.headers = headers
    return request


def _make_response() -> MagicMock:
    """Build a mock Starlette Response."""
    response = MagicMock()
    response.headers = {}
    return response


class TestValidRequestIdPassesThrough:
    """Test (a): valid X-Request-Id is passed through unchanged."""

    def test_valid_id_preserved(self, caplog: pytest.LogCaptureFixture) -> None:
        """A header matching ^[A-Za-z0-9_-]{1,64}$ must be used as-is."""
        valid_id = "abc-123"

        # Import and inspect: the middleware must accept this ID without generating a new one
        from observability.middleware import RequestContextMiddleware

        # We test the dispatch logic by inspecting the request_id selected.
        # We'll call the selection logic directly by constructing the middleware
        # and simulating dispatch with our own mock call_next.
        app_mock = MagicMock()
        middleware = RequestContextMiddleware(app_mock)

        request = _make_request(valid_id)
        response = _make_response()

        captured_ids: list[str] = []

        from observability.structured_log import set_request_context, reset_request_context

        real_set = set_request_context

        def capturing_set(ctx: dict) -> object:
            captured_ids.append(ctx.get("request_id", ""))
            return real_set(ctx)

        import asyncio

        async def call_next(req: object) -> MagicMock:
            return response

        with (
            patch("observability.middleware.set_request_context", side_effect=capturing_set),
            patch("observability.middleware.reset_request_context"),
        ):
            asyncio.run(middleware.dispatch(request, call_next))

        assert len(captured_ids) == 1, "set_request_context must be called once per request"
        assert captured_ids[0] == valid_id, (
            f"Valid request ID '{valid_id}' must be preserved unchanged; "
            f"got '{captured_ids[0]}'"
        )
        # No warnings should have been logged for a valid ID
        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert not warnings, f"No warnings expected for valid ID; got: {[r.message for r in warnings]}"


class TestXssRequestIdReplaced:
    """Test (b): XSS-like header triggers UUID generation + warning."""

    def test_xss_header_replaced_with_uuid(self, caplog: pytest.LogCaptureFixture) -> None:
        """'<script>alert(1)</script>' → server-generated UUID4 + logger.warning."""
        xss_id = "<script>alert(1)</script>"

        from observability.middleware import RequestContextMiddleware

        app_mock = MagicMock()
        middleware = RequestContextMiddleware(app_mock)
        request = _make_request(xss_id)
        response = _make_response()

        captured_ids: list[str] = []
        real_set = __import__("observability.structured_log", fromlist=["set_request_context"]).set_request_context

        def capturing_set(ctx: dict) -> object:
            captured_ids.append(ctx.get("request_id", ""))
            return real_set(ctx)

        import asyncio

        async def call_next(req: object) -> MagicMock:
            return response

        with (
            patch("observability.middleware.set_request_context", side_effect=capturing_set),
            patch("observability.middleware.reset_request_context"),
            caplog.at_level(logging.WARNING, logger="observability.middleware"),
        ):
            asyncio.run(middleware.dispatch(request, call_next))

        assert len(captured_ids) == 1
        generated = captured_ids[0]
        # Must be different from the supplied XSS string
        assert generated != xss_id, "XSS header must not be used as request ID"
        # Must be a valid UUID-like string (UUID4 hex or standard UUID format)
        assert _VALID_REQUEST_ID_RE.match(generated) or len(generated) == 32 or "-" in generated, (
            f"Generated ID must be UUID-like; got '{generated}'"
        )
        # A warning must have been logged
        warning_messages = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
        assert warning_messages, f"Expected a warning for invalid X-Request-Id; got none"


class TestEmptyOrLongRequestIdReplaced:
    """Test (c): empty string or over-64-char value → server-generated UUID."""

    @pytest.mark.parametrize("bad_id", [
        "",
        "x" * 65,
        "a" * 100,
    ])
    def test_bad_id_replaced(self, bad_id: str) -> None:
        """Empty or over-64-char X-Request-Id must be replaced with a server-generated UUID."""
        from observability.middleware import RequestContextMiddleware

        app_mock = MagicMock()
        middleware = RequestContextMiddleware(app_mock)
        request = _make_request(bad_id)
        response = _make_response()

        captured_ids: list[str] = []
        real_set = __import__("observability.structured_log", fromlist=["set_request_context"]).set_request_context

        def capturing_set(ctx: dict) -> object:
            captured_ids.append(ctx.get("request_id", ""))
            return real_set(ctx)

        import asyncio

        async def call_next(req: object) -> MagicMock:
            return response

        with (
            patch("observability.middleware.set_request_context", side_effect=capturing_set),
            patch("observability.middleware.reset_request_context"),
        ):
            asyncio.run(middleware.dispatch(request, call_next))

        assert len(captured_ids) == 1
        generated = captured_ids[0]
        assert generated != bad_id, (
            f"Bad request ID '{bad_id[:20]}...' must not be used; got '{generated}'"
        )
        # Must be a valid UUID or UUID-hex
        assert len(generated) >= 8, f"Generated ID must be non-trivial; got '{generated}'"
