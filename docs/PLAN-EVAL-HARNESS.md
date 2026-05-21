# AI Eval Harness — Build Plan (Future)

**Status:** Plan. Not implemented. Captures the design across multiple conversations so a future builder can pick it up cold.
**Sibling product:** AI Assurance Platform (this repo, `aigovern.sandboxhub.co`).
**This product:** AI Eval Harness — separate codebase, separate UI, separate users, **pumps eval data into the assurance platform via a thin ingestion API.**

---

## 1. Executive Summary

The eval harness is a standalone product peer to Braintrust / Patronus / Confident AI / Galileo. Its job is to run reproducible, governed evaluations of AI workloads — deterministic checks, adversarial probes, and model-as-a-judge scoring — and pump results into the assurance platform so governance, risk, and audit users have real data to act on.

**Two products, one contract:**

- **AI Eval Harness** (this plan) — ML engineers' cockpit. Owns runs, test suites, datasets, scorers, traces, drift detection.
- **AI Assurance Platform** (existing, this repo) — Governance dashboard. Owns workloads, intake, risk classification, controls, gates, evidence, runtime, reassessment.

The harness never owns workload definitions, never makes policy decisions. It reads the workload spec from the platform, honors its policy envelope (especially provider routing), and posts results back as ingestion events.

---

## 2. Architecture

```
┌────────────────────────────────────┐           ┌─────────────────────────────────────┐
│  EVAL HARNESS                       │   pumps  │  AI ASSURANCE PLATFORM              │
│  evalharness.signallayer.ai         │ ───────► │  aigovern.sandboxhub.co             │
│                                     │   events │                                     │
│  Audience: ML engineers,             │           │  Audience: Risk, GRC, Audit,        │
│            eval owners,              │           │            Cloud Security           │
│            QA, prompt engineers      │           │                                     │
│                                     │           │                                     │
│  Owns: test suites, test cases,     │           │  Owns: workloads, intake, risk,     │
│        datasets, scorers, runs,     │           │        controls, gates, evidence,   │
│        traces, drift detection,     │           │        runtime, reassessment        │
│        comparisons, run-level       │           │                                     │
│        guardrails + approvals       │           │                                     │
└────────────────────────────────────┘           └─────────────────────────────────────┘
```

### Why two products

| Dimension | Eval Harness | Assurance Platform |
|---|---|---|
| Audience | ML engineers, eval owners, QA, prompt engineers | Risk, GRC, Audit, Cloud Security |
| Cadence | Every commit / nightly / pre-merge | Per assessment / per release / quarterly |
| Stakes | "Is this prompt better than last week's?" | "Can this AI system safely operate in production?" |
| State | Many runs per workload per day | One assessment per workload per quarter |
| UI texture | Engineering dashboard (trace explorers, drift charts, ensemble comparisons) | Governance dashboard (status, evidence, approvals) |

Trying to fold both into a single UI dilutes both audiences. Keep them separate; let the contract do the work.

---

## 3. Data Contract — the load-bearing piece

This is what unblocks both teams to build in parallel. Freeze this first.

### Read endpoints (platform-side, harness consumes)

| Endpoint | Returns |
|---|---|
| `GET /api/workloads/{id}` | Workload definition + policy envelope (allowed actions, blocked actions, raw-data boundary, external-LLM policy) |
| `GET /api/workload-intake/{id}` | Intake fields — feeds context to the eval (which model, which tools, which data classes) |
| `GET /api/eval-packs/{pack_id}@{version}` | Eval pack manifest: categories, thresholds, golden references |
| `GET /api/goldens/{set_id}@{version}` | Golden dataset cases + expected outputs |
| `GET /api/ai-systems/{id}/effective` | Current effective state (folded revisions) |

### Write endpoints (platform-side, harness pushes)

