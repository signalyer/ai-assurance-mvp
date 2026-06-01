# vendor-risk-ext.rego — Workload-specific policy for vendor_risk EXTERNAL system
# system_id: sys-vendor-risk-ext-001
# SOP reference: docs/SOP-agent-onboarding.md Phase 3
# Design review:  docs/sop-vendor-risk/02-design-review.md
#
# Stacking order:
#   1. base.rego (org-mandatory) — PII scrub guarantee, fail-closed defaults
#   2. risk-tier policies — HIGH risk-tier rules
#   3. THIS FILE — vendor-risk-ext overlay
#   Most strict wins (DENY > REVIEW > ALLOW).
#
# Enforcement substrate:
#   The data declarations below are read by domain/rego_loader.py and
#   enforced by domain/policy_engine.py::_check_workload_specific. Adding
#   a new data shape here without extending the Python enforcer is
#   decorative — see [[rego-files-were-decorative]].
#
# Identity matcher: system_id prefix "sys-vendor-risk-ext-"
#   (resolved in domain/rego_loader.py::resolve_workload_policy)

package aigovern.workload

import future.keywords.if
import future.keywords.in

default decision := {
    "decision": "ALLOW",
    "policy_name": "vendor_risk_ext_default_allow",
    "reason": "No vendor-risk-ext-specific rule matched",
}

is_vendor_risk_ext if {
    startswith(input.workload_id, "sys-vendor-risk-ext-")
}

# ---------------------------------------------------------------------------
# Rule 1 — Tool allowlist. Only the 6 tools declared in the Phase 2 design
# review are permitted. Anything else is denied.
# Enforced by _check_workload_specific via the `*_tools` set discovery rule.
# ---------------------------------------------------------------------------
vendor_risk_ext_tools := {
    "search_tprm_corpus",
    "lookup_subprocessor_risk",
    "parse_vendor_document",
    "check_regulatory_requirements",
    "compare_to_baseline",
    "escalate_to_human",
}

# ---------------------------------------------------------------------------
# Rule 2 — Mutation-verb prefix DENY (defense in depth). Even if a future
# tool is added to the allowlist by mistake, anything whose name starts
# with create_/update_/delete_/etc. is denied. Catches the regression class
# where a reviewer approves a tool without realising it has side effects.
# ---------------------------------------------------------------------------
mutation_verbs := [
    "create_",
    "update_",
    "delete_",
    "set_",
    "put_",
    "patch_",
    "remove_",
    "destroy_",
    "deploy_",
    "rotate_",
    "grant_",
    "revoke_",
    "enable_",
    "disable_",
]

# ---------------------------------------------------------------------------
# Rule 3 — DENY if scrubber's redacted_token_types contains tokens whose
# presence indicates the operator query is referencing internal context
# that should never egress to the external cloud LLM. The internal sibling
# (sys-vendor-risk-int-001) is the correct destination for these queries.
# Enforced via the `denied_token_types` set.
# ---------------------------------------------------------------------------
denied_token_types := {
    "INTERNAL_SYSTEMS",
    "MNPI",
    "CREDIT_DATA",
}

# ---------------------------------------------------------------------------
# Rule 4 — Operator role allowlist. Only TPRM analysts, CISOs, and admins
# may invoke this agent. Enforced via the `required_operator_roles` set.
# ---------------------------------------------------------------------------
required_operator_roles := {
    "tprm-analyst",
    "ciso",
    "admin",
}

# ---------------------------------------------------------------------------
# Rule 5 — Per-call prompt token cap. Cost guard + a smell test for
# accidental whole-document dumps. 32K = generous for a single vendor
# package summary + retrieved corpus snippets.
# Enforced via the `max_prompt_tokens` scalar.
# ---------------------------------------------------------------------------
max_prompt_tokens := 32000

# ---------------------------------------------------------------------------
# Rule 6 — Prompt-injection score threshold (0-100 percentage). Any prompt
# scoring above this from the guardrails layer is denied at the policy
# gate before reaching the LLM. Threshold matches the project default for
# external-facing agents.
# Enforced via the `max_injection_score_pct` scalar.
# ---------------------------------------------------------------------------
max_injection_score_pct := 70

# ---------------------------------------------------------------------------
# Rule 7 — Per-run LLM call budget. A runaway loop should be stopped at
# the policy layer, not the billing layer. Caller passes
# input.run_call_count for the in-flight run.
# Enforced via the `max_llm_calls_per_run` scalar.
# ---------------------------------------------------------------------------
max_llm_calls_per_run := 25
