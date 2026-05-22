# Resume — AI Assurance Platform

**Last session ended:** 2026-05-21 (Day 8 of 12 — Sessions 01-08 complete · 8 commits ahead of origin after this commit lands)
**Repo state:** ready to commit · `main` (next commit = Session 08)
**GitHub:** https://github.com/signalyer/ai-assurance-mvp (private)

---

## Where I am
Day 8 of the 12-day production sprint complete:
- 01a/01b: Scrubber + Fernet vault + `@scrub_pii` ✓
- 02: Policy engine + OPA + `@policy_gate` ✓
- 03: Guardrails (injection + topic + safety) + `@guardrails` ✓
- 04: Memory (Postgres TTL) + RAG (Azure AI Search hybrid) ✓
- 05: Provider abstraction (5 Protocols + BaseSettings + 7 backends) ✓
- 06: Framework Coverage Matrix (6 systems × 8 frameworks) + YAML catalogs + 3 PDF Packs ✓
- 07: Multi-Agent + Agent Library (6 seeded agents, 6 new test systems, Postgres pubsub) ✓
- 08: **Right-to-Forget cascade + Tamper-Evident Audit log** (vault/T2/T3/Langfuse purge with genuine erasure via file compaction; SHA-256 hash chain over events.jsonl with rolling-window verify) ✓

Decorator chain (unchanged): `@policy_gate → @scrub_pii → @guardrails → @trace_llm_call → @evaluate_response`
Tests: 99 total — 82 Session 01-07 regression + 17 new Session 08 (8 audit_chain + 6 right_to_forget + 3 integration). All pass.

## Decisions locked (DECISIONS.md — don't re-litigate)
Sessions 01-07 decisions unchanged. New Session 08 decisions:
- **Cascade orchestration:** Sync inline (saga reconsidered + dropped; revisit Day 10 if load tests demand)
- **Hash chain algorithm:** SHA-256 plain over `prev_hash ‖ canonical_json(event)` — no secret required to verify; genesis = `"GENESIS"`
- **Verification scope:** Rolling window + checkpoint (default window=1000, checkpoints every 500 events to `data/audit_checkpoints.jsonl`, full=True supported)
- **Cascade idempotency:** cascade_id reverse lookup; re-submission returns `ALREADY_COMPLETED`
- **Langfuse delete:** flag-gated behind `LANGFUSE_DELETE_ENABLED` env var (default false); real API path wired but not reached without flag
- **PII erasure model:** File compaction (atomic rewrite), not append-only tombstones — required for genuine GDPR erasure of Fernet-encrypted ciphertext

## Working rules in effect (memory)
- `feedback_subagents_context_default.md` — 3+ file sessions default to parallel sub-agents in single Agent-block message + parallel code-reviewer/security-reviewer after, TaskCreate tracking
- `feedback_batch_llm_calls.md` — never sequential LLM calls when asyncio.gather possible
- `feedback_appservice_deploy_python.md` — 10 failure modes to apply upfront on Python App Service deploys

## Key files to load for next session
1. `CLAUDE.md` — auto-loaded
2. `ARCHITECTURE.md` — current Built state through Session 08
3. `DECISIONS.md` — all locked decisions including 6 new Session 08 entries
4. `docs/plans/12-DAY-PRODUCTION-SPRINT.md` — Day 9 spec (CLI + SDK + Postgres event projection)
5. `docs/plans/SESSION-08-right-to-forget.md` — completed Session 08 plan (reference)
6. `domain/right_to_forget.py`, `domain/audit_chain.py` — RTF cascade + hash chain (extend pattern for Day 9 projection worker)

## Outstanding questions for next session (Day 9)
1. **SDK distribution:** pip from PyPI vs internal index vs `pip install -e ./sdk` only?
2. **CLI auth model:** HMAC-SHA-256 (per Section 2.7 of sprint plan) vs Entra ID device-code vs both with toggle?
3. **Postgres projection:** trigger-based (LISTEN/NOTIFY → worker) vs polling worker (cron-style) vs change-data-capture?
4. **Materialized view schema:** column-per-event-type vs JSON column + GIN index?

## Next concrete action
Read `CLAUDE.md`, `ARCHITECTURE.md`, `DECISIONS.md`, then `docs/plans/12-DAY-PRODUCTION-SPRINT.md` Day 9 section. Draft `docs/plans/SESSION-09-cli-sdk-projection.md` with the 6-item pre-execution review. Ask the 4 locked-decision questions above. Wait for explicit "Y" / "go" / "approved" before spawning agents.

