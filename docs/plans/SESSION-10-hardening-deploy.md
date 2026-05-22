# SESSION 10 — Production Hardening + Load Tests + Deploy

**Sprint day:** 10 of 12
**Date drafted:** 2026-05-22
**Predecessors:** Sessions 01a/01b/02/03/04/05/06/07/08/09 — all complete (179 tests pass · 3 commits ahead of `origin/main`)
**Status:** PRE-EXECUTION REVIEW — awaiting 4 locked decisions + explicit "go" before sub-agent spawn

---

## 1. Decorator chain (UNCHANGED)

```
@policy_gate → @scrub_pii → @guardrails → @trace_llm_call → @evaluate_response
```

Session 10 does **NOT** touch decorator implementations or order. Hardening = (a) fixing the 19 debt items already inventoried in `docs/HANDOFF.md` § *Open items (debt)*, (b) adding observability instrumentation as **side-effect counters** at decorator entry/exit points (counter increments only — no behaviour change), (c) load-test harness, (d) App Insights wiring + 8 alerts as IaC, (e) deploy + smoke. The HMAC canonical signing string (locked in Session 09 DECISIONS.md) stays byte-identical across `sdk/signallayer/client.py`, `cli/sl/auth.py`, `middleware/hmac_auth.py`.

---

## 2. Files to CREATE (one-line purpose each)

### Observability layer
| File | Purpose |
|---|---|
| `observability/__init__.py` | Package marker. |
| `observability/counters.py` | Process-local counters via `prometheus_client`-compatible API (Counter/Histogram); exposes `record_scrub`, `record_eval_failure`, `record_policy_deny`, `record_pii_leak`, `record_opa_unreachable`, `record_vault_error`, `record_audit_chain_break`, `record_rtf_cascade`. Idempotent registration. |
| `observability/app_insights.py` | Azure Monitor / App Insights exporter wiring via OpenTelemetry SDK (`opentelemetry-sdk` + `azure-monitor-opentelemetry-exporter`). `init_app_insights(connection_string)` called once from `dashboard.py`. No-ops if connection string missing. |
| `observability/structured_log.py` | `get_logger(name)` returns a JSON-formatted logger (operation_id, request_id, role, vault_id, trace_id keys); attached as the global root handler. Replaces ad-hoc `logging.getLogger` in NEW code only — does not retrofit old modules. |
| `observability/middleware.py` | `RequestContextMiddleware` — generates `X-Request-Id` if absent, stamps it into a `contextvars.ContextVar`, accessible to every log line via the structured formatter. |
| `api/metrics.py` | `GET /api/metrics` — Prometheus exposition format; gated to `MetricsViewer` role; returns 404 if `METRICS_ENABLED != "true"`. |

### Load-test harness
| File | Purpose |
|---|---|
| `loadtests/__init__.py` | Package marker. |
| `loadtests/locustfile.py` | Locust scenarios — 100 RPS sustained: `mix_scrub_60`, `mix_policy_20`, `mix_framework_10`, `mix_health_10`. Reads target URL from `LOCUST_TARGET` env. |
| `loadtests/scrubber_perf.py` | Standalone microbench — 10k payloads through scrubber; asserts p95 < 100ms. Runnable via `python -m loadtests.scrubber_perf`. |
| `loadtests/framework_coverage_perf.py` | Microbench — `framework_matrix(["sys-payments-001", ...])` over the 6 seeded systems × 8 frameworks; asserts < 2s. |
| `loadtests/opa_p95.py` | Microbench — 1000 policy evaluations via `domain.policy_engine`; asserts p95 < 50ms. |
| `loadtests/README.md` | How to run each test + expected pass thresholds. |

