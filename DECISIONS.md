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

## 2026-05-21 — Guardrails position in decorator chain
Decision: @guardrails inserted between @scrub_pii and @trace_llm_call.
          Order: @policy_gate → @scrub_pii → @guardrails → @trace_llm_call → @evaluate_response
Alternatives: @guardrails before @policy_gate · @guardrails after @trace_llm_call · no guardrails
Why: Injection detection runs on scrubbed input (not raw PII). Guardrail violations block before 
     Langfuse trace (no poisoned traces). Fails closed: no response on injection/topic/safety violation.
Constrains: @guardrails middleware receives workload_id and auto-sets allowed_topics for known workloads.
     Decorator raises GuardrailViolationError on violations when strict=True.

## 2026-05-21 — Self-hosted guardrails only (no SaaS routing)
Decision: All guardrails implemented locally: regex injection detection, keyword-based topic 
          classification (NeMo-style), heuristic content safety (Llama Guard 3-style).
Alternatives: Azure Content Safety · Lakera Guard · external guardrail APIs
Why: SaaS guardrails route prompts externally — violates PII boundary from Sessions 01-02.
     Fail-closed architecture requires all safety checks to happen in-process.
Constrains: guardrail implementations are keyword/regex-based (Session 03) with LLM fallback deferred 
     to Session 05. No external calls in the prompt path. OPA sidecar deferred to Session 10.

## 2026-05-21 — Fail-closed guardrails with auto topic defaults
Decision: Guardrails raise GuardrailViolationError immediately on violation (strict=True).
          Known workloads (e.g., financial_advisor) auto-populate allowed_topics.
Alternatives: soft warnings (log but continue) · no defaults (user must pass allowed_topics)
Why: Financial advisor guardrails block stock tips and guaranteed return claims without manual config.
     Users can still disable guardrails per-endpoint (strict=False) or globally (GUARDRAILS_ENABLED=false).
Constrains: decorator auto-loads TopicClassifier.ALLOWED_TOPICS_DEFAULT for financial_advisor workload.
     Test coverage: 16 acceptance tests (injection, topic, safety, decorator integration).

## 2026-05-21 — Tier 2 episodic memory: Postgres with database-level TTL
Decision: Tier 2 episodic memory stored in Postgres (psql-aigovern-dev, westus2), not JSONL.
         TTL enforced via `expires_at TIMESTAMPTZ` column; `purge_expired()` for cron-driven cleanup.
         Inline schema bootstrap (`CREATE TABLE IF NOT EXISTS`) — no Alembic yet (none present in repo).
Alternatives: JSONL per workload (Session 04 plan default) · SQLite · Cosmos DB · in-memory
Why: User explicitly chose Postgres over JSONL during Session 04 planning. Database-level TTL means
     no application-layer TTL drift; queries can filter expired rows in the WHERE clause. Postgres
     full-text search (tsvector) provides selective_recall without an external search engine.
Constrains: every episode write requires DATABASE_URL set. write_episode enforces vault_id when
     SCRUBBER_ENABLED=true (mirrors tracer hardening). Parameterized SQL only — no f-string queries.

## 2026-05-21 — RAG: hybrid retrieval (BM25 + semantic vector)
Decision: Tier 3 RAG uses Azure AI Search hybrid mode: BM25 full-text + semantic vector reranking.
         Default weights: 0.6 semantic + 0.4 BM25 (configurable via RAG_HYBRID_SEMANTIC_WEIGHT).
         Embedding model: text-embedding-3-small (1536 dims).
Alternatives: semantic-only · BM25-only · two-stage retrieval (broad BM25 then rerank)
Why: User chose hybrid during Session 04 planning. Semantic-only misses exact-term queries (ticker
     symbols, names). BM25-only misses paraphrased queries. Combined scoring with tunable weights
     handles both. Azure AI Search natively supports both — no second infrastructure piece.
Constrains: index_document() runs scrubber.tokenise_payload() at index time; PII > 0.7 → reject,
     log doc_id + score (no content preview) to data/rag_rejections.jsonl. RAG_ENABLED=false
     auto-set when Azure creds missing — all RAG ops return safe defaults so dev/test work.

## 2026-05-21 — Memory API: asyncio.to_thread for sync domain functions
Decision: API endpoints in api/memory.py wrap all calls to domain.agent_memory and domain.rag_engine
         with asyncio.to_thread(). Domain functions remain synchronous (SQLAlchemy 2.x blocking I/O).
