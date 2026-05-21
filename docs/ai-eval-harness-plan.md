# AI Eval Harness — Product Plan

**File:** `docs/ai-eval-harness-plan.md`
**Status:** Strategy / product plan. Not code.
**Supersedes:** [`docs/PLAN-EVAL-HARNESS.md`](PLAN-EVAL-HARNESS.md) (kept for historical context; the engineering-detail sections there are still valid, but this document is now the canonical product strategy).
**Date:** 2026-05-19

---

## 1. Product Thesis

**Evals are not the product. Reliability is the product.**

Every "AI eval tool" on the market today sells a prompt-testing dashboard. That's a feature, not a category. The actual category — the one that will produce the next Datadog, Snyk, or PagerDuty of AI — is **reliability, governance, and runtime trust infrastructure for production AI agents.**

The framing matters. A prompt-testing dashboard makes engineers feel good before they ship. **Reliability infrastructure keeps the agent honest after it ships** — when an agent is making refund decisions, reading IAM policies, writing customer responses, or coordinating with other agents. That's when the cost of being wrong stops being theoretical.

The thesis in one sentence:

> The same way Datadog became the substrate for software observability and Snyk became the substrate for shift-left security, we become the substrate for autonomous AI reliability — eval as one layer, trace as another, drift as another, policy enforcement as another, simulation and rollback as the top of the stack.

What we are not:

- Not a prompt-testing tool. That's commodity.
- Not a benchmark leaderboard. Public benchmarks don't tell anyone whether *their* agent works for *their* users on *their* data.
- Not a LangSmith clone. LangSmith is observability for LangChain. We're observability + governance + reliability for **any agent on any framework**.
- Not "generic observability with AI tags." Datadog will eventually add AI features. That's not what we are.

What we are:

> **AI reliability infrastructure for production agents.** The substrate that lets enterprises actually ship autonomous AI without losing sleep.

**Why now.** Autonomous agents are about to ship at scale. The 2024–2025 wave was copilots — humans in the loop, low-stakes assists. The 2026–2027 wave is agents — making decisions, calling tools, moving money, touching production systems. The pre-deploy eval frameworks of today (Braintrust, Patronus, Confident AI, Galileo, Promptfoo) are necessary but insufficient. The hole in the market is runtime: continuous testing against live traffic, drift detection across semantic dimensions, replay against past failures, policy enforcement before tool calls, rollback when SLAs breach.

---

## 2. Target Users

Five distinct personas. Each has a different job-to-be-done and a different UI mode. We **don't** try to be one screen for all five. We are a substrate with role-aware surfaces.

| Persona | Job-to-be-done | Primary surfaces they use |
|---|---|---|
| **AI Platform Teams** | "Don't let bad agent versions reach production." | CI gates, drift alerts, replay, rollback, deployment dashboard |
| **ML / LLM Engineers** | "Make this agent better than yesterday's version." | Run-to-run diff, prompt versioning, ablation studies, trace explorer |
| **Enterprise Risk + Compliance** | "Prove we governed this AI before it shipped." | Audit logs, evidence packages, policy gates, framework-mapped reports |
| **Security Teams** | "Find the adversarial failure before an attacker does." | Adversarial test packs, prompt-injection probes, exfil detection, red-team workflows |
| **Product Teams shipping agents** | "Roll out this new behavior without breaking customers." | Shadow testing, A/B routing, slow-rollout controls, customer-segment dashboards |

Implications for the product:

- One database, many views. The same `EvalRun` is rendered differently for an ML engineer (trace-deep, model-knob-rich) than for a risk officer (rolled-up, policy-mapped, evidence-attached).
- Multi-tenant + RBAC from day 1. Risk officers shouldn't see prompts; engineers shouldn't see legal opinions.
- Notifications are role-routed. A drift alert pages the platform team; a policy violation pages risk + security.

---

## 3. Core Modules

Twenty modules grouped by capability tier. Tier-1 ships in MVP; tier-4 ships when the category exists.