### IaC (Bicep — Azure App Service standard)
| File | Purpose |
|---|---|
| `deploy/bicep/main.bicep` | Top-level deployment composing app-service-plan + web-app + app-insights + log-analytics-workspace. |
| `deploy/bicep/appinsights.bicep` | App Insights component + Log Analytics workspace reference. |
| `deploy/bicep/alerts.bicep` | 8 alerts (see Acceptance § A6 for the list): each as a `Microsoft.Insights/metricAlerts` or `scheduledQueryRules`. |
| `deploy/bicep/parameters.dev.json` | Parameters file for dev subscription (eastus). |
| `deploy/bicep/README.md` | Deploy command: `az deployment group create ...`. |

### Security review + smoke
| File | Purpose |
|---|---|
| `deploy/security_scan.ps1` | Runs `bandit`, `pip-audit`, and a custom secrets-grep over `*.py` + `*.html`. Outputs `data/security_scan_report.json`. Fails non-zero on any HIGH. |
| `deploy/smoke_e2e.ps1` | Runs the 6 demo scenarios against `$env:SMOKE_TARGET_URL`. Each scenario asserts a specific endpoint response. Exit non-zero on any failure. |
| `tests/test_session10_observability.py` | Unit tests for counters (idempotent registration, increment semantics, label cardinality bounds). |
| `tests/test_session10_hardening.py` | Regression tests asserting the FIXED debt items: nonce cache cap behaviour, projection rollback wraps secondary failure, `/api/health` no longer leaks `api_keys`, `cli/sl/config.py` uses `O_CREAT|O_WRONLY|O_TRUNC` mode 0o600 (POSIX assertion via patched os.open), pagination/limits on `purge_chunks` and `purge_episodes`, advisory file lock on `domain/audit_chain.py`. |
| `tests/test_session10_perf_smoke.py` | A fast (<5s) version of the three microbenches running 50 ops each — verifies the harness runs, not the production threshold. |
| `docs/RUNBOOK.md` | Operational runbook: what each alert means, who to page, rollback steps. |
| `docs/plans/SESSION-10-hardening-deploy.md` | THIS FILE. |

**Total new files:** ~24.

---

## 3. Files to MODIFY (exact change — debt fix or observability hook)

### Session 09 NEW debt fixes
| File | Exact change |
|---|---|
| `middleware/hmac_auth.py` | `_get_secret()` reads `os.environ` ONCE at module load → module-level `_SECRET: bytes \| None = _read_secret_env()`; per-request call replaced with `secret = _SECRET`. Fail-closed at import if `STRICT_HMAC_BOOT=true`. |
| `cli/sl/config.py` | `save_credentials`: replace open+chmod with `os.open(path, os.O_WRONLY \| os.O_CREAT \| os.O_TRUNC, 0o600)` (POSIX); Windows path unchanged (icacls). Closes TOCTOU window. |
| `dashboard.py` | Remove hand-rolled `.env` parser (lines 13-23 — dead after `load_dotenv(override=True)`). Strip `api_keys` dict from `/api/health` response (return only `{"status": "ready"|"incomplete"}`). Init App Insights via `observability.app_insights.init_app_insights(os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING"))`. Mount `RequestContextMiddleware` outermost-of-the-outermost. Mount `api/metrics.router`. |
| `domain/projection.py` | Delete dead `_DISPATCH` dict (or replace `_dispatch()` if/elif body with `_DISPATCH[event_type](event, conn)` lookup — implementer choice, but ONE source of truth). Wrap `conn.rollback()` in nested try/except to preserve original exception. |
| `cli/sl/main.py` | `Optional[bool]` → `bool \| None`; remove `Optional` import and `# noqa: UP007`. |

