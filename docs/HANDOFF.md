# Resume — AI Assurance Platform

**Last session ended:** 2026-05-21 (Day 1 of 12, Sessions 01-04 complete · Session 05 planned + awaiting approval)
**Repo state:** clean · in sync with `origin/main` at `14afa3c`
**GitHub:** https://github.com/signalyer/ai-assurance-mvp (private)

---

## Where I am
Day 1 delivered **5 sessions of work**. Full enforcement + memory stack live:
- 01a + 01b: Scrubber + Fernet vault + `@scrub_pii` ✓
- 02: Policy engine + OPA HTTP client + `@policy_gate` ✓
- 03: Guardrails (injection + topic + safety) + `@guardrails` ✓
- 04: Memory (Postgres TTL) + RAG (Azure AI Search hybrid) + memory API/UI ✓ — 12 acceptance tests + 3 endpoint smoke + 5 CRITICAL review fixes
- 05: **complete** (provider abstraction + legacy_guardrails delete) ✓ 12 new + 40 regression tests pass

Decorator chain finalized: `@policy_gate → @scrub_pii → @guardrails → @trace_llm_call → @evaluate_response`
40/40 acceptance tests across Sessions 01-04 pass.

## Decisions locked (DECISIONS.md — don't re-litigate)
- Decorator chain order · fail-closed everywhere · self-hosted guardrails only
- Tier 2 = Postgres with database-level TTL · Tier 3 = Azure AI Search hybrid (BM25 + semantic)
- API → sync domain calls via `asyncio.to_thread` (not async-rewrite)
- `guardrails.py` renamed → `legacy_guardrails.py` (Session 03 module/package collision)
- **Session 05 decisions (appended to DECISIONS.md):**
  1. Backend interfaces = `typing.Protocol`; backend config = Pydantic v2 `BaseSettings` ✓
  2. `legacy_guardrails.py` deleted; `api/security.py` + `api/batch.py` migrated to new guardrails package ✓
  3. Autopilot pace continues

## Working rule loaded from memory
`MEMORY.md` now includes `feedback_subagents_context_default.md`: for any 3+ file session, default to parallel sub-agents in a single Agent-block message + parallel code-reviewer/security-reviewer after, with TaskCreate tracking. Don't recommend `/compact` based on guesswork — ask "what's the context bar showing?" before suggesting compaction.

## Key files to load
1. `CLAUDE.md` — auto-loaded
2. `ARCHITECTURE.md` — current Built/Planned state
3. `docs/plans/SESSION-05-provider-abstraction.md` — full Session 05 spec (read this first, it has the 6-item review)
4. `DECISIONS.md` — all locked decisions
5. `domain/agent_memory.py`, `domain/rag_engine.py`, `scrubber.py`, `tracer.py`, `evaluator.py` — Session 05 refactor targets

## Outstanding question for new session
**Just one: does the user say "go" / "Y" / "approved" on the Session 05 plan?** If yes, execute. If they want changes, revise plan first.

## Next concrete action
Read `docs/plans/SESSION-05-provider-abstraction.md`. Re-present the 6-item review (decorator chain unchanged, 11 CREATE / 7 MODIFY / 1 DELETE, 2 critical constraints, NOT-build list, 12 acceptance tests). Wait for explicit "Y" before executing. On approval, spawn 3 sub-agents in parallel (Agent A: build `providers/` package · Agent B: refactor 5 root/domain files to proxy through providers · Agent C: delete `legacy_guardrails.py` + rewrite 2 callers). Then run 12 new + 40 regression tests + spawn code-reviewer/security-reviewer in parallel.

## Recent commits (last 5)
```
14afa3c Feat: Session 04 — Memory (Postgres TTL) + RAG (Azure AI Search hybrid)
287d627 Docs: pre-stage Session 04 — 8 tasks queued, handoff updated
af22647 Docs: Session 03 completion — DECISIONS.md, SESSION-04 plan, HANDOFF
a19f0a8 Feat: Session 03 — Guardrails (NeMo + Llama Guard 3)
a35a07d Feat: Session 02 — Policy Engine (OPA + 5 categories + trust scorer)
```

---

## Opening prompt for the new session (paste verbatim)

```
Read docs/HANDOFF.md first, then docs/plans/SESSION-05-provider-abstraction.md.

Status: Sessions 01-04 complete · 40 acceptance tests pass · Session 05 plan
already written and awaiting my Y/N approval.

User decisions for Session 05 are locked (in HANDOFF + plan):
  1. typing.Protocol for backend interfaces; Pydantic BaseSettings for backend config
  2. DELETE legacy_guardrails.py; rewrite api/security.py + api/batch.py to use
     middleware/injection.py + guardrails/llama_guard_adapter.py
  3. Autopilot pace

Do NOT spawn agents or write code yet. Do this first:

1. Re-present the 6-item pre-execution review from the Session 05 plan:
   - Decorator chain order (unchanged)
   - Every CREATE file (11) with one-line purpose
   - Every MODIFY file (7) with the exact change
   - Two most critical architectural constraints
   - Explicit "Will NOT build" list
   - 12 acceptance criteria with runnable assertions

2. Then wait for my explicit "Y" / "go" / "approved".

On approval, execute per the plan: 3 sub-agents in ONE message (Agent A
builds providers/ package · Agent B refactors 5 proxy targets · Agent C
deletes legacy + rewrites 2 callers). Use TaskCreate up front. Run all
12 new + 40 regression tests. Spawn code-reviewer + security-reviewer
in parallel. Update docs. Commit.

A memory entry (feedback_subagents_context_default.md) is now active —
the parallel-agent + TaskCreate workflow is the default, not optional.
```
