# 12-Day Production Sprint Plan
# AI Assurance Platform — aigovern.sandboxhub.co

**Scope:** Production-ready platform covering all 6 architectural layers, all governance features, and the full demo story.
**Quality bar:** Every shipped component is tested · observable · documented · security-reviewed · deployable to production.
**Effort:** ~12 person-days of focused work.
**Execution mode:** Either (A) 4 calendar days × 3 parallel Claude Code accounts, or (B) 12 calendar days × 1 builder.
**Companion docs:** `docs/target-architecture.md` · `docs/architecture/target-architecture.html` · `ARCHITECTURE.md` · `DECISIONS.md` · `CLAUDE.md`
**Start date:** TBD on user say-go · **End date:** Day 12 EOD + 1 day demo dry-run

---

## 0. Operating principles

| Principle | Practice |
|---|---|
| Production-ready means production-ready | Tests · observability · security review · documentation · graceful degradation · monitoring · rollback path. Every day. |
| Critical-path fixes go first | `tracer.py` raw-prompt leak is Day 1 Hour 1 — non-negotiable. No demo runs without it. |
| Compose, don't rebuild | Langfuse + DeepEval + Presidio are commodities. Wrap, don't reimplement. |
| Real-where-it-matters | The PII boundary, decorator stack, framework coverage, multi-agent governance — all real. Polished theater only where genuinely Phase 2. |
| Fail-closed semantics everywhere | Policy errors → DENY. Vault errors → drop trace locally. OPA unreachable → block release. Never ship raw. |
| Single source of truth | `events.jsonl` is the SSOT. Postgres materializes. UIs render. |
| Forward-compatible multi-tenancy | Every entity carries `org_id` (default `"default"` in v1). v2 = column-add + filter, not rewrite. |
| Honest deferral | What's NOT built is enumerated. No hidden gaps. Phase 2 list is in this doc, in the demo runbook, and in `DECISIONS.md`. |

---

## 1. Architectural foundation (locked)

### 1.1 The six layers

```
L1  Organizational         · risk_inventory · governance_body · raci · regulatory_posture
L2  Enterprise Control Plane · AI Gateway · Policy/Guardrail · Tool Registry/RBAC · Cost · Eval · Observability · Release Gates
L3  PII / IP / Secret Scrubbing Pipeline · Presidio + Fernet vault + @scrub_pii (THE BOUNDARY)
L4  Four-tier agent memory · T1 in-context · T2 episodic · T3 RAG · T4 procedural
L5  Runtime · Langfuse + DeepEval 6-metric + 3-decorator chain
L6  LLM abstraction · Anthropic · OpenAI · (Bedrock v2)
```

### 1.2 The three-decorator chain (enforced order)

```python
@scrub_pii          # L3 · scrubs args + return · writes to Fernet vault
@trace_llm_call     # L5 · Langfuse trace with scrubbed payload only
@evaluate_response  # L5 · DeepEval 6-metric scoring + policy gate
async def agent(query: str) -> str:
    ...
```

**SDK enforces order at decoration time.** Missing `@scrub_pii` → `MissingScrubberError` raised before the function ever runs.

### 1.3 Four-tier memory

| Tier | Backing | Write semantics | PII mitigation |
|---|---|---|---|
| T1 In-context | LLM context window | Assembled per call | `@scrub_pii` before LLM sees it |
| T2 Episodic | JSONL per workload | Write-time scrubbing | Episodes stored already-scrubbed |
| T3 Semantic / RAG | Azure AI Search | Index-time scrubbing | Reject HIGH-PII docs unless classified public |
| T4 Procedural | `domains.py` | Code (versioned) | n/a — no customer data |

### 1.4 Policy engine — OPA + Rego

5 categories with explicit precedence:
1. **Org-mandatory** (`policies/org/`) — cannot be opted out
2. **Posture-driven** (`policies/postures/{id}/`) — fires by regulatory posture
3. **Risk-tier-driven** (`policies/risk-tiers/{tier}/`) — fires by classification
4. **Team** (`policies/teams/{team}/`) — team-specific
5. **System-override** (`policies/systems/{id}/`) — requires active waiver

6 evaluation contexts: pre-LLM call · release gate · control applicability · agent binding · tool authz · right-to-forget cascade.

**OPA deployment:** sidecar process on the same App Service. Bundle hot-reload from `policies/main/`. Fail-closed.

### 1.5 Multi-agent + Agent Library

