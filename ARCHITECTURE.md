# AI Assurance Platform — Architecture Reference
# aigovern.sandboxhub.co | Azure | FastAPI + vanilla HTML

> **Source of truth.** Updated at the end of every Claude Code session via `/handoff`.
> For the holistic six-layer model and competitive positioning, see `docs/target-architecture.md`.
> For the WHY behind decisions, see `DECISIONS.md`.

## Stack
Backend: FastAPI (`dashboard.py` entry point)
Frontend: vanilla HTML + `static/shared.js` + `static/shared.css` (no framework, no build)
Storage: JSONL flat files via `storage.py`
Auth: SessionAuthMiddleware (`middleware/auth.py`) — 10-min sliding sessions
Observability: Langfuse Cloud (`tracer.py`) — ⚠ currently leaking raw prompts; fix in Session 01b
Eval: DeepEval (5 metrics today; extending to 6) — `evaluator.py`
Adversarial: Garak — `adversarial.py`
Deployment: Azure App Service Linux Python 3.12 at aigovern.sandboxhub.co

## Architectural decisions (non-negotiable)
- Decorator order: `@policy_gate` → `@scrub_pii` → `@guardrails` → `@trace_llm_call` → `@evaluate_response`
- Scrubber: `tokenise_payload()` runs BEFORE `trace_call()` — hard constraint
- Langfuse: receives `scrubbed_prompt` only — never raw prompt
- Policy engine: OPA fail-closed — error → DENY, never ALLOW
- Guardrails: self-hosted only — no SaaS tools in prompt path; fail-closed on injection/topic/safety violations
- RAG corpus: pre-scrubbed at index time — `index_document()` rejects PII > 0.7
- Memory tiers: T1 in-context · T2 episodic JSONL · T3 RAG (Azure AI Search) · T4 procedural
- DeepEval 6-metric suite: hallucination, relevancy, faithfulness, toxicity, PII leakage, scrub score
- Single-tenant for v1; multi-tenant later

## Files — Built ✓
### Root
`dashboard.py`, `storage.py`, `tracer.py` (⚠ leaks raw prompts), `evaluator.py`,
`guardrails.py` (regex-only), `adversarial.py`, `audit.py`, `report.py`,
`pdf_report.py`, `mock_data.py`, `domains.py` (Tier 4 procedural memory)

### Domain (`domain/`)
`models.py`, `repository.py`, `runtime_connectors.py`, `assessment_engine.py`,
`release_gate_engine.py`, `risk_classification.py`, `findings_workflow.py`,
`evidence_repository.py`, `framework_coverage.py`, `runtime_engine.py`,
`portfolio.py`, `notifications.py`, `governance_guide.py`, `assurance_providers.py`,
`usage_analytics.py`, `reports.py`, `ai_system_edit.py`, `aws_demo_flow.py`

### API (`api/`)
`grc.py`, `runtime_v2.py`, `assessment.py`, `release_gates.py`, `evaluate.py`,
`traces.py`, `findings_v2.py`, `connectors.py`, `demo_run.py`, `reports.py`,
`guide.py`, `assurance_model.py`, `usage.py`, `ai_system_edit.py`, `aws_demo.py`, `demo.py`

### Middleware (`middleware/`)
`auth.py` (5-role: demo-ciso, demo-risk, demo-engineer, demo-reviewer, demo-readonly)

### UI (`static/`)
`index.html` (Command Center), `ai-systems.html`, `findings.html`, `runtime.html`,
`release-gates.html`, `evidence.html`, `governance.html`, `assessment.html`,
`evals.html`, `policies.html`, `reports.html`, `connectors.html`,
`assurance-providers.html`, `framework-sop.html`, `analytics.html`,
`demo.html`, `demo-aws-analyzer.html`, `login.html`, `shared.js`, `shared.css`

## Files — Built (2026-05-21, Sessions 01a + 01b + 02)
### Session 01a (PII scrubbing core)
`scrubber.py` (Presidio NER + regex layer, fail-closed), `domain/deid_vault.py` (Fernet encrypted vault with TTL)

### Session 01b (decorator wiring + tracer patch)
`middleware/scrubber.py` (@scrub_pii decorator), `tracer.py` (hardened: vault_id required when SCRUBBER_ENABLED), `api/demo_run.py` (scrubs prompts before trace_call, vault_id in metadata)

