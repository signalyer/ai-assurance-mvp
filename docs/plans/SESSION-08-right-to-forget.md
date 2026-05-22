# SESSION 08 — Right-to-Forget Cascade + Tamper-Evident Audit Log

**Sprint day:** 8 of 12
**Date drafted:** 2026-05-21
**Predecessors:** Sessions 01a/01b/02/03/04/05/06/07 — all complete
**Status:** PRE-EXECUTION REVIEW — awaiting 4 locked decisions + explicit "go" before sub-agent spawn

---

## 1. Decorator chain (UNCHANGED)

```
@policy_gate → @scrub_pii → @guardrails → @trace_llm_call → @evaluate_response
```

Session 08 does NOT touch the decorator chain. The cascade orchestrator is invoked from an API endpoint and from a CLI hook; it is not itself a decorator. The audit hash chain wraps `domain.repository._append_jsonl` for the `EVENTS_FILE` (`data/events.jsonl`) only.

---

## 2. Files to CREATE (one-line purpose each)

| File | Purpose |
|---|---|
| `domain/right_to_forget.py` | Cascade orchestrator: vault → Tier 2 episodes → Tier 3 (Azure AI Search) → Langfuse; emits `RTF_CASCADE_STARTED/STEP_COMPLETED/STEP_FAILED/CASCADE_COMPLETED/CASCADE_VERIFIED` events with SHA-256 per-store digests; cascade_id idempotency. |
| `domain/audit_chain.py` | Tamper-evident hash-chain helpers: `compute_event_hash(prev_hash, event_json)`, `append_chained_event(event)`, `verify_chain(start, end) -> ChainVerifyResult`. Wraps `repository.append_agent_event` semantics. |
| `api/right_to_forget.py` | FastAPI router — `POST /api/right-to-forget` (request), `POST /api/right-to-forget/{cascade_id}/approve`, `GET /api/right-to-forget/{cascade_id}` (status + verification report), `GET /api/right-to-forget` (list). |
| `api/audit_verify.py` | FastAPI router — `GET /api/audit/verify` (verify chain over rolling window or full), `GET /api/audit/events` (paged, includes hash + prev_hash). |
| `static/right-to-forget.html` | Console UI: request form (subject_id, reason, scope) · approval queue · execution view · verification report with per-store SHA-256 digests. |
| `static/audit-events.html` | Audit-events page: paged event list with hash/prev_hash columns · "Verify chain" button · status banner (CLEAN/BROKEN @ event N). |
| `tests/test_right_to_forget.py` | Unit + integration: cascade across 4 stores · idempotency · partial failure · verification report. |
| `tests/test_audit_chain.py` | Unit: hash determinism · chain verification CLEAN/BROKEN · tampered event detection · genesis event. |
| `tests/test_session08_integration.py` | End-to-end: issue RTF for synthetic subject; assert all 4 stores purged; chain verifies clean after cascade. |
| `docs/plans/SESSION-08-right-to-forget.md` | THIS FILE. |

---

## 3. Files to MODIFY (exact change)

| File | Exact change |
|---|---|
| `domain/repository.py` | Replace body of `append_agent_event` to call `audit_chain.append_chained_event` (adds `event_id`, `prev_hash`, `hash` to record before write). Preserve existing signature + JSONL append semantics. Read path unchanged. Add `read_chain_tail(n)` helper for verifier. |
| `domain/deid_vault.py` | Add `purge_subject_tokens(subject_id: str) -> PurgeResult` returning `{tokens_removed, sha256_digest_after}`. Re-uses `_append_jsonl` tombstone pattern; never edits in place. |
| `domain/agent_memory.py` | Add `purge_episodes(subject_id: str, workload_id: str \| None = None) -> PurgeResult`. Tombstones matching episodes; emits `T2_EPISODE_PURGED` events. |
| `domain/rag_engine.py` | Add `purge_chunks(subject_id: str) -> PurgeResult`. Issues Azure AI Search `delete by source_id == subject_id`; verifies via post-delete count query; emits `T3_CHUNK_PURGED`. |
| `dashboard.py` | Mount `api.right_to_forget.router` and `api.audit_verify.router`; add static routes for `right-to-forget.html` and `audit-events.html`. (Stream A sole writer per CLAUDE.md.) |
| `ARCHITECTURE.md` | Append Day 8 row to Built table; move RTF + audit-chain entries from "In progress" to "Built"; bump verification block to include `python -c "from domain.right_to_forget import cascade; from domain.audit_chain import verify_chain"`. |
| `DECISIONS.md` | Append 4 locked decisions from §6 below. |
| `docs/HANDOFF.md` | Replace Day 7 handoff body with Day 8; preserve template structure. |

