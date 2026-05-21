# Resume — AI Assurance Platform

**Last session ended:** 2026-05-21 (Day 1 of 12, Session 03 complete)
**Repo state:** clean · in sync with `origin/main` at `a19f0a8`
**GitHub:** https://github.com/signalyer/ai-assurance-mvp (private)

---

## Where I am
Day 1 closed with **4 sessions of work delivered** (planned was 1 session). The full PII/policy/guardrails enforcement stack is built, tested, and live:
- Sessions 01a + 01b: Scrubber + Fernet vault + @scrub_pii decorator (✓ complete)
- Session 02: Policy engine + OPA HTTP client + @policy_gate decorator (✓ complete)
- Session 03: Guardrails (injection detection + topic enforcement + content safety) (✓ complete)

Decorator chain finalized: `@policy_gate → @scrub_pii → @guardrails → @trace_llm_call → @evaluate_response`

Azure infrastructure: PostgreSQL Flexible Server + Azure AI Search provisioned and credentials applied. All 28 acceptance tests from Sessions 01-03 PASS. Ready for **Session 04 (Memory + RAG)**, which per the master sprint plan was supposed to be Day 2.

## Decisions already made (locked in DECISIONS.md — don't re-litigate)
- **Mode B execution** — 12 calendar days × 1 builder (Day 1 actual: 4 sessions completed)
- **Decorator chain order:** `@policy_gate → @scrub_pii → @guardrails → @trace_llm_call → @evaluate_response` (finalized in Session 03)
- **Fail-closed guardrails:** injection/topic/safety violations block immediately (no response)
- **Self-hosted guardrails only:** no SaaS routing of prompts (all in-process)
- **OPA sidecar deferred:** Local Python evaluator fallback active; OPA sidecar to Session 10
- **Four-tier memory:** T1 in-context · T2 episodic JSONL · T3 RAG (Azure AI Search) · T4 procedural
- **Python local evaluator for policies:** OPA HTTP tries first, local fallback always available

## Key files to load (in order)
1. `CLAUDE.md` — HOW to work (auto-loaded by harness)
2. `ARCHITECTURE.md` — current Built/Planned state
3. `docs/SESSION-03-guardrails.md` — final Session 03 summary (after completion)
4. `docs/plans/SESSION-04-memory-rag.md` — Session 04 detailed plan (memory + RAG)
5. `docs/plans/12-DAY-PRODUCTION-SPRINT.md` — master plan (Sessions 04-12 outline)
6. `middleware/injection.py`, `middleware/guardrails.py` — guardrails decorator pattern to follow
7. `domain/agent_memory.py`, `domain/rag_engine.py` — memory pattern (Session 04 spec)

## Outstanding questions (need user input for Session 04)
1. **Memory TTL enforcement:** Tier 2 (episodic) JSONL TTL in Python, or migrate to Postgres now with database-level TTL?
2. **RAG search:** Semantic-only in Session 04, or implement hybrid (BM25 + semantic) in parallel?
3. **Pace:** Continue autopilot (3+ sessions/day), or slow to planned 1 session/day for testing/review?

## Next concrete action
**Session 04 — Memory + RAG (per ARCHITECTURE.md "Planned"):**
- Build `domain/agent_memory.py` — `build_context()`, `write_episode()`, `compress_episode()`, `selective_recall()`
- Build `domain/rag_engine.py` — Azure AI Search wrapper with index-time scrubbing
- Build `api/memory.py` — Memory API endpoints
- Build `static/memory.html` — Memory viewer UI
- Modify `api/demo_run.py` to log episodes after LLM success
- Acceptance: 12 tests (imports, write/recall, index-time PII rejection, API, stats)

## Working rules in effect
- Repo: `signalyer/ai-assurance-mvp` · default branch `main`
- Azure subscription: `SignalLayerDev` · resource group `rg-aigovern-dev` · region `eastus` (Postgres in westus2)
- Production URL: `aigovern.sandboxhub.co`
- Pre-register Azure providers + set `$env:MSYS_NO_PATHCONV = "1"` at session start
- Slash commands: `/arch` `/plan` `/verify` `/handoff` `/diagram`
- Code standards: full files only · type hints · Pydantic v2 `ConfigDict` · `from __future__ import annotations` · JSONL via `storage._append_jsonl()` only
- Hard security rules: scrubber BEFORE tracer (✓ enforced) · Langfuse scrubbed-only (✓ enforced) · guardrails fail-closed (✓ enforced) · no SaaS guardrails (✓ enforced)
- End-of-session: `/verify` · update ARCHITECTURE.md · append DECISIONS.md · write next SESSION plan · output handoff

## Recent commits (last 10)
```
a19f0a8 Feat: Session 03 — Guardrails (NeMo + Llama Guard 3)
a35a07d Feat: Session 02 — Policy Engine (OPA + 5 categories + trust scorer)
8a10027 Feat: Session 01b — @scrub_pii decorator + demo_run.py scrubber integration
1b39439 Docs: Session 01 final summary — infrastructure provisioning status
3637371 Docs: add provisioning script + tonight async work summary
2be4e1c Fix: tracer.py — enforce scrubbed prompts, fail-closed on missing vault_id
2ee7257 Feat: Session 01a — scrubber.py + de-ID vault with Fernet encryption and TTL
```

## Opening message for next session

```
Read docs/HANDOFF.md first.

Then /arch to confirm current state. Sessions 01a + 01b + 02 + 03 are complete.
All 28 acceptance tests pass. Decorator chain is live:
@policy_gate -> @scrub_pii -> @guardrails -> @trace_llm_call -> @evaluate_response

Three questions before you write code:
1. Session 04 memory TTL: enforce in Python, or migrate to Postgres now?
2. RAG search strategy: semantic-only, or hybrid search (BM25 + semantic)?
3. Pace: continue autopilot (3+ sessions/day), or slow to 1 session/day?

After I answer:
- Use /plan for Session 04 (Memory + RAG)
- Confirm the memory tier architecture (T1 in-context, T2 episodic JSONL, T3 RAG, T4 procedural)
- List files you will CREATE vs MODIFY
- Apply 12-test acceptance pattern from Session 03

Wait for my approval before executing.
```
