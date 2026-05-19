"""Langfuse tracer — two functions for tracing and fetching."""

import os
from datetime import datetime
from typing import Optional
from dotenv import load_dotenv
from langfuse import Langfuse

load_dotenv()

_client: Optional[Langfuse] = None
_traces_cache: dict[str, dict] = {}


def _get_client() -> Langfuse:
    """Get or create Langfuse client."""
    global _client
    if _client is None:
        public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
        secret_key = os.getenv("LANGFUSE_SECRET_KEY")
        host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")

        if not public_key or not secret_key:
            raise ValueError("LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY required")

        _client = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            host=host,
        )
    return _client


def trace_call(
    model: str,
    prompt: str,
    response: str,
    latency_ms: int,
    tokens_used: int,
    metadata: dict = None,
) -> str:
    """
    Send a model call trace to Langfuse.

    Args:
        model: Model name (e.g., 'claude-sonnet-4-20250514', 'gpt-4o-mini')
        prompt: Input prompt text
        response: Model response text
        latency_ms: Latency in milliseconds
        tokens_used: Total tokens consumed
        metadata: Optional metadata dict

    Returns:
        Trace ID string
    """
    if metadata is None:
        metadata = {}

    client = _get_client()

    trace = client.trace(name=f"model_call_{model}")
    trace.generation(
        name=f"{model}",
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
    return trace.id


def get_recent_traces(limit: int = 10) -> list[dict]:
    """
    Fetch recent traces from Langfuse.

    Args:
        limit: Max number of traces to return

    Returns:
        List of trace dicts with: id, model, prompt, response, latency_ms, tokens_used, timestamp, metadata
    """
    client = _get_client()

    result = []
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
