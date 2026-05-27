"""@policy_gate decorator for OPA-style policy enforcement.

Decorator chain position: FIRST (before @scrub_pii, before @trace_llm_call):
    @policy_gate -> @scrub_pii -> @trace_llm_call -> @evaluate_response

Fail-closed: policy errors or DENY decisions raise PolicyDeniedError.
REVIEW decisions may proceed but are flagged (downstream can handle).
"""

from __future__ import annotations

import functools
import inspect
import logging
import os
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# Observability counter hook (non-raising fallback if package absent)
try:
    from observability.counters import record_policy_deny as _record_policy_deny
except ImportError:
    try:
        from observability_compat import record_policy_deny as _record_policy_deny
    except ImportError:
        def _record_policy_deny() -> None:  # type: ignore[misc]
            """Local no-op fallback."""


class PolicyDeniedError(Exception):
    """Raised when a policy_gate evaluates to DENY."""

    def __init__(self, policy_name: str, reason: str, metadata: Optional[dict] = None):
        self.policy_name = policy_name
        self.reason = reason
        self.metadata = metadata or {}
        super().__init__(f"Policy DENY [{policy_name}]: {reason}")


def policy_gate(
    action: str,
    workload_id_arg: str = "workload_id",
    allow_review: bool = True,
    strict: bool = True,
) -> Callable:
    """
    Decorator that evaluates policies before invoking the wrapped function.

    The decorator:
    1. Extracts workload_id and other context from args/kwargs
    2. Calls policy_engine.evaluate(workload_id, action, input_data)
    3. If DENY: raises PolicyDeniedError (fail-closed)
    4. If REVIEW + allow_review=True: passes through with policy_result kwarg
    5. If ALLOW: invokes wrapped function

    Args:
        action: Action being requested (e.g., 'llm_call', 'tool_invoke', 'memory_write')
        workload_id_arg: Name of the parameter containing the workload_id
        allow_review: If True, REVIEW decisions allow the call (with flag in result)
        strict: If False, only logs policy violations (development mode)

    Returns:
        Decorator function

    Example:
        @policy_gate(action="llm_call", workload_id_arg="workload_id")
        async def call_llm(workload_id: str, prompt: str) -> str:
            ...
    """

    def decorator(func: Callable) -> Callable:
        is_async = inspect.iscoroutinefunction(func)

        if is_async:
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                policy_result = _evaluate_policy(func, args, kwargs, action, workload_id_arg)

                if not _should_proceed(policy_result, allow_review, strict, func.__name__):
                    try:
                        _record_policy_deny()
                    except Exception as _obs_exc:  # noqa: BLE001
                        logger.warning("@policy_gate: record_policy_deny raised: %s", _obs_exc)
                    raise PolicyDeniedError(
                        policy_name=policy_result.policy_name,
                        reason=policy_result.reason,
                        metadata=policy_result.metadata,
                    )

                # Pass policy_result through if function accepts it
                sig = inspect.signature(func)
                if "policy_result" in sig.parameters:
                    kwargs["policy_result"] = policy_result

                return await func(*args, **kwargs)

            return async_wrapper
        else:
            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                policy_result = _evaluate_policy(func, args, kwargs, action, workload_id_arg)

                if not _should_proceed(policy_result, allow_review, strict, func.__name__):
                    try:
                        _record_policy_deny()
                    except Exception as _obs_exc:  # noqa: BLE001
                        logger.warning("@policy_gate: record_policy_deny raised: %s", _obs_exc)
                    raise PolicyDeniedError(
                        policy_name=policy_result.policy_name,
                        reason=policy_result.reason,
                        metadata=policy_result.metadata,
                    )

                sig = inspect.signature(func)
                if "policy_result" in sig.parameters:
                    kwargs["policy_result"] = policy_result

                return func(*args, **kwargs)

            return sync_wrapper

    return decorator