## Open items deferred from Session 08 (NEW debt)
- **SECURITY DEBT (HIGH — Day 9/10):** `api/audit_verify.py` GET /api/audit/events returns full event payloads (including `subject_id`, `reason`, scrubbed-prompt fragments) with no authentication. Add auth middleware + a public-mode projection that strips PII-bearing fields. Privileged role required for full payload.
- **SECURITY DEBT (HIGH — Day 10):** `domain/agent_memory.py` Postgres `purge_episodes` still uses `metadata::text LIKE '%<subject_id>%'` substring match — false-positive purge risk if subject_ids are short. Migrate `subject_id` to indexed column or JSONB extraction operator (`metadata->>'subject_id' = :subject_id`). JSONL fallback path was fixed (compaction), Postgres path was not.
- **SECURITY DEBT (HIGH — Day 10):** `domain/rag_engine.py` `purge_chunks` caps at Azure Search 1000-doc top-limit per call. Subjects with >1000 chunks are silently under-purged. Add `$skip` pagination loop.
- **CODE DEBT (HIGH — Day 10):** `domain/audit_chain.py` `append_chained_event` re-reads the entire events.jsonl on every write to seed prev_hash. O(n) per write under the global lock. Cache prev_hash + chained_count in module-level state, update atomically inside the lock.
- **CODE DEBT (MEDIUM — Day 10):** `domain/right_to_forget.py` `_find_completed_cascade` only scans last 5000 events; older completed cascades are missed → silent double-purge. Index completed cascades in sidecar file during cascade emission.
- **CODE DEBT (MEDIUM — Day 10):** `api/audit_verify.py` pagination semantics are tail-relative — older events unreachable beyond `limit+offset` window. Switch to absolute `from_index` or full-file read.
- **CODE DEBT (MEDIUM — Day 10):** `domain/audit_chain.py` documents single-process safety only. Multi-instance App Service would corrupt the chain. Add advisory file lock or queue writes to a single writer.
- **CODE DEBT (LOW — Day 10):** `domain/right_to_forget.py` `_store_funcs` callable check is dead code (always true); remove and type-annotate as `list[tuple[str, Callable[[str], dict]]]`.
- **CODE DEBT (LOW — Day 10):** `_completed_cache` in `right_to_forget.py` is unbounded — move to persistent store when saga lands.
- **TEST DEBT (LOW — Day 10):** `tests/test_audit_chain.py` checkpoint-every-500 test deferred with TODO. Promote to a real test (writing 500 events is sub-second).
- (carried from Session 07) SSE pool exhaustion · ai-systems.html legacy XSS · RBAC on mutating endpoints · 3 SQLAlchemy engines consolidation — all Day 10 hardening.
- (carried from Session 07) ISO 42001 / SR 11-7 / FFIEC PDF Packs — endpoints return 501; deferred to Session 11.

## Critical findings FIXED in Session 08 (post-review)
- ✅ Vault `purge_subject_tokens` now compacts file atomically (drops ciphertext lines, not tombstones-only) — genuine GDPR erasure
- ✅ Episodes JSONL fallback purge now compacts atomically
- ✅ `cascade_id` API path parameters are UUID-validated (FastAPI Pydantic UUID type → 422 on invalid)
- ✅ `subject_id` body field has max_length=256 + charset allowlist `[A-Za-z0-9._@-]+`
- ✅ Langfuse `httpx.Client` delete loop moved inside `with` block (was use-after-close)
- ✅ `cascade()` no longer mutates `os.environ["LANGFUSE_DELETE_ENABLED"]` (race-safe local flag)
- ✅ Vault `sha256_digest_after` computed over sorted purged vault_id list + ts (not always sha256(""))

## Recent commits (last 5)
```
77d6d9e Feat: Session 07 — Multi-Agent + Agent Library (Day 7)
5ee9e3a Docs: Session 06 completion — ARCHITECTURE, DECISIONS, HANDOFF updated
6b77497 Feat: Session 06 — Framework Coverage Matrix (Day 6)
48b77c8 Feat: Session 05 — Provider abstraction + legacy guardrails delete
14afa3c Feat: Session 04 — Memory (Postgres TTL) + RAG (Azure AI Search hybrid)
```
(Next commit = Session 08 work)

---

## Opening prompt for the new session (paste verbatim)

```
Read docs/HANDOFF.md first, then docs/plans/12-DAY-PRODUCTION-SPRINT.md
Day 9 section.

Status: Sessions 01-08 complete · 99 acceptance/regression tests pass ·
8 commits ahead of origin/main · ready for Day 9 (CLI + SDK + Postgres
event projection).

Do NOT spawn agents or write code yet. Do this first:

1. Draft docs/plans/SESSION-09-cli-sdk-projection.md with the 6-item
   pre-execution review:
   - Decorator chain order (unchanged)
   - Every CREATE file with one-line purpose
   - Every MODIFY file with exact change
   - Two most critical architectural constraints
   - Explicit "Will NOT build" list
   - Acceptance criteria with runnable assertions

2. Surface 4 decisions via AskUserQuestion:
   - SDK distribution: pip from PyPI vs internal index vs editable-only
   - CLI auth: HMAC-SHA-256 vs Entra device-code vs both
   - Postgres projection: LISTEN/NOTIFY worker vs polling vs CDC
   - Materialized view schema: column-per-event-type vs JSON+GIN

3. Wait for explicit "Y" / "go" / "approved" before executing.

On approval: spawn 3 sub-agents in ONE message (TaskCreate up front).
Then run all new + 99 regression tests. Spawn code-reviewer + security-
reviewer in parallel. Update docs trio. Commit.

The parallel-agent + TaskCreate workflow is the default per
feedback_subagents_context_default.md memory entry.
```
