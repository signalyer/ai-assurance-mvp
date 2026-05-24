# SESSION 13 · Day 1 — API Typing Audit & Conventions

> **Status:** Draft v1 — ready for review.
> **Created:** 2026-05-23
> **Branch:** `phase/13-engine-hardening`
> **Scope:** Doc-only deliverable. Locks conventions and per-router plan for Days 2–5
> of [SESSION-13](SESSION-13-v2-engine-hardening.md). **No code changes today.**
> **Supersedes (only within Session 13 scope):** the bare "pin response models on every endpoint"
> instruction in SESSION-13 §3.A1 — this doc is the *how*.
> **Drives:** [V2-PORTAL-SPLIT.md](V2-PORTAL-SPLIT.md) §5 OpenAPI hardening row.

---

## 0. Why this doc exists (the one-paragraph version)

The engine has **34 routers** and **~100 public endpoints** consumed by **four clients on day one**
(V1 static HTML, Team Workspace SPA, CISO Console SPA, `signallayer` SDK + `sl` CLI) and an
auditor/regulator integration as a fifth. Today the contract is implicit: most handlers return
bare `dict`, the same router uses four different envelope shapes (see [`api/grc.py`](../../api/grc.py)),
and Schemathesis would produce noise rather than signal against the current `/openapi.json`.

Day 2 starts a mechanical typing pass against this surface. Without conventions locked *first*,
that pass will encode whatever shape the first router happens to use — and every subsequent
client (SDK regen, codegen, audit export) inherits that accident as a contract. This doc locks
the conventions and produces the per-router plan, so Days 2–5 are mechanical, not architectural.

---

## 1. Locked conventions (cite this section in every Day 2-5 PR)

### 1.1 Response envelopes

| Shape | When to use | Example |
|---|---|---|
| **Bare resource object** | `GET /resource/{id}`, single-row reads | `GET /api/grc/ai-systems/{id}` → `AiSystemDetailOut` |
| **`{items, total, next_cursor}`** | Any list/collection — even small ones | `GET /api/grc/findings` → `FindingsPageOut` |
| **`{ok: true}` + resource fields** | Mutations returning the new state | `POST /api/grc/notifications/{id}/resolve` → `NotificationResolveOut` |
| **`JobResponse`** | Any async-emitting endpoint (CLAUDE.md async-first rule) | `POST /api/batch/run` → `JobResponse` |

**Forbidden shapes** (drop on sight):
- Bare list at top level (e.g. `return [...]`) — blocks adding pagination metadata later
- Object-spread responses (e.g. `return {**system, "findings": [...], "evidence": [...]}` in
  [`grc.py:120`](../../api/grc.py)) — must be a defined `AiSystemDetailOut` model
- Mixed `{ok: true, ...resource}` where the resource also has an `ok` field — collision risk

**Why no global envelope:** Schemathesis' shape-conformance check is sharper without a
`{data: unknown}` wrapper. The SDK ([`sdk/signallayer/client.py`](../../sdk/signallayer/client.py))
already wraps responses client-side as `Result[T] = Ok | Err` — a second server-side envelope
is redundant. App Service health probes assume bare JSON for `/api/health`.

### 1.2 Error contract

| Status | Body shape | Pydantic model | Use when |
|---|---|---|---|
| `400` | `{detail: str}` | — (FastAPI default) | Malformed input not caught by Pydantic |
| `401` / `403` | `{detail: str}` | — (FastAPI default) | Auth / authz failure |
| `404` | `{detail: str}` | — (FastAPI default) | Resource not found |
| `409` | `{detail: ConflictDetail}` | `ConflictDetail` | Idempotency conflicts, gate denials |
| `422` | `{detail: list[ValidationDetail]}` | (FastAPI default Pydantic) | Schema validation |
| `500` | `{detail: str, trace_id: str}` | `ServerErrorDetail` | Unhandled exception — `trace_id` from App Insights |

**Custom typed details** (`ConflictDetail`, `ServerErrorDetail`) live in `api/_errors.py`,
registered as global exception handlers in `dashboard.py`. **No** custom error envelope that
wraps `detail` in a higher-level shape — Schemathesis natively understands FastAPI's default.

**Specific requirement for CISO Console:** Release Gate denials (`POST .../approve` → `409`)
must return `ConflictDetail` with `reason: str` and `policy_id: str | None`. Generic
`{detail: "denied"}` is insufficient for an audit artifact.

### 1.3 IDs, casing, timestamps