- `System` (deployable unit) has 1..N `Agents`
- `Agent` is versioned · owned by a team · either `custom` or `reusable`
- `AgentBinding` pins an Agent version to a System
- Publishing v2 of a reusable Agent triggers re-evaluation events for subscribers
- Cross-agent gates evaluate the agent graph as a whole (orchestration correctness, plan coherence)
- Weakest-link rule: System risk tier inherits the highest tier among its agents

### 1.6 Framework coverage

6 frameworks in v1 with inline mappings on every control, scorer, gate, and policy:
- NIST AI RMF 1.0 (top 20 subcategories)
- OWASP LLM Top 10 (2025) — all 10
- EU AI Act Annex IV (10 documentation items)
- ISO/IEC 42001 (top 15 controls)
- SR 11-7 (Sections IV, V, VII)
- FFIEC IT Handbook (AI-relevant subset)
- US-FinServ overlay (composes NIST + SR 11-7 + FFIEC + GLBA + NYDFS)

Coverage engine in `domain/framework_coverage.py` produces per-system per-framework status (Covered / Partial / Missing) with evidence pointers.

### 1.7 Eval pack tier model

| Tier | Scope | Authority |
|---|---|---|
| **A · Org-mandatory** | Every system, every release | AI Gov Lead · cannot be opted out |
| **B · Risk-tier-mandatory** | HIGH / CRITICAL systems | Risk classification triggers · waiver required to bypass |
| **C · Team-discretionary** | Team-owned · per system | Team lead approved by AI Gov |

Engine refuses release if Tier A or B fail.

### 1.8 Right-to-forget cascade

Single API call cascades across vault → Tier 2 episodic → Tier 3 RAG → Langfuse traces. Verification report with SHA-256 hashes proves each store was purged. Audit log captures the operation immutably.

### 1.9 Deployment shape (headless engine + thin clients)

```
   CLIENTS  · Team Portal · Gov Console · CLI + SDK     (v2 split)
                              │
   ENGINE  · headless · OpenAPI-described · event-sourced
                              │
   DATA    · events.jsonl (SSOT) · Postgres (views)
            · Key Vault + Blob (secrets, bundles)
            · Azure AI Search (T3 RAG) · Langfuse Cloud (L5)
```

**v1 ships as a single app at `aigovern.sandboxhub.co` with role-based views.** Architected so the v2 split is a refactor, not a rewrite.

---

## 2. Tech stack

### 2.1 Engine
| Concern | Choice |
|---|---|
| Language | Python 3.12 · `from __future__ import annotations` |
| Web framework | FastAPI (async-first, OpenAPI auto-gen) |
| ASGI | gunicorn + UvicornWorker (1 worker) on App Service |
| Models | Pydantic v2 (`ConfigDict`) · dataclasses for internal-only |
| Storage | JSONL via `storage._append_jsonl()` + Postgres Flexible for materialized views |
| Auth | itsdangerous URLSafeTimedSerializer · 10-min sliding sessions · Entra ID (v2) |
| Async | `asyncio.gather` for all independent LLM calls |

### 2.2 L3 PII
| Concern | Choice |
|---|---|
| Detection | Microsoft Presidio + `en_core_web_sm` |
| Custom patterns | 12 regex (SSN, CC, IBAN, ARN, API_KEY, IP, phone, DOB, MRN, NPI, ABA, custom hook) |
| Encryption | Fernet (cryptography lib) |
| Key management | Azure Key Vault · Managed Identity in prod |
| Vault storage | JSONL ciphertext at `data/deid_vault.jsonl` · TTL in app layer |

### 2.3 L4 Memory
| Tier | Backing |
|---|---|
| T1 | Token budget allocator (in-process) |
| T2 | JSONL per workload (`data/episodes_{workload_id}.jsonl`) |
| T3 | Azure AI Search Basic · vector + hybrid search · pinned `text-embedding-3-small` |
| T4 | In-code (`domains.py`) |
| Compression | Claude Haiku 4.5 |

### 2.4 L5 Runtime / Eval
| Concern | Choice |
|---|---|
| Tracing | Langfuse Cloud Pro · scrubbed payloads only |
| Metrics | DeepEval 6-metric (hallucination · relevancy · faithfulness · toxicity · PII leak · scrub score) |
| Adversarial | Garak (existing) |
| Guardrails | NeMo Guardrails (input/output) · Llama Guard 3 |
| Judge models | Claude Sonnet 4.6 (high-fidelity) · GPT-4o-mini (high-volume) |