| Endpoint | Body schema (key fields) |
|---|---|
| `POST /api/ingest/eval-run` | `run_id, ai_system_id, pack_id, pack_version, golden_versions{}, started_at, completed_at, categories[{id, cases_run, cases_passed, pass_rate, status, threshold}], provider_routing{bedrock_calls, external_llm_calls, sanitized_inputs, raw_inputs}` |
| `POST /api/ingest/finding` | `run_id, severity, control_id, eval_case_id, title, description, sla_days` |
| `POST /api/ingest/evidence-item` | `run_id, type, name, sha256, size_bytes, captured_at` (artifact body goes to evidence vault separately) |
| `POST /api/ingest/runtime-event` | (optional) `category, severity, detail, ai_system_id` — for provider-routing telemetry |

### Cross-cutting requirements on every event

- `schema_version: "1.0"`
- `event_id: uuid` (server dedupes on this)
- `signed_by_harness: <hmac>` — HMAC-SHA256 over body + timestamp + nonce; rotating shared secret
- Platform rejects replays older than 5 min
- Idempotent — platform dedupes on `event_id`; harness can safely retry forever

### Platform-side additions to support this

Just ingest endpoints + read endpoints. **Zero UI changes.** Estimate: ~half a day.

| Platform-side change | Effort |
|---|---|
| `POST /api/ingest/eval-run` + storage | 1 hour |
| `POST /api/ingest/finding` (already have findings model — just wire) | 30 min |
| `POST /api/ingest/evidence-item` | 30 min |
| HMAC auth middleware for ingest endpoints | 1 hour |
| `GET /api/eval-packs/{id}@{version}` + JSONL store | 1 hour |
| `GET /api/goldens/{id}@{version}` + JSONL store | 1 hour |

---

## 4. Eval Pack Spec

The pack is the harness's input. Stored on the platform side, versioned, immutable per version.

```yaml
pack_id: eval-aws-analyzer-v1
version: "1.3.2"
workload_type: aws_deployment_analyzer
categories:
  - id: parser_determinism
    threshold: { min_pass_rate: 100 }
    requires_raw_data: true
    golden_ref: parser_determinism@v3
    runner: deterministic_regex

  - id: prompt_injection
    threshold: { min_pass_rate: 95 }
    requires_raw_data: false             # synthetic / sanitized inputs OK
    golden_ref: prompt_injection@v7
    runner: model_as_judge
    judge:
      preferred_provider: openai
      preferred_model: gpt-4o-mini
      fallback_chain: [openai, anthropic, bedrock]
      rubric: rubrics/prompt_injection_v3.md
      pass_threshold: 0.85
      n_samples: 3
      calibration_set: cal_prompt_injection@v1
      min_agreement_with_humans: 0.90

  - id: sanitizer_leak
    threshold: { min_pass_rate: 100 }
    requires_raw_data: true
    golden_ref: sanitizer_leak@v2
    runner: deterministic_regex

  - id: narrative_faithfulness
    threshold: { min_pass_rate: 90 }
    requires_raw_data: true              # narrative may reference raw ARNs
    golden_ref: narrative_faithfulness@v2
    runner: model_as_judge
    judge:
      preferred_provider: bedrock        # router will refuse external on raw
      fallback_chain: [bedrock, local]
      ensemble:
        - { provider: bedrock, model: claude-3-5-sonnet }
        - { provider: local,   model: llama-3-70b-vpc }   # second opinion
      rubric: rubrics/faithfulness_v3.md
      pass_threshold: 0.85
      n_samples: 3
      temperature: 0.0
      calibration_set: cal_faithfulness@v1
      min_agreement_with_humans: 0.90
```

---

## 5. Model-as-a-Judge

A class of eval categories where an LLM scores another LLM's output against a rubric. Used when no regex or deterministic check works — narrative faithfulness, finding quality, remediation actionability, harm detection.

### Calibration is required, not optional

A judge that hasn't been calibrated is just a vibe. Pre-flight check before every judged run:

1. **Calibration set** — 30–100 cases that humans have labeled. Lives next to the rubric, versioned.
2. **Pre-flight check** — Run the judge against the calibration set. If `agreement_with_humans < min_agreement` threshold (e.g. 90%), abort the run with a critical finding: `Judge calibration failed`.
3. **Calibration drift** — Track scores over time. 5%+ drop auto-creates a P1 finding (`Judge drift detected — re-calibrate`).
4. **Self-judging ban** — The judge model cannot be the same model + version as the model being judged. Harness validates at config load.

