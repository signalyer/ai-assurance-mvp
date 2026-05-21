"""Providers package — env-var-driven backend abstraction layer.

Exposes five factory functions that return singleton backend instances
for scrubbing, tracing, evaluation, episodic memory, and RAG retrieval.
Each factory reads ProviderSettings (validated at module load) and caches
its instance via lru_cache — safe to import and call from anywhere.

Quick start:
    from providers import get_scrubber, get_tracer, get_evaluator
    from providers import get_memory_backend, get_rag_backend

    scrubbed, vault_id = get_scrubber().tokenise(raw_text, scope="my_scope")
    trace_id = get_tracer().trace_call(model, scrubbed, response, latency_ms, tokens, metadata)
    scores = get_evaluator().evaluate(prompt, response, context=[])

Environment variables (all optional, validated against enum at startup):
    SCRUBBER_BACKEND   presidio | regex | noop          (default: presidio)
    TRACER_BACKEND     langfuse | stdout | noop          (default: langfuse)
    EVAL_BACKEND       deepeval | noop                   (default: deepeval)
    MEMORY_BACKEND     postgres | jsonl | noop           (default: postgres)
    RAG_BACKEND        azure_search | noop               (default: azure_search)

An unknown value (e.g. SCRUBBER_BACKEND=invalid) raises ValidationError at
import time so misconfigured deployments fail loudly at startup.
"""

from __future__ import annotations

from providers.registry import (
    clear_registry,
    get_evaluator,
    get_memory_backend,
    get_rag_backend,
    get_scrubber,
    get_tracer,
)

__all__ = [
    "get_scrubber",
    "get_tracer",
    "get_evaluator",
    "get_memory_backend",
    "get_rag_backend",
    # clear_registry is intentionally NOT in __all__ — test-only helper, not public API
]