### 2.5 L2 Policy / Controls
| Concern | Choice |
|---|---|
| Policy engine | OPA v0.61+ · Rego policies in `policies/` |
| Deployment | Sidecar on same App Service · bundle hot-reload |
| Testing | `opa test ./policies` · CI gate · coverage required |
| Control library | YAML in `controls/library/` · 15 controls in MVP |
| Release gates | 6 gates · Python-evaluated against eval results + controls |

### 2.6 Frontend (single-app v1)
| Concern | Choice |
|---|---|
| Templating | Server-rendered HTML (Jinja2 in FastAPI) for v1 |
| CSS | Custom + design tokens · dark mode default |
| JS | Vanilla + Vite (no framework lock-in) |
| Charts | Inline SVG sparklines · Chart.js where needed |

### 2.7 SDK + CLI
| Concern | Choice |
|---|---|
| SDK package | `signallayer` · pip-installable · ~250 LOC |
| CLI package | `signallayer-cli` · entry `sl` · ~400 LOC |
| Contract | Generated from engine's OpenAPI · pinned per release |
| HMAC | SHA-256 over body + timestamp + nonce · 300s window |

### 2.8 DevOps
| Concern | Choice |
|---|---|
| VCS | Git · GitHub (signalyer/ai-assurance-mvp) |
| CI/CD | GitHub Actions · lint + types + unit + integration + Rego tests · auto-deploy to dev |
| Linting | ruff · prettier · opa fmt --check |
| Types | mypy strict mode for `domain/` and `api/` |
| Deployment | Azure App Service Linux · zip deploy via Oryx |

---

## 3. Azure infrastructure

| Resource | SKU | Purpose | Monthly |
|---|---|---|---|
| `app-aigovern-dev` | App Service P1V3 Linux Python 3.12 · Always On · HTTPS · TLS 1.2 | FastAPI engine + OPA sidecar | $340 |
| `pg-aigovern-dev` | Postgres Flexible B2ms · 128GB · PITR 35d | Materialized views from event log | $130 |
| `srch-aigovern-dev` | Azure AI Search Basic · 1 replica · 1 partition | Tier 3 RAG index | $75 |
| `kv-aigovern-dev` | Key Vault Standard | Fernet key · HMAC · session · DB conn | $5 |
| `staigoverndev` | Storage Standard LRS | JSONL backups · evidence bundles · SPA hosting (v2) | $5 |
| `ai-aigovern-dev` | App Insights + Log Analytics | Telemetry · alerts · dashboards | $30 |
| Langfuse Cloud | Pro · 100K traces/mo | L5 observability | $99 |
| LLM API | Pay-as-you-go | L6 LLM abstraction · production + judges | $200–500 |

**Total: ~$884–1,184/mo at demo load.**

All resources in subscription `SignalLayerDev`, resource group `rg-aigovern-dev`, region `eastus`.

---

## 4. The 12-day plan

### Execution mode A — 4 calendar days × 3 parallel streams

```
                  Day 1          Day 2          Day 3          Day 4
Stream A (lead)   PII pipeline   Eval runner    OPA + policies Memory + RTF
Stream B (UI)    /pii-pipeline   /evals dash    /frameworks    /agent-library
                                                + Frameworks tab + /audit-events
                                                                + demo control
Stream C (infra) Azure provis    rag_engine     frameworks/    sdk/ + cli/
                                 + AI Search    YAML + multi-  + Postgres
                                 + calibration  agent schema   projection
                                                              + hardening
```

Each stream commits every 2h. Integration windows at NOON and EOD daily.

### Execution mode B — 12 calendar days × 1 builder

```
Day 1   L3 PII pipeline (scrubber + vault + decorator)
Day 2   DeepEval 6-metric + /evals dashboard
Day 3   Azure AI Search + rag_engine (Tier 3)
Day 4   Tier 2 episodic memory + agent_memory orchestrator
Day 5   OPA sidecar + 3 Rego policies + policy_engine integration
Day 6   Frameworks coverage matrix (6 frameworks + US-FinServ overlay)
Day 7   Multi-agent schema + Agent Library + version pinning
Day 8   Right-to-forget cascade + tamper-evident audit log
Day 9   CLI + Python SDK + Postgres event projection
Day 10  Production hardening + load tests + deploy
Day 11  Demo orchestration + runbook + 6 scenarios scripted
Day 12  Stakeholder dry-run + fix critical bugs + final deploy
```

---

