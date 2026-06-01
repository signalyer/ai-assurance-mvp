# SESSION 80–83 — Agent Runner: a real, demo-watchable agent with full chain visibility

## Why this exists (user's words, S79 close)
> *"I need a real agent that I can run to show the demo and not just onboarded
> to the team and ciso sites. I should be able to show how the agent works and
> showcase everything."*

Onboarding records prove cataloging. They don't prove the platform DOES anything.
This arc builds the missing piece: a real agent the user can invoke on stage with
the entire governance chain rendered live, side-by-side with the destination-
agnostic local-simulated path, deep-linked to Langfuse + App Insights.

## Outcome (end of S83)
On stage, the user opens **team-portal → Agent Runner**, picks `finadvice`,
types *"Summarize this client's portfolio risk and recommend rebalancing"*,
clicks **Run**, and the screen splits into two columns:

| Left column — External / Anthropic | Right column — Internal / local-simulated |
|---|---|
| `sys-demo-finadvice-001` (sanitized_confidential) | `sys-demo-compliance-001` (PII + NPI tagged) |
| Provider: Anthropic claude-sonnet-4-6 | Provider: local-simulated |

Both columns animate the same 7-step chain ticker as events fire:

```
[ 12ms] ✓ policy_gate     ALLOW   (rule: assurance.allowed.use_cases)
[ 34ms] ✓ scrub_pii       REDACTED 3 tokens   vault_id=v_a4f...
[ 71ms] ✓ guardrails      PASSED  (injection: 0.02, topic: in-scope)
[201ms] » llm             streaming...      ▓▓▓▓▓▓▓░░░ 67%
[3.2s]  ✓ llm             184 in / 412 out  $0.00712  model=sonnet-4-6
[3.4s]  ✓ evaluate        0.84 avg  (5 metrics)  hallucination=0.91 ✓
[3.5s]  ✓ memory          ep_8f2a1c... outcome=success workload=sys-demo-...
[3.5s]  ✓ audit           aud-XXXXXXXX  decision=LIVE
                                              [open in Langfuse ↗] [App Insights ↗]
```

Below the columns: **PII Redaction Preview** showing raw operator prompt with
`[PII_NAME_001]` `[PII_ACCOUNT_002]` tokens highlighted vs the scrubbed text
sent upstream. `vault_id` is the join key — same redaction applied to both
columns, but the columns run independently and may complete at very different
times (Anthropic ~3s, local-simulated ~150ms).

## Architecture — load-bearing decisions to lock at S80 entry

### LBD-1. SSE chain-event protocol
Today: `_dispatch_streaming` emits two event types — `delta` (LLM token) + `done`
(terminal AskResponseOut JSON). That works for the drawer but is not enough for a
chain-visible demo.

**Decision:** new event type set, emitted by a new dispatcher
`stream_agent_run_with_chain_events()`. Each event carries `step`, `status`,
`elapsed_ms`, plus step-specific payload. Drawer continues to use the legacy
contract — Agent Runner is the only consumer of the rich contract.

Proposed event types:
| event | when | payload keys |
|---|---|---|
| `chain.start` | dispatcher entry | `run_id`, `agent_id`, `provider_id`, `system_id`, `started_at` |
| `policy_gate` | after `select_assurance_provider` + `validate_provider_policy` | `decision: ALLOW\|DENY`, `rule`, `reason`, `elapsed_ms` |
| `scrub_pii` | after `sanitize_payload_for_provider` + scrubber tokenise | `redacted_fields: [...]`, `redacted_count: int`, `vault_id`, `raw_preview` (first 200 chars, server-side decision whether to surface), `scrubbed_preview`, `elapsed_ms` |
| `guardrails` | after `@guardrails` decorator runs | `injection_score`, `topic_in_scope`, `safety_pass`, `elapsed_ms` |
| `llm.delta` | per token chunk | `text` (replaces the current `delta` payload exactly) |
| `llm.done` | terminal LLM event | `model`, `input_tokens`, `output_tokens`, `cost_estimate_usd`, `elapsed_ms` |
| `evaluate` | after 5-metric eval | `scores: {metric: {score, passed, skipped}}`, `avg_score`, `elapsed_ms` |
| `memory` | after `write_episode` | `episode_id`, `outcome`, `workload_id`, `elapsed_ms` |
| `audit` | after `create_provider_audit_event` | `audit_id`, `decision: LIVE\|BLOCKED\|SIMULATED`, `trace_id`, `langfuse_url`, `appinsights_url`, `elapsed_ms` |
| `chain.done` | terminal | `total_elapsed_ms`, `outcome`, `episode_id`, `audit_id` |
| `chain.error` | any uncaught | `step`, `error_type`, `message` |