| Concern | Rule | Why |
|---|---|---|
| JSON field naming | `snake_case` (existing convention — lock it) | Consistency with Python attribute access; SDK ergonomics |
| Resource IDs | Opaque string (never int, never raw `uuid.UUID`) | JSONL SSOT uses strings; UUIDs leak storage layer; ints rule out hash-based IDs |
| Timestamps | ISO 8601 UTC string with `Z` suffix | `tracer.py` and `audit_chain.py` already do this; Postgres projections coerce |
| Enum serialization | `enum.value` as string (never numeric) | Matches existing `runtime_v2._ser()` and `domain/models.py` patterns |
| Booleans | Always `true` / `false`, never `0/1` or `"yes"/"no"` | Default Pydantic; just don't deviate |

**Reserve for V3 multi-tenant:** field names `tenant_id`, `org_id`, `subject_id` are reserved
as future cross-cutting fields. Don't use them for anything else now.

### 1.4 Pagination — cursor only

```python
class CursorPage[T](BaseModel):
    model_config = ConfigDict(extra='forbid')
    items: list[T]
    total: int | None = None          # populated when cheap; null when full count would scan
    next_cursor: str | None = None    # opaque server-encoded; None = end of stream
    limit: int                         # echoed back so clients can verify
```

**Default `limit=50`, max `200`.** Query parameter: `cursor: str | None = None, limit: int = Query(50, ge=1, le=200)`.

**Why cursor over offset/limit, in this stack:**
- JSONL append-only files cannot efficiently offset-scan at scale; cursor = byte offset or
  event sequence is O(1).
- Postgres event projection (Session 09) tables already use `event_id` ordering.
- Right-to-Forget cascade (Session 08) mutates historical events; offset pagination would
  skip or duplicate rows mid-cascade. Cursor based on stable event hash does not.

**`total` field is optional** because counting JSONL rows is O(N). Routers that already have
a cheap count (mock_data, small in-memory lists) populate it; routers reading from
`events.jsonl` set it to `null` and rely on `next_cursor == null` to signal end of stream.

### 1.5 URL versioning — `/api/v1/*` alias

**Decision (locked):** Mount `/api/v1/*` as an alias of `/api/*` via a thin path-rewrite
middleware. Existing V1 static HTML keeps using `/api/*` unchanged. SPAs, SDK, and CLI
target `/api/v1/*`.

**Why a middleware, not router re-inclusion:** Routers already have prefixes (`/api/grc`,
`/api/frameworks`, `/api/grc/runtime/v2`). Re-mounting them under a second prefix would
duplicate every route in `/openapi.json` and double Schemathesis runtime. The middleware
approach keeps OpenAPI single-sourced.

**Implementation sketch (Day 5 task, not today):**
```python
# middleware/api_version_alias.py
class ApiVersionAliasMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path
        if path.startswith("/api/v1/"):
            # Rewrite to /api/* for downstream routers
            request.scope["path"] = "/api/" + path[len("/api/v1/"):]
            request.scope["raw_path"] = request.scope["path"].encode()
        return await call_next(request)
```

**OpenAPI implication:** The spec advertises `/api/v1/*` (set via `app.servers` + a
post-processing step in the OpenAPI generator hook). `/api/*` continues to work but is
**not advertised** in the published spec — it's a backward-compat surface, not a published
contract. V1 HTML keeps working; SDK/SPA codegen sees only `/api/v1/*`.

**Grandfathering plan:** When V1 static HTML is decommissioned in V2 Phase 5 (DNS cutover
week), remove the alias middleware in the same commit. Until then, `/api/*` is the safety net.

### 1.6 Cross-cutting governance field — `governance: GovernanceMetadata | None`

**Decision (locked):** Every response that touches the decorator chain
(`@policy_gate → @scrub_pii → @guardrails → @trace_llm_call → @evaluate_response`) carries
an optional `governance: GovernanceMetadata` field. Composition, not inheritance — added per
response model, not via a base class.

```python
class GovernanceMetadata(BaseModel):
    model_config = ConfigDict(extra='forbid')
    trace_id: str | None = None              # Langfuse trace_id + App Insights operation_Id (same value)
    vault_id: str | None = None              # scrubber vault reference, if PII was tokenized
    policy_decision: Literal["ALLOW", "DENY", "WARN"] | None = None
    guardrail_verdict: Literal["PASS", "BLOCK_INJECTION", "BLOCK_TOPIC", "BLOCK_SAFETY"] | None = None
    eval_scores: dict[str, float] | None = None   # DeepEval 6-metric suite when run
    chain_hash: str | None = None            # audit_chain.py event hash for traceability
    served_from_cache: bool | None = None    # provenance
```

**Endpoints that MUST populate it** (LLM-triggering or governance-emitting):
- `api/assurance_model.py` — all `ask`/`summarize_*`/`draft_*` endpoints
- `api/batch.py` — `run_batch`, `run_domain_test_suite`
- `api/demo_run.py` — anything that calls `tracer.trace_call()`
- `api/right_to_forget.py` — every cascade response (`chain_hash` required)
- `api/audit_verify.py` — already exposes chain data; align field names