### Session 02 (policy engine + OPA)
`domain/policy_engine.py` (OPA HTTP client + local Python fallback, 5 categories, fail-closed), `domain/trust_scorer.py` (time-decayed trust score from policy history, half-life 7 days), `middleware/policy.py` (@policy_gate decorator, raises PolicyDeniedError on DENY), `policies/base.rego` (org-mandatory), `policies/pii.rego` (posture: us-finserv, gdpr, hipaa), `policies/agent_tools.rego` (team tool authorization), `policies/financial_advisor.rego` (risk-tier critical handling)

### Session 03 (guardrails — NeMo + Llama Guard 3)
`middleware/injection.py` (prompt injection detection via regex + heuristics), `middleware/guardrails.py` (@guardrails decorator orchestrating injection/topic/safety checks), `guardrails/nemo_adapters.py` (topic classification + topic enforcement), `guardrails/llama_guard_adapter.py` (content safety evaluation — 8 categories), `guardrails/financial_advisor_rail.py` (topic rail + guardrail rules for financial advisor), `guardrails/config/financial_advisor_rails.yaml` (NeMo topic rail YAML config).

### Session 04 (memory + RAG — Postgres + Azure AI Search)
`domain/agent_memory.py` (Tier 2 episodic memory backed by Postgres with database-level TTL, inline schema bootstrap, parameterized SQL, scrubber vault_id enforcement, full-text search via tsvector, six public functions: write_episode/build_context/compress_episode/selective_recall/list_episodes/memory_stats/purge_expired), `domain/rag_engine.py` (Azure AI Search hybrid retrieval — BM25 + semantic vector via text-embedding-3-small, index-time PII rejection at confidence > 0.7, auto-disables on missing creds, four public functions: index_document/search_corpus/rag_stats/delete_document), `api/memory.py` (5 endpoints: POST /episodes, GET /episodes, GET /recall, GET /stats, GET /context — all using asyncio.to_thread for sync domain calls), `static/memory.html` (memory viewer UI: stats panel auto-refresh 30s, episode browser, semantic search, context viewer)

## Files — In Progress
None — Sessions 01, 02, 03, and 04 fully complete.

### RAG-related (Session 04)
- `api/rag.py` — new
- `static/rag-governance.html` — new

## Files — Built (2026-05-21, Session 05)
### Session 05 (provider abstraction + legacy cleanup)
`providers/__init__.py` (re-exports five factory functions), `providers/protocols.py` (five runtime_checkable Protocol interfaces: ScrubberBackend, TracerBackend, EvaluatorBackend, MemoryBackend, RagBackend), `providers/config.py` (Pydantic v2 BaseSettings with enum-validated backend choices: presidio|regex|noop for scrubber, langfuse|stdout|noop for tracer, deepeval|noop for evaluator, postgres|jsonl|noop for memory, azure_search|noop for RAG), `providers/registry.py` (five factory functions with lru_cache singleton caching), `providers/backends/__init__.py`, `providers/backends/scrubber_presidio.py` (wraps scrubber._tokenise_impl/_restore_impl), `providers/backends/scrubber_regex.py` (regex-only fallback), `providers/backends/tracer_langfuse.py` (wraps tracer._trace_call_impl), `providers/backends/memory_postgres.py` (wraps domain.agent_memory._write_episode_impl), `providers/backends/rag_azure_search.py` (wraps domain.rag_engine._index_document_impl/_search_corpus_impl/_rag_stats_impl), `providers/backends/noop.py`, `providers/backends/deepeval_evaluator.py` (wraps evaluator._evaluate_impl). Refactored `scrubber.py`, `tracer.py`, `evaluator.py`, `domain/agent_memory.py`, `domain/rag_engine.py` to proxy through providers registry. Deleted `legacy_guardrails.py`; rewrote `api/security.py`, `api/batch.py`, `api/demo_run.py` to use new guardrails package via middleware/injection and guardrails/llama_guard_adapter.