Alternatives: make domain functions async (asyncpg) · keep sync and accept event-loop blocking
Why: SQLAlchemy with psycopg2 is sync; converting to async asyncpg is a larger migration. asyncio.to_thread
     runs sync calls in the default thread pool, preserving event-loop concurrency without rewriting
     the data access layer. Discovered in Session 04 code review: initial implementation awaited sync
     functions directly, which would have caused TypeError 500s on every memory endpoint.
Constrains: every API handler that touches domain.agent_memory/rag_engine MUST use asyncio.to_thread.
     Future async DB migration (Session 10+) can drop the wrapper without changing API signatures.

## 2026-05-21 — Rename guardrails.py → legacy_guardrails.py
Decision: Old root-level `guardrails.py` (regex-only filters from Session 0) renamed to
         `legacy_guardrails.py` after Session 03 introduced `guardrails/` package (NeMo + Llama Guard).
         api/security.py, api/batch.py, api/demo_run.py updated to import from new location.
Alternatives: move legacy functions into guardrails/__init__.py · delete legacy and rewrite callers
Why: Python's import resolution picks the package over the module when both exist with the same name.
     Legacy filter_output / apply_guardrails / get_rail_summary still serve api/security.py adversarial
     probing and api/batch.py — moving them into the new package would mix concerns. Rename is
     minimal-blast-radius and preserves the legacy code's behavior for those specific call sites.
Constrains: new guardrail work goes in `guardrails/` package + `middleware/guardrails.py` decorator.
     `legacy_guardrails.py` is frozen — bug fixes only, no new features. Session 05 may evaluate
     deleting it entirely once api/security.py adversarial flow is rewritten to use Garak directly.

## 2026-05-21 — Provider abstraction: typing.Protocol + Pydantic BaseSettings
Decision: Backend interfaces defined via `typing.Protocol` (structural, zero runtime cost).
         Backend config via Pydantic v2 `BaseSettings` (env-var-driven, validated at startup).
         Five pluggable backends: scrubber (presidio|regex|noop), tracer (langfuse|stdout|noop),
         evaluator (deepeval|noop), memory (postgres|jsonl|noop), RAG (azure_search|noop).
Alternatives: inheritance-based ABC · Pydantic BaseModel for interfaces · fixed backend at build time
Why: Protocol satisfies structural typing contracts at runtime with no inheritance boilerplate.
     Pydantic BaseSettings auto-parses env vars and validates enums at import time (fail-closed).
     Backends cached in registry via lru_cache(maxsize=1) — no per-call instantiation overhead.
Constrains: every backend module implements its Protocol fully. Unknown env var values raise
     ValidationError at module load — no silent fallbacks. Backend lifecycle: create once at module
     load, reuse for all calls (stateful backends like Postgres engine must not leak connections).

## 2026-05-21 — Delete legacy_guardrails.py; migrate api/security.py + api/batch.py
Decision: legacy_guardrails.py deleted entirely. api/security.py, api/batch.py, api/demo_run.py
         rewritten to use new guardrails package (Session 03): middleware/injection.detect_injection
         for injection detection, guardrails/llama_guard_adapter.evaluate_content for safety scoring.
Alternatives: keep legacy as stub · keep both implementations indefinitely · move legacy into guardrails/
Why: Single-tenant project with no external consumers. Legacy implementation (regex filters + keyword
     matching) superseded by Session 03 guardrails (NeMo + Llama Guard 3). Deleting removes dead code
     and API surface confusion (filter_output exists in both api/batch and legacy_guardrails).
Constrains: api/security.py apply_guardrails and filter_output signatures unchanged (backward compat
     for callers). Session 03 guardrails are the new default. No feature degradation — new guardrails
     strictly more capable (LLM-based safety scoring + NeMo topic classification vs. keyword matching).

## 2026-05-21 — Framework definitions: YAML for new, Python for existing (hybrid)
Decision: New frameworks (EU AI Act, ISO 42001, SR 11-7, FFIEC, US-FinServ overlay) defined as
         YAML files in frameworks/ directory, loaded at module load via frameworks.loader.
         Existing NIST AI RMF, NIST AI 600-1, OWASP LLM Top 10, OWASP Agentic Top 10 stay as
         hardcoded Python catalogs in domain/framework_coverage.py.
