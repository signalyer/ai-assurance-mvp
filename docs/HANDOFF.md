# Resume — AI Assurance Platform

**Last session ended:** 2026-05-21 (Day 1 of 12, Session 03 complete, Session 04 pre-staged)
**Repo state:** clean · in sync with `origin/main` at `af22647`
**GitHub:** https://github.com/signalyer/ai-assurance-mvp (private)

---

## Where I am
Day 1 closed with **4 sessions delivered** + Session 04 **pre-staged** (task list created, plan written, user decisions captured). The full PII/policy/guardrails enforcement stack is built, tested, and live:
- Sessions 01a + 01b: Scrubber + Fernet vault + @scrub_pii decorator (✓ complete)
- Session 02: Policy engine + OPA HTTP client + @policy_gate decorator (✓ complete)
- Session 03: Guardrails (injection + topic + content safety) + @guardrails decorator (✓ complete, 16/16 tests pass)

Decorator chain finalized: `@policy_gate → @scrub_pii → @guardrails → @trace_llm_call → @evaluate_response`

**User decisions for Session 04 (captured 2026-05-21, do NOT re-litigate):**
1. **Postgres for Tier 2 episodic memory** (not JSONL) — database-level TTL enforcement
2. **Hybrid RAG search** (BM25 + semantic vector reranking) — not semantic-only
3. **Continue autopilot pace** (3+ sessions/day)

## Decisions already made (locked in DECISIONS.md — don't re-litigate)
- **Mode B execution** — 12 calendar days × 1 builder (Day 1 actual: 4 sessions completed)
- **Decorator chain order:** `@policy_gate → @scrub_pii → @guardrails → @trace_llm_call → @evaluate_response` (finalized in Session 03)
- **Fail-closed guardrails:** injection/topic/safety violations block immediately
- **Self-hosted guardrails only:** no SaaS routing of prompts
- **OPA sidecar deferred:** Python local evaluator active; OPA to Session 10
- **Four-tier memory:** T1 in-context · T2 episodic (Postgres, per user decision) · T3 RAG (Azure AI Search hybrid) · T4 procedural

## Key files to load (in order)
1. `CLAUDE.md` — HOW to work (auto-loaded by harness)
2. `ARCHITECTURE.md` — current Built/Planned state
3. `docs/plans/SESSION-04-memory-rag.md` — Session 04 detailed plan
4. `DECISIONS.md` — all locked-in architectural decisions
5. `middleware/guardrails.py`, `middleware/injection.py` — Session 03 reference patterns
6. `domain/policy_engine.py`, `domain/trust_scorer.py` — Session 02 patterns (Postgres-ready)

## Session 04 execution plan (PRE-STAGED — 8 tasks already in TaskList)

**Run `TaskList` first to see the staged work.**

### Step 1: Spawn 3 sub-agents IN PARALLEL (single message, 3 Agent tool calls)
- **Agent A (general-purpose):** Research Azure AI Search hybrid search → build `domain/rag_engine.py` with BM25 + semantic vector reranking, index-time PII scrubbing (reject PII > 0.7), `text-embedding-3-small`
- **Agent B (implementer):** Build `domain/agent_memory.py` with Postgres TTL (NOT JSONL). SQLAlchemy ORM + Alembic migration. Schema: episode_id, workload_id, timestamp, prompt (scrubbed), response (scrubbed), outcome, vault_id, expires_at. Functions: `build_context()`, `write_episode()`, `compress_episode()`, `selective_recall()`
- **Agent C (implementer):** Build `api/memory.py` (POST /episodes, GET /episodes, GET /recall, GET /stats) + `static/memory.html` (episode browser, semantic search, context viewer)

### Step 2: Integration (main thread)
- Wire `write_episode()` into `api/demo_run.py` after successful LLM call
- Mount `api/memory.py` router in `dashboard.py`

### Step 3: Acceptance tests (12 tests)
- Module imports x3 · Agent memory x3 · RAG engine x3 · Memory API x3

### Step 4: Spawn 2 review agents IN PARALLEL
- **code-reviewer:** SignalLayer pattern consistency, type hints, error handling
- **security-reviewer:** Postgres connection security, SQL injection in selective_recall, PII in episode storage, Azure Search key handling

### Step 5: Docs + commit
- Update ARCHITECTURE.md, DECISIONS.md, write SESSION-05 plan, update HANDOFF.md
- 2 commits: feature + docs

## Working rules in effect
- Repo: `signalyer/ai-assurance-mvp` · default branch `main`
- Azure subscription: `SignalLayerDev` · resource group `rg-aigovern-dev` · Postgres in westus2
- Production URL: `aigovern.sandboxhub.co`
- Pre-register Azure providers + set `$env:MSYS_NO_PATHCONV = "1"` at session start
- Slash commands: `/arch` `/plan` `/verify` `/handoff` `/diagram`
- Code standards: full files only · type hints · Pydantic v2 `ConfigDict` · `from __future__ import annotations`
- JSONL via `storage._append_jsonl()` only — but Tier 2 episodic now Postgres per user decision
- Hard security rules: scrubber BEFORE tracer (✓ enforced) · Langfuse scrubbed-only (✓ enforced) · guardrails fail-closed (✓ enforced) · no SaaS guardrails (✓ enforced)
- End-of-session: `/verify` · update ARCHITECTURE.md · append DECISIONS.md · write next SESSION plan · output handoff

## Recent commits (last 5)
```
af22647 Docs: Session 03 completion — update DECISIONS.md, SESSION-04 plan, and HANDOFF
a19f0a8 Feat: Session 03 — Guardrails (NeMo + Llama Guard 3)
a35a07d Feat: Session 02 — Policy Engine (OPA + 5 categories + trust scorer)
8a10027 Feat: Session 01b — @scrub_pii decorator + demo_run.py scrubber integration
2ee7257 Feat: Session 01a — scrubber.py + de-ID vault with Fernet encryption and TTL
```

---

## Opening message for next session (paste into fresh Claude Code)

```
Read docs/HANDOFF.md first.

Sessions 01a + 01b + 02 + 03 are complete. 28/28 acceptance tests pass.
Decorator chain finalized:
@policy_gate -> @scrub_pii -> @guardrails -> @trace_llm_call -> @evaluate_response

Session 04 (Memory + RAG) is pre-staged:
- 8 tasks already in TaskList (run TaskList to see them)
- Plan: docs/plans/SESSION-04-memory-rag.md
- User decisions locked: (1) Postgres for Tier 2 episodic, (2) Hybrid RAG search, (3) Autopilot pace

Execute Session 04 as planned:
1. Read SESSION-04-memory-rag.md and DECISIONS.md to confirm scope
2. Spawn 3 sub-agents in parallel (single message, 3 Agent tool calls):
   - Agent A (general-purpose): research Azure AI Search hybrid + build domain/rag_engine.py
   - Agent B (implementer): build domain/agent_memory.py with Postgres TTL + Alembic
   - Agent C (implementer): build api/memory.py + static/memory.html
3. After all 3 return: integrate into api/demo_run.py + dashboard.py
4. Run 12 acceptance tests, mark TaskList progress
5. Spawn code-reviewer + security-reviewer in parallel
6. Update docs, write SESSION-05 plan, commit

Use TaskUpdate to mark each task in_progress/completed as you go.
No re-litigation of decisions — proceed directly to spawning agents.
```