### Tier 1 — Foundation (MVP)

| Module | What it does | Why it matters |
|---|---|---|
| **Dataset management** | Versioned, signed test corpora with provenance. Append-only revisions; promotion requires approval. | Eval results are meaningless without a pinned dataset. This is the substrate everything else builds on. |
| **Multi-dimensional scoring** | Pluggable scorer interface: deterministic, model-as-judge, human, custom. Each case can carry multiple scores (accuracy, helpfulness, safety, cost). | Single-dimension scoring is what makes eval tools look like toys. |
| **Experiment tracking** | Run-to-run comparison. Diff which cases regressed when a prompt changed. | This is the loop ML engineers live in. |
| **Agent trace visualization** | Span tree explorer: user → retriever → tools → LLM → response. Per-span timing, tokens, cost, score. | Debugging an agent without a trace explorer is text-archaeology. |
| **Failure root-cause analysis** | Cluster failures by reason / category / shared tool / shared retrieval source. | Most failures are not random — they have structure. Surface the structure. |
| **CI/CD integration** | GitHub Action / GitLab / CircleCI: run eval pack on PR, post results, fail the build on regression. | Eval that doesn't gate releases is theater. |

### Tier 2 — Observability + Human Loop

| Module | What it does |
|---|---|
| **Human review workflows** | Reviewer queue, annotation tools, calibration sets, inter-rater agreement tracking. |
| **Production replay** | Rerun a prod trace (sanitized) against a candidate version. Did the change break it? Fix it? |
| **Shadow testing** | Route some % of prod traffic to a candidate model; score it offline; never affect the user. |
| **Trust scores** | Per-agent, per-version: rolling reliability score across all eval dimensions + production telemetry. The single number leadership asks for. |

### Tier 3 — Runtime + Drift

| Module | What it does |
|---|---|
| **Runtime drift detection** | Statistical change-detection on production scores, latency, tool-call patterns. Alert on regression before users complain. |
| **Alerting layer** | Routing rules → Slack / PagerDuty / email / webhook. Alert-quality feedback loop to suppress noise. |
| **Synthetic user generation** | Generate adversarial / realistic test inputs from production patterns. Continuous evolution of the test corpus. |

### Tier 4 — Governance + Safety

| Module | What it does |
|---|---|
| **Policy enforcement engine** | Runtime gate: agent cannot call tool X if policy Y is violated. Pre-call check, audit log, fallback path. |
| **Approval workflows** | Material changes (new dataset, new scorer, new agent version) require N approvers from M roles. |
| **Audit trails** | Append-only, signed, exportable. Includes every state change, every override, every approver signature. |
| **Compliance packs** | Pre-built mappings to NIST AI RMF, EU AI Act, ISO 42001, SOC 2, NYDFS, OCC SR 11-7. Auto-generated compliance reports. |
| **Adversarial testing** | Red-team-as-a-service: prompt injection, jailbreaks, ARN spoofing, role confusion, exfil probes. Curated attack pattern library + continuous generation. |

### Tier 5 — Advanced

| Module | What it does |
|---|---|
| **Action simulation sandbox** | Replica environment; agent's tool calls go to fakes; verify behavior without touching prod. The "staging environment" for agents. |
| **Auto-rollback** | SLA-breach detection → automatic revert to last-known-good version. With audit trail + on-call notification. |
| **Multi-agent coordination evals** | Test scenarios where multiple agents collaborate. Did they reach the right outcome? Did they leak info between roles? |
| **Economic optimization / model routing** | Per-request: pick cheapest model that meets quality bar. Continuous re-optimization as new models ship. |
| **Reliability SLAs** | Contractual uptime + accuracy + drift bounds. Credits when breached. The way enterprises buy reliability infrastructure. |

---

## 4. MVP Scope — Ruthlessly Cut

The MVP must answer one question for one persona: **"Can this prompt change ship?"** for the AI platform team.

Everything else is Phase 2+.

**In MVP:**