### Session 08 carried debt fixes
| File | Exact change |
|---|---|
| `api/audit_verify.py` | Add `Depends(require_role("auditor", "ciso"))` to `GET /api/audit/events`. Add `public_mode: bool = False` query param; when public, strip `subject_id`, `reason`, and any `scrubbed_prompt` fields from the response. Switch pagination from tail-relative to absolute `from_index`. |
| `domain/agent_memory.py` | Migrate `purge_episodes` Postgres SQL from `metadata::text LIKE '%<subject_id>%'` to `metadata->>'subject_id' = %s`. Add `CREATE INDEX IF NOT EXISTS idx_episodes_subject_id ON episodes((metadata->>'subject_id'))` migration. JSONL fallback already correct (compaction). |
| `domain/rag_engine.py` | `purge_chunks` adds `$skip` pagination loop; iterate until `value` array is empty; bound max iterations to 100 (100k chunks/subject sanity cap). |
| `domain/audit_chain.py` | Cache `prev_hash` + `chained_count` in module-level state; `append_chained_event` updates atomically under existing global lock (eliminates O(n) re-read). Add `_acquire_writer_lock()` advisory file lock via `portalocker` (cross-platform: `fcntl.flock` Linux / `msvcrt.locking` Windows) — bounded wait 5s, fail-closed if not acquired. |
| `domain/right_to_forget.py` | `_find_completed_cascade` — replace tail-5000 scan with a sidecar file `data/rtf_completed_index.jsonl` written during cascade emission; remove `_store_funcs` callable dead code; bound `_completed_cache` to LRU max 1000 entries (`functools.lru_cache` via wrapper or `cachetools.LRUCache`). |

### Observability hooks (additive — counter increments only)
| File | Exact change |
|---|---|
| `middleware/scrubber.py` | Call `observability.counters.record_scrub(detected_count)` after tokenisation. No behaviour change. |
| `middleware/policy.py` | Call `record_policy_deny()` when raising `PolicyDeniedError`. |
| `middleware/injection.py` | Call `record_pii_leak()` on detection (counter name is "pii_leak_attempt"; we count attempts not successful leaks). |
| `domain/policy_engine.py` | Call `record_opa_unreachable()` on the OPA HTTP-client fallback path. |
| `domain/deid_vault.py` | Call `record_vault_error()` on Fernet decryption failure. |
| `domain/audit_chain.py` | Call `record_audit_chain_break()` from `verify_chain` when `status != CLEAN`. |
| `domain/right_to_forget.py` | Call `record_rtf_cascade(status)` from `cascade()` exit. |
| `evaluator.py` | Call `record_eval_failure()` when metric score below threshold. |
| `requirements.txt` | Add `opentelemetry-sdk>=1.27`, `azure-monitor-opentelemetry-exporter>=1.0.0b30`, `prometheus-client>=0.20`, `portalocker>=2.10`, `locust>=2.30` (locust is optional dev dep — move to `requirements-dev.txt` if it exists). |
| `ARCHITECTURE.md` | Append Session 10 block. |
| `DECISIONS.md` | Append 4 new entries (multi-worker · SDK feed · load-test target · App Insights workspace). |
| `docs/HANDOFF.md` | Rewrite for Day 11 entry; record 179 → ~200+ test count; close debt items; surface any new debt. |
| `local.env` | Add `APPLICATIONINSIGHTS_CONNECTION_STRING=`, `METRICS_ENABLED=true`, `STRICT_HMAC_BOOT=false`, `LOCUST_TARGET=http://localhost:8000`. |

**No modifications to:** SDK signing canonical string, decorator chain order, scrubber/policy/guardrails business logic, audit hash algorithm, projection schema, Session 08 cascade orchestration semantics.

---

## 4. Two most critical architectural constraints

1. **HMAC canonical signing string is FROZEN.** Three files contain it: `sdk/signallayer/client.py`, `cli/sl/auth.py`, `middleware/hmac_auth.py`. Format `f"{unix_ts}\n{METHOD}\n{path}\n{sha256_hex(body)}"`. Session 10 changes the *reading* of the secret (module-level cache) but NOT the canonical input. The hardening tests must include a byte-equality check that the three signers produce identical hex for a fixed (key, ts, method, path, body, nonce) tuple. Any drift breaks every SDK + CLI client in the field.

2. **Audit-chain writer-lock and prev_hash cache must be transactionally consistent.** The Session 08 invariant — append + prev_hash linkage are atomic — must survive the prev_hash cache optimisation. The implementation MUST: (a) acquire writer lock, (b) read cache OR seed cache from file if cache empty, (c) compute new hash, (d) append to file, (e) update cache, (f) release lock — in that order, no early returns. Test: spawn 100 concurrent appenders against the same `events.jsonl`, verify final chain `verify_chain(full=True) == CLEAN` and `chained_count == 100 + pre-existing`.

