# Resume — AI Assurance Platform

**Last session ended:** 2026-05-21 (Day 1 of 12, Sessions 01-04 complete)
**Repo state:** ready to commit · ahead of `origin/main` by Session 04 work
**GitHub:** https://github.com/signalyer/ai-assurance-mvp (private)

---

## Where I am
Day 1 closed with **5 sessions of work delivered** (planned was 1 session). Full enforcement + memory stack live:
- Sessions 01a + 01b: Scrubber + Fernet vault + @scrub_pii decorator ✓
- Session 02: Policy engine + OPA HTTP client + @policy_gate decorator ✓
- Session 03: Guardrails (injection + topic + content safety) + @guardrails decorator ✓
- Session 04: Memory (Postgres TTL) + RAG (Azure AI Search hybrid) + memory API + UI ✓

Decorator chain (finalized in Session 03): `@policy_gate → @scrub_pii → @guardrails → @trace_llm_call → @evaluate_response`

Memory architecture (Session 04, user-chosen): T1 in-context · **T2 Postgres episodic (database-level TTL)** · **T3 Azure AI Search hybrid (BM25 + semantic)** · T4 procedural (domains.py)

40 acceptance tests total across 4 sessions, all passing.

## What Session 04 added
- `domain/agent_memory.py` — 7 functions: write_episode, build_context, compress_episode, selective_recall, list_episodes, memory_stats, purge_expired
- `domain/rag_engine.py` — 4 functions: index_document (PII rejection > 0.7), search_corpus (hybrid), rag_stats, delete_document
- `api/memory.py` — 5 endpoints: POST /episodes, GET /episodes, GET /recall, GET /stats, GET /context (all use asyncio.to_thread for sync domain calls)
- `static/memory.html` — Memory viewer UI with episode browser, semantic search, context viewer
- Modified: `api/demo_run.py` (calls write_episode after successful LLM call), `dashboard.py` (mounts memory router), `api/security.py`+`api/batch.py` (updated imports)
- Renamed: `guardrails.py` → `legacy_guardrails.py` (resolved module/package collision)

## Session 04 review fixes applied (from code-reviewer + security-reviewer)
- **CRITICAL:** `await` on sync domain functions → fixed with `asyncio.to_thread()` (5 endpoints)
- **CRITICAL:** PII leak in `rag_engine._log_rejection` → no longer logs content preview, only doc_id + score + length
- **CRITICAL:** CSS injection defense in `memory.html` recall results → scorePct clamped to integer 0-100
- **CRITICAL:** `print` in `demo_run.py` → switched to `logger.warning`
- **MEDIUM:** UI key mismatch (`by_workload` → `episodes_by_workload`) → fixed

Deferred to Session 05 follow-up (HIGH severity, not blocking):
- vault_id enforcement at API boundary regardless of SCRUBBER_ENABLED flag
- workload_id allowlist validation (when multi-tenant added)
- Move OpenAI client to module scope in rag_engine.py
- Remove per-request .env re-read in demo_run.py

## Decisions already made (locked in DECISIONS.md — don't re-litigate)
- **Mode B execution** — 12 calendar days × 1 builder (Day 1 actual: 5 sessions completed)
- **Decorator chain order** — finalized in Session 03
- **Fail-closed everywhere** — policy, guardrails, scrubber, memory, RAG
- **Self-hosted guardrails only** — no SaaS routing
- **OPA sidecar deferred to Session 10** — Python local evaluator active
- **Four-tier memory** — T1 in-context · T2 Postgres episodic · T3 Azure AI Search hybrid · T4 procedural
- **Postgres for Tier 2** — database-level TTL, parameterized SQL only
- **Hybrid RAG (BM25 + semantic)** — 0.6 semantic + 0.4 BM25 default
- **asyncio.to_thread** for sync domain calls from async API handlers

## Key files to load (in order)
1. `CLAUDE.md` — HOW to work (auto-loaded by harness)
2. `ARCHITECTURE.md` — current Built/Planned state
3. `docs/plans/SESSION-05-provider-abstraction.md` — Session 05 detailed plan
4. `DECISIONS.md` — all locked-in architectural decisions
5. `domain/agent_memory.py`, `domain/rag_engine.py` — Session 04 reference for provider abstraction targets

## Outstanding questions (need user input for Session 05)
1. **Backend protocol style:** `typing.Protocol` (structural, fast) or Pydantic `BaseModel` (runtime validation)?
2. **Legacy guardrails:** keep `legacy_guardrails.py` as `regex` backend in new provider layer, or delete and rewrite api/security.py adversarial flow?
3. **Pace:** Continue autopilot (5+ sessions/day), or slow down (Day 1 already exceeded 5x plan)?

## Next concrete action
**Session 05 — Provider Abstraction:**
- Build `providers.py` (registry + factory) and `providers/` package (5 backend modules)
- Refactor `scrubber.py`, `tracer.py`, `evaluator.py`, `agent_memory.py`, `rag_engine.py` to proxy through providers
- Backward compat: all 40 existing acceptance tests must still pass
- New acceptance: env-var-driven backend swap works

## Working rules in effect
- Repo: `signalyer/ai-assurance-mvp` · default branch `main`
- Azure subscription: `SignalLayerDev` · resource group `rg-aigovern-dev` · Postgres in westus2
- Production URL: `aigovern.sandboxhub.co`
- Pre-register Azure providers + set `$env:MSYS_NO_PATHCONV = "1"` at session start
- Slash commands: `/arch` `/plan` `/verify` `/handoff` `/diagram`
- Code standards: full files only · type hints · Pydantic v2 `ConfigDict` · `from __future__ import annotations`
- JSONL via `storage._append_jsonl()` only — Tier 2 episodic is now Postgres
- API-from-async: use `asyncio.to_thread()` for sync domain function calls
- Hard security rules: scrubber BEFORE tracer · Langfuse scrubbed-only · guardrails fail-closed · no SaaS guardrails · PII never logged in rejection records
- End-of-session: tests · update ARCHITECTURE.md · append DECISIONS.md · write next SESSION plan · output handoff

## Recent commits (last 6)
```
287d627 Docs: pre-stage Session 04 — 8 tasks queued, handoff updated with parallel agent strategy
af22647 Docs: Session 03 completion — update DECISIONS.md, SESSION-04 plan, and HANDOFF
a19f0a8 Feat: Session 03 — Guardrails (NeMo + Llama Guard 3)
a35a07d Feat: Session 02 — Policy Engine (OPA + 5 categories + trust scorer)
8a10027 Feat: Session 01b — @scrub_pii decorator + demo_run.py scrubber integration
2ee7257 Feat: Session 01a — scrubber.py + de-ID vault with Fernet encryption and TTL
```

## Opening message for next session

```
Read docs/HANDOFF.md first.

Sessions 01-04 are complete. 40 acceptance tests pass.
Decorator chain finalized:
@policy_gate -> @scrub_pii -> @guardrails -> @trace_llm_call -> @evaluate_response

Memory: Postgres TTL · RAG: Azure AI Search hybrid (BM25 + semantic).

Three questions before Session 05 (Provider Abstraction):
1. Backend protocols: typing.Protocol or Pydantic BaseModel?
2. Keep legacy_guardrails.py as 'regex' backend, or delete?
3. Pace: continue autopilot, or slow down?

After I answer:
- Use /plan for Session 05
- Confirm provider factory pattern
- List files you will CREATE vs MODIFY
- Apply 10-test acceptance pattern (5 protocols + 5 backend swaps + regression)

Wait for my approval before executing.
```