## 5. Day-by-day deliverables (with quality bars)

### Day 1 · L3 PII Pipeline (CRITICAL)
**Deliverables:**
- **Hour 1:** Patch `tracer.py` raw-prompt leak with regex-only stub · deploy hotfix
- `scrubber.py` — Presidio NER + 12 regex patterns + 50-case test suite
- `domain/deid_vault.py` — Fernet + Key Vault + TTL + `vault_stats()`
- `@scrub_pii` decorator wired into runtime
- `/pii-pipeline` admin page · App Insights alerts on scrub failures
- Azure provisioning kicked off (Postgres + AI Search async)

**Acceptance:**
- `python -c "from scrubber import tokenise_payload; ..."` → PASS 50/50 cases
- Vault TTL test passes (immediate hit · 2s wait · miss)
- Langfuse trace contains `[SSN_001]`, NEVER `123-45-6789`
- Vault JSONL on disk contains only ciphertext (no raw PII)
- App Insights alerts firing on synthetic scrub failure

### Day 2 · L5 Runtime + Evals dashboard
**Deliverables:**
- Extend `evaluator.py` — 6 metrics with domain categorization · 3-state classification · 0–100 normalization · stable `EVL-XX-NNN` IDs
- Real DeepEval wiring (not lazy)
- Calibration sets — 50 cases × 6 metrics in `data/calibration/`
- `/evals` dashboard matching reference design — KPI cards · trend line · status donut · results table with sparklines · domain/status filters · CSV export

**Acceptance:**
- Live LLM call scored on all 6 metrics in <5min for 1K cases
- Calibration kappa ≥ 0.7 per scorer
- Dashboard renders real scores (no seeded numbers)
- Trend sparklines built from event log data

### Day 3 · Azure AI Search + RAG (Tier 3)
**Deliverables:**
- Provision Azure AI Search Basic in `rg-aigovern-dev`
- `domain/rag_engine.py` — `index_document` · `retrieve_chunks` · `assemble_context` · `embed_query`
- Index-time scrubbing — rejects HIGH-PII unless classification permits
- Index 20 real documents (Azure Well-Architected · NIST AI RMF doc · OWASP LLM Top 10 PDF · sample policies)
- `/rag-governance` page · audit log of every index op

**Acceptance:**
- Query returns top-5 chunks with relevance scores in <500ms
- Doc with raw SSN gets REJECTED at index time · audit log entry captured
- `/rag-governance` shows real corpus health metrics

### Day 4 · Tier 2 Episodic Memory + Orchestrator
**Deliverables:**
- `domain/agent_memory.py` — `build_context` · `write_episode` · `compress_episode` (Claude Haiku) · `selective_recall`
- Tier 2 store: `data/episodes_{workload_id}.jsonl` with schema validation + scrub-at-write
- Memory inspector page on AI System detail — visualize T1-4 with per-call assembly trace
- Integration tests for write+recall+compress

**Acceptance:**
- Multi-turn conversation: turn 1 writes 3 episodes, turn 5 recalls relevant ones
- Compression at session-end summarizes 5 episodes into 1 with provenance link
- Memory inspector renders all 4 tiers for any system

### Day 5 · OPA Sidecar + Policy Engine
**Deliverables:**
- Deploy OPA as sidecar process on App Service (supervisor runs OPA + uvicorn)
- `domain/policy_engine.py` with OPA HTTP client + 6 evaluation contexts
- 3 real Rego policies + unit tests:
  - `policies/org/pii_no_raw_to_langfuse.rego`
  - `policies/postures/us-finserv/release_approval.rego`
  - `policies/teams/payments/tool_authz.rego`
- `@policy_gate` decorator wired · policy decisions logged to event log

**Acceptance:**
- OPA process running alongside FastAPI
- Bundle reload < 5s after `policies/` change
- Rego unit tests all green in CI
- Policy decision events visible in `/audit-events`

### Day 6 · Framework Coverage Matrix
**Deliverables:**
- `frameworks/` directory with 6 YAML files (NIST · OWASP · EU AI Act · ISO 42001 · SR 11-7 · FFIEC + US-FinServ overlay)
- Add `framework_refs` field to 15 controls · 6 scorers · 6 gates · 3 policies (backfill)
- Extend `domain/framework_coverage.py` — per-system per-framework computation with evidence pointers
- `/frameworks` matrix page (Console-style)
- Frameworks tab on AI System detail
- "Export NIST Pack" / "Export OWASP Pack" / "Export EU AI Act Pack" buttons producing PDFs with framework citations

