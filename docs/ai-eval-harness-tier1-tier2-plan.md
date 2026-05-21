# AI Eval Harness — Tier 1 & Tier 2 Build Plan

**Scope:** The 9 features that midsize enterprise teams will actually pay for.
**Out of scope:** Tier 3 features (multi-tenant org hierarchy, marketplaces, prompt optimization, fine-tuning hooks, agent simulators). Defer until ≥10 paying customers.
**Companion to:** [`ai-eval-harness-plan.md`](ai-eval-harness-plan.md) (north-star). This doc is the ruthless cut.
**Status:** Planning. No code yet.
**Author target:** Praveen Kosuri / SignalLayer
**Date:** 2026-05-19

---

## 0. Operating Assumptions

- Hub-and-spoke architecture. Eval harness is a **separate product** that ingests data from the assurance platform via HMAC-signed endpoints. No shared database.
- Single builder for MVP. Sizing reflects one engineer, not a team.
- Substrate choice: **Postgres + JSONB for everything** in Tier 1/2. No ClickHouse, no OTel collector, no Kafka. Add them when a customer's data volume forces it, not before.
- Auth: **Entra ID (Azure AD) SSO from day one.** Local password auth only for the seed admin.
- Hosting: Azure App Service Linux Python 3.12 (matches existing platform).
- Frontend: vanilla JS + server-rendered HTML to start (matches platform). Defer React/Vite until UI complexity demands it.
- Customer boundary rule (inherited from platform): **raw production traces never leave the customer's network without sanitization.** Sanitizer runs at SDK level, not at ingestion.

---

## 1. The Thirteen Features

| # | Feature | Tier | Phase | Effort (days) | Blocking? |
|---|---|---|---|---|---|
| F1 | Production trace capture + PII redaction at SDK | 1 | P1 | 8 | Yes |
| F2 | Regression detection on model/prompt changes | 1 | P1 | 5 | Yes |
| F3 | Audit-ready evidence export | 1 | P2 | 4 | Yes |
| F4 | Human-in-the-loop review queue + inter-rater agreement | 1 | P2 | 6 | Yes |
| F5 | RBAC + Entra SSO | 1 | P1 | 3 | Yes |
| F6 | Cost + latency tracking | 2 | P2 | 3 | No |
| F7 | Golden dataset versioning + drift detection | 2 | P3 | 5 | No |
| F8 | Side-by-side run comparison | 2 | P2 | 4 | No |
| F9 | Policy-as-code release gates | 2 | P3 | 5 | No |
| **F10** | **RAG eval pack (retrieval quality + context relevance + faithfulness)** | **1** | **P1** | **5** | **Yes** |
| **F11** | **Model-as-judge scoring runner (calibrated, multi-provider)** | **1** | **P1** | **4** | **Yes** |
| **F12** | **Guardrails scorer adapter (NeMo / Llama Guard signals)** | **1** | **P2** | **2** | **No** |
| **F13** | **Custom metric SDK hook + plugin interface** | **2** | **P2** | **2** | **No** |
| **F14** | **Two-way pipe — platform pushes Garak/NeMo/adversarial results into harness** | **1** | **P1** | **3** | **Yes** |

**Total: 59 working days for one engineer.** Realistically 12–14 calendar weeks with buffer.

**Phase definitions:**
- **P1 (Weeks 1–5):** Foundation + scoring. SDK, ingestion, auth, trace store, regression detection, **model-as-judge runner, RAG scorers, two-way pipe**. Without these, F2 is empty plumbing.
- **P2 (Weeks 6–9):** First customer-ready. Evidence export, review queue, cost tracking, run comparison, guardrails adapter, custom metric SDK.
- **P3 (Weeks 10–12):** Stickiness. Dataset versioning, policy-as-code gates.

---

## 2. Feature Specs

### F1 — Production Trace Capture + PII Redaction at SDK

**Why it matters:** Single biggest blocker to enterprise adoption. CISO will not approve a tool that sends raw prompts/responses to a vendor backend.