### Determinism — judges are noisy, mitigate explicitly

- **Temperature 0** for judge calls (always).
- **n_samples ≥ 3** for any score that drives a release-gate decision; majority vote with variance reported.
- **Pinned judge model version** — `bedrock/claude-3-5-sonnet@2024-10-22`, not `latest`.
- **Pinned rubric version** — rubric file is hashed; harness records the hash with every run.
- **Pinned prompt template** — judge prompt is in a versioned file, never inline.

### Per-case payload the harness writes back

```json
{
  "case_id": "FAITH-007",
  "score": 0.78,
  "score_scale": [0, 1],
  "passed": false,
  "judge_reason": "Narrative says S3 bucket has KMS encryption-context enforced but graph shows no such policy on bucket s3-case-docs.",
  "judge_model": "bedrock/claude-3-5-sonnet@2024-10-22",
  "judge_rubric_version": "faithfulness_v3",
  "judge_n_samples": 3,
  "judge_score_variance": 0.04,
  "judge_calibration_score": 0.93
}
```

### Categories worth judging for the AWS analyzer

| Category | What the judge grades | Judge provider |
|---|---|---|
| `narrative_faithfulness` | Does narrative match the graph? Any made-up resources, missed concerns? | Bedrock (raw content) |
| `finding_quality` | Are findings well-described, severity-appropriate, with concrete remediations? | Bedrock (raw content) |
| `remediation_actionability` | Is the remediation plan executable, with owners + dates + steps? | OpenAI / Anthropic (sanitized) |
| `harm_detection` | Bias, harm, inappropriate content? | OpenAI / Anthropic (sanitized) |
| `comparative_quality` | Pairwise: is this run's narrative better than last run's? | Bedrock (raw content) |

### Failure modes to defend against

| Failure mode | Defense |
|---|---|
| Judge agrees with everything (sycophancy) | Calibration set + min-agreement gate |
| Judge has been prompt-injected by the content | Prompt-injection eval on the judge itself; judge prompt structure isolates content via clear delimiters |
| Judge cost runs away | Per-run + per-day budget caps; circuit-breaker if cost > 2× p95 |
| Judge sees raw data when policy forbids | Pre-call policy check; refuse + log a runtime event |
| Bias from model family choice | Two judges from different families on critical categories; flag disagreement |

---

## 6. Multi-Provider Routing

The harness honors the platform's assurance-provider router. It never decides which provider to use — it asks the platform.

### Provider matrix

| Judged content / model input | Allowed judge providers |
|---|---|
| Raw customer deployment metadata (ARNs, account IDs, IAM, VPC topology) | Bedrock · Local/VPC |
| Sanitized / token-mapped outputs | **OpenAI · Anthropic · Bedrock · Local/VPC** |
| Synthetic test cases (red-team generated, no customer-derived bits) | **OpenAI · Anthropic · Bedrock · Local/VPC** |
| Aggregate scores / metrics only | **OpenAI · Anthropic · Bedrock · Local/VPC** |

### How the harness calls the router

```python
decision = platform.assurance_providers.select(
    use_case="judge_narrative_faithfulness",
    data_classes=case.data_classes,        # e.g. {AWS_METADATA, IAM_POLICY}
    preferred_provider=cfg.judge.preferred, # e.g. "anthropic"
)
# decision.provider_type → "bedrock" | "openai" | "anthropic" | "local"
# decision.reason → why this provider (policy + cost + latency)
# decision.audit_id → ID for the audit trail
```

If the preferred is OpenAI and the case has raw ARNs, the router falls back to Bedrock and logs the reason. If the case is sanitized, it honors the preferred. The harness just makes the call against whatever model the router returned.

### Benefits this unlocks

