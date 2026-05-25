# AI Assurance Platform — Architecture Reference
# aigovern.sandboxhub.co | Azure | FastAPI + vanilla HTML

> **Source of truth.** Updated at the end of every Claude Code session via `/handoff`.
> For the holistic six-layer model and competitive positioning, see `docs/target-architecture.md`.
> For the WHY behind decisions, see `DECISIONS.md`.

> **Visual map (built state):** [`docs/architecture/BUILT-STATE.html`](docs/architecture/BUILT-STATE.html) · [`docs/architecture/BUILT-STATE.svg`](docs/architecture/BUILT-STATE.svg) — 7 diagrams + file matrix + Phase-2 legend (Sessions 01-11).

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
None. (Prior session left stale RAG-related entries here; both shipped in
Session 18 under different paths — `api/rag.py` exists; the UI shipped as
`team-portal/src/pages/rag/RagCorpusPage.tsx` instead of `static/rag-governance.html`.
Cleaned in Session 25.)

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

## Files — Built (2026-05-22, Session 09)
### Session 09 (CLI + Python SDK + Postgres Event Projection — Day 9)
SDK (`sdk/`): `signallayer/__init__.py` (public surface: init, get_client, 5 decorator re-exports, guard, errors, __version__=0.1.0), `signallayer/client.py` (SignalLayerClient with HMAC-SHA-256 signing — canonical input `f"{unix_ts}\n{METHOD}\n{path}\n{sha256_hex(body)}"`, headers X-SL-Key-Id/Timestamp(Unix int)/Nonce/Signature, exponential-backoff retries, Result[T]=Ok|Err), `signallayer/decorators.py` (re-exports of platform decorators with `_sl_decorator_name` stamping for order_guard), `signallayer/order_guard.py` (`guard(fn)` walks `__wrapped__` chain; raises DecoratorOrderError on wrong order, ChainBrokenError on missing decorator; cycle-safe via seen_ids), `signallayer/errors.py` (SignalLayerError + 4 subclasses), `pyproject.toml` (hatchling, Python>=3.12, httpx + cryptography), `README.md`, `examples/billing_agent.py` (degrades gracefully when platform offline), `publish.ps1` (DRY-RUN gated — actual Azure Artifacts upload deferred to Day 10).

CLI (`cli/`): `sl/__init__.py`, `sl/__main__.py`, `sl/main.py` (Typer app: login, onboard, eval run, gate check, trace tail, evidence export; `--version`, `--base-url`), `sl/auth.py` (HMAC-SHA-256 signer matching middleware byte-for-byte), `sl/config.py` (credentials file `~/.signallayer/credentials.json` mode 0600 POSIX; Windows ACL fallback via icacls; env-var override SL_API_KEY/SL_BASE_URL/SL_KEY_ID), `sl/cmd_login.py`, `sl/cmd_onboard.py`, `sl/cmd_eval.py`, `sl/cmd_gate.py`, `sl/cmd_trace.py`, `sl/cmd_evidence.py`, `pyproject.toml` (console_script `sl = sl.main:app`), `README.md`.

Middleware: `middleware/hmac_auth.py` (HMACAuthMiddleware: guards `/api/sdk/*` only; constant-time compare via hmac.compare_digest; drift ±300s; nonce TTL 600s with hard cap 50,000 to prevent memory exhaustion; fail-closed on missing SL_HMAC_SECRET → 500; generic 401 never disclosing which check failed).

Projection: `domain/projection.py` (`project_event(event, conn)` dispatches by event_type to typed upserts; idempotency via `projection_state(event_id PK)` in same transaction; all SQL parameterized; PROJECTION_VIEWS frozenset whitelist), `domain/projection_worker.py` (`run_tailer` reads events.jsonl by byte offset + `SELECT pg_notify(%s, %s)` parameterized + checkpoint to data/projection_tailer_checkpoint.json; `run_projection_worker` LISTENs + dispatches; `replay(from_event_id)` for sync replay; runnable via `python -m domain.projection_worker {tailer|worker}`), `migrations/009_projection_views.sql` (5 hybrid-schema tables: ai_systems, eval_runs, findings, release_decisions, policy_evaluations + projection_state; typed PKs + hot columns + JSONB payload + GIN index per JSONB; all IF NOT EXISTS, re-runnable), `api/projection.py` (3 endpoints: GET /api/projection/status, POST /api/projection/replay (role-gated to ciso/risk/engineer; returns generic "internal_error" on failure — no exception leak), GET /api/projection/views/{view} paged with frozenset whitelist), `static/projection.html` (lag indicator, per-view counts auto-refresh 15s, replay button with confirm dialog).

Tests: `tests/test_sdk_client.py` (24 tests: HMAC determinism + delimiter/format + retry behavior + error mapping), `tests/test_sdk_order_guard.py` (17 tests: correct chain + wrong order + missing decorator), `tests/test_cli_commands.py` (9 tests: login/onboard/gate/evidence — 1 skipped for Windows mode-0600 check), `tests/test_hmac_auth.py` (6 tests: valid/drift/replay/tamper/non-SDK-path/missing-secret), `tests/test_projection_worker.py` (17 tests: 50-event replay + idempotency + checkpoint resume + architectural-invariant grep), `tests/test_session09_integration.py` (8 tests: SDK importable + CLI importable + dashboard router/middleware mount + projection-never-writes-JSONL + projection-never-joins-vault + decorator chain in ARCHITECTURE.md unchanged + HMAC middleware exists + migration file completeness).

Modified: `dashboard.py` (mounts api.projection.router + adds HMACAuthMiddleware OUTERMOST before SessionAuth; preserves existing route order), `middleware/auth.py` (adds `/api/sdk/` to PUBLIC_PREFIXES allowlist), `requirements.txt` (typer>=0.12, psycopg[binary]>=3.2, psycopg-pool>=3.2), `.gitignore` (.signallayer/, sdk/dist/, cli/dist/), `local.env` (SL_HMAC_SECRET, SL_API_BASE_URL, SL_KEY_ID placeholders).

Test count: 179 passing (170 from prior + 9 new integration), 1 skipped (Windows file-mode), 0 errors. Run with `--basetemp=./data/_pytest_tmp` to avoid Windows tmp ACL issue on pre-Session-08 tests.

## Files — Built (2026-05-22, Session 10)
### Session 10 (Production Hardening + Load Tests + IaC — Day 10)
Observability layer (`observability/`): `counters.py` (8 Prometheus Counters with idempotent registration + no-op fallback when prometheus_client absent), `app_insights.py` (`init_app_insights(connection_string)` — idempotent, never raises, never logs any portion of the conn string), `structured_log.py` (JSON-formatted logger; ContextVar-based `request_id` / `role` injection; `default=str` for JSON safety), `middleware.py` (`RequestContextMiddleware` — generates `X-Request-Id` if absent, ContextVar reset in `finally`), `api/metrics.py` (GET /api/metrics — 404 when disabled, 401 with constant-time token compare, Prometheus exposition format).

IaC (`deploy/bicep/`): `main.bicep` (composes workspace + App Insights + 8 alerts; `@secure()` connection-string output; references existing ASP/web-app as `Ignore` rather than recreating), `appinsights.bicep` (Log Analytics workspace `log-aigovern-prod` PerGB2018 30-day retention + workspace-based App Insights), `alerts.bicep` (8 scheduledQueryRules: pii-leak, opa-unreachable, vault-error, audit-chain-broken, http-5xx-rate, p95-latency, rtf-partial-failure, scrub-rate-regression), `parameters.dev.json`, `README.md`.

Load tests (`loadtests/`): `locustfile.py` (4 weighted tasks: scrub 60%, policy 20%, framework 10%, health 10%; 25 RPS sustained per Q3 B1 decision), `scrubber_perf.py` (10k payload microbench, p95 < 100ms; trial p95 = 6.3ms), `opa_p95.py` (1000 policy evals, p95 < 50ms), `framework_coverage_perf.py` (50 framework_matrix calls, median < 2s, exit 2 if no seeded systems), `README.md` (thresholds + SKU caveat).

Security scan + smoke: `deploy/security_scan.ps1` (bandit + pip-audit + secrets-grep with patterns for AWS/Anthropic/OpenAI/Slack/GitHub/GitLab/Postgres/Azure Storage; aggregate report to `data/security_scan_report.json`), `deploy/smoke_e2e.ps1` (6 demo scenario probes; dev/staging allowlist guard refuses to send synthetic PII to prod URLs unless `SMOKE_ALLOW_PROD=true`).

Runbook: `docs/RUNBOOK.md` (8 alert definitions + paging; rollback steps; KQL snippets for trace lookup, PII detections, RTF audit; Azure Artifacts feed 6-step checklist; STRICT_HMAC_BOOT toggle).

Tests: `tests/test_session10_hardening.py` (HMAC byte-equality across 3 signers; STRICT_HMAC_BOOT; /api/health no api_keys leak; audit chain writer-lock; 100-thread concurrent appenders → CLEAN; RTF sidecar; audit_events role gate; save_credentials atomic open POSIX), `tests/test_session10_observability.py` (25 tests: counter idempotency + missing-library fallback, App Insights no-op + bad-config tolerance, RequestContextMiddleware ContextVar reset, /api/metrics gate matrix), `tests/test_session10_perf_smoke.py` (12 tests: microbench importability, threshold constants frozen as module-level guards, graceful skip when systems not seeded).

Debt fixes closed (18 items): hmac_auth `_SECRET` cached at import + `STRICT_HMAC_BOOT`; cli/sl/config atomic `os.open(O_CREAT|O_WRONLY|O_TRUNC, 0o600)`; dashboard.py `.env` parser removed + `/api/health` strips `api_keys` + RequestContextMiddleware mounted + metrics router + App Insights init; projection.py dead `_DISPATCH` removed + rollback wrapped; cli/sl/main.py `bool | None`; api/audit_verify.py `require_role("auditor", "ciso")` + `public_mode` (RECURSIVE strip — fixed post-review) + absolute `from_index`; agent_memory `metadata->>'subject_id' = %s` + `idx_episodes_subject_id`; rag_engine `$skip` pagination (FAIL-CLOSED on cap exhaustion — fixed post-review); audit_chain module-level prev_hash + chained_count cache + `portalocker` advisory lock + warm-start docstring honest (fixed post-review); right_to_forget sidecar `rtf_completed_index.jsonl` + LRU 1000 cache + `_store_funcs` removed + warning log on sidecar/events disagreement (fixed post-review); counter hooks added to scrubber/policy/injection/policy_engine/deid_vault/audit_chain/right_to_forget/evaluator.

Critical post-review fixes: (1) `require_role()` with empty `allowed_roles` now raises `ValueError` (previously short-circuited and opened access in dev). (2) `_strip_public` is now recursive — nested PII inside `payload` sub-dicts is stripped at every depth. (3) `purge_chunks` cap raises `RuntimeError` instead of warn-and-continue — forces RTF cascade `PARTIAL_FAILURE`. (4) App Insights conn-string prefix no longer logged. (5) `smoke_e2e.ps1` host allowlist guard prevents accidental PII send to prod. (6) secrets-grep patterns broadened (Anthropic, Postgres, Azure Storage, SAS). (7) `_seed_cache_from_file` docstring corrected (full file scan, not reverse-tail).

Modified: `requirements.txt` (+opentelemetry-sdk, +azure-monitor-opentelemetry-exporter, +prometheus-client, +portalocker, +cachetools), `requirements-dev.txt` NEW (+locust, +bandit, +pip-audit), `local.env` placeholders for APPLICATIONINSIGHTS_CONNECTION_STRING / METRICS_ENABLED / METRICS_TOKEN / STRICT_HMAC_BOOT / LOCUST_TARGET.

Test count: 224 passing (179 prior regression + 45 new across hardening/observability/perf-smoke), 3 skipped (Windows file-mode-0600 POSIX-only + seeded-systems perf bench + one prior skip), 0 errors.

## Files — Built (2026-05-22, Session 11)
### Session 11 (Demo Orchestration + ISO/SR-11-7/FFIEC PDF Packs — Day 11)
Demo control: `api/demo_control.py` (orchestrator endpoints driving the 6 financial-advisor scenarios end-to-end through the full decorator chain; talk-track aligned with `docs/demo-scripts/`), `static/demo-control.html` (operator console for running scenarios live during stakeholder demos). 3 additional PDF packs in `pdf_report.py` extending the stdlib `_PdfWriter`: `generate_iso_42001_pack`, `generate_sr_11_7_pack`, `generate_ffiec_pack`. Talk tracks: `docs/demo-scripts/scenario-1.md` through `scenario-6.md` + `docs/DEMO-QA.md`.
Modified: `dashboard.py` (mounted demo_control router + `/demo-control` route).

## Files — Built (2026-05-23, Session 12)
### Session 12 (Stakeholder Dry-Run + Final Deploy — Day 12)
The day was dominated by a deploy outage that exposed a long-latent gap: `deploy/build-zip.py`'s INCLUDE allowlist had drifted behind the source tree. The stale container had been masking it for weeks; antenv rebuild on a fresh deploy detonated it.

Recovery: `deploy/build-zip.py` (added `guardrails/`, `frameworks/`, `observability/`, `policies/`, `scrubber.py`, `observability_compat.py`, `providers/` — 7 missing top-level entries), `requirements-deploy.txt` (restored module-load-time packages dropped during a prior slim-down). 5-phase recovery plan: `docs/plans/SESSION-12B-PROD-RECOVERY.md`.

V2 architecture spec: `docs/plans/V2-PORTAL-SPLIT.md` (1 engine + 2 SPAs + CLI/SDK; 22 surfaces, 16 acceptance criteria, 5-week estimate). Supersedes §1.9 in `12-DAY-PRODUCTION-SPRINT.md`.

Smoke fix: `deploy/smoke_e2e.ps1` (login flow for hardened AUTH_ENABLED=true targets). Bicep fix: `deploy/bicep/alerts.bicep` (workspace-mode KQL + parameters cleanup).

Commits: `76cf606` (Bicep) → `c095850` (smoke login) → `b33d59a` (V2 plan) → `dad83ae`+`e99cfdc`+`56630c7` (recovery rounds). Two intermediate commits (`019e1c8`/`99d09dc`) attempted App Insights instrumentation, crashed prod, were reverted by `418440c` — App Insights remains DEFERRED to a session with a Docker staging slot.

