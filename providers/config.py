"""Provider backend configuration — env-var-driven, validated at import time.

All five backend selections are validated against their respective enum sets.
An unknown value raises pydantic.ValidationError immediately (fail-closed).

Environment variables (all optional, all have defaults):
  SCRUBBER_BACKEND   presidio | regex | noop          (default: presidio)
  TRACER_BACKEND     langfuse | stdout | noop          (default: langfuse)
  EVAL_BACKEND       deepeval | noop                   (default: deepeval)
  MEMORY_BACKEND     postgres | jsonl | noop           (default: postgres)
  RAG_BACKEND        azure_search | noop               (default: azure_search)

Usage:
    from providers.config import ProviderSettings
    settings = ProviderSettings()           # reads from env + .env
    print(settings.scrubber_backend)        # e.g. 'presidio'
"""

from __future__ import annotations

from enum import Enum

from pydantic import field_validator
from pydantic_settings import BaseSettings


class ScrubberBackendChoice(str, Enum):
    """Supported scrubber backend identifiers."""

    presidio = "presidio"
    regex = "regex"
    noop = "noop"


class TracerBackendChoice(str, Enum):
    """Supported tracer backend identifiers."""

    langfuse = "langfuse"
    stdout = "stdout"
    noop = "noop"


class EvalBackendChoice(str, Enum):
    """Supported evaluator backend identifiers.

    ADR-003 (multi-vendor evals): ragas / promptfoo / openai_evals are
    declared here so the API catalog endpoint can surface them as roadmap
    items in the UI picker. They are NOT wired to backend modules yet —
    selecting one of them as the active EVAL_BACKEND will raise at
    construction time inside providers.registry.get_evaluator(). Tracked
    in docs/adr/ADR-003-multi-vendor-evals.md §7 Steps 2/4/5.
    """

    deepeval = "deepeval"
    ragas = "ragas"  # ADR-003 §7 Step 2 — pending
    promptfoo = "promptfoo"  # ADR-003 §7 Step 4 — pending
    openai_evals = "openai_evals"  # ADR-003 §7 Step 5 — pending (sidecar)
    noop = "noop"


class MemoryBackendChoice(str, Enum):
    """Supported memory backend identifiers."""

    postgres = "postgres"
    jsonl = "jsonl"
    noop = "noop"


class RagBackendChoice(str, Enum):
    """Supported RAG backend identifiers."""

    azure_search = "azure_search"
    noop = "noop"


class ProviderSettings(BaseSettings):
    """Pydantic v2 settings — reads from environment and local .env file.

    All fields accept enum-validated string values only. An unknown value
    (e.g. SCRUBBER_BACKEND=unknown) raises ValidationError at construction time
    so misconfigured deployments fail loudly at startup rather than silently
    falling through to wrong backends.
    """

    scrubber_backend: ScrubberBackendChoice = ScrubberBackendChoice.presidio
    tracer_backend: TracerBackendChoice = TracerBackendChoice.langfuse
    eval_backend: EvalBackendChoice = EvalBackendChoice.deepeval
    memory_backend: MemoryBackendChoice = MemoryBackendChoice.postgres
    rag_backend: RagBackendChoice = RagBackendChoice.azure_search

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
        # Allow pydantic to coerce bare string env var values into the Enum
        "use_enum_values": False,
    }

    @field_validator(
        "scrubber_backend",
        "tracer_backend",
        "eval_backend",
        "memory_backend",
        "rag_backend",
        mode="before",
    )
    @classmethod
    def _coerce_to_enum(cls, v: object) -> object:
        """Accept string values from env vars by passing them through unchanged.

        Pydantic v2 will attempt to coerce the string to the Enum after this
        validator runs. If the string is not a valid enum value, a ValidationError
        is raised automatically — no explicit raise needed here.
        """
        return v
