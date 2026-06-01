# SESSION-75 — Bedrock streaming adapter (when AWS subscription is provisioned)

## Status entering S75
S74 closed the carryover queue (3 test fixes, 1 rename, 1 CSS fix, repo
hygiene). S74 Primary (Bedrock streaming adapter) was blocked at the
verify-AWS-credentials step — user confirmed Azure-only; AWS subscription
provisioning is the gating prerequisite.

S74 commit: `c071286` — Refactor: S74 — carryover cleanup.

## Prerequisite — DO NOT START S75 WITHOUT THESE

User must provide:
1. **AWS subscription provisioned** with a billing alert at $20/month
   minimum (key-leak guard).
2. **IAM user + access key pair** (NOT IAM role — App Service can't transit
   cross-cloud IAM roles). Least-privilege inline policy:
   ```
   bedrock:InvokeModel
   bedrock:InvokeModelWithResponseStream
   ```
3. **Bedrock model access GRANTED** in the AWS console for
   `anthropic.claude-3-5-sonnet-20241022-v2:0` in the chosen region.
   This is a separate click-through approval — easy to miss.
4. **Region pick** — `us-east-1` (default) or `us-west-2`.

When ready, paste:
```
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=us-east-1
```

S75 sets them via `az webapp config appsettings set` exactly like
`ANTHROPIC_API_KEY` per global CLAUDE.md "Anthropic API Key — Handle With
Care" rule (never hardcode; never log; CLI-only).

## Primary block — Bedrock streaming adapter
**Workflow type:** Architecture (token band Normal <750K)

### Steps
1. **App Service appsettings** — set the 3 AWS_* vars via az CLI.
2. **`stream_bedrock_response()` async generator** in
   `domain/assurance_providers.py`. Mirrors the shape of
   `stream_anthropic_response` (now the only reference impl): yields
   `("delta", text) | ("done", usage)` tuples. Uses
   `bedrock-runtime.converse_stream` from `boto3` with lazy import per
   `[[appservice-deploy-python]]` (heavy SDK at top-level kills cold start).
   Same `_MAX_TOKENS_BY_USE_CASE` table; same `_build_prompt()` branches.
3. **Cost-rate table** — `_BEDROCK_COST_PER_INPUT/OUTPUT_TOKEN_USD` dict
   keyed by `provider.default_model`. Anthropic rates as fallback for
   unknown models (logged warning).
4. **Dispatcher selection** in `_stream_live_assurance_response` (renamed
   in S74 — file: `api/assurance_model.py`). Branch on
   `decision.provider.provider_type == 'bedrock'` to pick the new
   generator. Decision-time only — provider already chosen upstream by
   the routing engine.
5. **`requirements.txt` + `requirements-deploy.txt`** — add `boto3>=1.35`.
   Per `[[requirements-deploy-drift]]` the deploy file is the source of
   truth for runtime imports.
6. **Drop SPA Anthropic pins.** Authoritative count (audited 2026-05-31 in S74b):
   **9 pins across 5 files.** S73 plan said 8 because it counted the
   original `FailedGateRow.onExplain` pin and the AiSystemDrawer pins
   separately, but `FailedGateRow` logic was inlined into AiSystemDrawer
   in a later session — actual AiSystemDrawer count is 5, not 4.

   ```
   team-portal/src/pages/ai-systems/AiSystemDrawer.tsx:275  (Ask AI body)
   team-portal/src/pages/ai-systems/AiSystemDrawer.tsx:416  (summarize finding)
   team-portal/src/pages/ai-systems/AiSystemDrawer.tsx:436  (summarize evidence)
   team-portal/src/pages/ai-systems/AiSystemDrawer.tsx:472  (draft report)
   team-portal/src/pages/ai-systems/AiSystemDrawer.tsx:519  (explain release — original S69 FailedGateRow)
   ciso-console/src/pages/findings/FindingsInboxPage.tsx:426  (summarize finding)
   ciso-console/src/pages/evidence/EvidencePage.tsx:155  (summarize this view)
   ciso-console/src/pages/portfolio/PortfolioPage.tsx:295  (ask AI per system)
   ciso-console/src/pages/portfolio/PortfolioPage.tsx:319  (draft report per system)
   ```

   Remove all 9; routing engine picks Bedrock first for restricted
   data classes per existing config. Two SPA deploys after engine
   smoke proves the Bedrock path.
7. **Live smoke each button** post-deploy. Cookie + browser per
   `[[smoke-scripts-must-run-live]]`. Defer execution to user — they
   click, we watch logs.

### Risks
- `boto3` import is heavy. Lazy-load is mandatory for cold start.
- 8-9 buttons to smoke; defer execution to user.
- Two manual SPA deploys after engine is proven via `/explain-release`
  live path. Don't bundle engine + SPA in one deploy wave.
- Bedrock streaming uses `converse_stream` (newer API). Verify
  `event['contentBlockDelta']['delta']['text']` chunk shape against
  current `boto3` version — older 1.34 versions used different event
  schema (`event['chunk']['bytes']` JSON).

## Secondary block — Postgres password rotation
**Workflow type:** Deployment (token band Normal <300K)

```
az postgres flexible-server update --resource-group rg-aigovern-dev \
  --name psql-aigovern-dev --admin-password <new>
az webapp config appsettings set --resource-group rg-aigovern-dev \
  --name app-aigovern-dev --settings "POSTGRES_PASSWORD=<new>" "PG_PASSWORD=<new>"
```
(Verify both env var names — the engine reads `POSTGRES_PASSWORD` per
S74's `az webapp config appsettings list` audit, but legacy code may
reference `PG_PASSWORD`. Grep before rotation.)

Verify with one `/explain-release` live smoke (covers DB read path).

## Tertiary block — optional enhancements
- ciso-console `PortfolioPage` — prefetch per-row evidence counts so
  Draft Report has parity grounding with team-portal `AiSystemDrawer`.
- Address `datetime.utcnow()` deprecation warnings — 66 in current
  test suite output, all pointing at `domain/release_gate_engine.py:622`
  + similar sites. Bulk sed to `datetime.now(timezone.utc)` — pure
  refactor, no behavior change.

## Working rules in effect
- All S72 + S73 + S74 close-out rules.
- New from S74 — **provider-cache singletons compound test pollution**:
  any test that exercises a `@lru_cache`-backed `get_*_backend()` will
  pin state for the rest of the session. Mock at the lazy-import seam
  (`scrubber.tokenise_payload`) not the cached factory. See
  `tests/test_agent_memory_chain.py` for the pattern.
- `/verify` runs with `-s` on Python 3.14 per
  `[[pytest-py314-capture-teardown]]`. Full-suite summary truncates;
  use dots-only as primary signal.
- SPA deploys are manual `swa deploy` per `[[spa-deploy-is-manual-swa]]`.
- Engine deploy: push to `main` triggers `.github/workflows/deploy.yml`.

## Risks to manage entering S75
- Primary depends entirely on AWS provisioning landing cleanly. If
  model-access approval is delayed (sometimes takes hours), do not
  block — pivot to Tertiary (datetime warnings sweep, evidence
  prefetch). Both are useful, isolated, deploy-light.
- The "8 vs 9 button" discrepancy in the S74 plan is a real audit gap.
  Grep before editing; trust the grep, not the prior plan count.
