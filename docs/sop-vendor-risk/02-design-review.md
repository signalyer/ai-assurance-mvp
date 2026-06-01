# Phase 2 — Design Review — vendor_risk

**SOP reference:** [docs/SOP-agent-onboarding.md](../SOP-agent-onboarding.md) · Phase 2
**Session:** S82b
**Date:** 2026-06-01
**Status:** SIGNED (self-attested)
**Reviewers (self-attested):**
- Architect: Praveen Kosuri (acting as Architect)
- CISO / Security: Praveen Kosuri (acting as CISO)
- MRM: Praveen Kosuri (acting as MRM)

This review covers BOTH AI systems registered in S82a:
- `sys-vendor-risk-ext-001` — external cloud LLM path
- `sys-vendor-risk-int-001` — internal-only deterministic path

The agent code (`agents/vendor_risk/agent.py`, Phase 5) is identical for
both. The two systems differ in (a) data classification accepted at
intake, (b) LLM step (Anthropic vs local-deterministic), and (c) network
egress allowance. Governance is per-deployment, not per-agent — that
asymmetry is the demo argument.

---

## 1. Use case recap (Phase 0 anchor)

Reduce mean cycle time from vendor-package-received to structured risk
assessment from 5 business days to 4 hours, with consistent rubric
application. Output is ADVISORY only — feeds a human TPRM analyst's
contract recommendation; never directly executes a procurement decision.

Regulatory exposure (per intake): DORA, NYDFS Part 500, GDPR Art. 28,
FFIEC Appendix J. SOX + GLBA + FFIEC + GDPR captured in
[`01-intake-receipt-{ext,int}.md`](.).

---

## 2. Model / provider choice

| System | Model | Provider | Why |
|---|---|---|---|
| `sys-vendor-risk-ext-001` | `claude-sonnet-4-6` | Anthropic direct API | Synthesis reasoning over vendor PDFs + corpus citations. Sonnet-4-6 is the project default for non-trivial reasoning per global CLAUDE.md. Opus would over-spend (~5×); Haiku would under-perform on conflict detection in DPAs. |
| `sys-vendor-risk-int-001` | `local-deterministic-v1` | In-process (BM25 + template composition) | Internal data is the *reason* this path exists. Cloud LLM call would defeat the purpose. Deterministic answer assembly is acceptable for advisory output because the TPRM analyst is the decision-maker. |

**Pinned versions:** model IDs are constants in `agents/vendor_risk/prompts.py` (authored in S82d). Roll-forward requires eval re-baseline per global CLAUDE.md.

**Rejected alternatives:**
- `claude-opus-4-7` for external: rejected on cost (vendor risk is high-volume; opus 5× cost is not justified for advisory output).
- Bedrock-routed Claude for external: rejected because direct API is already wired for finadvice; introducing Bedrock here adds IAM surface without governance value.
- Off-the-shelf TPRM-SaaS LLM (e.g. UpGuard agentic): rejected — SaaS guardrails violate project CLAUDE.md "no external prompt routing" rule.

---

## 3. Autonomy ceiling — LOCKED

**Both systems: `ADVISORY` with HITL_ESCALATION tool.**

| Dimension | Value |
|---|---|
| `autonomy_level` (intake) | `recommend` |
| `human_approval_required` | true |
| `can_trigger_customer_communication` | false |
| Side-effect tools | exactly ONE: `escalate_to_human` |
| HITL on side effect | enforced at decorator + policy layer |

The agent never executes a contract decision, never sends external
communication, never writes to vendor-of-record systems. The only
side-effect tool (`escalate_to_human`) creates a Finding row + flips
the assessment to `requires_human_review` — itself a HITL surface.

**Autonomy ceiling lock means:** raising this ceiling requires a new
Phase 2 review, not just a code change. The lock is documented here so
the diff is auditable.

---

## 4. Data-flow diagram (both systems share the structure; LLM step differs)

```
Operator (TPRM analyst / CISO / admin)
        │
        │ POST /api/agent-runner/run
        │ { agent: "vendor_risk", system_id, vendor_package_ref }
        ▼
┌─────────────────────────────────────────────────────────────┐
│ DISPATCHER (api/agent_runner.py)                            │
│   workload_id := system_id                                  │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│ policy_gate(action="agent_run")  ← @decorator (outer-most)  │
│   evaluate(system_id, action, input_data)                   │
│   reads policies/vendor-risk-{ext,int}.rego                 │
│   DENY → PolicyDeniedError → chain.done short-circuit       │
└─────────────────────────────────────────────────────────────┘
        │ ALLOW
        ▼
┌─────────────────────────────────────────────────────────────┐
│ scrubber.tokenise_payload()  ← BEFORE tracer.trace_call()   │
│   pii → [PERSON_*], [EMAIL_*]                               │
│   internal sys refs → [INTERNAL_SYSTEMS_*]                  │
│   mnpi → [MNPI_*]                                            │
│   returns scrubbed_prompt + redacted_token_types[]          │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│ guardrails  (max prompt size, injection score)              │
│   computes prompt_token_count + prompt_injection_score      │
│   feeds policy_gate inputs on re-evaluation (LLM step)      │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│ tracer.trace_call() with scrubbed_prompt                    │
│   Langfuse (ext only) / AppInsights (both)                  │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│ RAG retrieval (BM25 over agents/vendor_risk/corpus/)        │
│   tprm-policy + regulatory + prior-assessments              │
│   + subprocessor-risk-db.json                               │
│   + internal-systems-inventory.json   (INT ONLY)            │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│ LLM step                                                    │
│   EXT: Anthropic claude-sonnet-4-6 (streaming, since        │
│        max_tokens > 2000)                                   │
│   INT: local template composition                           │
│        + network_egress_lock context manager (asserts no    │
│          outbound socket opens)                             │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│ Tool loop (≤5 turns)                                        │
│   6 tools: search_tprm_corpus, lookup_subprocessor_risk,    │
│   parse_vendor_document, check_regulatory_requirements,     │
│   compare_to_baseline, escalate_to_human                    │
│   Every tool_invoke re-enters policy_gate(action=tool_invoke)│
└─────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│ signallayer.write_episode()  → audit chain row              │
│   { run_id, system_id, agent, eval_scores, citations,       │
│     escalation_triggered, langfuse_url, appinsights_url }   │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
   Structured output back to operator (SPA chain ticker)
```

