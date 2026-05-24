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

## Files — Planned
### Session 13 — V2 Phase 1 (Engine Hardening + Carry-Over Debt)
See `docs/plans/SESSION-13-v2-engine-hardening.md`. Two parallel tracks:
- Track A (V2 prep): OpenAPI hardening, contract tests, parent-domain cookie, `api.aigovern.sandboxhub.co` CNAME
- Track B (V1 debt): `tests/test_deploy_completeness.py`, ARCHITECTURE.md backfill, SESSION-12B §6 update
- Deferred: App Insights staging, P1v3 + staging slot, CI-on-merge deploy

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