**Endpoints that omit it** (pure CRUD on mock data or static config):
- `api/grc.py` — KPIs, list endpoints, notifications (no LLM call)
- `api/framework.py`, `api/frameworks.py` — read-only catalog
- `api/guide.py`, `api/connectors.py` — config/metadata

**SPA UX hook:** the CISO Console "explain this finding" flyout reads `trace_id` and links
directly to the App Insights query — that's the cross-tool traceability the regulated-buyer
pitch depends on.

### 1.7 Pydantic v2 boilerplate (every response model)

```python
from pydantic import BaseModel, ConfigDict

class Foo(BaseModel):
    model_config = ConfigDict(
        extra='forbid',          # Schemathesis catches "router added a field" regressions
        populate_by_name=True,   # required for any field with alias=
        ser_json_timedelta='iso8601',
    )
    # ... fields ...
```

**Why `extra='forbid'`:** without it, Schemathesis cannot distinguish "field added on purpose"
from "field added by accident". With it, every new field is an explicit contract change visible
in `docs/openapi-v1.json` diff.

### 1.8 `operationId` naming

**Pattern:** `<resource>_<action>` snake_case, globally unique.

| Verb | Action verb |
|---|---|
| `GET /resource` | `list` |
| `GET /resource/{id}` | `get` |
| `POST /resource` | `create` |
| `PATCH /resource/{id}` | `update` |
| `DELETE /resource/{id}` | `delete` |
| `POST /resource/{id}/action` | `<action>` (e.g. `approve`, `resolve`) |
| `GET /resource/_meta` | `meta` |
| `GET /resource/export` | `export` |

**Examples:**
- `GET /api/grc/ai-systems` → `ai_systems_list`
- `GET /api/grc/ai-systems/{id}` → `ai_systems_get`
- `POST /api/grc/notifications/{id}/resolve` → `notifications_resolve`
- `POST /api/right-to-forget` → `right_to_forget_initiate`
- `GET /api/audit/verify` → `audit_verify`
- `POST /api/frameworks/{slug}/export` → `frameworks_export`

**Why this matters:** OpenAPI Generator produces SDK method names directly from `operationId`.
Bad names = bad SDK ergonomics for every downstream codegen. Full table in §3 below.

### 1.9 Sensitive-field stripping (Schemathesis custom check)

**Hard rules** (encoded as Schemathesis hooks in §5):
- No response field named `raw_prompt`, `unscrubbed_prompt`, `pii_entities` (the values, not metadata)
- No response field containing a value matching `re.compile(r"sk-(ant|proj|[a-z]+)-[A-Za-z0-9]{20,}")`
- No response field exposing `session_id` cookie value (the `Session` cookie itself is fine; the body must not echo it)
- Vault tokens (`vault_id`) are fine — they're opaque references; the contents in the vault are not

These match the existing CLAUDE.md security rule "Langfuse gets scrubbed_prompt — never raw_prompt"
extended to the API surface.

---

## 2. Cross-cutting models (copy-paste ready)

Place at `api/_models.py`. Imported by per-router `models.py` files.

```python
"""Cross-cutting response models shared across all api/*.py routers.

Locked by docs/plans/SESSION-13-api-typing-audit.md §2.
Changes here are breaking for every client. Bump info.version on any change.
"""
from __future__ import annotations

from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class GovernanceMetadata(BaseModel):
    """Cross-cutting governance overlay per docs/target-architecture.md §5."""
    model_config = ConfigDict(extra='forbid')

    trace_id: str | None = Field(
        default=None,
        description="Langfuse trace_id (also App Insights operation_Id; identical value).",
    )
    vault_id: str | None = Field(
        default=None,
        description="Scrubber vault reference if PII was tokenized; None if no PII present.",
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
    """Cursor-paginated collection response."""
    model_config = ConfigDict(extra='forbid')

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

    Returned by any endpoint that triggers a Claude call > 5s. Frontend polls
    GET /api/v1/jobs/{job_id} until status terminal.
    """
    model_config = ConfigDict(extra='forbid')

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
    """Structured 409 body for typed conflicts (gate denials, idempotency)."""
    model_config = ConfigDict(extra='forbid')

    reason: str
    conflict_type: Literal[
        "GATE_DENIED", "POLICY_DENIED", "IDEMPOTENCY", "STATE_TRANSITION"
    ]
    policy_id: str | None = None
    existing_id: str | None = None


class ServerErrorDetail(BaseModel):
    """Structured 500 body. Never contains stack traces or secrets."""
    model_config = ConfigDict(extra='forbid')

    detail: str
    trace_id: str
    request_id: str


class OkResponse(BaseModel):
    """Minimal mutation acknowledgment. Use only when no resource state to echo."""
    model_config = ConfigDict(extra='forbid')

    ok: Literal[True] = True
```

