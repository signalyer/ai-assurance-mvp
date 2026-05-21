"""Langfuse tracer backend — calls tracer._trace_call_impl.

CIRCULAR IMPORT PREVENTION:
  tracer.trace_call() is a proxy:
    trace_call(...) -> get_tracer().trace_call(...) -> LangfuseTracer.trace_call(...)

  This method MUST call tracer._trace_call_impl() (private), NOT tracer.trace_call().
  Calling tracer.trace_call() from here creates infinite recursion.

The stdout backend is also provided here as a lightweight alternative for
local development that avoids the Langfuse dependency entirely.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class LangfuseTracer:
    """TracerBackend that delegates to tracer._trace_call_impl (Langfuse Cloud)."""

    def trace_call(
        self,
        model: str,
        prompt: str,
        response: str,
        latency_ms: int,
        tokens_used: int,
        metadata: dict,
    ) -> str:
        """Send a model call trace to Langfuse.

        Calls tracer._trace_call_impl() (private) to avoid the infinite recursion
        that would result from calling the public trace_call() proxy:
          tracer.trace_call -> get_tracer().trace_call -> here -> tracer.trace_call -> ...

        IMPORTANT: *prompt* MUST be pre-scrubbed before calling. When
        SCRUBBER_ENABLED=true, metadata must contain a non-empty 'vault_id'.

        Args:
            model:       Model identifier string.
            prompt:      SCRUBBED prompt text — never raw.
            response:    Model response text.
            latency_ms:  End-to-end latency in milliseconds.
            tokens_used: Total tokens consumed.
            metadata:    Arbitrary metadata dict (must include 'vault_id' when
                         SCRUBBER_ENABLED=true).

        Returns:
            Opaque trace ID string from Langfuse (or a noop ID on failure).
        """
        logger.debug(
            "LangfuseTracer.trace_call: entry model=%s latency_ms=%d tokens_used=%d",
            model, latency_ms, tokens_used,
        )
        # Call _trace_call_impl (private) NOT trace_call (public proxy) — avoids recursion.
        from tracer import _trace_call_impl

        trace_id = _trace_call_impl(
            model=model,
            prompt=prompt,
            response=response,
            latency_ms=latency_ms,
            tokens_used=tokens_used,
            metadata=metadata,
        )
        logger.debug("LangfuseTracer.trace_call: exit trace_id=%s", trace_id)
        return trace_id


class StdoutTracer:
    """TracerBackend that writes traces to the Python structured logger only.

    Intended for local development and CI where Langfuse credentials are
    unavailable. No external network calls are made.
    """

    def trace_call(
        self,
        model: str,
        prompt: str,
        response: str,
        latency_ms: int,
        tokens_used: int,
        metadata: dict,
    ) -> str:
        """Log trace details via structured logging and return a local trace ID.

        Args:
            model:       Model identifier string.
            prompt:      Prompt text (should still be scrubbed even in stdout mode).
            response:    Response text.
            latency_ms:  Latency in milliseconds.
            tokens_used: Total tokens consumed.
            metadata:    Arbitrary metadata dict.

        Returns:
            Local trace ID in the form 'stdout-trace-<timestamp>'.
        """
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        trace_id = f"stdout-trace-{ts}"
        logger.info(
            "StdoutTracer.trace_call: model=%s latency_ms=%d tokens_used=%d "
            "prompt_length=%d response_length=%d trace_id=%s vault_id=%s",
            model,
            latency_ms,
            tokens_used,
            len(prompt),
            len(response),
            trace_id,
            metadata.get("vault_id", "(missing)"),
        )
        return trace_id
