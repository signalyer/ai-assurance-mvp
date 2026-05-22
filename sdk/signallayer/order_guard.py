"""Decorator-order assertion for the SignalLayer platform chain.

Call ``guard(fn)`` after stacking all decorators on a function.  It walks the
``__wrapped__`` chain and reads the ``_sl_decorator_name`` attribute stamped by
the SDK's decorator factories to build the detected order.

Required order (outermost → innermost):

    policy_gate → scrub_pii → guardrails → trace → evaluate

Raises ``DecoratorOrderError`` if the order is wrong.
Raises ``ChainBrokenError`` if a required decorator is missing entirely.

The ``_sl_decorator_name`` attribute is stamped by ``sdk/signallayer/decorators.py``
on every callable returned by the SDK decorator factories.  This avoids
``__qualname__`` inspection which ``functools.wraps`` rewrites.
"""
from __future__ import annotations

import logging
from typing import Callable

from .errors import ChainBrokenError, DecoratorOrderError

logger = logging.getLogger(__name__)

# Attribute name stamped by decorators.py on every SDK-wrapped callable.
_SL_DECORATOR_ATTR: str = "_sl_decorator_name"

# Required decorator names in outermost-to-innermost order.
REQUIRED_ORDER: tuple[str, ...] = (
    "policy_gate",
    "scrub_pii",
    "guardrails",
    "trace",
    "evaluate",
)


def _extract_chain(fn: Callable) -> list[str]:
    """Walk the ``__wrapped__`` chain and return stamped decorator names.

    Only callables that carry the ``_sl_decorator_name`` attribute (stamped by
    the SDK decorator factories) are included.  The original unwrapped function
    has no such attribute and is excluded.

    Args:
        fn: The fully-decorated callable.

    Returns:
        List of decorator name tokens in outermost-to-innermost order.
    """
    names: list[str] = []
    seen_ids: set[int] = set()  # guard against infinite loops
    current: Callable | None = fn

    while current is not None:
        if id(current) in seen_ids:
            break
        seen_ids.add(id(current))

        name: str | None = getattr(current, _SL_DECORATOR_ATTR, None)
        if name and name not in names:
            names.append(name)

        current = getattr(current, "__wrapped__", None)

    return names


def guard(fn: Callable) -> Callable:
    """Assert the decorator chain on ``fn`` matches the required order.

    Inspect every ``_sl_decorator_name`` attribute in the ``__wrapped__`` chain
    and verify the order is:

        policy_gate → scrub_pii → guardrails → trace → evaluate

    This function is a no-op if the chain is valid — it returns ``fn``
    unchanged so it can be used as an in-place assertion after decorating::

        fn = guard(fn)  # raises on bad order, returns fn unchanged on success

    Args:
        fn: The fully-decorated callable to inspect.

    Returns:
        ``fn`` unchanged (so the call is transparent in assignment).

    Raises:
        ChainBrokenError: If one or more required decorators are missing.
        DecoratorOrderError: If all required decorators are present but in the
            wrong order.
    """
    fn_name: str = getattr(fn, "__name__", repr(fn))
    logger.debug("order_guard.guard: inspecting chain for %r", fn_name)

    chain = _extract_chain(fn)
    logger.debug("order_guard.guard: detected chain = %s", chain)

    # Check all required decorators are present.
    missing = [name for name in REQUIRED_ORDER if name not in chain]
    if missing:
        raise ChainBrokenError(
            f"Required decorator(s) missing from chain: {missing}. "
            f"Detected chain: {chain}. "
            f"Required order: {list(REQUIRED_ORDER)}."
        )

    # Filter chain to only required names (drop any unknown wrappers).
    filtered = [name for name in chain if name in REQUIRED_ORDER]

    # Verify order.
    if filtered != list(REQUIRED_ORDER):
        raise DecoratorOrderError(
            f"Decorator order violation. "
            f"Detected (outermost→innermost): {filtered}. "
            f"Required: {list(REQUIRED_ORDER)}."
        )

    logger.info(
        "order_guard.guard: chain OK for %r — %s",
        fn_name,
        filtered,
    )
    return fn