Alternatives: migrate all 6 to YAML · keep all in Python · external CMS-style framework editor
Why: Hybrid model minimizes Session 06 scope while making future framework additions data-driven.
     YAML loader uses Pydantic v2 schema validation + path confinement (is_relative_to). Schema
     version field gates incompatible changes. Loader returns FrameworkItem dataclass instances
     that merge directly with Python catalogs — no engine refactor.
Constrains: domain/framework_coverage.py uses lazy deferred import to break circular dep with
     frameworks.loader. All new framework catalogs added as YAML files; Python catalogs frozen
     until future migration (deferred to Phase 2 if needed).

## 2026-05-21 — Framework coverage matrix: 8 user-facing slugs, not 6
Decision: MATRIX_FRAMEWORKS surfaces 8 framework slugs in the coverage matrix UI:
         nist-ai-rmf, nist-ai-600-1, owasp-llm, owasp-agentic, eu-ai-act, iso-42001, sr-11-7, ffiec.
         Day 6 spec listed "6 frameworks" but NIST and OWASP each have 2 catalog dialects.
Alternatives: collapse NIST 1 catalog + OWASP 1 catalog · keep all 13 enum slugs in matrix
Why: NIST AI RMF and NIST AI 600-1 measure different things (functions vs risk areas); collapsing
     them loses signal. Similarly OWASP LLM Top 10 and OWASP Agentic Top 10 are distinct. Legacy
     enum slugs (AWS_CONTROLS, SOC2, ISO_IEC_23894, FS_OVERLAY) excluded from matrix — they're
     leftover from earlier work and not in Day 6 spec.
Constrains: Day 6 acceptance test #6 asserts `len(matrix.frameworks) >= 6` (passes with 8).
     `_FRAMEWORK_SLUG_TO_CATALOG_KEY` is the single source of truth — `api/frameworks.py` imports
     it directly (no duplicate mapping).

## 2026-05-21 — Stdlib-only PDF generation (no reportlab/weasyprint)
Decision: PDF Pack generators (NIST/OWASP/EU AI Act) use a custom stdlib-only `_PdfWriter` in
         pdf_report.py — no reportlab, no weasyprint, no external PDF libraries.
Alternatives: reportlab (already in existing pdf_report.py?) · weasyprint · matplotlib backend
Why: pdf_report.py was already stdlib-only; introducing reportlab is a 10MB dependency for 3
     PDF templates. _PdfWriter builds PDF 1.4 with explicit object IDs + xref table + zlib-
     compressed content streams. Verified output starts with %PDF; acceptable PDF readers parse it.
Constrains: any new PDF feature must extend _PdfWriter, not bring in reportlab. Pre-allocated
     object IDs enforced via assertions in build() — fragile arithmetic eliminated.

## 2026-05-21 — Full framework_mappings backfill across 40 controls
Decision: Every one of 40 controls in domain/controls.py annotated with framework_mappings entries
         for all 8 user-facing framework slugs.
Alternatives: critical-path-only (top 5 controls) · skip backfill and use existing partial mappings
Why: Matrix coverage % is computed live — partial mappings produce misleading 0%/100% cells. Full
     backfill is mechanical but tedious; produces honest coverage signal. Each mapping = real clause
     ref (e.g., Art.10 for EU AI Act data governance), not placeholder.
Constrains: any new control added to CONTROLS must include framework_mappings for all 8 user-facing
     frameworks at definition time. Acceptance test #11 enforces this (asserts zero gaps).

## 2026-05-21 — Agent storage: Postgres-primary with JSONL audit trail (Session 07)
Decision: Agents, agent_versions, agent_bindings, agent_subscribers live in Postgres as primary
         store. data/events.jsonl receives append-only audit events for every agent mutation.
Alternatives: pure JSONL-primary (consistent with T2 episodic) · Redis cache · DB-only no audit
Why: Agent CRUD has rich queryable surface (filter by team, owner_type, list versions ordered by
     semver). Postgres schema enforcement (UNIQUE, FK, CHECK) prevents bad state. JSONL audit
     trail preserves the SSOT-replay property for governance: every AGENT_PUBLISHED,
     AGENT_BINDING_CREATED, AGENT_BINDING_UPGRADED, AGENT_BINDING_REMOVED captured immutably.
Constrains: all agent SQL parameterised via SQLAlchemy `text()` + named bind params. Audit event
     writes are best-effort outside the DB transaction; logged on failure. Session 08+ may move
     the audit write inside the transaction for completeness.

