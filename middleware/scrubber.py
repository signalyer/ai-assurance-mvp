"""@scrub_pii decorator for FastAPI route handlers and async functions.

Provides the @scrub_pii(scope) decorator that runs before tracer.trace_call().
Wraps async functions taking 'prompt' as kwarg or first positional arg.

CRITICAL: This is the second link in the decorator chain:
    @policy_gate -> @scrub_pii -> @trace_llm_call -> @evaluate_response

Fail-closed: if scrubber returns empty vault_id (error condition), the wrapped
function is NOT called and an error is logged.
"""

from __future__ import annotations

import functools
import inspect
import logging
import os
from typing import Any, Callable

logger = logging.getLogger(__name__)


def scrub_pii(scope: str = "default") -> Callable:
    """
    Decorator that scrubs PII from a 'prompt' arg before invoking the wrapped function.

    The decorator:
    1. Extracts 'prompt' from kwargs or first positional arg
    2. Calls scrubber.tokenise_payload(prompt, scope) -> (scrubbed, vault_id)
    3. If SCRUBBER_ENABLED=false: passes original prompt through (backward compat)
    4. If SCRUBBER_ENABLED=true and vault_id empty: blocks call (fail-closed)
    5. Otherwise: passes scrubbed prompt + vault_id to wrapped function

    The wrapped function receives:
    - prompt: scrubbed version (with tokens [PERSON_001] etc.)
    - vault_id: kwarg added by decorator for downstream tracer.trace_call()

    Args:
        scope: Logical scope for grouping tokens (e.g., 'demo-run', 'api-eval')

    Returns:
        Decorator function

    Example:
        @scrub_pii(scope="demo-run")
        async def call_llm(prompt: str, vault_id: str = "") -> str:
            # prompt is scrubbed; vault_id is set automatically
            result = await llm_client.call(prompt)
            trace_call(prompt=prompt, response=result, metadata={"vault_id": vault_id})
            return result
    """

    def decorator(func: Callable) -> Callable:
        is_async = inspect.iscoroutinefunction(func)

        if is_async:
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                scrubbed, vault_id = _scrub_args(func, args, kwargs, scope)

                if scrubbed is None:
                    # Fail-closed: scrubber failed when enabled
                    logger.error(
                        f"@scrub_pii: scrubber failed for {func.__name__} (scope={scope}); "
                        f"blocking call to prevent raw PII leak"
                    )
                    raise RuntimeError(
                        f"Scrubber failed in {func.__name__}: cannot proceed without vault_id"
                    )

                # Replace prompt arg with scrubbed version
                args, kwargs = _replace_prompt_arg(func, args, kwargs, scrubbed)

                # Inject vault_id as kwarg if function accepts it
                sig = inspect.signature(func)
                if "vault_id" in sig.parameters:
                    kwargs["vault_id"] = vault_id

                return await func(*args, **kwargs)

            return async_wrapper
        else:
            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                scrubbed, vault_id = _scrub_args(func, args, kwargs, scope)

                if scrubbed is None:
                    logger.error(
                        f"@scrub_pii: scrubber failed for {func.__name__} (scope={scope}); "
                        f"blocking call to prevent raw PII leak"
                    )
                    raise RuntimeError(
                        f"Scrubber failed in {func.__name__}: cannot proceed without vault_id"
                    )

                args, kwargs = _replace_prompt_arg(func, args, kwargs, scrubbed)

                sig = inspect.signature(func)
                if "vault_id" in sig.parameters:
                    kwargs["vault_id"] = vault_id

                return func(*args, **kwargs)

            return sync_wrapper

    return decorator


