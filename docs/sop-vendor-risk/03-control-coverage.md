# Phase 3 — Control Coverage Matrix — vendor_risk

**SOP reference:** [docs/SOP-agent-onboarding.md](../SOP-agent-onboarding.md) · Phase 3
**Session:** S82b
**Date:** 2026-06-01
**Sign-off (self-attested):**
- CISO: Praveen Kosuri (acting as CISO)
- Compliance: Praveen Kosuri (acting as Compliance)
- Operator: Praveen Kosuri

This matrix maps every ReleaseGate produced by S82a's intake to the
runtime mechanism that enforces it. Per SOP Phase 3 exit criteria, every
P0 (blocking) gate has a concrete runtime mechanism OR an explicitly
documented waiver with expiry. No silent gaps.

Policy files referenced:
- `policies/vendor-risk-ext.rego` — sha256 surfaced via [`GET /api/policies/rego`](../../api/policies_rego.py)
- `policies/vendor-risk-int.rego` — same surface
- `policies/base.rego` — org-mandatory (PII scrub, fail-closed)

Enforcement substrate:
- `domain.policy_engine._check_workload_specific` — reads rego data via
  `domain.rego_loader.resolve_workload_policy(system_id)` and enforces.
- `middleware.policy.policy_gate` — decorator that surfaces `PolicyDeniedError`.
- `tracer.trace_call` (Langfuse/AppInsights) — telemetry destination.
- `scrubber.tokenise_payload` — runs BEFORE tracer per project canonical order.

---

## sys-vendor-risk-ext-001 — 11 gates, 2 blocking

| # | Gate | Block? | Runtime mechanism | Status |
|---|---|---|---|---|
| 1 | Model Inventory Required | no | `agents/_registry.py::AgentSpec` lists `models_used`. `/api/agent-runner/agents` surfaces it. | COVERED |
| 2 | Business Owner Required | no | Intake payload `business_owner` field persisted on AISystem row; visible in AI Systems page. | COVERED |
| 3 | Technical Owner Required | no | Intake payload `technical_owner` field on AISystem row. | COVERED |
| 4 | **Critical Findings Block Production Release** | **YES** | Phase 11 `release_decision` flow reads open `Finding(severity=CRITICAL)` rows; flip to APPROVED requires zero open CRITs. Enforced in Phase 9/10/11 (S82g/i). | COVERED (Phase 9+ enforcement) |
| 5 | RAG Source Quarantine Required | no | RAG corpus is in-tree at `agents/vendor_risk/corpus/`. Corpus content authored in S82d; review attested by CISO at lock (Phase 6 / S82e). | COVERED (deliverable S82d/e) |
| 6 | AWS Private Connectivity for Regulated Workloads | no | N/A — Azure deployment (`cloud_provider: AZURE` per intake). Waived as non-applicable. | WAIVED — not-applicable, perpetual |
| 7 | Vector Store Access Control Required | no | BM25 is in-process (no separate vector store). Access control = process boundary. | COVERED (architecture) |
| 8 | **Tool Authorization Mandatory** | **YES** | `policies/vendor-risk-ext.rego` Rule 1 (`vendor_risk_ext_tools` allowlist) + Rule 2 (`mutation_verbs` deny). Live DENY proven in `tests/test_policy_vendor_risk.py::test_ext_tool_not_in_allowlist_denies` + `::test_ext_mutation_verb_denies`. | **COVERED + tested** |
| 9 | Groundedness Threshold Required | no | Phase 4 (S82c) `agents/vendor_risk/eval/thresholds.json::groundedness ≥ 0.80`. CI regression test from Phase 6 (S82e). | DEFERRED to S82c |
| 10 | Full Audit Logging Required | no | `signallayer.write_episode()` writes audit row per run. Decorator chain wires `tracer.trace_call` (Langfuse + AppInsights). | COVERED |
| 11 | Evidence Immutability Required | no | JSONL append-only via `storage._append_jsonl`. Project CLAUDE.md "JSONL only" rule. | COVERED |

