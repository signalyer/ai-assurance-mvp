# Agent Runner SSE Event Protocol

Locked at **S80** (`docs/plans/SESSION-80-agent-runner.md` LBD-1). This is the
public contract between `domain.agent_runner.stream_agent_run_with_chain_events`,
the SSE endpoint `POST /api/agent-runner/run`, and any client consuming the
stream (today: the team-portal `/agent-runner` page landing in S81).

Before changing the shape of any event below, grep every consumer per
`[[grep-all-consumers-before-contract-flip]]`. The two production consumers as
of S80 are this dispatcher itself and the test file
`tests/test_agent_runner_chain_events.py`; S81 adds the SPA.

## Transport

| Property | Value |
|---|---|
| Endpoint | `POST /api/agent-runner/run` |
| Content-Type | `text/event-stream` (via `sse_starlette.EventSourceResponse`) |
| Auth | session cookie OR `X-Role` header (see `_RUNNER_ROLES` in `api/agent_runner.py`) |
| Termination | `chain.done` is **always** the final event. `chain.error` is followed by `chain.done` — never by anything else. |
| Frame format | Each SSE frame is `event: <name>\ndata: <json>\n\n` where `<json>` is the full event dict (also includes `event` for client-side dispatch convenience). |

## Uniform keys (every event)

| Key | Type | Notes |
|---|---|---|
| `event` | string | Step name (the SSE `event:` field too). |
| `run_id` | string | `run-XXXXXXXXXXXX` — same for every event in one stream. |
| `elapsed_ms` | number | Either per-step time (most events) or total time (`chain.done`). |

## Event types — schemas

### `chain.start`
First event. Emitted once after the agent spec resolves.
```jsonc
{
  "event": "chain.start",
  "run_id": "run-3a2f1c7b9d4e",
  "agent_id": "finadvice",
  "agent_name": "Financial Advisor Risk Reviewer",
  "provider_id": "anthropic",       // S82: flips to "local-simulated" via system_id routing
  "system_id": "sys-demo-finadvice-001",
  "user": "operator@signallayer.ai",
  "started_at": "2026-06-01T17:42:11.483Z",
  "elapsed_ms": 0
}
```

### `policy_gate`
After `domain.policy_engine.evaluate`. If `decision` is DENY the chain
short-circuits — no more events except `chain.done` with `outcome="denied"`.
```jsonc
{
  "event": "policy_gate",
  "run_id": "run-3a2f1c7b9d4e",
  "decision": "ALLOW",              // ALLOW | DENY | REVIEW
  "rule": "all_local_checks_pass",
  "reason": "string",
  "elapsed_ms": 1.9
}
```

### `scrub_pii`
After `scrubber.tokenise_payload`. `raw_preview` ONLY included when
`DEMO_MODE=true` (env or `demo_mode=true` request kwarg) — never on a real
prod stream.
```jsonc
{
  "event": "scrub_pii",
  "run_id": "run-3a2f1c7b9d4e",
  "scrubber_enabled": true,
  "redacted_count": 0,              // count of [TYPE_NNN] tokens
  "redacted_field_types": [],       // sorted distinct token type labels
  "vault_id": "finadvice_nopii_abcd1234ef56",
  "scrubbed_preview": "first 200 chars of the scrubbed prompt",
  "raw_preview": "first 200 chars of the raw prompt",   // DEMO_MODE only
  "elapsed_ms": 0.4
}
```

### `guardrails`
After `middleware.guardrails.GuardrailsMiddleware.check_input`. If
`passed: false` the chain short-circuits with `outcome="guardrail_block"`.
```jsonc
{
  "event": "guardrails",
  "run_id": "run-3a2f1c7b9d4e",
  "passed": true,
  "violations": [],
  "injection_score": 0.02,          // null when injection adapter not loaded
  "topic_in_scope": true,           // null when NeMo topic enforcement off
  "safety_pass": true,              // null when LlamaGuard adapter off
  "elapsed_ms": 0.4
}
```

### `llm.delta`
Zero or more events. One per text chunk yielded by the agent's
`anthropic.messages.stream().text_stream`. Carries `text` + `turn` so
consumers can render per-turn streaming UIs.
```jsonc
{
  "event": "llm.delta",
  "run_id": "run-3a2f1c7b9d4e",
  "text": "## Top Positions\n\n",
  "turn": 2,
  "elapsed_ms": 4127.3              // elapsed since llm step start
}
```