No other files touched.

---

## 4. Two most critical architectural constraints

1. **Fail-closed on every cascade step.** If ANY store-purge step fails (vault, T2, T3, Langfuse), the orchestrator MUST: (a) emit `RTF_STEP_FAILED` with the failing store + error, (b) NOT emit `CASCADE_COMPLETED`, (c) return HTTP 207 (multi-status) with per-store result, (d) leave the cascade resumable via the same `cascade_id`. Partial success without a completed verification report is never reported as "done." This honors the global "Policy/security errors → DENY" rule and the sprint plan §1.8 + §6.

2. **Audit chain integrity is append-only and verifiable from genesis.** `events.jsonl` is the SSOT; every new event includes `prev_hash` = hash of the previous event's record (or `"GENESIS"` for the first). The hash function is deterministic over the canonical-JSON serialization of the event record EXCLUDING the `hash` field itself. The cascade emits its own events through the SAME chained writer — so a successful cascade is itself tamper-evident. The fix for the Session 07 MEDIUM debt (AGENT_PUBLISHED outside transaction) lands here: `publish_version` audit write moves inside the publish transaction AND uses `append_chained_event`.

---

## 5. Will NOT build (explicit deferral list)

- ❌ External blockchain anchoring of the chain head (Phase 2 — §8 of sprint plan)
- ❌ Real Langfuse API delete — Session 08 emits the API call with a feature flag; if `LANGFUSE_DELETE_ENABLED=false` (dev default) it logs intent + returns simulated digest. Real call wired but flag-gated. Documented in DECISIONS.md.
- ❌ Cascade across Postgres materialized views — Day 9 builds the projection; Day 8 cascade does not yet need to purge it (replay from purged JSONL will reconstruct correctly).
- ❌ Cross-org subject_id collision handling (multi-tenant) — v1 single-org; subject_id is org-unique by construction.
- ❌ Async/queued execution if §6.1 resolves to "sync within request" — orchestrator stays inline.
- ❌ Role-based authorization on RTF endpoints (Day 10 hardening item; Day 8 ships with same auth as existing mutating endpoints).
- ❌ UI for chain repair / rewrite — chain is append-only by design; a BROKEN result is a P0 incident, not a UI flow.
- ❌ Backfilling hash chain over pre-Session-08 historical events — chain starts at the first event written AFTER `audit_chain` lands. Existing events keep `prev_hash=null` and verifier treats them as pre-genesis (documented).
- ❌ Re-classifying the Session 07 SSE pool-exhaustion HIGH finding (deferred to Day 10 hardening — out of scope for Day 8).

---

## 6. Acceptance criteria (runnable assertions)

All assertions runnable from repo root. Each one becomes a pytest case.

**A. Cascade end-to-end (test_session08_integration.py)**
```python
# Given a subject_id "test-customer-9999" with tokens in vault, episodes in T2,
# chunks in T3, and traces in Langfuse:
result = cascade(subject_id="test-customer-9999", reason="GDPR Art 17 request")
assert result.status == "COMPLETED"
assert result.cascade_id  # uuid
assert result.steps["vault"].tokens_removed >= 1
assert result.steps["tier2"].episodes_removed >= 1
assert result.steps["tier3"].chunks_removed >= 1
assert result.steps["langfuse"].traces_removed >= 0  # flag-gated
assert all(len(s.sha256_digest_after) == 64 for s in result.steps.values())
# Post-cascade: re-running same cascade_id is a no-op
result2 = cascade(subject_id="test-customer-9999", cascade_id=result.cascade_id)
assert result2.status == "ALREADY_COMPLETED"
```

**B. Hash chain CLEAN over last 1000 events (test_audit_chain.py)**
```python
from domain.audit_chain import verify_chain
verdict = verify_chain(window=1000)
assert verdict.status == "CLEAN"
assert verdict.events_checked >= 1  # at least the cascade events written above
assert verdict.broken_at is None
```