1. **Eval run management** — Create, list, view, rerun. One run = one execution of one eval pack against one agent version on one dataset version.
2. **Versioned datasets** — Upload, edit, sign, promote. Pinned to a run.
3. **Test suites** — Group test cases into named suites (General Quality, Tool Use, RAG, Safety, Factuality, Tone). Suite-level pass thresholds.
4. **Configurable scorers** — Three implementations from day 1: regex/deterministic, model-as-judge (with calibration), human (deferred-judgment).
5. **Trace capture** — OTel-compatible span ingestion. Trace explorer in the UI.
6. **Failure dashboard** — Failures table, severity buckets, category clustering, top-failing-tests list, example trace.
7. **CI/CD integration** — GitHub Action. Single setup: drop a YAML in `.github/workflows/`, get eval results in PR comments + build gate.
8. **Human review queue** — Reviewers can label, comment, override scores, calibrate the judge.
9. **Basic production replay** — Post-hoc: paste a prod trace, run it against a different agent version, see the diff. Not live shadow yet.

**Out of MVP (deferred to Phase 2+):**

- Live drift detection (Phase 3)
- Shadow testing routed to live traffic (Phase 3)
- Policy enforcement at runtime (Phase 4)
- Auto-rollback (Phase 5)
- Compliance packs (Phase 4)
- Action simulation sandbox (Phase 5)
- Synthetic user generation (Phase 3)
- Trust scores (Phase 2)
- Multi-agent coordination (Phase 5)

**Why this cut.** The MVP must replace the ad-hoc Python scripts every AI team currently maintains. If we ship that — runs, datasets, scorers, traces, CI, review queue — engineers will use it. Everything else is sales pull (drift for ops; policy for risk; replay for incident response; compliance for procurement).

**MVP success criterion.** Three internal teams replace their ad-hoc eval scripts with our harness within 30 days of GA. If two say "still feels easier to write a Python script," the MVP is wrong.

---

## 5. Architecture

```
                        ┌─────────────────────────────────────────────────┐
                        │              Customer / agent runtime            │
                        │                                                  │
                        │   ┌─────────────┐    ┌─────────────────┐         │
                        │   │  SDK (Py/TS)│    │ OTel collector  │         │
                        │   │  - log run  │    │  - traces       │         │
                        │   │  - log case │    │  - tool calls   │         │
                        │   └──────┬──────┘    └────────┬────────┘         │
                        │          │                    │                  │
                        └──────────┼────────────────────┼──────────────────┘
                                   │                    │
                                   ▼                    ▼
   ┌──────────────────────────────────────────────────────────────────────────┐
   │                          AI Reliability Platform                          │
   │                                                                           │
   │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │
   │  │  Ingestion   │  │  Eval runner │  │  Scorer      │  │  Policy      │ │
   │  │  API (FastAPI)│ │  (async pool)│  │  engine      │  │  engine      │ │
   │  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘ │
   │         │                 │                 │                  │         │
   │         ▼                 ▼                 ▼                  ▼         │
   │  ┌──────────────────────────────────────────────────────────────────┐   │
   │  │  Datastore — Postgres (entities) + ClickHouse (time-series +     │   │
   │  │  traces) + Object storage (artifacts, dataset blobs)             │   │
   │  └──────────────────────────────────────────────────────────────────┘   │
   │         │                                                                 │
   │         ▼                                                                 │
   │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                  │
   │  │  Dashboard   │  │  Alerting    │  │  Integrations│                  │
   │  │  (React)     │  │  layer       │  │  GitHub, Slack│                 │
   │  │              │  │              │  │  Datadog, etc.│                 │
   │  └──────────────┘  └──────────────┘  └──────────────┘                  │
   └──────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼ (pumps governance events)
                          ┌─────────────────────┐
                          │ Assurance Platform   │
                          │ (separate product)   │
                          └─────────────────────┘
```

### Component breakdown

