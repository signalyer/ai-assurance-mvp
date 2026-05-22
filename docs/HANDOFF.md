# Resume — AI Assurance Platform

**Last session ended:** 2026-05-22 (Day 10 of 12 — Sessions 01-10 complete · 4 commits ahead of origin after this commit lands)
**Repo state:** ready to commit · `main` (next commit = Session 10)
**GitHub:** https://github.com/signalyer/ai-assurance-mvp (private)

---

## Where I am
Day 10 of the 12-day production sprint complete:
- 01a/01b: Scrubber + Fernet vault + `@scrub_pii` ✓
- 02: Policy engine + OPA + `@policy_gate` ✓
- 03: Guardrails (injection + topic + safety) + `@guardrails` ✓
- 04: Memory (Postgres TTL) + RAG (Azure AI Search hybrid) ✓
- 05: Provider abstraction (5 Protocols + BaseSettings + 7 backends) ✓
- 06: Framework Coverage Matrix (6 systems × 8 frameworks) + YAML catalogs + 3 PDF Packs ✓
- 07: Multi-Agent + Agent Library (6 seeded agents, 6 new test systems, Postgres pubsub) ✓
- 08: Right-to-Forget cascade + Tamper-Evident Audit log ✓
- 09: CLI (`sl`) + Python SDK (`signallayer`) + Postgres event projection ✓
- 10: **Production hardening — observability layer + Bicep IaC + load tests + 18 debt fixes** ✓

Decorator chain (unchanged): `@policy_gate → @scrub_pii → @guardrails → @trace_llm_call → @evaluate_response`
Tests: 224 total — 179 prior regression + 45 new (10 hardening + 25 observability + 12 perf-smoke). All pass.

## Decisions locked (DECISIONS.md — don't re-litigate)
Sessions 01-09 decisions unchanged. New Session 10 decisions:
- **Workers:** Single uvicorn worker, NO Redis. In-memory nonce cache documented as scale limit. `STRICT_HMAC_BOOT=true` enforces secret presence at startup.
- **SDK feed:** Deferred to post-demo. `publish.ps1` DRY-RUN; provisioning checklist in RUNBOOK.md.
- **Load test target:** B1 SKU. A7 acceptance adjusted from 100 RPS → 25 RPS sustained for 10 min, p95 < 2s, zero errors. 100 RPS deferred to Phase 2 + S1 autoscale.
- **App Insights:** NEW workspace `log-aigovern-prod` + new App Insights component `appi-aigovern-prod` (named "prod" intentionally — future-prod backbone provisioned now in `rg-aigovern-dev`).

## Critical findings FIXED in Session 10 (post-review)
- ✅ `require_role()` with empty args raised ValueError (was: silently opened dev access)
- ✅ `_strip_public` is now recursive — nested PII (subject_id, reason) inside `payload` sub-dicts stripped at every depth
- ✅ `purge_chunks` raises on pagination cap (was: warn-and-continue → silent under-purge / GDPR violation)
- ✅ App Insights conn-string prefix no longer logged
- ✅ `smoke_e2e.ps1` host allowlist guards against synthetic-PII send to prod URLs
- ✅ secrets-grep patterns broadened (Anthropic `sk-ant-`, Postgres conn strings, Azure Storage AccountKey, SAS sig)
- ✅ `_seed_cache_from_file` docstring corrected (was: claimed reverse-tail; actual: full file scan on cold start)
- ✅ RTF sidecar/events disagreement now emits `logger.warning` (was: silent fallthrough → potential double-purge)

## Working rules in effect (memory)
- `feedback_subagents_context_default.md` — 3+ file sessions default to parallel sub-agents
- `feedback_batch_llm_calls.md` — never sequential LLM calls when asyncio.gather possible
- `feedback_appservice_deploy_python.md` — 10 failure modes on Python App Service deploys

## Key files to load for next session
1. `CLAUDE.md` — auto-loaded
2. `ARCHITECTURE.md` — current Built state through Session 10
3. `DECISIONS.md` — all locked decisions including 4 new Session 10 entries
4. `docs/plans/12-DAY-PRODUCTION-SPRINT.md` — Day 11 spec (demo orchestration + ISO/SR-11-7/FFIEC PDF Packs)
5. `docs/plans/SESSION-10-hardening-deploy.md` — completed Session 10 plan
6. `docs/RUNBOOK.md` — alert definitions, rollback, KQL snippets, Azure Artifacts feed checklist
7. `deploy/bicep/` — IaC ready for `az deployment group create`