def _evaluate_policy(
    func: Callable,
    args: tuple,
    kwargs: dict,
    action: str,
    workload_id_arg: str,
):
    """Extract context from args/kwargs and call policy_engine.evaluate()."""
    from domain.policy_engine import evaluate, Decision, PolicyResult, PolicyCategory

    # Skip if policies disabled
    if os.getenv("POLICIES_ENABLED", "true").lower() != "true":
        return PolicyResult(
            decision=Decision.ALLOW,
            category=PolicyCategory.SYSTEM_OVERRIDE,
            policy_name="policies_disabled",
            reason="POLICIES_ENABLED=false",
        )

    # Extract workload_id
    workload_id = _extract_arg(func, args, kwargs, workload_id_arg, default="ws-unknown")

    # Build input_data from common kwargs
    input_data = {}
    for key in ("prompt", "response", "domain", "team", "risk_tier", "posture", "tool_name"):
        val = _extract_arg(func, args, kwargs, key, default=None)
        if val is not None:
            input_data[key] = val

    # Allow override of input_data via 'policy_input' kwarg
    if "policy_input" in kwargs:
        input_data.update(kwargs["policy_input"])

    return evaluate(
        workload_id=workload_id,
        action=action,
        input_data=input_data,
    )


def _extract_arg(func: Callable, args: tuple, kwargs: dict, arg_name: str, default: Any = None) -> Any:
    """Extract a named arg from kwargs, positional args, or the function's default.

    Resolution order:
      1. Explicit kwarg at call site.
      2. Positional arg at the parameter's declared index.
      3. The parameter's signature default (e.g. `tool_name="list_resource_groups"`
         as a kwarg-only default). Without this fallback, governed tools that
         encode their identity via a default value are invisible to the
         policy engine — every caller would have to repeat the kwarg, and a
         missed call site would silently bypass workload-specific rules.
         Caught in F-024 when @policy_gate(action="tool_invoke") failed to
         deny a mutation-verb tool whose name lived only in the default.
      4. The provided `default` arg.
    """
    if arg_name in kwargs:
        return kwargs[arg_name]

    sig = inspect.signature(func)
    params = sig.parameters

    if arg_name in params:
        positional_names = list(params.keys())
        idx = positional_names.index(arg_name)
        if idx < len(args):
            return args[idx]
        param_default = params[arg_name].default
        if param_default is not inspect.Parameter.empty:
            return param_default

    return default


def _should_proceed(policy_result, allow_review: bool, strict: bool, func_name: str) -> bool:
    """Decide whether to proceed with the wrapped function call."""
    from domain.policy_engine import Decision

    if policy_result.decision == Decision.ALLOW:
        return True

    if policy_result.decision == Decision.REVIEW:
        if allow_review:
            logger.warning(
                f"@policy_gate: REVIEW for {func_name}: {policy_result.reason}"
            )
            return True
        else:
            if not strict:
                logger.warning(
                    f"@policy_gate: REVIEW for {func_name} (non-strict mode): "
                    f"{policy_result.reason}"
                )
                return True
            return False

    # DENY
    if not strict:
        logger.warning(
            f"@policy_gate: DENY for {func_name} (non-strict mode, proceeding): "
            f"{policy_result.reason}"
        )
        return True

    logger.error(f"@policy_gate: DENY for {func_name}: {policy_result.reason}")
    return False


if __name__ == "__main__":
    # Smoke test
    import asyncio

    print("Testing @policy_gate decorator...\n")

    os.environ["POLICIES_ENABLED"] = "true"

    @policy_gate(action="llm_call", workload_id_arg="workload_id")
    async def mock_llm(workload_id: str, prompt: str) -> dict:
        return {"workload_id": workload_id, "prompt": prompt, "ok": True}

    # Test 1: Clean prompt — should ALLOW
    result = asyncio.run(mock_llm(workload_id="ws-001", prompt="What is 2+2?"))
    assert result["ok"], "Clean prompt should pass"
    print("[PASS] Clean prompt allowed")

    # Test 2: Raw PII — should DENY
    try:
        asyncio.run(mock_llm(workload_id="ws-002", prompt="SSN 123-45-6789"))
        print("[FAIL] Raw PII should have been denied")
    except PolicyDeniedError as e:
        print(f"[PASS] Raw PII denied: {e}")

    # Test 3: Scrubbed PII — should ALLOW
    result = asyncio.run(mock_llm(workload_id="ws-003", prompt="[EMAIL_001] [SSN_001]"))
    assert result["ok"], "Scrubbed PII should pass"
    print("[PASS] Scrubbed PII allowed")

    print("\nAll @policy_gate smoke tests passed")
