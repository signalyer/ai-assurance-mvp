# Resume — AI Assurance Platform · post-S75

## Where I am
**S75 shipped end-to-end.** Bedrock streaming adapter is live; the 9 SPA
Anthropic-prod pins are gone; routing engine now picks Bedrock first for
restricted data classes. All commits pushed to `main`. CI green.

Last commit: `ea9ebdc` (S75 close-out docs). Last engine deploy SHA: `fec54e1`
(or later if `ea9ebdc` deploy has finished by the time you read this — that
commit was docs-only so deploy is a no-op behavior-wise).

Live state:
- Engine: `app-aigovern-dev.azurewebsites.net` — boto3 + AWS env vars set,
  Bedrock route in `_stream_live_assurance_response` dispatcher.
- team-portal SPA: `index-lJdBG_wQ.js` on `portal.aigovern.sandboxhub.co` —
  zero `anthropic-prod` hits in live bundle.
- ciso-console SPA: `index-DU584gZD.js` on `gov.aigovern.sandboxhub.co` —
  zero `anthropic-prod` hits in live bundle.
- Bedrock model: `us.anthropic.claude-sonnet-4-6` (US cross-region inference
  profile). Pricing: $3/M input, $15/M output. Local probe cost: $0.00119
  per ~200-token interaction.

Tests: **354 passed / 0 failed / 8 skipped / 0 deprecation warnings.**

## Decisions locked in S75 (don't re-litigate)
- **Bedrock 4.x = inference profile required.** modelId is `us.anthropic.claude-sonnet-4-6`
  not `anthropic.claude-sonnet-4-6`. See [[bedrock-4x-requires-inference-profile]].
- **Marketplace + use-case form gates on first invoke.** Documented in
  [[bedrock-anthropic-marketplace-gate]]. Don't be surprised when a *new*
  AWS account hits the same chain.
- **Yield contract = `("delta", text) | ("done", usage_dict)`.** Provider-
  agnostic at the dispatcher. Any future streaming provider (Azure OpenAI,
  Foundry-Claude, local vLLM) must mirror this shape exactly so the audit /
  response code stays unchanged.
- **boto3 lazy import inside `stream_bedrock_response`.** Top-level would
  blow up App Service cold start. Per [[appservice-deploy-python]].
- **AWS creds via env vars on App Service**, not IAM roles. App Service can't
  transit cross-cloud IAM roles. `api_key_secret_ref` updated to reflect this.
- **9 SPA pins removed.** Authoritative audit complete in S74b. The routing
  engine sort key in `domain/assurance_providers.py:562` prefers Bedrock when
  both providers are allowed for the use case.

## Outstanding — things only the user can do
1. **Live button-click smoke** across all 9 streaming surfaces. Per
   `[[smoke-scripts-must-run-live]]` Claude can't replicate the OIDC/cookie
   chain. Check App Insights for `model=us.anthropic.claude-sonnet-4-6` in
   LIVE audit events. Buttons to test:
   - team-portal AiSystemDrawer: Ask AI, Summarize finding, Summarize
     evidence, Draft Report, Explain Release (the "FailedGateRow" path)
   - ciso-console PortfolioPage: Ask AI per system, Draft Report per system
   - ciso-console FindingsInboxPage: Summarize with AI
   - ciso-console EvidencePage: Summarize this view
2. **Postgres password rotation** (carryover from S71). Provide a password
   and Claude will run the two-step `az` rotation + verify.

## Optional hygiene (skip unless asked)
- **Revoke marketplace perms** on `signallayer-bedrock-runtime`. Bedrock
  subscription is now account-wide; the bootstrap-only perms aren't needed
  anymore. Tightens IAM blast radius. Updated policy JSON: drop the
  `MarketplaceSubscribeForBedrock` Sid; keep `BedrockClaudeInvoke` and
  `BedrockDiscovery`.
- **2 FastAPI-internal deprecation warnings** — wait for FastAPI 1.0 release.
- **AGENTS.md vs CLAUDE.md sync** — AGENTS.md has a 2026-05-27 compound rule
  CLAUDE.md doesn't. Decide canonical source. 5-min judgment call.

## Higher-leverage forward work (separate session)
**Wire the `agent_memory` decorator chain into a production code path.**

The S70b test (`tests/test_agent_memory_chain.py`) proves the contract:
@policy_gate → @scrub_pii → @guardrails → @trace → @evaluate, with
`write_episode` as inline tail receiving scrubbed payload + vault_id.

But no production agent currently *uses* this stack — `azure-architect/agent.py`
calls `write_episode` directly with inline trace/eval calls rather than
through the decorator chain. That's a real gap between the security contract
in CLAUDE.md ("scrubber.tokenise_payload() runs BEFORE tracer.trace_call()")
and what production agents actually do.

A session that converts azure-architect (and any other production agent
calling `write_episode` inline) to the decorated stack would close the gap.
~3-4 hours; touches `agents/azure-architect/agent.py`, possibly creates a
shared decorator-stack helper in `signallayer/decorators.py`, requires
running the live agent end-to-end to confirm scrubbed payload reaches
Langfuse and the Postgres T2 store.

## Session entry checklist
```powershell
az account set --subscription "SignalLayerDev"
$env:MSYS_NO_PATHCONV = "1"
cd C:/ai-assurance-mvp
git status                                   # expect clean (data/assurance_audit.jsonl drift OK)
git log --oneline -3                         # expect ea9ebdc at HEAD
python -m pytest tests/ -s 2>&1 | tail -2    # expect 354 passed
az webapp config appsettings list --name app-aigovern-dev --resource-group rg-aigovern-dev --query "[?contains(name, 'AWS')].name" -o tsv
                                             # expect: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION
```

## Working rules in effect (relevant to next sessions)
All prior rules apply. New in S74b + S75:
- [[provider-cache-singleton-test-pollution]] — mock at lazy-import seam
- [[bedrock-4x-requires-inference-profile]]
- [[bedrock-anthropic-marketplace-gate]]
- `/verify` runs with `-s` on Py 3.14 per [[pytest-py314-capture-teardown]]
- SPA deploys are manual `swa deploy` per [[spa-deploy-is-manual-swa]]
- Engine deploy: push to `main` triggers `.github/workflows/deploy.yml`