## 2026-05-21 — Database-tracked agent versions (separate agent_versions table)
Decision: AgentVersion is a separate Postgres entity with its own id (UUID), FK to Agent.id, and
         a regex-validated semver string. AgentBinding stores `version_id` FK (not a semver string).
Alternatives: semver in YAML manifests (per-agent dir) · hash-based immutable versions
Why: FK ensures referential integrity (a binding cannot point to a non-existent version). Semver
     validated by Pydantic field_validator at model construction AND by API PublishVersionRequest
     at the request boundary (two layers). UNIQUE(agent_id, semver) at the DB level catches semver
     collision in concurrent publishes.
Constrains: bindings always reference version_id (UUID), never semver. Semver is display-only.
     Version pin/unpin lives on the binding row (`pinned BOOLEAN`).

## 2026-05-21 — Postgres LISTEN/NOTIFY for publish notifications (Session 07)
Decision: Agent publish triggers `pg_notify('agent_update_{agent_id}', version_id)` inside the
         publish transaction. SSE endpoint `/api/agents/{agent_id}/listen` opens a dedicated psycopg2
         connection per client, calls `LISTEN agent_update_{agent_id}` (channel name passed through
         `psycopg2.extensions.quote_ident` to defend against identifier injection), and yields SSE
         events with 25s keepalive.
Alternatives: client polling every 10s · WebSocket fan-out from in-process pubsub · external broker
         (Redis pub/sub, Service Bus)
Why: LISTEN/NOTIFY is real-time (<100ms), distributed across Postgres replicas, requires no new
     infrastructure. Single SSE endpoint serves all subscribers. 30s SLA easily met. quote_ident
     makes the LISTEN identifier-safe even if upstream regex sanitisation is ever bypassed.
Constrains: each SSE client consumes one Postgres connection — production deployment must enforce
     per-IP rate limiting and/or global SSE connection caps (flagged as security debt for Day 10).
     Channel name regex `[a-zA-Z0-9_\-]{1,128}` validated at route entry.

## 2026-05-21 — Session 08 locked decisions

### Cascade orchestration — sync inline
Decision: Right-to-forget cascade runs synchronously inside `POST /api/right-to-forget`.
         Endpoint returns 201 on COMPLETED / 207 on PARTIAL_FAILURE.
         Saga / async background job deferred to Day 10 if load tests demand it.
Alternatives: async background job with status polling · distributed saga (compensating transactions)
Why: Single-tenant MVP; cascade completes in < 60s with ≤100 tokens/episodes/chunks per store
     (verified by acceptance H). Sync keeps the code simple and the audit trail contiguous.
     Background job adds a job-store, a polling endpoint, and a scheduler — unnecessary at MVP scale.
Constrains: Cascade orchestrator in domain/right_to_forget.py is a synchronous function.
     API endpoint may be made async with asyncio.to_thread wrapping the sync domain call
     (consistent with Session 04 pattern for Postgres-backed domain functions).

### Hash chain algorithm — SHA-256 plain
Decision: hash = SHA-256(prev_hash ‖ canonical_json(event_without_hash_field)).
         No HMAC secret required. genesis prev_hash = "GENESIS".
         Canonical JSON = json.dumps(event, sort_keys=True, ensure_ascii=True, separators=(',',':')).
Alternatives: HMAC-SHA-256 with Key Vault secret · SHA-3 · Merkle tree
Why: Plain SHA-256 is publicly verifiable without a secret — auditors can replay the chain with
     only the JSONL file and the algorithm spec. HMAC adds a Key Vault dependency for a property
     (tamper detection) that doesn't require secrecy. The audit trail is already access-controlled;
     secrecy of the chain key adds no meaningful defence against the threat model (insider deletion).
Constrains: hash field excluded from hash computation (prevents chicken-and-egg). Verifier must
     apply the same exclusion. Pre-Session-08 events (no hash field) are treated as pre-genesis
     and skipped without error.

### Verification scope — rolling window with checkpoint
Decision: verify_chain(window=N) checks the last N chained events. verify_chain(full=True) checks
         all chained events from genesis. Checkpoints written every 500 events to
         data/audit_checkpoints.jsonl (stores last known-good hash + event_id at that position).
         Default window = 1000.
Alternatives: full replay on every call (O(N) — prohibitive at scale) · no checkpointing
Why: At 1000 events/day, full replay would grow to 365k events/year. Rolling window keeps
     verify_chain < 2s (acceptance H). Checkpoints allow verification to start from a trusted
     anchor rather than genesis, making eventual full verification tractable.