---

## 3. Per-router audit (the work)

**Legend:**
- **Tier P0** = both SPAs depend on it. Type first.
- **Tier P1** = one SPA + SDK. Type second.
- **Tier P2** = SDK or CLI only, or internal demo. Type last.
- **Tier P3** = mock-data-only demo router; type minimally (still need shape lock for Schemathesis but no rich types).

### 3.1 Day 2 — Tier P0 (~30 endpoints across 5 files)

| File | Endpoints | Notes |
|---|---|---|
| [`api/grc.py`](../../api/grc.py) | 20 | The drift offender. Will produce ~15 new `BaseModel` types. `_list_ai_systems` returns `{**system, ...}` spread — split into `AiSystemSummaryOut` (list view) and `AiSystemDetailOut` (single view). Notifications mutation responses → `OkResponse`. |
| [`api/runtime_v2.py`](../../api/runtime_v2.py) | 14 | **Bonus:** delete `_ser()` helper entirely once Pydantic models replace dataclass→dict conversion. Request models already exist (good). Response models all new. |
| [`api/findings_v2.py`](../../api/findings_v2.py) | 5 | Used by CISO Console Findings tab + Team Workspace own-team filter. |
| [`api/release_gates.py`](../../api/release_gates.py) | 4 | `create_exception` body should return `ConflictDetail` on denial (currently `dict`). |
| [`api/evals_v2.py`](../../api/evals_v2.py) | 3 | `run_simulated_suite` is async-emitting → returns `JobResponse`. |

### 3.2 Day 3 — Tier P1 (~25 endpoints across 8 files)

| File | Endpoints | Notes |
|---|---|---|
| [`api/assurance_model.py`](../../api/assurance_model.py) | 12 | All `ask`/`summarize`/`explain`/`draft` endpoints populate `governance` field. `_dispatch` private — no change. |
| [`api/ai_system_edit.py`](../../api/ai_system_edit.py) | 6 | Mostly request models exist; add response. `decide_revision` → `ConflictDetail` on policy denial. |
| [`api/right_to_forget.py`](../../api/right_to_forget.py) | 4 | `chain_hash` required on all responses. Already has request models. |
| [`api/audit_verify.py`](../../api/audit_verify.py) | 2 | Already has 4 BaseModels — verify they cover both endpoints. |
| [`api/batch.py`](../../api/batch.py) | 5 | All async-emitting → `JobResponse`. |
| [`api/agents.py`](../../api/agents.py) | 5 | Already returns `dict[str, object]` — closer to typed but needs concrete models. |
| [`api/agent_bindings.py`](../../api/agent_bindings.py) | 4 | Same. |
| [`api/intake.py`](../../api/intake.py) | 3 | Already has request models. |

### 3.3 Day 3 (afternoon) — Tier P2 (~25 endpoints across 10 files)

| File | Endpoints | Notes |
|---|---|---|
| [`api/analytics.py`](../../api/analytics.py) | 3 | CISO Console only. Type-light is fine. |
| [`api/connectors.py`](../../api/connectors.py) | 4 | Stub responses; minimal types. |
| [`api/domains_api.py`](../../api/domains_api.py) | 5 | Config CRUD. |
| [`api/evidence.py`](../../api/evidence.py) | 4 | CISO Console drill-down. |
| [`api/framework.py`](../../api/framework.py) | 3 | Single framework lookups. |
| [`api/memory.py`](../../api/memory.py) | 5 | Already has 13 BaseModels — verify coverage. |
| [`api/usage.py`](../../api/usage.py) | 3 | Read-only. |
| [`api/security.py`](../../api/security.py) | ~7 | Guardrail check endpoints. Some `dict` to type. |
| [`api/reports.py`](../../api/reports.py) | 3 | PDF download endpoints — `include_in_schema=False` for the actual download; type the catalog endpoint. |
| [`api/guide.py`](../../api/guide.py) | 8 | Static content lookup; type-light is fine. |

### 3.4 Day 3 (late) — Tier P3 (~20 endpoints across 11 files) — minimal typing

These are demo orchestration, mock-data, or internal routers. Apply minimum: `OkResponse`
where mutations return `{ok: true}`, `CursorPage[dict]` where lists are demo-only, declare
nothing rich. Schemathesis still runs against them; conventions still apply.

| File | Endpoints | Treatment |
|---|---|---|
| `api/demo.py`, `api/demo_run.py`, `api/demo_control.py`, `api/aws_demo.py` | ~25 (mostly private `_step_*`) | Only the route handlers, not helpers. Most return `OkResponse` or `dict[str, Any]` typed loosely. |
| `api/agent_notifications.py` | 1 SSE endpoint | `include_in_schema=False`. Document separately as AsyncAPI (deferred to Phase 2). |
| `api/agent_bindings.py` private helpers, `api/projection.py`, `api/metrics.py`, `api/demo_control.py` | mixed | Apply `OkResponse` or skip. |
| `api/evaluate.py`, `api/traces.py`, `api/assessment.py` | mixed | Already partial coverage. |

