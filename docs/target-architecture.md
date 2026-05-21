# AI Assurance Platform — Holistic Target Architecture

**Status:** Authoritative target. Supersedes the prior eval-harness plan and the platform-realignment notes.
**Date:** 2026-05-20
**Diagram reference:** `aigovern_complete_target_architecture.svg`

---

## 1. What this platform IS, in one paragraph

A **governance substrate for enterprise AI** that wraps every LLM call in three enforced decorators (`@scrub_pii` → `@trace_llm_call` → `@evaluate_response`), backed by a four-tier memory model, fed by commodity evaluation tools (Langfuse + DeepEval + Presidio), and governed by an organizational layer (risk inventory, governance body, RACI, regulatory posture). It's not an eval tool, not a tracing tool, not a guardrails tool — it's the **control plane** that makes those tools auditable, attestable, and defensible across a portfolio of AI systems in regulated industries.

---

## 2. The Six Layers

```
┌───────────────────────────────────────────────────────────────────────────┐
│  Layer 1 — ORGANIZATIONAL  (planned)                                       │
│  Risk inventory · Governance body · RACI · Regulatory posture              │
│  Per-org config: which frameworks apply, which controls are strict,        │
│  who decides what, what risks the portfolio carries                        │
└──────────────────────────────────┬────────────────────────────────────────┘
                                   │ governs
                                   ▼
┌───────────────────────────────────────────────────────────────────────────┐
│  Layer 2 — ENTERPRISE AI CONTROL PLANE  (mostly built)                     │
│  ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐              │
│  │ AI Gateway /    │ │ Policy /        │ │ Agent Tool      │              │
│  │ Model Broker ✓  │ │ Guardrail ✓     │ │ Registry        │              │
│  │                 │ │ Engine          │ │ RBAC / ID ✓     │              │
│  └─────────────────┘ └─────────────────┘ └─────────────────┘              │
│  ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐              │
│  │ Eval & Testing  │ │ Observability   │ │ Usage, Cost &   │              │
│  │ DeepEval +      │ │ & Audit         │ │ Rate Controls ✓ │              │
│  │ adversarial ⟳   │ │ Langfuse +      │ │                 │              │
│  │ → 6 metrics     │ │ audit.py ⟳      │ │                 │              │
│  └─────────────────┘ └─────────────────┘ └─────────────────┘              │
│  ┌─────────────────┐                                                       │
│  │ Release Gates / │                                                       │
│  │ Assessment      │                                                       │
│  │ Engine ✓        │                                                       │
│  └─────────────────┘                                                       │
└──────────────────────────────────┬────────────────────────────────────────┘
                                   │ enforces
                                   ▼
┌───────────────────────────────────────────────────────────────────────────┐
│  Layer 3 — PII / IP / SECRET SCRUBBING PIPELINE  (in progress)             │
│  scrubber.py (Presidio NER + regex)                                        │
│  deid_vault.py (Fernet · Azure Key Vault token vault)                      │
│  Slots between Policy Engine and RAG Governance · reversible · auditable   │
│  Critical fix in-flight: tracer.py raw-prompt leak                         │
└──────────────────────────────────┬────────────────────────────────────────┘
                                   │ scrubs every byte
                                   ▼
┌───────────────────────────────────────────────────────────────────────────┐
│  Layer 4 — FOUR-TIER AGENT MEMORY  (Tier 4 built, 1-3 planned)             │
│                                                                            │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────────────┐               │
│  │ Tier 1  │  │ Tier 2  │  │ Tier 3  │  │ Tier 4          │               │
│  │ In-     │  │ Episodic│  │ Semantic│  │ Procedural ✓    │               │
│  │ context │  │ JSONL   │  │ /RAG    │  │ domains.py      │               │
│  │         │  │ sessions│  │ Azure   │  │                 │               │
│  │ per call│  │         │  │ AI Srch │  │                 │               │
│  └─────────┘  └─────────┘  └─────────┘  └─────────────────┘               │
│                                                                            │
│  agent_memory.py — build_context · compress_episode · selective_recall    │
│  rag_engine.py   — embed_query · retrieve_chunks · assemble_context ·     │
│                    index_document (corpus pre-scrubbed at index time)     │
└──────────────────────────────────┬────────────────────────────────────────┘
                                   │ assembles context
                                   ▼
┌───────────────────────────────────────────────────────────────────────────┐
│  Layer 5 — RUNTIME  (Langfuse + DeepEval MVP exists; harden + extend)      │
│                                                                            │
│  ┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐           │
│  │ Langfuse Cloud   │ │ DeepEval         │ │ Decorator chain  │           │
│  │ trace_call() ✓   │ │ 6-metric suite:  │ │ @scrub_pii       │           │
│  │ get_traces() ✓   │ │ hallucination,   │ │ @trace_llm_call  │           │
│  │ scrubbed payload │ │ relevancy,       │ │ @evaluate_resp   │           │
│  │ only (enforced)  │ │ faithfulness,    │ │ order enforced   │           │
│  │                  │ │ toxicity,        │ │                  │           │
│  │                  │ │ PII leakage,     │ │                  │           │
│  │                  │ │ scrub score      │ │                  │           │
│  └──────────────────┘ └──────────────────┘ └──────────────────┘           │
└──────────────────────────────────┬────────────────────────────────────────┘
                                   │ ALL traffic
                                   ▼
┌───────────────────────────────────────────────────────────────────────────┐
│  Layer 6 — LLM ABSTRACTION                                                 │
│  Claude (Sonnet 4.6 default, Opus 4.7 for deep work, Haiku 4.5 cheap)     │
│  GPT-4o-mini for cost-sensitive paths                                      │
│  Bedrock for in-boundary / regulated paths                                 │
│  NO PII / secrets / IP crosses this boundary                               │
└───────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Component Inventory by Status

### Built (12 components)

| Component | Location | Layer |
|---|---|---|
| AI Gateway / Model Broker | `domain/assurance_providers.py` | 2 |
| Policy / Guardrail Engine | `domain/release_gate_engine.py` + NeMo wiring | 2 |
| Agent Tool Registry / RBAC | `middleware/auth.py` + 5 role accounts | 2 |
| Release Gates / Assessment Engine | `domain/release_gate_engine.py`, `assessment_engine.py` | 2 |
| Usage, Cost & Rate Controls (partial) | `domain/usage_analytics.py`, provider routing audit | 2 |
| Eval & Testing Service (5 metrics) | `evaluator.py` + DeepEval lazy import + `adversarial.py` (Garak) | 2 |
| Observability & Audit (leaky) | `tracer.py` (Langfuse) + `audit.py` | 2 |
| Tier 4 Procedural Memory | `domains.py` + control libraries + framework coverage | 4 |
| Storage layer | `storage.py` (JSONL append-only) | always-on |
| Auth + sessions | `middleware/auth.py` (10-min sliding) | always-on |
| Domain models | `domain/models.py` | always-on |
| 12 UI pages | Command Center, AI Systems, Findings, Release Gates, Evidence, Runtime, Policies, Reports, Connectors, Assurance Providers, Framework SOP, Analytics + AWS Analyzer demo | 2 |

### In progress (6 components)

| Component | What's needed |
|---|---|
| `scrubber.py` | Presidio NER + regex layering + custom domain hooks |
| `deid_vault.py` | Fernet encryption + Azure Key Vault backing + reversible token map |
| `@scrub_pii` decorator | Wraps args + return value, populates vault, enforces before trace |
| `api/rag.py` | Endpoints for indexing, retrieval, corpus health |
| `rag-governance.html` | Corpus inventory, retrieval audit, scrub coverage UI |
| **🔴 Fix tracer.py raw-prompt leak** | **Insert scrubber before Langfuse trace_call (1-day emergency fix)** |

### Planned — Memory (5 components)

| Component | What it does |
|---|---|
| `agent_memory.py` | Orchestrator: `build_context`, `write_episode`, `compress_episode`, `selective_recall` |
| Tier 2 episodic store | `data/episodes_{workload_id}.jsonl`, append-only, scrubbed-at-write |
| `compress_episode()` | Summarizes long sessions via Claude Haiku; preserves token vault refs for uncompression |
| `selective_recall()` | Embedding similarity over Tier 2 + Tier 3, deduplicated |
| `rag_engine.py` | Tier 3 wrapper for Azure AI Search; index-time scrubbing enforced |

### Planned — Org layer (4 components)

| Component | What it does |
|---|---|
| `domain/risk_inventory.py` | Enterprise risk register; each AI System has parent risks tied to regulatory posture |
| `domain/governance_body.py` | AI Council / Risk Committee / Model Risk — seats, cadence, decision authority |
| `domain/raci.py` | RACI matrix per (AI System × decision type); resolved via governance body config |
| `domain/regulatory_posture.py` | Per-org: applicable frameworks (NIST AI RMF, EU AI Act, FFIEC, HIPAA, SR 11-7, ISO 42001) + strictness |

---

## 4. The Three Runtime Paths

Every operation in the platform flows through one of three paths.

### Path A — LLM call (the hot path)

```
User input arrives at an agent
    ▼