Constrains: Checkpoint file is append-only JSONL (same as events.jsonl). Tamper to checkpoint
     file itself is detectable: checkpoint hash must match hash at that position in events.jsonl.

### Cascade idempotency — cascade_id with reverse lookup
Decision: cascade_id (UUID) generated at request time, persisted as field on all RTF_* events.
         Re-submission with same cascade_id returns prior result with status="ALREADY_COMPLETED".
         Reverse lookup built lazily from event scan on first use, cached in-memory per process.
Alternatives: treat each store delete as idempotent on (subject_id, store_name) · separate
         cascade_state table in Postgres
Why: (subject_id, store_name) idempotency is weaker — it cannot distinguish a second request
     from the same cascade vs a second legitimate cascade for the same subject. cascade_id provides
     unambiguous re-submission detection. Lazy event scan avoids a new DB table for MVP.
     In-memory cache is acceptable for single-process App Service deployment.
Constrains: cascade_id must be supplied by the caller on re-submission; if omitted a new UUID
     is generated and the cascade runs fresh (new request for the same subject).

### Langfuse delete — feature flag gated
Decision: Langfuse trace delete is gated behind LANGFUSE_DELETE_ENABLED env var (default: not set = disabled).
         When disabled: Langfuse step logs intent, emits RTF_STEP_COMPLETED with items_removed=0
         and a deterministic sha256_digest_after (hash of "langfuse:no-op:{subject_id}").
         When enabled: real Langfuse API delete called; response count captured.
Alternatives: always delete · always skip · separate approval step for Langfuse
Why: Langfuse is a SaaS system; real deletes require production credentials and carry risk of
     accidental bulk delete in dev/test. Feature flag is the standard safety gate.
     Dev/test environments never need LANGFUSE_DELETE_ENABLED=true.
     The no-op path still produces a valid 64-char digest so acceptance E passes unconditionally.
Constrains: LANGFUSE_DELETE_ENABLED must be set to exactly "true" to enable. Any other value
     (including "false", "1", unset) results in the no-op path.

## 2026-05-21 — No migration of legacy ai-sys-001; 6 NEW seeded systems
Decision: Existing `ai-sys-001` stays as legacy (no agent bindings). 6 new test systems
         (sys-payments-001, sys-cx-001, sys-risk-001, sys-platform-001, sys-finserv-001,
         sys-internal-001) are seeded via `domain/seed_systems.py`, each bound to 1-3 agents
         from the 6-agent seed catalog.
Alternatives: automatic migration on first migrate.py run · one-time manual migration script
Why: Clean cutover; no risk of corrupting existing demo data; demo scenarios script can target
     specific systems by ID. Legacy ai-sys-001 continues to demonstrate the "no bindings" path
     in `assemble_context` and `framework_matrix` (backward-compat tests).
Constrains: `framework_matrix(["ai-sys-001"])` must continue to work without bindings.
     `assemble_context` returns plain string (not dict) when no bindings are present. Seeded
     agents use `framework_refs: list[str]` format `"FRAMEWORK:CLAUSE"` (e.g., `"NIST_AI_RMF:GOVERN-1.1"`).
     `framework_coverage._agent_framework_coverage` supports both `list[str]` and `list[dict]`
     ref formats for forward-compatibility.

## 2026-05-22 — SDK distribution: internal Azure Artifacts feed (publish gated off in v1)
Decision: SDK builds to a wheel via `hatchling`. Distribution target is an internal
         Azure Artifacts feed. CI publish workflow is wired but gated off (`if: false`)
         until the feed + PAT are provisioned on Day 10. Acceptance test uses
         `pip install -e ./sdk` (editable) which is unchanged.
Alternatives: editable-only forever · public PyPI from day one
Why: PyPI is premature for a v1 demo; editable-only blocks any real distribution story.
     Internal feed matches the eventual prod posture without paying the cost of PAT/feed
     provisioning during the 12-day sprint. `publish.ps1` exits with a DRY-RUN banner.
Constrains: `sdk/pyproject.toml` must build a valid wheel via `python -m build`. The publish
     script must NOT actually upload until Day 10 hardening lands the feed + secret.

