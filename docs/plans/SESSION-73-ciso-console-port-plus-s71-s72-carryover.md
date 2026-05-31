# SESSION-73 — ciso-console action port + S71+S72 carryover + pre-existing failure triage

## Status entering S73
S72 Block B shipped on `main`:
- `c05a566` Feat: S72 Block B — LLM action surface rollout (4 routes streaming)

Engine deployed (commit `c05a566`). Both SPAs deployed via `swa deploy`:
- team-portal `index-D6YPZap2.js` on `portal.aigovern.sandboxhub.co`
- ciso-console `index-BG5ryvcJ.js` on `gov.aigovern.sandboxhub.co`

All 4 LLM actions live on team-portal; only `summarize-finding` on
ciso-console (per S72 trimmed scope). Anthropic-pinned across all 5
streaming buttons until Bedrock streaming adapter ships.

## Primary block — finish the ciso-console LLM action port
**Workflow type:** Refactoring (token band Normal <500K)

### Goal
Port the remaining 3 actions (`ask`, `summarize-evidence`, `draft-report`)
to ciso-console so the two SPAs have feature parity on the LLM action
surface. Engine work is zero — the dispatcher and prompts shipped in S72.

### Steps
1. **Identify the right surfaces.** ciso-console doesn't have an
   AiSystemDrawer equivalent — the closest analogs are:
   - `pages/portfolio/PortfolioPage.tsx` (per-system row → could host Ask)
   - `pages/evidence/EvidencePage.tsx` (Summarize-evidence button)
   - `pages/reports/ReportsPage.tsx` (Draft-report button)
   - Confirm via Glob + Grep that each page exists and is actually wired
     (some were CSM-2/CSM-4 stubs in S64-S66). For stubbed pages, wiring
     a button is wasted work — promote the page to "live" first.