**C. Hash chain detects tamper (test_audit_chain.py)**
```python
# Mutate a single byte in the middle of events.jsonl, then verify
_tamper_random_event()
verdict = verify_chain(window=10_000)
assert verdict.status == "BROKEN"
assert verdict.broken_at is not None  # event_id of first mismatch
```

**D. Fail-closed on store error (test_right_to_forget.py)**
```python
# Simulate T3 down via monkeypatch
with mock_rag_failure():
    result = cascade(subject_id="t-1", reason="test")
assert result.status == "PARTIAL_FAILURE"
assert result.steps["tier3"].error
assert "CASCADE_COMPLETED" not in [e["event_type"] for e in _events_for(result.cascade_id)]
assert "RTF_STEP_FAILED" in [e["event_type"] for e in _events_for(result.cascade_id)]
```

**E. Verification report SHA-256 (test_right_to_forget.py)**
```python
report = get_verification_report(cascade_id=result.cascade_id)
for store in ("vault", "tier2", "tier3", "langfuse"):
    assert len(report.digests[store]) == 64
    assert all(c in "0123456789abcdef" for c in report.digests[store])
```

**F. API surface (test_right_to_forget.py — TestClient)**
```python
r = client.post("/api/right-to-forget", json={"subject_id":"t-2","reason":"test"})
assert r.status_code in (201, 207)
cascade_id = r.json()["cascade_id"]
r2 = client.get(f"/api/right-to-forget/{cascade_id}")
assert r2.status_code == 200 and r2.json()["status"] in ("COMPLETED","PARTIAL_FAILURE","IN_PROGRESS")
r3 = client.get("/api/audit/verify?window=1000")
assert r3.status_code == 200 and r3.json()["status"] in ("CLEAN","BROKEN")
```

**G. Regression — Session 01-07 verification (existing)**
- 82 acceptance tests + ~66 regression import smokes still pass
- Decorator chain order unchanged: `python -c "from middleware.chain import enforce_chain; ..."`
- `publish_version` audit event still emitted (now via chained writer) — Session 07 governance tests stay green

**H. Performance**
- Single cascade end-to-end < 60s with ≤100 tokens/episodes/chunks per store
- `verify_chain(window=1000)` < 2s

---

## 7. Locked decisions (filled after AskUserQuestion answered)

| # | Decision | Choice |
|---|---|---|
| 1 | Cascade orchestration | **Sync inline** — runs inside `POST /api/right-to-forget`. Saga reconsidered and dropped; deferred to Day 10 if load tests demand. Endpoint returns 201 on COMPLETED / 207 on PARTIAL_FAILURE. |
| 2 | Hash chain algorithm | **SHA-256 plain** — `hash = sha256(prev_hash ‖ canonical_json(event_without_hash_field))`. No secret required to verify. Genesis event uses `prev_hash="GENESIS"`. |
| 3 | Verification scope | **Rolling window with checkpoint** — default `window=1000`; checkpoints stored every 500 events in `data/audit_checkpoints.jsonl`; `verify_chain(window=N \| full=True)` supported. |
| 4 | Cascade idempotency | **cascade_id with reverse lookup** — uuid generated at request time, persisted in events.jsonl; re-submission with same cascade_id returns prior result with `status="ALREADY_COMPLETED"`. Index built lazily from event scan, cached in memory. |

---

## 8. Sub-agent split (post-approval)

Per `feedback_subagents_context_default.md` — spawn 3 in ONE message after TaskCreate:

- **Agent 1 (orchestrator + chain):** `domain/right_to_forget.py`, `domain/audit_chain.py`, `domain/repository.py` modification, `domain/deid_vault.py` + `domain/agent_memory.py` + `domain/rag_engine.py` purge methods.
- **Agent 2 (API + UI):** `api/right_to_forget.py`, `api/audit_verify.py`, `static/right-to-forget.html`, `static/audit-events.html`, `dashboard.py` mount.
- **Agent 3 (tests + docs):** `tests/test_right_to_forget.py`, `tests/test_audit_chain.py`, `tests/test_session08_integration.py`, ARCHITECTURE.md + DECISIONS.md + HANDOFF.md updates.

Then parallel: `code-reviewer` + `security-reviewer`. Then commit.

---

**End of plan. Awaiting 4 decisions + explicit "Y" / "go" / "approved".**