**Scope (in):**
- Python SDK (`pip install signallayer-eval`) with a `@trace` decorator and a `trace_call(prompt, response, metadata)` function
- Built-in redactors: regex (SSN, email, phone, credit card, AWS ARN), spaCy NER (PERSON, ORG, GPE), custom regex hook
- Reversible token map stored in customer-controlled location (local file, S3 bucket, or Azure Storage account the customer owns)
- Redaction happens **before** the HTTP POST to ingestion
- Failure mode: if redaction fails, drop the trace and log locally. Never ship raw.

**Scope (out):**
- Node.js / Go / Java SDKs (defer to P4)
- LLM-based redaction (token cost too high for production volume)
- Automatic de-anonymization in the UI (customer holds the key; we never see raw)

**Success criteria:**
- 1M trace ingests/day on a single App Service P2V3 instance
- Redaction round-trip <50ms p95
- Zero PII leakage in a 10K-sample audit by a third party

**Dependencies:** None. Build first.

**Watch out for:** spaCy model size (en_core_web_lg is 750MB). Use en_core_web_sm + regex layering for SDK; reserve large models for in-boundary analysis workers.

---

### F2 — Regression Detection on Model/Prompt Changes

**Why it matters:** This is what makes engineers actually wire up the SDK. Without it, you're a write-only dashboard.