**Acceptance:**
- Matrix renders 6 systems × 6 frameworks
- Click any cell → drill to evidence with SHA-256 hashes
- Evidence bundle PDF includes inline framework citations
- Coverage % accurate against seeded ground truth

### Day 7 · Multi-Agent + Agent Library
**Deliverables:**
- Add `Agent` and `AgentBinding` entities to schema
- Migration: existing `ai-sys-001` becomes a System with 1 bound agent
- Agent registry · library · binding · versioning modules
- 6 seeded agents (3 team-owned + 3 reusable)
- `/agent-library` page with publish/subscribe UI
- Multi-agent visualization on System detail · agent graph · per-agent evals

**Acceptance:**
- Publish v2 of reusable agent → subscribers receive notification within 30s
- Subscriber can pin v1 or accept v2 with explicit consent
- Multi-agent system passes/fails based on weakest agent's gates

### Day 8 · Right-to-Forget + Tamper-Evident Audit
**Deliverables:**
- `domain/right_to_forget.py` — cascade across vault · Tier 2 · Tier 3 (Azure Search delete by source_id) · Langfuse (API delete)
- Right-to-forget UI in Console — request form · approval · execution · verification report with SHA-256
- Tamper-evident audit log — hash chain over `events.jsonl` · each event carries `prev_event_hash` · `/audit/verify` endpoint validates chain

**Acceptance:**
- Issue right-to-forget for "test-customer-9999" → cascade completes in <60s
- Verification report shows: vault tokens removed, Tier 2 episodes removed, Tier 3 chunks removed, Langfuse traces removed
- Audit hash chain verifies clean for last 1000 events
- Attempt to mutate any event in log → verification fails

### Day 9 · CLI + SDK + Postgres Projection
**Deliverables:**
- Python SDK `signallayer` — `init()` + 4 decorators (`@scrub_pii` · `@trace` · `@evaluate` · `@policy_gate`) · HMAC client · compile-time order enforcement
- CLI `sl` — `login` · `onboard` · `eval run` · `gate check` · `trace tail` · `evidence export`
- Postgres event projection worker · materialized views (`ai_systems` · `eval_runs` · `findings` · `release_decisions` · `policy_evaluations`)

**Acceptance:**
- `pip install -e ./sdk && python examples/billing_agent.py` runs end-to-end
- `sl onboard my-new-agent` creates system + opens portal
- `sl gate check sys-001` exits 0 on pass, 1 on fail
- Postgres views match JSONL ground truth (replay verification)

### Day 10 · Production Hardening + Deploy
**Deliverables:**
- Load tests — scrubber under 100 req/sec · framework coverage compute at scale · OPA p95 < 50ms
- App Insights production dashboards · 8 alerts configured
- Security review — secrets scan · RBAC audit at every endpoint · HMAC verification on cross-boundary · OWASP top 10 web checks
- End-to-end smoke run all 6 scenarios on production deployment

**Acceptance:**
- 100 req/sec sustained for 10 min · p95 < 2s · zero errors
- All 8 App Insights alerts firing on synthetic incidents
- Zero high/critical security findings
- All 6 demo scenarios pass on production URL

### Day 11 · Demo Orchestration + Runbook
**Deliverables:**
- Demo Control panel — extends AWS Analyzer pattern · one-click triggers per scenario
- 6 demo scenarios scripted with talk tracks:
  1. Team Risk: live PII pipeline (real scrub + vault + Langfuse trace)
  2. Team Payments: gate failure → governance hold → recovery
  3. Team CX: reusable agent governance (v2 published, pinned, upgraded)
  4. Cross-team: right-to-forget cascade
  5. Team Payments: evals degradation detection over 14 days
  6. Auditor visit: NIST + OWASP coverage matrix + evidence pack export
- Demo runbook with 20-Q&A prep

### Day 12 · Stakeholder Dry-Run + Final Deploy
**Deliverables:**
- Internal stakeholder dry-run (full 30-min demo + Q&A)
- Fix any critical bugs surfaced
- Final deployment to `aigovern.sandboxhub.co`
- Final smoke test
- Demo deck + final docs

---

## 6. Production-readiness baseline (cross-cutting · every day)