1. **Multi-judge ensembles** — Claude on Bedrock + GPT-4o on OpenAI. Disagreement = signal.
2. **Cost-optimized routing** — Cheap evals → `gpt-4o-mini`; expensive evals → `claude-sonnet`.
3. **Latency-optimized routing** — CI evals route to lowest-latency option that meets policy.
4. **Provider-failure resilience** — OpenAI down → router falls over to Anthropic when policy allows.

---

## 7. UI Vision

Modeled after the mock-up referenced in the planning conversation. Layout matches Braintrust / Patronus aesthetic.

### Left sidebar

- **EVALUATIONS** — Runs · Test Suites · Test Cases · Datasets · Metrics · Scorers
- **OBSERVABILITY** — Live Monitor · Alerts · Drift Detection · Quality Signals
- **GOVERNANCE** — Policies · Guardrails · Approvals · Audit Logs *(run-level, not workload-level)*
- **SETTINGS** — Integrations · Environments · Team · Settings

### Run detail page (the screenshot)

| Region | Content |
|---|---|
| Top bar | Run selector (`customer-support-agent-v2.4.1`) · COMPLETED badge · Run ID · timestamp · duration · evaluated_by · Git commit · Share / Export / Rerun |
| Tabs | Overview · Test Suites · Test Cases · Results · Traces · Error Analysis · Compare · Config |
| KPI strip | Overall Score · Pass Rate · Critical Failures · Total Tests · Avg Latency · Est. Cost |
| Score by Test Suite | Table with score, pass rate, sparkline trend per suite |
| Score Over Time | 7-day line chart with daily averages |
| Failures by Severity | Donut chart (Critical / High / Medium / Low) |
| Failures by Category | Horizontal bars (Hallucination / Incorrect Tool Use / Policy Violation / Bad Formatting / Other) |
| Run Details panel | Environment · Model · Model Version · Temperature · Max Tokens · Top P · Evaluated By · Git Commit · Dataset Version · Harness Version |
| Environment health | Vector DB · Tools · Guardrails · Monitoring · Cost Tracker (with health dots) |
| Top Failing Tests | List with failure count per test |
| Recent Failures | Table with test case, suite, severity, reason, score, time |
| Example Failure Trace | Selected failure with input · retrieved context · model output · failure reason · scorer · score |
| Trace View | Span tree: User → Retriever / Tools → LLM → Response |

---

## 8. Data Model

```
Project
  └─ Environment              (production, staging, ci)
       └─ Run                 (one eval execution; ID, model, model_version, dataset_version, git_commit)
            ├─ TestSuite      (General Quality, Tool Use, RAG, Safety & Policy, Factuality, ...)
            │    └─ TestCase  (input, expected, context, tags)
            │         └─ Result  (per-case: score, passed, latency, tokens, cost, trace_id)
            └─ Trace          (span tree: user → retriever → tools → LLM → response)

Dataset          (versioned, signed corpora used by test cases)
Scorer           (judge configs: deterministic | model_as_judge | human)
Metric           (rollup function: pass_rate, p95_latency, hallucination_rate, ...)

Guardrail        (run won't ship if X — e.g. "critical_failures == 0")
Policy           (who can promote a dataset version, who can override a guardrail)
Approval         (signed promotion of a dataset / scorer / suite)
AuditLog         (every state change, append-only)
```

### Storage

- **Postgres** — entities + relations (projects, runs, suites, cases, results, guardrails, approvals, audit log)
- **Object storage** — traces + raw input/output blobs (can be large; S3 or Azure Blob)
- **ClickHouse** — time-series rollups (Score Over Time, Drift Detection) — or DuckDB for v1

---

## 9. Tech Stack

| Concern | Choice | Why |
|---|---|---|
| Backend API | Python 3.12 + FastAPI | Matches platform, fast async, easy to ship |
| DB | Postgres | Entities + transactions |
| Time-series + drift | ClickHouse (or DuckDB for v1) | Score-over-time + drift queries are columnar workloads |
| Object storage | S3 / Azure Blob | Traces, raw I/O blobs |
| Eval runner | Python worker pool (asyncio) | Same as the minimal plan |
| Streaming traces | OpenTelemetry collector → ClickHouse | Industry standard; integrates with existing customer tooling |
| Frontend | React + Vite + Tailwind + recharts | The mock-up demands real UI — vanilla JS too low for this product |
| Auth | OIDC (Auth0 / Azure AD / Okta) | Multi-tenant from day 1 |
| Multi-tenant model | Row-level tenancy on `project_id` | SignalLayer hosts many tenants |
| Deployment target (open) | App Service · Container Apps · ECS · Lambda · local VM | TBD |