---

## 5. Will NOT build (explicit non-goals)

- Key Vault migration (carried — this is a demo build per CLAUDE.md global rules; production migration is Phase 2).
- Managed Identity for service-to-service auth (Phase 2).
- VNet integration / private endpoints (Phase 2).
- Per-tenant Azure AI Search index (single-tenant v1).
- HA OPA cluster (single sidecar v1).
- ISO 42001 / SR 11-7 / FFIEC PDF Packs — endpoints stay 501 (Session 11).
- Demo Control panel and 6-scenario talk tracks (Session 11).
- Stakeholder dry-run + final deploy (Session 12).
- Streaming eval-as-traffic (batch only per Section 8 sprint plan).
- Node/Go/Java SDKs (Python only).
- Real-time webhooks (polling sufficient).
- BYO Azure subscription deploys (single subscription).
- 3 SQLAlchemy engines consolidation — carried Session 07 debt; LOW priority; only fix if implementer has spare cycles, otherwise deferred to Phase 2.
- `ai-systems.html` legacy XSS audit — carried Session 07 debt; addressed only as part of secrets-and-XSS scan in `deploy/security_scan.ps1` if the scan flags it; no manual rewrite this session.

---

## 6. Acceptance criteria (runnable assertions)

| # | Criterion | Runnable assertion |
|---|---|---|
| A1 | All 179 prior tests still pass | `pytest tests/ --basetemp=./data/_pytest_tmp -q` ≥ 179 passed |
| A2 | New session 10 tests pass | `pytest tests/test_session10_*.py --basetemp=./data/_pytest_tmp` exits 0 |
| A3 | HMAC byte-equality across 3 signers | `tests/test_session10_hardening.py::test_hmac_canonical_byte_equal_three_signers` passes for a fixed tuple |
| A4 | Scrubber p95 < 100ms | `python -m loadtests.scrubber_perf` exits 0; prints `p95=<100ms` |
| A5 | OPA p95 < 50ms | `python -m loadtests.opa_p95` exits 0 |
| A6 | Framework coverage < 2s | `python -m loadtests.framework_coverage_perf` exits 0 |
| A7 | Load test sustains 100 RPS for 10 min p95 < 2s zero errors | `locust -f loadtests/locustfile.py --headless -u 100 -r 20 --run-time 10m --host $LOCUST_TARGET` exits 0; final report `fails == 0`, `p95 < 2000ms` (runs against the deployed target per decision Q3) |
| A8 | 8 App Insights alerts deployed | `az monitor metrics alert list -g rg-aigovern-dev -o tsv | wc -l` ≥ 8. The 8 alerts: (1) PII leak counter > 0 in 5min, (2) OPA unreachable in 5min, (3) Vault decryption error count > 5 in 15min, (4) Audit chain BROKEN in any verify call, (5) HTTP 5xx rate > 1% in 5min, (6) p95 latency > 2s in 5min, (7) RTF cascade PARTIAL_FAILURE in any run, (8) scrub rate (scrubs/req) drops below 0.5 in 30min (detection regression). |
| A9 | Zero CRITICAL/HIGH in security scan | `pwsh deploy/security_scan.ps1` exits 0 |
| A10 | E2E smoke on deployed URL | `pwsh deploy/smoke_e2e.ps1` exits 0 |
| A11 | `/api/metrics` returns Prometheus format | `curl -H "X-Role: MetricsViewer" $HOST/api/metrics | head -1` matches `# HELP` |
| A12 | `/api/health` no longer leaks api_keys | response JSON has no `api_keys` key |
| A13 | Audit chain writer-lock concurrency | `tests/test_session10_hardening.py::test_audit_chain_100_concurrent_appenders` passes |
| A14 | RTF sidecar index used (no tail-scan) | `grep -n "_find_completed_cascade" domain/right_to_forget.py` shows index-file lookup, not events.jsonl tail scan |
| A15 | Bicep deploys clean to dev RG | `az deployment group what-if` returns no errors; `az deployment group create` for `deploy/bicep/main.bicep` returns ProvisioningState=Succeeded |

