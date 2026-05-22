"""Structured JSON logger for the AI Assurance Platform.

``get_logger`` returns a standard ``logging.Logger`` whose root handler emits
newline-delimited JSON.  Each log record includes contextual fields drawn from
a ``contextvars.ContextVar`` populated by ``RequestContextMiddleware``.

JSON serialisation never raises: non-serialisable values are coerced to
``str`` via ``default=str``.
"""
from __future__ import annotations

import json
import logging
import time
from contextvars import ContextVar
from typing import Any

# ---------------------------------------------------------------------------
# Context variable shared with RequestContextMiddleware
# ---------------------------------------------------------------------------

_request_context: ContextVar[dict[str, str]] = ContextVar(
    "_request_context", default={}
)


def get_request_context() -> dict[str, str]:
    """Return the current per-request context dict (may be empty)."""
    return _request_context.get()


def set_request_context(ctx: dict[str, str]) -> object:
    """Set the per-request context dict and return the reset Token.

    Returns:
        A ``contextvars.Token`` that must be passed to
        ``_request_context.reset(token)`` in a ``finally`` block to avoid
        context leaks.
    """
    return _request_context.set(ctx)


def reset_request_context(token: object) -> None:
    """Reset the per-request context using the Token returned by set."""
    _request_context.reset(token)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# JSON formatter
# ---------------------------------------------------------------------------

class _JsonFormatter(logging.Formatter):
    """Emit each log record as a single-line JSON object."""

    _FIELDS = ("request_id", "operation_id", "role", "vault_id", "trace_id")

    def format(self, record: logging.LogRecord) -> str:
        ctx = _request_context.get()
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,
            "name": record.name,
            "msg": record.getMessage(),
        }
        for field in self._FIELDS:
            payload[field] = ctx.get(field, "")

        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)

        try:
            return json.dumps(payload, default=str)
        except Exception:
            # Last-resort: never let the formatter raise.
            return json.dumps({"ts": payload["ts"], "level": "ERROR",
                               "name": record.name, "msg": "log_serialisation_failed"})


# ---------------------------------------------------------------------------
# Root-handler singleton
# ---------------------------------------------------------------------------

_handler_installed: bool = False


def _ensure_handler() -> None:
    global _handler_installed
    if _handler_installed:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter())
    root = logging.getLogger()
    # Avoid duplicating handlers when the module is reloaded in tests.
    for existing in list(root.handlers):
        if isinstance(existing.formatter, _JsonFormatter):
            _handler_installed = True
            return
    root.addHandler(handler)
    _handler_installed = True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_logger(name: str) -> logging.Logger:
    """Return a JSON-formatted logger for *name*.

    The JSON handler is attached to the root logger once; subsequent calls
    are instant.

    Args:
        name: Logger name, typically ``__name__`` of the calling module.

    Returns:
        A configured ``logging.Logger`` instance.
    """
    _ensure_handler()
    return logging.getLogger(name)
