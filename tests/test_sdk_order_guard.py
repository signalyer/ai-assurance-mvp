"""Tests for sdk/signallayer/order_guard.py.

Covers:
- Correct chain passes guard()
- Wrong order raises DecoratorOrderError
- Missing decorator raises ChainBrokenError
- Partial chain raises ChainBrokenError
- guard() returns fn unchanged on success
- Extra unknown wrappers in chain are tolerated
"""
from __future__ import annotations

import functools
import sys
import os
from typing import Any, Callable

import pytest

# Ensure sdk/signallayer is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "sdk"))

from signallayer.decorators import _make_noop_decorator, _SL_DECORATOR_ATTR, _stamp
from signallayer.errors import ChainBrokenError, DecoratorOrderError
from signallayer.order_guard import guard, REQUIRED_ORDER, _extract_chain


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _apply_correct_chain(fn: Callable) -> Callable:
    """Apply all 5 SDK decorators in the correct order to fn.

    Uses no-op factories so no platform imports are needed.

    Args:
        fn: The original callable.

    Returns:
        Decorated callable with all 5 ``_sl_decorator_name`` attributes in the
        chain.
    """
    pg = _make_noop_decorator("policy_gate")
    sp = _make_noop_decorator("scrub_pii")
    gr = _make_noop_decorator("guardrails")
    tr = _make_noop_decorator("trace")
    ev = _make_noop_decorator("evaluate")

    # Apply innermost first (evaluate), then outward
    fn = ev()(fn)
    fn = tr()(fn)
    fn = gr()(fn)
    fn = sp()(fn)
    fn = pg()(fn)
    return fn


def _apply_wrong_order(fn: Callable) -> Callable:
    """Apply decorators in wrong order: scrub_pii before policy_gate.

    Args:
        fn: The original callable.

    Returns:
        Decorated callable with wrong ``_sl_decorator_name`` order.
    """
    pg = _make_noop_decorator("policy_gate")
    sp = _make_noop_decorator("scrub_pii")
    gr = _make_noop_decorator("guardrails")
    tr = _make_noop_decorator("trace")
    ev = _make_noop_decorator("evaluate")

    # Wrong: scrub_pii outermost, policy_gate second
    fn = ev()(fn)
    fn = tr()(fn)
    fn = gr()(fn)
    fn = pg()(fn)   # ← flipped
    fn = sp()(fn)   # ← flipped
    return fn


def _apply_missing_evaluate(fn: Callable) -> Callable:
    """Apply only 4 decorators, omitting 'evaluate'.

    Args:
        fn: The original callable.

    Returns:
        Decorated callable missing the ``evaluate`` stamp.
    """
    pg = _make_noop_decorator("policy_gate")
    sp = _make_noop_decorator("scrub_pii")
    gr = _make_noop_decorator("guardrails")
    tr = _make_noop_decorator("trace")

    fn = tr()(fn)
    fn = gr()(fn)
    fn = sp()(fn)
    fn = pg()(fn)
    return fn


# ---------------------------------------------------------------------------
# Correct chain
# ---------------------------------------------------------------------------

class TestCorrectChain:
    def test_correct_chain_passes(self) -> None:
        """guard() returns fn unchanged when all 5 decorators are in correct order."""
        def my_fn(x: int) -> int:
            return x

        decorated = _apply_correct_chain(my_fn)
        result = guard(decorated)
        # guard returns the same object
        assert result is decorated

    def test_extract_chain_correct_order(self) -> None:
        """_extract_chain returns the 5 names in correct order."""
        def fn() -> None:
            pass

        decorated = _apply_correct_chain(fn)
        chain = _extract_chain(decorated)
        assert chain == list(REQUIRED_ORDER)

    def test_correct_chain_callable_still_works(self) -> None:
        """The decorated function is still callable after guard()."""
        def add(a: int, b: int) -> int:
            return a + b

        decorated = _apply_correct_chain(add)
        guard(decorated)
        assert decorated(1, 2) == 3

    def test_guard_returns_fn(self) -> None:
        """guard() returns exactly the same callable object."""
        def fn() -> None:
            pass

        decorated = _apply_correct_chain(fn)
        returned = guard(decorated)
        assert returned is decorated


# ---------------------------------------------------------------------------
# Wrong order
# ---------------------------------------------------------------------------