### `llm.done`
Terminal LLM event. Token counts come from the agent's observed Anthropic
usage records summed across all tool-use turns.
```jsonc
{
  "event": "llm.done",
  "run_id": "run-3a2f1c7b9d4e",
  "model": "claude-sonnet-4-6",
  "input_tokens": 6218,
  "output_tokens": 1254,
  "delta_count": 55,                // dispatcher's own count of yielded llm.delta events
  "stop_reason": "end_turn",
  "turns": 3,
  "elapsed_ms": 28491.2
}
```

### `evaluate`
S80 emits a placeholder that mirrors the agent's INTERNAL eval (which today is
`{}` for finadvice). S85 wires real per-run eval here. Contract shape is
stable; only values change.
```jsonc
{
  "event": "evaluate",
  "run_id": "run-3a2f1c7b9d4e",
  "scores": {},                     // metric_name → {score, passed, skipped, details}
  "avg_score": null,
  "scored_metric_count": 0,
  "deferred_to_s85": true,
  "elapsed_ms": 0.1
}
```

### `memory`
Mirrors `signallayer.write_episode` outcome from the agent's return dict.
The agent persists the episode itself; this event is a join-key surface.
```jsonc
{
  "event": "memory",
  "run_id": "run-3a2f1c7b9d4e",
  "episode_id": "464770ad-344c-42ef-8313-3842c015b01d",
  "outcome": "success",             // success | failure | review
  "workload_id": "sys-demo-finadvice-001",
  "elapsed_ms": 0
}
```

### `audit`
S80 synthesizes `audit_id` from `run_id` so SSE consumers always have a
stable join key. S82 wires `domain.assurance_providers.create_provider_audit_event`
so the audit row actually lands. S83 fills `langfuse_url` + `appinsights_url`
from env-driven URL builders.
```jsonc
{
  "event": "audit",
  "run_id": "run-3a2f1c7b9d4e",
  "audit_id": "aud-af363b3f5fc6",
  "decision": "LIVE",               // LIVE | SIMULATED | BLOCKED
  "trace_id": "",                   // S82 fills from real Langfuse trace_id
  "langfuse_url": null,             // S83
  "appinsights_url": null,          // S83
  "elapsed_ms": 0
}
```

### `chain.done`
Terminal. Always last. Even after `chain.error`.
```jsonc
{
  "event": "chain.done",
  "run_id": "run-3a2f1c7b9d4e",
  "outcome": "success",             // success | failure | review | denied | guardrail_block | error
  "episode_id": "464770ad-...",     // empty string when no episode written
  "audit_id": "aud-af363b3f5fc6",   // empty string when no audit row
  "elapsed_ms": 28739.8,
  "total_elapsed_ms": 28739.8,      // alias of elapsed_ms for semantic clarity
  "terminal_reason": null           // present on short-circuit paths only
}
```

### `chain.error`
Emitted on ANY uncaught step exception. The chain ALWAYS continues to
`chain.done` after one of these — clients can rely on `chain.done` as the
terminal signal regardless of error.
```jsonc
{
  "event": "chain.error",
  "run_id": "run-3a2f1c7b9d4e",
  "step": "llm",                    // resolve | policy_gate | scrub_pii | guardrails | llm | evaluate | sse
  "error_type": "RuntimeError",
  "message": "boom from inner",
  "elapsed_ms": 1247.0
}
```

## Order

Happy path:
```
chain.start → policy_gate → scrub_pii → guardrails → [llm.delta]* → llm.done → evaluate → memory → audit → chain.done
```

Short-circuit paths (each ends at `chain.done` with the named `outcome`):
- Policy DENY: `chain.start → policy_gate → chain.done(outcome="denied", terminal_reason="policy_deny:<rule>")`
- Guardrail violation: `chain.start → policy_gate → scrub_pii → guardrails → chain.done(outcome="guardrail_block")`
- Step exception: `... → chain.error(step=<name>) → chain.done(outcome="error")`
- Unknown agent_id: `chain.error(step="resolve") → chain.done(outcome="error")` (no `chain.start`)

## Adding a new event type

1. Add the schema here under "Event types — schemas".
2. Update the order diagram above.
3. Update `tests/test_agent_runner_chain_events.py`:
   - Expected event order list in `test_event_order_happy_path`.
   - Per-event payload-shape test in the style of `test_scrub_pii_payload_shape`.
4. Update the team-portal `/agent-runner` page (S81+) — SPA renders one badge per event type.
5. Bump this doc's "Locked at" header with the session number.

Never add an event type without updating all five surfaces.