agent_memory.build_context(workload, session, query)
    ├── pulls Tier 4 procedural rules (domains.py)
    ├── pulls Tier 3 RAG chunks (rag_engine.retrieve_chunks)
    ├── pulls Tier 2 episodes (selective_recall)
    └── assembles Tier 1 within token budget
    ▼
@scrub_pii(args)
    ├── Presidio entity detection on prompt
    ├── token vault writes for any PII found
    └── returns scrubbed prompt
    ▼
@trace_llm_call → Langfuse.trace_call(scrubbed_prompt)
    ▼
LLM abstraction layer (Claude / GPT-4o-mini / Bedrock)
    └── provider routing via assurance_providers per workload sensitivity
    ▼
@scrub_pii(response) on the way back
    ▼
@evaluate_response → DeepEval scores attached to trace
    ├── hallucination, relevancy, faithfulness
    ├── toxicity, PII leakage, scrub score
    └── policy gate check → block / warn / pass
    ▼
agent_memory.write_episode(session, turn) → Tier 2 append (scrubbed)
    ▼
Response returned to user
```

### Path B — RAG ingest

```
Document arrives for indexing
    ▼
rag_engine.index_document(workload, source, content, classification)
    ▼
scrubber.scan(content)
    ├── HIGH-confidence PII detected + classification != 'public' → reject + audit
    ├── otherwise → scrub, record audit hash of pre-scrub doc
    ▼
