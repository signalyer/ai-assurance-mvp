# AI Eval Harness — Implementation Plan
# Tier 1 + Tier 2, Single-Tenant v1

**Companion to:** `docs/ai-eval-harness-tier1-tier2-plan.md` (feature specs)
**This document:** Translates feature specs into a concrete repo layout, file-level deliverables, week-by-week tasks, and milestone gates.

**Deployment model:** **Single tenant for v1.** One deployment at `evals.sandboxhub.co`. Data, results, findings, and evidence are piped back to the assurance platform at `aigovern.sandboxhub.co` over an HMAC-signed HTTPS contract.

**Multi-tenant:** Deferred to v2 after this build is verified end-to-end. The data model is intentionally built so multi-tenant becomes "add an `org_id` column + filter" later, not a rewrite.

**Pricing:** Not in scope for this build.
**Infra:** Medium — single App Service + single Postgres. Scale up only when load demands it.

**Repo target:** `signallayer/eval-harness` (new repo, separate from assurance platform)
**Date:** 2026-05-20

---

## 0. Architecture Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Tenancy | **Single tenant for v1.** No `org_id` on tables. Build code paths so adding `org_id` later is a column + filter, not a rewrite. | Get to verification fastest. Multi-tenant happens in v2 after design partner validates. |
| Hosting | **`evals.sandboxhub.co`** on Azure App Service Linux Python 3.12. Same subscription as `aigovern.sandboxhub.co`. | Reuses existing certs, DNS, auth patterns. Operationally identical to the assurance platform. |
| Data pipe-back | **HMAC-signed POSTs from harness → `aigovern.sandboxhub.co/api/ingest/*`.** Every eval run, finding, evidence bundle, and policy decision is replicated to the assurance platform. The harness is the system-of-record for eval data; the platform is the system-of-record for governance state. | The assurance platform is where Risk + CISO + audit views live. Harness data must show up there or the workflow is broken. |
| Token map location | **Azure Blob Storage in the same subscription.** Encrypted with a key in Key Vault. We control it for v1; in v2 / production sales, switch to customer-managed. | Speed for v1. The contract (SAS URL pointer) is the same shape — swap location later without SDK change. |
| F2 PR comments | **Slack webhook only for v1.** GitHub PR comments and email deferred. | Smallest surface that demonstrates value. |
| F4 reviewers | **Local users on this deployment.** Entra SSO wired but optional; seed admin + invite flow covers v1. | No org / tenant complexity. |
| Infra size | **Medium.** App Service P1V3 Linux (not P2V3), Postgres Flexible B2ms. Scale up after load testing, not before. | Right-size for one-tenant verification. Easy to bump via `az` later. |

### What "Single Tenant v1" Means In Practice

- One App Service at `evals.sandboxhub.co`. One Postgres. One Storage account. One Key Vault.
- No `organizations` table; replaced by a single-row `deployment_config`.
- No `org_id` foreign keys on any table.
- Every DB query is naturally scoped to this deployment.
- Sessions, audit log, RBAC — all single-instance.
- Outbound pipe to `aigovern.sandboxhub.co` is **the integration**; treat it as a first-class subsystem (`harness/domain/platform_sync.py`).

### Forward Compatibility With Multi-Tenant v2

Build now so v2 is mechanical:

- All DB models inherit from a `TenantScoped` base mixin that today has no fields but in v2 adds `org_id`.
- All API handlers receive a `tenant_id` value via dependency injection. Today it returns the singleton `DEPLOYMENT_TENANT_ID`. In v2 it returns the authenticated user's org.
- All domain functions accept `tenant_id` as a parameter even if v1 ignores it.
- HMAC scheme already supports a `tenant_id` claim in the signed payload (set to constant for v1).

**Cost of forward compat: ~1 day of plumbing now. Cost of skipping it: 2 weeks of refactor in v2.** Do it.

---

## 1. Repo Layout

```
signallayer-eval-harness/
│
├── harness/                        # FastAPI web app (the SaaS backend + UI)
│   ├── main.py                     # App factory, startup, shutdown
│   ├── settings.py                 # Pydantic Settings v2 (env vars, validated at start)
│   │
│   ├── api/                        # Route handlers (thin — call domain, return response)
│   │   ├── auth.py                 # /api/auth/login, /callback, /logout
│   │   ├── ingest.py               # POST /api/ingest/trace, /eval-run, /finding
│   │   ├── runs.py                 # GET/POST /api/runs, /api/runs/{id}/compare
│   │   ├── failures.py             # GET /api/failures, /api/failures/{id}
│   │   ├── review.py               # GET/POST /api/review/queue, /api/review/{id}/submit
│   │   ├── calibration.py          # GET/POST /api/calibration
│   │   ├── datasets.py             # GET/POST /api/datasets, versioning endpoints
│   │   ├── policies.py             # GET/POST /api/policies, /api/policies/{id}/evaluate
│   │   ├── evidence.py             # POST /api/evidence/export
│   │   ├── costs.py                # GET /api/costs/summary, /api/costs/agents
│   │   └── audit.py                # GET /api/audit-log
│   │
│   ├── domain/                     # Business logic (no FastAPI imports)
│   │   ├── ingestion.py            # HMAC verification, idempotency, trace normalization
│   │   ├── redaction.py            # PII scrubber (regex + spaCy wrapper)
│   │   ├── regression.py           # Delta computation, bootstrap significance, alert dispatch
│   │   ├── comparison.py           # Two-run diff, failure clustering
│   │   ├── review_queue.py         # Routing rules, assignment, kappa/alpha math
│   │   ├── calibration.py          # Calibration set management, drift detection
│   │   ├── dataset_versions.py     # Semver, diff, drift clustering via embeddings
│   │   ├── policy_engine.py        # YAML parser, expression evaluator, gate check
│   │   ├── evidence_builder.py     # Bundle assembly, SHA-256 hash, WeasyPrint render
│   │   ├── cost_engine.py          # Price table, aggregations, anomaly detection
│   │   └── alerts.py               # Slack webhook, email, PR comment dispatcher
│   │
│   ├── db/                         # Database layer
│   │   ├── models.py               # SQLAlchemy 2.0 mapped classes (14 tables)
│   │   ├── session.py              # Async engine, session factory
│   │   ├── migrations/             # Alembic migration files
│   │   │   ├── env.py
│   │   │   └── versions/
│   │   │       ├── 001_initial_schema.py
│   │   │       ├── 002_add_calibration.py
│   │   │       └── ...
│   │   └── seed.py                 # Seed org + admin user for local dev
│   │
│   ├── middleware/
│   │   ├── auth.py                 # Session validation, Entra OIDC token verification
│   │   └── rbac.py                 # Role → permission matrix, require_role() decorator
│   │
│   ├── templates/                  # Jinja2 HTML templates
│   │   ├── base.html               # Layout, nav, shared.js inclusion
│   │   ├── login.html
│   │   ├── dashboard.html          # Command center (KPIs + recent runs)
│   │   ├── runs.html               # Run list + status
│   │   ├── run_detail.html         # Single run: metrics, failures, download
│   │   ├── comparison.html         # Side-by-side diff
│   │   ├── failures.html           # Failure browser
│   │   ├── review_queue.html       # Reviewer workspace
│   │   ├── calibration.html        # Calibration set manager
│   │   ├── datasets.html           # Dataset browser + version history
│   │   ├── policies.html           # Policy editor + gate status
│   │   ├── costs.html              # Cost + latency dashboard
│   │   └── audit.html              # Audit log viewer
│   │
│   └── static/
│       ├── harness.css             # Design tokens + component styles
│       └── harness.js              # Shared UI logic (nav, drawer, modals)
│
├── sdk/                            # pip-installable package
│   ├── pyproject.toml              # Package metadata, deps
│   └── signallayer_eval/
│       ├── __init__.py             # Public API: trace_call, EvalRun, @trace
│       ├── client.py               # HTTP client to harness /api/ingest/*
│       ├── redact.py               # PII redaction (regex + optional spaCy)
│       ├── token_map.py            # Reversible token map, Azure Storage writer
│       ├── run.py                  # EvalRun context manager
│       └── config.py               # SDK config (HARNESS_URL, HMAC_KEY, TOKEN_MAP_URL)
│
├── cli/                            # signallayer-eval CLI
│   ├── pyproject.toml
│   └── signallayer_eval_cli/
│       ├── __init__.py
│       ├── main.py                 # Click entrypoint
│       ├── cmd_gate.py             # `gate check --run-id X` → exit 0/1
│       ├── cmd_run.py              # `run trigger --dataset X --agent Y`
│       └── cmd_export.py           # `export evidence --run-id X`
│
├── ci-templates/                   # Ready-to-use CI snippets
│   ├── github-action.yml           # .github/workflows/eval-gate.yml
│   └── azure-devops-pipeline.yml   # azure-pipelines.yml snippet
│
├── deploy/
│   ├── provision.ps1               # Postgres (Azure Database for PostgreSQL Flexible), App Service
│   ├── build-zip.py                # Deploy package builder (port from platform)
│   └── smoke.ps1                   # Post-deploy smoke test
│
├── tests/
│   ├── unit/                       # Domain logic tests (no DB, no HTTP)
│   │   ├── test_redaction.py
│   │   ├── test_regression.py
│   │   ├── test_kappa.py
│   │   ├── test_policy_engine.py
│   │   └── test_cost_engine.py
│   └── integration/                # Tests against real Postgres (Docker)
│       ├── test_ingest.py
│       ├── test_run_lifecycle.py
│       └── test_evidence_export.py
│
├── docs/                           # Planning docs (already exist in platform repo)
├── CLAUDE.md                       # Project-level Claude Code instructions
├── pyproject.toml                  # Root project (harness app deps)
└── .env.example                    # All required env vars documented
```

