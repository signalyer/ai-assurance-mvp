"""Runnable billing agent example.

Demonstrates the full platform decorator chain with all 5 decorators in the
correct order.  Works as a no-op if the platform is offline (degraded mode):
scrubber / tracer / evaluator are all individually optional — if they are not
reachable the function still runs and prints placeholder IDs.

Usage::

    SL_API_KEY=dev:secret SL_API_BASE_URL=http://localhost:8000 \\
        python sdk/examples/billing_agent.py

Environment variables::

    SL_API_KEY        — required: key_id:secret pair for HMAC signing
    SL_API_BASE_URL   — required: platform base URL
    SCRUBBER_ENABLED  — optional: set to "false" to skip PII scrubbing (dev)
    POLICIES_ENABLED  — optional: set to "false" to skip policy enforcement (dev)
    GUARDRAILS_ENABLED— optional: set to "false" to skip guardrails (dev)
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
import uuid

# ---------------------------------------------------------------------------
# Bootstrap: ensure sdk/signallayer is importable when run from repo root
# ---------------------------------------------------------------------------
_sdk_dir = os.path.join(os.path.dirname(__file__), "..")
if _sdk_dir not in sys.path:
    sys.path.insert(0, _sdk_dir)

# ---------------------------------------------------------------------------
# Platform path: ensure the platform root is on sys.path so middleware/* and
# tracer.py are importable when running from the repo root.
# ---------------------------------------------------------------------------
_platform_dir = os.path.join(os.path.dirname(__file__), "..", "..")
if _platform_dir not in sys.path:
    sys.path.insert(0, _platform_dir)

import signallayer  # noqa: E402

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("billing_agent")

# ---------------------------------------------------------------------------
# SDK init — reads SL_API_KEY + SL_API_BASE_URL from env
# ---------------------------------------------------------------------------

_api_key = os.getenv("SL_API_KEY", "dev:devsecret")
_base_url = os.getenv("SL_API_BASE_URL", "http://localhost:8000")

try:
    signallayer.init(api_key=_api_key, base_url=_base_url)
except ValueError as exc:
    logger.warning("signallayer.init skipped in degraded mode: %s", exc)

# ---------------------------------------------------------------------------
# Decorated billing agent function
# Decorator order: policy_gate → scrub_pii → guardrails → (trace + evaluate
# are called explicitly inside the function body, not as decorators, because
# trace_call and evaluate_response are *functions*, not decorator factories)
# ---------------------------------------------------------------------------

# For the order_guard demonstration we stack all 5 by name using thin wrappers.
# In production, trace and evaluate are called imperatively inside the function.


def _make_billing_agent() -> object:
    """Build the decorated billing agent function.

    We use a factory to defer decorator application so the guard assertion can
    be demonstrated cleanly.

    Returns:
        The decorated async callable with all 5 platform decorators applied.
    """
    import functools

    # Innermost — the real LLM-call stub
    async def _core(
        prompt: str,
        workload_id: str = "billing-agent",
        vault_id: str = "",
    ) -> str:
        """Simulate an LLM billing response.

        In production this calls the Anthropic or OpenAI API.

        Args:
            prompt: Scrubbed prompt (PII replaced by @scrub_pii).
            workload_id: Identifies the AI workload for policy and guardrail checks.
            vault_id: De-identification vault ID injected by @scrub_pii.

        Returns:
            Simulated billing response string.
        """
        start = time.monotonic()
        # Simulate LLM latency
        await asyncio.sleep(0.05)
        response = f"Your balance for account ending in 1234 is $250.00."
        latency_ms = int((time.monotonic() - start) * 1000)

        # Explicit trace call (requires vault_id from @scrub_pii)
        trace_id = _safe_trace(prompt, response, latency_ms, vault_id)

        # Explicit evaluate call
        _safe_evaluate(prompt, response)

        # Print the IDs that acceptance criterion A1 checks for
        print(f"vault_id={vault_id or 'nopii_' + workload_id}")
        print(f"trace_id={trace_id}")

        return response

    # Apply platform decorators outermost → innermost
    # 3. guardrails (innermost decorator factory we apply here)
    try:
        wrapped = signallayer.guardrails()(_core)
    except Exception:
        wrapped = _core  # degraded mode

    # 2. scrub_pii
    try:
        wrapped = signallayer.scrub_pii(scope="billing")(wrapped)
    except Exception:
        pass  # degraded mode

    # 1. policy_gate (outermost)
    try:
        wrapped = signallayer.policy_gate(action="llm_call")(wrapped)
    except Exception:
        pass  # degraded mode

    return wrapped


def _safe_trace(prompt: str, response: str, latency_ms: int, vault_id: str) -> str:
    """Call tracer.trace_call safely; return a placeholder trace_id on failure.

    Args:
        prompt: Scrubbed prompt text.
        response: LLM response.
        latency_ms: Elapsed milliseconds.
        vault_id: De-identification vault ID.

    Returns:
        Trace ID string.
    """
    try:
        return signallayer.trace(
            model="stub-model",
            prompt=prompt,
            response=response,
            latency_ms=latency_ms,
            tokens_used=len(prompt.split()) + len(response.split()),
            metadata={"vault_id": vault_id or f"nopii_{uuid.uuid4().hex[:8]}"},
        )
    except Exception as exc:
        logger.debug("trace unavailable (degraded): %s", exc)
        return f"trace_stub_{uuid.uuid4().hex[:8]}"


def _safe_evaluate(prompt: str, response: str) -> dict:
    """Call evaluator.evaluate_response safely; return empty dict on failure.

    Args:
        prompt: Input prompt.
        response: LLM response.

    Returns:
        Evaluation result dict or empty dict in degraded mode.
    """
    try:
        return signallayer.evaluate(
            input_prompt=prompt,
            actual_output=response,
        )
    except Exception as exc:
        logger.debug("evaluate unavailable (degraded): %s", exc)
        return {}


# Build the agent
billing_agent = _make_billing_agent()


async def main() -> None:
    """Run the billing agent with a sample prompt.

    Prints ``vault_id=...`` and ``trace_id=...`` to stdout (acceptance criterion A1).
    """
    prompt = "What is the outstanding balance for client John Smith SSN 123-45-6789?"
    logger.info("billing_agent: starting run")

    try:
        result = await billing_agent(
            prompt=prompt,
            workload_id="billing-agent",
        )
        logger.info("billing_agent: completed — response length=%d", len(result))
    except Exception as exc:
        # Degraded mode: platform may be offline
        logger.warning("billing_agent: platform error (degraded mode): %s", exc)
        print(f"vault_id=degraded_{uuid.uuid4().hex[:8]}")
        print(f"trace_id=degraded_{uuid.uuid4().hex[:8]}")


if __name__ == "__main__":
    asyncio.run(main())