Open question for S80: **PII raw_preview policy.** Should the SSE stream EVER carry
the raw operator text back to the SPA? Default position is **yes for the demo
(behind `DEMO_MODE=true` env)**, **never in production**. The Redaction Preview
needs both halves to be the visceral demo moment, but in real prod we'd render
only the scrubbed half plus token-count + vault_id.

### LBD-2. Agent registry — making `finadvice` a first-class concept
Today `agents/azure-architect/` is the only agent. There's no registry — the
agent runs from CLI only.

**Decision:** introduce a lightweight `agents/_registry.py`:
```python
@dataclass(frozen=True)
class AgentSpec:
    agent_id: str           # "finadvice", "azure-architect"
    name: str               # "Financial Advisor Risk Reviewer"
    description: str
    default_system_id: str  # which onboarded AI system this agent belongs to
    module_path: str        # "agents.finadvice.agent"
    entrypoint: str         # "run_review" — the async function name
    tool_specs: list[dict]  # Anthropic-format tool specs for the loop
```

`api/agent_runner.py` looks up the spec, imports the module, calls the
entrypoint with the operator prompt. No magic. azure-architect gets registered
too (`agent_id="azure-architect"`).

### LBD-3. Where the dual-path mechanic lives
Each column = one independent SSE stream against `POST /api/agent-runner/run`.
The page opens TWO `EventSource` connections with different `system_id` query
params. The backend doesn't know about "dual" — it just streams one run. The
SPA orchestrates the side-by-side.

This keeps the backend honest: every run is the same governance chain regardless
of who's watching. The demo framing is a UI choice.

### LBD-4. finadvice agent — tool-use shape
Mirror azure-architect: 5-turn cap, three tools, deterministic mock data.

| Tool | What it does | Mock data source |
|---|---|---|
| `get_client_portfolio(client_id)` | Returns positions + balances | `agents/finadvice/mocks/portfolios.json` — 3 fixture clients |
| `get_market_snapshot(symbols: list[str])` | Last-price + 30d vol per symbol | `agents/finadvice/mocks/market.json` — deterministic |
| `get_client_risk_profile(client_id)` | KYC tier, risk tolerance, restrictions | `agents/finadvice/mocks/profiles.json` |

The agent reasons across these and produces a portfolio-risk + rebalance
recommendation. Calibration target: the response should name the client's
actual top-3 positions, cite at least one risk-profile constraint, and produce
2-3 ranked rebalance actions. Calibration via worked example per the
[[grep-all-consumers-before-contract-flip]] / "synthetic data only reveals
schema" rule in CLAUDE.md.

PII surface (for the redaction demo): each portfolio mock includes
`client_name`, `account_number`, `tax_id`, `dob`. These should ALL get redacted
by scrubber.tokenise_payload before reaching Anthropic. The Redaction Preview
component proves it.

## Session split

