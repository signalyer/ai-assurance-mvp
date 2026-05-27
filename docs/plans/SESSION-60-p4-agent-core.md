# SESSION-60 — P4 agent core (azure-architect)

**Status entering S60:** P3 CLOSED in S59 at surface-acceptance granularity. Three platform fixes shipped (F-019 export 401, F-020 display %, route prefix from S57 #1), three carry-forwards logged (F-021 azure-architect data, F-022 portfolio rollup PDF, F-023 evidence-add UI). EU AI Act PDF Pack generated for ai-sys-002 (sha256 `86c9382f…f466c6`). Full P3 EXIT GATE entry in [POC-RETROSPECTIVE.md](../../agents/azure-architect/POC-RETROSPECTIVE.md).

S60 builds the P4 agent core. Reference: [docs/plans/AZURE-ARCHITECT-POC.md §P4](AZURE-ARCHITECT-POC.md).

---

## Locked decisions (from S59 session start — do NOT relitigate)

- **Turns cap:** 5
- **Intermediate state:** `data/plans.jsonl` via `storage._append_jsonl()` (per CLAUDE.md storage rule)
- **Synthesis landing:** ONE JSONL row per final synthesis to `eval/dataset.jsonl` — unblocks S58 directly
- **Model default:** Sonnet 4.6 (`claude-sonnet-4-6`) — tool calls don't need Opus reasoning per turn; cost compounds
- **Router prefix rule (S57 #1, S59 reaffirmed):** Any new router uses `prefix="/api"` NOT `"/api/v1"` — alias middleware handles v1 rewrite
- **Policy gate rule:** Every new tool added to the agent gets a matching rule in `policies/azure-architect.rego` AND a sha256 visible in CISO Console "Active enforced policies" panel (F-018 contract)

---

## STEP 1 — Tool layer scaffold (~45-60 min)

**Goal:** minimum viable Azure inspection tool wrapped with the SignalLayer decorator chain.

**Concrete first tool:** `list_resource_groups()` — smallest real verb, read-only, no destructive blast radius.

**File placement (per CLAUDE.md):**
- New module: `agents/azure-architect/tools/azure_inspect.py`
- Decorator import: `from signallayer import tool_call` (existing) + `from middleware.policy_gate import policy_gate` (existing — used in agent code paths)
- Azure SDK: `azure.mgmt.resource.ResourceManagementClient` (subscription-scoped)

**Acceptance:**
- `python -c "from agents.azure_architect.tools.azure_inspect import list_resource_groups; print(list_resource_groups())"` returns a list of dicts.
- The call goes through scrubber → tracer → policy_gate in that order (per CLAUDE.md security rule).
- New rego rule in `policies/azure-architect.rego` for action `"azure.list_resource_groups"`; sha256 appears in CISO Console panel.

---

## STEP 2 — Orchestration loop (~60-90 min)

**Pattern:** Anthropic `tool_use` API → 5-turn cap → integrates each tool result → emits synthesis.

**File:** `agents/azure-architect/agent.py` (extend existing scaffold)

**Loop sketch:**
```
plans_path = "data/plans.jsonl"
synthesis_path = "agents/azure-architect/eval/dataset.jsonl"
TURN_CAP = 5

for turn in range(TURN_CAP):
    response = client.messages.create(
        model="claude-sonnet-4-6",
        tools=[...tool_specs],
        messages=conversation,
    )
    storage._append_jsonl(plans_path, {
        "run_id": ..., "turn": turn, "stop_reason": response.stop_reason,
        "tool_calls": [...], "elapsed_ms": ...,
    })
    if response.stop_reason != "tool_use":
        break
    for tu in response.content:
        if tu.type == "tool_use":
            result = dispatch(tu.name, tu.input)  # policy_gate wraps dispatch
            conversation.append(... tool_result ...)

# Final synthesis row
storage._append_jsonl(synthesis_path, {
    "input": initial_plan_request,
    "output": final_text,
    "context": [tool_call_summaries],
    "metadata": {"run_id": ..., "turns": turn+1, "cost_usd": ...},
})
```

**Acceptance:**
- `python agents/azure-architect/agent.py --plan "audit my prod subscription"` completes within 5 turns.
- Each turn appears as a row in `data/plans.jsonl`.
- One row appears in `agents/azure-architect/eval/dataset.jsonl` with the four canonical fields (input, output, context, metadata).
- Each tool call shows up as its own `trace_id` in `data/traces.jsonl` (existing tracer).
- Cost per `--plan` run under $0.50.

---

## STEP 3 — Per-tool tracing + policy enforcement verification (~30 min)

**Acceptance:**
- Manually call the agent with a `--plan` that should trigger `list_resource_groups`. Confirm:
  - `data/traces.jsonl` has the trace with scrubbed prompt (never raw).
  - `policies/azure-architect.rego` allowlist enforced — try injecting a fake `delete_resource_group` tool call (test-only) and confirm it `PolicyDenied`.
  - CISO Console "Active enforced policies" panel shows the new rule with current sha256.

---

## STEP 4 (spill to S61) — Mermaid synthesis + per-tool eval

Plan §P4 items 3+4. Defer to S61 unless S60 finishes early.

---

## Working rules in effect

- All P4 commits expect `docs/openapi-v1.json` drift if any API changes; regenerate via `python scripts/export_openapi.py` and commit in same push (S56 #3 pattern).
- Any new trace/eval source goes through JSONL fallback path (S56 #1) — no silent-drop integrations.
- Any new API endpoint: `prefix="/api"` NOT `/api/v1` (S57 #1 / [[auth-shadows-404]]).
- Storage: `storage._append_jsonl()` only — no direct file writes outside that path (CLAUDE.md).
- Security order: `scrubber.tokenise_payload()` BEFORE `tracer.trace_call()` — Langfuse never sees raw_prompt.
- Policy engine errors → default DENY (CLAUDE.md).

## Compound rules in memory (relevant)

- [[auth-shadows-404]] — router prefix discipline
- [[grep-all-consumers-before-contract-flip]] — sweep before flipping any contract
- [[raw-fetch-drifts-from-shared-client]] — never bypass shared API client in SPA code
- [[ui-promise-audit-owed]] — three F-018/F-022/F-023 same-shape findings; an audit pass is overdue. Don't add a fourth.
- [[bare-except-hides-broken-integrations]] — log + surface, never swallow
- [[two-origins-spa-vs-engine]] — check response BODY not status
- [[wizard-mounts-create-resources]] — list-then-create, never POST on mount
- [[run-commands-dont-defer]] — execute, don't present a menu
- [[bash-cwd-persistence]] — absolute paths or fresh `cd` per logical step