## Files — Built (2026-05-21, Session 06)
### Session 06 (Framework Coverage Matrix — Day 6)
`frameworks/__init__.py`, `frameworks/loader.py` (Pydantic v2 YAML loader; fail-closed on malformed/unknown framework/schema-version; path-confined via `Path.is_relative_to`), `frameworks/eu_ai_act.yaml` (7 items, Art.9-15 high-risk obligations), `frameworks/iso_42001.yaml` (7 items, clauses 4-10), `frameworks/sr_11_7.yaml` (6 items, Fed model risk management), `frameworks/ffiec.yaml` (6 items, IT Examination Handbook AI/ML supplements), `frameworks/us_finserv_overlay.yaml` (7 items, posture overlay additive over base frameworks), `api/frameworks.py` (4 endpoints: GET /matrix, GET /{slug}, GET /{slug}/system/{id}, POST /{slug}/export; evidence drill returns SHA-256 hashes; parallel asyncio.gather for per-item lookups; Content-Disposition filename sanitized), `static/frameworks.html` (console-style matrix UI, color-coded coverage cells, click-to-drill modals, PDF export buttons, escHtml on all interpolations, data-item-id event listeners), 3 new PDF Pack generators in `pdf_report.py` (`generate_nist_pack`, `generate_owasp_pack`, `generate_eu_ai_act_pack`; stdlib-only `_PdfWriter` with pre-allocated object IDs + xref). Modified: `domain/framework_coverage.py` (added `framework_matrix(system_ids)`, `MatrixRow`, `MatrixResult`, `framework_display_name(slug)`, YAML catalog merging via `_ensure_yaml_catalogs()`; MATRIX_FRAMEWORKS expanded to 8 user-facing slugs), `domain/controls.py` (backfilled `framework_mappings` on 40 controls across 8 user-facing frameworks), `domain/release_gate_engine.py` (added `framework_refs` field to `GateDefinition`; populated for 10 gates), `domain/assessment_engine.py` (added `framework_refs` to `FrameworkCoverage`), `domain/models.py` (added `ISO_42001`, `SR_11_7`, `FFIEC`, `US_FINSERV_OVERLAY` to FrameworkName enum), `dashboard.py` (mounted api/frameworks router, served `/frameworks` route), `static/ai-systems.html` (Frameworks tab with per-system framework cards), `requirements.txt` (added PyYAML>=6.0.0).

## Files — Built (2026-05-21, Session 07)
### Session 07 (Multi-Agent + Agent Library — Day 7)
`domain/agents.py` (agent registry: create_agent / get_agent / list_agents / get_version / list_versions / create_version / publish_version with atomic transaction + pg_notify + audit trail / seed_agents with 6 seeded agents at v1.0.0), `domain/agent_bindings.py` (binding lifecycle: bind_agent_to_system / list_bindings_for_system / list_bindings_for_agent / get_binding / update_binding_version / unbind_agent / accept_upgrade with auto-subscribe + audit events), `domain/agent_subscribers.py` (subscription state: subscribe (idempotent upsert) / unsubscribe / list_subscribers / notify_subscribers_on_publish (bulk UPDATE on unpinned bindings) / mark_notified), `domain/seed_systems.py` (6 NEW test systems: sys-payments-001, sys-cx-001, sys-risk-001, sys-platform-001, sys-finserv-001, sys-internal-001 — each bound to 1-3 agents), `migrate.py` (idempotent Postgres DDL for agents/agent_versions/agent_bindings/agent_subscribers; calls seed_agents + seed_test_systems), `api/agents.py` (5 endpoints: GET/POST /api/agents, GET /api/agents/{id}, POST /api/agents/{id}/publish with published_by="api", GET /api/agents/{id}/subscribers — all via asyncio.to_thread), `api/agent_bindings.py` (4 endpoints: GET/POST /api/systems/{id}/bindings, PATCH/DELETE /api/systems/{id}/bindings/{id} — PATCH does ownership check via get_binding before update), `api/agent_notifications.py` (SSE endpoint GET /api/agents/{id}/listen with dedicated psycopg2 connection, quote_ident for LISTEN channel safety, 25s keepalive, clean disconnect cleanup), `static/agent-library.html` (publish/subscribe UI with filter chips, agent card grid, modal with 4 tabs (Overview/Versions/Subscribers/Publish), SSE auto-connect on modal open, 15s polling fallback, 36 escHtml calls), `tests/test_agents_unit.py` (50 unit tests covering CRUD/versioning/subscription/binding lifecycle/semver validation), `tests/test_agent_bindings_integration.py` (20 integration tests via FastAPI TestClient + monkeypatch domain), `tests/test_governance_integration.py` (12 tests for framework_matrix_with_agents / aggregate_agent_risk_tier / evaluate_system_gates agent-aware / get_agent_context / assemble_context). Modified: `domain/models.py` (added Agent / AgentVersion (semver field_validator) / AgentBinding / AgentSubscriber Pydantic v2 models + AgentOwnerType / AgentStatus enums), `domain/repository.py` (added append_agent_event / read_agent_events + EVENTS_FILE), `domain/framework_coverage.py` (added framework_matrix_with_agents / aggregate_agent_risk_tier / EnrichedMatrixResult dataclasses; _agent_framework_coverage supports list[str] "FRAMEWORK:CLAUSE" + list[dict] formats), `domain/release_gate_engine.py` (added evaluate_agent_gates; evaluate_system_gates now agent-aware — fails if ANY bound agent fails gate, names weakest agent in failed_reason), `domain/runtime_engine.py` (added get_agent_context with composite workload_id `{system_id}__{agent_id}__{version_id}`; assemble_context returns dict with per_agent_contexts when bindings exist, string when no bindings — backward compat), `static/ai-systems.html` (Bound Agents drawer section with upgrade banner + Accept/Pin/Unbind/Add actions, all `_escHtmlAis` wrapped), `dashboard.py` (mounted 3 new routers + /agent-library route).