| Component | Tech | Why |
|---|---|---|
| **SDK / API ingestion layer** | Python + TypeScript SDKs; FastAPI server | Thin, idempotent, HMAC-signed. SDK should be 5 lines to integrate. |
| **Eval runner** | Python 3.12 asyncio worker pool | Handles deterministic + judge + human scorers. Pulls eval-pack + dataset by version. |
| **Dataset store** | Postgres for metadata, object storage for case blobs | Postgres handles relations + revisions. Blobs scale linearly. |
| **Scorer engine** | Pluggable Python interface | Implementations: regex, model-as-judge (with calibration), human (queue), custom-callable. |
| **Trace store** | ClickHouse | Span queries are columnar workloads. Materialized views for drift detection. |
| **Policy engine** | Rule DSL → evaluable Python expressions | Same shape as the assurance platform's gate expressions. Reuse the contract. |
| **Dashboard** | React + Vite + Tailwind + recharts | Mock-up demands real UI. Vanilla JS is the wrong choice here. |
| **Alerting layer** | Webhook fanout + native Slack/PagerDuty | Alert-quality feedback loop critical (see Risks). |
| **Integrations** | First-class: GitHub Actions, Slack, Datadog, LangChain/LangGraph, OpenAI, Anthropic, Bedrock | These are where users already live. We meet them there. |

### Deployment

- **SaaS (default)** — multi-tenant on Azure or AWS, row-level tenancy, OIDC SSO.
- **Self-hosted** — Helm chart for k8s; Terraform module for AWS-native deploy. Required for FedRAMP / HIPAA / DPA-restrictive customers. Phase 4.
- **Hybrid** — control plane in SaaS, data plane in customer VPC. For teams that can't ship traces out. Phase 5.

---

## 6. Data Model

```
Organization
└─ Project
   ├─ Agent                       (the thing being evaluated; one agent = one git repo or one deployed service)
   │  ├─ ModelConfig              (model + provider + temperature + tokens; many per agent)
   │  └─ PromptVersion            (immutable; pinned by ModelConfig)
   ├─ Dataset                     (versioned; signed; promoted)
   │  └─ TestCase                 (input, expected, context, tags)
   ├─ TestSuite                   (named grouping of TestCases + suite-level thresholds)
   ├─ EvalRun                     (one execution at one commit against one dataset version)
   │  ├─ EvalResult               (per-case: score, passed, latency, tokens, cost, trace_id)
   │  ├─ Trace                    (span tree captured during the run)
   │  │  └─ ToolCall              (each tool invocation in the trace)
   │  ├─ Failure                  (auto-derived from failing EvalResults; severity + category)
   │  └─ ReviewerAnnotation       (human comments, score overrides, calibration labels)
   ├─ Policy                      (run-level gates: "no critical failures", "p95 latency < 3s")
   └─ Alert                       (configured rule + fired instances)
```

### Notes on the model

- **Organization → Project** is multi-tenant. Org is the billing + SSO boundary; Project is the work boundary.
- **Agent + ModelConfig + PromptVersion** decouples "what the agent is" from "what configuration we're testing." Lets you compare gpt-4o vs claude-3-5 on the same agent without forking the agent record.
- **Dataset is versioned and promoted.** Lower environments can use a draft version; production runs must use a promoted (signed) version.
- **EvalRun is immutable once started.** Results can be added; the run header (model, dataset, prompt versions, git commit) is frozen at run-start.
- **Trace is optional but recommended.** Many evals don't need traces (deterministic regex). But for any judge-based or production-replay eval, the trace is the forensic record.
- **Failure is derived, not authored.** When an EvalResult comes in failing above the severity threshold, the system creates the Failure record. Reviewers annotate; they don't create.

---

## 7. Roadmap

Five phases. Tight, time-boxed, with shippable value at the end of each.

### Phase 1 — Static eval harness (8–10 weeks)
**Goal:** Replace ad-hoc Python eval scripts.
**Modules:** Dataset management · Multi-dimensional scoring · Experiment tracking · Trace visualization (basic) · Failure root-cause clustering · CI/CD integration · Reviewer queue (basic) · Basic production replay.
**Demo win:** "Run our AWS analyzer through a real eval pack with a real CI gate and see the dashboard."
**Internal pilots:** 3 teams replace their scripts.

