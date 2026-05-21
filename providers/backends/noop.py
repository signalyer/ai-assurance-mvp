"""No-op backend implementations for all five provider protocols.

Used in dev/test environments where live infrastructure (Presidio, Langfuse,
Postgres, Azure AI Search) is unavailable. All methods return safe, non-null
defaults so callers can branch on results without null-checking.

No-op contract:
  - tokenise()  → (original_text, "noop-vault-id")
  - restore()   → scrubbed (returned unchanged — no vault to reverse)
  - trace_call()→ deterministic noop-trace-<timestamp> ID
  - evaluate()  → all metrics skipped=True, score=None, passed=False
  - write()     → stable UUID string
  - read()      → []
  - stats()     → zeroed dict matching real backend shape
  - index()     → True (accepted, not stored)
  - search()    → []
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class NoopScrubber:
    """Scrubber that returns text unchanged — no PII detection, no vault."""

    def tokenise(self, text: str, scope: str) -> tuple[str, str]:
        """Return text unchanged with a stable noop vault_id.

        Args:
            text:  Any input text.
            scope: Ignored.

        Returns:
            (text, "noop-vault-id") — original text is returned unmodified.
        """
        logger.debug("NoopScrubber.tokenise: noop path (scope=%s)", scope)
        return text, "noop-vault-id"

    def restore(self, scrubbed: str, vault_id: str) -> str:
        """Return the scrubbed text unchanged — nothing to reverse in noop mode.

        Args:
            scrubbed: Input text (no tokens to replace).
            vault_id: Ignored.

        Returns:
            scrubbed unchanged.
        """
        logger.debug("NoopScrubber.restore: noop path (vault_id=%s)", vault_id)
        return scrubbed


class NoopTracer:
    """Tracer that logs to Python logger and returns a deterministic trace ID."""

    def trace_call(
        self,
        model: str,
        prompt: str,
        response: str,
        latency_ms: int,
        tokens_used: int,
        metadata: dict,
    ) -> str:
        """Log trace details locally and return a noop trace ID.

        Args:
            model:       Model identifier.
            prompt:      Prompt text (may be scrubbed or raw in noop mode).
            response:    Response text.
            latency_ms:  Latency in milliseconds.
            tokens_used: Token count.
            metadata:    Arbitrary metadata dict.

        Returns:
            Trace ID string in the form 'noop-trace-<timestamp>'.
        """
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        trace_id = f"noop-trace-{ts}"
        logger.info(
            "NoopTracer.trace_call: model=%s latency_ms=%d tokens_used=%d trace_id=%s",
            model, latency_ms, tokens_used, trace_id,
        )
        return trace_id


class NoopEvaluator:
    """Evaluator that marks all metrics as skipped."""

    def evaluate(
        self,
        input_prompt: str,
        actual_output: str,
        context: list[str],
    ) -> dict:
        """Return a skipped result for every standard metric.

        Args:
            input_prompt:  User query.
            actual_output: Model response.
            context:       Grounding context (ignored).

        Returns:
            Dict with keys: answer_relevancy, toxicity, hallucination,
            faithfulness, pii_leakage — all skipped with score=None.
        """
        logger.debug("NoopEvaluator.evaluate: returning skipped metrics")
        skipped_metric: dict = {
            "score": None,
            "passed": False,
            "skipped": True,
            "details": "Noop evaluator — no evaluation performed",
        }
        return {
            "answer_relevancy": skipped_metric,
            "toxicity": skipped_metric,
            "hallucination": skipped_metric,
            "faithfulness": skipped_metric,
            "pii_leakage": skipped_metric,
        }


class NoopMemory:
    """Memory backend that accepts writes silently and returns empty reads."""

    def write(
        self,
        workload_id: str,
        prompt: str,
        response: str,
        outcome: str,
        metadata: dict,
        ttl_seconds: int,
    ) -> str:
        """Accept the write and return a stable UUID without persisting.

        Args:
            workload_id: Workload identifier.
            prompt:      Prompt text.
            response:    Response text.
            outcome:     Outcome label.
            metadata:    Metadata dict.
            ttl_seconds: TTL (ignored).

        Returns:
            A new UUID string on every call.
        """
        episode_id = str(uuid.uuid4())
        logger.debug(
            "NoopMemory.write: noop for workload=%s outcome=%s episode_id=%s",
            workload_id, outcome, episode_id,
        )
        return episode_id

    def read(
        self,
        workload_id: str,
        query: str,
        top_k: int,
        lookback_days: int,
    ) -> list[dict]:
        """Return empty episode list.

        Args:
            workload_id:   Workload to search within (ignored).
            query:         Search terms (ignored).
            top_k:         Max results (ignored).
            lookback_days: Lookback window (ignored).

        Returns:
            Empty list.
        """
        logger.debug("NoopMemory.read: noop for workload=%s", workload_id)
        return []

    def stats(self) -> dict:
        """Return zeroed memory statistics matching the real backend shape.

        Returns:
            Dict with all counters at zero.
        """
        return {
            "total_episodes": 0,
            "episodes_by_workload": {},
            "oldest_episode": None,
            "expired_count": 0,
            "ttl_default_seconds": 0,
        }


class NoopRag:
    """RAG backend that accepts index calls silently and returns empty searches."""

    def index(
        self,
        doc_id: str,
        content: str,
        metadata: dict,
        scrub: bool,
    ) -> bool:
        """Accept the document without indexing.

        Args:
            doc_id:   Document ID (ignored).
            content:  Document content (ignored).
            metadata: Metadata (ignored).
            scrub:    Scrub flag (ignored).

        Returns:
            True — noop treats every index call as a logical success.
        """
        logger.debug("NoopRag.index: noop for doc_id=%s", doc_id)
        return True

    def search(
        self,
        query: str,
        top_k: int,
        hybrid: bool,
    ) -> list[dict]:
        """Return empty search results.

        Args:
            query:  Search query (ignored).
            top_k:  Result limit (ignored).
            hybrid: Hybrid mode flag (ignored).

        Returns:
            Empty list.
        """
        logger.debug("NoopRag.search: noop (query_length=%d)", len(query))
        return []

    def stats(self) -> dict:
        """Return zeroed RAG statistics matching the real backend shape.

        Returns:
            Dict with all counters at zero and model set to 'noop'.
        """
        return {
            "index_size": 0,
            "doc_count": 0,
            "last_updated": None,
            "embedding_model": "noop",
            "rejections_total": 0,
        }