## Files — Built (2026-05-21, Session 08)
### Session 08 (Right-to-Forget Cascade + Tamper-Evident Audit Log — Day 8)
`domain/right_to_forget.py` (cascade orchestrator: vault → T2 → T3 → Langfuse; RTF_* events with SHA-256 per-store digests; cascade_id idempotency; fail-closed on any step failure; PARTIAL_FAILURE on store error; sync inline per locked decision §7.1), `domain/audit_chain.py` (tamper-evident hash chain: compute_event_hash / append_chained_event / verify_chain; SHA-256 plain over canonical JSON excluding hash field; genesis = "GENESIS"; rolling window with checkpoints every 500 events; pre-chain events skipped gracefully), `api/right_to_forget.py` (4 endpoints: POST /api/right-to-forget → 201/207, POST /api/right-to-forget/{id}/approve, GET /api/right-to-forget/{id}, GET /api/right-to-forget), `api/audit_verify.py` (2 endpoints: GET /api/audit/verify?window=N&full=true, GET /api/audit/events?page=N), `static/right-to-forget.html` (request form, approval queue, execution view, verification report with per-store SHA-256 digests), `static/audit-events.html` (paged event list with hash/prev_hash columns, verify button, CLEAN/BROKEN banner). Modified: `domain/repository.py` (append_agent_event now calls audit_chain.append_chained_event; adds hash + prev_hash to every new event record; read_chain_tail(n) helper added; Session 07 MEDIUM debt fixed), `domain/deid_vault.py` (purge_subject_tokens added), `domain/agent_memory.py` (purge_episodes added), `domain/rag_engine.py` (purge_chunks added; flag-gated: LANGFUSE_DELETE_ENABLED), `dashboard.py` (mounts api.right_to_forget.router + api.audit_verify.router; /right-to-forget + /audit-events routes). Tests: `tests/test_audit_chain.py` (8 tests), `tests/test_right_to_forget.py` (6 tests), `tests/test_session08_integration.py` (3 tests).

## Files — Planned
### Sessions 09+ — CLI + SDK + Postgres Projection, Hardening, Demo
- See docs/plans/12-DAY-PRODUCTION-SPRINT.md
- Session 09: CLI + SDK + Postgres Projection (Day 9)
- Session 10: Production Hardening + Deploy (Day 10)
- Session 11: Demo Orchestration + ISO/SR-11-7/FFIEC PDF Packs (Day 11)
- Session 12: Stakeholder Dry-Run + Final Deploy (Day 12)

## Environment variables
### Existing (set on app-aigovern-dev)
- `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`
- `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`
- `EVAL_MODEL=gpt-4o-mini`
- `SESSION_SECRET`

### Added (Session 01a + 01b, applied to Azure App Service)
- `SCRUBBER_ENABLED=true` — Presidio scrubber active
- `DEID_VAULT_TTL_SECONDS=3600` — Default vault entry TTL
- `AZURE_SEARCH_ENDPOINT=https://search-aigovern-dev.search.windows.net` — RAG backend (Session 04)
- `AZURE_SEARCH_KEY` — Azure AI Search admin key (provisioned 2026-05-21)
- `AZURE_SEARCH_INDEX=aigovern-rag-index` — RAG index name
- `POSTGRES_HOST=psql-aigovern-dev.postgres.database.azure.com` — Provisioned westus2
- `POSTGRES_USER=pgadmin`, `POSTGRES_PASSWORD`, `POSTGRES_DATABASE=postgres`
- `DATABASE_URL=postgresql://...` — Full connection string with sslmode=require
- `RAG_EMBEDDING_MODEL=text-embedding-3-small`, `RAG_TOP_K=5`

### Added (Session 02)
- `POLICIES_ENABLED=true` — Policy engine + @policy_gate decorator active
- `OPA_URL` (optional) — OPA sidecar HTTP endpoint; falls back to local Python evaluator