### 3.5 Endpoints excluded from `/openapi.json` and Schemathesis

| Endpoint | Reason |
|---|---|
| `/api/health` (assumed) | Health probe; not a contract |
| `/api/metrics/*` | Prometheus scrape; not a JSON contract |
| `GET /api/agents/{id}/listen` | SSE stream; not a JSON response |
| All `/api/reports/.../download` PDF endpoints | Binary stream |
| `/static/*`, `/`, `/login` | UI routes, not API |

Mark with `include_in_schema=False` on the route decorator.

---

## 4. `operationId` table (all ~100 endpoints)

This is the table Day 2 follows mechanically. Each row generates exactly one
`@router.<verb>("...", operation_id="...", response_model=...)` decoration.

(Generated by enumerating §3 against the routers; abbreviated here — full table maintained
inline in each router file as code, this section is the cross-reference.)

| operationId | Method | Path | Response model |
|---|---|---|---|
| `grc_kpis` | GET | /api/grc/kpis | `KpisOut` |
| `grc_next_actions` | GET | /api/grc/next-actions | `NextActionsOut` |
| `grc_homepage_runtime_events` | GET | /api/grc/homepage/runtime-events | `HomepageEventsOut` |
| `grc_homepage_critical_findings` | GET | /api/grc/homepage/critical-findings | `HomepageFindingsOut` |
| `grc_homepage_threat_series` | GET | /api/grc/homepage/threat-series | `ThreatSeriesOut` |
| `notifications_list` | GET | /api/grc/notifications | `NotificationsOut` |
| `notifications_resolve` | POST | /api/grc/notifications/{id}/resolve | `OkResponse` |
| `notifications_reset` | POST | /api/grc/notifications/reset | `OkResponse` |
| `ai_systems_list` | GET | /api/grc/ai-systems | `CursorPage[AiSystemSummaryOut]` |
| `ai_systems_get` | GET | /api/grc/ai-systems/{system_id} | `AiSystemDetailOut` |
| `findings_list` | GET | /api/grc/findings | `CursorPage[FindingSummaryOut]` |
| `findings_get` | GET | /api/grc/findings/{finding_id} | `FindingDetailOut` |
| `release_gate_rules_list` | GET | /api/grc/release-gates/rules | `GateRulesOut` |
| `release_gate_results_list` | GET | /api/grc/release-gates/results | `GateResultsOut` |
| `release_gate_result_get` | GET | /api/grc/release-gates/{system_id} | `GateResultOut` |
| `nist_rmf_get` | GET | /api/grc/governance/nist-ai-rmf | `NistRmfOut` |
| `nist_ai_600_1_get` | GET | /api/grc/governance/ai-600-1 | `AI600_1Out` |
| `owasp_llm_get` | GET | /api/grc/security/owasp-llm | `OwaspListOut` |
| `owasp_agentic_get` | GET | /api/grc/security/owasp-agentic | `OwaspListOut` |
| `runtime_events_list` | GET | /api/grc/runtime/events | `RuntimeEventsOut` |
| `policies_list` | GET | /api/grc/policies | `PoliciesOut` |
| `policies_get` | GET | /api/grc/policies/{policy_id} | `PolicyDetailOut` |
| `evidence_list` | GET | /api/grc/evidence | `CursorPage[EvidenceSummaryOut]` |
| `runtime_v2_events` | GET | /api/grc/runtime/v2/events | `RuntimeV2EventsOut` |
| `runtime_v2_connectors` | GET | /api/grc/runtime/v2/connectors | `ConnectorsOut` |
| `runtime_v2_state_get` | GET | /api/grc/runtime/v2/state/{ai_system_id} | `RuntimeStateOut` |
| `runtime_v2_state_list` | GET | /api/grc/runtime/v2/state | `RuntimeStatesOut` |
| `runtime_v2_enabled_set` | POST | /api/grc/runtime/v2/state/{id}/enabled | `RuntimeStateOut` |
| `runtime_v2_kill_switch` | POST | /api/grc/runtime/v2/state/{id}/kill-switch | `RuntimeStateOut` |
| `runtime_v2_reset_kill_switch` | POST | /api/grc/runtime/v2/state/{id}/reset-kill-switch | `RuntimeStateOut` |
| `runtime_v2_monitoring_set` | POST | /api/grc/runtime/v2/state/{id}/monitoring | `RuntimeStateOut` |
| `runtime_v2_approvals_list` | GET | /api/grc/runtime/v2/approvals | `ApprovalsOut` |
| `runtime_v2_approval_create` | POST | /api/grc/runtime/v2/approvals | `ApprovalOut` |
| `runtime_v2_approval_resolve` | POST | /api/grc/runtime/v2/approvals/{id}/resolve | `ApprovalOut` |
| `runtime_v2_incidents_list` | GET | /api/grc/runtime/v2/incidents | `IncidentsOut` |
| `runtime_v2_incident_create` | POST | /api/grc/runtime/v2/incidents | `IncidentOut` |
| `runtime_v2_incident_update` | POST | /api/grc/runtime/v2/incidents/{id}/update | `IncidentOut` |
| `runtime_v2_meta` | GET | /api/grc/runtime/v2/_meta | `RuntimeMetaOut` |
| `frameworks_matrix` | GET | /api/frameworks/matrix | `MatrixOut` (exists ✓) |
| `frameworks_overview` | GET | /api/frameworks/{slug} | `FrameworkOverviewOut` (exists ✓) |
| `frameworks_system_drill` | GET | /api/frameworks/{slug}/system/{id} | `DrillDownOut` (exists ✓) |
| `frameworks_export` | POST | /api/frameworks/{slug}/export | (PDF binary; `include_in_schema=False`) |
| _(... remaining ~60 endpoints follow same pattern; updated inline in each router on Day 2-3)_ | | | |