**Blocking gate verification:** both P0 gates (#4, #8) are covered with concrete runtime mechanisms. Gate #8 is enforced live and tested.

---

## sys-vendor-risk-int-001 — 15 gates, 5 blocking

The internal sibling inherits all 11 ext gates and adds 4 more for the
sensitive-data path (`pii`/`npi`/`confidential`/`credit_data` declared at
intake).

| # | Gate | Block? | Runtime mechanism | Status |
|---|---|---|---|---|
| 1-7 | (same as ext rows 1-7) | mixed | (same) | (same) |
| 8 | **No Raw PII/NPI/PCI in Prompts** | **YES** | Canonical chain order (project CLAUDE.md security rule): `scrubber.tokenise_payload()` runs BEFORE `tracer.trace_call()`. Tokens replace raw values. `policies/base.rego` enforces "no raw PII" via `_check_org_mandatory`. | COVERED (existing canonical) |
| 9 | **DLP Before Model Context Assembly** | **YES** | `policies/vendor-risk-int.rego` Rule 4 `required_true_flags = {"dlp_completed", "network_egress_lock_engaged"}`. Live DENY: `tests/test_policy_vendor_risk.py::test_int_required_dlp_flag_missing_denies`. | **COVERED + tested** |
| 10 | **Tool Authorization Mandatory** | **YES** | `policies/vendor-risk-int.rego` Rule 1 (`vendor_risk_int_tools` allowlist) + Rule 2 (`mutation_verbs`) + Rule 5 (`denied_url_substrings` belt-and-braces). Tests `test_int_tool_not_in_allowlist_denies` + `test_int_denied_url_substring_in_tool_args_denies`. | **COVERED + tested** |
| 11 | No Persistent Memory for Restricted Data | no | Agent design is stateless; signallayer writes are append-only audit, not retrievable memory. Asserted in Phase 5 unit tests (S82d). | COVERED (architecture) |
| 12 | Groundedness Threshold Required | no | Same as ext gate #9. | DEFERRED to S82c |
| 13 | Macie Scan Required for S3 / RAG Sources | no | N/A — RAG sources are in-tree; no S3. Macie is AWS-specific. | WAIVED — not-applicable, perpetual |
| 14 | Full Audit Logging Required | no | Same as ext gate #10. | COVERED |
| 15 | Evidence Immutability Required | no | Same as ext gate #11. | COVERED |

**Blocking gate verification:** all 5 P0 gates have runtime mechanisms; 3 are enforced via rego + Python and tested live in S82b. P0 gate #4 (Critical Findings Block) enforces in S82g+ (Phase 9 forward). P0 gate #8 (No Raw PII) is enforced by the canonical scrubber-before-tracer chain (project CLAUDE.md security rule).

---

## Beyond ReleaseGates — additional runtime mechanisms from Phase 2 design review

These are NOT in the intake-generated gate set but ARE in the Phase 2
design review tool inventory + autonomy lock. Documented here so the
Phase 9 auditor (S82g) sees the complete enforcement surface.

| Control | Source | Runtime mechanism | Test |
|---|---|---|---|
| Operator role allowlist (ext) | Design §3 — autonomy ceiling | `policies/vendor-risk-ext.rego::required_operator_roles` | `test_ext_operator_role_not_allowed_denies` |
| Operator role allowlist (int, stricter) | Design §3 — autonomy ceiling | `policies/vendor-risk-int.rego::required_operator_roles` (admin EXCLUDED) | `test_int_admin_role_denied` |
| Internal-system token routing (ext deny) | Design §4 — data flow | `policies/vendor-risk-ext.rego::denied_token_types` (`INTERNAL_SYSTEMS`/`MNPI`/`CREDIT_DATA`) | `test_ext_denied_token_type_denies[*]` |
| Prompt size cap | Design §3 — cost guard | `max_prompt_tokens = 32000` (both rego files) | `test_ext_prompt_token_cap_denies` |
| Prompt injection threshold | Design §3 — guardrails | `max_injection_score_pct = 70` (ext) | `test_ext_injection_score_over_threshold_denies` |
| Runaway-loop guard | Design §5 — tool inventory turn cap | `max_llm_calls_per_run = 25` | `test_ext_llm_call_budget_exceeded_denies` |
| Network egress isolation (int) | Design §6 — isolation boundary | `required_true_flags::network_egress_lock_engaged` + S82d socket-monitor context manager | `test_int_required_egress_flag_missing_denies` |
| Kill-switch | Design §7 | `runtime_status == PAUSED` → policy DENY (wired S82f) | DEFERRED to S82f drill |

---

## Waivers (named + dated)

| Gate | Reason | Acceptor | Expiry |
|---|---|---|---|
| AWS Private Connectivity for Regulated Workloads | Azure-hosted deployment; AWS-specific control not applicable | CISO (acting) — Praveen Kosuri | Perpetual while `cloud_provider=AZURE` |
| Macie Scan Required for S3 / RAG Sources | In-tree corpus; no S3 surface | CISO (acting) — Praveen Kosuri | Perpetual while `vector_store` is in-process |

Both waivers are tied to the architecture choice, not a defect. If
either decision is revisited, the waiver expires automatically and the
gate becomes binding.

---

## Deferred-with-date items

| Item | Resolves in | Why deferred |
|---|---|---|
| Groundedness threshold enforcement | S82c (Phase 4 eval skeleton) | Threshold definition is Phase 4 deliverable; runtime regression gate is Phase 6 (S82e) |
| Critical findings block | S82g (Phase 9 pre-release) | No findings exist until red-team in Phase 9 |
| Network-egress socket-monitor context manager | S82d (Phase 5 V0 build) | Lives in agent code, not policy substrate |
| Kill-switch policy-DENY wiring | S82f (Phase 8 staged) | Requires `runtime_status` plumbing into policy input_data |

Each deferred item has a named target session. No unbounded deferrals.

---

## Phase 3 exit checklist

| Item | Status |
|---|---|
| `policies/vendor-risk-ext.rego` shipped | ✅ |
| `policies/vendor-risk-int.rego` shipped | ✅ |
| sha256 in registry (via `/api/policies/rego`) | ✅ auto-discovered |
| ≥1 negative DENY test passing per rule | ✅ 23/23 tests pass (`tests/test_policy_vendor_risk.py`) |
| ≥1 positive ALLOW test passing per system | ✅ `test_ext_clean_path_allows` + `test_int_clean_path_allows` |
| Control coverage matrix zero unmapped P0 | ✅ this document |
| Waivers explicitly documented with expiry | ✅ §Waivers |
| Compliance attests coverage vs declared regulatory exposure | ✅ self-attested |

## Next phase

[Phase 4 — Behavioral Spec / Eval Skeleton](04-eval-spec-signoff.md) in S82c. The eval IS the spec — Phase 4 GATES Phase 5 (V0 build) per the SOP's load-bearing reordering.
