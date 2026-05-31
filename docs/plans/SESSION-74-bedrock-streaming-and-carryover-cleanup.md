# SESSION-74 — Bedrock streaming adapter + carryover cleanup

## Status entering S74
S73 shipped on `main`:
- `<AiActionsMenu>` shared component (team-portal + ciso-console verbatim copies)
- team-portal AiSystemDrawer refactored: 7 buttons → 6 (Ask + Draft Report collapsed into menu)
- ciso-console PortfolioPage rows: per-system Ask AI + Draft Report via menu
- ciso-console EvidencePage: `Summarize this view` button bound to filtered rows
- Bundles: team-portal `index-DHlFuQxe.js`, ciso-console `index-BtyZTC8Z.js`
- 8 streaming buttons total across both SPAs, all Anthropic-pinned

S71+S72 carryover items remain untouched. The compounding "S71/S72/S73 carryover" header on these is now a smell — S74 should close most of them.

## Primary block — Bedrock streaming adapter
**Workflow type:** Architecture (token band Normal <750K)

### Goal
Build the Bedrock streaming adapter and drop `preferred_provider: 'anthropic-prod'`
on all 8 streaming buttons. This is the work S69/S71/S72/S73 plans repeatedly
mention as "deferred."

### Steps
1. **App Service creds.** Verify `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` +
   `AWS_REGION` exist in `appsettings` (dev). If absent, set them via
   `az webapp config appsettings set` — same pattern as `ANTHROPIC_API_KEY`.
   Production-hardening rule doesn't apply (dev).
2. **`stream_bedrock_response()` async generator** in
   `domain/assurance_providers.py`. Same shape as `stream_anthropic_response`
   (yields `("delta", text) | ("done", usage)` tuples). Uses
   `bedrock-runtime.converse_stream` from `boto3`. Lazy import per
   App Service cold start (see existing `stream_anthropic_response` import
   pattern). Same `_MAX_TOKENS_BY_USE_CASE` table; same `_build_prompt()`
   branches; same SSE wire shape.
3. **Dispatcher selection** in `_stream_live_release_narrative` (still
   misnamed — rename this session per S73 open issue). Branch on
   `decision.provider.provider_type == 'bedrock'`. Decision-time only —
   provider already chosen upstream.
4. **Drop SPA pins.** Grep both SPAs for
   `preferred_provider: 'anthropic-prod'`. Expected count: 8
   (1 in team-portal FailedGateRow + 4 in team-portal AiSystemDrawer
   + 1 in ciso-console FindingsInboxPage + 2 in ciso-console PortfolioPage
   + 1 in ciso-console EvidencePage). Remove all. Routing engine picks
   Bedrock first for RELEASE_DECISION_NARRATIVE per existing config.
5. **Cost-rate table.** `_BEDROCK_COST_PER_INPUT/OUTPUT_TOKEN_USD` dict
   keyed by `provider.default_model`. Anthropic Sonnet rates as fallback
   for unknown models (with logged warning).
6. **Live smoke each of 8 buttons** post-deploy. Cookie + browser per
   `[[smoke-scripts-must-run-live]]`.

### Risks
- `bedrock-runtime` import is heavy. Lazy-load or cold start hurts.
- 8 buttons to smoke; defer to user.
- Dropping pins ships through 2 swa deploys; do that last after Bedrock
  is proven via the live `/explain-release` path.

## Secondary block — Carryover cleanup bundle
**Workflow type:** Refactoring (token band Normal <500K)

The carryover queue is now 4 sessions deep. Close it in one bundle.

### Step 1 — dev Postgres admin password rotation
```
az postgres flexible-server update --resource-group rg-aigovern-dev \
  --name psql-aigovern-dev --admin-password <new>
az webapp config appsettings set --resource-group rg-aigovern-dev \
  --name app-aigovern-dev --settings "PG_PASSWORD=<new>"
```
Verify with one `--review` smoke.

### Step 2 — AGENTS.md + team-portal/cookies.txt triage
- `cookies.txt`: almost certainly local-only test debris from S69. Add to
  `.gitignore` + `rm`.
- `AGENTS.md`: glance content. If it's the OpenAI-format agent registry,
  decide commit vs gitignore. If unclear, default to commit-with-empty-stub
  so the slot exists for future runtimes.

### Step 3 — Pre-existing test failures
- `test_agents_unit::test_08_list_agents_returns_empty_list_no_engine`:
  fails only in full-run. Singleton state pollution in `domain/agents.py`.
  Fix: `pytest.fixture(autouse=True)` resetting the singleton, or move
  assertion to tmp_path scaffold.
- `test_session10_hardening::test_rtf_index_sidecar_used`: sidecar grew
  a signing requirement; test fixture builds unsigned entry. Fix the
  fixture (signed entry) OR roll the sidecar format version.
  Determine which during triage.

### Step 4 — agent_memory integration test (S70b deferral)
Mock `domain.agent_memory._write_episode_impl` and assert the
@policy_gate → @scrub_pii → @guardrails → @trace → @evaluate chain ran
in order before `write_episode` saw the scrubbed payload. Decorator-chain-
aware mocking.

### Step 5 — EvidencePage `--surface-2` dead var (S73 finding)
`ciso-console/src/pages/evidence/EvidencePage.tsx:351` uses
`var(--surface-2)` which isn't defined. Expanded evidence row has no
background. Replace with `--bg-card-hover` (or whatever matches the
intended expanded-row chrome).

## Tertiary block — Misc S73 open issues
- Rename `_stream_live_release_narrative` → `_stream_live_assurance_response`
  (or similar). Touched anyway by the Bedrock branch.
- Optional: prefetch per-row evidence counts in the portfolio listing so
  ciso-console PortfolioPage Draft Report has parity grounding with
  team-portal AiSystemDrawer.

## Working rules in effect
- All S72 + S73 close-out rules.
- New no-name lesson from S73: **Audit SPA CSS var names before any
  themed component lands.** S73 caught `--surface-1/2` (used nowhere
  else) only because I grepped before deploy. The same shape silently
  shipped on EvidencePage:351 in an earlier session. Make `grep -E
  "^\s*--[a-z]" base.css` the canonical pre-write check for any new
  styled component.
- `/verify` runs with `-s` on Python 3.14 per
  `[[pytest-py314-capture-teardown]]`.

## Risks to manage entering S74
- Primary (Bedrock) is wider than S73. App Service creds + heavy SDK +
  new cost-rate table + 8 buttons to smoke. Could push to Architecture
  Review Required (>750K). If band tightens, ship Primary alone and
  push Secondary carryover to S75.
- Don't bundle Primary + Secondary + Tertiary. Pick Primary + at most
  one Secondary step (Step 1 password rotation is fastest).