### Phase 2 — Trace observability + human review (8 weeks)
**Goal:** Become the place engineers debug agent failures.
**Modules:** Full trace explorer · Reviewer workspace (mobile-friendly) · Failure clustering (semantic) · Trust scores · Vertical packs (finserv, healthcare).
**Demo win:** "Click any failure → see the trace → see what the judge thought → annotate → trigger a re-run."
**External pilots:** First paying customers.

### Phase 3 — Runtime monitoring + replay (10 weeks)
**Goal:** Own production reliability.
**Modules:** Live production trace ingestion · Drift detection · Production replay (forward + back) · Shadow testing · Synthetic user generation · Alerting layer.
**Demo win:** "Drift detected on prod scores → alert in Slack → click → replay the regressed cases against the new candidate → fix."
**Outcome:** First customer ties production deploy gate to our drift signal.

### Phase 4 — Policy enforcement + governance (8 weeks)
**Goal:** Become the system-of-record for "did this AI ship safely."
**Modules:** Policy engine · Approval workflows · Audit log · Compliance packs (NIST AI RMF, EU AI Act, SOC 2, ISO 42001) · SOC 2 Type II readiness on our own platform · Self-hosted deployment option.
**Demo win:** "Generate the EU AI Act compliance report for this agent in one click."
**Outcome:** First enterprise procurement win.

### Phase 5 — Simulation + rollback + enterprise (12 weeks)
**Goal:** Set the bar for the category.
**Modules:** Action simulation sandbox · Auto-rollback · Adversarial testing (red team as a service) · Multi-agent coordination evals · Economic optimization / model routing · Reliability SLAs · Hybrid deployment (control plane SaaS, data plane in customer VPC).
**Demo win:** "Show me an agent we trained ourselves, evaluated, deployed, drifted, rolled back, and audited — without a human in any loop."
**Outcome:** Category leadership claim is defensible.

**Total horizon:** ~46 weeks for the full vision. **Phase 1 alone is shippable in 10 weeks** and replaces the in-house scripts customers maintain today.

---

## 8. Competitive Positioning

Direct comparisons. Be honest about where we overlap and where we win.

| Category | Examples | What they do well | Where we win |
|---|---|---|---|
| **Prompt testing** | PromptFoo, OpenAI Evals, DeepEval, RAGAS | Easy to start, open-source-friendly, dev-loop fast | Production monitoring · policy enforcement · governance · enterprise audit |
| **Eval platforms** | Braintrust, Patronus, Confident AI, Galileo | Real dashboards, judge support, dataset versioning | Runtime drift · replay · adversarial testing · multi-agent · compliance packs |
| **LangSmith / LangChain ecosystem** | LangSmith, LangFuse | Tight LangChain integration, trace UI | Framework-agnostic · policy gates · compliance · simulation |
| **Observability** | Datadog, Honeycomb, New Relic LLM module | Production telemetry maturity, broad integration footprint | Semantic understanding · drift on judged dimensions · governance overlay |
| **AI security / red team** | HiddenLayer, Lakera, Robust Intelligence | Deep adversarial expertise | Integrated with eval + governance · continuous (not point-in-time) · compliance-mapped |
| **AI governance** | Credo AI, Holistic AI, ModelOp | Compliance reporting, framework mapping | Wired to live eval + runtime data (their reports are mostly questionnaires) |

**The positioning statement we lead with:**

> "Prompt testing tools tell you if your agent passed today. We tell you if your agent is still safe to run tomorrow — and prove it to your regulator."

**The product category we are creating:** AI Reliability Infrastructure. Same shape as observability infrastructure (Datadog), shift-left security infrastructure (Snyk), and incident-response infrastructure (PagerDuty). We expect a category-defining outcome — not a feature added to an adjacent product.