### S80 — Backend: agent registry, chain-event protocol, agent runner endpoint
**Files net-new:**
- `agents/_registry.py` — `AgentSpec` dataclass + `REGISTRY` dict + `get_agent(agent_id)`
- `agents/finadvice/__init__.py`
- `agents/finadvice/agent.py` — `run_review(prompt: str, *, vault_id="", workload_id=...) -> dict`. SDK decorator chain on entry. Anthropic tool-use loop (5-turn cap, same shape as azure-architect `_run_plan`). Mock-API tool dispatch. `write_episode` at synthesis.
- `agents/finadvice/prompts.py` — `SYSTEM_PROMPT`, `TOKEN_BUDGETS`, `build_user_message`, `TOOL_SPECS` (Anthropic-format)
- `agents/finadvice/mocks/portfolios.json` + `market.json` + `profiles.json`
- `agents/finadvice/.env.example`
- `domain/agent_runner.py` — `stream_agent_run_with_chain_events(agent_id, prompt, system_id, user) -> AsyncIterator[dict]`. Wraps the agent call; emits the 10 typed events listed in LBD-1. Catches exceptions per step, emits `chain.error`.
- `api/agent_runner.py` — `POST /api/agent-runner/run` (SSE), `GET /api/agent-runner/agents` (returns registry as JSON for the picker)
- `tests/test_agent_runner_chain_events.py` — asserts event ORDER (policy before scrub before guard before llm before eval before memory before audit), asserts every event has `elapsed_ms`, asserts `chain.done` arrives last.

**Files modified:**
- `dashboard.py` — eager-import `agents._registry` + `api.agent_runner`; `app.include_router(agent_runner_router)`. (Per `[[lazy-imports-skip-module-load-bootstrap]]`.)
- `agents/azure-architect/__init__.py` — register in `agents._registry` (lightweight).
- `requirements-deploy.txt` — no new deps expected; finadvice uses anthropic + signallayer + json (already pinned).
- `ARCHITECTURE.md` — S80 entry.

**Calibration step (mandatory before declaring S80 done):**
1. Run finadvice agent from CLI against client `cln-001` with the seed prompt.
2. Assert: 3 specific positions named, ≥1 risk constraint cited, ≥2 rebalance actions ranked. If not, tighten `SYSTEM_PROMPT` and re-run. Do NOT proceed to UI work on an uncalibrated agent.
3. Verify all 4 PII fields (`client_name`, `account_number`, `tax_id`, `dob`) appear redacted in the scrubbed prompt that lands in the `scrub_pii` event.

### S81 — SPA: Agent Runner page, single-stream Chain Ticker
**Files net-new:**
- `team-portal/src/pages/agent-runner/AgentRunnerPage.tsx`
- `team-portal/src/pages/agent-runner/ChainTicker.tsx` — renders the 8-step badge column from a stream of events
- `team-portal/src/pages/agent-runner/ChainStepBadge.tsx`
- `team-portal/src/pages/agent-runner/AgentPicker.tsx`
- `team-portal/src/pages/agent-runner/types.ts` — TS interface for each event type

**Files modified:**
- `team-portal/src/App.tsx` (or router file) — register `/agent-runner` route
- `team-portal/src/shared/Nav.tsx` (or equivalent) — top-nav entry
- `team-portal/src/pages/agent-runner/api.ts` — `runAgent({ agentId, systemId, prompt })` returns an `EventSource`

**Calibration:** click Run, watch all 8 badges flip in order, eyeball that
`elapsed_ms` numbers are plausible (single-digit ms for policy/scrub/guard,
seconds for LLM). Bundle-hash + swa deploy + live verify per `[[spa-deploy-is-manual-swa]]`.

### S82 — SPA: side-by-side dual-path + PII Redaction Preview
**Files net-new:**
- `team-portal/src/pages/agent-runner/DualPathColumns.tsx` — splits the page into two ChainTicker columns running independent EventSources
- `team-portal/src/pages/agent-runner/PIIRedactionPreview.tsx` — raw vs scrubbed side-by-side with token highlighting; reads from the `scrub_pii` event payload

**Files modified:**
- `AgentRunnerPage.tsx` — pivot from single-stream to dual-stream layout; the second column targets `system_id=sys-demo-compliance-001` so routing picks `local-simulated`
- Backend `domain/agent_runner.py` — env-gate `raw_preview` payload behind `DEMO_MODE=true`. Default off in prod; flip on for App Service deploy via app setting.

### S83 — Deep links + first stage rehearsal
**Files modified:**
- `domain/agent_runner.py` — `audit` event payload gains `langfuse_url` (built from `LANGFUSE_PROJECT_URL` + `trace_id`) and `appinsights_url` (built from `APPLICATIONINSIGHTS_RESOURCE_ID` + `operation_id`). Both env-driven; fall back to `null` if unset (UI hides link).
- `ChainStepBadge.tsx` — render link icons in the `audit` row when URLs present.
- App Service settings: ensure `LANGFUSE_PROJECT_URL` and `APPLICATIONINSIGHTS_RESOURCE_ID` are set per `[[appservice-deploy-python]]`.