**Where each data class is redacted:**

| Source field | Detection point | Token shape | Visible to LLM |
|---|---|---|---|
| PII (email, name, phone) | scrubber (pre-tracer) | `[EMAIL_001]`, `[PERSON_001]` | tokens only |
| SSN / NPI | scrubber | `[US_SSN_001]` | tokens only |
| Internal system names | scrubber (token type INTERNAL_SYSTEMS) | `[INTERNAL_SYSTEMS_001]` | EXT: blocked at policy; INT: tokens only |
| MNPI markers | scrubber (token type MNPI) | `[MNPI_001]` | EXT: blocked at policy; INT: tokens only |
| Credit data | scrubber | `[CREDIT_*]` | EXT: blocked at policy; INT: tokens only |

The asymmetry — EXT blocks vs INT allows tokens — is the
per-deployment governance argument and is enforced by
`policies/vendor-risk-{ext,int}.rego`.

---

## 5. Tool inventory

| Tool | side_effect | authorization_required | rate_limit | Notes |
|---|---|---|---|---|
| `search_tprm_corpus` | none | none | 50/run | BM25 over local corpus, read-only |
| `lookup_subprocessor_risk` | none | none | 20/run | Local JSON lookup |
| `parse_vendor_document` | none | none | 10/run | Local PDF/text parse |
| `check_regulatory_requirements` | none | none | 20/run | Local regulatory mapping |
| `compare_to_baseline` | none | none | 20/run | Compares to prior assessments in corpus |
| `escalate_to_human` | **yes — creates Finding + flips assessment** | **HITL required** | 3/run | Only side-effect tool; idempotent on (system_id, vendor_ref) |

**Total tool-loop turn cap:** 5 turns. Enforced in `agents/vendor_risk/agent.py` (Phase 5). Caught at the policy layer via `max_llm_calls_per_run` regression bound (Phase 3 rego data).

---

## 6. Isolation boundary

| System | Subscription | Network egress | Secrets surface |
|---|---|---|---|
| `sys-vendor-risk-ext-001` | SignalLayerDev | Anthropic API only (api.anthropic.com:443) | `ANTHROPIC_API_KEY` (Key Vault in prod; env var in demo per project CLAUDE.md) |
| `sys-vendor-risk-int-001` | SignalLayerDev | **none — asserted-off** | none — fully local |

Internal-path egress assertion: context manager around the LLM step
monitors `socket.create_connection` opens; any outbound connection
attempt raises and short-circuits the chain (logged as a Finding).
Implemented in S82d (V0). Drill rehearsed in S82f (Staged).

---

## 7. Kill-switch design

**Who engages:** CISO role (self-attested in demo; real RBAC in prod).

**What it does:**
1. Sets `runtime_status` → `PAUSED` on the target AISystem row.
2. `policy_gate(action=agent_run)` reads `runtime_status` from the AI
   system store; PAUSED → DENY with `policy_name=killswitch_engaged`.
3. Revokes the `escalate_to_human` tool from the binding (operator
   loses HITL surface; no new side effects can fire).
4. Falls back to "preliminary only" mode: agent can still return a
   risk-tier preview from local corpus, but cannot escalate.

**How it's tested:** S82f failure-mode drill — engage the switch
between two pilot runs, verify second run short-circuits with the
expected `policy_name`, verify the audit row carries the killswitch
event.

The kill switch is itself audited — engagement and disengagement both
produce audit chain rows so the timeline is reconstructable.

---

## 8. Phase 2 exit checklist

| Item | Status |
|---|---|
| Model/provider choice reviewed vs use-case sensitivity | ✅ §2 |
| Autonomy ceiling locked | ✅ §3 (ADVISORY + HITL on escalate_to_human) |
| Data-flow review (scrub before tracer, per-class redaction) | ✅ §4 |
| Tool inventory with side_effect + authz + rate_limit | ✅ §5 (6 tools, 1 with side effect) |
| Isolation boundary documented | ✅ §6 |
| Kill-switch design defined | ✅ §7 |
| Self-attested sign-off | ✅ header |

## Next phase

[Phase 3 — Runtime Spec: Policy & Controls](03-control-coverage.md)
runs in this same session (S82b). The rego files
(`policies/vendor-risk-ext.rego`, `policies/vendor-risk-int.rego`) and
the control coverage matrix are the Phase 3 deliverables.
