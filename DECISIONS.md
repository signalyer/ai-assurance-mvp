# DECISIONS.md — Immutable architectural decision log
# Never edit existing entries. Append only.

## 2026-05-20 — Scrubber before Langfuse
Decision: scrubber.tokenise_payload() runs before tracer.trace_call() at every call site.
Alternatives: post-hoc Langfuse redaction · Langfuse self-hosted only · accept the risk
Why: Langfuse Cloud is SaaS — even self-hosted must never receive raw PII as defence-in-depth.
     The constraint must survive any backend swap. Today tracer.py leaks raw prompts; Session 01a/01b fixes it.
Constrains: all LLM call wrappers permanently follow scrub → trace order.

## 2026-05-20 — OPA as primary policy engine
Decision: OPA (Rego) primary, Cedar secondary, no home-grown rules dict.
Alternatives: Cedar-only · home-grown rules dict · NeMo for policy
Why: OPA most mature, multi-cloud, git-backed, 9500+ tests. Home-grown = unmaintainable at scale.
Constrains: `policies/` contains `*.rego` files, evaluated via OPA sidecar.

## 2026-05-20 — No SaaS guardrails
Decision: all guardrails self-hosted (LLM Guard, NeMo Guardrails, Llama Guard 3).
Alternatives: Lakera Guard · Azure Content Safety
Why: SaaS guardrails route prompts externally — direct PII boundary contradiction.
Constrains: guardrail stack deployable on Azure ACI with no external calls in the prompt path.

## 2026-05-20 — Four-tier agent memory
Decision: T1 in-context · T2 episodic JSONL · T3 RAG (Azure AI Search) · T4 procedural (domains.py).
Alternatives: single vector store for all memory · pure in-context · LangChain memory primitives
Why: RAG and episodic memory solve different problems. Conflating creates stale retrieval and
     unbounded context growth. Procedural memory (Tier 4) is already built as domains.py.
Constrains: agent_memory.py manages all four tiers. RAG is read-only corpus; episodic is per-session.

## 2026-05-20 — JSONL storage for MVP
Decision: JSONL flat files via storage.py for de-id vault and episodic memory.
Alternatives: Redis · SQLite · Azure CosmosDB
Why: SQLAlchemy already in requirements for future migration path. JSONL minimises dependencies
     for MVP/demo. Swap backend later via Session 05 provider abstraction.
Constrains: vault TTL enforced in application layer, not database layer. No queries beyond
     append + read; aggregation done in Python.

## 2026-05-20 — Single tenant for v1
Decision: Build single-tenant. No `org_id` on tables. Multi-tenant deferred to v2.
Alternatives: shared multi-tenant with row-level isolation · per-customer infra from day one
Why: Fastest path to verification with one design partner. Forward-compat plumbing (TenantScoped
     mixin, tenant_id DI) makes v2 a column-add + filter, not a rewrite.
Constrains: every model accepts `tenant_id` parameter (default "default"); DB queries use it but
     v1 returns same data regardless.

## 2026-05-20 — Compose, don't rebuild commodities
Decision: Wrap Langfuse + DeepEval + Presidio rather than build custom tracing / metrics / PII detection.
Alternatives: custom SDK (rejected) · LangSmith · Helicone · Honeycomb
Why: These tools are battle-tested, multi-language, mature. Defensibility lives in the layers
     around them (Org layer, four-tier memory, governance overlay, control framework mapping) —
     not in reimplementing commodities. Saves ~6 weeks vs. custom path.
Constrains: SDK adapters in `providers.py` (Session 05) keep backend swappable.

## 2026-05-20 — Eval harness folded into main platform
Decision: SUPERSEDES the prior plan to host eval harness at evals.sandboxhub.co as a separate product.
         Eval functionality lives inside aigovern.sandboxhub.co as new modules.
Alternatives: separate harness deployment at evals.sandboxhub.co (originally agreed)
Why: With compose-don't-build, the eval "harness" is just a few modules wrapping Langfuse + DeepEval.
     One codebase, one deploy, one auth is simpler than a hub-and-spoke architecture for v1.
     Hub-and-spoke can re-emerge in v2 if customer pressure requires it.
Constrains: `docs/ai-eval-harness-*.md` plans are marked historical. Eval pipe-back contract is moot;
     eval data is co-located with governance data.

## 2026-05-20 — DeepEval 6-metric suite
Decision: hallucination · relevancy · faithfulness · toxicity · PII leakage · scrub score.
Alternatives: ContextualRecall + ContextualPrecision instead of toxicity + scrub score
Why: Toxicity is a CISO-visible metric; scrub score is a meta-metric on the pipeline's own
     PII performance. Contextual metrics are RAG-specific and move into RAG eval pack.
Constrains: every LLM call gets all 6 scores. Custom domain scorers add to this baseline.

## 2026-05-20 — Adopt structured Chat → Code workflow
Decision: Three persistent files (CLAUDE.md ≤150 lines · ARCHITECTURE.md no limit · DECISIONS.md
         append-only). Five slash commands (/arch, /plan, /verify, /handoff, /diagram).
         Seven-session build plan (01a/01b/02/03/04/05/06/07) extended to 10 sessions for Org layer.
Alternatives: continue ad-hoc session-by-session planning · single CLAUDE.md with everything
Why: Long Chat sessions produce plans that fragment in Code sessions. The structured workflow
     gives a forcing function for handoff and a continuity primitive (SESSION-NN plan files).
Constrains: every build session starts with /arch, plans via /plan, ends with /handoff.
     New decisions get appended here at the end of every session.
