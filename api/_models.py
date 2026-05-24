"""Cross-cutting response models shared across all api/*.py routers.

Locked by docs/plans/SESSION-13-api-typing-audit.md §2.
Changes here are breaking for every client. Bump __version__ on any change per the
bump rule in __version__.py.

Import discipline:
    - Routers import only what they use from this module.
    - Per-router response models live in the router file (default) or in
      api/<router>_models.py if the router has more than ~10 response models.
    - Do not import domain types here -- this module is the API boundary, not the
      domain boundary.
"""
from __future__ import annotations

from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class GovernanceMetadata(BaseModel):
    """Cross-cutting governance overlay per docs/target-architecture.md §5.

    Populated on responses from endpoints that trigger the decorator chain
    (@policy_gate -> @scrub_pii -> @guardrails -> @trace_llm_call -> @evaluate_response).
    Pure CRUD / catalog endpoints omit this field.

    SPA UX hook: CISO Console "explain finding" flyout reads trace_id and links
    directly to App Insights via the operation_Id correlation.
    """

    model_config = ConfigDict(extra="forbid")

    trace_id: str | None = Field(
        default=None,
        description="Langfuse trace_id (also App Insights operation_Id; identical value).",
    )
    vault_id: str | None = Field(
        default=None,
        description="Scrubber vault reference if PII was tokenised; None if no PII present.",
    )
    policy_decision: Literal["ALLOW", "DENY", "WARN"] | None = None
    guardrail_verdict: Literal[
        "PASS", "BLOCK_INJECTION", "BLOCK_TOPIC", "BLOCK_SAFETY"
    ] | None = None
    eval_scores: dict[str, float] | None = Field(
        default=None,
        description="DeepEval 6-metric scores when evaluator ran; keys per evaluator.py.",
    )
    chain_hash: str | None = Field(
        default=None,
        description="SHA-256 hash from audit_chain.py for the originating event.",
    )
    served_from_cache: bool | None = None


class CursorPage(BaseModel, Generic[T]):
    """Cursor-paginated collection response.

    Pagination contract per audit doc §1.4: cursor-based only, never offset/limit.
    `total` is optional because counting JSONL rows is O(N); routers reading from
    events.jsonl set it to None and rely on `next_cursor is None` to signal end.
    """

    model_config = ConfigDict(extra="forbid")

    items: list[T]
    total: int | None = Field(
        default=None,
        description="Total count when cheap to compute; null when computing would scan.",
    )
    next_cursor: str | None = Field(
        default=None,
        description="Opaque cursor for next page; null at end of stream.",
    )
    limit: int = Field(description="Echoed limit from request for client verification.")


class JobResponse(BaseModel):
    """Async job response per CLAUDE.md async-first rule.

    Returned by any endpoint that triggers a Claude call > 5s (or queues background work).
    Frontend polls GET /api/v1/jobs/{job_id} until status is terminal.
    """

    model_config = ConfigDict(extra="forbid")

    job_id: str
    status: Literal["queued", "running", "complete", "failed"]
    progress: float | None = Field(default=None, ge=0.0, le=1.0)
    eta_seconds: int | None = None
    result_url: str | None = Field(
        default=None,
        description="Populated when status == 'complete'.",
    )
    error: str | None = Field(
        default=None,
        description="Populated when status == 'failed'. Never contains stack trace.",
    )
    governance: GovernanceMetadata | None = None


class ConflictDetail(BaseModel):
    """Structured 409 body for typed conflicts (gate denials, idempotency, state transitions).

    Vocabulary locked at the 4 values below per audit doc §10 resolution #3.
    Adding a new value = minor __version__ bump.
    """

    model_config = ConfigDict(extra="forbid")

    reason: str
    conflict_type: Literal[
        "GATE_DENIED", "POLICY_DENIED", "IDEMPOTENCY", "STATE_TRANSITION"
    ]
    policy_id: str | None = None
    existing_id: str | None = None


class ServerErrorDetail(BaseModel):
    """Structured 500 body. Never contains stack traces or secrets."""

    model_config = ConfigDict(extra="forbid")

    detail: str
    trace_id: str
    request_id: str


class OkResponse(BaseModel):
    """Minimal mutation acknowledgment for fire-and-forget endpoints.

    Use ONLY when the server has no resource state to echo back to the client
    (e.g. notifications/reset, purge endpoints). For state-changing mutations
    where the client wants the new state without a re-fetch, return the typed
    resource directly (e.g. notifications/{id}/resolve -> NotificationOut).
    """

    model_config = ConfigDict(extra="forbid")

    ok: Literal[True] = True
