# Resume — AI Assurance Platform · S81 (Agent Runner — SPA half)

## Where I am
End of S80. Three commits landed and deployed cleanly:

1. `12a320b` — Chore: untrack 13 runtime `data/*.jsonl` files (gitignore hygiene; no behavior change).
2. `8000abd` — Feat: S79 LOCAL dispatcher + `_run_plan` governance + `write_episode` audit. CD verified live in ~40s.
3. `e56b37d` — Feat: S80 Agent Runner backend. CD verified live (see "Live engine SHA" below). New endpoints:
   - `GET /api/agent-runner/agents` (registry catalog)
   - `POST /api/agent-runner/run` (SSE — 10-event chain protocol)

**The backend is fully built and on prod.** S81 is the SPA half — making the
chain visible in motion on `team-portal /agent-runner`. The full demo arc is
S80–S83 per `docs/plans/SESSION-80-agent-runner.md`; S81 is the page itself,
S82 is dual-path columns + redaction preview, S83 is deep links + rehearsal.

**Live engine SHA at S80 close: `e56b37d`** (verify via
`curl https://aigovern.sandboxhub.co/api/health`).

## Decisions already made — don't re-litigate
- **SSE protocol locked.** 10 event types: `chain.start, policy_gate, scrub_pii, guardrails, llm.delta*, llm.done, evaluate, memory, audit, chain.done` (+ `chain.error`). Full schema in `docs/agent-runner-sse-protocol.md`. Every event carries `event`, `run_id`, `elapsed_ms`. `chain.done` is always terminal.
- **ONE agent, TWO systems** for the dual-path (S82). The picker shows `finadvice` only; columns switch via `system_id` query param.
- **`raw_preview` in `scrub_pii` event is DEMO_MODE-gated.** App Service env will need `DEMO_MODE=true` to surface raw text. Default off.
- **Inline eval** in the chain ticker — not backgrounded.
- **Stateless runs** for now — no `agent_runs` Postgres persistence; replay UI is a separate mountain.
- **Wrapper/inner pattern** is the canonical S80+ shape: `_run_review_inner` undecorated + `run_review = decorators(_inner)`. azure-architect deferred until it actually goes runner-invocable.
- **Auth model:** `GET /agents` + `POST /run` require any role in `(operator, architect, ciso, auditor, admin)`. SPA must include cookies (`credentials: 'include'`) — per `[[two-origins-spa-vs-engine]]`, the SPA at `portal.aigovern.sandboxhub.co` hits the apex `aigovern.sandboxhub.co`.

## S81 concrete deliverables
Per the plan doc (`SESSION-80-agent-runner.md` S81 section):

**Files net-new (team-portal/src/pages/agent-runner/):**
- `AgentRunnerPage.tsx` — top-level page; mounts at `/agent-runner` route.
- `ChainTicker.tsx` — renders the 8 named badges (`policy_gate → … → audit`) as a column. Each badge consumes one chain-event type.
- `ChainStepBadge.tsx` — one badge: icon + name + elapsed_ms + decision/status pill.
- `AgentPicker.tsx` — dropdown populated from `GET /agents`. Disabled rows for `cli_only=true` with a tooltip.
- `types.ts` — TS interface for each of the 10 event types (mirror `docs/agent-runner-sse-protocol.md`).
- `api.ts` — `runAgent({ agentId, systemId, prompt })` returns an `EventSource`; `listAgents()` for the picker.

**Files modified:**
- `team-portal/src/App.tsx` (or router) — register `/agent-runner` route.
- `team-portal/src/shared/Nav.tsx` (or equivalent) — top-nav entry.

**Calibration step (mandatory before S81 close):**
1. Open `team-portal/agent-runner` in a browser. Pick `finadvice`. Type the seed prompt: *"Review the portfolio for client cln-001. Identify the dominant risk and recommend 2-3 specific rebalancing actions."*
2. Click Run. Watch all 8 badges flip in order with plausible `elapsed_ms` (single-digit ms for policy/scrub/guard, ~30s for LLM, ms for the tail).
3. Bundle-hash + `swa deploy ./dist --env production` + live verify per `[[spa-deploy-is-manual-swa]]`.
4. Confirm cookie travels — DevTools Network on the first `POST /run` must show `Cookie:` header. If not, the SPA is dropping credentials (F-019 / `[[raw-fetch-drifts-from-shared-client]]`).