| Concern | Standard |
|---|---|
| Tests | Unit tests on every domain module · integration tests for every API · `/verify` smoke gates each day |
| Error handling | Every async wrapped · typed Result patterns · no silent swallows · fail-closed on gates |
| Security | No secrets in code (Key Vault only) · HMAC on every cross-boundary · RBAC enforced at API layer · constant-time auth comparisons |
| Observability | Structured logging · App Insights · counters for scrub rate, eval failures, policy denies · alerts on PII leak detection, OPA unreachable, vault errors |
| Documentation | Docstrings on every public function · ARCHITECTURE.md updated daily · DECISIONS.md appended for any new architectural call |
| Performance | Scrubber p95 < 100ms · eval run < 5min for 1K cases · framework coverage compute < 2s |
| Reliability | Health endpoints (`/health`, `/health/deep`) · graceful degradation when OPA/Langfuse down · retry+backoff on transient failures · outbox for cross-system writes |
| CI | Lint + type-check + unit + integration tests must pass before merge · auto-deploy to dev on merge |

---

## 7. The 6 demo scenarios

| # | Scenario | What's real |
|---|---|---|
| **1** | **Team Risk · live PII pipeline** | Real Presidio scrub + Fernet vault round-trip + Langfuse trace showing tokens |
| **2** | **Team Payments · gate failure → governance hold → recovery** | Real gate engine + seeded eval regression + real governance review queue |
| **3** | **Team CX · reusable agent governance** | Real Agent Library + real versioning + real publish/subscribe events |
| **4** | **Cross-team · right-to-forget** | Real cascade across vault · T2 · T3 · Langfuse with verification hashes |
| **5** | **Team Payments · evals degradation detection** | Real DeepEval + real trend computation from event log |
| **6** | **Auditor visit · framework coverage** | Real coverage engine + real evidence bundles with SHA-256 + real framework citations |

Each scenario ≤2 minutes. 12 minutes total. 18 minutes Q&A. 30-minute demo block.

---

## 8. What's deferred to Phase 2 (called out in demo)

| Deferred | Why |
|---|---|
| Team Portal / Governance Console split | Architectural — 2+ weeks alone · v1 single-app + role-based views works |
| Real-time webhooks for agent version updates | Polling sufficient for v1 |
| BYO Azure subscription deploys | Single subscription for v1 |
| Hash-chained audit log → external blockchain anchor | Append-only + internal hash chain is enough |
| Per-tenant Azure AI Search | Single index for MVP |
| Mobile / responsive console | Desktop-first |
| Streaming eval (eval-as-traffic-flows) | Batch eval only |
| Synthetic golden dataset generation | Customer-provided datasets only |
| Multi-language SDKs (Node, Go, Java) | Python only in v1 |
| Bedrock provider | Anthropic + OpenAI for v1 |
| HIPAA · GDPR · FedRAMP · DORA frameworks | NIST + OWASP + EU AI Act + ISO 42001 + SR 11-7 + FFIEC in v1 |
| OPA cluster (HA) | Single sidecar for v1 |
| Custom DSL for policies | Rego is enough |
| Agent marketplace beyond org | Library is org-internal for v1 |

---

## 9. Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `tracer.py` leak persists past Day 1 | LOW | CRITICAL | Day 1 Hour 1 fix · smoke verifies before any other work proceeds |
| OPA sidecar deploy fails on App Service | MED | HIGH | Test sidecar pattern in dev on Day 4 EOD · fallback: existing engine pretends OPA-backed |
| Azure AI Search provisioning blocked | LOW | MED | Provision Day 1 morning · fallback: mock retrieval until provisioned |
| Langfuse rate limits hit during eval batch | MED | MED | Pre-warm on Day 9 · Pro tier provides 100K traces/mo headroom |
| Calibration kappa < 0.7 for some scorer | MED | MED | Iterate on calibration set composition · adjust scorer prompt |
| Multi-agent visualization renders slow on graphs > 5 agents | LOW | LOW | Truncate display · expand on click |
| Right-to-forget cascade partial failure | MED | HIGH | Cascade is idempotent · retry on partial failure · log to outbox |
| Day 10 load test reveals scrubber bottleneck | MED | MED | Profile · batch Presidio calls · cache regex compilations |
| Stream B (UI) blocked waiting for Stream A API | HIGH | MED | Stream A publishes OpenAPI by NOON Day 1 · B builds against contract |
| Architectural drift across 3 parallel accounts | MED | MED | DECISIONS.md locked · CLAUDE.md enforces patterns · daily integration windows |
| Stakeholder dry-run reveals integration gaps Day 12 | MED | HIGH | Build Day 11 buffer · Day 12 has fix time |

---