**Pass bar:** A1–A6 + A11–A14 (10 criteria) MUST pass locally before commit. A7, A8, A10, A15 run against the deployed environment after commit — they gate the demo, not the commit.

---

## 7. Locked-decision dependencies (BLOCKING)

Sub-agent spawn does NOT proceed until the 4 questions below are answered:

- **Q1 — Multi-worker deploy:** affects `dashboard.py` startup (single uvicorn vs gunicorn workers), `middleware/hmac_auth.py` nonce cache (in-process vs Redis), `deploy/bicep/main.bicep` App Service Always-On config + ARR-Affinity.
- **Q2 — SDK feed:** affects `deploy/bicep/main.bicep` Azure Artifacts feed resource + `sdk/publish.ps1` gate flip vs no-op.
- **Q3 — Load test target SKU:** affects `deploy/bicep/parameters.dev.json` (`appServicePlanSku: "B1"` vs `"S1"`) + budget impact (~$13/mo B1 vs ~$70/mo S1). 100 RPS sustained on B1 is unlikely without scale-out; S1 + autoscale is honest.
- **Q4 — App Insights workspace:** affects `deploy/bicep/appinsights.bicep` (new vs `existing log-aigovern-dev` reference).

---

## 8. Sub-agent plan (executes ONLY after approval)

Single `Agent` message with 3 parallel implementers (per `feedback_subagents_context_default.md`):

1. **Debt-fix implementer** — owns all 9 debt fixes in § 3 (Session 09 NEW + Session 08 carried + observability hooks); also writes `tests/test_session10_hardening.py`. SCOPED to Python files only.
2. **Observability + IaC implementer** — owns `observability/**`, `api/metrics.py`, `deploy/bicep/**`, `docs/RUNBOOK.md`, `tests/test_session10_observability.py`.
3. **Load-test implementer** — owns `loadtests/**`, `deploy/security_scan.ps1`, `deploy/smoke_e2e.ps1`, `tests/test_session10_perf_smoke.py`.

Then sequentially:
4. Full test run: 179 regression + new (target ≥ 200 pass).
5. Parallel `code-reviewer` + `security-reviewer` in one Agent message.
6. Apply review fixes inline.
7. Update `ARCHITECTURE.md` + `DECISIONS.md` + `docs/HANDOFF.md`.
8. Commit: `Feat: Session 10 — Production hardening + load tests + IaC (Day 10)`.
9. **DEPLOY-GATED FOLLOW-UPS (not part of commit):** Bicep deploy → smoke → load-test run. These four artefacts (deployment, alerts created, smoke pass, load-test report) flagged as Day 11 prereqs in HANDOFF.md.

---

## 9. Open risks for this session

- **Scope is large.** 24 new files + 9 debt-fix touchpoints + 3 IaC files in one session. Mitigation: 3 parallel implementers; defer the "advisory file lock on audit_chain" to a follow-up commit if the implementer blocks.
- **Locust on Windows dev box.** Python 3.14 + gevent compatibility unverified. Mitigation: locustfile pinned to `locust>=2.30` which has 3.13+ support; if 3.14 issue arises, fall back to `httpx`-based async load runner.
- **App Insights connection string drift.** Bicep creates the AI component but the connection string must be injected into the App Service settings. Mitigation: Bicep output → `az functionapp config appsettings set` in `deploy-all.ps1` (existing script).
- **Audit-chain prev_hash cache + writer-lock concurrency.** This is the hardest correctness change. Mitigation: 100-thread test (A13) is non-optional; revert the optimisation if the test does not converge by mid-session.
- **B1 SKU 100 RPS sustained.** Almost certain to fail; the decision matters here (Q3). The plan's acceptance line is honest about this — A7 runs against whichever SKU Q3 picks.