---

## 2. Tech Stack (Locked)

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.12 | Matches platform, Azure App Service support |
| Web framework | FastAPI 0.115+ | Async, Pydantic v2 native, matches platform patterns |
| Templates | Jinja2 | Server-rendered HTML (no build step) |
| ORM | SQLAlchemy 2.0 (async) | Type-safe, async-native, Alembic migrations |
| Database | Postgres 16 (Azure Database for PostgreSQL Flexible) | JSONB + row-level security + PG-native search |
| Migrations | Alembic | One-way migrations only; no down() except in dev |
| Auth | msal (Microsoft Authentication Library) | Entra OIDC — well-trodden |
| Sessions | itsdangerous URLSafeTimedSerializer | Port from platform |
| PDF | WeasyPrint | HTML → PDF; strict templates |
| HTTP client (SDK) | httpx async | Matches harness patterns |
| NLP (redaction) | spaCy en_core_web_sm | Small model for SDK; no GPU dep |
| Stats | scipy + numpy | Bootstrap resampling for regression |
| Config | pydantic-settings v2 | Fail-loud missing vars |
| Dep management | uv | Fast; lock file |
| Hosting | Azure App Service Linux Python 3.12 P2V3 | Same as platform |
| CI | GitHub Actions | Already where the code lives |

**Not in stack for Tier 1/2:** ClickHouse, Kafka, OTel collector, Redis, React, Next.js, Docker, Kubernetes.

---

## 3. Environment Variables

Every var must be present or the app refuses to start.

```bash
# Database
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/evalharness

# Auth
ENTRA_TENANT_ID=...
ENTRA_CLIENT_ID=...
ENTRA_CLIENT_SECRET=...
SESSION_SECRET=<32-char random string>

# Ingestion security
HMAC_SECRET=<32-char random string>          # shared with SDK
INGEST_NONCE_TTL_SECONDS=300                 # replay protection window

# Alerts
SLACK_WEBHOOK_URL=...                         # optional; skip alerts if absent
GITHUB_WEBHOOK_TOKEN=...                      # optional

# Eval / model-as-judge
ANTHROPIC_API_KEY=...                         # for F2 model-as-judge scorer
OPENAI_API_KEY=...                            # optional; second scorer

# Email (fallback alerts)
SMTP_HOST=...
SMTP_PORT=587
SMTP_USER=...
SMTP_PASS=...
```

---

## 4. Data Model (SQL DDL)

Concrete SQL — not pseudocode. Alembic generates `001_initial_schema.py` from this.

```sql
-- Single-tenant: NO org_id on any table. The deployment IS the boundary.
-- Deployment-level config (customer name, Entra tenant, plan) lives in a single
-- deployment_config row, not propagated to every table.

CREATE TABLE deployment_config (
    id              INTEGER PRIMARY KEY CHECK (id = 1),  -- enforce single row
    customer_name   TEXT NOT NULL,
    entra_tenant_id TEXT NOT NULL,
    plan            TEXT NOT NULL DEFAULT 'base',
    deployed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    schema_version  TEXT NOT NULL                        -- for upgrade fan-out tracking
);

CREATE TABLE users (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entra_oid   TEXT UNIQUE,                  -- Entra object ID; null = local admin only
    email       TEXT NOT NULL UNIQUE,
    role        TEXT NOT NULL,                -- admin | engineer | reviewer | risk | readonly
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE projects (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL UNIQUE,
    repo_url    TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE agents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      UUID NOT NULL REFERENCES projects(id),
    name            TEXT NOT NULL,
    model_provider  TEXT NOT NULL,            -- openai | anthropic | bedrock | local
    model_name      TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE prompt_versions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id        UUID NOT NULL REFERENCES agents(id),
    version         TEXT NOT NULL,            -- semver string
    content_hash    TEXT NOT NULL,            -- SHA-256 of prompt content
    content         TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (agent_id, version)
);

CREATE TABLE datasets (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      UUID NOT NULL REFERENCES projects(id),
    name            TEXT NOT NULL,
    version         TEXT NOT NULL,            -- semver
    content         JSONB NOT NULL,           -- array of {id, input, expected_output, tags}
    case_count      INTEGER NOT NULL,
    created_by      UUID REFERENCES users(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_id, name, version)
);

CREATE TABLE eval_runs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id            UUID NOT NULL REFERENCES agents(id),
    prompt_version_id   UUID REFERENCES prompt_versions(id),
    dataset_id          UUID NOT NULL REFERENCES datasets(id),
    commit_sha          TEXT,
    status              TEXT NOT NULL DEFAULT 'queued', -- queued|running|complete|failed
    metrics             JSONB,                -- {hallucination_rate, factuality, latency_p50, ...}
    baseline_run_id     UUID REFERENCES eval_runs(id),  -- for regression comparison
    started_at          TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE eval_results (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id          UUID NOT NULL REFERENCES eval_runs(id),
    test_case_id    TEXT NOT NULL,            -- stable ID from dataset
    input           TEXT,                     -- redacted
    output          TEXT,                     -- redacted
    expected        TEXT,
    score           JSONB,                    -- {factuality: 0.9, hallucination: 0, ...}
    failure_category TEXT,                    -- null = pass
    latency_ms      INTEGER,
    tokens_in       INTEGER,
    tokens_out      INTEGER,
    cost_usd        NUMERIC(10,6)
);

CREATE TABLE traces (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id            UUID NOT NULL REFERENCES agents(id),
    external_id         TEXT UNIQUE,          -- customer's own trace ID (idempotency)
    prompt_redacted     TEXT,
    response_redacted   TEXT,
    tokens_in           INTEGER,
    tokens_out          INTEGER,
    latency_ms          INTEGER,
    cost_usd            NUMERIC(10,6),
    metadata            JSONB,
    captured_at         TIMESTAMPTZ NOT NULL
);

CREATE TABLE failures (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_type TEXT NOT NULL,               -- eval_result | trace
    source_id   UUID NOT NULL,
    severity    TEXT NOT NULL,               -- critical | high | medium | low
    category    TEXT NOT NULL,               -- hallucination | pii_leak | refusal | format | off_topic
    status      TEXT NOT NULL DEFAULT 'open', -- open | in_review | resolved | risk_accepted
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE review_assignments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    failure_id      UUID NOT NULL REFERENCES failures(id),
    reviewer_id     UUID NOT NULL REFERENCES users(id),
    status          TEXT NOT NULL DEFAULT 'pending', -- pending | submitted | skipped
    label           TEXT,                    -- pass | fail | unclear
    rationale       TEXT,
    submitted_at    TIMESTAMPTZ
);

CREATE TABLE calibration_scores (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    reviewer_id     UUID NOT NULL REFERENCES users(id),
    dataset_id      UUID NOT NULL REFERENCES datasets(id),  -- the calibration dataset
    agreement_kappa NUMERIC(4,3),
    case_count      INTEGER,
    scored_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE policies (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      UUID NOT NULL REFERENCES projects(id),
    name            TEXT NOT NULL,
    content_yaml    TEXT NOT NULL,
    version         INTEGER NOT NULL DEFAULT 1,
    created_by      UUID REFERENCES users(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE gate_evaluations (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id              UUID NOT NULL REFERENCES eval_runs(id),
    policy_id           UUID NOT NULL REFERENCES policies(id),
    passed              BOOLEAN NOT NULL,
    blocking_failures   JSONB,               -- list of {gate_name, expression, actual_value}
    evaluated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE evidence_bundles (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id          UUID REFERENCES eval_runs(id),
    sha256          TEXT NOT NULL,
    storage_path    TEXT NOT NULL,           -- Azure Blob URL
    generated_by    UUID REFERENCES users(id),
    generated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE audit_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID REFERENCES users(id),
    action          TEXT NOT NULL,           -- evidence.export | policy.edit | run.override | ...
    target_type     TEXT,
    target_id       UUID,
    before_state    JSONB,
    after_state     JSONB,
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indexes (performance-critical paths)
CREATE INDEX idx_eval_runs_agent_dataset ON eval_runs(agent_id, dataset_id, completed_at DESC);
CREATE INDEX idx_eval_results_run ON eval_results(run_id);
CREATE INDEX idx_traces_agent_captured ON traces(agent_id, captured_at DESC);
CREATE INDEX idx_failures_status ON failures(status, severity);
CREATE INDEX idx_review_assignments_reviewer ON review_assignments(reviewer_id, status);
CREATE INDEX idx_audit_log_occurred ON audit_log(occurred_at DESC);
```

