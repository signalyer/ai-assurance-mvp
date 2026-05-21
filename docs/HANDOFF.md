# Resume — AI Assurance Platform

**Last session ended:** 2026-05-21 (Day 1 of 12)
**Repo state:** clean · in sync with `origin/main` at `a35a07d`
**GitHub:** https://github.com/signalyer/ai-assurance-mvp (private)

---

## Where I am
Day 1 closed with **3 sessions worth of work delivered** (planned was 1 session). The full PII/policy enforcement stack is built, tested, and live: scrubber + Fernet vault + @scrub_pii decorator + @policy_gate decorator + 5-category policy engine + trust scorer + 4 Rego policy files. Azure infrastructure (PostgreSQL Flexible Server + Azure AI Search) is provisioned and credentials applied to `app-aigovern-dev`. All 28 acceptance tests PASS. The critical raw-prompt leak to Langfuse is sealed at 5 layers (defense in depth). Ready for **Session 03 (Guardrails — NeMo + Llama Guard 3)**, which per the master sprint plan was supposed to be Day 3.

## Decisions already made (locked in DECISIONS.md — don't re-litigate)
- **Mode B execution** — 12 calendar days × 1 builder (Day 1 actual: 3 sessions completed)
- **Decorator chain order:** `@policy_gate → @scrub_pii → @trace_llm_call → @evaluate_response` (all 4 active)
- **OPA fail-closed:** errors and ambiguity always DENY
- **Tracer security:** `SCRUBBER_ENABLED=true` requires `vault_id` in metadata or trace is blocked
- **Trust scoring:** time-decayed (half-life 7 days), category-weighted penalties
- **Postgres provisioned in westus2** (eastus not available for SignalLayerDev subscription)
- **OPA optional:** local Python evaluator is fallback when OPA sidecar unavailable

## Key files to load (in order)
1. `CLAUDE.md` — HOW to work (auto-loaded by harness)
2. `ARCHITECTURE.md` — current Built/InProgress/Planned state
3. `docs/SESSION-01-COMPLETE.md` — Session 01 full summary (defense in depth at 5 layers)
4. `docs/plans/SESSION-02-policy-engine.md` — Session 02 detailed plan + acceptance
5. `docs/plans/12-DAY-PRODUCTION-SPRINT.md` — master plan (Sessions 03-12 outline)
6. `middleware/scrubber.py`, `middleware/policy.py` — decorator pattern to follow for Session 03
7. `domain/policy_engine.py`, `domain/trust_scorer.py` — policy engine reference

## Outstanding questions (need user input)
1. **Session 03 scope:** Build full NeMo Guardrails + Llama Guard 3 integration, or start with regex-only guardrails extension and stub the heavy adapters?
2. **OPA sidecar deployment:** Deploy actual OPA process on App Service now (so OPA HTTP path stops being a fallback)? Or keep Python local evaluator and defer to Session 10 hardening?
3. **Pace:** Continue ahead-of-schedule autopilot (3 sessions/day), or slow to planned 1 session/day for review cycles?

## Next concrete action
**Session 03 — Guardrails (per ARCHITECTURE.md "Planned"):**
- Build `middleware/injection.py` — prompt-injection detection (regex + LLM-based)
- Extend `guardrails.py` — add NeMo + Llama Guard 3 adapters
- Build `guardrails/topic_rail.py` and `guardrails/financial_advisor.co`
- Decorator chain: `@policy_gate → @scrub_pii → @guardrails → @trace_llm_call → @evaluate_response`
  (insert `@guardrails` between scrub and trace)
- Acceptance: prompt injection blocked, off-topic prompts rejected, financial advisor topic rail enforced

## Working rules in effect
- Repo: `signalyer/ai-assurance-mvp` · default branch `main`
- Azure subscription: `SignalLayerDev` · resource group `rg-aigovern-dev` · region `eastus` (Postgres in westus2)
- Production URL: `aigovern.sandboxhub.co`
- Pre-register Azure providers + set `$env:MSYS_NO_PATHCONV = "1"` at session start
- Slash commands: `/arch` `/plan` `/verify` `/handoff` `/diagram`
- Code standards: full files only · type hints · Pydantic v2 `ConfigDict` · `from __future__ import annotations` · JSONL via `storage._append_jsonl()` only
- Hard security rules: scrubber BEFORE tracer (✓ enforced) · Langfuse scrubbed-only (✓ enforced) · OPA fail-closed (✓ enforced) · no SaaS guardrails · no secrets in code
- End-of-session: `/verify` · update ARCHITECTURE.md · append DECISIONS.md · write next SESSION plan · output handoff

## Recent commits (last 6)
```
a35a07d Feat: Session 02 — Policy Engine (OPA + 5 categories + trust scorer)
8a10027 Feat: Session 01b — @scrub_pii decorator + demo_run.py scrubber integration
1b39439 Docs: Session 01 final summary — infrastructure provisioning status
3637371 Docs: add provisioning script + tonight async work summary
2be4e1c Fix: tracer.py — enforce scrubbed prompts, fail-closed on missing vault_id
2ee7257 Feat: Session 01a — scrubber.py + de-ID vault with Fernet encryption and TTL
```

## Opening message for next session
Paste this verbatim into the new Claude Code session:

```
Read docs/HANDOFF.md first.

Then /arch to confirm current state. Sessions 01a + 01b + 02 are complete.
All 28 acceptance tests pass. Decorator chain is live:
@policy_gate -> @scrub_pii -> @trace_llm_call -> @evaluate_response

Three questions before you write code:
1. Session 03 scope: full NeMo + Llama Guard 3 integration, or regex-only with stubs?
2. Deploy OPA sidecar now, or defer to Session 10 hardening?
3. Pace: continue autopilot (3 sessions/day), or planned 1 session/day?

After I answer:
- Use /plan for Session 03 (Guardrails)
- Confirm the new decorator position (@guardrails between @scrub_pii and @trace_llm_call)
- List files you will CREATE vs MODIFY
- Apply 16-test acceptance pattern from Session 02

Wait for my approval before executing.
```