Semantic chunking (~500 tokens, 50-token overlap)
    ▼
Embed via text-embedding-3-small (pinned)
    ▼
Upsert to Azure AI Search (index named with embedding-model version)
    ▼
audit_log.write(source_id, chunk_count, pii_entities, indexed_at, scrub_hash)
```

### Path C — Governance read (the cold path)

```
Auditor / Risk / CISO request
    ▼
api/grc.py · api/reports.py · api/evidence.py
    ▼
Read across:
    ├── AI Systems registry (data/ai_systems.jsonl)
    ├── Findings (findings_events.jsonl)
    ├── Release gate decisions (release_gates.jsonl)
    ├── Revision history (ai_system_revisions.jsonl)
    ├── Audit log (audit_log)
    ├── Langfuse traces (filtered by workload + time range)
    ├── DeepEval scores (joined from Langfuse trace metadata)
    ├── Scrub audit (every scrub event logged)
    ▼
Bundle assembly:
    ├── PDF executive summary (WeasyPrint)
    ├── JSON raw evidence
    ├── CSV detail tables
    ▼
SHA-256 hash → evidence_bundles row → download link
```

---

## 5. Cross-Cutting Concerns (Governance Overlay)

These apply at EVERY layer, not just one. This is what makes the platform defensible vs. raw Langfuse + DeepEval.

| Concern | Tier 1 | Tier 2 | Tier 3 | Tier 4 | Langfuse | DeepEval |
|---|---|---|---|---|---|---|
| **PII scrubbed** | required | write-time | index-time | n/a | enforced | enforced |
| **Audit log entry** | every call | every write | every index/retrieve | static | yes | yes |
| **Access control** | per-workload | per-session+role | per-classification | platform | per-role | per-role |
| **Retention policy** | per-call | 90d default | per-source TTL | static | configurable | configurable |
| **Right-to-forget** | n/a | by session_id | by source_id | n/a | by trace_id | cascades |
| **Reproducibility** | non-deterministic | append-only | index version pinned | versioned | trace ID stable | metric versioned |
| **Provenance** | call context | session lineage | source_id chain | code version | trace metadata | scorer version |

---

## 6. Broad-Use-Case Fit

The architecture serves multiple AI patterns with the same invariant runtime stack.

| Use case | Tier 2 use | Tier 3 use | Tools | Custom scorers needed |
|---|---|---|---|---|
| Single-turn Q&A | minimal | knowledge base lookup | none | relevancy |
| Customer support chatbot | heavy (conversation context) | policy KB | order lookup, refund, escalate | resolution quality, tone |
| Internal document RAG | minimal | document corpus | none | ContextualRecall, citation accuracy |
| Code-generation agent | session history of prior gen | code knowledge base | linter, test runner, git | security vuln, license compliance |
| Multi-agent workflow | shared session state | shared corpus + per-agent | many, gated by RBAC | tool-call correctness, plan coherence |
| Adversarial / red-team | adversarial session history | none | adversarial probes | jailbreak resistance, refusal rate |
| Regulated industry (bank/health) | strictly retained per policy | classification-tiered | gated by RBAC + classification | regulator-specific (model fairness, BSA/AML) |

**What changes per use case:** Tier 3 corpus, tool registry membership, custom DeepEval scorers, governance body config, regulatory posture.

**What stays invariant:** The decorator stack, the PII boundary, Tier 4 procedural memory, the audit overlay, the evidence export pipeline, the release gate workflow.

---

## 7. Defensibility — Why This Wins

Most competitors stop at one or two layers. This stack defends across all six.

| Competitor | Layer 1 Org | Layer 2 Control Plane | Layer 3 PII | Layer 4 Memory | Layer 5 Runtime | Layer 6 LLM |
|---|---|---|---|---|---|---|
| PromptFoo / Braintrust | ✗ | ✗ | partial | ✗ | ✓ | ✓ |
| LangSmith | ✗ | partial | ✗ | partial (1, 2) | ✓ | ✓ |
| Langfuse alone | ✗ | ✗ | ✗ | ✗ | ✓ | ✓ |
| DeepEval alone | ✗ | ✗ | ✗ | ✗ | partial | ✓ |
| Datadog AI Observability | ✗ | partial | partial | ✗ | ✓ | ✓ |
| Credo AI / Holistic AI | partial (1) | ✗ | ✗ | ✗ | ✗ | ✗ |
| **This platform** | **✓** | **✓** | **✓** | **✓** | **✓** | **✓** |

The wedge:
- **Compose, don't rebuild commodities.** Langfuse + DeepEval + Presidio are battle-tested. Don't waste cycles reimplementing them.
- **Layer 1 + Layer 4 are the moats.** Nobody else packages an Org layer (RACI, regulatory posture) with a four-tier memory model.
- **Cross-cutting governance overlay** turns commodities into compliance artifacts.

---

## 8. Build Sequence — Roadmap to the Holistic Architecture

Three phases, ~10–11 weeks. Order optimized for "regulated buyer can demo safely."

```
Week  Phase                              Deliverable                          Layer
────  ─────                              ───────────                          ─────
 1    EMERGENCY                          Patch tracer.py raw-prompt leak       L3
                                         (regex-only scrubber, ship today)

 2-3  Phase A — PII Pipeline             scrubber.py (Presidio + regex)        L3
                                         deid_vault.py (Fernet + Key Vault)
                                         @scrub_pii decorator
                                         Index-time scrubbing for RAG

 4-5  Phase B — Runtime Hardening        Wire Langfuse properly                L5
                                         DeepEval 6-metric suite
                                         Three-decorator stack enforced
                                         Replace tracer.py / evaluator.py

 6-7  Phase C — Memory Layer Part 1      Tier 2 episodic store                 L4
                                         agent_memory.py orchestrator
                                         compress_episode + selective_recall

 8-9  Phase C — Memory Layer Part 2      rag_engine.py + Azure AI Search       L4
                                         rag-governance.html UI
                                         Memory inspector page