**Single-tenant note:** 13 tables (down from 14 — `organizations` collapses to `deployment_config` with a single-row CHECK constraint). Every query is naturally scoped to "this deployment" because the deployment IS the customer.

---

## 5. RBAC Permission Matrix

Enforced at the API layer via `require_role()` middleware. UI hides controls but API enforces.

| Action | Admin | Engineer | Reviewer | Risk | ReadOnly |
|---|:---:|:---:|:---:|:---:|:---:|
| Trigger eval run | ✓ | ✓ | | | |
| View runs + metrics | ✓ | ✓ | ✓ | ✓ | ✓ |
| View traces (redacted) | ✓ | ✓ | ✓ | | |
| Submit review label | ✓ | | ✓ | | |
| Export evidence bundle | ✓ | | | ✓ | |
| Edit / upload policy | ✓ | ✓ | | | |
| Override gate block | ✓ | | | ✓ | |
| Manage users + roles | ✓ | | | | |
| View cost dashboard | ✓ | ✓ | | ✓ | |
| View audit log | ✓ | | | ✓ | |
| Manage datasets | ✓ | ✓ | | | |
| Promote to golden set | ✓ | | ✓ | | |

---

## 6. SDK Contract (What Customers Wire Up)

Minimal interface — must work in 10 minutes or they'll abandon it.

```python
# Installation
# pip install signallayer-eval

# SDK init (once at app startup)
from signallayer_eval import init, trace_call, EvalRun

init(
    harness_url="https://eval.signallayer.ai",
    hmac_key=os.environ["SL_HMAC_KEY"],
    agent_id="agent-billing-001",
    token_map_url="https://mystorageaccount.blob.core.windows.net/token-maps/billing.json.enc"
)

# Option A: decorator (wraps any LLM-calling function)
@trace
def call_model(prompt: str) -> str:
    return openai_client.chat(prompt)

# Option B: manual (when you can't decorate)
result = my_llm_call(prompt)
trace_call(
    prompt=prompt,
    response=result,
    metadata={"transaction_id": txn_id, "model": "gpt-4o"}
)

# Option C: EvalRun context manager (batch eval)
with EvalRun(dataset_version="payments-v1.3.0", commit_sha=git_sha) as run:
    for case in dataset:
        output = call_model(case.input)
        run.record(test_case_id=case.id, output=output)
    # auto-submits on context exit; triggers regression detection
```

**SDK internal flow on `trace_call()`:**
1. Regex redact (SSN, email, phone, CC, AWS ARN)
2. spaCy NER redact (PERSON, ORG, GPE) — lazy-loaded, skipped if model not installed
3. Build reversible token map entry → append to local buffer
4. Every 100 entries OR 10s (whichever first): flush buffer to customer's Azure Storage SAS URL
5. POST redacted trace to `/api/ingest/trace` with HMAC-SHA256 signature
6. If POST fails: write to local fallback queue (`~/.signallayer/failed_traces.jsonl`), retry async

---

## 6a. Pipe-Back to `aigovern.sandboxhub.co`

The harness is **not** an island. Every meaningful event in the harness is replicated to the
assurance platform so Risk + CISO + auditor views show the same truth.

### What flows back

| Event in harness | Endpoint on platform | When |
|---|---|---|
| Eval run completed | `POST /api/ingest/eval-run` | On run.complete |
| Finding created (failure with severity ≥ HIGH) | `POST /api/ingest/finding` | On failure routed for review |
| Evidence bundle generated | `POST /api/ingest/evidence-item` | On bundle build complete |
| Gate evaluation (policy check) | `POST /api/ingest/gate-decision` | On every gate evaluation |
| Reviewer sign-off submitted | `POST /api/ingest/review-signoff` | On review submit |

**Not piped back:** raw traces, redacted prompts/responses, reviewer rationale text. Those stay in the harness DB. Only the **governance-relevant facts** (run summaries, control mapping, decisions, hashes) cross the wire. Two reasons: keeps the platform DB small, and reduces the blast radius if anything in the pipe leaks.

### Wire format

Same HMAC scheme as inbound ingestion, opposite direction. The harness signs; the platform verifies.

```http
POST https://aigovern.sandboxhub.co/api/ingest/eval-run
Authorization: SL-HMAC-SHA256 timestamp=<unix>, nonce=<uuid>, sig=<hex>
X-Source: evals.sandboxhub.co
Content-Type: application/json

{
  "event_id": "evt-uuid",              // idempotency key on platform side
  "tenant_id": "default",              // constant in v1; real org_id in v2
  "occurred_at": "2026-05-20T14:00Z",
  "agent_id": "agent-billing-001",
  "ai_system_id": "ai-sys-001",        // foreign key into platform's AI System registry
  "run_id": "run-uuid",
  "dataset_version": "payments-v1.3.0",
  "prompt_version": "v4",
  "commit_sha": "abc123",
  "metrics": {
    "hallucination_rate": 0.018,
    "factuality": 0.91,
    "pii_leak_count": 0,
    "latency_p50_ms": 1240
  },
  "regression_summary": {
    "vs_baseline_run": "run-uuid-baseline",
    "deltas": { "hallucination_rate": -0.004, "factuality": +0.012 },
    "alerted": false
  },
  "harness_url": "https://evals.sandboxhub.co/runs/run-uuid"  // deep link for platform UI
}
```

### Platform-side ingestion endpoints (must be built on the assurance platform)

These don't exist yet. They are a deliverable of this build:

- `POST /api/ingest/eval-run` → write to `data/platform_eval_runs.jsonl`, link to AI System
- `POST /api/ingest/finding` → write to `data/platform_findings.jsonl`, link to AI System
- `POST /api/ingest/evidence-item` → add to that AI System's evidence list with `source=eval-harness`
- `POST /api/ingest/gate-decision` → update release gate state on the AI System
- `POST /api/ingest/review-signoff` → append to revision approvals if linked to a revision