## Outstanding questions for next session (Day 11)
1. **Demo Control panel:** new `static/demo-control.html` extending AWS Analyzer pattern, or evolve the existing `static/demo.html` in place?
2. **PDF Pack engines (ISO 42001 / SR 11-7 / FFIEC):** copy the NIST/OWASP/EU AI Act pattern verbatim (3 stdlib-only generators) or factor a shared `pdf_pack_base.py` first?
3. **Demo narration storage:** talk tracks inline in HTML data-attributes vs separate `docs/demo-scripts/` markdown files referenced by the Control panel?
4. **20-Q&A prep document:** living in `docs/DEMO-QA.md` or section-appended into `docs/RUNBOOK.md`?

## Next concrete action
Read `CLAUDE.md`, `ARCHITECTURE.md`, `DECISIONS.md`, then `docs/plans/12-DAY-PRODUCTION-SPRINT.md` Day 11 section. Draft `docs/plans/SESSION-11-demo-orchestration.md` with the 6-item pre-execution review. Ask the 4 locked-decision questions above. Wait for explicit "Y" / "go" / "approved" before spawning agents.

## Deploy-gated follow-ups (NOT in commit — manual run required)
- **Bicep deploy:** `az deployment group create --resource-group rg-aigovern-dev --template-file deploy/bicep/main.bicep --parameters @deploy/bicep/parameters.dev.json`
- **Set conn string in App Service:** `az functionapp config appsettings set --name app-aigovern-dev --resource-group rg-aigovern-dev --settings "APPLICATIONINSIGHTS_CONNECTION_STRING=$(az resource show ... --query properties.connectionString -o tsv)"`
- **Verify 8 alerts present:** `az monitor scheduled-query list -g rg-aigovern-dev --query "[].name" -o tsv | wc -l` ≥ 8
- **Run smoke against deployed URL:** `$env:SMOKE_TARGET_URL = "https://aigovern.azurewebsites.net"; pwsh deploy/smoke_e2e.ps1` (note: requires either dev/staging suffix or `SMOKE_ALLOW_PROD=true`)
- **Run 25-RPS load test:** `$env:LOCUST_TARGET = "https://aigovern.azurewebsites.net"; pip install -r requirements-dev.txt; locust -f loadtests/locustfile.py --headless -u 25 -r 5 --run-time 10m --host $env:LOCUST_TARGET`

These four artefacts (deployment, alerts created, smoke pass, load-test report) are Day 11 prereqs — they gate the demo, not the commit.

## Open items (debt) — Day 11/12 priorities

### NEW from Session 10 review (not blocking the commit)
- **SECURITY DEBT (HIGH — Day 11):** RTF sidecar `data/rtf_completed_index.jsonl` has no integrity check. If an attacker writes to `data/`, they can mark a NEW subject as "already completed" and prevent GDPR purge. Mitigation: HMAC-sign each sidecar entry with `SL_HMAC_SECRET`, verify on read. Reject unsigned entries and fall back to events.jsonl scan.
- **SECURITY DEBT (MEDIUM — Day 11):** `cli/sl/config.py` uses `O_CREAT|O_WRONLY|O_TRUNC`. Symlink-attack vector: attacker pre-creates the credentials path as a symlink to a sensitive file → TRUNC truncates the target. Fix: `O_CREAT|O_EXCL` for first write (refuse to overwrite); separate update path with fd-confirmed-regular-file check.
- **SECURITY DEBT (MEDIUM — Day 11):** `X-Request-Id` header accepted from client verbatim; no validation. Mitigation: enforce regex `^[a-zA-Z0-9\-_]{1,64}$`; reject and generate UUID on violation.
- **CODE DEBT (MEDIUM — Day 11):** `domain/audit_chain.py` checkpoint write at line 358-368 is released BEFORE the file lock. Documented as single-worker-safe; if multi-worker is ever enabled, checkpoint duplication is possible. Either move checkpoint inside lock or assert single-worker at startup.
- **CODE DEBT (MEDIUM — Day 11):** `domain/audit_chain.py` `_acquire_writer_lock` wraps Lock CONSTRUCTION in try/except `LockException`, but portalocker raises on `__enter__` not `__init__`. The except branch is dead. Move the wrap to the `with` block at the call site.
- **CODE DEBT (MEDIUM — Day 11):** `api/metrics.py` `_token_valid` reads `METRICS_TOKEN` per-request. Cache at module load (same pattern as `_SECRET` in hmac_auth.py).
- **CODE DEBT (LOW — Day 11):** `observability/counters.py:43` accesses `REGISTRY._names_to_collectors` (prometheus_client private API). Replace with `REGISTRY.get_sample_value` probe.
- **CODE DEBT (LOW — Day 11):** `domain/right_to_forget.py` `list_cascades()` still full-scans events.jsonl; could consult the new sidecar index.
- **CODE DEBT (LOW — Day 11):** Bicep `alerts.bicep` queries `customMetrics` — verify against actual telemetry table once App Insights is receiving data; OTel bridge may write to `customEvents` instead.
- **CODE DEBT (LOW — Day 11):** `middleware/auth.py` `require_role` assumes `demo-` user prefix; document the assumption inline.

