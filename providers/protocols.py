"""Typing Protocols for all provider backends.

Each Protocol is @runtime_checkable so backends can be verified with isinstance()
at construction time. All method signatures are kept minimal — backends delegate
to the underlying implementation modules rather than duplicating logic here.

Protocol hierarchy:
  ScrubberBackend   — PII tokenisation + vault restore
  TracerBackend     — LLM call tracing
  EvaluatorBackend  — multi-metric response evaluation
  MemoryBackend     — Tier 2 episodic memory (write / read / stats)
  RagBackend        — Tier 3 RAG corpus (index / search / stats)
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ScrubberBackend(Protocol):
    """Scrub PII from text and restore it from the de-ID vault."""

    def tokenise(self, text: str, scope: str) -> tuple[str, str]:
        """Replace PII in *text* with stable tokens.

        Args:
            text:  Raw input text that may contain PII.
            scope: Logical grouping label (e.g. 'api_call_xyz') for the vault entry.

        Returns:
            (scrubbed_text, vault_id) — vault_id is empty string when no PII found
            or on error (fail-closed: callers must check vault_id before trusting scrub).
        """
        ...

    def restore(self, scrubbed: str, vault_id: str) -> str:
        """Reverse PII scrubbing for *scrubbed* text using *vault_id*.

        Args:
            scrubbed: Text containing [ENTITY_TYPE_NNN] placeholder tokens.
            vault_id: Key returned by a prior tokenise() call.

        Returns:
            Original text with all tokens replaced by their PII values.

        Raises:
            ValueError: If vault_id is missing or expired.
        """
        ...


@runtime_checkable
class TracerBackend(Protocol):
    """Send LLM call telemetry to an observability back-end."""

    def trace_call(
        self,
        model: str,
        prompt: str,
        response: str,
        latency_ms: int,
        tokens_used: int,
        metadata: dict,
    ) -> str:
        """Record a single LLM call.

        IMPORTANT: *prompt* MUST be pre-scrubbed (PII tokenised) before calling.
        When SCRUBBER_ENABLED=true, metadata must contain a non-empty 'vault_id'.

        Args:
            model:       Model identifier string.
            prompt:      SCRUBBED prompt text — never raw.
            response:    Model response text.
            latency_ms:  End-to-end call latency in milliseconds.
            tokens_used: Total tokens consumed by the call.
            metadata:    Arbitrary key/value dict. Must include 'vault_id' when
                         SCRUBBER_ENABLED=true.

        Returns:
            Opaque trace ID string (used for cross-referencing with vault_id).
        """
        ...


@runtime_checkable
class EvaluatorBackend(Protocol):
    """Run multi-metric quality evaluation against a model response."""

    def evaluate(
        self,
        input_prompt: str,
        actual_output: str,
        context: list[str],
    ) -> dict:
        """Evaluate *actual_output* against the provided *input_prompt*.

        Args:
            input_prompt:  The user-facing query that produced the response.
            actual_output: The model response to evaluate.
            context:       Optional grounding context strings (required for
                           hallucination / faithfulness metrics).

        Returns:
            Dict mapping metric_name -> {score, passed, skipped, details}.
            Keys always present: answer_relevancy, toxicity, hallucination,
            faithfulness, pii_leakage.
        """
        ...


@runtime_checkable
class MemoryBackend(Protocol):
    """Tier 2 episodic memory store — read/write scrubbed episodes."""

    def write(
        self,
        workload_id: str,
        prompt: str,
        response: str,
        outcome: str,
        metadata: dict,
        ttl_seconds: int,
    ) -> str:
        """Persist a scrubbed episode.

        Args:
            workload_id: AI workload identifier (e.g., 'financial_advisor').
            prompt:      Pre-scrubbed prompt text.
            response:    Pre-scrubbed response text.
            outcome:     One of 'success', 'failure', 'review'.
            metadata:    Dict; must include 'vault_id' when SCRUBBER_ENABLED.
            ttl_seconds: Time-to-live for the episode in seconds.

        Returns:
            Episode ID string (UUID).
        """
        ...

    def read(
        self,
        workload_id: str,
        query: str,
        top_k: int,
        lookback_days: int,
    ) -> list[dict]:
        """Recall episodes matching *query* for *workload_id*.

        Args:
            workload_id:   Workload to search within.
            query:         Full-text search terms.
            top_k:         Maximum results to return.
            lookback_days: How many calendar days back to search.

        Returns:
            List of episode dicts ordered by relevance then recency.
            Empty list when memory is unavailable.
        """
        ...

    def stats(self) -> dict:
        """Return aggregate memory statistics.

        Returns:
            Dict with at minimum: total_episodes (int), episodes_by_workload (dict),
            oldest_episode (str|None), expired_count (int), ttl_default_seconds (int).
        """
        ...


@runtime_checkable
class RagBackend(Protocol):
    """Tier 3 RAG corpus — index documents and execute hybrid searches."""

    def index(
        self,
        doc_id: str,
        content: str,
        metadata: dict,
        scrub: bool,
    ) -> bool:
        """Add or update a document in the search corpus.

        Args:
            doc_id:   Unique document identifier.
            content:  Raw document text (will be scrubbed when scrub=True).
            metadata: Arbitrary key/value metadata stored alongside the document.
            scrub:    Whether to PII-scrub content before indexing. Default True.

        Returns:
            True if successfully indexed; False if rejected or disabled.
        """
        ...

    def search(
        self,
        query: str,
        top_k: int,
        hybrid: bool,
    ) -> list[dict]:
        """Search the corpus.

        Args:
            query:  Natural language query.
            top_k:  Maximum result count.
            hybrid: When True, combines BM25 with semantic vector reranking.

        Returns:
            List of result dicts with: id, content, score, metadata,
            bm25_score, semantic_score. Empty list on failure.
        """
        ...

    def stats(self) -> dict:
        """Return corpus statistics.

        Returns:
            Dict with at minimum: index_size (int), doc_count (int),
            last_updated (str|None), embedding_model (str), rejections_total (int).
        """
        ...
