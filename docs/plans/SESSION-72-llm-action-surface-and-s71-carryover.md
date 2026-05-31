# SESSION-72 — LLM action surface rollout (S71 Block B) + S71 carryover

## Status entering S72
S71 Block A shipped on `main`:
- `dacac41` Feat: S71 Block A — SDK write_episode() over signed HTTP
- `2224949` Fix: S71 — re-export Err/Ok/Result at signallayer top level
- `c00120e` Fix: S71 — test fixture must not mutate hmac_auth._SECRET

Engine deployed to `app-aigovern-dev` (BUILD_SHA `dacac41…`). Customer
agent → SDK → signed HTTP → engine → Postgres path proven end-to-end
(episode `40218060-6e0d-44de-865d-ed858f2b77c1` written on the smoke run).

Block B (LLM action surface rollout) was deferred — explicit decision per
S71 plan "doing both together risks Refactoring band overrun."

## Primary block — LLM action surface rollout (S71 Block B)
**Workflow type:** Architecture (token band Normal <750K)

### Goal
Port S69's real-Anthropic streaming pattern to the remaining 3 LLM
affordances on `api/assurance_model.py`:
- `ask` (general Q&A)
- `summarize-finding` (CISO Console findings drawer)
- `summarize-evidence` (Evidence panel in AiSystemDrawer)
- `draft-report` (RELEASE_DECISION_NARRATIVE was S69; this is the
  generic report draft surface)

All four become live-streaming when `REAL_LLM_ENABLED=true`, with
simulation fallback when blocked, and BLOCKED audit on Anthropic
exception (same shape S69 established for `/explain-release`).

### Steps
1. **Engine — _dispatch_streaming on 4 routes.**
   - `api/assurance_model.py`: switch each of `ask`, `summarize-finding`,
     `summarize-evidence`, `draft-report` to `_dispatch_streaming` per
     S69 pattern.
   - Drop the `response_model` on each (OpenAPI cannot represent SSE).
   - Mirror S69's CancelledError → BLOCKED audit with
     `streaming_complete=False`.
2. **Prompt builders.**
   - `domain/assurance_providers.py::_build_prompt()`: add 4 use cases.
   - `_MAX_TOKENS_BY_USE_CASE` entries (likely 2000–3500 each; any
     >2000 MUST use the streaming context manager per
     `[[anthropic-max-tokens-streaming-threshold]]`).
3. **team-portal SPA — 4 buttons + wire-up.**
   - `team-portal/src/shared/components/AiSummaryDrawer.tsx` is already
     SSE-aware (S69). Just need new entry points.
   - `team-portal/src/pages/ai-systems/AiSystemDrawer.tsx`: add
     "Summarize evidence" action on the Evidence section.
   - "Ask" surface: probably a new menu button on `AiSystemDrawer`
     header. Consider an "AI Actions" menu component if the drawer
     header gets crowded.
   - All buttons route through `openAiSummary` with the use-case key.
4. **ciso-console SPA — mount the shared drawer.**
   - `ciso-console/src/app.tsx`: mount `<AiSummaryDrawer />` at shell.
   - Wire `summarize-finding` into the Findings table row actions.
   - SPA build + manual `swa deploy` per
     `[[spa-deploy-is-manual-swa]]`. **Both** SPAs (team-portal +
     ciso-console) need separate `npm run build && swa deploy`.
5. **Anthropic-pin sweep.**
   - S69 left `preferred_provider:'anthropic-prod'` pinned on
     `FailedGateRow.onExplain`. Same pin needed on any new live path
     until Bedrock streaming adapter ships (S71b/S73).
6. **Tests + deploy + verify.**
   - Extend `tests/test_api_assurance_model.py` per S69 pattern: one
     sim-when-flag-off, one live-stream-with-mocked-Anthropic, one
     sim-fallback-no-creds — for each of the 4 new use cases.
   - Engine deploy + per-button smoke on both SPAs (live string
     markers grep-verified per S70b protocol).

### Risks
- AiSystemDrawer already dense — UX may need an "AI Actions" menu
  component. Don't over-engineer; a simple dropdown is fine for S72.
- ciso-console SPA not touched since S66. Build chain may have
  drifted; verify `npm run build` clean before any code edits.
- 4 new prompts × calibration cost. Per CLAUDE.md "Prompt calibration
  — plan for it": each prompt needs at least one worked-example
  validation run before declaring done.
- Hidden cost: 4 streaming routes × ~2000 max_tokens each. Per-button
  smoke is ~$0.20–0.40 on Sonnet. Budget for it.

### Done when
- All 4 LLM affordances stream live on team-portal.
- `summarize-finding` works on ciso-console (port other 3 to ciso-console
  in S73 if scope-tight).
- Per-button smoke confirms each landed without disconnect.
- ARCHITECTURE.md S72 block written.

## Secondary block — S71 carryover (small, bundle as time permits)
- **Rotate dev Postgres admin password.** Surfaced in S70b chat
  transcript via `az` lookup. Already in App Service settings + repo
  committers' shells. Rotate via:
  `az postgres flexible-server update --resource-group rg-aigovern-dev \
   --name psql-aigovern-dev --admin-password <new>`
  then `az webapp config appsettings set` to roll the connection
  string. Verify with one `--review` smoke.
- **Triage `AGENTS.md` + `team-portal/cookies.txt`.** Untracked since
  S69. Decide: commit, .gitignore, or rm. `cookies.txt` is almost
  certainly local-only test debris.
- **agent_memory integration test (S70b STEP 7 deferral).** Needs
  decorator-chain-aware mocking. Could mock `domain.agent_memory.
  _write_episode_impl` and assert the @policy_gate → @scrub_pii →
  @guardrails → @trace → @evaluate chain ran in order before
  `write_episode` saw the scrubbed payload.

## Working rules in effect
- All ARCHITECTURE / S71 / S71b memory pointers from the S71 handoff.
- New: `[[sdk-tests-use-public-import-path]]` — any SDK / library
  refactor must include at least one test that imports the way real
  consumers do.
- `/verify` cross-file pytest caught the S71 fixture pollution.
  Continue running it in close-out, not just the single touched suite.

## Risks to manage
- Block B is wider than Block A (engine + 2 SPAs + manual swa deploys).
  Watch the band — refactoring of AiSystemDrawer + ciso-console app
  shell could easily push to Refactoring Review Required (500K-1M).
- The Anthropic-pin is the right S72 default. Dropping it is S71b/S73
  work tied to Bedrock streaming adapter — do not bundle here.
