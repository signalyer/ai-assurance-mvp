# Resume — AI Assurance Platform

**Last session ended:** 2026-05-21 (Day 6 of 12 — Sessions 01-06 complete · 6 commits ahead of origin)
**Repo state:** clean working tree · `main` at commit `6b77497`
**GitHub:** https://github.com/signalyer/ai-assurance-mvp (private)

---

## Where I am
Day 6 of the 12-day production sprint complete:
- 01a/01b: Scrubber + Fernet vault + `@scrub_pii` ✓
- 02: Policy engine + OPA + `@policy_gate` ✓
- 03: Guardrails (injection + topic + safety) + `@guardrails` ✓
- 04: Memory (Postgres TTL) + RAG (Azure AI Search hybrid) ✓
- 05: Provider abstraction (5 Protocols + BaseSettings + 7 backends) + legacy_guardrails deleted ✓
- 06: **Framework Coverage Matrix** (6 systems × 8 frameworks) + YAML catalogs + 3 PDF Packs ✓

Decorator chain: `@policy_gate → @scrub_pii → @guardrails → @trace_llm_call → @evaluate_response`
Tests: 14 new (Session 06) + 52 regression (Sessions 01-05) all pass.

## Decisions locked (DECISIONS.md — don't re-litigate)
- Decorator chain order · fail-closed everywhere · self-hosted guardrails only
- Tier 2 = Postgres TTL · Tier 3 = Azure AI Search hybrid
- API → sync domain calls via `asyncio.to_thread`
- Backend interfaces = `typing.Protocol`; backend config = Pydantic v2 `BaseSettings`
- `legacy_guardrails.py` deleted
- Framework defs hybrid: YAML for new (EU AI Act / ISO 42001 / SR 11-7 / FFIEC / US-FinServ overlay), Python for existing (NIST RMF / NIST 600-1 / OWASP LLM / OWASP Agentic)
- Framework matrix surfaces 8 user-facing slugs (NIST and OWASP each split into 2 catalogs)
- PDF Packs stdlib-only via `_PdfWriter` — no reportlab/weasyprint
- 40 controls backfilled with framework_mappings across all 8 user-facing frameworks

## Working rules in effect (memory)
- `feedback_subagents_context_default.md` — 3+ file sessions default to parallel sub-agents in single Agent-block message + parallel code-reviewer/security-reviewer after, TaskCreate tracking
- `feedback_batch_llm_calls.md` — never sequential LLM calls when asyncio.gather possible
- `feedback_appservice_deploy_python.md` — 10 failure modes to apply upfront on Python App Service deploys

## Key files to load
1. `CLAUDE.md` — auto-loaded
2. `ARCHITECTURE.md` — current Built state through Session 06
3. `DECISIONS.md` — all locked decisions
4. `docs/plans/12-DAY-PRODUCTION-SPRINT.md` — Day 7 spec
5. `docs/plans/SESSION-07-multi-agent.md` — Session 07 plan (to be drafted at start of new session)
6. `domain/models.py` — existing AISystem schema; need to add Agent + AgentBinding entities

## Outstanding question for new session
Just one: **draft SESSION-07 plan and present 6-item pre-execution review.** Day 7 = Multi-Agent + Agent Library. Decisions to lock before approval:
1. Agent storage — extend repository.py JSONL pattern, or new dedicated module?
2. Version pinning — semver in YAML manifests, or DB-tracked versions?
3. Notification mechanism for "subscribers receive within 30s" — polling endpoint, SSE stream, or Postgres LISTEN/NOTIFY?
4. Migration of existing `ai-sys-001` → System with 1 bound agent — automatic on first load, or one-time script?

## Next concrete action
Read `CLAUDE.md`, `ARCHITECTURE.md`, `DECISIONS.md`, then `docs/plans/12-DAY-PRODUCTION-SPRINT.md` Day 7 section. Draft `docs/plans/SESSION-07-multi-agent.md` with 6-item pre-execution review. Ask the 4 locked-decision questions above. Wait for explicit "Y" / "go" / "approved" before spawning agents.

## Open items deferred from Session 06
- Finding #3 (evidence summary scrubbing) — partial; needs decision on scrub point (repository write vs API render). Currently un-scrubbed in PDF and drill-down responses. Track as security debt.
- ISO 42001 / SR 11-7 / FFIEC PDF Packs — endpoints return 501; deferred to Session 11.

## Recent commits (last 5)
```
6b77497 Feat: Session 06 — Framework Coverage Matrix (Day 6)
48b77c8 Feat: Session 05 — Provider abstraction + legacy guardrails delete
14afa3c Feat: Session 04 — Memory (Postgres TTL) + RAG (Azure AI Search hybrid)
287d627 Docs: pre-stage Session 04 — 8 tasks queued, handoff updated
af22647 Docs: Session 03 completion — DECISIONS.md, SESSION-04 plan, HANDOFF
```

---

## Opening prompt for the new session (paste verbatim)

```
Read docs/HANDOFF.md first, then docs/plans/12-DAY-PRODUCTION-SPRINT.md
Day 7 section.

Status: Sessions 01-06 complete · 14 + 52 acceptance tests pass · 6 commits
ahead of origin/main · ready for Day 7 (Multi-Agent + Agent Library).

Do NOT spawn agents or write code yet. Do this first:

1. Draft docs/plans/SESSION-07-multi-agent.md with the 6-item pre-execution
   review:
   - Decorator chain order (unchanged)
   - Every CREATE file with one-line purpose
   - Every MODIFY file with exact change
   - Two most critical architectural constraints
   - Explicit "Will NOT build" list
   - Acceptance criteria with runnable assertions

2. Surface 4 decisions via AskUserQuestion:
   - Agent storage: extend repository.py JSONL vs new module
   - Version pinning: semver YAML manifests vs DB-tracked
   - Subscriber notification: polling vs SSE vs Postgres LISTEN/NOTIFY
   - ai-sys-001 migration: automatic vs one-time script

3. Wait for explicit "Y" / "go" / "approved" before executing.

On approval: spawn 3 sub-agents in ONE message (TaskCreate up front).
Then run all new + 66 regression tests. Spawn code-reviewer + security-
reviewer in parallel. Update docs trio. Commit.

The parallel-agent + TaskCreate workflow is the default per
feedback_subagents_context_default.md memory entry.
```