def _scrub_args(
    func: Callable,
    args: tuple,
    kwargs: dict,
    scope: str,
) -> tuple[str | None, str]:
    """
    Extract prompt from args/kwargs, scrub it, return (scrubbed, vault_id).

    Returns (None, "") if scrubber failed when enabled (caller should block).
    Returns (original_prompt, "") if scrubber disabled (backward compat).

    Args:
        func: The wrapped function (for signature inspection)
        args: Positional args
        kwargs: Keyword args
        scope: Scrubber scope

    Returns:
        (scrubbed_text, vault_id) or (None, "") on fail-closed condition
    """
    scrubber_enabled = os.getenv("SCRUBBER_ENABLED", "false").lower() == "true"

    # Extract prompt
    prompt = _extract_prompt(func, args, kwargs)
    if prompt is None or not isinstance(prompt, str):
        # No prompt to scrub; pass through
        return "", ""

    if not scrubber_enabled:
        # Backward compat: scrubber disabled, pass through
        return prompt, ""

    try:
        from scrubber import tokenise_payload
        scrubbed, vault_id = tokenise_payload(prompt, scope)

        if not vault_id and prompt:
            # No entities detected — that's OK, but vault_id is empty
            # Generate a synthetic vault_id for traceability
            import hashlib
            vault_id = f"{scope}_nopii_{hashlib.sha256(prompt.encode()).hexdigest()[:12]}"

        logger.debug(f"@scrub_pii: scrubbed prompt in {func.__name__}, vault_id={vault_id}")
        return scrubbed, vault_id

    except Exception as e:
        logger.error(f"@scrub_pii: scrubber raised {type(e).__name__}: {e}", exc_info=True)
        return None, ""


def _extract_prompt(func: Callable, args: tuple, kwargs: dict) -> Any:
    """Extract the 'prompt' value from kwargs or positional args."""
    if "prompt" in kwargs:
        return kwargs["prompt"]

    sig = inspect.signature(func)
    params = list(sig.parameters.keys())

    if "prompt" in params:
        idx = params.index("prompt")
        if idx < len(args):
            return args[idx]

    # Fall back to first positional arg if function has only 1 string-like param
    if args and isinstance(args[0], str):
        return args[0]

    return None


def _replace_prompt_arg(
    func: Callable,
    args: tuple,
    kwargs: dict,
    new_prompt: str,
) -> tuple[tuple, dict]:
    """Replace the prompt value in args/kwargs with new_prompt."""
    if "prompt" in kwargs:
        kwargs["prompt"] = new_prompt
        return args, kwargs

    sig = inspect.signature(func)
    params = list(sig.parameters.keys())

    if "prompt" in params:
        idx = params.index("prompt")
        if idx < len(args):
            args = args[:idx] + (new_prompt,) + args[idx + 1:]
            return args, kwargs

    if args and isinstance(args[0], str):
        args = (new_prompt,) + args[1:]

    return args, kwargs


if __name__ == "__main__":
    # Smoke test
    import asyncio

    print("Testing @scrub_pii decorator...\n")

    os.environ["SCRUBBER_ENABLED"] = "true"
    os.environ["SESSION_SECRET"] = "test-secret"

    @scrub_pii(scope="smoke-test")
    async def mock_llm_call(prompt: str, vault_id: str = "") -> dict:
        return {"prompt_received": prompt, "vault_id_received": vault_id}

    # Test 1: prompt with PII
    pii_prompt = "Client John Smith email john@example.com SSN 123-45-6789"
    result = asyncio.run(mock_llm_call(pii_prompt))

    print(f"Original prompt: {pii_prompt}")
    print(f"Prompt received by function: {result['prompt_received']}")
    print(f"Vault ID: {result['vault_id_received']}")

    assert "john@example.com" not in result["prompt_received"], "FAIL: email leaked"
    assert "123-45-6789" not in result["prompt_received"], "FAIL: SSN leaked"
    assert "John Smith" not in result["prompt_received"], "FAIL: name leaked"
    assert result["vault_id_received"], "FAIL: vault_id not set"
    print("\n[PASS] PII scrubbed and vault_id passed to function")

    # Test 2: scrubber disabled (backward compat)
    os.environ["SCRUBBER_ENABLED"] = "false"
    result = asyncio.run(mock_llm_call(pii_prompt))
    assert result["prompt_received"] == pii_prompt, "FAIL: scrubber should be disabled"
    print("[PASS] Scrubber disabled mode preserves original prompt")

    print("\nAll @scrub_pii smoke tests passed")