## Files — Built (2026-05-23, Session 12B — Day-12 close-out)
### Session 12B (8 root-cause smoke fixes — 6/6 PASS)
Single commit `53ebd4a` resolving 8 distinct bugs surfaced by the prod smoke run. Tag `day-12-complete` at this commit.

`middleware/guardrails.py` — added `_extract_text()` helper + tolerant `check_output()`. Was: `AttributeError: 'dict' object has no attribute 'lower'` when handlers returned the `_build_run()` dict instead of a string. Decorator contract now coerces structured returns via prioritized field lookup (`response_text` → `actual_output` → `text` → `response` → `output` → `content` → `str()` fallback).

`audit.py` — scoped audit format to a dedicated logger with `propagate=False`. Was: `logging.basicConfig(format='%(action)s ...')` mutated the ROOT logger, so every other module's `logger.warning()` without `extra={"action": ...}` crashed with `KeyError: 'action'`. Now: private `_AUDIT_FMT` on a non-propagating `audit_logger` with idempotent handler install.

`guardrails/llama_guard_adapter.py` — keyword matcher now uses `re.compile(r'\bkw\b')` with `@lru_cache`. Was: substring matching had massive false positives ("cut" matched "calculate", "harm" matched "pharmaceutical", "kill" matched "skillfully"). Any portfolio-related LLM response was flagged VIOLENCE+SELF_HARM.

`api/demo_run.py` — `_run_claude_wrapper` and `_run_openai_wrapper` now catch `GuardrailViolationError` and surface as structured error in the run record. Was: `strict=True` decorator raised, exception escaped `asyncio.gather`, endpoint returned 500. Demo blocks are demo material, not crashes.

`dashboard.py` — added `@app.on_event("startup")` calling `seed_agents()`. Was: 6 agents existed in `domain.agents.seed_agents()` but nothing called it. Postgres unavailable on App Service so agents are in-memory only; startup hook matches that lifecycle.

`domain/agents.py` — added `_inmem_agents: dict[str, Agent]` shared between `create_agent` (fallback path) and `list_agents`. Was: `create_agent` returned an Agent in-memory but `list_agents` only queried Postgres, so the seeded agents were invisible.

`deploy/smoke_e2e.ps1` — Scenario 2 path corrected to `/api/grc/release-gates/v2/systems`. Scenario 5 path corrected to `/api/analytics/trends`. Scenario 1 assertions corrected to read from `runs[0]` (response shape was wrapped); demo prompt phrased neutrally for safety-scan friendliness.

`requirements-deploy.txt` — added `pydantic-settings>=2.0.0`. Was: `providers/config.py:24` lazy-imports `BaseSettings`; missing in slim deploy reqs → first LLM call crashed. Second hit of the same drift class as Day-12 (the underlying cause is captured-but-not-yet-tested-for in carry-over `tests/test_deploy_completeness.py`).

App Service config (not in git): `EVAL_BACKEND=noop` set on `app-aigovern-dev`. Avoids `deepeval` import (~800 MB transitive deps, intentionally not shipped). To be captured as a fresh-deploy requirement in `docs/plans/SESSION-12B-PROD-RECOVERY.md` §6.

Verification: `pwsh deploy/smoke_e2e.ps1` returns **6/6 PASSED** against `https://aigovern.sandboxhub.co`. Tag `day-12-complete` pushed to origin.

## Files — Built (2026-05-24, Session 16)
### Session 16 (Phase 2 Week 2 follow-ups #14–#20 — Team Workspace SPA)
Three commits on `phase/14-team-workspace-scaffold`, closing all remaining disabled-button gaps from Session 15.