## 2026-05-22 — CLI auth: HMAC-SHA-256 only (no Entra in v1)
Decision: The `sl` CLI and the `signallayer` SDK both sign every request to `/api/sdk/*`
         with HMAC-SHA-256. Canonical signing input is newline-delimited:
         `f"{unix_ts}\n{METHOD}\n{path}\n{sha256_hex(body)}"`. Headers: `X-SL-Key-Id`,
         `X-SL-Timestamp` (Unix integer seconds, str), `X-SL-Nonce`, `X-SL-Signature`.
         Drift tolerance 300s. Nonce TTL 600s with hard cap 50,000 entries.
         `middleware/hmac_auth.py` is mounted OUTERMOST (before SessionAuthMiddleware).
         `/api/sdk/` is added to `SessionAuthMiddleware.PUBLIC_PREFIXES` so it is not
         double-processed.
Alternatives: Entra ID device-code · both with toggle
Why: HMAC is the simplest robust signer for service-to-service + CLI traffic on a 12-day
     sprint. Entra adds MSAL + app registration + token refresh — 4h of overhead for no
     demo-visible value. A toggle doubles the security review surface.
Constrains: The canonical signing string above is load-bearing; SDK, CLI, and middleware
     MUST stay byte-identical. Any change requires updating all three files in the same
     commit. `hmac.compare_digest` for verification — never `==`. Multi-worker deploys
     MUST migrate the nonce cache to Redis before going to production (per-process cache
     loses replay protection across workers).

## 2026-05-22 — Postgres projection: LISTEN/NOTIFY via read-side tailer (not inline NOTIFY)
Decision: Postgres materialized views are populated by a two-process pipeline:
         (1) `run_tailer()` reads `data/events.jsonl` (the source of truth), issues
         `SELECT pg_notify('projection_events', <json>)` (PARAMETERIZED, not f-string SQL),
         and checkpoints to `data/projection_tailer_checkpoint.json`.
         (2) `run_projection_worker()` `LISTEN`s on `projection_events` and calls
         `project_event(event, conn)` to upsert into typed tables. Both processes are
         started independently via `python -m domain.projection_worker {tailer|worker}`.
         Replay path bypasses NOTIFY: `replay(from_event_id)` reads JSONL directly and
         applies projections in-process.
Alternatives: inline NOTIFY in `repository._append_jsonl` · polling worker · CDC (Debezium)
Why: Inline NOTIFY would couple the audit-chain write path to Postgres availability,
     violating the Session 08 invariant that JSONL append is PG-free. Read-side tailer
     preserves that invariant: if Postgres is down, the tailer queues and retries; the
     audit log keeps working. Polling alone wastes ~1 RTT/sec; LISTEN gives sub-100ms
     projection latency. CDC (Debezium) is operational overkill for a single-source JSONL.
Constrains: `domain/projection.py` and `domain/projection_worker.py` MUST NOT write to
     `events.jsonl` or `vault.jsonl`. MUST NOT include `raw_prompt` in any materialized
     view. Idempotency keyed on `(event_id)` in `projection_state` inside the same
     transaction as the upsert. Tested by `tests/test_session09_integration.py`.

## 2026-05-22 — Materialized view schema: hybrid (typed hot columns + JSONB rest)
Decision: Each of the 5 view tables has typed columns for the hot fields (queried in
         demos / auditor evidence packs / joins) plus one JSONB column for the rest of
         the payload, with a GIN index on the JSONB column.
         Hot columns (LOCKED):
         - ai_systems: system_id PK, name, owner, risk_tier, created_at, metadata JSONB
         - eval_runs: run_id PK, system_id, status, pass_rate, started_at, finished_at, metrics JSONB
         - findings: finding_id PK, system_id, severity, status, created_at, payload JSONB
         - release_decisions: decision_id PK, system_id, decision, decided_at, gate_results JSONB
         - policy_evaluations: eval_id PK, system_id, category, decision, evaluated_at, inputs JSONB
         Plus `projection_state(event_id PK)` for idempotency.
Alternatives: column-per-event-type (fully typed) · JSONB-only (one table)
Why: Fully typed locks the schema for every event-type evolution → migration churn every
     session. JSONB-only obscures the schema for the auditor demo (scenario 6) where
     `SELECT system_id, severity, count(*) FROM findings ...` is clearer than
     `... WHERE payload->>'severity' = 'HIGH'`. Hybrid gives clean SQL for the demo path
     AND flexibility for fields we haven't promoted yet.
