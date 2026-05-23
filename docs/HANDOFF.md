# Resume — AI Assurance Platform

**Last session ended:** 2026-05-22 (Day 11 of 12 — Sessions 01-11 complete · 5 commits ahead of origin after the Session 11 commit lands)
**Repo state:** Session 11 staged, awaiting commit
**GitHub:** https://github.com/signalyer/ai-assurance-mvp (private)

---

## Where I am
Day 11 of the 12-day production sprint complete:
- 01a/01b — 10 done (see prior HANDOFF history)
- **11: Demo orchestration + ISO/SR-11-7/FFIEC PDF Packs + 20-Q&A + 5 Day-11 debt fixes ✓**

Decorator chain (unchanged): `@policy_gate → @scrub_pii → @guardrails → @trace_llm_call → @evaluate_response`
Tests: **252 total — 224 prior + 28 new Session 11 (4 POSIX-skipped on Windows).** All pass.

## What shipped in Session 11
- **Demo Control Panel** — `api/demo_control.py` (router) + `static/demo-control.html` (UI) + `/demo-control` route. RBAC: `demo-operator` or `ciso`. Six scenarios trigger REAL backends (no mocks): PII pipeline · gate failure · reusable-agent v2 publish · RTF cascade · evals trend · framework export. Bounded `_RUNS` (LRU 200) via `OrderedDict`. Synchronous execution; events go to `events.jsonl` via `storage._append_jsonl`. Counters: `demo_scenario_runs_total{scenario,outcome}` + `demo_scenario_duration_seconds`.
- **PDF Pack base extraction** — `domain/pdf_pack_base.py` carries `_PdfWriter` + shared helpers. `pdf_report.py` re-imports for the 3 existing generators (NIST/OWASP/EU AI Act) plus 3 new ones: `generate_iso_42001_pack`, `generate_sr_11_7_pack`, `generate_ffiec_pack`. Stdlib-only.
- **RTF sidecar HMAC** — `data/rtf_completed_index.jsonl` entries signed with HMAC-SHA256 (`SL_HMAC_SECRET`). Unsigned/invalid entries log + counter `rtf_sidecar_unsigned_total` + fall back to events.jsonl scan. Strict-reject mode is Session 12.
- **Day-11 debt fixes** (5/9 carryover items closed):
  - `cli/sl/config.py` symlink hardening (`lstat` pre-check + `O_EXCL` first-write + `fstat` regular-file invariant on update).
  - `X-Request-Id` regex validator (`^[A-Za-z0-9_-]{1,64}$`) in `observability/middleware.py`; UUID4 fallback on violation.
  - `domain/audit_chain.py` — checkpoint write moved inside the lock; dead `LockException` except branch removed.
  - `api/metrics.py` `METRICS_TOKEN` cached at module load.
  - `middleware/auth.py::ROLES` — `OPERATOR` added.
- **Docs** — `docs/DEMO-QA.md` (20 Q&As, 4 audience groups), `docs/demo-scripts/scenario-1..6.md` (≤300 words each), `docs/RUNBOOK.md` appended with "Demo operations" (pre-demo checklist, mid-demo recovery).
- **Test harness** — `pytest.ini` pins `--basetemp=./_pytest_tmp` (Windows %TEMP% ACL workaround). `_pytest_tmp/` gitignored.

## Decisions locked (DECISIONS.md — don't re-litigate)
Sessions 01-10 decisions unchanged. New Session 11 entries D-11.1 through D-11.5: RTF HMAC migration-mode, PDF pack base extraction with call-stability gate, sync execution with LRU cap, `demo-operator` role, pytest tmp workaround.