`7e35900` (#17 Evals): `team-portal/src/pages/evals/types.ts` (added `SimulatedRunResponse` + `RefreshedEval` + `AssessmentSummary` + `GateRollup` mirroring `api.evals_v2.SimulatedRunOut`), `team-portal/src/pages/evals/EvalsPage.tsx` (export `reloadEvalsOverview` so the card can refresh parent KPIs), `team-portal/src/pages/evals/SystemEvalCard.tsx` (wired the previously-disabled "Run Simulated Eval Suite" button → `POST /grc/evals/v2/run/{ai_system_id}`; module-level `running` / `lastRun` / `actionError` signals; cache-bust + detail re-fetch on success; "Last run … · N evals · gates {decision}" chip).

`ca74efd` (#14 + #15 + #16 Runtime bundle): new `team-portal/src/pages/runtime/RuntimeModals.tsx` colocating three signal-driven modals (state-change, request-approval, create-incident) + shared `runtimeActionError` signal + `registerRuntimeReload` callback (avoids circular imports without registering through a parent). `team-portal/src/pages/runtime/SystemStates.tsx` (3 buttons wired to `openStateChange` — kill-switch reason required, monitoring picks STANDARD|HEIGHTENED|INCIDENT, enable/disable toggles via the same modal). `team-portal/src/pages/runtime/RuntimePage.tsx` (+ Request on the Approval Queue card → `openRequestApproval`; mount `<RuntimeModals />`; render `runtimeActionError` above KpiRow). `team-portal/src/pages/runtime/EventStream.tsx` (row click → `openCreateIncident(event)` pre-fills `from_event_id` + `ai_system_id` + severity-mapped). Engine endpoints: `POST /grc/runtime/v2/state/{id}/{kill-switch|reset-kill-switch|monitoring|enabled}`, `POST /grc/runtime/v2/approvals`, `POST /grc/runtime/v2/incidents`. Actor hardcoded to `demo-engineer`.

`79c8486` (#18 + #19 + #20 Agent Library bundle): new `team-portal/src/pages/agent-library/AgentCreateModal.tsx` (name / team / description / owner_type / inherent_risk; `POST /agents`; `registerAgentsReload` callback). `team-portal/src/pages/agent-library/AgentModal.tsx` rewritten: `PublishTab` replaces `PublishTabStub` (semver MAJOR.MINOR.PATCH + changelog → `POST /agents/{id}/publish`; success badge; reloads agent detail). `useAgentSse(id)` hook opens `EventSource` to `GET /agents/{id}/listen` on modal open; `sseState` signal cycles connecting → open → closed; `agent_update` event → reload detail; cleanup on close; footer dot turns green/amber/gray. `team-portal/src/pages/agent-library/AgentLibraryPage.tsx` (+ Register button enabled, registers reload callback, mounts `<AgentCreateModal />`).

Engine fixes uncovered during smoke verification (folded into the Agent Library commit since they were prerequisites):
- `api/agents.py` `POST /api/agents`: Pydantic `Literal` validates the string but `domain.agents.create_agent` calls `.value` on it. Coerce to `AgentOwnerType` / `RiskLevel` enums at the boundary before delegating.
- `domain/agents.py`: extended Session 12B's `_inmem_agents` pattern to versions. New `_inmem_versions: dict[str, AgentVersion]` + in-memory paths for `create_version` (store), `publish_version` (validate DRAFT, mutate status, update `agent.latest_version_id`, best-effort audit + subscriber-notify matching DB-path semantics), `get_version`, `list_versions`. Without this, publish raised `RuntimeError` in dev (no `DATABASE_URL`). This is a depth gap from Session 12B that surfaced only when the publish UI got wired — the read paths were covered, the write path wasn't.

Verification: all 7 endpoints reached end-to-end through the Vite proxy (200/201), all UI flows driven via `preview_eval` (modals open/submit/close, state refreshes, no console errors). No PR opened per user direction — branch accumulates for now.

## Files — Built (2026-05-24, Session 17)
### Session 17 (Phase 2 Week 3 — Team Workspace SPA surfaces 8/2/10/11)

Four commits on `phase/14-team-workspace-scaffold`. Brings Team Workspace from
4/12 surfaces to **9/12**. Zero engine endpoint changes; all four surfaces
consume existing APIs through the Vite `/api/v1/*` → engine `/api/*` proxy.

`fe99a6e` (#8 Memory inspector + V2 plan addendum + hygiene): new
`team-portal/src/pages/memory/{types.ts,MemoryPage.tsx}` — four-panel SPA
decompose of V1 `static/memory.html`. Module-level signals (`stats`,
`episodes`, `recallResults`, `ctxResult`) matching the Phase 2 pattern.
Stats KPIs auto-refresh every 30s via `window.setInterval` cleanup-on-unmount.
Endpoints: `GET /api/memory/stats`, `GET /api/memory/episodes`,
`GET /api/memory/recall`, `GET /api/memory/context`, plus
`GET /api/domains/` for the workload picker.
Also in this commit: `.gitignore` now excludes `ai-systems-inventory-*.csv`
(session-produced exports). `docs/plans/V2-PORTAL-SPLIT.md` §3 gets a Decision
Log table — first entry locks Findings to CISO Console only (rejected dual-
home framing from the Session 17 handoff prompt; reversible if engineers
later need a filtered Team view).

`258c89f` (#2 SDK Quickstart): new
`team-portal/src/pages/sdk-quickstart/SdkQuickstartPage.tsx` — pure display
surface. System picker reuses `/api/grc/ai-systems` (zero new endpoints).
Snippet template mirrors `sdk/README.md` so divergence is visible at code-
review time; `scope` ← `system.domain`, `workload_id` ← `system.id`. Per-card
Copy button with 1.5s "Copied!" flash. Four code blocks: install command,
env file, decorator stack, plus a "selected system context" sanity panel
showing what got baked into the snippet.

`5f78bad` (#10 RTF engineer side): new
`team-portal/src/pages/rtf/{types.ts,RtfRequestPage.tsx}` — form-driven
cascade submission + own-history table. Client-side validation mirrors the
Session 08 server validator (subject_id `[A-Za-z0-9._@\-]+`, ≤256 chars;
reason 1-1024 chars). Submit button disabled until both fields valid; success
banner shows cascade_id, status, and store/items-removed summary; list
auto-refreshes. List is reverse-sorted (newest first) — the V1 envelope
returns oldest-first per audit §1.1; engineer UX wants newest-first.
Hardcoded `actor = "demo-engineer"` matching the Session 16 pattern.
Per-store SHA-256 forensics and approval queue stay on CISO Console per
V2-PORTAL-SPLIT.md §3.
Verified end-to-end: `POST /api/right-to-forget` returned 201, cascade ran
across vault · tier2 · tier3 · langfuse.

`47af837` (#11 My Portfolio): new
`team-portal/src/pages/portfolio/PortfolioPage.tsx` — dashboard view
(KPIs + risk distribution + top-N by findings), complementary to the AI
Systems CRUD list rather than duplicating it. All four panels are pure
`computed()` projections off `/api/grc/ai-systems` — no new endpoints, no
chart-library dependency (runtime mix is a string breakdown).
Own-team filter is a client-side All/My team toggle. "My team" matches on
`business_owner` / `technical_owner` string containment of the actor token.
Defaults to "All" so dev renders non-empty; "My team" honestly returns 0
in dev (no seeded match for "demo-engineer") and shows an explicit stub-
mode banner rather than faking matches. Swap to engine-side `?scope=` when
session auth wires the real actor in Phase 3.

All four routes registered in `team-portal/src/app.tsx`; nav items added in
`team-portal/src/shared/components/Sidebar.tsx`. Sidebar now: AI Systems,
Runtime, Evals, Agent Library, Memory, SDK Quickstart, Right-to-Forget,
My Portfolio.

PR: [signalyer/ai-assurance-mvp#1](https://github.com/signalyer/ai-assurance-mvp/pull/1)
(draft) — accumulates all of Sessions 14-17 (17 commits). Branch pushed to
origin at `47af837`.

## Files — Built (2026-05-24, Session 18)
### Session 18 (Phase 2 Week 3 close-out — Team Workspace SPA surfaces 9 + 5)
Brought count from **9/12 → 11/12** (only #3 remains, locked-deferred per
V2 risk register §9). Two engine deltas added with ADR-style justification,
both because the *engine* layer existed since prior sessions but the *HTTP*
layer had never been wired:

| # | File | Purpose |
|---|---|---|
| #9 RAG | [api/rag.py](api/rag.py) | NEW. Thin router over `domain/rag_engine.py`. GET /stats, POST /search, POST /documents, DELETE /documents/{id}. Async via `asyncio.to_thread` over sync httpx + OpenAI SDK. Fail-soft when RAG disabled (200 OK with `rag_enabled:false`, never 500). |
| #9 RAG | [team-portal/src/pages/rag/RagCorpusPage.tsx](team-portal/src/pages/rag/RagCorpusPage.tsx) | NEW. Stats KPIs + search + index form + delete. Mirrors `RtfRequestPage` mutation template. |
| #5 Adv | [adversarial.py](adversarial.py) | Added `run_adversarial_suite_streaming()` generator. Original `run_adversarial_suite()` unchanged — additive, not a rewrite. |
| #5 Adv | [api/adversarial.py](api/adversarial.py) | NEW. GET /categories + POST /run returning **text/event-stream** (SSE). First SSE surface in the portal. Sync generator drained via `asyncio.to_thread(next, gen, sentinel)` so the event loop stays responsive while LLM probes block. Errors after stream start surface as an `error` SSE event, not HTTP 500. |
| #5 Adv | [team-portal/src/pages/adversarial/AdversarialPage.tsx](team-portal/src/pages/adversarial/AdversarialPage.tsx) | NEW. Uses `fetch + ReadableStream` (not EventSource — EventSource is GET-only; needed POST + JSON body). Manual SSE frame parser splits on `\n\n`. Results table fills row-by-row; live progress bar + elapsed timer; final KPIs on `done` event. |

CI workflow drift fixed in same session:
- [.github/workflows/contract-tests.yml](.github/workflows/contract-tests.yml) — schemathesis v4 renamed `--hypothesis-max-examples` → `--max-examples` and removed `--hooks`; hooks now load via `SCHEMATHESIS_HOOKS=ci.schemathesis_hooks` env var (PEP 420 namespace package, no `__init__.py` needed).
- Same fix applied to [.github/workflows/contract-tests-nightly.yml](.github/workflows/contract-tests-nightly.yml).

PR: PR #1 squash-merged at [`3b246aa`](https://github.com/signalyer/ai-assurance-mvp/commit/3b246aa) (10/12 cut), then 3 post-PR commits cherry-picked directly to main ([`e4b7886`](https://github.com/signalyer/ai-assurance-mvp/commit/e4b7886), [`7aec9d9`](https://github.com/signalyer/ai-assurance-mvp/commit/7aec9d9), [`4ad2515`](https://github.com/signalyer/ai-assurance-mvp/commit/4ad2515)) per user "don't create any more PRs" rule after PR sync got stuck. Stale `phase/14-team-workspace-scaffold` branch deleted from origin.

Compound rules earned this session:
- **Session 18a:** GitHub PR head can desync from branch ref when webhook delivery silently fails. `gh pr view --json headRefOid` is the canary; force re-sync via close+reopen if stuck. Empty-commit nudges do NOT fix it.
- **Session 18b:** schemathesis v4 dropped `--hooks` and `--hypothesis-*` prefixes. If contract-tests fails with "No such option", check for upstream CLI breakage before treating as a contract regression.
- **Session 18c:** SSE for long-running probes — drain a sync generator with `await asyncio.to_thread(next, gen, sentinel)` per iteration. Don't use `async for` directly over a sync generator; the event loop blocks on every iteration.

## Files — Built (2026-05-24, Session 19)
### Session 19 (CI auto-deploy + drift detection)
Closed the "is it actually live?" gap that left every prior session's merge
unverified in prod. Before this session, deploys required manual
`python deploy/build-zip.py` + `pwsh deploy/deploy-and-poll.ps1`. Prod was
serving stale code of unknown vintage — possibly back to before Session 13
(see #1 below).

| # | File | Purpose |
|---|---|---|
| #1 | [.github/workflows/deploy.yml](.github/workflows/deploy.yml) | NEW. Push-to-main triggers zip build + `azure/webapps-deploy@v3` + post-deploy SHA-match verification. `concurrency: deploy-app-aigovern-dev` with `cancel-in-progress:false` (never cancel mid-flight; config-zip is non-atomic). Auth via OIDC federated credential — no long-lived secret. |
| #1 | [dashboard.py](dashboard.py) | `_read_build_sha()` reads `BUILD_SHA` file baked into zip; `/api/health` now returns `{"status","sha"}` so deploy verification works without auth. |
| #1 | [deploy/build-zip.py](deploy/build-zip.py) | `_resolve_sha()` prefers `GITHUB_SHA` (CI) then `git rev-parse HEAD` (local). Writes `BUILD_SHA` to zip. Also adds `__version__.py` to INCLUDE whitelist — missing since Session 13. |
| #1 | [docs/openapi-v1.json](docs/openapi-v1.json) | Regenerated for new `/api/health` response shape. |

**Azure identity (created out-of-band):**
- Entra app `github-deploy-aigovern` (appId `7899ac3e-ad16-415e-9780-192bd9e94c3b`)
- Two federated credentials: `repo:signalyer/ai-assurance-mvp:ref:refs/heads/main` and `repo:signalyer/ai-assurance-mvp:environment:production`
- RBAC: `Website Contributor` on `app-aigovern-dev` only (least privilege)
- GitHub repo variables (not secrets): `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`

**First deploy validated the design.** The SHA-match step caught a silent
failure on first run: the deploy succeeded but `/api/health` returned a SHA
that didn't match the commit. Diagnosis: `dashboard.py` line 72
`from __version__ import __version__` (added Session 13) had never been
shipped — the build-zip whitelist was never updated. Adding the file to
INCLUDE produced a green deploy. **Prior prod was serving pre-Session-13
code.**

Compound rules earned this session:
- **Session 19a:** App Service SCM Basic Auth is OFF by default on modern provisions. `webapps-deploy@v3` with a publish profile fails 'Publish profile is invalid' even though the XML looks right. Use OIDC federated credentials instead — no security regression, no secret rotation.
- **Session 19b:** az CLI 2.85.0 has a bug where `az role assignment create` returns `MissingSubscription` even with explicit `--subscription` and subscription set as default. Workaround: `az rest --method PUT` directly against `https://management.azure.com/.../roleAssignments/{guid}?api-version=2022-04-01`. Body needs `principalType: ServicePrincipal` when assigning to a brand-new SP (replication lag).
- **Session 19c:** `deploy/build-zip.py` uses an explicit whitelist (not a `.funcignore` blacklist) so missing files fail visibly — but only if you actually run the deploy. Without CI auto-deploy, the whitelist drift accumulated silently for 6 sessions. Compound: any explicit-allowlist deploy needs CI to enforce its own correctness.
- **Session 19d:** Verify deploys with a SHA round-trip, never a 200 health check. `/api/health` 200 means a container is serving — not the container you just shipped. Bake commit SHA into the deploy artifact at build time, verify at smoke-test time.

## Files — Built (2026-05-24, Session 20)
### Session 20 (adversarial.py tech debt cleanup)
Cleared two pre-existing rule violations flagged in Session 18's risk register,
now safe to refactor because Session 19's SHA round-trip catches regressions
in ~90s.

| # | File | Purpose |
|---|---|---|
| #1 | [adversarial.py](adversarial.py) | Lazy-imported `anthropic` + `openai` SDKs inside `run_single_probe()` (was module-top-level). `/api/adversarial/categories` no longer drags in either SDK transitively. |
| #1 | [adversarial.py](adversarial.py) | Parallelized probe execution in both `run_adversarial_suite()` and `run_adversarial_suite_streaming()` via `ThreadPoolExecutor(max_workers=5)` + `as_completed`. Sync-generator interface preserved so the SSE wrapper's `asyncio.to_thread(next, gen, sentinel)` drain pattern (Session 18c) keeps working unchanged. 13-probe wall clock: ~40-60s → ~10-15s. |
| #2 | [tests/test_adversarial_lazy_imports.py](tests/test_adversarial_lazy_imports.py) | NEW. AST-walks `adversarial.py` asserting no top-level `import anthropic`/`import openai`. Plus a runtime check that neither symbol leaks into the module namespace at import time. Belt-and-suspenders against regression. |

**SSE protocol stability.** Event shape verified compatible with the SPA
consumer at `team-portal/src/pages/adversarial/AdversarialPage.tsx`:
`start` / `probe` / `done` event names unchanged; `probe` events still carry
`{index, total, category, probe_name, severity, resisted, confidence, reason,
error, latency_ms}`. `index` now reflects completion order (not submission
order), which is fine — the SPA uses it for the row key and a progress
counter, both of which only require uniqueness ≤ total.

Compound rules earned this session:
- **Session 20a:** When parallelizing a sync generator that already drives an SSE stream, keep it sync — don't convert to async. The wrapping `asyncio.to_thread(next, gen, sentinel)` pattern is the contract; converting the inner generator to `async def` would force a rewrite of the wrapper and break the "engine is sync, transport is async" separation. Use `ThreadPoolExecutor` + `as_completed` inside the sync generator instead.
- **Session 20b:** Session 19d's "200 ≠ fresh" rule applies to the *readiness* check, not just the final verifier. The first Session 20 deploy failed because the wait loop broke on `code=200` after 10s — but App Service was still serving the previous container during the zip-swap window. Collapse "wait for ready" + "verify SHA" into a single loop that polls until `live_sha == GITHUB_SHA`. Any intermediate 200 is meaningless; only SHA match proves the swap completed.

## Files — Built (2026-05-24, Session 21)
### Session 21 (CI hygiene: Node 24 + OpenAPI export reproducibility)
Pure CI hardening — no app-code change. Two carried items closed:

| # | File | Purpose |
|---|---|---|
| #1 | [.github/workflows/deploy.yml](.github/workflows/deploy.yml) | Added `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: 'true'` at job-scope env. Validates the Node 24 runtime flip on our schedule, ahead of the GitHub-forced 2026-06-02 cutover. |
| #1 | [.github/workflows/contract-tests.yml](.github/workflows/contract-tests.yml) | Same flag, alongside the existing `SL_OPENAPI_STRICT: 'false'`. |
| #1 | [.github/workflows/contract-tests-nightly.yml](.github/workflows/contract-tests-nightly.yml) | Same flag. New job-level `env:` block. |
| #2 | [scripts/export_openapi.py](scripts/export_openapi.py) | Replaced `os.environ.setdefault()` with an explicit `SL_OPENAPI_EXPORT_PROFILE` switch. Default `ci` force-sets the canonical env (caller's shell loses); `local` opts back into setdefault behavior for debugging. Output is now byte-reproducible across machines regardless of shell pollution. |

**Validation:** deploy run 26374360142 (commit 1231cd4) ran green under Node 24 in 1m04s — annotation explicitly confirms `actions/checkout@v4`, `actions/setup-python@v5`, and `azure/login@v2` were forced onto Node 24. `docs/openapi-v1.json` regenerated under the new `ci` profile produced a zero-byte diff (existing artifact already canonical).

**Env contract** (`SL_OPENAPI_EXPORT_PROFILE`):
- `ci` (default) — pins `EVAL_BACKEND=noop`, `SCRUBBER_BACKEND=regex`, `TRACER_BACKEND=noop`, `MEMORY_BACKEND=noop`, `RAG_BACKEND=noop`, `POLICY_BACKEND=noop`, `SL_OPENAPI_SKIP_STARTUP_CHECK=true`. Caller's shell env loses. **This is the only profile whose output is committable.**
- `local` — legacy setdefault: shell env participates. Useful for inspecting route registration under a real backend, but the output **must not** be committed.

Compound rules earned this session:
- **Session 21a:** `os.environ.setdefault()` in a build/export script is nondeterminism waiting to happen. It looks like a defensive guard but is really "trust whatever the shell happens to leave alone." For any artifact whose drift triggers CI gates, force-set the env contract explicitly and document the profile. Reserve setdefault for opt-in debugging modes.
- **Session 21b:** When GitHub deprecates a runner-level dependency (Node 20→24), prefer the workflow-scope env flag (`FORCE_JAVASCRIPT_ACTIONS_TO_NODE24`) over bumping every action version. The env flag is reversible (delete one line); version bumps compound with each action's own breaking changes (`actions/checkout@v5` may change defaults). Only bump versions when an action gains a feature you actually want.

## Files — Built (2026-05-24, Session 22)
### Session 22 (CI hygiene: deploy path filter)
Pure CI change — no app code touched. Closes the Session 21 carry-over:
doc-only / CI-only pushes were triggering full 3-min App Service redeploys.
Session 21's own commits (`1231cd4` workflow + `7c86b8d` script + `ad1f98f`
plan) each fired a deploy that proved nothing about runtime behavior.

| # | File | Purpose |
|---|---|---|
| #1 | [.github/workflows/deploy.yml](.github/workflows/deploy.yml) | Added `paths-ignore` block under `on.push`: `docs/**`, `**.md`, `.github/workflows/contract-tests*.yml`. Path filters are per-push (not per-file), so any mixed code+doc commit still deploys. `workflow_dispatch` retained as escape hatch for wrongly-skipped pushes. |

**Done criteria:** a doc-only follow-up commit shows zero new entries in the
deploy workflow's run history. A code-touching commit deploys as before.

Compound rules earned this session:
- **Session 22a:** GitHub's `paths-ignore` is evaluated against the union of changed files in the push, not file-by-file. A commit that changes one `.py` and ten `.md` files still triggers the workflow. This is the correct safety semantic for a deploy filter — opposite of how a naive reader might interpret "ignore." Document this explicitly in any path-filtered workflow; it's the question every future maintainer will ask.
- **Session 22b:** Keep `workflow_dispatch` on every deploy workflow that has a path filter. Path filters are a heuristic for "what can affect the running app"; the heuristic will sometimes be wrong (e.g. a `MANIFEST.in`-style packaging file that looks like config but ships into the zip). Manual re-trigger costs nothing and unblocks the edge case without weakening the filter.

## Files — Built (2026-05-24, Session 23)
### Session 23 (ADR-001 Garak + deploy completeness test)
Two carry-overs closed in one session: Track B (Garak integration design)
landed as an ADR rather than code, and V1 debt
`tests/test_deploy_completeness.py` was finally written.

| # | File | Purpose |
|---|---|---|
| #1 | [docs/adr/ADR-001-garak.md](docs/adr/ADR-001-garak.md) | NEW. First ADR in the repo. Decides **subprocess via dedicated Azure Container App sidecar** (`ca-aigovern-garak-dev`) for Garak integration. Rejects library-import (violates Session 12 slim-deploy invariant — Garak's torch/transformers transitives are ~1.5 GB) and full HTTP service (defer to V2 multi-tenancy). Garak suite is **additive** to `adversarial.py`, not replacement: presented as "Quick Smoke" (in-house, ~10s) vs "Deep Scan" (Garak, 1-10 min). New endpoint `POST /api/adversarial/deep-scan` mirroring the Session 18c SSE contract. Includes 6-step implementation plan deliberately scoped to a *future* session — this session is design only. |
| #2 | [tests/test_deploy_completeness.py](tests/test_deploy_completeness.py) | NEW. Catches the Session 12 / Session 19 root-cause class: INCLUDE whitelist drift in `deploy/build-zip.py`. Four tests: `test_build_sha_baked` (Session 19 invariant), `test_dashboard_imports_from_zip_contents` (builds zip, extracts to tmpdir, runs `python -c "import dashboard"` in fresh subprocess with that dir as only PYTHONPATH — mimics App Service antenv cold-start), `test_include_list_documented_excludes_still_excluded` (locks the slim-deploy invariant by asserting `garak`/`ragas`/`encryption.py` never appear in INCLUDE — paired with ADR-001 §2), `test_forbidden_files_not_in_zip`. Third-party `ModuleNotFoundError` triggers an honest skip with explicit message ("This skip does NOT validate zip completeness") so a missing dev dep can't be mistaken for green. CI with `requirements-deploy.txt` installed runs the import test for real. |

Local verification (Python 3.14, no `requirements-deploy.txt` installed):
3 passed, 1 skipped — the skip path correctly identified `dotenv` as
third-party rather than blaming the zip. CI will exercise the full path.

Compound rules earned this session:
- **Session 23a:** ADRs live at `docs/adr/ADR-NNN-{slug}.md`, numbered sequentially, status header at top. The repo had no ADR convention before this session because every prior decision was small enough to capture in ARCHITECTURE.md `## Architectural decisions`. Integrations with persistent operational footprint (a sidecar Container App, a new Docker image, a new SSE surface) deserve their own document with rejected-options and revisit triggers.
- **Session 23b:** A deploy-completeness test must honestly distinguish "zip is incomplete" from "test runner is missing third-party deps." Failing on a missing dev `dotenv` would have trained future maintainers to ignore the test; skipping with an explicit "does NOT validate" message keeps the failure mode load-bearing. CI installs the real requirements file, so the test runs for real exactly where it matters.

## Files — Built (2026-05-24, Session 24)
### Session 24 (V2 Phase 1 closeout — parent-domain cookie + SESSION-12B §6 + ADR-001 acceptance)
Three working artifacts, all V2 Phase 1 carry-over from `docs/plans/SESSION-13-v2-engine-hardening.md`. Closes Track A item A3 (parent-domain cookie), Track B item B3 (SESSION-12B §6 backend pins), and flips ADR-001 from Proposed to Accepted. OpenAPI response-model sweep (Track A item A1) deliberately deferred — a survey counted **66 routes across ~25 files** lacking `response_model=`, which exceeds the project's ≤3-file-per-session rule and conflicts with the SESSION-13 §6 risk register's "one router at a time" mitigation. Will land as a per-router series in Sessions 25+. DNS work (item A4) deferred to a follow-up despite zone access being in hand, to keep this session focused on the auth change's blast radius.

| # | File | Purpose |
|---|---|---|
| #1 | [middleware/auth.py](middleware/auth.py) | Added `_cookie_domain()` reading new `SESSION_COOKIE_DOMAIN` env var. `_set_session_cookie()` now conditionally passes `domain=` only when env var is set — unset → host-only cookie (V1 behaviour, byte-identical). Logout's `delete_cookie` mirrors the same domain via the same helper, closing a logout-bypass class bug where a parent-domain cookie would survive logout if the delete call were host-only. Code path is dormant on V1 today; flip the env var at V2 SPA cutover. |
| #2 | [docs/plans/SESSION-12B-PROD-RECOVERY.md](docs/plans/SESSION-12B-PROD-RECOVERY.md) | §6 carry-over table gains two rows. **Row 1: backend env pins as fresh-deploy requirement** — captures `EVAL_BACKEND=noop` plus the full Session 21 `ci`-profile set (`SCRUBBER_BACKEND=regex`, `TRACER_BACKEND=noop`, `MEMORY_BACKEND=noop`, `RAG_BACKEND=noop`, `POLICY_BACKEND=noop`). Without these, a Bicep rebuild on a fresh App Service would re-detonate the deepeval cold-start crash and pull in heavy transitives not in `requirements-deploy.txt`. Bicep parameterisation deliberately deferred to the staging-slot session — encoding into `appsettings.bicep` without a staging slot to verify against repeats the Session 12 risk pattern. **Row 2: `SESSION_COOKIE_DOMAIN` activation procedure** for V2 cutover (DevTools verification + logout mirror). |
| #3 | [docs/adr/ADR-001-garak.md](docs/adr/ADR-001-garak.md) | Status flipped from Proposed → Accepted. Acceptance unblocks Sessions 25-26 (sidecar implementation per ADR §7) but does not schedule them — they remain independent of the V2 critical path. No code change accompanies this; first Garak code lands in a dedicated session that opens with the ADR §7 6-step plan. |

**Verification.** `python -c "import middleware.auth; print(hasattr(middleware.auth, '_cookie_domain'))"` → `True`. Auth route signatures unchanged, so OpenAPI shape is unaffected by this session. `test_session09_integration.py::test_dashboard_mounts_session09_routers` fails locally with `openapi.drift` from `dashboard.py:215` — confirmed pre-existing on clean main (`git stash` round-trip reproduced); spawned as separate task. Smoke test against prod deferred to the deploy that ships this commit; the change is dormant on V1 (env unset) so the worst case is "behaves identically to before."

Compound rules earned this session:
- **Session 24a:** A `set_cookie` with `domain=` MUST be paired with a `delete_cookie` carrying the same `domain=`. The browser treats host-only and parent-domain cookies as distinct entries with the same name; deleting one does not delete the other. Logout that calls host-only `delete_cookie` against a parent-domain session leaves the cookie alive — a silent auth-bypass-on-logout. Pattern: route both calls through a single `_cookie_domain()` helper so the two paths can't drift.
- **Session 24b:** When a multi-file sweep is technically straightforward but blasts past the per-session file-count rule, do the survey, document the count, defer to a per-unit series. The Session 24 OpenAPI sweep is a 66-route change across 25 files — mechanically possible in one session, but the SESSION-13 §6 risk register explicitly warns "do one router at a time" because pinned response models surface latent shape inconsistencies that would break V1 UI consumers. A 25-router parallel sweep would amortize the risk into one giant unreviewable commit; per-router sessions keep each diff small enough to read and each smoke test cheap enough to run.

## Files — Built (2026-05-24, Session 25)
### Session 25 (Track A first router + drift gate fix + Track C activation)
First per-router OpenAPI sweep, the openapi.drift gate fix carried from
the Session 24 spawned-task chip, AND Track C (parent-domain cookie
activation) — all three landed in one session because discovery showed
Track C's hostname+TLS bind had already been provisioned out-of-band,
collapsing Track C to a one-command env-var flip.

| # | File | Purpose |
|---|---|---|
| #1 | [api/security.py](api/security.py) | Added 6 Pydantic v2 response models (3 strict — `ProbeCategory`, `AdversarialCategoriesResponse`, `AdversarialHistoryResponse`; 3 permissive with `ConfigDict(extra="allow")` — `AdversarialRunResponse`, `GuardrailsSummaryResponse`, `GuardrailCheckResponse`). All 5 routes now carry `response_model=` + `operation_id="security_<resource>_<verb>"`. Permissive models pin only the stable contract fields (e.g. `error`, `guardrail_version`) and surface the rest via `extra="allow"` — deliberate tradeoff to avoid freezing internal shapes of `run_adversarial_suite()` on the first sweep. Zero UI consumers verified via grep across `static/` + `team-portal/` before changes. |
| #2 | [dashboard.py](dashboard.py) | `_validate_openapi_artifact()` strict mode flipped from "any non-prod = strict" to opt-in via `CI=true` (GitHub Actions default). Local `import dashboard` now warns rather than raises on routine spec drift — unblocks per-router OpenAPI verification ergonomics for Sessions 25+. Prod warn-only (unchanged). CI still strict — drift in PR validation still fails the build. Closes the spawned-task chip from Session 24. |
| #3 | [docs/openapi-v1.json](docs/openapi-v1.json) | Regenerated under `SL_OPENAPI_EXPORT_PROFILE=ci`. +260/-20: 6 new component schemas + 5 cleaned-up operationIds (replacing FastAPI's auto-generated `get_categories_api_security_adversarial_categories_get` style). |
| #4 (Track C) | App Service config | `az webapp config appsettings set --name app-aigovern-dev --resource-group rg-aigovern-dev --settings "SESSION_COOKIE_DOMAIN=.aigovern.sandboxhub.co"`. Activates the dormant Session 24 code path. Verified live: `az ... --query "[?name=='SESSION_COOKIE_DOMAIN']"` returns the leading-dot value with `slotSetting:false`. App restart clean; `/api/health` 200 on both `aigovern.sandboxhub.co` + `api.aigovern.sandboxhub.co` post-flip. |
| #5 (Track C discovery) | Pre-existing custom-domain bind | `api.aigovern.sandboxhub.co` was already bound to `app-aigovern-dev` with SNI SSL (thumbprint `9287FDA19B72D6C48EA82B9EA2618DA027DB9D8A`) — discovered via `az webapp config hostname list`. Session 24's deferred A4 item was effectively closed out-of-band between sessions. No new hostname add or cert bind was needed in Session 25. |

**Sweep progress:** 1/25 routers done (api/security.py — 5/66 routes). Order
for Sessions 26+: leave high-traffic UI consumers (`api/guide.py` — 9 routes,
high SPA coupling) for later in the sweep; pick low-coupling routers first
to build the model-definition pattern.

**Verification.** Local: `from api.security import router` → 5 routes OK;
`import middleware.auth; _cookie_domain` → True (Session 24 dormant path
still wired); `import dashboard` → no raise (drift fix working as designed,
logs `openapi.drift.production_warn` because the local spec includes real
backends; the committed ci-profile artifact is the only committable one
per Session 21a). Prod smoke deferred to the post-deploy verifier (no UI
consumer change, response shape additive-only for the 3 permissive models).

Compound rules earned this session:
- **Session 25a:** When introducing `response_model=` on an existing route
  whose handler returns a multi-shape dict (e.g. `apply_guardrails` returns
  the input-direction shape; `filter_output` returns the output-direction
  shape from the same endpoint), use a unioned Pydantic model with all
  fields `Optional` + `ConfigDict(extra="allow")`. A strict Union[A, B]
  forces FastAPI to pick one schema for the OpenAPI surface; a permissive
  union surfaces both branches as discoverable fields without breaking
  callers that branch on field presence. Lock the few fields that are
  genuinely stable (here: `guardrail_version`, `total_input_patterns`)
  and leave the rest extra=allow until the underlying handler is itself
  split.
- **Session 25b:** The Session 21a "the `ci`-profile artifact is the only
  committable one" rule has a corollary worth surfacing: the local-import
  drift warning is *expected* and *correct* on bare-Python imports, because
  real backends (deepeval, presidio, etc.) register routes that the
  `ci`-profile artifact omits. The Session 24 spawned-task chip mistakenly
  treated this as a defect. Fix shape: gate the *raise* on CI (where the
  committed-artifact contract is enforced), keep warn-only on local + prod.
  Do not try to make local match the committed artifact byte-for-byte —
  that would require running every local import under `ci`-profile env,
  which defeats the purpose of having local backends configurable.

## Files — Built (2026-05-24, Session 26)
### Session 26 (Track A second router — api/reports.py)
Second per-router OpenAPI sweep. Pattern from Session 25 applied verbatim:
grep UI consumers first (only `static/reports.html` — keys off
`reports[].type/title/scope` and `systems[].id/name`); read router + consumer
end-to-end; draft Pydantic v2 models inline; add `response_model=` +
`operation_id=` to every route.

| # | File | Purpose |
|---|---|---|
| #1 | [api/reports.py](api/reports.py) | Added 5 Pydantic v2 response models (2 strict — `ReportCatalogResponse` wrapping `ReportCatalogItem`, `ReportSystemsResponse` wrapping `ReportSystemItem`; 1 permissive — `ReportDataResponse` with `ConfigDict(extra="allow")` pinning only `report_title` / `generated_at` / `audience` per compound rule 25a, since the report payload diverges across the six builders). All 6 routes carry `operation_id="reports_<resource>_<verb>"`. The 3 export endpoints (`export.json`/`.csv`/`.pdf`) get `operation_id` only — they return raw `Response` / `HTMLResponse` so FastAPI skips runtime `response_model` validation anyway; documenting the raw body via OpenAPI was not worth the schema complexity. |
| #2 | [docs/openapi-v1.json](docs/openapi-v1.json) | Regenerated under `SL_OPENAPI_EXPORT_PROFILE=ci`. +163/-13: 5 new component schemas + 6 cleaned-up operationIds (replacing FastAPI auto-generated `catalog_api_reports_catalog_get` style with `reports_catalog_list`). No removed routes; no shape changes to existing schemas. |

**Sweep progress:** 2/25 routers done (11/66 routes — api/security.py 5 +
api/reports.py 6). Next candidates per SESSION-27 plan: `api/analytics.py`
(5 routes, medium UI coupling) or `api/connectors.py` (4 routes, low
coupling). `api/guide.py` still deferred (9 routes, high SPA surface).

**Verification.** `python -c "from api.reports import router; print(len(router.routes), [r.operation_id for r in router.routes])"` → 6 routes, all 6 `reports_*` op_ids present. Spec diff smoke (`git diff docs/openapi-v1.json | grep -E 'operationId|Report*'`) matched expectations: 5 new schemas, 6 renamed operationIds, zero removed routes. Local `import dashboard` still logs `openapi.drift.production_warn` — expected per compound rule 25b (`ci`-profile artifact is the only committable one). Prod smoke deferred to post-deploy verifier; no UI consumer change since `static/reports.html` only reads stable discriminator fields that were already preserved.

Compound rules earned this session:
- **Session 26a:** For routes that return a `Response` subclass (`JSONResponse`,
  `HTMLResponse`, raw `Response`) FastAPI skips runtime `response_model`
  validation but **still uses it for OpenAPI schema generation**. This is
  the safest path for documenting JSON-returning endpoints that currently
  return `JSONResponse(...)` rather than a dict: you get the schema in the
  spec without altering serialization behavior. The 3 raw-binary exports
  (`.csv`, `.pdf`) intentionally got `operation_id` only — adding a
  response_model would have been schema-noise without payload typing.
- **Session 26b:** Permissive-model pattern (compound 25a) extends cleanly to
  multi-builder dispatch routes like `GET /reports/{report_type}`. The
  alternative — six discriminated Union members keyed on `report_type` —
  would have required either (a) freezing six internal `domain.reports`
  builder shapes into the public OpenAPI contract, or (b) duplicating the
  shape-evolution logic in two places. Permissive + pinned discriminators
  defers that decision to whoever splits the route per type later, without
  forcing it now.

## Files — Built (2026-05-24, Session 27)
### Session 27 (Track A third router — api/analytics.py)
Third per-router OpenAPI sweep. Pattern from Sessions 25-26 applied. UI-consumer
grep returned only `deploy/smoke_e2e.ps1` (asserts HTTP 200 only, no shape
coupling) plus `ARCHITECTURE.md` itself — lowest-coupling sweep target so far.

| # | File | Purpose |
|---|---|---|
| #1 | [api/analytics.py](api/analytics.py) | Added 3 Pydantic v2 response models — 1 permissive (`AnalyticsResponse`, `ConfigDict(extra="allow")` with Optional `period_days`/`pass_rate` because `calculate_analytics()` returns 8 keys on the empty-history path vs 10 when runs exist) and 2 strict (`AnalyticsByDomainResponse`, `AnalyticsTrendsResponse` — fixed 3-key subsets). All 5 routes carry `operation_id="analytics_<resource>_<verb>"`. The 2 raw-export routes (`/api/export/csv`, `/api/export/json`) returning `PlainTextResponse`/`Response` get `operation_id` only, per compound rule 26a. Added `from __future__ import annotations`. |
| #2 | [docs/openapi-v1.json](docs/openapi-v1.json) | Regenerated under `SL_OPENAPI_EXPORT_PROFILE=ci`. New component schemas: `AnalyticsResponse`, `AnalyticsByDomainResponse`, `AnalyticsTrendsResponse`. 5 new/renamed operationIds (`analytics_rollup_get`, `analytics_by_domain_get`, `analytics_trends_get`, `analytics_export_csv`, `analytics_export_json`). No removed routes; no shape changes to prior schemas. |

**Sweep progress:** 3/25 routers done (16/66 routes — api/security.py 5 +
api/reports.py 6 + api/analytics.py 5). Next candidates: `api/connectors.py`
(4, low coupling), `api/evidence.py` (4, medium), `api/domains_api.py` (5).
`api/guide.py` still deferred (9, high SPA surface).

**Verification.** `python -c "import api.analytics"` → ok. OpenAPI export wrote
425164 bytes. Inspector script confirmed 5/5 operationIds present and 3/3
`Analytics*` schemas in `components.schemas`. Smoke script `deploy/smoke_e2e.ps1`
scenario 5 only asserts HTTP 200 on `/api/analytics/trends`, so no shape
contract was touched. Local `import dashboard` still logs
`openapi.drift.production_warn` — expected per compound rule 25b.

Compound rule earned this session:
- **Session 27a:** When a router has *no* live UI consumers (only smoke-script
  HTTP-200 assertions and doc cross-references), the OpenAPI sweep is the
  cheapest place to introduce strict response models because the blast radius
  of shape regressions is bounded to OpenAPI clients (none yet generated) and
  spec-diff CI. Reserve permissive `extra="allow"` for genuinely polymorphic
  rollup payloads (like `AnalyticsResponse`'s empty-vs-populated asymmetry),
  not as a reflex.

## Files — Built (2026-05-24, Session 28)
### Session 28 (Track A fourth router — api/connectors.py)
Fourth per-router OpenAPI sweep. UI-consumer grep across `static/` and
`team-portal/` returned **zero hits** — only doc / plan files reference
`/api/grc/connectors/v2/`. Lowest-coupling target in the sweep so far; per
compound rule 27a, all four routes get **strict** response models (no
`extra="allow"` anywhere — every payload shape is fully known and stable).

| # | File | Purpose |
|---|---|---|
| #1 | [api/connectors.py](api/connectors.py) | Added 6 Pydantic v2 response models — `ConnectorSummary` (11 fields), `ConnectorListResponse` (envelope), `SyncResultModel` (9 fields mirroring `domain.connectors.SyncResult` dataclass; `error: Optional[str]`, `sample_ids: dict[str, list[str]]`), `SyncAllTotals` (5 ints), `SyncAllResponse` (envelope), `ConnectorResultsResponse` (4× `list[dict]` + `sync_count`). Domain-model payloads (EvalResult/Finding/RuntimeEvent/Evidence) typed as `list[dict]` — already validated by domain layer via `model_dump(mode="json")`; binding to full domain Pydantic models would re-validate on response and couple the connectors OpenAPI surface to every domain schema bump. All 4 routes carry `operation_id` (`connectors_list_get`, `connectors_sync_run`, `connectors_sync_all_run`, `connectors_results_get`) — `_run` semantic verb chosen for the two POST sync actions per reports.py precedent. |
| #2 | [docs/openapi-v1.json](docs/openapi-v1.json) | Regenerated under `SL_OPENAPI_EXPORT_PROFILE=ci`. New component schemas: `ConnectorSummary`, `ConnectorListResponse`, `SyncResultModel`, `SyncAllTotals`, `SyncAllResponse`, `ConnectorResultsResponse`. 4 new operationIds on `/api/grc/connectors/v2/*`. Pre-existing `ConnectorsOut`/`ConnectorStatusOut` schemas (different router) untouched. |

**Sweep progress:** 4/25 routers done (20/66 routes — security 5 + reports 6 +
analytics 5 + connectors 4). Next candidates: `api/evidence.py` (4, medium),
`api/domains_api.py` (5, medium-high). `api/guide.py` still deferred (9, high
SPA surface).

**Verification.** `python -c "import api.connectors"` → ok (4 routes). OpenAPI
export wrote 432061 bytes. Inspector confirmed 4/4 operationIds + 6/6 new
schemas in `components.schemas`. `TestClient` end-to-end against
`dashboard.app`: all four routes return 200 with shapes matching the strict
models exactly — POST `/sync` returns the 9 `SyncResultModel` fields, POST
`/sync-all` `totals` carries exactly the 5 expected keys. Local `import
dashboard` still logs `openapi.drift.production_warn` — expected per compound
rule 25b (dashboard generates under production profile vs the ci-profile spec
on disk).

**Open issue surfaced this session (not a fix — log for a focused later
session):** Prod `/api/health` reports SHA `241991b` (the Session 27 doc
commit), not `149bc8e` (the Session 27 code commit). The Session 27 code IS
deployed — `241991b` is a descendant of `149bc8e` so its worktree contains
the analytics.py and openapi-v1.json changes — but the doc-only commit
triggered a deploy it should have been filtered out of. Indicates
`.github/workflows/azure-deploy.yml` `paths-ignore` is not catching
`ARCHITECTURE.md` / `docs/plans/**` (Session 22 regression resurfacing). No
runtime impact; wastes deploy cycles and risks masking a real deploy
failure. Recommend dedicated single-file workflow-fix session with a
doc-only test commit to confirm filter.

## Files — Built (2026-05-24, Session 29)
### Session 29 (Track A fifth router — api/evidence.py)
Fifth per-router OpenAPI sweep. UI-consumer grep found exactly one
live consumer — `static/evidence.html` — which reads only the
`sectioned` and `completeness` payloads (specifically the section
roll-up `items[]` rows and the completeness `rows[]`). Every shape
upstream of these routes is a deterministic dataclass
(`EvidenceRow`, `CompletenessRow`) or the `Evidence` Pydantic v2
domain model; no asymmetric/polymorphic payloads in the surface.
Per compound rule 27a, all four routes get **strict** response
models (no `extra="allow"` anywhere).

| # | File | Purpose |
|---|---|---|
| #1 | [api/evidence.py](api/evidence.py) | Added 6 Pydantic v2 response models — `SectionCatalogItem` + `SectionsResponse` envelope; `EvidenceRowOut` (18 fields mirroring `domain.evidence_repository.EvidenceRow` dataclass; Optionals reflect source: `assessment_id`/`hash`/`uri` may be None); `SectionedSection` + `SectionedResponse` envelope; `CompletenessRowOut` (5 fields mirroring `CompletenessRow` dataclass) + `CompletenessResponse` envelope; `EvidenceDetailResponse` (14 fields mirroring `domain.models.Evidence` field-by-field plus joined `ai_system_name`). All 4 routes carry `operation_id` (`evidence_v2_sections_get`, `evidence_v2_sectioned_get`, `evidence_v2_completeness_get`, `evidence_v2_record_get`). The single-record endpoint mirrors `Evidence` strict rather than typing as `dict` — chosen because `Evidence` is a stable domain model and audit clients fetching by id genuinely benefit from a typed shape (departs from the connectors pattern, where domain-payload **lists** stayed `list[dict]` to avoid coupling to every domain schema bump; single-record fetch of a stable model is a different trade). Module docstring documents the strict choice and the consumer-surface verification. |
| #2 | [docs/openapi-v1.json](docs/openapi-v1.json) | Regenerated under `SL_OPENAPI_EXPORT_PROFILE=ci`. 458589 bytes. New component schemas: `SectionCatalogItem`, `SectionsResponse`, `EvidenceRowOut`, `SectionedSection`, `SectionedResponse`, `CompletenessRowOut`, `CompletenessResponse`, `EvidenceDetailResponse`. 4 new operationIds on `/api/grc/evidence/v2/*`. No removed routes; no shape changes to prior schemas. |

**Sweep progress:** 5/25 routers done (24/66 routes — security 5 +
reports 6 + analytics 5 + connectors 4 + evidence 4). Next candidate
per SESSION-30 plan: `api/domains_api.py` (5 routes, 6 live UI
consumers — higher coupling than evidence; list endpoints likely
need `list[dict]` decoupling per the connectors pattern).
`api/guide.py` (9, high SPA coupling) still deferred to late in sweep.

**Verification.** `python -c "import api.evidence"` → ok (4 routes
registered). OpenAPI export wrote 458589 bytes. Worktree diff stat
+549/-20 (148 router + 421 spec). No `data/*.jsonl` pollution. Local
`import dashboard` still logs `openapi.drift.production_warn` —
expected per compound rule 25b.

**Open issue carried from Session 28:** `paths-ignore` regression in
`.github/workflows/azure-deploy.yml` still uncorrected. The Session 29
code commit will deploy (expected); the Session 29 doc closeout commit
will likely also deploy (unwanted but harmless). **Recommend dedicated
workflow-fix session before Session 30 starts** so the SESSION-30
domains_api work isn't muddied by a second spurious deploy.

### Session 30 prep (2026-05-25) — paths-ignore root cause fixed
Workflow file is `.github/workflows/deploy.yml` (not `azure-deploy.yml`;
the Session 28 + 29 handoffs misnamed it). Hypothesis from Session 28
("paths-ignore is silently misbehaving") confirmed empirically across
1d77d4f, 241991b, 069e923, b40d90c — every doc-only closeout commit
since Session 26 triggered a deploy. Root cause was glob syntax, not
workflow logic. Commit `2589dbd`:
```
- 'docs/**'   ->  'docs/**/*'
- '**.md'     ->  '**/*.md'
```

**Compound rule 28a (GitHub Actions path-filter globs).** In GitHub's
minimatch evaluator, `**` only behaves as the "any depth" recursive
segment when it stands alone between path separators. Glued forms
(`docs/**`, `**.md`) degrade to single-segment matches and silently
miss nested paths. Canonical safe forms: `prefix/**/*` and `**/*.ext`.
This commit itself is a doc-only change to ARCHITECTURE.md — if
paths-ignore is now working, this push should NOT trigger a deploy.
The presence/absence of a deploy run on commit verifies the fix.

## Files — Built (2026-05-25, Session 30)
### Session 30 (Track A sixth router — api/domains_api.py)
Sweep advances to **6/25 routers / 29/66 routes**. Compound 28a's
`paths-ignore` fix (S30 prep) held — doc-only commit 704e743 did not
deploy, empirically confirming the glob fix.

`api/domains_api.py` — added 4 Pydantic v2 response models
(`DomainConfig` retained as request body; new `DomainOut`,
`DomainListResponse`, `DomainDeleteResponse`) + `response_model=` +
stable `operation_id` on all 5 routes (`domains_list`, `domains_get`,
`domains_create`, `domains_update`, `domains_delete`). Strict-vs-
`list[dict]` decision matrix per compound 27a:

| Route | Decision | Reason |
|---|---|---|
| `GET /` | `list[dict]` envelope | Domain JSON files carry arbitrary keys (`eval_weights`/`risk_rules`/`test_cases` vary per file); picker consumers (`compare.html`, `memory.html`) read 2-3 fields |
| `GET /{id}` | strict `DomainOut` + `extra="allow"` | `domains.html` edit modal reads many fields; bounded drift in stored JSON tolerated |
| `POST /{id}` | strict `DomainOut` + `extra="allow"` | Response echoes stored data |
| `PUT /{id}` | strict `DomainOut` + `extra="allow"` | Same |
| `DELETE /{id}` | strict `DomainDeleteResponse` | Trivial 2-field envelope; high audit value |

Live consumer surface (6, unchanged from S29 grep): `static/compare.html:124`,
`static/domains.html:209/240/414/439`, `static/memory.html:374`. All keep
working — response shapes are wire-compatible. Bonus modernization:
deprecated `config.dict()` → `config.model_dump()` (Pydantic v2 API).

`docs/openapi-v1.json` regenerated: +181/-21 lines. Diff is exactly
{5 new operationIds renamed to convention, 3 new schemas, 5 `$ref`
wires}. No removed routes, no upstream schema shape changes.

Verification: `python -c "import api.domains_api"` + TestClient
`GET /api/domains/` → 200 (envelope: `domains`, `count`); `GET
/api/domains/finance` → 200 with all DomainOut fields + extras
(`compliance_checks`, `finra_requirements`) tolerated via
`extra="allow"`. `openapi.drift.production_warn` logs as expected
on local import (compound 25b).

### Session 31 (Track A seventh router — api/adversarial.py + sweep recount)
Sweep counter **corrected from recount** — prior planning headers
(6/25 routers, 29/66 routes) were tracking only the routers swept by
this initiative, not total project coverage. Empirical recount of
`api/*.py` against the spec:

| Bucket | Routers | Routes |
|---|---|---|
| Fully typed (`response_model` on every JSON route) | 19 | ~108 |
| Partially typed | 5 | 11 untyped |
| Fully untyped | 12 | 32 untyped |
| **Total** | **36** | **~151** |

S31 promotes `api/adversarial.py` from partially-typed to fully-swept,
so the new state is **19/36 routers fully typed** (some by pre-S25
typing audit, e.g. `findings_v2.py` per SESSION-13 §3.1). Sweep
target list goes forward on the 5 partial + 12 untyped routers, not
the inflated `25 - swept-this-initiative` framing.

**Originally planned S31 target `api/findings_v2.py` was already
fully typed** (5 response models + 5 operation_ids, SESSION-13 §3.1).
No-op on that file. Pivoted to `api/adversarial.py` — 1 typed JSON
route, 1 SSE route (`POST /run` returns `StreamingResponse`,
intentionally cannot have a JSON `response_model`).

Changes to `api/adversarial.py`:
- `CategoriesResponse.model_config` tightened `ConfigDict()` → `ConfigDict(extra="forbid")` (sweep strict-mirror policy)
- `GET /categories` operation_id stamped `adversarial_categories_list` (was auto-generated `list_categories_api_adversarial_categories_get`)
- `POST /run` operation_id stamped `adversarial_run` (was auto-generated `run_suite_api_adversarial_run_post`); no `response_model` since SSE — documented in file docstring

Consumer surface: only `team-portal/src/pages/adversarial/AdversarialPage.tsx`,
locked out per V2-PORTAL-SPLIT.md §3. No `static/` consumer.
Grep for old auto-generated operationIds across `*.py`, `*.ts`,
`*.tsx`, `*.html` returned zero hits — safe to rename.

`docs/openapi-v1.json` regenerated: +3/-2 lines. Diff is exactly
{two operationIds renamed, `additionalProperties: false` added to
`CategoriesResponse` schema}. No removed routes, no shape changes
to other schemas. `openapi.drift.production_warn` fires on local
`import dashboard` as expected per compound 25b.

**Compound rule 28a regression (open issue, not in this session's
budget).** S30 closeout commit `b796494` (doc-only:
`ARCHITECTURE.md` + delete `SESSION-30-*.md` + add `SESSION-31-*.md`)
**did trigger the deploy workflow** despite all 3 files matching
the `**/*.md` and `docs/**/*` paths-ignore globs. By contrast,
the prior test commit `704e7430` (single-file `ARCHITECTURE.md`
modify) correctly skipped deploy. The only diff between them is
the presence of file **deletions/additions** vs pure modify.
Suspected GitHub Actions paths-ignore quirk around delete+add
in the same push; needs reproduction in a dedicated session before
the rule is updated. Until then, doc-only commits that **only
modify** (no add/delete) remain safe; doc-only commits with file
moves should expect deploy to fire.

Verification: `python -c "import api.adversarial"` + `python -c
"import dashboard"` both pass; route inspection confirms new
operation_ids on `adversarial.router.routes`; spec round-trip
clean.

### Session 32 (Track A eighth router — api/frameworks.py)
**Originally planned S32 target `api/agent_bindings.py` was already
fully swept** (4/4 routes carry `response_model` + `operation_id`;
DELETE correctly response_model-less for 204). Second consecutive
session where the partial-router list was stale on read — same
pattern as S31's `findings_v2.py` no-op pivot. Recount of the partial
list is overdue.

Pivoted to `api/frameworks.py` per handoff alternative. 4 routes:
- `GET /matrix` — typed since S06, op_id stamped `frameworks_matrix_get`
- `GET /{slug}` — typed since S06, op_id stamped `frameworks_overview_get`
- `GET /{slug}/system/{system_id}` — typed since S06, op_id stamped `frameworks_drilldown_get`
- `POST /{slug}/export` — returns `application/pdf` bytes; op_id only
  (`frameworks_export`), no `response_model` per S31 binary-response
  rule (mirrors the SSE precedent).

Strict pass per compound 27a: 10 response models + `ExportRequest`
all promoted to `extra="forbid"` (`MatrixCellOut`, `MatrixRowOut`,
`MatrixOut`, `ControlRollupOut`, `FindingSummaryOut`, `ItemCoverageOut`,
`FrameworkOverviewOut`, `EvidenceOut`, `DrillDownItemOut`,
`DrillDownOut`).

Consumer surface: only `static/frameworks.html` + `static/ai-systems.html`
(no team-portal SPA route). Both use the operation paths directly,
not the FastAPI auto-generated operationIds — safe to rename.

**Finding: `EvidenceOut` name-collides with `api/grc.py:491`.** The
non-strict `grc.py` definition wins in the merged OpenAPI schema
(EvidenceOut shows `additionalProperties: null` in components, not
`false`), even though the frameworks.py version is strict. Both
routers reference their own local class — runtime behavior is
unaffected — but the OpenAPI artifact under-represents the
strictness of `/api/frameworks/{slug}/system/{id}` responses. Out
of sweep scope per compound 24b (per-router only). Carried to a
future session that touches `api/grc.py` — fix is rename to
`FrameworksEvidenceOut` + regen artifact, ~3 lines.

Also-noted (not fixed): `MatrixCellOut` at `api/frameworks.py:83`
is dead code — `MatrixRowOut.cells` is typed `dict[str, float]`,
not `dict[str, MatrixCellOut]`. Leave as-is per scope discipline.

`docs/openapi-v1.json` regenerated: +13/-4 lines (10 strict markers
+ 4 op_id renames). `openapi.drift.production_warn` fires on local
`import dashboard` as expected per compound 25b.

Compound rule **24c (NEW — earned this session):** Before targeting
a "partial" router from the planned-target list, grep the actual
file for `response_model=` + `operation_id=` and recount routes —
the planned-target list goes stale fast as sibling sweeps stamp
files. Two consecutive sessions (S31, S32) burned a context-load
pivot on a target that turned out already done. Add a one-line
state-check to the session-start ritual: `grep -c 'response_model=\|operation_id=' api/<target>.py`.

Verification: `python -c "import api.frameworks"` passes,
`python -c "import dashboard; dashboard.app.openapi_schema=None; spec=dashboard.app.openapi(); ..."`
confirms all 4 op_ids stamped and 10 strict models present (modulo
the EvidenceOut collision above). /verify all PASS.

### Session 33 (Track A ninth router — api/projection.py)
Compound rule 24c probe (added end of S32) ran on session start
against the planned S33 target `api/projection.py`:
`grep -c 'response_model=\|operation_id=' api/projection.py` → 1.
Route walk confirmed 1 typed (`GET /status` had response_model only,
no operation_id), 2 untyped (`POST /replay`, `GET /views/{view}`).
**Probe matched the S33 plan exactly — no pivot needed.** First clean
24c application after S31 + S32 both ate pivots on stale targets.

3 routes touched:
- `GET /status` — already had `ProjectionStatusResponse`; added
  `operation_id="projection_status"`
- `POST /replay` — new `ReplayResponse` (strict, 2 fields: `events_processed`,
  `from_event_id`); op_id `projection_replay`; return type flipped from
  `JSONResponse` to `ReplayResponse`
- `GET /views/{view}` — new `ProjectionViewResponse` (envelope + polymorphic
  `rows: list[dict[str, Any]]`); op_id `projection_view`; return type flipped
  from `JSONResponse` to `ProjectionViewResponse`

`ProjectionViewResponse.rows` is intentionally `list[dict]` per compound
27a — the endpoint serves five materialized Postgres tables (ai_systems,
eval_runs, findings, release_decisions, policy_evaluations) with genuinely
different column shapes. Single strict union would either force five
sibling endpoints or freeze all five table schemas into the public OpenAPI
contract. Model docstring also flags the JSONB-columns-as-strings
serialization shim at `api/projection.py:278-281` so SDK consumers know
to `json.loads` JSONB columns explicitly.

`ReplayResponse` is strict (`extra="forbid"`) — 2 fields, zero variance.

Unused `JSONResponse` import removed; pre-existing unused `Depends`
import left alone (out of sweep scope per compound 24b).

Consumer surface: `static/projection.html` only — reads `lag_events`,
`tailer_checkpoint_offset`, `last_event_id` from /status, calls /replay
with confirm dialog. Per-view counts auto-refresh queries /views/{view}.
None of the consumers care about FastAPI auto-generated operationIds.
No SPA route in `team-portal/`.

`docs/openapi-v1.json` regenerated via `scripts/export_openapi.py`
(ci profile, the canonical exporter): +75/-5 lines. Exactly 2 new
schemas (`ReplayResponse`, `ProjectionViewResponse`) + 3 op_id renames
(`projection_status_api_projection_status_get` → `projection_status`,
etc.). Zero removed routes; no shape changes to prior schemas.

Compound rule **24d (NEW — earned this session):** Always regenerate
`docs/openapi-v1.json` via `python scripts/export_openapi.py`, never
via an ad-hoc `dashboard.app.openapi()` one-liner. The canonical
exporter both pins the env profile (compound 25b) AND normalizes key
ordering — running FastAPI's raw `.openapi()` produces a 15K-line
key-reordering diff that hides the actual change. First-pass attempt
this session produced a 15036/14966 diff vs the canonical exporter's
clean +75/-5 — wasted ~3 min of review before the discrepancy was
caught. Add to session-start ritual: regen step is `scripts/export_openapi.py`,
not `python -c "..."`.

**Sweep progress:** 9 routers shipped by this initiative
(security + reports + analytics + connectors + evidence +
domains_api + adversarial + frameworks + projection). Empirical
router count still owed a fresh recount in S34 — the "20/36 fully
typed" carry-over from S32 is now itself one session stale.

**Compound 28a regression — third data point.** S32 closeout commit
`ca20d85` (doc-only: ARCHITECTURE.md modify + delete `SESSION-32-*.md`
+ add `SESSION-33-*.md`) needs to be checked for deploy trigger to
extend the S30→S31 + S31→S32 pattern. This S33 closeout commit will
follow the same shape (modify + delete + add), giving a fourth data
point if it also triggers. Dedicated fix session still pending; not
in S33 scope.

Verification: `python -c "import api.projection"` passes, route
inspection via `router.routes` confirms all 3 op_ids stamped
(`projection_status`, `projection_replay`, `projection_view`).
Canonical exporter spec round-trip clean.

### Session 34 (Track A tenth router — api/memory.py + sweep recount)
First action per S34 plan: empirical recount across all `api/*.py`.
The "20/36 fully typed" estimate carried S31→S32→S33 was off — actual
floor is **18/40 fully clean** (40 = total non-stub api routers).
Recount loop captured per-file `routes/response_model/operation_id`
counts; results stored verbatim in the S35 carry-over below.

Target picked: `api/memory.py` (5 routes, 5 response_model, **0
operation_id**) — cleanest possible sweep shape. All response models
already present from Session 04; only OpenAPI metadata missing.

5 op_ids stamped following the locked `<prefix>_<verb>` convention:
`memory_write_episode`, `memory_list_episodes`, `memory_recall`,
`memory_get_stats`, `memory_get_context`. No response model changes,
no domain logic touched, no consumer surface impact.

Compound 24c probe post-edit: `api/memory.py` 5/5/5. Import smoke
clean (`python -c "import api.memory"`).

Spec regenerated via `python scripts/export_openapi.py` (compound 24d
applied first try — no raw-`app.openapi()` detour this session): exactly
10-line diff, 5 operationIds replaced. The "before" form
(`write_episode_api_memory_episodes_post`) is FastAPI's auto-generated
`<funcname>_<path>_<method>` — unstable across renames; the "after"
form survives rename. Zero key-reorder noise — clean diff proves the
canonical exporter is doing its job.

**Sweep progress:** 10 routers shipped by this initiative (security +
reports + analytics + connectors + evidence + domains_api + adversarial
+ frameworks + projection + memory). **Sweep counter: 19/40 fully typed**
(18 carried in from prior sessions + memory.py this session).

**Compound 28a regression — STREAK BROKEN at S34 closeout.** S29-S33
closeouts (5/5) all triggered deploy: 26377047211, 26377787295,
26378101370, 26378408453, 26378651826. **The S34 closeout commit
`d5b36de` did NOT trigger deploy** — only contract-tests fired. Same
diff shape as the prior 5 (modify ARCHITECTURE.md + delete
`SESSION-N-*.md` + add `SESSION-N+1-*.md`). Pattern is now
**intermittent, not consistent**. S35 reframed from "fix session" to
**"observation session"** — gather 3 more closeout data points before
attempting any workflow change. Premature fix risks adding complexity
to a workflow that may already be working. See
[SESSION-35-deploy-paths-ignore-fix.md](docs/plans/SESSION-35-deploy-paths-ignore-fix.md)
Step 0 for the decision gate.

Verification: `python -c "import api.memory"` passes, route inspection
via 24c grep returns 5/5/5, canonical exporter spec round-trip clean.

### Session 35 (Track A eleventh router — api/rag.py + compound 28a observation #2)
S35 plan reframed from "dedicated 28a fix" to "observation phase" after
S34 closeout `d5b36de` broke the 5/5 streak. Step 0 observation ran first,
then per the plan's "if S34 was a flake, do nothing" branch, S35 returned
to the OpenAPI sweep with `api/rag.py` (the 4/4/0 sibling of S34's memory.py).

**Compound 28a observation results (2 new data points).** Re-verification
via `gh run list` against recent commits:

| Commit | Shape | Deploy fired? |
|---|---|---|
| `37458cd` (S33 closeout) | modify+delete+add | YES — 26378651826 |
| `19e794a` (S34 Track A code) | code change | YES — 26378823188 |
| `d5b36de` (S34 closeout) | modify+delete+add | **NO** |
| `0d8ff1c` (S35 reframe) | modify-only | **NO** |
| `12e3908` (S35 Track A code) | code change | YES — expected |
| `8933b34` (S35 closeout) | modify+delete+add | **NO** (recorded at S36 start) |

Three consecutive closeouts now suppressed (S34 + S35-reframe + S35).
State remains "intermittent: 3/5 prior closeouts triggered, 3 most
recent did not." **Workflow unchanged through S36 per plan.**
Decision gate at observation point #5 stands.

`api/rag.py` sweep: 4 routes, all already had `response_model=` from
Session 18; added `operation_id=` to all four following the locked
`<prefix>_<verb>` convention:
- `GET /stats` → `rag_get_stats`
- `POST /search` → `rag_search`
- `POST /documents` → `rag_index_document`
- `DELETE /documents/{doc_id}` → `rag_delete_document`

No response model changes, no consumer surface impact. Sole consumer
`team-portal/src/pages/rag/RagCorpusPage.tsx` reads by path, not op_id.

Compound 24c probe post-edit: `api/rag.py` 4/4/4. Import smoke clean.
Spec regen via `python scripts/export_openapi.py` (compound 24d applied
first try): exactly +4/-4 lines, four operationId swaps. Zero key-reorder
noise — clean diff consistent with the canonical exporter contract.

**Sweep progress:** 11 routers shipped by this initiative (security +
reports + analytics + connectors + evidence + domains_api + adversarial
+ frameworks + projection + memory + rag). **Sweep counter: 20/40
fully typed** (19 carried from S34 + rag.py this session).

Verification: `python -c "import api.rag"` passes, route inspection
via 24c grep returns 4/4/4, canonical exporter spec round-trip clean.

## Files — Planned

### Session 36 (Track A twelfth router — api/agent_bindings.py + compound 28a observation #3)
Two threads, both as planned.

**Compound 28a observation #3.** `gh run list --commit=8933b34` returned
empty — S35 closeout did NOT trigger deploy. Tally now 5 fired / 3
missed (S29-S33 closeouts fired; S34 closeout + S35 reframe + S35
closeout did not). State remains "intermittent, observation phase";
workflow stays unchanged through S37. Decision gate at observation
point #5 stands.

**Track A — `api/agent_bindings.py` sweep.** Compound 24c probe
confirmed 4/3/4 (matching S34 recount). The missing `response_model=`
is on DELETE, which returns `Response(status_code=204)` — per compound
26a, OpenAPI's 204 status forbids a response body, so `response_model=`
would be misleading. This is a **document-the-gap** sweep per S31 rule,
not an add-response_model sweep.

Module docstring expanded to record:
- Per-route response/operation_id status
- Why DELETE is bare (204 + bare `Response` subclass; consumer reads
  `response.ok` only)
- Why `AgentBindingOut` uses `ConfigDict(extra='allow')` (domain
  enriches base binding with `agent_name`/`agent_team`/
  `agent_owner_type`/`version_semver` joined from agents + versions)

Spec regeneration via `scripts/export_openapi.py` produced no schema
diff (prose-only change). Probe re-verified 4/3/4 after docstring
cleanup — caught new **compound 28b mid-sweep**.

**Compound 28b (new this session).** Docstrings that contain the
literal tokens `response_model=` or `operation_id=` inflate the 24c
grep recount. First post-edit probe returned 4/5/5 (true: 4/3/4 + 2
docstring matches). Rule: when documenting OpenAPI conventions in
docstrings, refer prose-style (e.g. "response model", "operation id"),
never with the `=` suffix attached. Catching this pre-commit via the
second 24c run is the win from running the probe twice — exactly the
"every mistake → new rule" pattern from CLAUDE.md.

**Sweep progress:** 12 routers shipped by this initiative (security +
reports + analytics + connectors + evidence + domains_api + adversarial
+ frameworks + projection + memory + rag + agent_bindings).
**Sweep counter: 21/40 fully typed** (20 carried from S35 +
agent_bindings.py this session).

Verification: `python -c "import api.agent_bindings"` passes; 24c probe
returns 4/3/4 (DELETE bare-by-design per 26a); spec regen produced
identical file.

### Session 37 (Track A thirteenth router — api/analytics.py [verification-only] + compound 28a observation #4)

**Compound 28a observation #4.** `gh run list --commit=bb2a520` confirmed
S36 closeout DID trigger deploy (both `contract-tests` and `deploy`
workflows ran successfully). Tally now **6 fired / 3 missed** across
last 9 closeouts (S29-S33 YES, S34/S35-reframe/S35-closeout NO, S36 YES).
S36 was a mixed modify+delete+add commit, consistent with the suspected
"add/delete in same push bypasses paths-ignore" pattern flagged in S31.
State remains "intermittent, observation phase"; workflow unchanged
through S38. Decision gate at observation point #5 stands.

**Track A — `api/analytics.py` verification-only sweep.** Compound 24c
probe returned 5/3/5 as the S35 partials list predicted, BUT visual
inspection confirmed S27 already swept this router to 26a-conformant
final state. The "2 missing `response_model=`" are the `/api/export/csv`
and `/api/export/json` endpoints — both return `PlainTextResponse`/
`Response` subclasses for raw-binary download with
`Content-Disposition: attachment`. Per compound 26a, response_model
is intentionally omitted; both carry `operation_id=` for SDK naming.
The module docstring (lines 1-10) already documents this since S27.

**Outcome: no code change.** This is the third consecutive partial-list
staleness (S31 `findings_v2.py`, S32 `agent_bindings.py` originally
planned, S37 `analytics.py`) — the partials count never accounted for
26a bare-by-design routes. Spec regeneration via `scripts/export_openapi.py`
produced zero-byte diff (`git diff --stat docs/openapi-v1.json` empty),
confirming wire-compat unchanged.

**Sweep progress:** 13 routers verified-or-shipped by this initiative
(prior 12 + analytics confirmed-final). **Sweep counter: 22/40 fully
typed** (21 carried from S36 + analytics confirmed-final under 26a).

Verification: `python -c "import api.analytics"` passes; 24c probe
5/3/5 matches S27 final state; spec regen byte-identical;
SPA-consumer grep returned only `deploy/smoke_e2e.ps1` (HTTP-200
assertion, no shape coupling) + ARCHITECTURE/plan docs.

**Compound rules amended this session (parallelization pivot):**
- **24b amendment (per-coupling-tier sweep).** Original "one router per
  session" rule was minted in S25-28 when every sweep touched live UI
  consumers. By S28+ most untouched routers have zero SPA consumers
  (verified by S25b grep pattern). New rule: routers batch by coupling
  tier. **Tier 1** (zero SPA consumers — verified via grep across
  `static/` + `team-portal/`): batch up to 5 in one Track A commit via
  parallel `implementer` subagents, single closeout. **Tier 2**
  (partials needing visual recount): batch up to 2 via parallel
  `Explore` agents. **Tier 3** (≥1 live SPA consumer or ≥6 routes):
  keep one-per-session. Rationale: serial pacing was protecting against
  blast radius that no longer exists for low-coupling routers.
- **Compound rule 28c (NEW — batch verification audits).** When ≥3
  consecutive sweep sessions are verification-only no-ops (S31
  `findings_v2`, S32-original `agent_bindings`, S37 `analytics`), the
  partials-list staleness is systemic, not per-router. Batch the
  remaining partials in a single audit-and-recount pass with parallel
  agents — do not spend one session per stale entry. Couples with the
  24b amendment above: verification batches sit in Tier 2.

**Partials list audit.** Quick 24c on remaining partials revealed
`api/reports.py` is also 6/3/6 mirroring analytics' exact shape
(3 JSON routes typed + 3 export endpoints bare-by-design per
S26 entry — already final). `api/assurance_model.py` is 5/12/12,
which is grep over-counting (docstrings/comments inflate the
recount — needs visual check per partials list note). The partials
bucket has effectively run dry; S38+ should pivot to the untouched
list (agent_notifications, metrics, traces, evaluate, assessment,
demo_run, demo, demo_control, aws_demo, framework, usage; defer
guide.py per high SPA coupling).

### Session 38 (FIRST parallel batch sweep — 7 routers in one session + 28a observation #5)

**Compound 28a observation #5 = NO** (`gh run list --commit=8e97454`
empty). Tally last 5 closeouts: S33 YES, S34 NO, S35 NO, S36 YES, S37 NO
= **2/5 fired**. Below decision gate threshold (3/5). Observation
continues; workflow unchanged. Gate moves to S38 closeout commit (obs #6).

**First execution of compound 24b amendment (per-coupling-tier batching).**
Session pivoted from one-router-per-session to a structured parallel batch:

**Tier 2 verify batch** (2 parallel `Explore` agents):
- `api/reports.py` → 26a-conformant final since S26. 3 JSON routes typed
  + 3 export endpoints (.json/.csv/.pdf) bare-by-design per 26a. PASS.
- `api/assurance_model.py` → fully swept (12 routes, all carry
  response_model + operation_id). Raw 5/12/12 grep was NOT inflation —
  the "5" was a glob mismatch on the route count probe; visual confirmed
  12 real decorators. PASS.
- Counter +2 (both confirmed-final).

**Tier 1 batch sweep** (5 parallel `implementer` subagents, single Track A commit `216359f`):
| Router | Routes | Pattern |
|---|---|---|
| `api/agent_notifications.py` | 1 SSE | op_id only per 26a |
| `api/metrics.py` | 1 Prometheus | op_id only per 26a |
| `api/traces.py` | 1 JSON | `TracesResponse` envelope + `TraceItemOut` + `EvalScoreEntry` (dynamic metric keys via `extra="allow"` per 27a) |
| `api/evaluate.py` | 1 JSON | `EvaluateResponse` envelope + `EvalScore` strict inner; `extra="allow"` on envelope for dynamic evaluator metric keys |
| `api/demo_run.py` | 2 routes | `DomainsResponse` strict + `DemoRunResponse` permissive (runs payload polymorphic across guardrail configs) |

**Pre-flight consumer-coupling grep gate** (Tier 1 safety net): batch
candidates were `agent_notifications, metrics, traces, evaluate,
demo_run, aws_demo` (zero SPA hits). Dropped to Tier 3 for future
sessions: `assessment` (1 SPA hit), `framework` (3 hits), `usage` (3 hits).
The grep gate IS the parallelization safety — without it, parallel
implementer agents could blast UI contracts.

**Spec regenerated once** for all 5 routers (24d, single export):
`docs/openapi-v1.json` +247/-10 (8 new component schemas + 6 renamed
operationIds). All 5 imports pass.

**Sweep progress:** 18 routers shipped/verified by this initiative
(prior 13 + reports verified + assurance_model verified + 5 Tier 1 batch).
**Sweep counter: 22 → 29/40 fully typed in one session** (vs ~7 sessions
under the original 24b rule). Validates the amendment.

Compound rule earned this session:
- **Session 38a:** When parallelizing a sweep via subagents, the
  consumer-coupling grep gate is what makes batching safe — not the
  agents themselves. Run the grep on EVERY candidate router before
  fan-out; routers with ≥1 SPA hit drop to Tier 3 regardless of route
  count. This pre-flight step takes <2 minutes and prevents the
  blast-radius failure mode that motivated the original one-per-session
  rule. Document the gate output in the session entry so future
  reviewers can see which routers were eligible.

### Session 39 (second parallel batch + first Tier 3 sequential + CISO Console scaffold kicked off)

**Compound 28a observation #6 = NO** (`gh run list --commit=aaca029`
empty). Tally last 6: **2/6 fired**. Below gate (3/5 of last 5).
Observation continues. Workflow unchanged.

**Track A — combined commit `7730d44` (1014/-109 lines):**

Tier 1 batch (3 parallel `implementer` subagents):
| Router | Routes | Pattern |
|---|---|---|
| `api/aws_demo.py` | 3 | 2 JSON permissive (large heterogeneous demo payloads) + 1 HTMLResponse bare per 26a |
| `api/demo.py` | 3 | `DemoStateResponse` strict + `DemoResetResponse` strict + `DemoStepResponse` permissive (13-step polymorphic) |
| `api/demo_control.py` | 3 | `ScenariosResponse` strict + `RunAcceptedResponse` strict + `RunStatusResponse` permissive (6-handler polymorphic) |

Tier 3 sequential (main session — has 1 SPA consumer `static/assessment.html`):
- `api/assessment.py` — 2 routes (POST `/run/{id}` + GET `/{id}` convenience alias). `AssessmentReportResponse` mirrors `domain.assessment_engine.AssessmentReport` dataclass with 6 strict nested models (`_RiskFactorsOut`, `_ResidualRiskScoreOut`, `_ReleaseRecommendationOut`, `_ControlEvaluationOut`, `_GeneratedFindingOut`, `_FrameworkCoverageOut`). Top-level `extra="allow"` for additive evolution; nested models strict because domain shapes anchor the contract. SPA consumer surface (`static/assessment.html`) reads 14 distinct field paths — all preserved by the strict mirror.

**Sweep progress:** 22 routers shipped/verified by this initiative.
**Sweep counter: 29 → 33/40** in one session (4 routers in one session
via Tier 1 batch + Tier 3 sequential). Validates the 24b amendment
holds under mixed-tier sessions.

**CISO Console SPA scaffold (V2 acceptance A5)** kicked off in
parallel worktree (`isolation: worktree`) — first 3 of 10 surfaces
(Findings inbox, Audit verification, RTF approval queue) using
locked Team Workspace pattern. Running in background; results
fold into S40 closeout if landed by then, otherwise next session.

### Sessions 40+ — OpenAPI sweep continuation
Post-S39 sweep state: **33/40 routers fully typed.** Empirical recount
output (preserve verbatim for next-session carry-over):

```
Fully clean (29 prior + 3 Tier 1 + assessment Tier 3 = 33):
  agents, ai_system_edit, audit_verify, batch, connectors,
  domains_api, evals_v2, evidence, findings_v2, grc, intake,
  projection, release_gates, right_to_forget, runtime_v2,
  security, frameworks, adversarial, memory, rag, agent_bindings,
  analytics, reports, assurance_model,
  agent_notifications, metrics, traces, evaluate, demo_run,
  aws_demo, demo, demo_control, assessment

Tier 3 remaining (has live SPA consumers — sequential, one per session):
  api/framework.py       (3 SPA hits — static/ai-systems.html, static/frameworks.html)
  api/usage.py           (3 SPA hits — static/analytics-usage.html)
  api/guide.py           (9 routes — high SPA coupling, defer late)

Tier 1 remaining (zero SPA consumers):
  none — bucket emptied at S39

Special-shape (already documented exceptions):
  api/agent_notifications.py — SSE only, op_id deferrable per S31 rule
  api/metrics.py             — Prometheus exposition, response_model n/a
```

Recommended S40+ plan: 3 remaining Tier 3 routers, one per session.
Order by SPA coupling: `framework` (S40) → `usage` (S41) → `guide`
(S42, 9 routes, largest). Counter: 33 → 34 → 35 → 40/40 (sweep complete
at S42). CISO Console SPA work continues in parallel worktree.

Defer to its own session: `api/guide.py` (9 routes, high SPA coupling).
- `api/agent_notifications.py` (1, SSE — would be op_id-only per S31 rule)
- `api/metrics.py` (1)
- `api/evaluate.py` (1)
- `api/assessment.py` (2)

Defer: `api/guide.py` (9 routes, high SPA coupling).

Fully-untyped candidates (small first): `agent_notifications.py` (1),
`metrics.py` (1), `traces.py` (1), `evaluate.py` (1), `assessment.py`
(2), `demo_run.py` (2), `demo.py` (3), `demo_control.py` (3),
`aws_demo.py` (3), `framework.py` (3), `usage.py` (3),
`guide.py` (9 — defer).

Pattern locked by Sessions 25-31:
1. Grep `static/` + `team-portal/` for `/api/<prefix>/` consumers first.
2. Draft Pydantic v2 BaseModels inline (or `api/contracts/` if duplication
   crosses three routers).
3. `response_model=` + `operation_id="<prefix>_<resource>_<verb>"`.
4. Regenerate `docs/openapi-v1.json` under `SL_OPENAPI_EXPORT_PROFILE=ci`.
5. Verify diff includes new schemas + new operationIds only (no removed routes).
6. **SSE/streaming routes get `operation_id=` only** — `response_model=`
   cannot apply; document the intentional gap in the file docstring (S31 lesson).

### Sessions 25-26 — Garak Deep Scan implementation (now unblocked)
ADR-001 accepted this session. Six-step plan per ADR §7: Dockerfile + sidecar server, `deploy/bicep/garak.bicep`, `domain/garak_bridge.py` + `frameworks/garak_severity.yaml`, `api/adversarial.py::deep_scan` endpoint, SPA tab split in `AdversarialPage.tsx`, end-to-end integration test. Independent of V2 critical path.

### ~~Session 24b — DNS + custom domain (V2 Phase 1 item A4)~~ ✓ Session 25
Closed in Session 25: `api.aigovern.sandboxhub.co` was already bound with SNI SSL active when discovery ran. Only the `SESSION_COOKIE_DOMAIN` env-var flip was needed to fully activate the parent-domain cookie path. Final manual step pending: one real-login DevTools verification of cookie `Domain` attribute.

### Session 40 (Track A Tier 3 sweep api/framework.py + RTF reject + CSM-2 parallel)
Two-track parallel push. Track A landed at [`8e2eb3f`](https://github.com/signalyer/ai-assurance-mvp/commit/8e2eb3f); CSM-2 (Track B) landed at [`e40fccd`](https://github.com/signalyer/ai-assurance-mvp/commit/e40fccd).

**Track A — A1 OpenAPI sweep 33/40 → 34/40 (85%) + RTF reject endpoint:**
- [api/right_to_forget.py](api/right_to_forget.py): NEW `POST /{cascade_id}/reject` (op_id `right_to_forget_reject`) mirroring `approve_cascade` shape — lookup → audit `RTF_REJECTED` with operator reason → return `CascadeResultOut`. `RejectCascadeIn` body is strict (`extra="forbid"`), reason 1-1024 chars. Auto-approved-stub workflow stays as-is (cascade runs sync inline at initiate per S08 §7.1); reject is audit-trail-only in MVP. Closes the CSM-1 carry-over 404 banner.
- [api/framework.py](api/framework.py): Tier 3 sweep. All 3 endpoints (`/catalog`, `/overview`, `/{item_id}`) now return strict Pydantic v2 response models (`FrameworkItemOut`, `ControlRollupOut`, `FindingSummaryOut`, `ItemCoverageOut`, `CatalogOut`, `OverviewOut`) mirroring the underlying dataclasses; all `extra="forbid"` per 27a. Operation_ids prefixed `framework_*` to avoid collision with `frameworks_*` from api/frameworks.py (S32). Consumer-coupling grep (38a): only `/overview` hits SPAs (governance.html line 112, security.html line 110); `/catalog` + `/{item_id}` are zero-consumer but typed uniformly.
- `docs/openapi-v1.json` regenerated ONCE via `scripts/export_openapi.py` per 24d.

**Track B — A5 CISO Console 3/10 → 6/10 (60%):**
- [ciso-console/src/pages/portfolio/](ciso-console/src/pages/portfolio/) — KPI strip + risk distribution 4-grid + top-10 by findings, drill link to /findings?system_id=. Pure read on GET /api/grc/ai-systems.
- [ciso-console/src/pages/release-gates/](ciso-console/src/pages/release-gates/) — per-system expandable rollups + inline gate table; CISO "Create Exception" on FAILED blocking gates → POST /v2/system/{id}/exception (button label matches endpoint; engine has no /override).
- [ciso-console/src/pages/frameworks/](ciso-console/src/pages/frameworks/) — matrix grid (systems × frameworks) with color-coded coverage cells, click-cell drill modal, per-framework PDF export. Consumes api/frameworks.py (plural, S32) — orthogonal to this session's api/framework.py (singular) Track A sweep.
- Build: tsc --noEmit PASS; vite build PASS (index 45.84 kB / 11.98 kB gzip).
- Spawned via parallel implementer subagent (run_in_background, worktree); isolation didn't take (agent wrote to main tree) — accepted per spawn-prompt fallback because net-new files in `ciso-console/src/pages/` had zero collision risk.

**Compound 28a observation #7:** CSM-1 commit `b7c2a3c` (pure ciso-console scaffold, zero engine code) fired `deploy` wastefully because `paths-ignore` doesn't cover SPA dirs. Tally **3/7** — below 3/5 decision gate; observation continues, workflow unchanged. When the gate hits, fix is likely additive (`team-portal/**`, `ciso-console/**` to `paths-ignore`) but must verify `deploy/build-zip.py` whitelist first per S19c.

**Remaining V2 critical path:** A1 Tier 3 = usage.py (S41) + guide.py (S42). A5 CISO Console = 4 more surfaces (Evidence, Analytics, Policies, Reports + RTF deep view across S41-S42). A6/A7 role-aware redirect + cutover (S43+).

### Session 41 (Track A Tier 3 sweep api/usage.py + 28a decision-gate fix + CSM-3 parallel)
Two-track parallel push, plus first 28a remediation. Track A landed at [`eaa0509`](https://github.com/signalyer/ai-assurance-mvp/commit/eaa0509); CSM-3 (Track B) landed at [`2dc1e17`](https://github.com/signalyer/ai-assurance-mvp/commit/2dc1e17).

**28a OBSERVATION → DECISION-GATE → ACTION (closed):**
S41 obs #8 confirmed CSM-2 commit `e40fccd` (pure ciso-console SPA, zero engine) fired `deploy` wastefully. Tally **4/8 — tripped 3/5 decision gate**. Action landed in same session: [.github/workflows/deploy.yml](.github/workflows/deploy.yml) `paths-ignore` extended with `team-portal/**` + `ciso-console/**`. Precondition verified per S19c: `deploy/build-zip.py` INCLUDE allowlist does NOT ship either SPA dir, so source-only commits to SPAs cannot affect the running engine. Reversal documented inline (e.g. if SSR ever ships server-side from SPA dirs). `workflow_dispatch` escape valve retained per S22b.

**Track A — A1 OpenAPI sweep 34/40 → 35/40 (88%):**
- [api/usage.py](api/usage.py): All 3 endpoints (`/summary`, `/active-sessions`, `/events`) now return strict Pydantic v2 envelopes (`SummaryOut`, `ActiveSessionsOut`, `EventsOut`) with `extra="forbid"`. Bounded nested rows (`TotalsOut`, `ByUserRow`, `TopPageRow`, `ByCountryRow`) are strict. Polymorphic nested rows (`ActiveSessionRow`, `EventRow`) use `extra="allow"` per compound 27a — sessions carry variable geo/UA enrichment; events vary by `event_type` (LOGIN vs PAGE_VIEW vs domain events). Explicit fields cover read-paths in static/analytics-usage.html (38a verified). Operation_ids prefixed `usage_*`.
- `docs/openapi-v1.json` regenerated ONCE via `scripts/export_openapi.py` per 24d.

**Track B — A5 CISO Console 6/10 → 9/10 (90%) + 1 bonus depth-surface:**
- [ciso-console/src/pages/evidence/](ciso-console/src/pages/evidence/) — Evidence Bundles: KPI row + completeness 4-axis switcher + filterable table with expandable per-row detail (full SHA-256 digest, linked controls/frameworks). Consumes GET /api/grc/evidence/v2/sectioned + /completeness. Verify button rendered disabled (engine has no CISO verify endpoint — surface deferred).
- [ciso-console/src/pages/analytics/](ciso-console/src/pages/analytics/) — Cross-portfolio Analytics: 4 KPIs + 3 breakdown cards (by-domain, by-model, failure-types) using inline bar rendering (no chart-lib dep) + daily trends table with period switcher. Consumes GET /api/analytics + /api/analytics/trends. Distinct from /api/usage (which is operator analytics).
- [ciso-console/src/pages/rtf-forensics/](ciso-console/src/pages/rtf-forensics/) — **NEW route** (added to app.tsx + Sidebar.tsx as "RTF Forensics", path `/rtf-forensics`). Operator-forensics counterpart to CSM-1's RTF Approval Queue (action-oriented). Cascade table → drill modal with per-store SHA-256 digests (vault/T2/T3/langfuse) + governance metadata + "Verify Chain Now" calling GET /api/audit/verify?window=200 (CLEAN/BROKEN banner). **Bonus surface not counted against A5 numerator** — Sidebar now 11 items.
- Build: tsc --noEmit PASS; vite build PASS (index 66.94 kB / 16.20 kB gzip).
- Spawned via parallel implementer subagent (no worktree this time — both prior CSMs bypassed isolation; pattern accepted).

**27a polymorphic-payload sub-rule (codified this session):** For Tier 3 sweeps where the underlying dict carries variable keys by record type (events keyed by event_type, session dicts with optional enrichment), the canonical pattern is: strict outer envelope + bounded nested rows strict + polymorphic nested rows `extra="allow"` with the read-path superset declared explicitly. Explicit-fields serve as schema documentation; `extra="allow"` preserves payload fidelity. Apply to remaining Tier 3 candidates if they exhibit the same shape.

**Remaining V2 critical path:** A1 Tier 3 = guide.py (S42) + 4 unspecified routers (suspected Tier 1, batch via parallel implementers in S42-43). A5 CISO Console = Policies + Reports (CSM-4 in S42 → 10/10). A6/A7 role-aware redirect + cutover (S43+).

### Session 42 (Track A Tier 3 sweep api/guide.py + 28a action validated + CSM-4 → A5 10/10 ✅)
Two-track parallel push. Track A landed at [`be71444`](https://github.com/signalyer/ai-assurance-mvp/commit/be71444); CSM-4 (Track B) landed at [`5d8ae2c`](https://github.com/signalyer/ai-assurance-mvp/commit/5d8ae2c).

**Track A — A1 OpenAPI sweep 35/40 → 36/40 (90%):**
- [api/guide.py](api/guide.py): Heaviest Tier 3 sweep to date — 8 of 9 endpoints consumed by `static/shared.js` (the Governance Assistant panel, shared across every V1 page). All shapes were bounded (no event-type polymorphism); strict envelopes + `extra="forbid"` per 27a default. 9 strict response models added (PageGuideOut, GlossaryOut, ControlsListOut, ControlDetailOut, FrameworksListOut, FrameworkItemDetailOut, SearchOut, TipsRegistryOut + per-row models). Two 27a polymorphic-sub-rule exceptions: `TipsRegistryOut.tips` is `dict[str, dict[str, Any]]` (tip records vary by type, consumed as map); `TipOut` single-tip endpoint uses `extra="allow"`. Operation_ids prefixed `guide_*`.
- `docs/openapi-v1.json` regenerated ONCE per 24d. **All KNOWN Tier 3 routers now complete.**

**Track B — A5 CISO Console 9/10 → 10/10 ✅:**
- [ciso-console/src/pages/policies/](ciso-console/src/pages/policies/) — read-only policy browser (list + click-drill modal with full text, last-eval, bound systems). Consumes GET /api/grc/policies. Deviation: dropped redundant detail-endpoint round-trip (list response is full shape).
- [ciso-console/src/pages/reports/](ciso-console/src/pages/reports/) — catalog + per-system Generate/Download (PDF/JSON/CSV). Consumes GET /api/reports/catalog, /systems, /{type}, /{type}/export.{pdf,json,csv}. Two deviations driven by engine reality: (a) PDF export opens new tab — engine returns print-ready HTML per /api/report/compliance pattern, user Ctrl+Ps; (b) Generate button validates via JSON data endpoint then unlocks downloads — engine has no separate job endpoint (exports are sync server-side builders).
- Build: tsc --noEmit PASS; vite build PASS (index 79.70 kB / 18.85 kB gzip).
- app.tsx + Sidebar.tsx unchanged (stubs overwritten in place).

**Compound 28a action VALIDATED (closed):**
First post-action SPA-only commit was CSM-4 (`5d8ae2c`). CI evidence:
- `be71444` (engine code — api/guide.py): fired contract-tests + deploy ✓
- `5d8ae2c` (pure ciso-console SPA): fired contract-tests **only — NO deploy** ✓

The S41 `paths-ignore` extension to `team-portal/**` + `ciso-console/**` works as designed. 28a closes from observation → decision-gate → action → validation across 8 sessions (S35-S42). Workflow_dispatch escape valve retained per S22b for the edge case.

**V2 acceptance state after S42:**
- A1 OpenAPI: **36/40 (90%)** — 4 routers remaining, all suspected Tier 1 (pre-flight 38a grep in S43 to confirm)
- A5 CISO Console: **10/10 ✅ DONE** (+ 1 bonus RTF Forensics depth-surface)
- A2/A3/A4/A8/A10/A14/A16: ✓ (prior sessions)
- A6/A7: blockers — role-aware login redirect (S43-44)
- A12/A13: blockers — cutover work (S44-45)
- A15: 🟡 Bicep ✓; P1v3 + staging slot independent infra track
- A9, A11 (Garak): locked-deferred / out-of-scope V2

**Trajectory:** A1 likely closes 40/40 in S43 (fan-out 4 Tier 1 routers via parallel implementers per 24b). S44 = role-aware redirect + smoke harnesses. S45 = V1→V2 302 + DNS rehearsal. V2 live in ~3 more sessions.

### Session 13 — V2 Phase 1 (Engine Hardening + Carry-Over Debt) — status
See `docs/plans/SESSION-13-v2-engine-hardening.md`. Closeout status:
- Track A: A1 OpenAPI hardening (per-router series, 5/25 done Sessions 25-29), A2 contract tests ✓ Session 18, ~~A3 parent-domain cookie~~ ✓ Session 24 (activated Session 25), ~~A4 CNAME~~ ✓ Session 25 (env-var flip + verified-already-bound)
- Track B: ~~B1 `tests/test_deploy_completeness.py`~~ ✓ Session 23, B2 ARCHITECTURE.md backfill ✓ Sessions 11-24 inline, ~~B3 SESSION-12B §6 update~~ ✓ Session 24
- Deferred: App Insights staging, P1v3 + staging slot, CI-on-merge deploy ✓ Session 19

### Garak Deep Scan — implementation (per ADR-001 §7)
Six-step plan deferred to a future session pending ADR-001 acceptance: Dockerfile + sidecar server, `deploy/bicep/garak.bicep`, `domain/garak_bridge.py` + `frameworks/garak_severity.yaml`, `api/adversarial.py::deep_scan` endpoint, SPA tab split in `AdversarialPage.tsx`, end-to-end integration test. Estimated 2 sessions.

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
python -c "from signallayer import init, guard; print('SDK OK')"                     # after Session 09
python -c "from sl.main import app; print('CLI OK')"                                 # after Session 09
python -c "from middleware.hmac_auth import HMACAuthMiddleware; print('hmac OK')"    # after Session 09
python -c "from domain.projection import project_event; print('projection OK')"      # after Session 09
python -c "from observability.counters import record_scrub, record_policy_deny; print('counters OK')"  # after Session 10
python -c "from observability.middleware import RequestContextMiddleware; print('request_ctx OK')"  # after Session 10
python -c "from api.demo_control import router; print('demo_control OK')"            # after Session 11
python -c "from middleware.guardrails import _extract_text; assert _extract_text({'response_text':'x'})=='x'; print('extract_text OK')"  # after Session 12B
python -c "from guardrails.llama_guard_adapter import LlamaGuardEvaluator; r=LlamaGuardEvaluator.evaluate('discuss execution of allocation strategy'); assert r.safe, 'FAIL: word-boundary regression'; print('word-boundary OK')"  # after Session 12B
python -c "import logging,audit; logging.getLogger('any').warning('no action key needed'); print('audit no-root-mutation OK')"  # after Session 12B
python -m pytest tests/ -v                                                     # after Session 10 — expect 252 passed
pwsh deploy/smoke_e2e.ps1                                                      # after Session 12B — expect 6/6 PASSED
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