10-11 Phase D — Org Layer                risk_inventory + governance_body      L1
                                         + raci + regulatory_posture
                                         3 new UI pages

 12   Polish + Deploy                    Smoke, audit verification, deploy     all
```

**Acceptance for "complete" target architecture:**

1. Every LLM call in `aigovern.sandboxhub.co` traces in Langfuse with zero PII (verified by 10K-sample audit)
2. Every RAG document is index-scrubbed; PII rejection rate visible in UI
3. Tier 2 episodes survive session restart; compression triggers automatically; recall works
4. Switching org regulatory posture (fintech ↔ hospital) changes active controls + RACI automatically
5. Right-to-forget endpoint cascades through Tier 2, Tier 3, Langfuse, token vault in one transaction
6. Evidence export bundle includes Langfuse trace IDs, DeepEval scores, scrub audit, and is reproducible by hash

---

## 9. What This Doc Supersedes

- `docs/PLAN-EVAL-HARNESS.md` — original eval harness sketch
- `docs/ai-eval-harness-plan.md` — north-star (15 sections)
- `docs/ai-eval-harness-tier1-tier2-plan.md` — 14-feature spec
- `docs/ai-eval-harness-impl-plan.md` — 12-week build plan

Keep those as historical record. **This document is the authoritative target.**

The eval harness was a useful exercise but the right answer was "wrap commodity tools and put the value in the governance overlay" — exactly what this architecture does.

---

## 10. Single-Page Mental Model

If you remember one thing from this doc:

> **Every LLM call passes through three decorators in this order:**
> **`@scrub_pii` → `@trace_llm_call` → `@evaluate_response`**
>
> **Context is assembled from four memory tiers:**
> **Tier 4 (procedural) + Tier 3 (RAG) + Tier 2 (episodic) → Tier 1 (in-context)**
>
> **The governance overlay (audit, retention, RBAC, right-to-forget) applies at every layer.**
>
> **The organizational layer (risk inventory, RACI, regulatory posture) decides which controls fire and how strictly.**
>
> **Langfuse + DeepEval + Presidio are commodities. The wedge is the layers around them.**

That's the architecture.
