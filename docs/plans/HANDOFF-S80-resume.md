# Resume — AI Assurance Platform · S80 (Agent Runner — backend half of the demo build)

## Where I am
End of S79. Three substantial pieces landed and are **uncommitted in the worktree** (user holds the deploy call):
1. LOCAL dispatcher branch — new `local-simulated` provider + `stream_local_response` generator. Same governance chain runs regardless of destination.
2. `_run_plan` governance — azure-architect's `--plan` tool-use loop now runs under `@policy_gate → @scrub_pii → @guardrails` + `write_episode` at synthesis.
3. `write_episode` caller audit — all 6 prod callers documented; `api/memory.py:188` flagged for S84.

**Major reframe at S79 close (user-driven):** the S79–S86 arc was originally
"showcase rehearsal." User pushed back: *"I need a real agent that I can run
to show the demo and not just onboarded to the team and ciso sites. I should
be able to show how the agent works and showcase everything."* Cataloging AI
systems is not the same as showing one *do something*.

**New arc: S80–S83 = Agent Runner.** Build a real `finadvice` agent + an Agent
Runner page in team-portal that renders the entire governance chain live,
side-by-side with the local-simulated destination, deep-linked to Langfuse +
App Insights. Full spec in `docs/plans/SESSION-80-agent-runner.md`. Read that
doc FIRST.

Live engine SHA last verified: `8f41366` (pre-S79).

## Decisions already made — don't re-litigate
- **The demo agent is new: `finadvice` at `agents/finadvice/agent.py`.** Mirrors azure-architect's shape (SDK decorator chain, tool-use loop, 5-turn cap, write_episode at synthesis) but with finance-flavored tools and mock data. Azure-architect stays — gets registered in the same `agents/_registry.py` so the picker lists both.
- **Invocation surface is a new team-portal page** `/agent-runner`. NOT a CLI demo + side panel; NOT a drawer button trigger. Full dedicated page with prompt input, agent picker, side-by-side dual columns.
- **Chain visibility = all four features the user picked:**
  1. Per-step status (8 steps) with timing + decision
  2. PII redaction preview (raw vs scrubbed with vault_id)
  3. Langfuse + App Insights deep links per run
  4. Side-by-side dual-path (same prompt → Anthropic + local-simulated in parallel columns)
- **Side-by-side mechanic:** two independent `EventSource` connections from the SPA, both hitting the same `POST /api/agent-runner/run` with different `system_id` query params. Backend doesn't know about "dual." Dual is a UI choice.
- **Local-simulated is NOT a real agent.** Demo framing: "same prompt, two destinations, identical governance, different cost profiles." One agent (`finadvice`), two systems.
- **Per-turn re-scrub of tool-result blocks remains S85 scope.** Entry-only scrub for now.
- **S79.6 + S79.7 carryovers (eval UI + auto-finding glue) slip to S85.** They have demo value but are NOT critical path for "watch the agent run."

## S80 concrete deliverables (backend half)
The plan doc has the full file list. Headline:
1. `agents/_registry.py` — `AgentSpec` dataclass + `REGISTRY` dict + `get_agent(agent_id)`.
2. `agents/finadvice/` — new module: `agent.py` (`run_review` with SDK decorator chain + 5-turn tool-use), `prompts.py` (system prompt + token budgets + tool specs), `mocks/portfolios.json` + `market.json` + `profiles.json` (deterministic fixtures with realistic PII fields), `.env.example`.
3. `domain/agent_runner.py` — `stream_agent_run_with_chain_events(agent_id, prompt, system_id, user)` async generator. Emits 10 typed events: `chain.start`, `policy_gate`, `scrub_pii`, `guardrails`, `llm.delta`, `llm.done`, `evaluate`, `memory`, `audit`, `chain.done` (+ `chain.error` on any uncaught).
4. `api/agent_runner.py` — `POST /api/agent-runner/run` (SSE) + `GET /api/agent-runner/agents` (registry JSON).
5. `tests/test_agent_runner_chain_events.py` — asserts event order, every event has `elapsed_ms`, `chain.done` arrives last.
6. `dashboard.py` — eager-import `agents._registry` + `api.agent_runner` per `[[lazy-imports-skip-module-load-bootstrap]]`.
7. ARCHITECTURE.md S80 entry.

**Calibration step before declaring S80 done** (non-negotiable per CLAUDE.md
"Prompt Calibration — Plan For It"):
- Run finadvice from CLI against fixture client `cln-001` with the seed prompt.
- Assert: 3 specific positions named, ≥1 risk constraint cited, ≥2 rebalance actions ranked. If not, tighten `SYSTEM_PROMPT` and re-run.
- Verify all 4 PII fields (`client_name`, `account_number`, `tax_id`, `dob`) appear redacted in the scrubbed prompt visible in the `scrub_pii` event payload.