## Findings closed by Session 11 review (per code-reviewer + security-reviewer)
- **CRITICAL** — `demo-operator` couldn't log in with `AUTH_ENABLED=true` (missing from ROLES). FIXED.
- **HIGH** — exception `str(exc)` leaked paths/conn-strings into browser. Now returns `type(exc).__name__`; full detail in server log only.
- **HIGH** — PII pipeline scenario could return residual PII. Post-scrub regex tripwire added (`_has_residual_pii`).
- **HIGH** — `_RUNS` unbounded. Now `OrderedDict` with `_MAX_RUNS=200` LRU.
- **MUST CHANGE** — `_append_event` duplicated storage helper. Now imports + calls `storage._append_jsonl`.
- **MUST CHANGE** — RTF scan used `break` on bad sig. Now `continue` — preserves the scan for later well-signed duplicates.
- **MUST CHANGE** — dead imports in `pdf_report.py` (`io`, `struct`, `zlib`, `json`, `hashlib`). Removed.
- **SHOULD CHANGE** — `outcome` could be unbound in `finally`. Initialized to `"failure"` before `try`.
- **SHOULD CHANGE** — symlink check used `path.exists()` (follows links). Now `os.lstat` + explicit symlink rejection.
- **SHOULD CHANGE** — `tuple[object, list]` typing. Now `tuple[Any, list[Any]]` with circular-import note.

## Outstanding Session-12 debt (carried)
- **RTF strict-reject mode** — flip from migration mode to refusing unsigned entries once Prometheus shows `rtf_sidecar_unsigned_total == 0` for a week.
- **`_sidecar_secret()` caching** — currently per-call for test fixtures; cache at module load with restart-required rotation in Session 12.
- **Synchronous demo execution** — move to `BackgroundTasks` if any scenario crosses 5s p95.
- **PDF pack cover-page duplication** — `_render_cover_page` helper extraction across all 6 generators.
- **Cover the `/demo-control` HTML route with role gating in prod** — currently public (matching other HTML routes). Add `require_role` when `AUTH_ENABLED=true`.
- Other Day-11 carryover items not yet closed: SSE pool exhaustion · ai-systems.html legacy XSS · 3 SQLAlchemy engines consolidation (Phase 2).

## Working rules in effect (memory)
- `feedback_subagents_context_default.md` — parallel sub-agents default. **Caveat: this codebase hits sub-agent stream-idle timeouts consistently — 5 of 6 Session 11 agents timed out. Inline implementation is faster for medium-scope work.**
- `feedback_batch_llm_calls.md` — never sequential LLM calls when asyncio.gather possible.
- `feedback_appservice_deploy_python.md` — 10 failure modes on Python App Service deploys.

## Key files to load for next session
1. `CLAUDE.md` (auto)
2. `ARCHITECTURE.md` — needs Session 11 entries added (deferred from this commit)
3. `DECISIONS.md` — D-11.1 through D-11.5 just appended
4. `docs/DEMO-QA.md` + `docs/demo-scripts/` — review the talk tracks before dry-run
5. `docs/RUNBOOK.md` "Demo operations" section — pre-demo checklist
6. `docs/plans/SESSION-11-demo-orchestration.md` — completed plan
7. `docs/architecture/BUILT-STATE.html` — built-state architecture (7 inline-SVG diagrams + file matrix + Phase-2 legend)
8. `docs/architecture/BUILT-STATE.svg` — single master SVG (6-layer map + decorator chain + data plane) for decks

## Next concrete action (Day 12)
1. Deploy to `aigovern.sandboxhub.co` via `deploy/bicep/main.bicep`.
2. Provision `DEMO_USER_OPERATOR_HASH` for the demo-operator login.
3. Set `SL_HMAC_SECRET` (already required by `middleware/hmac_auth.py`; new RTF code re-uses it).
4. Run 6-scenario green check via Demo Control panel.
5. Stakeholder dry-run.
6. Add ARCHITECTURE.md entries for Session 11 components (deferred from this commit to keep diff scoped).

## Recent commits (last 6)
```
<pending>  Feat: Session 11 — Demo Control + ISO/SR-11-7/FFIEC PDF Packs + Day-11 debt (Day 11)
<sess10>   Feat: Session 10 — Production hardening + observability + Bicep + load tests
7272d58    Feat: Session 09 — CLI + Python SDK + Postgres event projection (Day 9)
c025324    Feat: Session 08 — Right-to-Forget cascade + Tamper-Evident Audit (Day 8)
77d6d9e    Feat: Session 07 — Multi-Agent + Agent Library (Day 7)
5ee9e3a    Docs: Session 06 completion — ARCHITECTURE, DECISIONS, HANDOFF updated
```
