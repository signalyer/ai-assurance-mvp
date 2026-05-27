"""Provider backend registry — factory functions with lru_cache singleton caching.

Each get_*() function returns the single backend instance for its service.
Instances are created once (lazy, on first call) and cached via lru_cache(maxsize=1).
This ensures connection pools (Postgres engine) and SDK clients (Langfuse) are
reused across calls — never recreated per request.

Backend selection is driven by ProviderSettings (env-var validated at module load).
An unknown backend name raises ValidationError at module load — fail-closed.

Public API:
    get_scrubber()        -> ScrubberBackend
    get_tracer()          -> TracerBackend
    get_evaluator()       -> EvaluatorBackend
    get_memory_backend()  -> MemoryBackend
    get_rag_backend()     -> RagBackend
    clear_registry()      -> None  (test helper — clears lru_cache on all factories)
"""

from __future__ import annotations

import logging
from functools import lru_cache

from providers.config import (
    EvalBackendChoice,
    MemoryBackendChoice,
    ProviderSettings,
    RagBackendChoice,
    ScrubberBackendChoice,
    TracerBackendChoice,
)
from providers.protocols import (
    EvaluatorBackend,
    MemoryBackend,
    RagBackend,
    ScrubberBackend,
    TracerBackend,
)

logger = logging.getLogger(__name__)

# Settings are read once at module load — ValidationError here is intentional (fail-closed)
_settings: ProviderSettings = ProviderSettings()

logger.info(
    "providers.registry: config loaded — scrubber=%s tracer=%s eval=%s memory=%s rag=%s",
    _settings.scrubber_backend,
    _settings.tracer_backend,
    _settings.eval_backend,
    _settings.memory_backend,
    _settings.rag_backend,
)


@lru_cache(maxsize=1)
def get_scrubber() -> ScrubberBackend:
    """Return the active ScrubberBackend instance (cached after first call).

    Backend selection:
      presidio → PresidioScrubber  (Presidio NER + regex layer + de-ID vault)
      regex    → RegexScrubber     (regex patterns only, no Presidio dependency)
      noop     → NoopScrubber      (passthrough — returns text unchanged)

    Returns:
        An instance satisfying the ScrubberBackend Protocol — never None.

    Raises:
        ValueError: If SCRUBBER_BACKEND has a value not covered by the enum
                    (should not happen — ValidationError fires at module load first).
    """
    choice = _settings.scrubber_backend
    logger.info("get_scrubber: initialising backend=%s", choice)

    if choice == ScrubberBackendChoice.presidio:
        from providers.backends.scrubber_presidio import PresidioScrubber
        return PresidioScrubber()

    if choice == ScrubberBackendChoice.regex:
        from providers.backends.scrubber_regex import RegexScrubber
        return RegexScrubber()

    if choice == ScrubberBackendChoice.noop:
        from providers.backends.noop import NoopScrubber
        return NoopScrubber()

    raise ValueError(
        f"Unknown SCRUBBER_BACKEND value: {choice!r}. "
        f"Valid values: {[c.value for c in ScrubberBackendChoice]}"
    )


@lru_cache(maxsize=1)
def get_tracer() -> TracerBackend:
    """Return the active TracerBackend instance (cached after first call).

    Backend selection:
      langfuse → LangfuseTracer  (Langfuse Cloud SDK — delegates to tracer.trace_call)
      stdout   → StdoutTracer    (structured logger only — no external network calls)
      noop     → NoopTracer      (generates trace ID, discards all data)

    Returns:
        An instance satisfying the TracerBackend Protocol — never None.
    """
    choice = _settings.tracer_backend
    logger.info("get_tracer: initialising backend=%s", choice)

    if choice == TracerBackendChoice.langfuse:
        from providers.backends.tracer_langfuse import LangfuseTracer
        return LangfuseTracer()

    if choice == TracerBackendChoice.stdout:
        from providers.backends.tracer_langfuse import StdoutTracer
        return StdoutTracer()

    if choice == TracerBackendChoice.noop:
        from providers.backends.noop import NoopTracer
        return NoopTracer()

    raise ValueError(
        f"Unknown TRACER_BACKEND value: {choice!r}. "
        f"Valid values: {[c.value for c in TracerBackendChoice]}"
    )