class TestWrongOrder:
    def test_wrong_order_raises_decorator_order_error(self) -> None:
        """Wrong decorator order raises DecoratorOrderError."""
        def fn() -> None:
            pass

        decorated = _apply_wrong_order(fn)
        with pytest.raises(DecoratorOrderError):
            guard(decorated)

    def test_wrong_order_error_message_includes_detected(self) -> None:
        """DecoratorOrderError message includes the detected chain."""
        def fn() -> None:
            pass

        decorated = _apply_wrong_order(fn)
        with pytest.raises(DecoratorOrderError) as exc_info:
            guard(decorated)
        assert "Detected" in str(exc_info.value)

    def test_wrong_order_error_message_includes_required(self) -> None:
        """DecoratorOrderError message includes the required chain."""
        def fn() -> None:
            pass

        decorated = _apply_wrong_order(fn)
        with pytest.raises(DecoratorOrderError) as exc_info:
            guard(decorated)
        assert "Required" in str(exc_info.value)

    def test_guard_evaluate_before_trace_raises(self) -> None:
        """evaluate appearing before trace (in wrong position) raises."""
        pg = _make_noop_decorator("policy_gate")
        sp = _make_noop_decorator("scrub_pii")
        gr = _make_noop_decorator("guardrails")
        tr = _make_noop_decorator("trace")
        ev = _make_noop_decorator("evaluate")

        def fn() -> None:
            pass

        # evaluate before trace: pg → sp → gr → evaluate → trace
        fn = tr()(fn)
        fn = ev()(fn)  # ← swapped
        fn = gr()(fn)
        fn = sp()(fn)
        fn = pg()(fn)

        with pytest.raises(DecoratorOrderError):
            guard(fn)


# ---------------------------------------------------------------------------
# Missing decorator
# ---------------------------------------------------------------------------

class TestMissingDecorator:
    def test_missing_evaluate_raises_chain_broken_error(self) -> None:
        """Missing 'evaluate' raises ChainBrokenError."""
        def fn() -> None:
            pass

        decorated = _apply_missing_evaluate(fn)
        with pytest.raises(ChainBrokenError):
            guard(decorated)

    def test_missing_error_message_names_decorator(self) -> None:
        """ChainBrokenError message names the missing decorator."""
        def fn() -> None:
            pass

        decorated = _apply_missing_evaluate(fn)
        with pytest.raises(ChainBrokenError) as exc_info:
            guard(decorated)
        assert "evaluate" in str(exc_info.value)

    def test_empty_chain_raises_chain_broken_error(self) -> None:
        """An undecorated function raises ChainBrokenError."""
        def fn() -> None:
            pass

        with pytest.raises(ChainBrokenError):
            guard(fn)

    def test_only_policy_gate_raises_chain_broken(self) -> None:
        """Single decorator in chain raises ChainBrokenError."""
        pg = _make_noop_decorator("policy_gate")

        def fn() -> None:
            pass

        decorated = pg()(fn)
        with pytest.raises(ChainBrokenError):
            guard(decorated)

    def test_missing_policy_gate_raises(self) -> None:
        """Missing 'policy_gate' (outermost) raises ChainBrokenError."""
        sp = _make_noop_decorator("scrub_pii")
        gr = _make_noop_decorator("guardrails")
        tr = _make_noop_decorator("trace")
        ev = _make_noop_decorator("evaluate")

        def fn() -> None:
            pass

        fn = ev()(fn)
        fn = tr()(fn)
        fn = gr()(fn)
        fn = sp()(fn)
        # no policy_gate

        with pytest.raises(ChainBrokenError):
            guard(fn)

    def test_missing_scrub_pii_raises(self) -> None:
        """Missing 'scrub_pii' raises ChainBrokenError."""
        pg = _make_noop_decorator("policy_gate")
        gr = _make_noop_decorator("guardrails")
        tr = _make_noop_decorator("trace")
        ev = _make_noop_decorator("evaluate")

        def fn() -> None:
            pass

        fn = ev()(fn)
        fn = tr()(fn)
        fn = gr()(fn)
        fn = pg()(fn)

        with pytest.raises(ChainBrokenError):
            guard(fn)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_extra_unknown_wrappers_tolerated(self) -> None:
        """Unknown wrappers in the chain (no _sl_decorator_name) are ignored."""
        def fn() -> None:
            pass

        # Apply correct SDK chain first
        decorated = _apply_correct_chain(fn)

        # Add an extra unknown wrapper on top
        @functools.wraps(decorated)
        def unknown_wrapper(*args: Any, **kwargs: Any) -> Any:
            return decorated(*args, **kwargs)

        # No _sl_decorator_name stamp → guard should still see the underlying chain
        # but unknown_wrapper wraps decorated, so __wrapped__ points to decorated
        unknown_wrapper.__wrapped__ = decorated  # type: ignore[attr-defined]

        # Should pass because the required chain is still present via __wrapped__
        result = guard(unknown_wrapper)
        assert result is unknown_wrapper

    def test_stamp_helper_sets_attribute(self) -> None:
        """_stamp sets _sl_decorator_name on the callable."""
        def fn() -> None:
            pass

        stamped = _stamp(fn, "policy_gate")
        assert getattr(stamped, _SL_DECORATOR_ATTR) == "policy_gate"
        assert stamped is fn

    def test_required_order_constant(self) -> None:
        """REQUIRED_ORDER has exactly 5 elements in the expected sequence."""
        assert REQUIRED_ORDER == (
            "policy_gate",
            "scrub_pii",
            "guardrails",
            "trace",
            "evaluate",
        )