### Carried from Session 09 (closed in Session 10) — for reference
- ✅ Multi-worker Redis: NOT needed; Q1 decision locked single worker.
- ✅ TOCTOU on credentials write: fixed via atomic os.open (further harden with O_EXCL in MEDIUM debt above).
- ✅ /api/health api_keys leak: fixed.
- ✅ projection.py dead `_DISPATCH`: removed.
- ✅ projection.py bare rollback: nested try/except added.
- ✅ hmac_auth `_get_secret()` per-request: cached at import.
- ✅ cli/sl/main.py `Optional[bool]`: → `bool | None`.
- ✅ dashboard.py hand-rolled `.env` parser: removed.

### Carried from Session 08 (closed in Session 10) — for reference
- ✅ /api/audit/events no auth: now require_role("auditor", "ciso") + public_mode.
- ✅ purge_episodes LIKE substring: → JSONB `->>'subject_id' = %s` + index.
- ✅ purge_chunks 1000-cap: → $skip pagination + fail-closed on cap.
- ✅ audit_chain O(n) per-write re-read: cached + portalocker advisory lock.
- ✅ _find_completed_cascade tail-5000: sidecar index + warn log on disagreement.
- ✅ audit_chain single-process safety: portalocker advisory lock + LRU cache.
- ✅ right_to_forget `_store_funcs` dead code: removed.
- ✅ _completed_cache unbounded: LRU 1000.
- ✅ audit_verify pagination tail-relative: → absolute `from_index`.
- ⏸ test_audit_chain checkpoint-every-500: TODO still open (LOW priority).

### Carried from Session 07 (deferred)
- SSE pool exhaustion · ai-systems.html legacy XSS · 3 SQLAlchemy engines consolidation — Phase 2.
- ISO 42001 / SR 11-7 / FFIEC PDF Packs — Session 11 deliverable.

## Recent commits (last 5)
```
7272d58 Feat: Session 09 — CLI + Python SDK + Postgres event projection (Day 9)
c025324 Feat: Session 08 — Right-to-Forget cascade + Tamper-Evident Audit (Day 8)
77d6d9e Feat: Session 07 — Multi-Agent + Agent Library (Day 7)
5ee9e3a Docs: Session 06 completion — ARCHITECTURE, DECISIONS, HANDOFF updated
6b77497 Feat: Session 06 — Framework Coverage Matrix (Day 6)
```
(Next commit = Session 10 work)

---

## Opening prompt for the new session (paste verbatim)

```
Read docs/HANDOFF.md first, then docs/plans/12-DAY-PRODUCTION-SPRINT.md
Day 11 section.

Status: Sessions 01-10 complete · 224 tests pass · 4 commits ahead of
origin/main · ready for Day 11 (demo orchestration + ISO/SR-11-7/FFIEC
PDF Packs + 20-Q&A prep).

Do NOT spawn agents or write code yet. Do this first:

1. Draft docs/plans/SESSION-11-demo-orchestration.md with the 6-item
   pre-execution review.

2. Surface 4 decisions via AskUserQuestion:
   - Demo Control panel: new static/demo-control.html vs evolve demo.html
   - PDF Pack engines: copy NIST/OWASP/EU AI Act pattern vs factor shared base
   - Demo narration storage: inline data-attributes vs docs/demo-scripts/
   - 20-Q&A prep: docs/DEMO-QA.md vs section in RUNBOOK.md

3. Wait for explicit "Y" / "go" / "approved" before executing.

The parallel-agent + TaskCreate workflow is the default per
feedback_subagents_context_default.md memory entry.
```