@lru_cache(maxsize=1)
def get_evaluator() -> EvaluatorBackend:
    """Return the active EvaluatorBackend instance (cached after first call).

    Backend selection:
      deepeval → DeepEvalEvaluator  (DeepEval 5-metric suite via evaluator.evaluate_response)
      noop     → NoopEvaluator      (returns all metrics as skipped=True, score=None)

    Returns:
        An instance satisfying the EvaluatorBackend Protocol — never None.
    """
    choice = _settings.eval_backend
    logger.info("get_evaluator: initialising backend=%s", choice)

    if choice == EvalBackendChoice.deepeval:
        from providers.backends.deepeval_evaluator import DeepEvalEvaluator
        return DeepEvalEvaluator()

    if choice == EvalBackendChoice.noop:
        from providers.backends.noop import NoopEvaluator
        return NoopEvaluator()

    # ADR-003 §7 Steps 2/4/5 — enum entries declared so the catalog
    # endpoint can surface them as roadmap items, but no backend module
    # is wired yet. Selecting one as the active EVAL_BACKEND must fail
    # loudly with an actionable message.
    if choice in (
        EvalBackendChoice.ragas,
        EvalBackendChoice.promptfoo,
        EvalBackendChoice.openai_evals,
    ):
        raise NotImplementedError(
            f"EVAL_BACKEND={choice.value!r} is declared in ADR-003 but the "
            f"backend module has not been built yet. See "
            f"docs/adr/ADR-003-multi-vendor-evals.md §7 for the rollout "
            f"sequence. Set EVAL_BACKEND=deepeval or noop for now."
        )

    raise ValueError(
        f"Unknown EVAL_BACKEND value: {choice!r}. "
        f"Valid values: {[c.value for c in EvalBackendChoice]}"
    )


@lru_cache(maxsize=1)
def get_memory_backend() -> MemoryBackend:
    """Return the active MemoryBackend instance (cached after first call).

    Backend selection:
      postgres → PostgresMemory  (Postgres via domain.agent_memory, SQLAlchemy pool)
      jsonl    → NoopMemory      (jsonl backend not yet implemented — uses noop fallback)
      noop     → NoopMemory      (discards all writes, returns empty reads)

    Returns:
        An instance satisfying the MemoryBackend Protocol — never None.
    """
    choice = _settings.memory_backend
    logger.info("get_memory_backend: initialising backend=%s", choice)

    if choice == MemoryBackendChoice.postgres:
        from providers.backends.memory_postgres import PostgresMemory
        return PostgresMemory()

    if choice in (MemoryBackendChoice.jsonl, MemoryBackendChoice.noop):
        if choice == MemoryBackendChoice.jsonl:
            logger.warning(
                "get_memory_backend: jsonl backend not yet implemented — falling back to noop"
            )
        from providers.backends.noop import NoopMemory
        return NoopMemory()

    raise ValueError(
        f"Unknown MEMORY_BACKEND value: {choice!r}. "
        f"Valid values: {[c.value for c in MemoryBackendChoice]}"
    )


@lru_cache(maxsize=1)
def get_rag_backend() -> RagBackend:
    """Return the active RagBackend instance (cached after first call).

    Backend selection:
      azure_search → AzureSearchRag  (Azure AI Search hybrid — domain.rag_engine)
      noop         → NoopRag         (accepts index calls silently, returns empty searches)

    Returns:
        An instance satisfying the RagBackend Protocol — never None.
    """
    choice = _settings.rag_backend
    logger.info("get_rag_backend: initialising RAG backend=%s", choice)

    if choice == RagBackendChoice.azure_search:
        from providers.backends.rag_azure_search import AzureSearchRag
        return AzureSearchRag()

    if choice == RagBackendChoice.noop:
        from providers.backends.noop import NoopRag
        return NoopRag()

    raise ValueError(
        f"Unknown RAG_BACKEND value: {choice!r}. "
        f"Valid values: {[c.value for c in RagBackendChoice]}"
    )


def clear_registry() -> None:
    """Clear all lru_cache instances — test helper only.

    After calling this, the next call to any get_*() factory will re-read
    ProviderSettings from the current environment and construct a fresh backend.
    Useful in test suites that need to switch backends between test cases.

    WARNING: This does NOT re-read _settings at module level. To change the
    global settings object (e.g. in tests), reload the module or mutate
    _settings directly.
    """
    get_scrubber.cache_clear()
    get_tracer.cache_clear()
    get_evaluator.cache_clear()
    get_memory_backend.cache_clear()
    get_rag_backend.cache_clear()
    logger.debug("clear_registry: all lru_cache entries cleared")