**Day 2 deliverable per router PR:** the relevant slice of this table copied into the PR
description as a checklist, ticked off as each route's `operation_id=` and `response_model=`
are wired.

---

## 5. Schemathesis configuration

### 5.1 CI target — local uvicorn (locked)

GitHub Actions workflow `.github/workflows/contract-tests.yml`:

```yaml
name: contract-tests
on: [pull_request, push]

jobs:
  schemathesis:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - run: pip install -r requirements.txt -r requirements-dev.txt
      - name: Start engine locally
        env:
          EVAL_BACKEND: noop
          SCRUBBER_BACKEND: regex
          TRACER_BACKEND: noop
          MEMORY_BACKEND: noop
          RAG_BACKEND: noop
          POLICY_BACKEND: noop
        run: |
          uvicorn dashboard:app --host 127.0.0.1 --port 9007 &
          sleep 5
          curl -f http://127.0.0.1:9007/api/health
      - name: Schemathesis
        run: |
          schemathesis run http://127.0.0.1:9007/openapi.json \
            --checks all \
            --hypothesis-max-examples 50 \
            --workers 4 \
            --hooks ci/schemathesis_hooks.py
      - name: Diff OpenAPI artifact
        run: |
          python scripts/export_openapi.py > /tmp/openapi-new.json
          diff docs/openapi-v1.json /tmp/openapi-new.json || \
            (echo "::error::OpenAPI changed but artifact not regenerated. Run scripts/export_openapi.py and commit."; exit 1)
```

**Why all backends `noop`/`regex`:** no external dependencies (no Langfuse, no Postgres,
no Azure Search) means CI runs in <2 minutes and costs nothing. Tests pure contract
shape, not external integration.

### 5.2 Custom Schemathesis hooks — `ci/schemathesis_hooks.py`

```python
"""Custom Schemathesis hooks enforcing CLAUDE.md security rules at the API contract level.

Locked by docs/plans/SESSION-13-api-typing-audit.md §1.9 + §5.2.
"""
from __future__ import annotations

import re

import schemathesis

_SECRET_RE = re.compile(r"sk-(ant|proj|[a-zA-Z]+)-[A-Za-z0-9]{20,}")
_FORBIDDEN_KEYS = {"raw_prompt", "unscrubbed_prompt", "pii_entities"}


@schemathesis.check
def no_secret_in_response(response, case):
    """Response body must never contain a secret-shaped string."""
    body = response.text or ""
    if _SECRET_RE.search(body):
        raise AssertionError(
            f"Response from {case.operation.path} contains a secret-shaped token."
        )


@schemathesis.check
def no_raw_prompt_field(response, case):
    """Response body must never contain a forbidden field name."""
    try:
        body = response.json()
    except ValueError:
        return
    def walk(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in _FORBIDDEN_KEYS:
                    raise AssertionError(
                        f"Response from {case.operation.path} contains forbidden field '{k}'"
                    )
                walk(v)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)
    walk(body)


@schemathesis.check
def llm_response_has_trace_id(response, case):
    """Endpoints that trigger LLM calls must include trace_id in governance metadata."""
    # Tagged paths from §1.6 above.
    llm_paths = {
        "/api/assurance/ask",
        "/api/assurance/summarize-finding",
        "/api/assurance/summarize-evidence",
        "/api/assurance/explain-release",
        "/api/assurance/draft-report",
        "/api/batch/run",
        "/api/demo/run",
    }
    if case.operation.path not in llm_paths:
        return
    if response.status_code != 200:
        return
    body = response.json()
    governance = body.get("governance") if isinstance(body, dict) else None
    if not governance or not governance.get("trace_id"):
        raise AssertionError(
            f"LLM-triggering endpoint {case.operation.path} missing governance.trace_id"
        )
```