2. **AI Actions menu vs inline buttons.** AiSystemDrawer.tsx in
   team-portal has 7 buttons now (S72 #6 above). For ciso-console, the
   surfaces are different but the menu refactor is overdue. Decision:
   build a small reusable `<AiActionsMenu>` component in the shared
   `components/` dir and use it on the new ciso-console buttons. Port
   team-portal to the menu in the same session if band has headroom —
   otherwise leave team-portal with inline and ship the menu only on
   ciso-console first.
3. **Wire each button per S72 pattern.** Each opens
   `openAiSummary({...})` with use-case-appropriate payload + Anthropic
   pin. Helpers (`openAskAboutSystem`, etc.) copied from
   team-portal/AiSystemDrawer.tsx — the helpers themselves are not
   AiSystem-specific.
4. **Tests + deploy + smoke.** No engine tests needed (dispatcher
   unchanged). SPA build + `swa deploy ./dist --deployment-token --env
   production`. Per-button smoke via the live SPA in browser session
   (need real cookie — S72 found that scripted SSE smoke needs the user
   to be logged in).

### Risks
- Stubbed CSM-4 pages (Reports, Policies) may not have an "AI surface"
  yet. Don't shoehorn buttons into pages that aren't ready.
- `<AiActionsMenu>` is reusable but adds a component to maintain in two
  shared dirs (team-portal/shared and ciso-console/shared). Either
  duplicate verbatim (S72 pattern, ok for now) or extract to a shared
  npm-workspace package (overkill for two SPAs — defer indefinitely).

### Done when
- 3 new buttons wired on ciso-console.
- Per-button smoke confirms each streams end-to-end.
- ARCHITECTURE.md S73 block written.

## Secondary block — Anthropic-pin sweep + Bedrock streaming adapter
**Workflow type:** Architecture (token band Normal <750K)

### Goal
Drop the `preferred_provider: 'anthropic-prod'` pin on all 5 streaming
buttons by building the Bedrock streaming adapter. This is the work the
S69/S72 plans repeatedly mention as "S71b/S73 deferred."

### Steps
1. **Bedrock streaming SDK.** Add `boto3` streaming via
   `bedrock-runtime.converse_stream`. Lazy import (App Service cold
   start; same pattern as `domain/assurance_providers.py::stream_anthropic_response`).
2. **`stream_bedrock_response()`** — new async generator yielding the
   same `("delta", text) | ("done", usage)` tuple shape as the
   Anthropic helper. Same `_MAX_TOKENS_BY_USE_CASE` table; same
   `_build_prompt()` branches; same SSE wire shape from the caller's
   perspective.
3. **Dispatcher selection.** In `_stream_live_release_narrative` (still
   misnamed — rename in this session since we're touching it):
   `if decision.provider.provider_type == 'bedrock': stream_bedrock_response(...)`
   else `stream_anthropic_response(...)`. Decision-time branching only.
4. **Drop the SPA pins.** Search SPA code for
   `preferred_provider: 'anthropic-prod'` and remove all 5 occurrences.
   Routing engine will now pick Bedrock first for RELEASE_DECISION_NARRATIVE
   (Bedrock outranks Anthropic for that use case per
   `domain/assurance_providers.py:561`).
5. **Cost-rate table.** Bedrock pricing varies per model. Add
   `_BEDROCK_COST_PER_INPUT/OUTPUT_TOKEN_USD` dict keyed by
   `provider.default_model`. Fall back to Anthropic Sonnet rates if model
   unknown — operators see an "approximate cost" warning rather than $0.

### Risks
- App Service has no AWS creds today. Bedrock will need `AWS_ACCESS_KEY_ID`
  + `AWS_SECRET_ACCESS_KEY` + `AWS_REGION` in `appsettings`. Or
  managed identity if the production hardening rule kicks in (it doesn't
  for dev). Verify before writing code.
- `bedrock-runtime` is a heavy import — must be lazy or cold start hurts.
- Dropping the SPA pins is reversible but ships through 2 swa deploys;
  do it last after Bedrock is proven via the live `/explain-release` path.

## Tertiary block — S71+S72 carryover bundle
- **Dev Postgres admin password rotation.** Surfaced in S70b chat via `az`
  lookup. `az postgres flexible-server update --resource-group
  rg-aigovern-dev --name psql-aigovern-dev --admin-password <new>`, then
  `az webapp config appsettings set` to roll the connection string.
  Verify with one `--review` smoke.
- **Triage `AGENTS.md` + `team-portal/cookies.txt`.** Untracked since S69.
  `cookies.txt` is almost certainly local-only test debris → `.gitignore`
  + rm. `AGENTS.md` needs a glance — if it's the OpenAI-format agent
  registry, decide commit vs gitignore.
- **agent_memory integration test (S70b STEP 7 deferral).** Needs
  decorator-chain-aware mocking. Mock `domain.agent_memory.
  _write_episode_impl` and assert the @policy_gate → @scrub_pii →
  @guardrails → @trace → @evaluate chain ran in order before
  `write_episode` saw the scrubbed payload.

## Quaternary block — pre-existing test failure triage
S72 `/verify` surfaced 2 failures unrelated to S72 scope. Triage:
- **`test_agents_unit::test_08_list_agents_returns_empty_list_no_engine`** —
  passes in isolation, fails in full-run. Test-order-dependent state
  pollution (likely module-level singleton in `domain/agents.py` retains
  state across tests). Fix: either use `pytest.fixture(autouse=True)` to
  reset the singleton between tests, or move the assertion to a
  setup-isolated tmp_path scaffold.
- **`test_session10_hardening::test_rtf_index_sidecar_used`** — log shows
  "unsigned (legacy entry)" — the RTF sidecar grew a signing requirement
  at some point and the test fixture builds a legacy unsigned entry. Fix:
  update the test fixture to construct a signed entry, OR roll the sidecar
  format version. Determine which during triage.

## S72 followups noted in ARCHITECTURE.md
- `Ask AI` window.prompt() UX is janky — drawer-resident input in S73 or S74.
- `EvidenceSection` summarize-context is a CSV of evidence types
  computed client-side; long types lists may degrade prompt quality.
  Consider server-side evidence-summary endpoint if it hurts.
- `_stream_live_release_narrative` is misnamed (use-case agnostic now).
  Rename when Bedrock branch is added (Secondary block above touches it
  anyway).
- AiSystemDrawer has 7 buttons — at the ceiling. Add the menu refactor
  to the Primary block if scoping the `<AiActionsMenu>` component.
- ciso-console Finding type uses `priority` (P0-P3) — passed into prompt
  as `severity`. Semantic mismatch. Add `severity` to Finding type or
  rename the prompt's slot.

## Working rules in effect
- All S72 close-out rules apply.
- New no-name lessons:
  - SPA wiring for shared components: when porting between SPAs, the
    base CSS class names differ (`font-mono` in team-portal vs `mono` in
    ciso-console). Build-time check catches it but worth grepping when
    porting.
  - `swa deploy` after `npm install` of a new dep: lockfile update lands
    a new vendor chunk hash; the verification grep must include the
    vendor bundle for SSE-dep additions, not just the index bundle.
- `/verify` cross-file pytest stays in close-out routine. Run with `-s`
  on Python 3.14 to bypass the pytest capture-teardown crash (was new
  in this session — pytest 9.0.3 + Py 3.14.4 interaction).

## Risks to manage entering S73
- Secondary block (Bedrock streaming adapter) is the wider one — App
  Service creds + heavy SDK + new cost-rate table. Could push to
  Architecture Review Required (>750K). If band gets tight, ship
  Primary + Tertiary and defer Secondary again.
- Don't bundle Primary + Secondary + Tertiary + Quaternary in one
  session. Pick at most 2.
