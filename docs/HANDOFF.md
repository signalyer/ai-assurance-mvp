# Resume — AI Assurance Platform

**Last session ended:** 2026-05-22 (Day 9 of 12 — Sessions 01-09 complete · 9 commits ahead of origin after this commit lands)
**Repo state:** ready to commit · `main` (next commit = Session 09)
**GitHub:** https://github.com/signalyer/ai-assurance-mvp (private)

---

## Where I am
Day 9 of the 12-day production sprint complete:
- 01a/01b: Scrubber + Fernet vault + `@scrub_pii` ✓
- 02: Policy engine + OPA + `@policy_gate` ✓
- 03: Guardrails (injection + topic + safety) + `@guardrails` ✓
- 04: Memory (Postgres TTL) + RAG (Azure AI Search hybrid) ✓
- 05: Provider abstraction (5 Protocols + BaseSettings + 7 backends) ✓
- 06: Framework Coverage Matrix (6 systems × 8 frameworks) + YAML catalogs + 3 PDF Packs ✓
- 07: Multi-Agent + Agent Library (6 seeded agents, 6 new test systems, Postgres pubsub) ✓
- 08: Right-to-Forget cascade + Tamper-Evident Audit log ✓
- 09: **CLI (`sl`) + Python SDK (`signallayer`) + Postgres event projection (hybrid schema + LISTEN/NOTIFY via read-side tailer)** ✓

Decorator chain (unchanged): `@policy_gate → @scrub_pii → @guardrails → @trace_llm_call → @evaluate_response`
Tests: 179 total — 170 prior regression + 9 new Session 09 integration. All pass.

## Decisions locked (DECISIONS.md — don't re-litigate)
Sessions 01-08 decisions unchanged. New Session 09 decisions:
- **SDK distribution:** Internal Azure Artifacts feed; `publish.ps1` builds wheel but publish step gated off (DRY RUN) until Day 10 provisions feed + PAT
- **CLI auth model:** HMAC-SHA-256 only (no Entra). Canonical signing input: `f"{unix_ts}\n{METHOD}\n{path}\n{sha256_hex(body)}"`. Byte-identical across SDK / CLI / middleware — any change requires updating all three.
- **Postgres projection strategy:** LISTEN/NOTIFY via read-side tailer (NOT inline NOTIFY in `_append_jsonl`). Preserves Session 08 invariant that JSONL append is PG-free.
- **Materialized view schema:** Hybrid — typed hot columns + JSONB rest + GIN index per JSONB. Locked hot-column list in DECISIONS.md.

## Critical findings FIXED in Session 09 (post-review)
- ✅ SDK ↔ middleware signing scheme mismatch (CRITICAL) — SDK client was using colon-delimited + ISO-8601; aligned to newline-delimited + Unix integer (matches CLI + middleware)
- ✅ `domain/projection_worker.py` NOTIFY used f-string SQL with manual quote-escaping → migrated to parameterized `SELECT pg_notify(%s, %s)`
- ✅ Nonce cache unbounded — added `NONCE_CACHE_MAX=50_000` hard-cap clear on overflow
- ✅ `/api/projection/replay` and `/api/projection/views/{view}` leaked exception messages → switched to generic `"internal_error"` detail (exc still logged with `exc_info=True`)

## Working rules in effect (memory)
- `feedback_subagents_context_default.md` — 3+ file sessions default to parallel sub-agents in single Agent-block message + parallel code-reviewer/security-reviewer after, TaskCreate tracking
- `feedback_batch_llm_calls.md` — never sequential LLM calls when asyncio.gather possible
- `feedback_appservice_deploy_python.md` — 10 failure modes to apply upfront on Python App Service deploys

## Key files to load for next session
1. `CLAUDE.md` — auto-loaded
2. `ARCHITECTURE.md` — current Built state through Session 09
3. `DECISIONS.md` — all locked decisions including 4 new Session 09 entries
4. `docs/plans/12-DAY-PRODUCTION-SPRINT.md` — Day 10 spec (production hardening + load tests + deploy)
5. `docs/plans/SESSION-09-cli-sdk-projection.md` — completed Session 09 plan (reference)
6. `middleware/hmac_auth.py`, `sdk/signallayer/client.py`, `cli/sl/auth.py` — three files that MUST stay byte-identical on the signing canonical string

## Outstanding questions for next session (Day 10)
1. **Multi-worker production deploy strategy:** single uvicorn worker (preserves in-memory nonce cache replay protection) vs gunicorn multi-worker + Redis-backed nonce cache?
2. **SDK publish feed:** provision Azure Artifacts feed now, or defer to a public PyPI release post-demo?
3. **Load test target service:** App Service B1 (current) or scale to S1 for the 100 req/s × 10 min run?
4. **App Insights workspace:** new workspace vs reuse `log-aigovern-dev`?

## Next concrete action
Read `CLAUDE.md`, `ARCHITECTURE.md`, `DECISIONS.md`, then `docs/plans/12-DAY-PRODUCTION-SPRINT.md` Day 10 section. Draft `docs/plans/SESSION-10-hardening-deploy.md` with the 6-item pre-execution review. Ask the 4 locked-decision questions above. Wait for explicit "Y" / "go" / "approved" before spawning agents.

## Open items (debt) — Day 10 priorities

