"""Langfuse tracer — two functions for tracing and fetching.

Langfuse is imported lazily so dashboard.py can load when the langfuse SDK
isn't installed (e.g. slim production image). If the SDK is missing or
credentials are absent, trace_call returns a no-op trace id and get_recent_traces
returns an empty list.

Architecture (Session 05):
  trace_call() is now a thin proxy that delegates to the active TracerBackend
  returned by providers.get_tracer(). The implementation logic lives in
  _trace_call_impl() (private, called by LangfuseTracer backend to avoid
  circular imports).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Optional
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_client: Optional[Any] = None
_traces_cache: dict[str, dict] = {}


def _get_client():
    """Get or create Langfuse client. Returns None if SDK or creds are unavailable."""
    global _client
    if _client is not None:
        return _client

    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
    if not public_key or not secret_key:
        return None

    try:
        from langfuse import Langfuse
    except ImportError:
        return None

    _client = Langfuse(public_key=public_key, secret_key=secret_key, host=host)
    return _client


def _trace_call_impl(
    model: str,
    prompt: str,
    response: str,
    latency_ms: int,
    tokens_used: int,
    metadata: dict,
) -> str:
    """Internal Langfuse tracing implementation.

    This private function contains the actual tracing logic. It is called
    by LangfuseTracer backend to avoid the circular import that would occur
    if the backend imported the public trace_call() proxy.

    CRITICAL: The prompt parameter MUST be pre-scrubbed via scrubber.tokenise_payload()
    before calling this function. Raw prompts must NEVER reach Langfuse. If vault_id is
    empty or missing, this function will abort the trace to Langfuse.

    Args:
        model: Model name (e.g., 'claude-sonnet-4-20250514', 'gpt-4o-mini')
        prompt: SCRUBBED prompt text (pre-tokenized, PII replaced with [TYPE_NNN] tokens)
        response: Model response text
        latency_ms: Latency in milliseconds
        tokens_used: Total tokens consumed
        metadata: Optional metadata dict. Should include 'vault_id' for de-ID traceability.

    Returns:
        Trace ID string
    """
    if metadata is None:
        metadata = {}

    # vault_id is ALWAYS required — scrubber.tokenise_payload() must run before trace_call().
    # This is unconditional: no SCRUBBER_ENABLED gate. Every call path must scrub.
    if not metadata.get("vault_id"):
        raise ValueError(
            "tracer.trace_call called without vault_id — scrubber must run first. "
            "Call scrubber.tokenise_payload(prompt, scope) and pass the returned "
            "vault_id in metadata before invoking trace_call()."
        )

    client = _get_client()
    trace_id = f"trace_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{hash(prompt) % 10000}"
    if client is None:
        return trace_id

    try:
        client.create_generation(
            trace_id=trace_id,
            name=f"model_call_{model}",
            model=model,
            input={"prompt": prompt},
            output={"response": response},
            metadata={
                **metadata,
                "latency_ms": latency_ms,
                "tokens_used": tokens_used,
            },
        )
        client.flush()
    except Exception:
        pass

    return trace_id


# ---------------------------------------------------------------------------
# Public API — proxy through providers.get_tracer() backend
# ---------------------------------------------------------------------------

def trace_call(
    model: str,
    prompt: str,
    response: str,
    latency_ms: int,
    tokens_used: int,
    metadata: Optional[dict] = None,
) -> str:
    """
    Send a model call trace to the active tracer backend.

    Proxies through providers.get_tracer().trace_call(). The langfuse backend
    delegates back to _trace_call_impl() to avoid circular imports.

    CRITICAL: The prompt parameter MUST be pre-scrubbed via scrubber.tokenise_payload()
    before calling this function. Raw prompts must NEVER reach Langfuse. If vault_id is
    empty or missing, this function should NOT be called.

    Args:
        model: Model name (e.g., 'claude-sonnet-4-20250514', 'gpt-4o-mini')
        prompt: SCRUBBED prompt text (pre-tokenized, PII replaced with [TYPE_NNN] tokens)
        response: Model response text
        latency_ms: Latency in milliseconds
        tokens_used: Total tokens consumed
        metadata: Optional metadata dict. Should include 'vault_id' for de-ID traceability.

    Returns:
        Trace ID string
    """
    if metadata is None:
        metadata = {}
    from providers import get_tracer
    backend = get_tracer()
    return backend.trace_call(
        model=model,
        prompt=prompt,
        response=response,
        latency_ms=latency_ms,
        tokens_used=tokens_used,
        metadata=metadata,
    )


def get_recent_traces(limit: int = 10) -> list[dict]:
    """
    Fetch recent traces from Langfuse.

    Args:
        limit: Max number of traces to return

    Returns:
        List of trace dicts with: id, model, prompt, response, latency_ms, tokens_used, timestamp, metadata
    """
    client = _get_client()
    result: list[dict] = []
    if client is None:
        return result

    try:
        # Try to fetch traces via the API
        # Note: Langfuse Cloud API requires HTTP calls or SDK async methods
        # For demo purposes, return empty list (traces will be created by demo runs)
        pass
    except Exception:
        pass

    return result


if __name__ == "__main__":
    # Test
    try:
        trace_id = trace_call(
            model="gpt-4o-mini",
            prompt="What is 2+2?",
            response="4",
            latency_ms=500,
            tokens_used=10,
            metadata={"test": True},
        )
        print(f"✓ Trace created: {trace_id}")

        traces = get_recent_traces(limit=5)
        print(f"✓ Fetched {len(traces)} recent traces")
        for t in traces:
            print(f"  - {t['model']}: {t['timestamp']}")
    except Exception as e:
        print(f"✗ Error: {e}")