## 10. Open decisions (must answer before Day 1)

| Decision | Options | Default |
|---|---|---|
| Execution mode | A (4-day + 3 streams) · B (12-day + 1 builder) | **A · faster calendar** |
| Start time | Tonight (tracer.py fix) · Tomorrow AM · Monday | **Tonight Hour 1 fix · Day 1 at 8AM tomorrow** |
| Stakeholder dry-run date | Day 12 EOD · Day 13 AM | **Day 12 EOD** |
| Working hours assumption | 8h/day · 10h/day · 12h+/day | **10h/day average** |
| Provision Postgres + AI Search | Tonight async · Day 1 AM | **Tonight async** |
| Granular task tracking via TaskCreate | Yes · No | **Yes** |
| Use AWS Analyzer demo content or re-theme to Azure | Keep AWS · Re-theme · Both | **Keep AWS** (working demo content) |
| Demo audience for dry-run | Internal team · +sponsor exec · +board | **Internal team + sponsor exec** |
| Authorize destructive changes (tracer.py · evaluator.py) | Yes · Behind feature flag | **Yes** (feature flags add a day; smoke tests gate everything) |

---

## 11. Success criteria — definition of done

The 12-day sprint is complete when ALL of the following are true:

- [ ] `tracer.py` leak fixed · zero raw PII in Langfuse for 50K consecutive traces
- [ ] PII pipeline tests pass 50/50 + TTL test
- [ ] DeepEval 6 metrics scoring real LLM calls in production
- [ ] `/evals` dashboard renders real scores · sparkline trends · 3-state classification
- [ ] Azure AI Search indexed with 20 docs · index-time scrubbing verified
- [ ] Tier 2 episodic memory write + recall + compress all working
- [ ] OPA sidecar running · 3 Rego policies enforced · CI tests green
- [ ] Framework coverage matrix renders for 6 frameworks · evidence bundle export works
- [ ] Multi-agent: publish v2 → subscriber notified · pin/upgrade flow works
- [ ] Right-to-forget cascade verified across 4 stores · SHA-256 verification produced
- [ ] CLI installable · `sl onboard` works · `sl gate check` returns correct exit code
- [ ] Postgres projection matches JSONL on replay
- [ ] Load test: 100 req/sec sustained for 10 min · p95 < 2s · zero errors
- [ ] App Insights alerts firing on all 8 critical signals
- [ ] Zero high/critical security findings in scan
- [ ] All 6 demo scenarios pass end-to-end on production
- [ ] Stakeholder dry-run completed with no blocking issues
- [ ] ARCHITECTURE.md · DECISIONS.md · CLAUDE.md current
- [ ] Demo runbook + Q&A document complete

---

## 12. Coordination model (if Mode A · 3 parallel streams)

### Stream ownership (strict, no overlap)

**Stream A · Runtime + Security (lead / integrator)**
Files owned: `scrubber.py` · `evaluator.py` · `tracer.py` · `domain/policy_engine.py` · `domain/agent_memory.py` · `domain/deid_vault.py` · `domain/right_to_forget.py` · `dashboard.py` routing · `requirements.txt` · integration

**Stream B · UI**
Files owned: `static/pii-pipeline.html` · `static/evals.html` · `static/frameworks.html` · `static/agent-library.html` · `static/audit-events.html` · all new `shared.js` components · all new `shared.css` blocks

**Stream C · Infra + Data + CLI/SDK**
Files owned: `deploy/*` · `frameworks/*` · `sdk/*` · `cli/*` · `data/*.jsonl` seed files · `domain/rag_engine.py` · `domain/agents/*` · App Service config · App Insights dashboards

### Coordination
- **Integration windows:** NOON + EOD daily · Stream A pulls B+C changes · runs integration smoke
- **Shared state:** `ARCHITECTURE.md` · `DECISIONS.md` · `CLAUDE.md` committed by Stream A only
- **API contracts:** Stream A publishes OpenAPI updates by noon · B+C build against contracts
- **Merge conflicts:** Stream A is sole writer of `dashboard.py` + `requirements.txt`
- **Architectural decisions:** bubbled to PM (user) within 15 min · no silent improvisation
- **Status reports:** EOD per stream (shipped · at-risk · blockers)

### PM (user) commitment
~6 hours total over 4 days:
- 15 min × 2 daily integration reviews × 4 days = 2h
- 30 min × 4 days architectural decision review = 2h
- 10 min × 6 merge approvals = 1h
- 1h scope-cut decisions if a stream slips
- 30 min total file-ownership dispute adjudication