**Defensibility logic:**
1. **Data network effect.** Every customer's evals improve our judge calibration sets, our adversarial pattern library, our drift baselines.
2. **Compliance lock-in.** Once a regulator accepts our compliance pack format, ripping us out is a multi-quarter regulatory exercise.
3. **Integration depth.** GitHub Action + Slack + Datadog + LangGraph + Bedrock + OpenAI + Anthropic in production — switching cost is real.
4. **Substrate position.** We are below the eval tool, below the governance tool, below the observability tool — we are the data layer. That's the Datadog playbook.

---

## 9. Risks

Honest list. Mitigations for each.

| Risk | Severity | Mitigation |
|---|---|---|
| **Scoring quality is hard.** Judge variance, calibration drift, false positives erode trust fast. | HIGH | Calibration sets are mandatory before any judge ships · n_samples ≥ 3 on critical · ensemble across providers · alert-quality scoring loop. |
| **Enterprise sales cycles.** SOC 2, FedRAMP, DPA negotiations slow everything. Phase 4 might gate revenue. | HIGH | Pull SOC 2 work into Phase 2 · pre-build the FedRAMP-readiness story · publish security posture early. |
| **OpenAI / Anthropic platform risk.** If they ship native evals + governance, half our wedge disappears. | HIGH | Multi-provider from day 1 · win on neutrality (compliance officers don't want to trust OpenAI to audit OpenAI) · win on depth (they won't build red-teaming or compliance packs for years). |
| **Generic evals commoditize.** Pass-rate dashboards trend to free. | MEDIUM | Lead with depth — trust scores, drift, replay, policy, simulation. Compete on the hard stuff. |
| **Vertical correctness is domain-specific.** A medical agent's "correct" is different from a payments agent's. | MEDIUM | Ship vertical packs (finserv, healthcare, legal) curated by domain experts in Phase 2–3. Don't try to be vertical-neutral. |
| **Noisy alerts destroy trust.** False positives mean teams turn off alerts. | MEDIUM | Alert-quality feedback loop: every alert prompts the user for "was this useful"; tune thresholds + suppress patterns. |
| **Single-tenant deploy expectations.** Many enterprises refuse SaaS. | MEDIUM | Support self-hosted (Helm + Terraform) from Phase 4. Don't promise hybrid until Phase 5. |
| **Model-as-judge is a moving target.** Judge models themselves drift, deprecate, get replaced. | MEDIUM | Pin judge model + version per rubric · re-calibrate quarterly · multi-family ensemble. |
| **We become a "yet another eval tool" in market perception.** | LOW-MEDIUM | Lead positioning with "reliability infrastructure" not "evals." Press, demos, customer language all reinforce this. |
| **Build-vs-buy at large enterprises.** Banks build their own. | MEDIUM | Make the build-side analysis painful: compliance packs + SOC 2 + framework mappings take years to assemble from scratch. We sell time-to-audit, not just code. |

---

## 10. Next Build Steps

Concrete, ordered, sized. Each step is one engineer for the listed duration.