**Scope (in):**
- Every `EvalRun` is tagged with `model_version`, `prompt_version`, `dataset_version`, `commit_sha`
- On each new run, auto-compare against the last 5 runs on the same dataset
- Compute deltas per metric (factuality, hallucination, latency, cost)
- Statistical significance: paired bootstrap, n=1000 resamples (don't trust t-tests on metric distributions)
- Alert thresholds: >5% absolute drop OR >2σ from rolling mean → fire
- Delivery channels: Slack webhook, GitHub PR comment (via GitHub App), email fallback

**Scope (out):**
- Multi-metric composite scores (too easy to game; engineers ignore them)
- Auto-rollback (customer policy decision, not ours)
- Time-series anomaly detection (Phase 2+ when ClickHouse arrives)

**Success criteria:**
- PR comment appears within 60s of eval run completion
- False positive rate <10% on a 30-day backtest with internal data
- ≥3 engineers across ≥2 teams say "this caught something I would have shipped"

**Dependencies:** F1 (need traces to compare against).

**Watch out for:** Comparing across different dataset versions is meaningless. Refuse to compare if `dataset_version` differs; surface "no comparable baseline" instead of a wrong number.

---

### F3 — Audit-Ready Evidence Export

**Why it matters:** This is what Risk & Compliance pays for. Your assurance platform already produces this shape — port the pattern.

**Scope (in):**
- One-click export from any `EvalRun` or `AIWorkload`
- Bundle contents: eval results JSON, failure samples (sanitized), reviewer sign-offs, model/prompt/dataset versions, timestamps, control mappings
- Output formats: PDF (executive summary) + ZIP of JSON+CSV (raw evidence)
- Control mappings out-of-box: NIST AI RMF (GOVERN/MAP/MEASURE/MANAGE), EU AI Act Annex IV, SR 11-7, ISO 42001, OWASP LLM Top 10
- Each control mapped to specific eval categories + thresholds
- SHA-256 hash of bundle stored in DB for integrity verification

**Scope (out):**
- Custom control framework builder (Phase 3)
- Auto-submission to GRC tools (Phase 3 integration work)
- E-signature workflows (use existing GRC for this)

**Success criteria:**
- A risk officer at a design-partner bank says "this is the document I would hand to an examiner" without edits
- Export completes in <30s for runs up to 10K test cases
- Bundle is reproducible: same inputs → identical hash

**Dependencies:** F1, F2 (need data to export). F4 (need reviewer sign-offs).

**Watch out for:** PDF generation libraries are a swamp. Use WeasyPrint with strict HTML templates. Do not let business logic creep into the PDF layer.

---

### F4 — Human-in-the-Loop Review Queue + Inter-Rater Agreement

**Why it matters:** Without this, model-as-judge scores are unfalsifiable and Risk won't accept them. This is the calibration layer that makes everything else credible.

**Scope (in):**
- Auto-route eval failures to a review queue based on category + severity
- Reviewer UI: see prompt, response, model verdict, original score; submit label + rationale
- Inter-rater agreement: Cohen's kappa per reviewer pair, Krippendorff's alpha across the panel
- Calibration set: 50–100 hand-labeled gold cases per category; every reviewer scored against it on signup + monthly
- Drift detection: reviewer's agreement with gold drops >10% → flag for re-calibration
- Sample size per failure: minimum 2 reviewers if severity ≥ HIGH, 1 otherwise

**Scope (out):**
- Reviewer marketplace (Scale.ai / Surge.ai integration — Phase 3)
- Active learning loop (Phase 4)
- Reviewer payment/tracking infrastructure (customer's HR system handles this)

**Success criteria:**
- Average review time per failure <90s
- Inter-rater agreement (κ) ≥0.7 on calibration set across panel
- Model-as-judge calibrated against human panel achieves >0.85 agreement with majority human label

**Dependencies:** F1 (failures to review).

**Watch out for:** Reviewer fatigue. Cap queue depth per reviewer at 50/day; force breaks. A tired reviewer is worse than no reviewer.

---

### F5 — RBAC + Entra SSO

**Why it matters:** Day-one requirement. Midsize enterprise procurement dies on auth gaps.

**Scope (in):**
- Roles: Admin, Engineer, Reviewer, Risk, Read-Only
- Entra ID (Azure AD) via OIDC; Okta via OIDC as second provider
- Group → role mapping (Entra group "AI-Engineers" → Engineer role)
- Permission matrix enforced at API layer (not just UI)
- Audit log: every privileged action (export, policy edit, reviewer assignment) logged with user ID, timestamp, before/after diff

**Scope (out):**
- Fine-grained per-project ACLs (Phase 3)
- SCIM provisioning (Phase 3 — most midsize don't need it)
- Custom role definitions (use the 5 defaults until a customer complains)

**Success criteria:**
- SSO round-trip <2s
- Zero auth-related findings in a third-party security audit
- A new user can be onboarded by adding them to an Entra group; no admin action in our app

**Dependencies:** None. Build alongside F1.

**Watch out for:** Storing access tokens server-side. Don't. Use short-lived sessions + refresh from IdP.

---

### F6 — Cost + Latency Tracking

**Why it matters:** Finance asks "what does this AI cost us per transaction." If you can't answer in 2 clicks, you lose the renewal.

**Scope (in):**
- SDK captures: input tokens, output tokens, model name, latency
- Cost computation: token counts × per-model price table (refreshed quarterly)
- Aggregation: cost per eval run, per agent, per customer transaction, per day/week/month
- Dashboard: cost trend line, cost-per-call distribution, top 10 most expensive agents
- Anomaly alert: 24h spend >2× 7-day rolling mean → notify Finance role
- Budget alerts: per-agent monthly cap, configurable per workload

**Scope (out):**
- Multi-currency (USD only for v1; convert in customer's BI tool)
- Bedrock cost modeling beyond on-demand pricing (Provisioned Throughput is Phase 3)
- Predictive cost forecasting (Phase 3)

**Success criteria:**
- Cost accuracy within 3% of actual provider bill on a 30-day reconciliation
- Finance can answer "what's our AI cost this quarter" in one click
- Anomaly alert fires within 4h of spike start

**Dependencies:** F1 (trace metadata includes tokens).

**Watch out for:** Provider price changes silently. Build a "price table updated YYYY-MM-DD" stamp and surface it in the UI. Stale prices are a credibility-killer.

---

### F7 — Golden Dataset Versioning + Drift Detection

**Why it matters:** This is the data-network-effect flywheel. Customers who curate datasets in your tool can't easily leave.

**Scope (in):**
- Datasets are versioned (semver: 1.0.0, 1.1.0). Every test case has a stable ID.
- Drift detection: scan production traces weekly, cluster failures, surface "12 production cases not in golden set"
- One-click "promote to golden" with reviewer approval (uses F4)
- Dataset diff view: what changed between v1.2.0 → v1.3.0
- Dataset coverage map: per-category, per-risk-tier, per-domain breakdown

**Scope (out):**
- Synthetic data generation (Phase 3 — too easy to get wrong; users distrust it)
- Cross-customer dataset sharing (privacy minefield; defer indefinitely)
- Auto-promotion (always require human in the loop for golden set changes)

**Success criteria:**
- ≥3 customers add ≥10 production-derived cases per month
- Average golden set freshness <30 days
- A customer can roll back to any prior dataset version in <1 click

**Dependencies:** F1, F4 (reviewer approval for promotions).

**Watch out for:** Clustering algorithms are sensitive to embedding model choice. Pin the model + version; don't auto-upgrade. Reproducibility >freshness.

---

### F8 — Side-by-Side Run Comparison

**Why it matters:** This is the workflow engineers actually use 5×/day. Make it fast and they'll never leave.

**Scope (in):**
- Pick any two runs → diff view
- Per-test-case: same/better/worse/new/missing
- Failure clustering: group by failure type (hallucination, refusal, format error, off-topic)
- Filter by category, severity, dataset subset
- Export comparison as CSV or PNG (for PR comments)
- Permalink to share specific comparisons

**Scope (out):**
- N-way comparison beyond 2 (cognitive overload; engineers don't actually use it)
- Real-time diff during run (compute post-completion only)
- Automated "winner" declaration (humans interpret; we don't decide)

**Success criteria:**
- Diff renders in <2s for runs up to 10K test cases
- ≥80% of weekly active engineers use this feature
- Engineers report "I check this before every prompt PR"

**Dependencies:** F1, F2.

**Watch out for:** Long test cases (multi-turn agent traces) blow up the UI. Truncate by default, expand on click.

---

### F9 — Policy-as-Code Release Gates

**Why it matters:** This is how you become substrate, not a dashboard. Once policies live in customer repos and gate CI, switching cost is high.

**Scope (in):**
- YAML policy files committed to customer repo
- Policy language: simple boolean expressions over metrics
  ```yaml
  gates:
    - name: hallucination_rate
      expression: "hallucination_rate < 0.02"
      severity: blocking
      applies_to: ["agents/billing-*"]
    - name: pii_leakage
      expression: "pii_leak_count == 0"
      severity: blocking
      applies_to: ["*"]
  ```
- CLI: `signallayer-eval gate check --run-id X` → exit 0/1
- GitHub Action + Azure DevOps Pipeline templates
- Override workflow: blocked release requires Risk role approval + reason logged in audit trail

**Scope (out):**
- Full DSL with custom functions (use Python plugin hooks if needed)
- Visual policy builder (engineers prefer YAML; product managers don't write policies)
- ML-based "smart gates" that auto-tune thresholds (unfalsifiable; defer)

**Success criteria:**
- A customer blocks a real production release because of a gate failure within 60 days of install
- Policy evaluation <500ms
- Override requires multi-party approval (Risk role + audit log entry)

**Dependencies:** F1, F2, F5 (RBAC for overrides).

**Watch out for:** Gate fatigue. If gates fire too often, engineers will route around them. Start with 2–3 critical gates, expand carefully.

---

### F10 — RAG Eval Pack

**Why it matters:** The platform's AWS analyzer + most enterprise AI runs on RAG. AI Systems on the platform carry `rag_enabled` and `rag_sources` fields. Without RAG-specific scorers, the harness can't credibly evaluate the majority of production agents.

**Scope (in):**
- SDK extension: `trace_rag_call(query, retrieved_chunks, response, expected=None)` — captures the retrieval step separately from generation
- Retrieval-quality scorers:
    - **precision@k** — how many of top-k retrieved chunks are in the ground-truth set
    - **recall@k** — how many ground-truth chunks made it into top-k
    - **MRR (Mean Reciprocal Rank)** — rank position of first relevant chunk
    - **NDCG@k** — normalized discounted cumulative gain (handles graded relevance)
- Generation-quality scorers (model-as-judge via F11):
    - **Context relevance** — are the retrieved chunks actually relevant to the query? (0–1)
    - **Answer faithfulness** — is the answer grounded in the retrieved context, or hallucinated? (0–1)
    - **Context utilization** — did the answer use the retrieved context, or ignore it? (0–1)
- Eval pack template: `rag-default-v1.yaml` (off-the-shelf RAG eval suite)
- UI: dedicated RAG metrics panel on run detail page (separate from "model quality" panel)

**Scope (out):**
- Embedding-model-specific eval (let customers pick their embedder)
- Vector store benchmarking (we eval the agent's RAG, not the underlying infra)
- Auto-tuning chunk size / top-k (customer's job)

**Success criteria:**
- A RAG agent scored on all 7 metrics in <60s for 100-case dataset
- Retrieval metrics match RAGAS reference implementation within 1% on a canonical test set
- A customer running a RAG eval can say "this told me my retriever sucked, not my prompt"

**Dependencies:** F1, F11 (model-as-judge runner for faithfulness/relevance scorers).

**Watch out for:** Ground-truth labels for retrieval metrics are expensive to generate. Provide a fallback "judge-graded relevance" mode where the model labels chunk relevance — flag the score as approximate when this mode is used.

---

### F11 — Model-as-Judge Scoring Runner

**Why it matters:** F2 (regression detection) assumes scorers exist. F10 (RAG eval) requires judge scorers. F4 (review queue) calibrates against the judge. Without an explicit, calibrated, multi-provider judge runner, none of those features work.

**Scope (in):**
- Scoring runner: `score_run(run_id, scorer_config)` → writes per-result scores to `eval_results.score` JSONB
- Built-in scorers:
    - `factuality` — claim verification against expected output
    - `hallucination_detect` — flag content not grounded in context
    - `relevance` — answer-to-question relevance
    - `pii_leak` — detect PII in output (regex + judge)
    - `refusal` — detect inappropriate refusal
    - `format_compliance` — output matches expected JSON/schema
- **Multi-provider routing** via existing platform `domain/assurance_providers.py` pattern — judge can be Anthropic, OpenAI, or Bedrock based on workload's sensitivity classification
- **Self-judging ban** — system enforces that the judge model ≠ the model under test (configurable override for cost-sensitive deployments, logged in audit)
- **n_samples ≥ 3 by default** at temperature=0 with majority vote for robustness
- **Calibration set integration** — every scorer has a gold-labeled calibration set; report judge-vs-gold agreement on every run; flag drift >10%
- Async execution: judge calls run in parallel (asyncio.gather), respecting rate limits per provider

**Scope (out):**
- Fine-tuning custom judges (Phase 3 — too operationally heavy)
- Ensemble of multiple judges (one judge + n_samples is sufficient; ensembles increase cost 3× for marginal gains)

**Success criteria:**
- Judge-vs-human agreement ≥ 0.85 (κ) on a 50-case calibration set per scorer
- 1000-case run scored in <5 minutes (parallelism + caching)
- Self-judging warning fires when configured judge = model under test
- Audit log captures: scorer config, judge model + version, n_samples, calibration score, cost

**Dependencies:** F1 (results to score). Platform's `assurance_providers.py` (provider routing).

**Watch out for:** Judge prompts drift silently. Version-control every scorer prompt; require a re-calibration run when the prompt changes; refuse to use a scorer whose calibration is >30 days old.

---

### F12 — Guardrails Scorer Adapter

**Why it matters:** The platform already integrates NeMo Guardrails. The harness should consume those signals as scorer outputs, not rebuild guardrail logic.

**Scope (in):**
- Adapter that runs NeMo Guardrails (input + output rails) against each test case
- Optional Llama Guard integration as a second adapter
- Scorer outputs:
    - `input_safety` — pass / fail per input rail (jailbreak, prompt injection, off-topic)
    - `output_safety` — pass / fail per output rail (toxicity, PII leak, policy violation)
    - `safety_score` — composite 0–1
- Per-rail breakdown in eval results
- UI: safety panel on run detail page with rail-level pass/fail breakdown

**Scope (out):**
- Building custom guardrails (use the platform's NeMo config; don't fork)
- Real-time guardrails enforcement in production (that's the platform's job, not the harness's)

**Success criteria:**
- Same guardrails config in platform + harness produces identical pass/fail decisions
- 100 test cases evaluated in <30s
- Customers can point the adapter at their existing platform NeMo config (path or URL)

**Dependencies:** F1, F11 (some rails use judge models). Existing platform NeMo integration.

**Watch out for:** Version skew between platform NeMo config and harness adapter version. Pin the config hash; refuse to run if hashes mismatch.

---

### F13 — Custom Metric SDK Hook

**Why it matters:** Without a plugin interface, the harness is a closed system. Engineers will need custom domain-specific scorers (e.g., "SQL query equivalence", "diagnosis code accuracy", "regulatory citation correctness") — if they can't add them, they'll work around the harness.

**Scope (in):**
- Python plugin interface:
  ```python
  from signallayer_eval import Scorer, ScoreResult

  class SQLEquivalenceScorer(Scorer):
      name = "sql_equivalence"

      async def score(self, test_case, output) -> ScoreResult:
          # Customer's logic — anything goes
          return ScoreResult(value=0.85, label="pass", metadata={...})

  # Register in eval pack YAML:
  # scorers:
  #   - type: custom
  #     module: my_company.scorers.SQLEquivalenceScorer
  ```
- Plugin discovery via `signallayer_eval.scorers` entry point in customer's `pyproject.toml`
- Sandboxing: plugins run in the harness process (no isolation in v1; document trust model)
- 1 worked example: a "JSON schema compliance" scorer in the SDK examples
- Documentation: how to write, register, and test a custom scorer

**Scope (out):**
- Plugin marketplace (Tier 3)
- Hot-reload of plugins (require restart in v1)
- Wasm / RPC sandbox isolation (v3 if security-sensitive customers demand it)

**Success criteria:**
- A customer ships their first custom scorer in <2 hours from docs read to passing test
- Custom scorers appear in run detail UI alongside built-ins, indistinguishable in presentation

**Dependencies:** F11 (Scorer base class shared with built-in scorers).

**Watch out for:** Customer scorers will leak memory / hang / make external calls. Wrap every call in a timeout (default 30s) and a memory cap; surface failures as scorer errors, not run failures.

---

### F14 — Two-Way Pipe (Platform → Harness)

**Why it matters:** The platform already has Garak adversarial testing, NeMo guardrails runs, multi-provider routing audit, and a workload registry. Rebuilding these in the harness is waste. The pipe-back goes both ways.

**Scope (in):**
- Reverse-direction ingestion endpoints on **harness** side:
    - `POST /api/ingest/platform-adversarial-result` — Garak run results from platform
    - `POST /api/ingest/platform-guardrail-eval` — NeMo guardrail eval results from platform
    - `POST /api/ingest/platform-provider-audit` — provider routing decisions (which model handled which call)
- Harness ingests these into the same `eval_results` table with `source=platform` flag
- Trace correlation: if platform's adversarial run references a harness `agent_id`, the results link to that agent's run history
- UI: separate filter/badge for "platform-sourced" results vs harness-native; both contribute to regression detection and findings
- HMAC scheme: identical to harness → platform, opposite direction (platform signs, harness verifies)

**Scope (out):**
- Real-time streaming (batched ingest is fine for v1; sub-second sync is v3)
- Bidirectional eval-pack synchronization (manual export/import in v1)

**Success criteria:**
- Platform-side Garak run completes → result appears in harness run history within 60s
- Harness regression detection (F2) flags drift on platform-sourced adversarial scores
- A unified "all eval results for ai-sys-001" view shows both harness and platform results

**Dependencies:** F1 (trace store), F2 (regression). Platform-side outbound HMAC client (small addition to platform).

**Watch out for:** Schema drift between platform's Garak output format and harness's `eval_results.score` shape. Define a strict envelope at the ingestion boundary; never let platform format leak into harness domain logic.

---

## 3. Build Sequence (Week-by-Week)

```
Week 1   F1 (start)  + F5 (parallel: SSO + RBAC scaffold)
Week 2   F1 (finish) + F5 (finish)
Week 3   F11 (model-as-judge runner — calibrated, multi-provider)
Week 4   F10 (RAG eval pack — uses F11)
Week 5   F2 (regression detection — uses F11 scorers) + F14 (two-way pipe)
                            ── P1 Milestone: ingestion + scoring + regression + two-way pipe ──
Week 6   F8 (run comparison) + F6 (cost tracking — parallel)
Week 7   F4 (start: review queue UI + data model)
Week 8   F4 (finish: inter-rater agreement) + F12 (guardrails adapter, parallel)
Week 9   F3 (evidence export) + F13 (custom metric SDK hook, parallel)
                            ── P2 Milestone: design-partner ready ──
Week 10  F7 (dataset versioning + drift)
Week 11  F9 (policy-as-code gates)
Week 12  Buffer / polish / smoke / deploy
                            ── P3 Milestone: full v1 shipped ──
```

**Critical path:** F1 → F11 → F10 → F2 → F4 → F3. Don't parallelize; downstream features need upstream data shapes locked.

**Parallelizable:**
- F5 alongside F1 (different stack)
- F14 alongside F2 (both build on F1's ingestion contract)
- F6 alongside F8 (both UI work)
- F12 alongside F4 (one is API/adapter, the other is UI)
- F13 alongside F3 (orthogonal areas)

---

## 4. Data Model (Minimum Viable)

Single Postgres database, JSONB columns where flexibility >performance.

```
organizations          (id, name, entra_tenant_id, created_at)
users                  (id, org_id, entra_oid, email, role, created_at)
projects               (id, org_id, name, repo_url)
agents                 (id, project_id, name, model_provider, model_name)
prompt_versions        (id, agent_id, version, content_hash, content, created_at)
datasets               (id, project_id, name, version, content jsonb, created_at)
eval_runs              (id, agent_id, prompt_version_id, dataset_id, commit_sha,
                        status, metrics jsonb, started_at, completed_at)
eval_results           (id, run_id, test_case_id, output, score jsonb, failure_category)
traces                 (id, agent_id, prompt_redacted, response_redacted, tokens_in,
                        tokens_out, latency_ms, cost_usd, metadata jsonb, captured_at)
failures               (id, trace_id OR result_id, severity, category, status)
review_assignments     (id, failure_id, reviewer_id, status, label, rationale, submitted_at)
calibration_scores     (id, reviewer_id, dataset_id, agreement_kappa, scored_at)
policies               (id, project_id, content_yaml, version, created_at)
gate_evaluations       (id, run_id, policy_id, passed, blocking_failures jsonb)
evidence_bundles       (id, run_id, sha256, generated_at, generated_by)
audit_log              (id, user_id, action, target_type, target_id, before jsonb,
                        after jsonb, occurred_at)
```

**14 tables. That's it.** Resist adding more until a feature demands it.

---

## 5. What This Plan Deliberately Excludes

- **Tier 3 features:** Multi-tenant org hierarchy beyond org→project, custom dashboards, scheduled runs, marketplace, prompt optimization, fine-tuning hooks, agent simulators, A/B testing infrastructure.
- **Non-Python SDKs:** Node/Go/Java arrive in Phase 4 only if ≥3 customers block on them.
- **ClickHouse / OTel / Kafka:** Postgres handles 10M traces/month per customer comfortably with proper indexing. Defer until that breaks.
- **React frontend:** Vanilla JS + server-rendered HTML is enough for 50 customers. Rewrite when complexity demands.
- **Multi-region / DR:** Single region (eastus) until a customer's procurement blocks on it.
- **Self-hosted offering:** SaaS only. Self-hosted is a Phase 4+ decision and changes everything about the build.

---

## 6. Success Metrics (90 Days Post-MVP)

- **3 design partners** running production traces through F1 daily
- **≥1 regression caught** by F2 that would have shipped without the tool
- **≥1 evidence bundle** delivered to a real auditor or examiner via F3
- **Inter-rater agreement (κ) ≥0.7** on F4 panel
- **<5% false positive rate** on F2 alerts (measured weekly)
- **Zero PII leakage incidents** in F1 redaction
- **≥1 customer** has policies in F9 blocking real releases

If 5 of 7 hit, the product has PMF signal. If <3 hit, rethink positioning before building Tier 3.

---

## 7. Open Decisions (Need User Input Before Build)

1. **Where does the customer's reversible token map live?** Customer-managed S3/Azure Storage vs. our managed KMS-encrypted store. Recommend customer-managed for trust; harder UX.
2. **Pricing model:** Per-trace, per-eval-run, per-seat, or flat tier? This shapes the data model (per-trace requires precise counting from day one).
3. **Single-tenant vs. shared multi-tenant for MVP:** Single-tenant per customer is easier to sell to enterprise but expensive to operate. Shared is cheaper but enterprise will push back on data isolation.
4. **GitHub App vs. webhook for F2 PR comments:** App is more user-friendly but requires marketplace listing + maintenance burden. Webhook is uglier but faster to ship.
5. **F4 reviewer compensation:** Are reviewers customer-employees (no payment infra needed) or paid third parties (need integration with Scale/Surge)? Assumption above is the former.

---

## 8. Where to Start

If picking this up cold, do these in order:

1. Stand up the repo: `signallayer/eval-harness` with FastAPI + Postgres + uv-managed Python 3.12
2. Build the `eval_runs` + `traces` + `users` tables (skeleton schema)
3. Build the SDK skeleton: `pip install signallayer-eval` → `trace_call()` → POST to `/ingest/trace` with HMAC
4. Wire Entra SSO via `msal` library; protect all routes with a session middleware (port the pattern from the assurance platform)
5. Add regex-based PII redactors in the SDK; defer spaCy until v0.2
6. Build the regression detection cron: nightly job that scans new runs, computes deltas, fires Slack webhook
7. Stop. Show to 3 prospective design partners. Iterate before building F3–F9.

Do not skip step 7. Building F3–F9 without design-partner contact is how this becomes a museum piece.

---

## Appendix A — Effort Sizing Sanity Check

| Feature | Days | Reality Check |
|---|---|---|
| F1 | 8 | SDK + redaction + reversible token map + ingestion endpoint. Tight but doable. |
| F2 | 5 | Statistical bootstrap is ~1 day; alert plumbing is ~2; Slack/PR integration ~2. |
| F3 | 4 | WeasyPrint templates + control mapping table. Mostly content work. |
| F4 | 6 | Review UI is ~3 days; agreement math is ~1; calibration loop is ~2. |
| F5 | 3 | Entra OIDC via msal is well-trodden. |
| F6 | 3 | Price table + aggregations + dashboard. |
| F7 | 5 | Versioning is easy; drift clustering needs careful embedding pipeline. |
| F8 | 4 | UI-heavy. Diff algorithm is trivial; rendering 10K cases isn't. |
| F9 | 5 | YAML parser + CLI + GitHub Action template + override workflow. |
| F10 | 5 | Retrieval metrics (1d) + judge-graded RAG scorers via F11 (2d) + RAG UI panel (1d) + eval pack template (1d). |
| F11 | 4 | Scorer base class (1d) + 6 built-in scorers (2d) + multi-provider routing + calibration integration (1d). |
| F12 | 2 | NeMo adapter (1d) + Llama Guard adapter (0.5d) + UI panel (0.5d). |
| F13 | 2 | Scorer base class (already in F11) + entry-point discovery + worked example + docs. |
| F14 | 3 | 3 reverse ingestion endpoints (1.5d) + correlation logic (0.5d) + UI badge/filter (0.5d) + platform-side outbound HMAC client (0.5d). |

Total: **59 days.** Add 30% buffer = **~77 calendar days = 12–14 weeks** for one engineer.

---

## Appendix B — Anti-Goals

These are tempting and wrong:

- **Building a beautiful UI before the SDK works.** No SDK = no data = no UI value.
- **Supporting every model provider on day one.** Pick OpenAI + Anthropic + Bedrock. Add others when paid.
- **Custom DSL for policies.** YAML + Python plugins is enough. DSLs are graveyards.
- **Auto-fixing failures.** Detection only. Remediation is the customer's job; pretending otherwise destroys trust.
- **Model-as-judge without calibration.** Unfalsifiable scores destroy the product's credibility. F4 is non-negotiable for shipping F2 at scale.
