# vendor-risk-int.rego — Workload-specific policy for vendor_risk INTERNAL system
# system_id: sys-vendor-risk-int-001
# SOP reference: docs/SOP-agent-onboarding.md Phase 3
# Design review:  docs/sop-vendor-risk/02-design-review.md
#
# This is the on-prem deterministic path. The agent code is identical to
# the external sibling but the LLM step never leaves the network, so the
# rules here harden the network-isolation contract rather than relax it.
#
# Stacking with base.rego + risk-tier same as the external sibling.
#
# Identity matcher: system_id prefix "sys-vendor-risk-int-"

package aigovern.workload

import future.keywords.if
import future.keywords.in

default decision := {
    "decision": "ALLOW",
    "policy_name": "vendor_risk_int_default_allow",
    "reason": "No vendor-risk-int-specific rule matched",
}

is_vendor_risk_int if {
    startswith(input.workload_id, "sys-vendor-risk-int-")
}

# ---------------------------------------------------------------------------
# Rule 1 — Same tool allowlist as the external sibling. The agent code is
# shared; if the allowlists drift, that is a bug.
# ---------------------------------------------------------------------------
vendor_risk_int_tools := {
    "search_tprm_corpus",
    "lookup_subprocessor_risk",
    "parse_vendor_document",
    "check_regulatory_requirements",
    "compare_to_baseline",
    "escalate_to_human",
}

# ---------------------------------------------------------------------------
# Rule 2 — Mutation-verb prefix DENY (same shape, defense in depth).
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
# Rule 3 — STRICTER operator role allowlist than the external sibling.
# Internal data exposure requires direct TPRM accountability; admin
# break-glass not permitted on this path (the external system is the
# correct surface for admin-level access).
# Enforced via the `required_operator_roles` set.
# ---------------------------------------------------------------------------
required_operator_roles := {
    "tprm-analyst",
    "ciso",
}

# ---------------------------------------------------------------------------
# Rule 4 — Required boolean flags. The runtime must assert these before
# the LLM step proceeds; the policy layer is the belt-and-braces check.
# `network_egress_lock_engaged` is the canonical flag set by the
# socket-monitor context manager in agents/vendor_risk/agent.py (S82d).
# `dlp_completed` is set after scrub_pii confirms tokens are in place.
# Enforced via the `required_true_flags` set.
# ---------------------------------------------------------------------------
required_true_flags := {
    "network_egress_lock_engaged",
    "dlp_completed",
}

# ---------------------------------------------------------------------------
# Rule 5 — Denied URL substrings in tool args. If a tool call's args
# contain any of these patterns, the internal-path agent is being asked
# to reach outside the isolation boundary. DENY immediately.
# Enforced via the `denied_url_substrings` list.
# ---------------------------------------------------------------------------
denied_url_substrings := [
    "http://",
    "https://",
    "://",
    "anthropic.com",
    "openai.com",
    "bedrock",
    "amazonaws.com",
]

# ---------------------------------------------------------------------------
# Rule 6 — Per-call prompt token cap. Same threshold as external; the
# governance principle is identical even though the LLM substrate differs.
# ---------------------------------------------------------------------------
max_prompt_tokens := 32000

# ---------------------------------------------------------------------------
# Rule 7 — Per-run call budget. Same shape as external.
# ---------------------------------------------------------------------------
max_llm_calls_per_run := 25

# Note: `denied_token_types` intentionally NOT declared for the internal
# system. INTERNAL_SYSTEMS / MNPI tokens are the very reason this path
# exists — denying them here would deny the system's purpose. The
# isolation boundary (network egress lock + role allowlist) is the
# safeguard, not data-class denial.
