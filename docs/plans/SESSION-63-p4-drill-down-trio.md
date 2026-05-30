# SESSION 63 — P4 drill-down trio complete (`get_resource_metadata` live)

**Date:** 2026-05-29
**Branch:** main
**Tip going in:** `5cd80ae` (S62 close)
**Scope:** Implement `get_resource_metadata` body, complete the drill-down trio (list RGs → list resources → get one), live-validate multi-turn fan-out with three parallel drill-downs, fix `plan_turn` ceiling exposed by deeper synthesis.

## What changed

| File | Change |
|---|---|
| [agents/azure-architect/tools/arm_read.py](../../agents/azure-architect/tools/arm_read.py) | Added `_parse_resource_id()` parser (validates ARM shape, returns sub/rg/ns/type_path; raises ValueError on malformed). Filled `get_resource_metadata` body: parse → `providers.get(namespace)` for newest stable api_version (filter preview tags) → `resources.get_by_id`. `@signallayer.policy_gate(action="tool_invoke")`, `asyncio.to_thread`. |
| [agents/azure-architect/prompts.py](../../agents/azure-architect/prompts.py) | Added 3rd `PLAN_TOOL_SPECS` entry for `get_resource_metadata` (input_schema: `resource_id` required). Bumped `TOKEN_BUDGETS["plan_turn"]` 4096 → 8192. |
| [agents/azure-architect/agent.py](../../agents/azure-architect/agent.py) | `_build_tool_dispatch` adds `_get_metadata` async dispatch with missing-`resource_id` ValueError mirror of `_list_resources`. |
| [ARCHITECTURE.md](../../ARCHITECTURE.md) | `/verify` rego positive test pinned from `list_resource_groups` to `get_resource_metadata` so the test proves the *current* allowlist surface. |
| [agents/azure-architect/POC-RETROSPECTIVE.md](../../agents/azure-architect/POC-RETROSPECTIVE.md) | Added "S63 P4 STEP 1 — drill-down trio complete" section. |

## Decisions locked

- **Drill-down trio is the canonical audit pattern.** `list_resource_groups → list_resources_in_group → get_resource_metadata` is the minimum-viable Azure read surface. Adding tools beyond this should require a concrete review pattern the trio can't satisfy.
- **api_version discovery is per-call.** ARM requires explicit api_version on `get_by_id`; no "give me the latest" mode exists because the polymorphic `properties` blob is api-version-pinned. Two-step discovery (`providers.get(namespace)` → newest stable, skip preview) is acceptable cost for an audit tool.
- **`plan_turn` 8192 is the synthesis-turn budget.** Drill-down depth scales synthesis volume; 4096 was sufficient for 1-tool fan-out, insufficient for 3-tool. New rule: every allowlist addition re-checks `plan_turn` against worst-case (turn-cap × max-parallel-calls × per-result prose).
- **Verify block convention:** rego positive test rotates to the newest allowlist entry. Proves the *current* surface, not the original one.
- **Rego allowlist edit FIRST discipline still applies** even when the entry is pre-reserved (S60 scaffolded all 8 entries up-front). Re-run the positive+negative replay anyway — [[rego-files-were-decorative]] guards against the "file looks right but isn't enforced" class.

## Live run — `plan-867aa0931a0a`

| Turn | Stop | In | Out | Tools |
|---|---|---|---|---|
| 0 | tool_use | 1510 | 160 | 1× `list_resources_in_group` (skipped `list_resource_groups` — operator named RG) |
| 1 | tool_use | 5057 | 416 | **3× parallel `get_resource_metadata`** (KV / App Service / PostgreSQL) |
| 2 | **max_tokens@4096** | 10726 | 4096 | 0 (synthesis truncated mid-verdict-table → S63 bumped to 8192) |

**Real CRITICAL findings produced** (Sonnet 4.6 against SignalLayerDev):
- Key Vault purge protection disabled
- PostgreSQL public network access enabled, no private endpoint, Entra ID auth off, geo-redundant backup off
- App Service `minTlsVersion: null`, no health probe, SCM endpoint unprotected
- Prod-named Log Analytics + App Insights co-located inside `rg-aigovern-dev` (RBAC blast-radius / chargeback confusion)

Token cost ≈ 17K input + 4.7K output ≈ $0.07. Sonnet economics still healthy for routine subscription audits.

## Verification

- ✅ Baseline rego DENY (`delete_resource_group`) + ALLOW (`get_resource_metadata`) — PASS
- ✅ `_parse_resource_id` happy path + nested `sites/slots` + malformed — PASS
- ✅ `PLAN_TOOL_SPECS` length = 3, tool 3 = `get_resource_metadata` — PASS
- ✅ Post-impl rego replay — PASS
- ✅ Live `--plan` trio run — turn shape, parallel fan-out, synthesis quality all correct

## Carry-forward to S64

- **STEP 4 spillover** (Mermaid + per-tool eval rubric) — still deferred since S60.
- **4 read-surface stubs remain:** `list_subscriptions`, `list_role_assignments`, `get_network_topology`, plus `get_storage_account_properties` / `get_key_vault_properties`. Property-bag tools are partly redundant now that `get_resource_metadata` returns full polymorphic `properties` — reassess scope before implementing.
- **UI-promise audit overdue (4×)** — [[ui-promise-audit-owed]]. Highest-leverage prevention work remaining.
- **F-021** — framework mapping data for `ai-sys-bae72e75`.

## Outstanding questions

None for S63. S64 entry choice is the next decision.
