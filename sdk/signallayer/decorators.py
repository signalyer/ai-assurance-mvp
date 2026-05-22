"""Re-exports of the 5 platform decorators under SDK-canonical names.

The SDK exposes:
    policy_gate     — from middleware.policy
    scrub_pii       — from middleware.scrubber
    guardrails      — from middleware.guardrails
    trace           — thin wrapper around tracer.trace_call (function, not decorator)
    evaluate        — thin wrapper around evaluator.evaluate_response (function, not decorator)

Each decorator factory stamps the attribute ``_sl_decorator_name`` on the
returned callable so that ``order_guard.guard()`` can detect the chain
reliably without inspecting ``__qualname__`` (which ``functools.wraps``
overwrites with the original function's name).

NOTE: ``trace_call`` and ``evaluate_response`` in the platform are *functions*,
not decorator factories.  The SDK aliases them as ``trace`` and ``evaluate``
for a consistent naming surface.

Config is read from the module-level ``_config`` dict populated by ``init()``.
All imports are deferred to avoid pulling in platform dependencies when the SDK
is imported in environments where the platform package is not installed.
"""
from __future__ import annotations

import functools
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Attribute name stamped on each wrapped callable by the SDK decorator factories.
_SL_DECORATOR_ATTR: str = "_sl_decorator_name"


def _stamp(fn: Callable, name: str) -> Callable:
    """Stamp ``_sl_decorator_name`` on a callable and return it.

    Args:
        fn: The callable to stamp.
        name: SDK canonical decorator name (e.g. ``"policy_gate"``).

    Returns:
        ``fn`` with ``_sl_decorator_name`` set.
    """
    setattr(fn, _SL_DECORATOR_ATTR, name)
    return fn


# ---------------------------------------------------------------------------
# Deferred platform imports — wrapped in functions to allow the SDK to load
# even when the platform is not installed (degraded mode).
# ---------------------------------------------------------------------------


def _get_policy_gate() -> Callable:
    """Import and return the platform ``policy_gate`` decorator factory.

    Returns:
        The ``policy_gate`` callable from ``middleware.policy``.

    Raises:
        ImportError: If the platform package is not installed.
    """
    from middleware.policy import policy_gate  # type: ignore[import]
    return policy_gate


def _get_scrub_pii() -> Callable:
    """Import and return the platform ``scrub_pii`` decorator factory.

    Returns:
        The ``scrub_pii`` callable from ``middleware.scrubber``.

    Raises:
        ImportError: If the platform package is not installed.
    """
    from middleware.scrubber import scrub_pii  # type: ignore[import]
    return scrub_pii


def _get_guardrails() -> Callable:
    """Import and return the platform ``guardrails`` decorator factory.

    Returns:
        The ``guardrails`` callable from ``middleware.guardrails``.

    Raises:
        ImportError: If the platform package is not installed.
    """
    from middleware.guardrails import guardrails  # type: ignore[import]
    return guardrails


def _get_trace_call() -> Callable:
    """Import and return the platform ``trace_call`` function.

    Returns:
        The ``trace_call`` callable from ``tracer``.

    Raises:
        ImportError: If the platform package is not installed.
    """
    from tracer import trace_call  # type: ignore[import]
    return trace_call


def _get_evaluate_response() -> Callable:
    """Import and return the platform ``evaluate_response`` function.

    Returns:
        The ``evaluate_response`` callable from ``evaluator``.

    Raises:
        ImportError: If the platform package is not installed.
    """
    from evaluator import evaluate_response  # type: ignore[import]
    return evaluate_response


# ---------------------------------------------------------------------------
# Public re-exports (lazy wrappers that forward all args and stamp the name)
# ---------------------------------------------------------------------------

