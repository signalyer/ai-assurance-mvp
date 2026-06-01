# Resume — AI Assurance Platform → S75

## Where I am
S74 + S74b shipped end-to-end on `main`. Seven commits, all pushed, all CI-green.
Test suite at **354 passed / 0 failed / 8 skipped / 0 deprecation warnings**.
Last committed engine SHA: `05e55b2`. Live SPA bundle on `gov.aigovern.sandboxhub.co`:
`index-Bw_jV-dl.js`. team-portal SPA unchanged since S73 (`index-DHlFuQxe.js`).

S75 Primary (Bedrock streaming adapter) is **blocked on AWS subscription provisioning**.
User is working on it.

## Decisions already made (don't re-litigate)
- **S75 Primary = Bedrock streaming adapter.** Not Azure OpenAI, not Foundry-Claude.
  User confirmed AWS subscription is the path.
- **Anthropic pins: 9, not 8.** Authoritative list in
  [SESSION-75-bedrock-streaming-when-aws-ready.md](SESSION-75-bedrock-streaming-when-aws-ready.md)
  Step 6. Verified by grep, not by prior plan estimate.
- **Provider cache @lru_cache mocking pattern** — mock at the lazy-import seam
  (e.g. `scrubber.tokenise_payload`), not the cached factory. See
  `tests/test_agent_memory_chain.py` for the pattern. Memory rule:
  [[provider-cache-singleton-test-pollution]].
- **datetime wire format = "Z" trailing.** Sweep used
  `.isoformat().replace("+00:00", "Z")` to preserve. Don't switch to bare
  `.isoformat()` — JSONL consumers parse the `Z` suffix.
- **PortfolioPage evidence prefetch is O(systems × file-scan).** Acceptable at
  demo scale (<25 systems); flagged in code for revisit if portfolio grows.
- **OpenAPI spec is committed.** Run `python scripts/export_openapi.py` after
  any API model change and commit the diff. Pre-commit hook is documented but
  not enforced — silent drift is the risk.

## Key files to load
- [SESSION-75-bedrock-streaming-when-aws-ready.md](SESSION-75-bedrock-streaming-when-aws-ready.md) — full Primary plan with prereq checklist + 9-pin file:line list
- [ARCHITECTURE.md](../../ARCHITECTURE.md) S73, S74, S74b blocks (~lines 192-260) — for the streaming pattern reference
- `domain/assurance_providers.py::stream_anthropic_response` (line 1054) — Bedrock adapter must mirror this shape exactly
- `api/assurance_model.py::_stream_live_assurance_response` (line 489) — dispatcher; branch on `decision.provider.provider_type == 'bedrock'` here
- `tests/test_agent_memory_chain.py` — provider-cache mocking pattern reference

## Outstanding questions (need user input)
1. **AWS credentials** — paste `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`,
   `AWS_REGION` (default `us-east-1`).
2. **Bedrock model access status** — confirm "Access granted" (not just
   "Available") for `anthropic.claude-3-5-sonnet-20241022-v2:0` in console.
3. **Postgres rotation password** — optional bundle with AWS work, or defer.
4. **AGENTS.md ↔ CLAUDE.md sync** — AGENTS.md has a 2026-05-27 compound rule
   CLAUDE.md doesn't. Decide canonical source. (5-min decision, deferred from
   S74b "stop scraping the barrel" rule.)

## Next concrete action when AWS lands
1. Verify creds via `az webapp config appsettings set` (3 vars on `app-aigovern-dev`).
2. Boto3 smoke probe: `boto3.client('bedrock-runtime').list_foundation_models()`
   to confirm IAM + region + reachability before any code.
3. Build `stream_bedrock_response()` async generator in
   `domain/assurance_providers.py` mirroring `stream_anthropic_response`.
4. Wire dispatcher in `_stream_live_assurance_response`.
5. Add `boto3>=1.35` to `requirements-deploy.txt` per
   [[requirements-deploy-drift]].
6. Push → engine auto-deploys → live smoke `/explain-release`.
7. Drop 9 SPA Anthropic pins; rebuild + `swa deploy` both SPAs.
8. User clicks 9 buttons; we watch App Insights.

## Working rules in effect
- All rules from S72 + S73 + S74 + S74b close-outs.
- Hot rules for S75:
  - [[anthropic-max-tokens-streaming-threshold]] — Bedrock equivalent applies;
    use `converse_stream` not `converse` for any max_tokens > 2000.
  - [[appservice-deploy-python]] — boto3 lazy import; never top-level.
  - [[requirements-deploy-drift]] — boto3 goes in requirements-deploy.txt too.
  - [[smoke-scripts-must-run-live]] — defer button-click smoke to user.
  - [[spa-deploy-is-manual-swa]] — manual swa deploy for both SPAs after pin drops.
  - [[provider-cache-singleton-test-pollution]] — when writing Bedrock tests,
    mock at the lazy-import seam (`boto3.client`), not the cached factory.
- `/verify` uses `-s` on Py 3.14 per [[pytest-py314-capture-teardown]].
- Engine deploy: push to `main` triggers `.github/workflows/deploy.yml`.

## Session entry checklist
```
az account set --subscription "SignalLayerDev"
$env:MSYS_NO_PATHCONV = "1"
cd C:/ai-assurance-mvp
git status                                   # expect clean (modulo data/assurance_audit.jsonl drift)
git log --oneline -3                         # expect 05e55b2 at HEAD
python -m pytest tests/ -s 2>&1 | tail -2    # expect 354 passed
az webapp config appsettings list --name app-aigovern-dev --resource-group rg-aigovern-dev --query "[?contains(name, 'AWS')].name" -o tsv
                                             # expect empty until AWS creds set
```