## Outstanding questions (need user input AT S80 START)
Per the plan doc's "Open architectural questions":
1. **Raw prompt visibility in `scrub_pii` event:** include `raw_preview` only when `DEMO_MODE=true` env? Or never in the SSE — surface raw-vs-scrubbed via a separate role-gated `GET /api/agent-runner/runs/{run_id}/redaction` endpoint? (Honest demo vs honest prod tension.)
2. **Picker UX:** ONE agent (`finadvice`) with two system targets, or TWO pickers (`finadvice` + `local-sim-demo`)? Recommendation: ONE agent, two systems.
3. **Run history persistence:** persist a row per run to `agent_runs` Postgres table (enables a future "replay last 50 runs" page), or stateless MVP and tackle replay later? Recommendation: stateless for now.
4. **Eval inline or backgrounded:** keep eval (~600ms–2s) inline in the chain ticker, or background it and surface a "pending" badge while the rest finishes? Recommendation: inline — eval scoreboard is one of the showcase moments.
5. **Pre-S80 deploy of the S79 worktree changes:** push uncommitted ARCHITECTURE.md + agent.py + assurance_model.py + assurance_providers.py NOW (before starting S80), or bundle with S80 in one larger commit? Recommendation: separate commit + deploy NOW so S80 starts on a clean known-good base; the LOCAL dispatcher needs to be live for the dual-path part of S82 anyway.

## Next concrete action
1. Read `docs/plans/SESSION-80-agent-runner.md` end-to-end. The SSE event protocol (LBD-1 in the doc) is the load-bearing piece — get it right at design time, not later.
2. Resolve the 5 outstanding questions above with one `AskUserQuestion`.
3. Decide commit/deploy strategy for the S79 worktree changes.
4. Start with the agent registry + finadvice mocks (smallest standalone pieces) before the dispatcher rewrite. Build bottom-up: registry → finadvice agent → CLI calibration → `domain/agent_runner.py` → `api/agent_runner.py` → tests.

## Key files to load
- `docs/plans/SESSION-80-agent-runner.md` — full architecture for the 4-session arc
- `agents/azure-architect/agent.py` — the shape `finadvice` will mirror (especially `_run_plan` for the tool-use loop pattern with the S79 decorator chain)
- `agents/azure-architect/prompts.py` — shape `finadvice/prompts.py` will mirror
- `api/assurance_model.py::_stream_live_assurance_response` — the existing dispatcher; `stream_agent_run_with_chain_events` will reuse `select_assurance_provider` + `sanitize_payload_for_provider` + `create_provider_audit_event`
- `domain/assurance_providers.py` — provider catalog (already has `local-simulated` from S79)
- `dashboard.py` (lifespan section) — where to add eager imports
- `team-portal/src/App.tsx` (or equivalent router) — where the future `/agent-runner` route mounts (for S81 — not S80)

## Working rules in effect
All prior rules. Key locks for S80:
- `[[lazy-imports-skip-module-load-bootstrap]]` — eager-import the registry AND `api.agent_runner` in dashboard.py lifespan. Registry imports the agent modules; without this, the picker returns empty.
- `[[anthropic-max-tokens-streaming-threshold]]` — finadvice tool-use turns use streaming context manager (already canonical pattern in `_run_plan`).
- `[[bare-except-hides-broken-integrations]]` — each step in `stream_agent_run_with_chain_events` uses `_log.exception` + emits `chain.error`. Never bare pass.
- `[[grep-all-consumers-before-contract-flip]]` — chain-event protocol is a new public contract; document schema in `docs/agent-runner-sse-protocol.md` at S80 close.
- `[[deploy-zip-overwrites-runtime-data]]` — `agents/finadvice/mocks/*.json` is code (deterministic fixtures), belongs in deploy zip. Different from `data/episodes_*.jsonl`.
- `[[pytest-py314-capture-teardown]]` — `pytest -s` for any test runs.
- `[[smoke-scripts-must-run-live]]` — CLI calibration of finadvice must hit real Anthropic before declaring the agent calibrated, not mocked.
- `[[show-handoff-prompt-inline]]` — at S80 close, render the HANDOFF-S81 file content inline in chat as well.

## Slipped / deferred (still tracked)
- **S79.6 — Eval suite UI → real episodes** (S70b carryover) → S85
- **S79.7 — Eval-failure → finding auto-create glue** (`<0.6→P2`, `<0.4→P1`) → S85
- **S84 — RBAC review of `api/memory.py:188`** → still S84
- **Per-turn tool-result re-scrub in `_run_plan`** → S85 (Tier-3 health)
- **Dual-path live verify with `sys-demo-finadvice-001` + `sys-demo-compliance-001`** — folds into S82 (dual-path columns) instead of being a standalone verify
- **`data/*.jsonl` to `.gitignore`** — quick win, do at S80 entry along with the S79 deploy