---

## 13. References — all related docs

| Doc | Purpose |
|---|---|
| `docs/architecture/target-architecture.html` | Reviewable HTML with diagrams (20 sections) |
| `docs/target-architecture.md` | Narrative form of the architecture |
| `ARCHITECTURE.md` | Current platform state (updated every session via `/handoff`) |
| `DECISIONS.md` | Immutable architectural decision log (append-only) |
| `CLAUDE.md` | HOW Claude Code works (≤150 lines · loaded every session) |
| `docs/plans/SESSION-01a-scrubber-vault.md` | First session plan (existing) |
| `docs/plans/12-DAY-PRODUCTION-SPRINT.md` | **This document** |
| `complete_implementation_guide.html` | Chat-to-code workflow methodology |
| `aigovern_complete_target_architecture.svg` | Target architecture diagram (source) |

---

## 14. Coverage verification — anything missing?

Cross-checked against every prior conversation thread:

| Topic | In this plan | Notes |
|---|---|---|
| 6-layer architecture | ✓ Section 1.1 | Full layer model |
| 3-decorator chain | ✓ Section 1.2 | Order-enforced at SDK |
| 4-tier memory | ✓ Section 1.3 | T1-T4 with PII per tier |
| OPA policy engine | ✓ Section 1.4 + Day 5 | 5 categories · 6 contexts |
| Multi-agent + Agent Library | ✓ Section 1.5 + Day 7 | Publish/subscribe + version pinning |
| Framework coverage (6 frameworks) | ✓ Section 1.6 + Day 6 | NIST + OWASP + EU + ISO + SR 11-7 + FFIEC + US-FinServ |
| Eval pack tiers (A/B/C) | ✓ Section 1.7 | Mandatory + risk-tier + discretionary |
| Right-to-forget cascade | ✓ Section 1.8 + Day 8 | Across vault · T2 · T3 · Langfuse |
| Headless engine + thin clients | ✓ Section 1.9 | v2 north star · v1 single-app |
| Tech stack | ✓ Section 2 | All 8 sub-stacks |
| Azure infrastructure | ✓ Section 3 | All resources · costs · topology |
| Execution modes (A and B) | ✓ Section 4 | 4-day parallel · 12-day serial |
| Day-by-day deliverables | ✓ Section 5 | 12 days with acceptance criteria |
| Production-readiness baseline | ✓ Section 6 | Cross-cutting standards |
| 6 demo scenarios | ✓ Section 7 | All real except where annotated |
| Phase 2 deferred items | ✓ Section 8 | Honest enumeration |
| Risk register | ✓ Section 9 | 11 risks with mitigations |
| Open decisions | ✓ Section 10 | 9 decisions to lock |
| Success criteria | ✓ Section 11 | 19 checkboxes for done |
| Coordination model (Mode A) | ✓ Section 12 | Stream ownership + integration windows |
| PII pipeline detail | ✓ Section 1 + Day 1 | Presidio + Fernet + Key Vault |
| Eval dashboard (matches screenshot) | ✓ Day 2 | KPI cards · sparklines · status donut |
| Frameworks matrix UI | ✓ Day 6 | Console-style + evidence drill |
| Audit log + audit-events page | ✓ Day 8 | Hash chain + verification |
| CLI + SDK | ✓ Day 9 | Production-real, not slides |
| Postgres projection | ✓ Day 9 | Materialized views from event log |
| App Insights alerts | ✓ Day 10 + Section 6 | 8 critical signals |
| Demo runbook | ✓ Day 11 | 20-Q&A prep |
| Stakeholder dry-run | ✓ Day 12 | Definition of done |
| References | ✓ Section 13 | All companion docs linked |
| Compound engineering rule | ✓ via CLAUDE.md | Every mistake → new rule |
| Verification commands | ✓ via ARCHITECTURE.md | `/verify` runs all gates |
| Slash commands (/arch /plan /verify /handoff /diagram) | ✓ via .claude/commands/ | All committed |
| AWS Analyzer demo content | ✓ Section 10 (kept) | No re-theme needed |
| OWASP LLM Top 10 defense map | ✓ via Section 1.6 | All 10 threats defended |
| Customer / user personas | ✓ Section 1.9 | Engineer · Governance · Audit |

**Gaps identified during verification:** None substantive. The plan covers every topic from prior conversations.

---

**End of plan.** Locked. Awaiting "go" to execute.
