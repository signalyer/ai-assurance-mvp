# SESSION-70b — Wire Evals UI to real data + agent memory write

> **Replaces S70 plan-A scope** (LLM-action surface rollout) for this session.
> Plan-A carried forward as S71-candidate. Decision logged in session-open
> AskUserQuestion: user picked plan-B (E2E demo unblock).

## Goal
Make the end-to-end story real for a single agent run:

  agent.py --review → policy_gate → scrub_pii → guardrails →
  Anthropic call → trace_call → evaluate_response → **write_episode** →
  Langfuse trace visible → episodes row visible →
  data/evals.jsonl row visible → **team-portal Evals page surfaces it**.

Today: every step works EXCEPT the last two. `write_episode` is implemented
but no agent calls it. `data/evals.jsonl` is written by `evaluate_response`
but the team-portal Evals page reads `/grc/evals/v2/overview` (seed/overlay
data), so a real run leaves no visible trace in the UI.

## Workflow type
**Refactoring** — touches 4-6 files, all bounded edits to existing surfaces.
No new modules. Token band Normal <500K.

## Non-goals (out of scope, do NOT drift)
- Per-metric SSE streaming on the Evals page (decided: one-shot, all 5 metrics)
- Retrofitting `write_episode` to other agents (decided: azure-architect only)
- Touching the decorator chain order or adding a new decorator
- New endpoints — reuse `/api/evaluate` and add at most one read endpoint
- ciso-console SPA changes (S71+)
- Dropping the Anthropic-pin on `FailedGateRow` (that's S71b per S69 lesson)

## Decisions locked at session open
1. **Evals UX:** one-shot, all 5 metrics. DeepEval scores in parallel locally
   — SSE per-metric would be artificial theater.
2. **Memory scope:** azure-architect only. Other agents follow when S71's
   `sl agent init` scaffolder lands.
3. **Decorator chain unchanged.** `write_episode` is a POST-call inline
   (same pattern as `trace_call`, `evaluate_response`).

## Pre-flight context (from S69 close)
- Engine tip `e532ff7` on `origin/main`
- Team-portal SPA `index-CaTHiUwg.js` (S69 streaming drawer)
- Decorator chain order: `@policy_gate` → `@scrub_pii` → `@guardrails` →
  `@trace_llm_call` → `@evaluate_response`
- Files in progress: none (ARCHITECTURE.md line 76)
- Live: `REAL_LLM_ENABLED=true` on `app-aigovern-dev`
- Anthropic-pin on `FailedGateRow.onExplain` is intentional; preserve it

## Load-bearing rules in effect
- `[[requirements-deploy-drift]]` — grep `requirements-deploy.txt` before any
  new top-level import in engine code
- `[[appservice-deploy-python]]` — apply all 10 modes on engine deploy
- `[[raw-fetch-drifts-from-shared-client]]` — `apiGet`/`apiPost` only
- `[[spa-deploy-is-manual-swa]]` — team-portal SPA must be deployed via
  `swa deploy ./dist --env production`; CI does not handle SPAs
- `[[two-origins-spa-vs-engine]]` — verify SPA bundle-hash + string-grep
- `[[bash-cwd-persistence]]` — multi-target deploy: absolute paths or re-cd
- `[[deploy-zip-overwrites-runtime-data]]` — build-zip INCLUDE is code-only
- `[[anthropic-max-tokens-streaming-threshold]]` — not triggered (we're not
  adding new LLM calls in this session)
- `[[bare-except-hides-broken-integrations]]` — if `write_episode` swallows,
  log and surface; success flag must reflect Postgres outcome, not just
  "the function returned without raising"

## Implementation steps

### STEP 1 — Add `write_episode()` to azure-architect post-call tail
**File:** `agents/azure-architect/agent.py`

Insert after the eval block (~line 250), before `return {...}`. Use the
already-computed `vault_id`, `trace_id`, `prompt` (scrubbed), `response_text`,
`eval_result`. Outcome derived from eval pass-rate:
  - all metrics passed → "success"
  - any blocking metric failed → "failure"
  - mixed → "review"

Wrap in try/except per `[[bare-except-hides-broken-integrations]]`:
- success flag (`episode_id` non-empty) returned in the result dict
- failure logs with module+exc name+message; does NOT block the agent
- include `agent="azure-architect"`, `model`, `latency_ms`, `eval_summary`
  in `metadata` so the row is self-describing in a future episode browser

Extend the `call_llm` return dict with `episode_id: str` (empty on failure).
Extend `_print_review` to show `episode_id` in the bottom-line footer.

**Verify:** `python -c "import agents.azure-architect.agent"` must pass.

### STEP 2 — Smoke the agent + memory write live
1. Confirm `DATABASE_URL` is set in `agents/azure-architect/.env`
2. Run: `PYTHONPATH=. python agents/azure-architect/agent.py --review "Deploy a public AKS cluster with no NSG, RBAC disabled, allowing kubectl from 0.0.0.0/0" --fast`
3. Confirm stdout contains: trace_id, eval scores, **episode_id** (non-empty)
4. Confirm Postgres `episodes` table has the new row (psql or
   `GET /api/memory/episodes?workload_id=azure-architect&limit=5`)
5. Confirm `data/evals.jsonl` has a new row matching the trace_id
6. Confirm Langfuse trace visible

**Stop condition:** if any of the 4 confirmations fails, fix before STEP 3.

### STEP 3 — Add read endpoint for real evals (or repurpose existing)
**File:** `api/evaluate.py` (or `api/grc.py` — check which is cleaner)

Add `GET /api/evals/recent?workload_id=&limit=20` that reads `data/evals.jsonl`
via `storage._read_jsonl` and returns the most recent rows. Strict Pydantic
v2 response model. NO mock-data fallback (the whole point is real data).

Pick one of:
- (a) Extend `/api/evaluate` with a list endpoint (simpler, fewer routers)
- (b) Add to `/api/grc/evals/v2/recent` alongside the existing overview
  (keeps the SPA's existing prefix)

**Decide (a) vs (b) when STEP 3 starts** — pick whichever requires fewer
imports and zero new auth wiring.

### STEP 4 — Wire team-portal Evals page to the new endpoint
**Files:**
- `team-portal/src/pages/evals/EvalsPage.tsx`
- `team-portal/src/pages/evals/types.ts` (if exists; else add a `RealEvalRow`)
- `team-portal/src/pages/evals/SystemEvalCard.tsx` (if the per-system layout
  needs adapting; preferred: keep the existing seed overview AND add a
  "Recent live runs" panel above it so we don't break the demo if real data
  is empty)

Add a **"Recent live runs"** section above the KPI row. Render one row per
recent eval: `model`, `trace_id` (link to traces.html or trace drawer),
`latency_ms`, per-metric scores chip row, timestamp. Empty state: "No live
runs yet — run an agent via SDK to populate this."

Loading guard: `loading && !hasData` per `[[never-blank-on-refresh]]`.
Fetch via `apiGet` only — NO raw fetch.

### STEP 5 — Smoke the SPA path
1. `cd team-portal && npm run build`
2. `swa deploy ./dist --env production` (per `[[spa-deploy-is-manual-swa]]`)
3. Capture new bundle hash; verify with curl + string-grep that the live
   bundle contains the new "Recent live runs" string
4. Hit `https://portal.aigovern.sandboxhub.co/evals` in browser; confirm
   the panel shows the row from STEP 2

### STEP 6 — Engine deploy (if any engine code changed in STEP 3)
1. `python build-zip.py` (INCLUDE code-only per
   `[[deploy-zip-overwrites-runtime-data]]`)
2. Apply all 10 deploy-Python modes per `[[appservice-deploy-python]]`
3. Smoke `/api/evals/recent` returns the STEP 2 row

### STEP 7 — Tests
Add at least:
- `tests/test_agent_memory_integration.py` — agent.py's write_episode call
  is invoked when the LLM path succeeds (monkeypatch Anthropic + the
  decorator-wrapped path; assert write_episode invoked with the scrubbed
  prompt + vault_id)
- Extend `tests/test_api_evaluate.py` (or add `tests/test_api_evals_recent.py`)
  for the new GET endpoint — read fixture jsonl, assert shape

Pytest: `python -m pytest -s -p no:deepeval tests/...`

### STEP 8 — Close-out per project CLAUDE.md "End of every session"
1. `/verify` — show all output
2. Update `ARCHITECTURE.md` — add S70b block under "Files — Built" with
   commit tip, SPA bundle hash, engine version
3. Write next session plan (S71 — `sl agent init` scaffolder OR S70a if user
   wants the LLM-action surface rollout next)
4. List deviations + open issues
5. Commit in two commits per repo convention: `Feat: S70b — ...` for the
   functional change, `Docs: S70b close-out — ...` for ARCHITECTURE updates

## Risks + mitigations
- **R1: DATABASE_URL not set in agent .env.** Mitigation: STEP 1 logs +
  agent reports `episode_id=""` clearly; STEP 2 confirmation #4 catches.
- **R2: Postgres schema drift (S04 inline DDL).** Mitigation: agent_memory
  bootstraps schema on engine creation; agent runs against same DATABASE_URL
  so the table exists. Verify with `\d episodes` in psql if STEP 2 #4 fails.
- **R3: SPA build picks up stale env.** Mitigation: bundle-hash verify per
  `[[two-origins-spa-vs-engine]]`.
- **R4: `_read_jsonl` is sync; called from async endpoint.** Use
  `asyncio.to_thread` per the rest of the codebase pattern.
- **R5: Eval data could include PII passthrough.** All evals.jsonl rows go
  through `evaluate_response` which already runs against scrubbed text;
  vault_ids are NOT in evals.jsonl. Safe to surface in UI as-is.

## Done when
- Real run produces visible row in Postgres, evals.jsonl, AND Evals page
- All 4 STEP 2 confirmations + STEP 5 #4 pass
- New tests green
- ARCHITECTURE.md updated
- Next-session plan written

## Carry-over backlog (next sessions)
- S70a / S71: LLM-action surface rollout (ask, summarize-finding,
  summarize-evidence, draft-report — all 4 buttons) + port AiSummaryDrawer
  to ciso-console SPA
- S71b: drop Anthropic-pin on FailedGateRow once Bedrock streaming adapter
  ships
- S72: `sl agent init` CLI scaffolder + second example agent
- Triage `AGENTS.md` and `team-portal/cookies.txt` untracked files
