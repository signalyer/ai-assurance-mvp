# SESSION-69 — Wire real Anthropic streaming in assurance dispatcher
# Date: 2026-05-31 (planned)
# Context cost: LARGE (engine streaming + SSE + frontend SSE consumer + eval pass)
#
# Prereq: S68a shipped — `AiSummaryDrawer` is live and handles
# `status === 'simulated' | 'blocked'`. This session adds `'live'` and
# the engine path that produces it. UI changes are minimal because the
# drawer already discriminates on `result.status`.

## Pre-conditions
- [ ] Engine tip ≥ S67 (currently `17683c6`); team-portal SPA
      `index-yKOGPBUx.js` (S68a) live on `portal.aigovern.sandboxhub.co`
- [ ] `ANTHROPIC_API_KEY` set in App Service config (verify via
      `az functionapp config appsettings list` — never echo the value)
- [ ] Baseline: POST `/api/v1/assurance-model/explain-release` returns
      `status="simulated"` end-to-end against the live origin

## Scope

S69 wires real Anthropic streaming into ONE of the 5 endpoints:
`explain-release` (the one S68a already drives from the UI). The other
four (`ask`, `summarize-finding`, `summarize-evidence`, `draft-report`)
get the same treatment in S69b once the pattern is proven and the
prompts are calibrated.

## Engine work

### 1. `domain/assurance_providers.py`
- Add `REAL_LLM_ENABLED` env flag (default `false` — backward compat).
- Add async helper `stream_anthropic_response(provider, use_case, sanitized) -> AsyncIterator[str]`:
  - Uses `anthropic.AsyncAnthropic` (already in requirements)
  - **MUST use streaming context manager** per
    [[anthropic-max-tokens-streaming-threshold]] — `max_tokens > 2000`
    for these use cases (release narrative ~3500, exec report ~4000),
    non-streaming will fail with `APIConnectionError` mid-response
  - Yields text deltas; caller assembles or pipes through SSE
  - Records final `AuditDecision.LIVE` with real `token_estimate` from
    `usage` block + `cost_estimate_usd` from token count × per-model rate
- Add `LIVE` to `AuditDecision` enum (currently has `ALLOWED`, `BLOCKED`,
  `SIMULATED`, `WARNING`)
- Per-use-case prompts colocated in this module (per
  [global CLAUDE.md] prompts-in-one-place rule); cite the existing
  `simulate_response()` text as the "what the answer should look like"
  calibration target

### 2. `api/assurance_model.py`
- New helper `_dispatch_streaming(req) -> EventSourceResponse`:
  - Runs policy gate + sanitization (same as `_dispatch`)
  - If blocked → returns one SSE event with the blocked JSON and closes
    (UI already handles `status="blocked"` via the existing drawer)
  - If allowed AND `REAL_LLM_ENABLED` AND `have_real_credentials()` →
    streams text deltas as `event: delta\ndata: {...}\n\n`, then a final
    `event: done\ndata: {full AskResponseOut with status="live"}\n\n`
  - Else → falls back to current sync `_dispatch` (sim path unchanged)
- Switch `POST /explain-release` to call `_dispatch_streaming`
  (keeps the other four endpoints on sync `_dispatch` for now)
- Response model change: union of `AskResponseOut` (sync) | SSE stream.
  FastAPI handles this via `sse-starlette.EventSourceResponse`
  (already in requirements? — verify; if not, add it)

### 3. Audit log shape
- Add `streaming_complete: bool` field to the audit record (false on
  client disconnect mid-stream so CISO Console can show "partial").
  Backwards-compatible default: `false`.

## Frontend work

### `team-portal/src/shared/components/AiSummaryDrawer.tsx`
- Detect SSE content-type on response; if so, switch to `EventSource`
  consumption mode
- Progressive text rendering: append `delta` events to `result.response`;
  flip from "Drafting summary…" loading state to streaming-cursor
  affordance (subtle pulsing block char at end of text)
- On `event: done`: set the final `AskResponseOut` (drops the cursor,
  surfaces audit_event_id + redactions + status="live" — badge drops)
- On client close (Close button or drawer dismiss): abort the
  `EventSource` so the engine sees disconnect and writes
  `streaming_complete: false`

### `team-portal/src/shared/api/client.ts`
- Add `apiSse(path, body) -> EventSource`-ish wrapper, with
  `credentials: 'include'` and `X-Data-Mode` header per
  [[raw-fetch-drifts-from-shared-client]]. Native `EventSource` doesn't
  support POST bodies — likely need `fetchEventSource` from
  `@microsoft/fetch-event-source` (add to deps).

## Verification

1. `pytest tests/ -k "assurance_model"` — no tests today; ADD ONE in S69:
   `tests/test_api_assurance_model.py::test_explain_release_streams_when_real_llm_enabled`
   (mocks Anthropic client, asserts SSE events shape)
2. Manual smoke against live: `REAL_LLM_ENABLED=true` (per-request
   header for now, gated by demo-ciso role) → click Explain → text
   streams in progressively → completion event drops badge → audit
   entry in CISO Console shows `decision=LIVE` + real token count
3. Failure modes to test explicitly:
   - `ANTHROPIC_API_KEY` unset with flag on → must fall back to sim,
     not 500
   - Client closes mid-stream → audit `streaming_complete: false`
   - Anthropic rate-limit / 529 → graceful drawer error (not a hang)
4. Bundle-hash + string-grep verify on live origin (expect new
   `index-*.js`; "Live response" or absence of "Simulated preview" on
   a real run)

## Deploy

- Engine: commit + `build-zip.py` + OneDeploy. Apply
  [[appservice-deploy-python]] checklist upfront (B1 SKU, top-level
  imports, cold-start cooldown).
- SPA: manual `swa deploy ./dist --env production` per
  [[spa-deploy-is-manual-swa]]
- App settings: `REAL_LLM_ENABLED=true` via
  `az functionapp config appsettings set` (sticky setting; survives
  swap if any).

## Carry-forward NOT addressed by S69

- **S69b — apply the streaming pattern to the other 4 endpoints**
  (`ask`, `summarize-finding`, `summarize-evidence`, `draft-report`)
  AND ship G-5 (Summarize finding) — requires either creating
  `FindingsPage.tsx` in team-portal or surfacing the button on
  existing finding rows in the AI System drawer (the second is
  smaller, decide in S69b)
- **CISO Console parity** — same drawer pattern, mounted in
  `ciso-console/src/app.tsx`; can be done in parallel with S69b
- **STEP 4 spillover** — Mermaid synthesis + per-tool eval rubric
- **Remaining ARM read stubs** — `list_subscriptions`,
  `list_role_assignments`, `get_network_topology`
- **F-021** — framework mapping data for `ai-sys-bae72e75`
- **UI-promise audit re-run** — due ~S74 per
  [[ui-promise-audit-owed]]; S68a + S69 will close G-5/G-6 and
  partially close G-7/G-8/G-9

## Open questions for session start

1. Confirm `REAL_LLM_ENABLED` rollout mode: env flag (all-or-nothing) vs
   per-request header (more flexible but more surface area)
2. Token-cost surfacing: drawer shows `audit_event_id` today; add
   `token_estimate` + `cost_estimate_usd` to the routing dl? (Operators
   probably want to know what a click costs once real LLM is on.)
3. `sse-starlette` vs hand-rolled SSE in FastAPI — verify what's
   already in `requirements.txt` before deciding.