**Calibration:**
- Stage rehearsal: cold-start the demo flow 5 times; measure end-to-end time
  (seed prompt → both columns complete). Target < 8s on warm App Service.
- One rehearsal MUST include disconnecting wifi mid-stream to prove the
  `asyncio.CancelledError` path in the dispatcher still writes a partial audit
  row (S78 plumbing).
- Confirm deep links work from a cold browser session (no Langfuse session
  cookie pre-warmed).

## Working rules in effect
- `[[lazy-imports-skip-module-load-bootstrap]]` — `dashboard.py` lifespan eager-imports `api.agent_runner` AND `agents._registry`. The registry's import side effect is the agent module imports themselves; missing this means the picker returns an empty list with no error.
- `[[anthropic-max-tokens-streaming-threshold]]` — finadvice tool-use turns use streaming context manager (already the pattern in `_run_plan`).
- `[[bare-except-hides-broken-integrations]]` — each step's exception handler in `stream_agent_run_with_chain_events` uses `_log.exception` + emits `chain.error` with the step name. Never swallow.
- `[[grep-all-consumers-before-contract-flip]]` — the SSE event protocol is a new public contract. Document the schema in `docs/agent-runner-sse-protocol.md` at S80 close so future agents extending it know what they're conforming to.
- `[[deploy-zip-overwrites-runtime-data]]` — `agents/finadvice/mocks/*.json` is code (deterministic fixtures), not runtime data. Belongs in the deploy zip. Different from `data/episodes_*.jsonl`.
- `[[spa-deploy-is-manual-swa]]` — every S81/S82/S83 SPA change ends with `cd team-portal && npm run build && swa deploy ./dist --env production` + bundle-hash + string-grep verify against `portal.aigovern.sandboxhub.co`.
- `[[two-origins-spa-vs-engine]]` — `EventSource` from the SPA hits the apex engine `aigovern.sandboxhub.co`, not the portal origin. CORS must include `credentials: include` semantics for the cookie to travel; verify cookie present in DevTools Network on first run.
- `[[pytest-py314-capture-teardown]]` — all `tests/test_agent_runner*` runs use `pytest -s`.

## Open architectural questions (need user signoff at S80 start)
1. **Raw prompt visibility in `scrub_pii` event:** include `raw_preview` when `DEMO_MODE=true`, hide otherwise? Or always emit token-counts only, and surface the raw-vs-scrubbed comparison via a separate `GET /api/agent-runner/runs/{run_id}/redaction` endpoint that's role-gated? (Honest demo vs honest prod tension.)
2. **`local-simulated` "agent" identity:** does the agent picker show `finadvice` only (and the dual-path is just a system-id switch with the same agent), or two pickers ("finadvice" and "local-sim demo")? Recommendation: ONE agent, two systems. Cleaner narrative.
3. **Run history persistence:** every run produces a `run_id`. Persist a row to `agent_runs` table (Postgres) so the audit page can show "last 50 runs" with deep-link to chain replay? Or stateless for now and tackle replay in S84? Recommendation: stateless for the demo MVP; replay is a different mountain.
4. **Eval timing in the chain ticker:** eval today runs ~600ms-2s (5 metrics, some via LLM-as-judge). Is that fast enough for the chain ticker UX, or should `evaluate` be backgrounded and the badge stay "pending" while the run otherwise completes? Recommendation: keep inline — the eval scoreboard is one of the showcase moments.

## What does NOT happen in this arc
Explicitly out of scope for S80–S83:
- S79.6 eval suite UI rewire (S70b carryover) — slipped to S85
- S79.7 eval-failure → finding auto-create — slipped to S85
- S84 RBAC review of `api/memory.py:188` — slipped (still tracked)
- Replay UI / run history page — separate mountain
- Mobile / responsive polish — Tier-4 per S78 scope freeze
- Multi-tenant — locked at single-tenant per ARCHITECTURE.md line 29