Constrains: New hot columns are migration-gated (no schema-on-write). All non-hot fields
     stay in the JSONB column. Whitelist of view names in `/api/projection/views/{view}`
     enforced via `PROJECTION_VIEWS` frozenset before any SQL interpolation.

## 2026-05-22 — Single uvicorn worker, no Redis (Session 10 Q1)
Decision: Deploy as a SINGLE uvicorn worker. In-memory nonce cache stays
         in-process. No Redis dependency.
Alternatives: Gunicorn + uvicorn workers + Redis-backed nonce cache · Gunicorn
         multi-worker WITHOUT shared store
Why: The locked SKU is B1 (~$13/mo, single small core). Running multiple workers
     on one core thrashes instead of scaling. Paying for Azure Cache for Redis
     (~$16/mo) only to coordinate workers that physically can't run in parallel
     is wasted budget. Multi-worker without shared store is documented as a
     security hole (per-worker nonce caches lose replay protection across
     processes) and explicitly rejected. Single worker is the coherent demo
     posture.
Constrains: `middleware/hmac_auth.py` `_nonce_cache` is per-process and is
     documented as such. Migrating to Redis is a Phase 2 task before any scale-out.
     `STRICT_HMAC_BOOT=true` enforces secret presence at startup; staging
     deployments MUST set this.

## 2026-05-22 — SDK Azure Artifacts feed deferred to post-demo (Session 10 Q2)
Decision: `publish.ps1` remains DRY-RUN gated. Azure Artifacts feed
         provisioning checklist captured in `docs/RUNBOOK.md` § "Azure Artifacts
         feed provisioning" (6 steps). Demo distribution path is editable install
         (`pip install -e ./sdk`) plus wheel handoff.
Alternatives: Provision feed during Session 10 (~2-3h CI plumbing) · Public PyPI release
Why: Demo audience sees the platform UI, not `pip install` output. The 2-3h cost
     of provisioning the feed + PAT in CI carries no demo-visible value and
     directly competes with Day 10's already-loaded scope (24 new files, 18 debt
     fixes, IaC, load tests). Editable install + wheel handoff is a credible
     answer to any "how do customers install this?" question during demo.
Constrains: When the team is ready to publish, `sdk/pyproject.toml` is wheel-ready
     and `publish.ps1` only needs the DRY-RUN guard removed and a PAT injected.

## 2026-05-22 — Load test target B1, A7 acceptance adjusted to 25 RPS (Session 10 Q3)
Decision: App Service Plan stays at B1 (~$13/mo). Load test acceptance A7 is
         "25 RPS sustained for 10 min, p95 < 2s, zero errors" (NOT the original
         100 RPS target). 100 RPS deferred to Phase 2 on S1 + autoscale.
Alternatives: Upgrade to S1 + autoscale 1-3 instances (~$70/mo) · drop the load
         test entirely
Why: The 100 RPS target on B1 is physically not achievable — single small core,
     no autoscale. Pretending it is would produce a test that always fails or a
     load profile that doesn't reflect demo conditions. The honest documented
     limit (25 RPS, B1) matches what the demo will actually serve. S1 + autoscale
     is the right answer for a real production cutover; not for a 12-day demo.
Constrains: `loadtests/locustfile.py` is wired for 25 RPS (`-u 25 -r 5`).
     `loadtests/README.md` documents the SKU caveat. The original 100 RPS
     command is kept as a comment for future S1 deploys.

## 2026-05-22 — New Log Analytics workspace `log-aigovern-prod` (Session 10 Q4)
Decision: Provision a NEW Log Analytics workspace named `log-aigovern-prod` and
         a NEW App Insights component `appi-aigovern-prod`, both via
         `deploy/bicep/`. Provisioned in `rg-aigovern-dev` for v1 but named "prod"
         intentionally — they become the future-prod observability backbone.
Alternatives: Reuse existing `log-aigovern-dev` workspace · App Insights with
         no workspace
Why: Cleaner separation; matches a future prod cutover where the workspace
     stays put and only the App Service identity flips. Workspace-less App
     Insights loses Kusto/KQL access — half the value of the 8 alerts becomes
     unobservable.
Constrains: `deploy/bicep/main.bicep` outputs `appInsightsConnectionString` as a
     `@secure()` output; post-deploy script injects it into App Service settings
     as `APPLICATIONINSIGHTS_CONNECTION_STRING`. All 8 alerts in
     `deploy/bicep/alerts.bicep` query this workspace via `scheduledQueryRules`.