---

## 10. Build Phases — 9 weeks for v1 matching the mock-up

### Phase 1 — Core runs + suites (2 weeks)
- DB schema (Project, Env, Run, TestSuite, TestCase, Result)
- POST /api/v1/runs (ingest a run with cases + results)
- GET /api/v1/runs/{id} (detail with suites + cases)
- Minimal UI: Runs list + Run detail Overview tab (KPI strip + suite breakdown table + failure feed)
- Ingestion contract to assurance platform — first end-to-end pump

### Phase 2 — Traces + Trace View (1 week)
- OTel collector setup
- Trace ingestion → ClickHouse
- Trace View UI (user → retriever → tools → LLM → response tree)

### Phase 3 — Score Over Time + Drift Detection (1 week)
- ClickHouse materialized views for daily score rollups per suite
- Score Over Time line chart
- Drift Detection rule engine + alerts (Quality Signals)

### Phase 4 — Datasets + Scorers + Versioning (1 week)
- Dataset CRUD + versioning + signed approval workflow
- Scorer configs (deterministic, model_as_judge, human)
- Calibration pre-flight per the model-as-judge plan

### Phase 5 — Compare + Error Analysis (1 week)
- Diff view between two runs (which test cases regressed)
- Error clustering (group failures by reason / category)
- Top Failing Tests leaderboard

### Phase 6 — Governance: Policies / Guardrails / Approvals / Audit (1 week)
- Guardrail expressions (`critical_failures == 0`, `pass_rate >= 0.95`)
- Promotion approvals (who can ship a new dataset version)
- Audit log
- **Run-level** governance, distinct from the assurance platform's **workload-level** governance

### Phase 7 — Live Monitor + Alerts (1 week)
- Streaming evals against production traffic samples
- Real-time score thresholds → alerts to Slack / PagerDuty
- Live Monitor page

### Phase 8 — Settings: Integrations / Environments / Team / RBAC (1 week)
- OIDC SSO
- Team membership + roles
- Integration webhooks (GitHub Actions, Slack, PagerDuty, the assurance platform)

**Resources estimate:** 4 engineers part-time, or 1.5 full-time.

---

## 11. Run Lifecycle — What One Execution Does

1. **Pull spec** — Harness asks platform for the workload, intake, pinned eval-pack version, pinned golden versions.
2. **Resolve target** — From the intake, figure out what to actually call (a test endpoint, a Bedrock model, a Lambda).
3. **Provider routing decision** — For each eval category, consult the workload policy via `platform.assurance_providers.select(...)`. Refuse to run if config violates policy.
4. **Calibration pre-flight (judges only)** — Run judge against calibration set; abort with critical finding if agreement < threshold.
5. **Run cases** — Async pool. Each case: build prompt, call inference (via router decision), capture output, score (deterministic / judge / human), record latency + token count + provider + audit_id.
6. **Aggregate** — Roll up to per-category pass rates. Compare against thresholds.
7. **Emit events** — POST eval-run + N findings (one per failing case at minimum) + N evidence-items (input/output blobs hashed + stored).
8. **Archive artifacts** — Move local run dir to the evidence vault (S3 / Blob / local-WORM).
9. **Notify** — Platform's notification center auto-creates a notification on critical-finding ingestion.

---

## 12. Hard Constraints — bake in from day 1