## Outstanding questions (need user input AT S81 START)
1. **Chain ticker layout** — vertical column (mirrors the protocol's temporal order) vs horizontal pipeline (matches the conceptual chain)?
2. **What does the SPA show before the user clicks Run?** Empty chain ticker with grey badges? A "select an agent and Run to begin" placeholder? An example of a prior run?
3. **Should the picker hit `GET /agents` on mount or on dropdown-open?** On-mount = faster perceived load. On-open = less work for users who never use the page. Recommend on-mount — it's one tiny request.
4. **EventSource error handling** — if the SSE stream drops mid-run, do we auto-reconnect, surface a banner, or just freeze the chain ticker with whatever events arrived? Native EventSource auto-reconnects but state would be confused.

## Next concrete action
1. Read `docs/plans/SESSION-80-agent-runner.md` (full arc) and `docs/agent-runner-sse-protocol.md` (the contract).
2. Resolve the 4 questions above with one `AskUserQuestion`.
3. Build bottom-up: `types.ts` first (TS protocol mirror) → `api.ts` (network seams) → `ChainStepBadge` + `ChainTicker` (presentational) → `AgentPicker` (data) → `AgentRunnerPage` (composition). Route + Nav last.
4. Hit the live engine end-to-end before SPA deploy — bundle-hash + string-grep verify against `portal.aigovern.sandboxhub.co` per `[[spa-deploy-is-manual-swa]]`.

## Key files to load
- `docs/plans/SESSION-80-agent-runner.md` — S81 section (line ~152).
- `docs/agent-runner-sse-protocol.md` — protocol contract (load this before writing `types.ts`).
- `team-portal/src/App.tsx` (or `src/main.tsx` / router file) — where the route mounts.
- `team-portal/src/shared/api/client.ts` — established shared API client pattern (use it; don't raw-fetch per `[[raw-fetch-drifts-from-shared-client]]`).
- `api/agent_runner.py` — the backend the SPA consumes.
- `agents/_registry.py::list_registered_agents` — what the picker gets.

## Working rules in effect
All prior rules. Locks especially relevant for S81:
- `[[spa-deploy-is-manual-swa]]` — Free SKU has no GH Actions integration for the SPA. `cd team-portal && npm run build && swa deploy ./dist --env production` after every change. Bundle-hash + string-grep verify.
- `[[two-origins-spa-vs-engine]]` — SPA at `portal.*`, engine at apex. `EventSource` URL is apex. Cookies must travel (credentials include).
- `[[raw-fetch-drifts-from-shared-client]]` — use the shared API client for `GET /agents`; raw `fetch()` will drift the cookie contract.
- `[[dropdown-in-transformed-ancestor-needs-portal]]` — if the agent picker lives inside a drawer/modal/transformed container, portal to body from day one.
- `[[never-blank-on-refresh]]` — chain ticker must distinguish "loading first time" from "no events yet for this run". An empty ticker mid-stream is different from an empty ticker pre-Run.
- `[[ui-promise-audit-owed]]` — every event type in the protocol must have a SPA binding. Grep `team-portal/src` for each event name before declaring S81 done.

## Slipped / deferred (still tracked)
- **S82** — dual-path columns + PII redaction preview component. Needs second `system_id` routed to `local-simulated` (the S79 dispatcher branch is live).
- **S83** — `audit` event Langfuse + AppInsights deep links. Requires `LANGFUSE_PROJECT_URL` + `APPLICATIONINSIGHTS_RESOURCE_ID` App Service settings.
- **S84** — RBAC review of `api/memory.py:188`.
- **S85** — per-turn tool-result re-scrub (closes the operator-prompt-PII demo gap), real per-run eval scoring, eval-failure → finding auto-create glue.
- **OpenAPI drift** flagged at S80 close (`docs/openapi-v1.json` does not match generated spec). Run `python scripts/export_openapi.py` and commit the diff at S81 entry.