| # | Task | Duration | Output |
|---|---|---|---|
| 1 | **Create repo structure** (`ai-reliability/`) — monorepo with `server/`, `web/`, `sdk-python/`, `sdk-typescript/`, `cli/`, `integrations/github-action/`, `docs/` | 0.5 day | Empty repo with directory README files and CI skeleton |
| 2 | **Define database schema** — Postgres migrations for Organization, Project, Agent, ModelConfig, PromptVersion, Dataset, TestSuite, TestCase, EvalRun, EvalResult, Trace, ToolCall, Failure, ReviewerAnnotation, Policy, Alert | 2 days | Alembic migrations + ER diagram in `docs/data-model.md` |
| 3 | **Build EvalRun CRUD** — FastAPI endpoints: POST/GET/list/rerun. Idempotent ingestion, HMAC auth | 3 days | Working `/api/v1/runs/*` endpoints with tests |
| 4 | **Implement scorer abstraction** — `Scorer` interface; three implementations: `RegexScorer`, `ModelAsJudgeScorer`, `HumanScorer` (queued) | 3 days | Scorer plugin registry; first eval runs against fixtures |
| 5 | **Add OpenAI / Anthropic / Bedrock runner adapters** — pluggable LLM client; provider routing per call (cost, latency, policy) | 2 days | Cross-provider eval runs working |
| 6 | **Build first dashboard** — React + Vite + Tailwind. Match the reference mock-up: Runs list + Run detail Overview tab (KPI strip, suite breakdown, failure feed, trace view) | 5 days | Browsable dashboard at localhost; first internal demo |
| 7 | **Add GitHub Action** — `signallayer/ai-reliability-action@v1`. Reads `.ai-reliability.yml`, runs eval pack, posts results to PR, gates the build | 2 days | Working Action; tested on our own repo's PRs |
| 8 | **Add trace capture** — OTel collector + ClickHouse + trace explorer UI | 4 days | Production traces ingested + viewable |
| 9 | **Implement reviewer queue** — UI for human annotation; calibration set tooling; score-override workflow | 3 days | Reviewers can label cases; calibration sets versioned |
| 10 | **Internal pilot** — run our own AWS analyzer (this repo's `aws_demo_flow.py` workload) through the new harness end-to-end | 2 days | First real run; events pumped into assurance platform; demo recorded |

**Total Phase 1 (MVP):** ~26 working days for one engineer; 8–10 calendar weeks with code review + iteration.

After step 10, do a hard internal review. Confirm three teams will adopt before building Phase 2.

---

## Appendix A — Definitions

| Term | Definition |
|---|---|
| **Eval pack** | A versioned, signed manifest defining what evals run against an agent (suites, thresholds, golden refs, scorer configs). |
| **Golden dataset** | A versioned, signed corpus of (input, expected output) test cases. |
| **Run** | One execution of an eval pack against an agent at a specific commit, with pinned dataset + scorer versions. |
| **Trace** | The span tree of a single inference (user → retriever → tools → LLM → response). |
| **Scorer** | A plug-in that produces a score for a (input, output) pair. Three families: deterministic, model-as-judge, human. |
| **Calibration set** | Human-labeled cases used to validate a judge agrees with humans before being trusted. |
| **Drift** | Statistically significant degradation in eval scores over time. |
| **Trust score** | Per-agent-version rolling reliability score across eval dimensions + production telemetry. |
| **Shadow testing** | Routing some % of production traffic to a candidate version, scoring offline, never affecting users. |
| **Replay** | Re-running a captured production trace against a different agent version to see the diff. |

---

## Appendix B — What we will deliberately not build

A list to come back to when something feels tempting:

- **A model training / fine-tuning UI.** Adjacent category. Hugging Face / Weights & Biases own it.
- **A prompt IDE.** Engineers use Cursor / Copilot.
- **A vector DB.** Adjacent category. Pinecone / Qdrant / pgvector own it.
- **A LangChain replacement.** We integrate with LangChain; we don't compete with it.
- **A customer-facing analytics dashboard for the AI agent's end-users.** That's the customer's product UX.
- **Generic APM.** Datadog owns latency / errors / hosts.
- **A chatbot.** Self-explanatory.

---

## Appendix C — One-page summary for execs

**The company:** AI reliability infrastructure for production agents.

**The wedge:** Replace the ad-hoc Python eval scripts every AI team currently maintains. Ship in 10 weeks.

**The expansion:** Production drift detection → policy enforcement → compliance reports → simulation + rollback. Sold per-agent, then per-org.

**The moat:** Data network effect + compliance integration + GitHub/Slack/CI integration depth + substrate position below eval/governance/observability.

**The risk:** OpenAI or Anthropic ship native evals. Mitigation: be multi-provider and lead on governance + reliability depth they will not match.

**The first revenue:** Phase 2 (Q + N weeks). First Fortune-500 deal in Phase 4.

**The category outcome:** Datadog-shaped — we are the substrate everyone runs on.