def policy_gate(*args: Any, **kwargs: Any) -> Any:
    """Re-export of ``middleware.policy.policy_gate``.

    Decorates a function with OPA-style policy enforcement.  All arguments are
    forwarded unchanged to the platform implementation.  The returned callable
    is stamped with ``_sl_decorator_name = "policy_gate"`` so that
    ``order_guard.guard()`` can detect it.

    See ``middleware.policy.policy_gate`` for full parameter documentation.

    Returns:
        Decorator function with ``_sl_decorator_name`` attribute set.
    """
    platform_decorator = _get_policy_gate()
    result = platform_decorator(*args, **kwargs)
    if callable(result):
        # result is a decorator (factory-style call like policy_gate(action=...))
        original_decorator = result

        @functools.wraps(original_decorator)
        def stamping_decorator(fn: Callable) -> Callable:
            wrapped = original_decorator(fn)
            return _stamp(wrapped, "policy_gate")

        _stamp(stamping_decorator, "policy_gate")
        return stamping_decorator
    # Direct application (shouldn't happen for policy_gate but guard it)
    return _stamp(result, "policy_gate")


def scrub_pii(*args: Any, **kwargs: Any) -> Any:
    """Re-export of ``middleware.scrubber.scrub_pii``.

    Decorates a function with PII scrubbing before the LLM call.  The returned
    callable is stamped with ``_sl_decorator_name = "scrub_pii"``.

    See ``middleware.scrubber.scrub_pii`` for full parameter documentation.

    Returns:
        Decorator function with ``_sl_decorator_name`` attribute set.
    """
    platform_decorator = _get_scrub_pii()
    result = platform_decorator(*args, **kwargs)
    if callable(result):
        original_decorator = result

        @functools.wraps(original_decorator)
        def stamping_decorator(fn: Callable) -> Callable:
            wrapped = original_decorator(fn)
            return _stamp(wrapped, "scrub_pii")

        _stamp(stamping_decorator, "scrub_pii")
        return stamping_decorator
    return _stamp(result, "scrub_pii")


def guardrails(*args: Any, **kwargs: Any) -> Any:
    """Re-export of ``middleware.guardrails.guardrails``.

    Decorates a function with injection detection, topic enforcement, and
    content safety checks.  The returned callable is stamped with
    ``_sl_decorator_name = "guardrails"``.

    See ``middleware.guardrails.guardrails`` for full parameter documentation.

    Returns:
        Decorator function with ``_sl_decorator_name`` attribute set.
    """
    platform_decorator = _get_guardrails()
    result = platform_decorator(*args, **kwargs)
    if callable(result):
        original_decorator = result

        @functools.wraps(original_decorator)
        def stamping_decorator(fn: Callable) -> Callable:
            wrapped = original_decorator(fn)
            return _stamp(wrapped, "guardrails")

        _stamp(stamping_decorator, "guardrails")
        return stamping_decorator
    return _stamp(result, "guardrails")


def trace(*args: Any, **kwargs: Any) -> Any:
    """SDK alias for ``tracer.trace_call``.

    Sends a model call trace to the active tracer backend.  The prompt must be
    pre-scrubbed via ``scrub_pii`` before this is called.

    All arguments are forwarded to ``tracer.trace_call``.

    Returns:
        Trace ID string.
    """
    return _get_trace_call()(*args, **kwargs)


def evaluate(*args: Any, **kwargs: Any) -> Any:
    """SDK alias for ``evaluator.evaluate_response``.

    Runs the DeepEval metric suite against a model response.  All arguments
    are forwarded to ``evaluator.evaluate_response``.

    Returns:
        Dict mapping metric name to ``{score, passed, details}``.
    """
    return _get_evaluate_response()(*args, **kwargs)


# ---------------------------------------------------------------------------
# Helper for tests and order_guard: create a stamped no-op decorator
# ---------------------------------------------------------------------------

def _make_noop_decorator(name: str) -> Callable:
    """Return a stamped no-op decorator factory for testing purposes.

    The returned factory, when called (with or without arguments), returns a
    decorator that wraps a function and stamps ``_sl_decorator_name = name``
    on the result.

    Args:
        name: SDK canonical decorator name.

    Returns:
        Callable that behaves like a decorator factory.
    """
    def factory(*args: Any, **kwargs: Any) -> Callable:
        def decorator(fn: Callable) -> Callable:
            @functools.wraps(fn)
            def wrapper(*a: Any, **kw: Any) -> Any:
                return fn(*a, **kw)
            return _stamp(wrapper, name)
        return _stamp(decorator, name)
    return factory