All endpoints:
- Validate HMAC + check `X-Source` header
- Idempotent on `event_id` (replay-safe)
- Look up `ai_system_id` and reject if not found
- Append-only to JSONL (matches platform's existing storage pattern)

### Failure handling

If the platform is unreachable:
- Harness retries with exponential backoff (1s, 4s, 16s, 60s)
- After 4 failures: write to local outbox table (`platform_sync_outbox`) and surface a banner in harness UI
- Background drain job retries outbox every 5 minutes
- Outbox depth alert at 100 events → page on-call

**Never block the user-facing flow on the pipe-back.** Always succeed locally first, then sync.

### Reverse direction: harness pulls from platform

The harness needs three things from the platform; it pulls, never the other way:

| What | Endpoint on platform | When |
|---|---|---|
| AI System registry | `GET /api/ai-systems` | On harness startup + every 15 min |
| Workload definitions | `GET /api/ai-systems/{id}` | When eval run starts (fresh fetch, never cache) |
| Approved policies / controls | `GET /api/ai-systems/{id}/controls` | When policy YAML references a platform control |

The harness uses a service account (Entra app registration on the platform tenant) with read-only role.

---

## 6b. Platform-Side Build (`aigovern.sandboxhub.co`)

This is the work that lands in the **existing assurance platform repo**, not the harness repo.
Must be done first — the harness has nothing to talk to until these endpoints exist.

### File-level deliverables

```
ai-assurance-mvp/
├── domain/
│   └── platform_ingest.py        # NEW — HMAC verification, idempotency, JSONL append
├── api/
│   └── platform_ingest.py        # NEW — 5 ingestion endpoints
├── data/
│   ├── platform_eval_runs.jsonl  # NEW — append-only
│   ├── platform_findings.jsonl   # NEW — append-only
│   ├── platform_gate_decisions.jsonl  # NEW — append-only
│   ├── platform_review_signoffs.jsonl # NEW — append-only
│   └── platform_ingest_nonces.jsonl   # NEW — replay protection (TTL-pruned)
├── static/
│   └── ai-systems.html            # MODIFIED — add "Eval Harness" tab
└── dashboard.py                   # MODIFIED — mount platform_ingest_router
```

### Auth model

- All five endpoints require `Authorization: SL-HMAC-SHA256 timestamp=..., nonce=..., sig=...`
- `X-Source: evals.sandboxhub.co` header required (defense in depth — not auth)
- Shared secret stored in env var `HARNESS_INGEST_HMAC_SECRET` on the platform
- Nonce TTL: 300 seconds; replays beyond TTL rejected as expired, within TTL rejected as duplicate
- `event_id` provides idempotency at the application layer (separate from nonce replay protection at the transport layer)

### Endpoint 1 — Eval Run Ingest

```
POST /api/ingest/eval-run
```

**Request body:**
```json
{
  "event_id": "evt-7f3a2c1e-...",
  "tenant_id": "default",
  "occurred_at": "2026-05-20T14:00:00Z",
  "ai_system_id": "ai-sys-001",
  "agent_id": "agent-billing-001",
  "run_id": "run-uuid",
  "dataset_name": "payments-golden",
  "dataset_version": "1.3.0",
  "prompt_version": "v4",
  "commit_sha": "abc123",
  "status": "complete",
  "metrics": {
    "hallucination_rate": 0.018,
    "factuality": 0.91,
    "pii_leak_count": 0,
    "latency_p50_ms": 1240,
    "latency_p95_ms": 3200,
    "total_cost_usd": 4.82,
    "case_count": 250,
    "pass_count": 243,
    "fail_count": 7
  },
  "regression_summary": {
    "vs_baseline_run": "run-uuid-baseline",
    "deltas": { "hallucination_rate": -0.004, "factuality": 0.012 },
    "alerted": false
  },
  "harness_url": "https://evals.sandboxhub.co/runs/run-uuid"
}
```

**Responses:**
- `201 {"status": "accepted", "platform_record_id": "..."}`
- `200 {"status": "duplicate", "platform_record_id": "..."}` (idempotent replay)
- `400 {"error": "unknown_ai_system_id"}` — `ai_system_id` does not exist in platform
- `401 {"error": "invalid_hmac"}` / `{"error": "nonce_expired"}` / `{"error": "nonce_replayed"}`
- `422 {"error": "validation_failed", "details": [...]}` — Pydantic errors

**Side effects:**
- Appended to `data/platform_eval_runs.jsonl`
- AI System's `latest_eval_run` field updated (in-memory rollup cached, recomputed on read)
- If `regression_summary.alerted == true` → create a finding row referencing this run

---

### Endpoint 2 — Finding Ingest

```
POST /api/ingest/finding
```

**Request body:**
```json
{
  "event_id": "evt-...",
  "tenant_id": "default",
  "occurred_at": "2026-05-20T14:05:00Z",
  "ai_system_id": "ai-sys-001",
  "source": "eval-harness",
  "source_run_id": "run-uuid",
  "external_finding_id": "harness-fail-uuid",
  "severity": "HIGH",
  "category": "hallucination",
  "title": "Hallucination rate exceeds threshold on payments-golden dataset",
  "description": "5/250 cases (2.0%) returned fabricated account numbers. Threshold is 1.0%.",
  "evidence_links": [
    "https://evals.sandboxhub.co/runs/run-uuid/failures/fail-1",
    "https://evals.sandboxhub.co/runs/run-uuid/failures/fail-2"
  ],
  "recommended_action": "Re-prompt with stricter grounding constraints; re-run before release."
}
```

**Responses:**
- `201 {"status": "accepted", "finding_id": "FIN-..."}`
- `200 {"status": "duplicate", "finding_id": "FIN-..."}`
- `400`, `401`, `422` — as above

**Side effects:**
- Appended to `data/platform_findings.jsonl` (same shape as existing platform findings)
- Linked to AI System; appears in Findings page with `source: eval-harness` badge
- Triggers existing platform notification pipeline (Slack to AI Governance role)

---

### Endpoint 3 — Evidence Item Ingest

```
POST /api/ingest/evidence-item
```

**Request body:**
```json
{
  "event_id": "evt-...",
  "tenant_id": "default",
  "occurred_at": "2026-05-20T14:10:00Z",
  "ai_system_id": "ai-sys-001",
  "source": "eval-harness",
  "evidence_type": "eval_bundle",
  "title": "Eval bundle — payments-golden v1.3.0 — run abc123",
  "sha256": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
  "storage_url": "https://evals.sandboxhub.co/evidence/bundle-uuid/download",
  "control_mapping": {
    "NIST_AI_RMF": ["MEASURE-2.7", "MEASURE-2.11"],
    "EU_AI_ACT_ANNEX_IV": ["Section 2(b)"],
    "OWASP_LLM": ["LLM01", "LLM06"]
  },
  "generated_by_user": "engineer@customer.com",
  "size_bytes": 482719
}
```

**Responses:**
- `201 {"status": "accepted", "evidence_id": "EV-..."}`
- `200 {"status": "duplicate"}`
- `400`, `401`, `422`

**Side effects:**
- Added to AI System's evidence list; appears on Evidence page
- `source: eval-harness` badge in UI
- Auditor view shows the SHA-256 for integrity verification
- Download link opens harness UI (platform never stores the bundle bytes)

---

### Endpoint 4 — Gate Decision Ingest

```
POST /api/ingest/gate-decision
```

**Request body:**
```json
{
  "event_id": "evt-...",
  "tenant_id": "default",
  "occurred_at": "2026-05-20T14:15:00Z",
  "ai_system_id": "ai-sys-001",
  "policy_id": "policy-billing-prod",
  "policy_version": 3,
  "run_id": "run-uuid",
  "passed": false,
  "blocking_failures": [
    {
      "gate_name": "hallucination_rate",
      "expression": "hallucination_rate < 0.02",
      "actual_value": 0.028,
      "severity": "blocking"
    }
  ],
  "non_blocking_warnings": [],
  "harness_url": "https://evals.sandboxhub.co/policies/policy-billing-prod/eval/run-uuid"
}
```

**Responses:**
- `201 {"status": "accepted"}`
- `200 {"status": "duplicate"}`
- `400`, `401`, `422`

**Side effects:**
- Appended to `data/platform_gate_decisions.jsonl`
- Updates release gate state on AI System (matches existing platform release gate model)
- If `passed == false` and AI System is in "Approved" release state → flag for re-review; surface banner on AI System detail page
- Override workflow: platform's existing approval flow handles overrides; harness does not override directly

---

### Endpoint 5 — Review Sign-Off Ingest

```
POST /api/ingest/review-signoff
```

**Request body:**
```json
{
  "event_id": "evt-...",
  "tenant_id": "default",
  "occurred_at": "2026-05-20T14:20:00Z",
  "ai_system_id": "ai-sys-001",
  "revision_id": "rev-...",
  "reviewer_email": "reviewer@customer.com",
  "reviewer_role": "AI Governance",
  "decision": "APPROVE",
  "decision_rationale": "Failure samples reviewed; all are acceptable edge cases. Recommend monitoring.",
  "linked_failures": ["harness-fail-uuid-1", "harness-fail-uuid-2"],
  "inter_rater_agreement_kappa": 0.84
}
```

**Responses:**
- `201 {"status": "accepted"}`
- `200 {"status": "duplicate"}`
- `400`, `401`, `422`
- `404 {"error": "unknown_revision_id"}` if linked to an Edit AI System revision that doesn't exist

**Side effects:**
- Appended to `data/platform_review_signoffs.jsonl`
- If linked to a revision: appended to that revision's approval list (matches existing `ai_system_edit.py` decide flow)
- Reviewer's kappa score recorded for audit trail
- Surfaces on Revision History panel under the AI System

---

### Shared Validation & Error Handling

`domain/platform_ingest.py` exposes:

```python
def verify_hmac(headers: dict, body_bytes: bytes) -> Result[None, IngestError]:
    """Constant-time HMAC verify. Checks timestamp drift (±300s), nonce replay."""

def check_idempotent(event_id: str, jsonl_path: Path) -> bool:
    """Returns True if event_id already seen."""

def append_event(record: dict, jsonl_path: Path) -> None:
    """Atomic append to JSONL with fsync."""

def lookup_ai_system(ai_system_id: str) -> AISystem | None:
    """Reads existing AI System registry."""
```

All five endpoint handlers in `api/platform_ingest.py` share this flow:
```
1. verify_hmac → 401 on failure
2. parse + validate Pydantic model → 422 on failure
3. lookup_ai_system → 400 on unknown ID
4. check_idempotent → 200 if duplicate
5. append_event → 201 with record ID
6. fire side-effect hooks (notifications, rollups)
```

---

### AI Systems UI — Eval Harness Tab

`static/ai-systems.html` modification: add a new tab to the AI System detail drawer.

**Tab placement:** between "Findings" and "Evidence" tabs.

**Tab label:** `Eval Harness` with badge showing latest run status (PASS / FAIL / N/A).

**Tab content:**
```
┌─────────────────────────────────────────────────────────────────┐
│ Eval Harness — ai-sys-001 (billing-agent)                       │
│ Last sync: 2 min ago    [Open in Eval Harness →]                │
├─────────────────────────────────────────────────────────────────┤
│ Latest Run                                                       │
│   Run ID: run-abc123     Status: COMPLETE                       │
│   Dataset: payments-golden v1.3.0                                │
│   Prompt: v4 · Commit: abc123                                    │
│                                                                  │
│   Metrics:                                                       │
│     Hallucination rate:  1.8%   (threshold 2.0%) ✓              │
│     Factuality:          91%    (threshold 90%) ✓               │
│     PII leak count:      0      (threshold 0)   ✓               │
│     Latency p50:         1.24s                                  │
│                                                                  │
│   vs. baseline run-xyz789:                                       │
│     Hallucination rate:  -0.4% (improved)                        │
│     Factuality:          +1.2% (improved)                        │
├─────────────────────────────────────────────────────────────────┤
│ Recent Runs (last 10)                                            │
│   [table: timestamp, dataset@version, pass/fail, deep link]      │
├─────────────────────────────────────────────────────────────────┤
│ Gate Decisions (last 10)                                         │
│   [table: timestamp, policy, passed, blocking gates]             │
├─────────────────────────────────────────────────────────────────┤
│ Eval-Sourced Findings (open)                                     │
│   [table: severity, category, title, source run]                 │
├─────────────────────────────────────────────────────────────────┤
│ Eval-Sourced Evidence                                            │
│   [table: type, title, generated, SHA-256, download]             │
└─────────────────────────────────────────────────────────────────┘
```

**Backing API endpoint (new):**
```
GET /api/ai-systems/{id}/eval-harness-summary
```

Reads from the 4 platform JSONL files, filters by `ai_system_id`, returns a single bundled view.

**Deep links:** every "→" in the tab opens `evals.sandboxhub.co/...` in a new tab. Platform never embeds harness pages; iframes are out of scope.

---

### Build sequence on the platform

This work blocks harness deploy. Estimate: **3–4 days**.

| Day | Task |
|---|---|
| 1 | Build `domain/platform_ingest.py` (HMAC + idempotency + append helpers). Build endpoint 1 (eval-run). Unit tests for HMAC verify. |
| 2 | Build endpoints 2 (finding), 3 (evidence-item). Wire side-effects (existing findings + evidence stores). |
| 3 | Build endpoints 4 (gate-decision), 5 (review-signoff). Build `GET /api/ai-systems/{id}/eval-harness-summary`. |
| 4 | Build "Eval Harness" tab in `static/ai-systems.html`. End-to-end test with curl POST → tab refresh. Deploy to `aigovern.sandboxhub.co`. |

**Acceptance:** curl five HMAC-signed POSTs against the deployed platform; refresh AI System detail page; all data appears in the Eval Harness tab.

---

## 7. Ingestion API Contract

All ingestion endpoints validate HMAC before touching the DB.

```
POST /api/ingest/trace
Authorization: SL-HMAC-SHA256 timestamp=<unix>, nonce=<uuid>, sig=<hex>
Content-Type: application/json

{
  "external_id": "trace-abc-123",           # idempotency key
  "agent_id": "agent-billing-001",
  "prompt_redacted": "What is the balance for [PERSON_001]?",
  "response_redacted": "The balance for [PERSON_001] is [AMOUNT_001].",
  "tokens_in": 42,
  "tokens_out": 18,
  "latency_ms": 1240,
  "cost_usd": 0.000312,
  "metadata": { "transaction_id": "txn-9981" },
  "captured_at": "2026-05-20T14:22:00Z"
}

Response 201: { "trace_id": "...", "status": "accepted" }
Response 409: { "status": "duplicate" }           # idempotent replay
Response 401: { "error": "invalid_hmac" }
```

**HMAC verification:**
```python
# sig = HMAC-SHA256(key=HMAC_SECRET, msg=f"{timestamp}.{nonce}.{body_bytes}")
# Reject if: abs(now - timestamp) > INGEST_NONCE_TTL_SECONDS
# Reject if: nonce seen in last TTL window (Postgres table or in-memory LRU)
```

---

## 8. Week-by-Week Build Tasks

**Updated scope:** 14 features (F1–F14), 12-week build. F10 (RAG eval pack), F11 (model-as-judge runner), F12 (guardrails adapter), F13 (custom metric SDK), F14 (two-way pipe) added per scope expansion. See spec doc §2 for full feature specs.

### P1 — Foundation + Scoring (Weeks 1–5)

#### Week 1 — Repo, DB, Auth, SDK Skeleton

**Day 1–2: Repo + Infrastructure**
```
Tasks:
- Create signallayer/eval-harness repo
- uv init + pyproject.toml (harness deps: fastapi, sqlalchemy[asyncio], asyncpg,
  alembic, pydantic-settings, msal, itsdangerous, httpx, jinja2, weasyprint)
- CLAUDE.md with project-specific rules
- .env.example with all vars documented
- deploy/provision.ps1: Azure Postgres Flexible (eastus, B2ms for dev) + App Service P2V3 Linux Python 3.12
- harness/settings.py: Pydantic Settings v2, fail-loud missing vars

Deliverable: `az resource list --resource-group rg-evalharness-dev` shows Postgres + App Service
```

**Day 3: DB Schema**
```
Tasks:
- harness/db/models.py: all 14 SQLAlchemy mapped classes
- harness/db/session.py: async engine + session factory
- alembic init + harness/db/migrations/env.py
- alembic/versions/001_initial_schema.py (all tables + indexes)
- harness/db/seed.py: seed org "SignalLayer Dev" + admin user
- alembic upgrade head + seed.py verify

Deliverable: psql shows all 14 tables, seed row visible
```

**Day 4–5: Entra SSO + RBAC**
```
Tasks:
- harness/middleware/auth.py: OIDC redirect → callback → session cookie (port platform pattern)
- harness/middleware/rbac.py: ROLES dict + require_role() dep
- harness/api/auth.py: GET /login → /api/auth/callback → redirect home, GET /logout
- harness/templates/login.html: bare-bones login button
- harness/main.py: app factory, mount middleware, health route GET /health
- Smoke: curl /health → 200, /login → redirect to Entra

Deliverable: SSO round-trip works locally; /api/* routes return 401 without session
```

**Day 6–7: SDK Skeleton**
```
Tasks:
- sdk/pyproject.toml (deps: httpx, pydantic, spacy optional)
- sdk/signallayer_eval/config.py: init() stores config in module-level singleton
- sdk/signallayer_eval/client.py: async HTTP client, HMAC signing, retry queue
- sdk/signallayer_eval/redact.py: regex redactors (SSN, email, phone, CC, ARN)
- sdk/signallayer_eval/__init__.py: public API — init, trace_call, @trace decorator
- harness/api/ingest.py: POST /api/ingest/trace (HMAC verify, idempotency, DB write)
- harness/domain/ingestion.py: verify_hmac(), normalize_trace(), check_nonce()
- Integration smoke: sdk trace_call() → harness ingest → row in traces table

Deliverable: `python -c "import signallayer_eval; signallayer_eval.trace_call(...)"` → 201
```

---

#### Week 2 — SDK Redaction + Token Map + Ingestion Polish

**Day 8–9: PII Redaction + Token Map**
```
Tasks:
- sdk/signallayer_eval/redact.py: add spaCy NER (lazy-load en_core_web_sm)
- sdk/signallayer_eval/token_map.py:
    - ReversibleTokenMap class
    - Encrypt token map with customer-provided AES-256 key (cryptography lib)
    - Write to Azure Blob Storage via SAS URL (azure-storage-blob dep, optional)
    - Fallback: write to ~/.signallayer/token_map.json.enc if no SAS URL
- Unit tests: test_redaction.py — 50 cases covering each pattern, verify no PII in output

Deliverable: test_redaction.py passes 50/50; token map written to blob
```

**Day 10: Eval Run Ingestion**
```
Tasks:
- sdk/signallayer_eval/run.py: EvalRun context manager
- harness/api/ingest.py: POST /api/ingest/eval-run (create EvalRun row, trigger regression job)
- harness/domain/ingestion.py: normalize_eval_run(), validate_dataset_version()

Deliverable: EvalRun context manager creates run row + results rows via API
```

**Day 11–12: Run List + Detail UI**
```
Tasks:
- harness/api/runs.py: GET /api/runs (paginated, filter by agent/status/date)
- harness/templates/runs.html: run list table (status badge, dataset, prompt version, metrics)
- harness/templates/run_detail.html: metrics panel + results table + failures list
- harness/templates/dashboard.html: KPI cards (total runs, pass rate, avg latency, total cost)
- harness/templates/base.html: nav (Dashboard, Runs, Failures, Review, Datasets, Policies, Costs, Audit)
- harness/static/harness.css + harness.js: design tokens matching platform aesthetic

Deliverable: /dashboard shows KPIs, /runs shows run list, /runs/{id} shows detail
```

---

#### Week 3 — Model-as-Judge Scoring Runner (F11)

**Day 13–14: Scorer Base + Built-In Scorers**
```
Tasks:
- harness/domain/scoring.py:
    - Scorer abstract base class (name, version, calibration_set_id, async score())
    - ScoreResult dataclass (value, label, metadata, judge_model, n_samples, cost_usd)
    - Built-in scorers: factuality, hallucination_detect, relevance, pii_leak, refusal, format_compliance
    - Each scorer has versioned prompt + frozen calibration set reference
- harness/domain/judge_router.py:
    - Route judge calls via assurance_providers pattern (Anthropic / OpenAI / Bedrock)
    - Enforce self-judging ban (judge model ≠ model under test) — log + warn on override
    - n_samples=3 majority vote at temperature=0
- tests/unit/test_scoring.py: 15 cases per scorer (pass, fail, edge)

Deliverable: score_run(run_id) writes per-result scores; calibration kappa surfaced
```

**Day 15–16: Calibration + Async Execution**
```
Tasks:
- harness/domain/scoring.py:
    - calibrate_scorer(scorer, gold_dataset_id) → kappa, agreement_table
    - reject_stale_calibration(scorer) — refuse if >30 days old
- harness/api/scoring.py:
    - POST /api/runs/{id}/score (trigger scoring)
    - GET /api/scorers (list with calibration status)
- run_detail.html: scoring panel (per-scorer kappa, n_samples, judge model, cost)
- Parallel execution: asyncio.gather over results, respect provider rate limits

Deliverable: 1000-case run scored in <5min; calibration drift surfaced in UI
```

---

#### Week 4 — RAG Eval Pack (F10)

**Day 17–18: Retrieval-Quality Scorers**
```
Tasks:
- sdk/signallayer_eval/rag.py: trace_rag_call(query, retrieved_chunks, response, expected=None)
- harness/domain/rag_scorers.py:
    - precision_at_k, recall_at_k, mrr, ndcg_at_k (pure-Python; numpy)
    - All accept (retrieved_ids, ground_truth_ids, k)
- tests/unit/test_rag_retrieval.py: 20 cases against RAGAS reference values

Deliverable: retrieval scorers match RAGAS within 1% on canonical set
```

**Day 19–20: Judge-Graded RAG Scorers**
```
Tasks:
- harness/domain/rag_scorers.py:
    - context_relevance(query, chunks) — judge scorer via F11
    - answer_faithfulness(answer, chunks) — judge scorer via F11
    - context_utilization(answer, chunks) — judge scorer via F11
- eval-packs/rag-default-v1.yaml: off-the-shelf RAG eval pack
- run_detail.html: RAG metrics panel (separate from "model quality" panel)

Deliverable: RAG agent scored on all 7 metrics in <60s for 100-case dataset
```

**Day 21: RAG UI + Eval Pack Template**
```
Tasks:
- harness/templates/rag_panel.html: per-query breakdown (chunks shown, relevance, faithfulness)
- docs/rag-eval-guide.md: how to wire trace_rag_call + interpret metrics

Deliverable: A customer reading the guide can eval their RAG agent in <30 min
```

---

#### Week 5 — Regression Detection (F2) + Two-Way Pipe (F14)

**Day 22–23: Regression Detection (F2)**
```
Tasks:
- harness/domain/regression.py:
    - compute_deltas(run_a, run_b) → per-metric diff dict (uses F11 scores)
    - bootstrap_significance(scores_a, scores_b, n=1000) → p_value, is_significant
    - find_baselines(run) → last 5 runs same dataset+agent
    - check_alert_thresholds(delta) → list of triggered thresholds
- harness/domain/alerts.py: dispatch_slack(webhook_url, message)
- Background task: on eval_run complete → score → compare → alert
- harness/api/runs.py: expose regression delta on GET /api/runs/{id}
- run_detail.html: regression panel
- tests/unit/test_regression.py: 20 cases

Deliverable: complete an eval run → Slack message within 60s on regression
```

**Day 24–25: Two-Way Pipe (F14) — Platform → Harness**
```
Tasks:
- harness/api/platform_ingest.py:
    - POST /api/ingest/platform-adversarial-result (Garak results from platform)
    - POST /api/ingest/platform-guardrail-eval (NeMo eval results from platform)
    - POST /api/ingest/platform-provider-audit (provider routing decisions)
- harness/domain/platform_intake.py: HMAC verify, normalize, store with source=platform
- harness/db/models.py: add source column to eval_results
- run_detail.html: filter/badge for platform-sourced vs harness-native results
- Platform side (in ai-assurance-mvp repo):
    - domain/harness_pipe.py: outbound HMAC client + POST builder
    - On adversarial run / guardrail eval completion → POST to harness
- Integration smoke: trigger Garak run on platform → result in harness <60s

Deliverable: unified "all eval results for ai-sys-001" view shows both sources
```

**Day 26: P1 Milestone Gate**
```
Checklist:
[ ] POST /api/ingest/trace → 201, trace in DB
[ ] EvalRun context manager creates run + results
[ ] Model-as-judge runner scores results with calibration kappa
[ ] RAG eval pack scores RAG agent on 7 metrics
[ ] Regression detection fires on 5% metric drop using judge scores
[ ] Slack alert delivered within 60s
[ ] SSO login/logout works
[ ] RBAC blocks wrong-role requests with 403
[ ] Platform → harness pipe: Garak result lands in harness
[ ] /dashboard, /runs, /runs/{id} render correct data
[ ] All unit tests passing

If ≥8/10 pass: proceed to P2. If <8: debug before proceeding.
Show to ≥1 design-partner engineer before continuing.
```

---

### P2 — Customer-Ready (Weeks 6–9)

#### Week 6 — Run Comparison (F8) + Cost Tracking (F6)

**Day 18–19: Side-by-Side Comparison (F8)**
```
Tasks:
- harness/domain/comparison.py:
    - diff_runs(run_id_a, run_id_b) → {same, better, worse, new, missing} per test case
    - cluster_failures(results) → group by failure_category
- harness/api/runs.py: GET /api/runs/{id}/compare?baseline={id}
- harness/templates/comparison.html:
    - Two-column diff view
    - Filters: category, severity, dataset subset
    - Export CSV button
    - Permalink (URL with run IDs)
- harness/static/harness.js: truncate long traces by default, expand on click

Deliverable: /runs/{id}/compare?baseline={id} renders diff in <2s for 1K results
```

**Day 20–21: Cost Tracking (F6)**
```
Tasks:
- harness/domain/cost_engine.py:
    - PRICE_TABLE dict (model → $/1K tokens in, $/1K tokens out, refreshed date)
    - compute_cost(tokens_in, tokens_out, model) → usd
    - aggregate_costs(agent_id, period) → {total, per_day, per_call}
    - detect_anomaly(agent_id) → bool (24h spend > 2× 7-day rolling mean)
- harness/api/costs.py: GET /api/costs/summary, /api/costs/agents/{id}
- harness/templates/costs.html:
    - Cost trend sparkline (vanilla JS canvas, no charting lib dependency)
    - Top 10 most expensive agents table
    - "Price table last updated: YYYY-MM-DD" badge
    - Anomaly alert banner when triggered
- Budget alert: persist monthly cap in agents table; check on every trace ingest

Deliverable: /costs shows correct aggregations; anomaly alert fires on mock spike
```

---

#### Week 7–8 — Human Review Queue (F4) + Guardrails Adapter (F12)

**Parallel track (F12, ~2 days during Week 8):**
```
Tasks:
- harness/domain/guardrails_adapter.py:
    - NeMoGuardrailsAdapter: load platform's NeMo config (by URL or path)
    - LlamaGuardAdapter: optional second adapter
    - Score outputs: input_safety, output_safety, safety_score (composite)
    - Pin config hash; refuse to run if config mismatch detected
- harness/api/scoring.py: register adapters as scorer types
- run_detail.html: safety panel with per-rail pass/fail breakdown
- tests/unit/test_guardrails.py: same config produces identical decisions to platform

Deliverable: 100 cases evaluated by NeMo in <30s; rail breakdown visible in UI
```

#### Week 7–8 — Human Review Queue (F4) [main track]

**Day 22–24: Review Queue UI + Assignment Logic**
```
Tasks:
- harness/domain/review_queue.py:
    - route_failure(failure) → assign to reviewer(s) based on severity + workload
    - get_queue(reviewer_id) → list of pending assignments, capped at 50
    - submit_review(assignment_id, label, rationale)
- harness/api/review.py:
    - GET /api/review/queue (reviewer's pending items)
    - POST /api/review/{assignment_id}/submit
    - GET /api/review/stats (completion rate, avg time per review)
- harness/templates/review_queue.html:
    - One-at-a-time card UI (prompt, response, model verdict, score)
    - Pass / Fail / Unclear buttons with keyboard shortcuts (P/F/U)
    - Rationale text field (required for Fail)
    - Queue depth + time estimate banner
    - Progress bar

Deliverable: reviewer logs in → sees queue → submits labels → failure status updates
```

**Day 25–26: Inter-Rater Agreement + Calibration**
```
Tasks:
- harness/domain/review_queue.py:
    - compute_kappa(reviewer_a_labels, reviewer_b_labels) → Cohen's κ
    - compute_alpha(all_reviewer_labels) → Krippendorff's α
    - detect_reviewer_drift(reviewer_id) → bool (kappa vs gold < 0.7)
- harness/domain/calibration.py:
    - manage calibration dataset (50–100 hand-labeled cases)
    - score_reviewer_against_gold(reviewer_id) → kappa, accuracy
    - schedule_recalibration(reviewer_id)
- harness/api/calibration.py:
    - GET /api/calibration/set (calibration cases for this reviewer)
    - POST /api/calibration/submit
    - GET /api/calibration/scores (admin view: all reviewers' kappa)
- harness/templates/calibration.html: calibration test UI + score history
- tests/unit/test_kappa.py: 10 cases including edge cases (all-agree, all-disagree)

Deliverable: kappa computed correctly; drift flag fires when kappa drops below 0.7
```

---

#### Week 9 — Evidence Export (F3) + Custom Metric SDK (F13)

**Parallel track (F13, ~2 days):**
```
Tasks:
- sdk/signallayer_eval/scorers.py: Scorer base class + ScoreResult (shared with harness/domain/scoring.py via shared module)
- Entry-point discovery: customers register scorers in their pyproject.toml under `signallayer_eval.scorers`
- examples/json_schema_scorer.py: worked example custom scorer
- docs/custom-scorers-guide.md: how to write, register, test
- Sandboxing: 30s timeout + memory cap per scorer call; surface failures as scorer errors

Deliverable: A customer ships their first custom scorer in <2h from docs
```

#### Week 9 — Evidence Export (F3) [main track]

**Day 27–29: Evidence Bundle Assembly**
```
Tasks:
- harness/domain/evidence_builder.py:
    - CONTROL_MAP dict: eval category → [NIST AI RMF, EU AI Act, SR 11-7, ISO 42001, OWASP LLM]
    - build_bundle(run_id, generated_by) → EvidenceBundle dataclass
        - eval_results.json (sanitized)
        - failure_samples.json (top 20, redacted)
        - reviewer_signoffs.json (labels + rationale)
        - model_metadata.json (version, prompt hash, dataset version)
        - control_mapping.json (eval category → control IDs + pass/fail)
    - compute_sha256(bundle_bytes) → hex string
    - upload_to_blob(bundle_bytes, storage_path) → url
- harness/api/evidence.py: POST /api/evidence/export (async; returns job_id)
- Background task: assemble bundle → upload → update evidence_bundles row

Deliverable: POST /api/evidence/export → job completes in <30s, sha256 matches
```

**Day 30: Evidence PDF + UI**
```
Tasks:
- harness/domain/evidence_builder.py: render_pdf(bundle) via WeasyPrint
    - Template sections: Executive Summary, Eval Summary, Failures, Reviewer Sign-offs,
      Control Mapping, Integrity Hash
- harness/templates/evidence_report.html: PDF template (strict — no dynamic logic)
- harness/api/evidence.py: GET /api/evidence/{id}/download → ZIP(json+csv+pdf)
- run_detail.html: "Export Evidence Bundle" button (Risk role only) + bundle history

Deliverable: ZIP download contains valid PDF + JSON + CSV; sha256 matches stored hash
```

**Day 31: P2 Milestone Gate**
```
Checklist:
[ ] Side-by-side comparison renders correct diff
[ ] CSV export from comparison works
[ ] Cost dashboard shows correct aggregations
[ ] Anomaly alert fires correctly
[ ] Review queue routes failures to correct reviewers
[ ] Labels update failure status
[ ] Cohen's kappa computed correctly
[ ] Evidence bundle download: PDF + JSON + CSV in ZIP
[ ] SHA-256 matches stored value
[ ] Reproducible: same inputs → identical hash

Show to ≥2 design partners. Get written feedback before P3.
Gate: don't proceed to P3 unless ≥1 partner says "I would use this in production."
```

---

### P3 — Stickiness (Weeks 10–12)

#### Week 10 — Dataset Versioning + Drift (F7)

**Day 32–34: Dataset Versioning**
```
Tasks:
- harness/domain/dataset_versions.py:
    - create_version(project_id, name, cases) → Dataset (semver auto-increment)
    - diff_versions(dataset_id_a, dataset_id_b) → {added, removed, modified} case IDs
    - coverage_map(dataset_id) → {per_category, per_risk_tier, per_domain} counts
- harness/api/datasets.py:
    - GET /api/datasets (list, with version history)
    - POST /api/datasets (create new version)
    - GET /api/datasets/{id}/diff?against={id}
- harness/templates/datasets.html:
    - Dataset browser with version history timeline
    - Diff view: added/removed/modified cases
    - Coverage map heatmap

Deliverable: create v1.0.0 → v1.1.0, diff shows correct changes
```

**Day 35–36: Drift Detection**
```
Tasks:
- harness/domain/dataset_versions.py:
    - embed_cases(cases) → numpy array (text-embedding-3-small via OpenAI; pin model version)
    - cluster_production_failures(agent_id, since) → clusters with representative cases
    - find_coverage_gaps(clusters, dataset_id) → list of {cluster, nearest_dataset_case, distance}
    - surface_uncovered_cases(agent_id) → "12 production failures not in golden set"
- Weekly cron: run drift detection for all active agents → store results → notify Engineer role
- datasets.html: "Potential gaps" panel with "Promote to golden" button (triggers F4 review)

Deliverable: weekly job surfaces production failures not in dataset; promote flow works
```

---

#### Week 11 — Policy-as-Code Gates (F9)

**Day 37–39: Policy Engine + Evaluation**
```
Tasks:
- harness/domain/policy_engine.py:
    - parse_policy(yaml_str) → Policy dataclass (gates list)
    - evaluate_gate(gate, run_metrics) → GateResult(passed, actual_value, threshold)
    - evaluate_policy(policy, run_id) → PolicyResult(passed, blocking_failures)
    - safe_expression_eval: whitelist-only (no exec/eval); parse to AST, evaluate
- harness/api/policies.py:
    - GET /api/policies (list by project)
    - POST /api/policies (upload YAML; validate + store)
    - POST /api/policies/evaluate?run_id={id} → gate results
    - POST /api/policies/{id}/override (Risk role; requires reason; logs to audit)
- harness/templates/policies.html:
    - YAML editor with syntax highlighting
    - Live gate evaluation preview
    - Gate status per latest run
    - Override history
- tests/unit/test_policy_engine.py: 15 cases (pass, fail, partial, invalid YAML)

Deliverable: YAML policy uploaded → eval run → gate check returns correct pass/fail
```

**Day 40–41: CLI + CI Templates**
```
Tasks:
- cli/signallayer_eval_cli/cmd_gate.py:
    `signallayer-eval gate check --run-id X --policy-id Y`
    → exit 0 if passed, exit 1 if blocked, prints blocking gates to stdout
- cli/pyproject.toml: entry_points for `signallayer-eval` command
- ci-templates/github-action.yml:
    ```yaml
    - name: Eval Gate Check
      uses: signallayer/eval-harness@v1
      with:
        run-id: ${{ steps.eval.outputs.run_id }}
        harness-url: ${{ secrets.SL_HARNESS_URL }}
        hmac-key: ${{ secrets.SL_HMAC_KEY }}
    ```
- ci-templates/azure-devops-pipeline.yml: equivalent ADO snippet

Deliverable: `signallayer-eval gate check --run-id X` returns 1 + prints failed gates
```

#### Week 12 — Polish + Deploy + Final Smoke

**Day 56–60: Buffer, polish, end-to-end smoke**
```
Tasks:
- deploy/build-zip.py: whitelist harness/* + templates + static (port platform pattern)
- deploy/smoke.ps1: hit all 13 key routes, verify 200s
- All audit log entries verified (evidence export, policy override, user role change)
- Confirm price table stamp visible in /costs
- Confirm calibration test fires for new Reviewer on first login
- Final README.md with setup instructions

Deliverable: deploy/smoke.ps1 → 13/13 green on production App Service
```

---

## 9. Test Strategy

### Unit Tests (no DB, no HTTP — fast, run in CI)

| File | What it covers |
|---|---|
| `test_redaction.py` | 50 cases: SSN, email, phone, CC, ARN, NER; verify no PII in output |
| `test_regression.py` | 20 cases: no regression, real regression, same-version guard |
| `test_kappa.py` | 10 cases: all-agree (κ=1), all-disagree (κ=-1), partial agreement |
| `test_policy_engine.py` | 15 cases: pass, fail, partial, invalid YAML, expression edge cases |
| `test_cost_engine.py` | 10 cases: known token counts × known prices → expected USD |

**Target: 100% pass before any PR merges to main.**

### Integration Tests (real Postgres via Docker)

| File | What it covers |
|---|---|
| `test_ingest.py` | HMAC accept/reject, idempotency replay → 409, nonce expiry |
| `test_run_lifecycle.py` | Create run → ingest results → regression check → alert dispatched |
| `test_evidence_export.py` | Bundle assembly → sha256 stable → PDF renders |

**Run on PR in CI; also run before every production deploy.**

### Manual Smoke Tests (post-deploy)

```powershell
# deploy/smoke.ps1 hits:
GET  /health                    → 200
GET  /login                     → 302 to Entra
GET  /dashboard                 → 200 (with session)
GET  /runs                      → 200
GET  /runs/{id}                 → 200
GET  /runs/{id}/compare?baseline={id} → 200
GET  /failures                  → 200
GET  /review/queue              → 200 (Reviewer role)
GET  /costs                     → 200
GET  /datasets                  → 200
GET  /policies                  → 200
GET  /audit                     → 200 (Admin role)
POST /api/ingest/trace          → 201
```

---

## 10. Deployment — Single Tenant at `evals.sandboxhub.co`

One environment. Same Azure subscription as `aigovern.sandboxhub.co`. Same DNS zone, same
auth patterns, same deploy tooling.

### Resource Layout

```
Resource group:  rg-evals-dev
├── App Service:     app-evals-dev               (P1V3 Linux Python 3.12, Always On, HTTPS-only, TLS 1.2 min)
│   └── Custom domain: evals.sandboxhub.co       (managed cert)
├── Postgres:        pg-evals-dev                (Flexible Server, B2ms, eastus, public endpoint + firewall rules)
├── Storage:         stevalsdev                  (containers: token-maps, evidence-bundles, outbox)
├── Key Vault:       kv-evals-dev                (HMAC secrets, session secret, DB connection, platform sync key)
└── App Insights:    ai-evals-dev                (telemetry)
```

**Sizing rationale:**
- **P1V3 Linux** (not P2V3): 2 vCPU / 8 GB RAM. Enough for one tenant doing 100K traces/day. Bump to P2V3 if load testing demands.
- **Postgres B2ms**: 2 vCore / 8 GB RAM. Comfortable for 10M trace rows + JSONB indexes. Bump to D2ds_v5 when row count crosses ~50M.
- **Single instance everywhere.** Scale-out is a v2 problem.

### Provisioning Script

`deploy/provision.ps1` — one-off, idempotent. Same structure as the assurance platform's provisioning:

```powershell
param(
    [string]$Env = "dev",
    [string]$Location = "eastus"
)

$env:MSYS_NO_PATHCONV = "1"
az account set --subscription "SignalLayerDev"

# 1. Pre-register providers (Microsoft.Web, Microsoft.DBforPostgreSQL, Microsoft.Storage,
#    Microsoft.KeyVault, Microsoft.Insights)
# 2. Create resource group rg-evals-dev
# 3. Parallel via Start-Job:
#    - Postgres Flexible (B2ms, eastus, admin user, db "evalharness")
#    - Storage (st evals dev) + containers
#    - Key Vault
#    - App Insights
# 4. Generate secrets, store in Key Vault:
#    - HMAC_SECRET_INBOUND  (SDK → harness)
#    - HMAC_SECRET_OUTBOUND (harness → aigovern.sandboxhub.co)
#    - SESSION_SECRET
#    - Postgres connection string
# 5. Provision App Service P1V3 Linux Python 3.12
# 6. Wire Key Vault references into App Service app settings
# 7. Bind custom domain evals.sandboxhub.co + managed cert
# 8. Enable Always On, HTTP/2, HTTPS-only, TLS 1.2 min
# 9. Configure CORS (locked to evals.sandboxhub.co and aigovern.sandboxhub.co only)
# 10. Print URL, admin credentials, SDK init snippet

# Acceptance: GET https://evals.sandboxhub.co/health returns 200 from this script alone.
```

**Acceptance:** `git clone` to working `evals.sandboxhub.co/health` in <30 minutes.

### App Settings on App Service

All read from Key Vault references. Validated at startup via `harness/settings.py`.

```
DATABASE_URL                = @Microsoft.KeyVault(SecretUri=...)
HMAC_SECRET_INBOUND         = @Microsoft.KeyVault(SecretUri=...)
HMAC_SECRET_OUTBOUND        = @Microsoft.KeyVault(SecretUri=...)
SESSION_SECRET              = @Microsoft.KeyVault(SecretUri=...)
PLATFORM_BASE_URL           = https://aigovern.sandboxhub.co
PLATFORM_SERVICE_ACCOUNT_ID = <Entra app registration client id>
PLATFORM_SERVICE_ACCOUNT_SECRET = @Microsoft.KeyVault(SecretUri=...)
ENTRA_TENANT_ID             = <tenant guid>
ENTRA_CLIENT_ID             = <eval harness entra app reg>
ENTRA_CLIENT_SECRET         = @Microsoft.KeyVault(SecretUri=...)
SLACK_WEBHOOK_URL           = @Microsoft.KeyVault(SecretUri=...)
ANTHROPIC_API_KEY           = @Microsoft.KeyVault(SecretUri=...)
OPENAI_API_KEY              = @Microsoft.KeyVault(SecretUri=...)
ANALYTICS_ENABLED           = true
```

### Startup Command

```
gunicorn harness.main:app --workers 1 --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000 --timeout 120
```

### Deploy Flow

```powershell
# Build slim zip (port from platform's deploy/build-zip.py pattern)
python deploy/build-zip.py

# Deploy
az webapp deploy --src-path deploy/app.zip `
    --resource-group rg-evals-dev `
    --name app-evals-dev `
    --type zip

# Wait for Oryx build + warm-up
Start-Sleep -Seconds 60

# Smoke
Invoke-RestMethod https://evals.sandboxhub.co/health
.\deploy\smoke.ps1
```

### Platform-Side Changes Required

Before this deploy goes live, the assurance platform at `aigovern.sandboxhub.co` needs:

1. Five ingestion endpoints from Section 6a built and tested
2. Service account Entra app registration with read-only role on the platform
3. Outbound HMAC secret stored in platform's environment (matches harness's `HMAC_SECRET_OUTBOUND`)
4. New JSONL stores: `data/platform_eval_runs.jsonl`, `data/platform_findings.jsonl`
5. UI hook on AI System detail page: "Eval Harness" tab linking to `evals.sandboxhub.co/runs?ai_system_id=X`

**Sequence:** build platform-side endpoints first, then provision harness, then wire SDK. No point shipping the harness before the platform can receive its data.

### Scale-Up Plan (When We Hit It)

Not now. But document the thresholds so we don't get caught flat-footed:

| Signal | Action |
|---|---|
| App Service CPU > 70% sustained | Scale up to P2V3 |
| Postgres CPU > 70% sustained | Scale to D2ds_v5 |
| Postgres storage > 60% | Bump storage |
| Trace ingest > 10/s sustained | Add a second App Service instance + sticky sessions OR move ingest to a queue |
| Eval run completion > 5 min | Move scoring to a background worker (Azure Container Apps job) |
| User-facing latency > 2s p95 | Profile; likely DB index issue first |

None of this in v1. Build the metrics dashboard in v1 so we can see the thresholds approaching.

---

## 11. What "Done" Looks Like

The product is done when a design-partner engineering team can answer yes to all of:

1. "I wired up the SDK in < 1 day"
2. "My CISO approved data flow within 1 week (PII boundary satisfied)"
3. "F2 caught a regression before it hit production"
4. "F10 told me my retriever was broken before I shipped the prompt"
5. "F11's judge scores agree with my reviewers (κ ≥ 0.85)"
6. "F14 shows me Garak adversarial results next to my CI eval results in one view"
7. "I handed F3's PDF to our risk officer without editing it"
8. "I have an F9 policy gate in CI that blocked a release"
9. "I wrote my own custom scorer using F13 in under 2 hours"
10. "The platform at aigovern.sandboxhub.co shows my eval data in the AI System detail page"

If any answer is no, that feature is not done — it's a demo. Fix before declaring v1 complete.