### 5.3 Schemathesis exclusions

```yaml
# schemathesis.yaml (project root)
endpoints:
  exclude:
    - /api/health
    - /api/metrics
    - /api/metrics/.*
    - /api/agents/.*/listen      # SSE stream
    - /api/reports/.*/download   # binary PDF
    - /static/.*
    - /login
    - /
```

---

## 6. OpenAPI export pre-commit hook

### 6.1 Script — `scripts/export_openapi.py`

```python
"""Export FastAPI's OpenAPI schema to docs/openapi-v1.json.

Run automatically via pre-commit hook (see .pre-commit-config.yaml).
Committing the artifact means API changes are visible in PR review diffs.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure noop backends so import doesn't hit Langfuse/Postgres
import os
os.environ.setdefault("EVAL_BACKEND", "noop")
os.environ.setdefault("SCRUBBER_BACKEND", "regex")
os.environ.setdefault("TRACER_BACKEND", "noop")
os.environ.setdefault("MEMORY_BACKEND", "noop")
os.environ.setdefault("RAG_BACKEND", "noop")
os.environ.setdefault("POLICY_BACKEND", "noop")

from dashboard import app

spec = app.openapi()
out_path = Path(__file__).parent.parent / "docs" / "openapi-v1.json"
out_path.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n")
print(f"Wrote {out_path} ({len(json.dumps(spec))} bytes)")
```

### 6.2 Pre-commit config — `.pre-commit-config.yaml`

```yaml
repos:
  - repo: local
    hooks:
      - id: export-openapi
        name: Export OpenAPI artifact
        entry: python scripts/export_openapi.py
        language: system
        pass_filenames: false
        files: ^(api/|dashboard\.py|providers/)
        stages: [commit]
```

### 6.3 `__version__` source

Create `__version__.py` at repo root:

```python
__version__ = "2.0.0-phase1"
```

`dashboard.py` change (Day 5):
```python
from __version__ import __version__
app = FastAPI(
    title="AI Assurance Platform",
    version=__version__,
    servers=[{"url": "https://api.aigovern.sandboxhub.co", "description": "Production"}],
)
```

Bump rule: any change to a response_model in a P0/P1 router → minor version bump. Any
removed or renamed field → major version bump. Adding a new optional field → patch bump.

---

## 7. Execution sequence (Days 2-5)

This replaces the table in SESSION-13 §5 for Track A with a more concrete plan.

| Day | Track A morning | Track A afternoon | Track B parallel |
|---|---|---|---|
| **2** | Create `api/_models.py` + `api/_errors.py` + `__version__.py`. Wire global exception handlers in `dashboard.py`. Smoke. | Type `api/grc.py` (20 endpoints). Smoke after every 5 endpoints. Commit per logical group. | B2 — ARCHITECTURE.md Sessions 11/12/12B entries |
| **3** | Type `api/runtime_v2.py` (14) + `api/findings_v2.py` (5) + `api/release_gates.py` (4) + `api/evals_v2.py` (3). | Type Tier P1 routers (assurance_model, ai_system_edit, RTF, audit_verify, batch, agents, agent_bindings, intake). | B1 — `tests/test_deploy_completeness.py` |
| **4** | Type Tier P2 routers. Add Schemathesis hooks. | Write `scripts/export_openapi.py`. Generate first `docs/openapi-v1.json`. PR review of diff with Praveen. | B3 — SESSION-12B §6 update |
| **5** | Add `middleware/api_version_alias.py`. Wire `/api/v1/*` alias. Engine custom domain CNAME (A4). | Run full Schemathesis pass locally + verify CI green. Tag `v2-phase-1-complete`. | B6 — GitHub Actions deploy workflow draft (no deploy) |

**Smoke checkpoint after every router commit:**
```powershell
$env:SMOKE_TARGET_URL = "http://localhost:9007"   # local during Day 2-4
pwsh deploy/smoke_e2e.ps1
```

A failed smoke = revert the last commit and re-type that router more carefully. Never push
forward through a red smoke.

---

## 8. Risks (extends SESSION-13 §6)

