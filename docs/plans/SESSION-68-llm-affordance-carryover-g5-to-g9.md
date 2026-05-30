# SESSION-68 — V1→V2 LLM affordance carryover (G-5..G-9)
# Date: 2026-05-31 (planned)
# Context cost: SMALL (S68a ships UI on existing simulated endpoints)
#
# REVISED post-S67 streaming audit. Original plan assumed these endpoints
# made real Anthropic calls; audit proved they're simulation-only. Scope
# split into S68a (UI on simulated) + S69 (wire real LLM in dispatcher).

## What the audit found (S67 end-of-session)

Five `api/assurance_model.py` endpoints exist and are operator-promised
in V1 (`static/findings.html` etc), zero V2 consumers:

| Gap | Verb               | Engine endpoint                          | Body                         |
| --- | ------------------ | ---------------------------------------- | ---------------------------- |
| G-5 | Summarize finding  | `POST /api/assurance-model/summarize-finding` | `AskRequest` (use_case auto-set) |
| G-6 | Explain release    | `POST /api/assurance-model/explain-release`   | `AskRequest`                 |
| G-7 | Summarize evidence | `POST /api/assurance-model/summarize-evidence`| `AskRequest`                 |
| G-8 | Draft report       | `POST /api/assurance-model/draft-report`      | `AskRequest`                 |
| G-9 | Ask (free-form Q&A)| `POST /api/assurance-model/ask`               | `AskRequest`                 |

**All five are SIMULATION-ONLY by design** (api/assurance_model.py:404):
- `response_text = simulate_response(req.use_case, decision.provider, sanitized)` is hardcoded
- Audit logs `AuditDecision.SIMULATED` with comment "real credentials present
  but simulation enforced in this build" even when `ANTHROPIC_API_KEY` is set
- No `FORCE_REAL` / `REAL_LLM` flag exists in `domain/assurance_providers.py`
- Synchronous, fast, deterministic — **streaming is moot**, the
  [[anthropic-max-tokens-streaming-threshold]] rule doesn't apply

This reshapes the work. UI work is safe to ship (no engine bug to fix
first) but shipping a button labeled "Summarize" returning fake text
without operator-visible disclosure is misleading.

## S68a — ship UI with explicit "Simulated preview" labeling

Scope: G-5 (Summarize finding) + G-6 (Explain release). G-7/G-8/G-9
follow the same pattern in S69b once S69 has wired real calls.

### Pre-conditions
- [ ] Engine tip is `800fa48` (S67 close-out) or later
- [ ] Team-portal SPA tip is `index-B65x86z3.js` (S67) or later
- [ ] `pytest tests/ -k "assurance_model"` baseline pass count
- [ ] Manual smoke (already done in S67 audit): POST
      `/api/assurance-model/summarize-finding` with a valid `AskRequest`
      → returns 200 with `status="simulated"` and `response` non-empty

### Files to create
1. `team-portal/src/shared/components/AiSummaryDrawer.tsx`
   - Module-level signal `openSummaryRequest = signal<{url, title, body} | null>(null)`
   - `openAiSummary({ url, title, body })` setter
   - On open: `apiPost<AskResponseOut>(url, body)`, show drawer overlay
   - Render the `response` field as monospace/preformatted text
   - **Mandatory "Simulated preview" badge** at top of drawer when
     `response.status === "simulated"` (will be every response in S68a).
     Use the existing `badge badge-warning` class with text
     "Simulated preview — provider routing + audit are live; LLM text is
     deterministic placeholder until S69 wires the real call."
   - "Copy markdown" + "Close" affordances
   - `apiPost` already handles `credentials: 'include'`
     ([[raw-fetch-drifts-from-shared-client]])
   - Loading state: rotating "Routing to provider…" / "Drafting summary…"
     / "Logging audit event…" — 3s cadence (CLAUDE.md "Loading states")

2. `team-portal/src/shared/types/assurance.ts`
   - `AskRequest` + `AskResponseOut` + `PolicyDecisionOut` types
     mirroring `api/assurance_model.py` Pydantic models. Engine source
     of truth is `api/assurance_model.py::AskResponseOut`.

### Files to modify
1. `team-portal/src/pages/findings/FindingsPage.tsx` (verify exists)
   - Add **Summarize** button per finding row → calls
     `openAiSummary({ url: '/assurance-model/summarize-finding',
       title: 'Summary: ' + f.id, body: { ai_system_id: f.system_id,
       use_case: '', user: currentUser, data_classes: [], payload: { finding_id: f.id } } })`
   - If FindingsPage doesn't exist as a standalone surface, drop G-5
     from S68a and ship G-6 only — don't synthesize a new page in this
     session.

2. `team-portal/src/pages/ai-systems/AiSystemDrawer.tsx`
   - In the Release Gate Status section, add **Explain** button per
     failed gate row → calls
     `openAiSummary({ url: '/assurance-model/explain-release', ... })`

3. `team-portal/src/app.tsx` — mount `<AiSummaryDrawer />` once at shell

### Verification
- `pytest tests/ -k "assurance_model"` — same pass count
- Browser smoke: click Summarize → drawer opens → simulated preview
  badge visible → response text streams in → close → audit trail in
  CISO Console shows the new SIMULATED event
- Bundle-hash + string-grep for "Simulated preview" in the deployed bundle

### Deploy
- Engine: no commit (engine unchanged)
- SPA: `cd team-portal && npm run build && swa deploy ./dist --env production`
  per [[spa-deploy-is-manual-swa]]

## S69 — wire real LLM in `assurance_providers.simulate_response()`'s caller

Out of scope for S68. Separate session. High-level:

1. Add `REAL_LLM_ENABLED` env flag in `domain/assurance_providers.py`;
   default OFF for backward compat.
2. When flag ON + `have_real_credentials(provider)` + use_case allowed,
   route to a real `anthropic.AsyncAnthropic` streaming call.
   `max_tokens` per use_case (likely all > 2K → streaming context
   manager mandatory per [[anthropic-max-tokens-streaming-threshold]]).
3. Replace synchronous `simulate_response()` line with conditional:
   real → stream → assemble text → record `AuditDecision.LIVE` with
   real token/cost metrics.
4. Change `api/assurance_model.py` endpoints to SSE response (when
   real path active). Keep simulated path synchronous.
5. Frontend: switch `AiSummaryDrawer` from `apiPost` to SSE consumer
   when response is streaming. Drop the "Simulated preview" badge
   when `response.status === "live"`.

Scope makes this a full session on its own. S68a's UI work transitions
cleanly because the drawer already handles `response.status` discrimination.

## Open carry-forward NOT addressed by S68a (for S69+)

- **G-7 / G-8 / G-9** — same pattern as G-5/G-6; deferrable
- **CISO Console parity** for G-5..G-9
- **Real LLM wiring (S69)** — the bigger work
- **STEP 4 spillover** — Mermaid synthesis + per-tool eval rubric
- **Remaining ARM read stubs** — list_subscriptions, list_role_assignments,
  get_network_topology
- **F-021** — framework mapping data for `ai-sys-bae72e75`
- **UI-promise audit re-run** — due ~S74 per [[ui-promise-audit-owed]]
