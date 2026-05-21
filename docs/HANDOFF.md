# Resume — AI Assurance Platform

**Last session ended:** 2026-05-21
**Repo state:** clean · in sync with `origin/main` at `e7f101f`
**GitHub:** https://github.com/signalyer/ai-assurance-mvp (private)

---

## Where I am
The architecture and 12-day production sprint plan are locked, committed, and pushed. Repo is bootstrapped with the structured Chat → Code workflow (CLAUDE.md ≤150 lines, ARCHITECTURE.md, DECISIONS.md, .claude/commands/, .claude/skills/diagram.md, docs/plans/). The existing platform at `aigovern.sandboxhub.co` is live with 12+ pages and 5-role auth, but `tracer.py` leaks raw prompts to Langfuse — **this is the Day 1 Hour 1 critical fix and gates everything else**. No new code written yet this sprint; only planning and scaffolding. The user said "go" then asked for a fresh session to execute.

## Decisions already made (locked in DECISIONS.md — don't re-litigate)
- **Compose, don't rebuild commodities** — wrap Langfuse + DeepEval + Presidio
- **3-decorator chain enforced order:** `@scrub_pii` → `@trace_llm_call` → `@evaluate_response`
- **OPA as policy engine** with 5 categories (org-mandatory · posture · risk-tier · team · system-override)
- **Four-tier memory** — T1 in-context · T2 episodic JSONL · T3 Azure AI Search · T4 procedural
- **JSONL events as source of truth** + Postgres materialized views (Day 9)
- **Single tenant v1** with `org_id` plumbed for v2 multi-tenant
- **Single app v1** with role-based views — headless engine + thin clients is v2 north star
- **6 frameworks:** NIST AI RMF · OWASP LLM Top 10 · EU AI Act Annex IV · ISO 42001 · SR 11-7 · FFIEC + US-FinServ overlay
- **DeepEval 6-metric:** hallucination · relevancy · faithfulness · toxicity · PII leakage · scrub score
- **Eval pack tiers A/B/C** (org-mandatory · risk-tier-mandatory · team-discretionary)
- **Keep AWS Analyzer demo content** — no re-theme

## Key files to load (in order)
1. `CLAUDE.md` — HOW to work (≤150 lines · auto-loaded by harness)
2. `ARCHITECTURE.md` — current state · decorator order · build/in-progress/planned
3. `DECISIONS.md` — 10 locked architectural decisions
4. `docs/plans/12-DAY-PRODUCTION-SPRINT.md` — master plan (624 lines · 14 sections)
5. `docs/plans/SESSION-01a-scrubber-vault.md` — first session plan (PII pipeline)
6. `docs/architecture/target-architecture.html` — visual reference (open in browser)
7. `tracer.py` — the leak that must be fixed Day 1 Hour 1

## Outstanding questions (need user input before Day 1)
1. **Execution mode:** A (4 calendar days × 3 parallel Claude Code accounts · ~12 person-days) or B (12 calendar days × 1 builder)?
2. **Start time:** patch `tracer.py` tonight or wait until tomorrow AM?
3. **Provision Postgres + Azure AI Search tonight (async) or Day 1 AM?**
4. **Stakeholder dry-run target:** Day 12 EOD or Day 13 AM?

## Next concrete action
**First action in new session:**
1. Run `/arch` to confirm current state
2. Read `docs/plans/SESSION-01a-scrubber-vault.md`
3. Answer the 4 outstanding questions above
4. **Patch `tracer.py` raw-prompt leak (Day 1 Hour 1)** — this is the critical fix that gates everything

## Working rules in effect
- Repo: `signalyer/ai-assurance-mvp` · default branch `main`
- Azure subscription: `SignalLayerDev` · resource group `rg-aigovern-dev` · region `eastus`
- Production URL: `aigovern.sandboxhub.co`
- Pre-register Azure providers + set `$env:MSYS_NO_PATHCONV = "1"` at session start
- Slash commands: `/arch` `/plan` `/verify` `/handoff` `/diagram`
- Code standards: full files only · type hints · Pydantic v2 `ConfigDict` · `from __future__ import annotations` · JSONL via `storage._append_jsonl()` only
- Hard security rules: `scrubber.tokenise_payload()` BEFORE `tracer.trace_call()` always · Langfuse gets scrubbed only · OPA fail-closed · no SaaS guardrails · no secrets in code
- End-of-session: `/verify` · update ARCHITECTURE.md · append DECISIONS.md · write next SESSION plan · output opening message for next session

## Recent commits (last 6)
```
e7f101f Docs: add diagram generation guide
0ef921d Plan: 12-day production sprint — consolidated single source
f1cee9a Docs: add deployment-shape section to architecture HTML
fd18c22 Docs: full architecture + tech stack as reviewable HTML
e5fc78d Fix: track .claude/commands/ and .claude/skills/
cca0466 Bootstrap: structured Chat → Code workflow
```

## Opening message for next session
Paste this verbatim into the new Claude Code session:

```
Read docs/HANDOFF.md first.

Then /arch and read docs/plans/SESSION-01a-scrubber-vault.md in full.

I need to answer these before you write any code:
1. Execution mode (A: 4 calendar days × 3 parallel accounts · B: 12 calendar days × 1 builder)
2. Patch tracer.py leak tonight or tomorrow AM
3. Provision Postgres + Azure AI Search tonight async or Day 1 AM
4. Stakeholder dry-run Day 12 EOD or Day 13 AM

After I answer, use /plan to show your implementation approach for Day 1
(scrubber.py + domain/deid_vault.py + @scrub_pii decorator + tracer.py patch).
Confirm:
- The decorator chain order
- Files you create vs modify
- The two critical constraints from the plan file
- What you will NOT build in this session

Wait for my approval before executing.
```