| Risk | Likelihood | Mitigation |
|---|---|---|
| Hidden V1 HTML page consumers depend on undocumented response field | **High** | Smoke runs full UI flow after every router change. `extra='forbid'` only on **response models**, not request — so V1 forms with extra fields still work. |
| `extra='forbid'` rejects fields V1 pages currently send in POST bodies | Medium | Apply `extra='forbid'` only to response models; request models stay `extra='ignore'` (default). Document this asymmetry. |
| Schemathesis fuzzing hits rate-limit / breaker logic and false-positives | Medium | Limit `--hypothesis-max-examples 50` (low). All backends noop in CI = no rate limiters active. |
| `JobResponse` introduction changes the response shape for `batch.py` consumers (V1 batch.html) | Medium | Audit `static/*.html` use of `/api/batch/*` first. If it parses old shape, add a transitional `legacy_payload: dict` field on `JobResponse` for one release. |
| `governance.trace_id` requires plumbing through every LLM-path handler — touches more files than just `api/*.py` | High | Track separately. Initial typing pass sets `governance: None`; populating fields is a follow-up Phase 1.5. Marked TODO in each affected handler. |
| Pre-commit hook regenerates artifact and adds it to staged files mid-commit | Medium | Hook runs at commit stage; if artifact changes, commit fails with message "run script + git add docs/openapi-v1.json + retry". Don't auto-add (per CLAUDE.md "never auto-commit"). |
| `/api/v1/*` middleware breaks something subtle (request.url vs request.scope mismatch) | Medium | Add a test: hit `/api/v1/grc/kpis` and `/api/grc/kpis`, assert identical responses. Goes in `tests/test_api_version_alias.py`. |
| `info.version` change cadence undefined → bumped on every PR or never | Medium | Bump rule above in §6.3. Enforce via PR template checkbox: "Did you bump `__version__.py`?" |

---

## 9. Out of scope for Day 1 (deferred to dedicated session/phase)

- **Populating `governance` field values** in handlers. Day 1-5 declares the model; plumbing
  the data through `tracer.py` / `policy_gate` / `evaluator.py` to the handler return path
  is Phase 1.5 (one extra session). Initial typing pass sets `governance: None` everywhere.
- **AsyncAPI spec for SSE endpoints.** Deferred to V2 Phase 2 (Workspace SPA scaffold).
- **SDK regen from new OpenAPI.** SDK is hand-rolled today (Session 09). Regen via
  `openapi-python-client` is Phase 1.5 once spec is stable.
- **Removal of `_ser()` from `runtime_v2.py`.** Happens incidentally during the typing pass;
  not a standalone goal.
- **Multi-tenant `tenant_id`/`org_id` fields.** Reserved field names per §1.3; not added.

---

## 10. Open questions (answer before Day 2 starts)

1. **`__version__` initial value.** Proposed `"2.0.0-phase1"` per §6.3. Alternative: `"1.12.0"`
   continuing V1 numbering until Phase 5 cutover, then jump to 2.0.0. Recommend the former
   so the spec advertises "this is V2-track" from Day 2.

2. **Where does `dashboard.py` validate the OpenAPI artifact?** Two options: (a) startup check
   that compares generated spec to committed artifact, fails fast if drift; (b) CI-only check
   per §5.1. Option (b) is cheaper; option (a) catches local-dev drift faster. Recommend (b).

3. **CISO Console `ConflictDetail` vocabulary lock.** §1.2 lists 4 `conflict_type` values
   (`GATE_DENIED`, `POLICY_DENIED`, `IDEMPOTENCY`, `STATE_TRANSITION`). Is this the complete
   list, or are there governance-specific conflicts I'm missing? Most likely complete; flag
   if not.

4. **`OkResponse` vs returning the mutated resource.** Some POST endpoints currently return
   `{"ok": True, **resource}`. The audit treats those as "return resource" (typed model),
   not `OkResponse`. Confirm: do you want explicit `OkResponse` for fire-and-forget mutations
   (e.g. `notifications/reset`), and full resource echo for state-changing mutations (e.g.
   `notifications/{id}/resolve`)? Recommend yes.

5. **Schemathesis run frequency.** Every PR (locked) — also on a nightly cron against the
   deployed engine? Recommend deferring nightly to Phase 1.5 to keep CI free during Phase 1.

---

## 11. Acceptance for Day 1

This doc is "done for Day 1" when:

- [x] Conventions §1 cover envelope, errors, IDs, pagination, URL versioning, governance
      field, Pydantic config, operationId naming, sensitive-field rules
- [x] §2 has copy-paste-ready cross-cutting models
- [x] §3 enumerates every router with priority tier
- [x] §4 starts the operationId table (full table maintained in code on Day 2-3)
- [x] §5 has CI workflow + custom checks
- [x] §6 has export script + pre-commit hook + version source
- [x] §7 has day-by-day execution plan
- [x] §8 enumerates the risks the audit itself introduces
- [x] §10 lists open questions for sign-off

**Sign-off required before Day 2:** Praveen on §10 (5 questions).

---

## 12. Sign-off

| Reviewer | Date | Status |
|---|---|---|
| Praveen (architect) | _pending_ | _pending_ |