### NEW from Session 09
- **SECURITY DEBT (HIGH — Day 10):** Multi-worker deploys require shared nonce cache (Redis). Current per-process `dict` loses replay protection across workers. Single-worker uvicorn is safe for v1 demo; production must migrate before scale-out.
- **SECURITY DEBT (MEDIUM — Day 10):** `cli/sl/config.py` `save_credentials` has TOCTOU: file written before chmod 0600. Fix: open with `os.open(O_CREAT|O_WRONLY|O_TRUNC, mode=0o600)`.
- **SECURITY DEBT (MEDIUM — Day 10):** `dashboard.py` `/api/health` discloses configured-API-key flags (`{"api_keys": {...true/false}}`) to unauthenticated callers. Strip to `{"status": "ready"|"incomplete"}` only.
- **CODE DEBT (MEDIUM — Day 10):** `domain/projection.py` has dead `_DISPATCH` dict alongside the actual if/elif dispatcher in `_dispatch()`. Either remove or replace with lookup; the divergence is a maintenance trap.
- **CODE DEBT (MEDIUM — Day 10):** `domain/projection.py:330` bare `except Exception` swallows secondary rollback failure. Wrap rollback in its own try/except so original exception is preserved.
- **CODE DEBT (LOW — Day 10):** `middleware/hmac_auth.py` `_get_secret()` reads `os.environ` per-request; should be read once at module load per CLAUDE.md.
- **CODE DEBT (LOW — Day 10):** `cli/sl/main.py` uses `Optional[bool]` with `# noqa: UP007`; switch to `bool | None` (Python 3.12+).
- **CODE DEBT (LOW — Day 10):** `dashboard.py` lines 13-23 hand-roll an `.env` parser before `load_dotenv(override=True)`; the hand-roll is dead code.

### Carried from Session 08
- **SECURITY DEBT (HIGH — Day 10):** `api/audit_verify.py` GET /api/audit/events returns full event payloads with no authentication. Add auth + public-mode projection that strips PII-bearing fields.
- **SECURITY DEBT (HIGH — Day 10):** `domain/agent_memory.py` Postgres `purge_episodes` uses `metadata::text LIKE '%<subject_id>%'` — false-positive purge risk if subject_ids are short. Migrate to indexed column or JSONB extraction operator.
- **SECURITY DEBT (HIGH — Day 10):** `domain/rag_engine.py` `purge_chunks` caps at Azure Search 1000-doc top-limit. Add `$skip` pagination loop.
- **CODE DEBT (HIGH — Day 10):** `domain/audit_chain.py` `append_chained_event` re-reads entire events.jsonl on every write (O(n) per write under global lock). Cache prev_hash + chained_count in module-level state.
- **CODE DEBT (MEDIUM — Day 10):** `domain/right_to_forget.py` `_find_completed_cascade` only scans last 5000 events — older cascades missed. Sidecar index file needed.
- **CODE DEBT (MEDIUM — Day 10):** `api/audit_verify.py` pagination tail-relative; switch to absolute `from_index`.
- **CODE DEBT (MEDIUM — Day 10):** `domain/audit_chain.py` documents single-process safety only. Multi-instance App Service would corrupt the chain. Advisory file lock or single-writer queue.
- **CODE DEBT (LOW — Day 10):** `domain/right_to_forget.py` `_store_funcs` callable check is dead code.
- **CODE DEBT (LOW — Day 10):** `_completed_cache` in right_to_forget.py unbounded.
- **TEST DEBT (LOW — Day 10):** `tests/test_audit_chain.py` checkpoint-every-500 test deferred with TODO.

### Carried from Session 07
- SSE pool exhaustion · ai-systems.html legacy XSS · RBAC on mutating endpoints · 3 SQLAlchemy engines consolidation — all Day 10 hardening.
- ISO 42001 / SR 11-7 / FFIEC PDF Packs — endpoints return 501; deferred to Session 11.

## Recent commits (last 5)
```
c025324 Feat: Session 08 — Right-to-Forget cascade + Tamper-Evident Audit (Day 8)
77d6d9e Feat: Session 07 — Multi-Agent + Agent Library (Day 7)
5ee9e3a Docs: Session 06 completion — ARCHITECTURE, DECISIONS, HANDOFF updated
6b77497 Feat: Session 06 — Framework Coverage Matrix (Day 6)
48b77c8 Feat: Session 05 — Provider abstraction + legacy guardrails delete
```
(Next commit = Session 09 work)

---

## Opening prompt for the new session (paste verbatim)

```
Read docs/HANDOFF.md first, then docs/plans/12-DAY-PRODUCTION-SPRINT.md
Day 10 section.

Status: Sessions 01-09 complete · 179 tests pass · 9 commits ahead of
origin/main · ready for Day 10 (production hardening + load tests + deploy).

Do NOT spawn agents or write code yet. Do this first:

1. Draft docs/plans/SESSION-10-hardening-deploy.md with the 6-item
   pre-execution review:
   - Decorator chain order (unchanged)
   - Every CREATE file with one-line purpose
   - Every MODIFY file with exact change
   - Two most critical architectural constraints
   - Explicit "Will NOT build" list
   - Acceptance criteria with runnable assertions

2. Surface 4 decisions via AskUserQuestion:
   - Multi-worker deploy: single uvicorn vs gunicorn + Redis nonce cache
   - SDK feed: provision Azure Artifacts now vs defer to public PyPI
   - Load test target: B1 vs scale to S1
   - App Insights workspace: new vs reuse log-aigovern-dev

3. Wait for explicit "Y" / "go" / "approved" before executing.

On approval: spawn 3 sub-agents in ONE message (TaskCreate up front).
Then run all new + 179 regression tests. Spawn code-reviewer + security-
reviewer in parallel. Update docs trio. Commit.

The parallel-agent + TaskCreate workflow is the default per
feedback_subagents_context_default.md memory entry.
```