### Added (Session 03)
- `GUARDRAILS_ENABLED=true` — Guardrails enforcement active (injection/topic/safety)
- `INJECTION_DETECTION=true` — Prompt injection detection enabled
- `TOPIC_ENFORCEMENT=true` — Topic validation for workloads enabled
- `LLAMA_GUARD_ENABLED=true` — Llama Guard 3 content safety enabled

### Added (Session 04)
- `MEMORY_ENABLED=true|false` — Tier 2 episodic memory active (Postgres)
- `EPISODE_TTL_SECONDS=2592000` — Default episode TTL (30 days)
- `RAG_ENABLED=true|false` — Tier 3 RAG retrieval active (Azure AI Search)
- `RAG_HYBRID_SEMANTIC_WEIGHT=0.6` — Hybrid scoring weight (0.6 semantic + 0.4 BM25)
- (Existing, now active: `AZURE_SEARCH_ENDPOINT`, `AZURE_SEARCH_KEY`, `AZURE_SEARCH_INDEX`, `RAG_EMBEDDING_MODEL`, `RAG_TOP_K`, `DATABASE_URL`)

### To add (per upcoming sessions)
- `SCRUBBER_BACKEND=presidio` (Session 05)
- `TRACER_BACKEND=langfuse` (Session 05)
- `EVAL_BACKEND=deepeval` (Session 05)
- `OPA_URL=http://localhost:8181` (Session 02)
- `RAG_ENABLED=false` (Session 04, default off)
- `AZURE_SEARCH_ENDPOINT`, `AZURE_SEARCH_KEY` (Session 04)
- `AZURE_SEARCH_INDEX=aigovern-rag-index` (Session 04)
- `RAG_EMBEDDING_MODEL=text-embedding-3-small`, `RAG_TOP_K=5` (Session 04)

## Demo scenario
Financial advisor adversarial: hallucination + PII leakage + compliance failure +
prompt injection attempt + scope violation.
Side-by-side: Claude Sonnet 4.6 vs GPT-4o-mini.

## Verification commands
```bash
python -c "import scrubber; print('scrubber OK')"                              # after Session 01a
python -c "from domain.deid_vault import vault_stats; print('vault OK')"       # after Session 01a
python -c "from domain.policy_engine import evaluate; print('policy OK')"      # after Session 02
python -c "from middleware.injection import detect_injection; print('injection OK')"  # after Session 03
python -c "from middleware.guardrails import guardrails; print('guardrails OK')"     # after Session 03
python -c "from guardrails.nemo_adapters import validate_topic; print('nemo OK')"   # after Session 03
python -c "from guardrails.llama_guard_adapter import evaluate_content; print('llama_guard OK')"  # after Session 03
python -c "from domain.agent_memory import build_context; print('memory OK')"  # after Session 04
python -c "from domain.rag_engine import rag_stats; print('rag OK')"           # after Session 04
python -c "from domain.agents import create_agent, publish_version, get_version; print('agents OK')"  # after Session 07
python -c "from domain.agent_bindings import bind_agent_to_system, get_binding; print('bindings OK')"  # after Session 07
python -c "from domain.agent_subscribers import notify_subscribers_on_publish; print('subscribers OK')"  # after Session 07
python -c "from api.agents import router; from api.agent_notifications import router as nr; print('agent APIs OK')"  # after Session 07
python -c "from domain.right_to_forget import cascade; print('right_to_forget OK')"  # after Session 08
python -c "from domain.audit_chain import verify_chain; print('audit_chain OK')"     # after Session 08
python -c "from api.right_to_forget import router; print('api.right_to_forget OK')"  # after Session 08
python -c "from api.audit_verify import router; print('api.audit_verify OK')"        # after Session 08
python -m pytest tests/ -v                                                     # after Session 08 — expect 99 passed (82 + 17 new)
uvicorn dashboard:app --port 8001 &
curl -s http://localhost:8001/api/rag/stats                                    # after Session 04
curl -s http://localhost:8001/api/policies/stats                               # after Session 02
curl -s http://localhost:8001/api/guardrails/stats                             # after Session 03

# End-to-end scrubber smoke (after Session 01a)
python -c "
from scrubber import tokenise_payload, restore_payload
text = 'Client John Smith SSN 123-45-6789 email john@example.com'
scrubbed, vault_id = tokenise_payload(text, 'verify')
assert 'john@example.com' not in scrubbed, 'FAIL: email leaked'
assert '123-45-6789' not in scrubbed, 'FAIL: SSN leaked'
restored = restore_payload(scrubbed, vault_id)
assert 'john@example.com' in restored, 'FAIL: email not restored'
print('PASS: scrubber end-to-end')
"
```