1. **Provider routing is non-negotiable.** Harness must consult workload policy AND eval category metadata and refuse to send raw data to external LLMs. A failed policy check is a fatal error, not a soft skip.
2. **Determinism.** Pinned pack version + pinned golden version + fixed random seeds for fuzzers. Same `(pack@v, golden@v, target_endpoint_commit)` → same scores within variance bounds.
3. **HMAC + nonce + timestamp** on every event. Platform rejects replays older than 5 min.
4. **Idempotent ingestion.** Platform dedupes on `event_id`. Harness retries forever.
5. **No data leaves the trust boundary unless sanitized.** Even pack metadata — account IDs / ARNs in test cases must be tokenized before logging.
6. **Pack and goldens are immutable** per version. Harness pulls a pinned version. Newer versions require explicit promotion.
7. **Self-judging is banned.** Judge model cannot be the same model + version as the model under evaluation.
8. **Calibration is required for every judged run.** No "skip calibration" flag exists.

---

## 13. Open Decisions to Lock Before Scaffolding

| Decision | Options | Recommendation |
|---|---|---|
| Deployment target | App Service · Container Apps · ECS / Lambda · local VM | App Service for v1 (matches what we know) |
| Triggering | Cron only · Webhook only · All three (cron + webhook + manual CLI) | All three |
| Pack + golden storage | On the platform as JSONL · Separate git repo · Object storage | On the platform (consistent with existing pattern) |
| Multi-tenancy model | Single-tenant per Azure sub · Row-level tenancy in one DB | Row-level (cheaper, scales with sales) |
| Frontend stack | React + Vite + Tailwind · Vanilla JS like the platform | React + Vite + Tailwind (the screenshot demands it) |

---

## 14. Sequencing Plan

If you only build **one phase**: Phase 1 — it's the entire v1 pump and proves the contract.
If you build **three phases**: Phase 1 + 2 + 4 — gives you runs, traces, and versioned datasets/scorers. Enough for a real eval team.
If you build **the whole nine weeks**: ship Phase 1 to a customer in week 2 to validate the contract, then iterate the rest behind it.

---

## 15. Where to Start When You Pick This Up

1. **Read this doc end-to-end.**
2. **Freeze the data contract** (Section 3). Write the OpenAPI spec. Get sign-off from both teams.
3. **Build platform-side ingestion + read endpoints** (~half a day). Test with `curl`.
4. **Scaffold the harness repo.** Phase 1 only: FastAPI + Postgres + minimal Overview UI + ingestion to platform.
5. **Run a real eval against the AWS Analyzer workload** end-to-end. Confirm an `eval_run` event lands in the platform's findings + evidence.
6. **Demo to a stakeholder.** Get feedback before committing to Phases 2–8.

---

## Glossary

| Term | Definition |
|---|---|
| **Eval pack** | A versioned, signed manifest defining what evals run against a workload (categories, thresholds, golden refs, runner configs). Stored on the platform. |
| **Golden dataset** | A versioned, signed corpus of (input, expected output) test cases. Stored on the platform. |
| **Runner** | The execution engine for a category — `deterministic_regex`, `model_as_judge`, `human`, etc. |
| **Scorer** | A specific judge config — model + rubric + threshold + calibration set. |
| **Calibration set** | Human-labeled cases used to validate a judge agrees with humans before being trusted. |
| **Provider routing** | The platform's decision about which LLM provider can be called for a given (use_case, data_classes) tuple. |
| **Run** | One execution of an eval pack against a workload at a specific commit. |
| **Trace** | The span tree of a single inference (user → retriever → tools → LLM → response). |
| **Drift** | A statistically significant degradation in eval scores over time. |

---

**Authorship:** This plan was assembled across the AI Assurance Platform conversation on 2026-05-19. Source-of-truth lives in this file; future iterations should update it in place rather than fork.

**Reference UI:** See the in-conversation screenshot of the eval harness mock-up (Acme Corp branding, customer-support-agent-v2.4.1 run, dark theme matching this platform).

**Linked plans:**
- AWS Analyzer walkthrough: `docs/WALKTHROUGH-AWS-ANALYZER.md`
- App Service deploy failures (lessons for harness deployment): `~/.claude/projects/C--ai-assurance-mvp/memory/feedback_appservice_deploy_python.md`
