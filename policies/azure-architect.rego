# azure-architect.rego — Workload-specific policy for the Azure Deployment Architect agent
# Category: workload-specific
# Applies to workloads with workload_type == "azure_architect" or workload_id
# starting with "azure-architect".
#
# Stacking with base.rego (org-mandatory) and risk-tier policies:
#   - base.rego runs first (PII scrub guarantee, fail-closed defaults)
#   - This file runs as workload-specific overlay
#   - Most strict policy wins (DENY > REVIEW > ALLOW)
#
# Operational stance:
#   - The agent's ONLY job is to read Azure subscription state and emit a
#     Well-Architected Framework review. It must NEVER mutate Azure resources.
#   - Read-only tool allowlist below explicitly enumerates the P4 tool surface.
#   - Mutation patterns are denied by name AND by verb (defense in depth).
#   - LLM calls are allowed but rate-limit-aware: a single review run should
#     not exceed N model calls; runaway loops are caught upstream.

package aigovern.workload

import future.keywords.if
import future.keywords.in

default decision := {
    "decision": "ALLOW",
    "policy_name": "workload_default_allow",
    "reason": "No workload-specific rule matched",
}

# ---------------------------------------------------------------------------
# Identity matcher: anything tagged azure-architect via workload_type or
# workload_id falls under this policy file.
# ---------------------------------------------------------------------------
is_azure_architect if {
    input.workload_type == "azure_architect"
}
is_azure_architect if {
    startswith(input.workload_id, "azure-architect")
}

# ---------------------------------------------------------------------------
# Tool allowlist — the P4 read-only surface. Any tool invoked by the agent
# that is NOT in this list is denied.
# ---------------------------------------------------------------------------
readonly_azure_tools := {
    "list_subscriptions",
    "list_resource_groups",
    "get_resource_metadata",
    "get_network_topology",
    "list_role_assignments",
    "get_storage_account_properties",
    "get_key_vault_properties",
}

# ---------------------------------------------------------------------------
# Rule 1 — Deny any tool call NOT in the read-only allowlist.
# Catches everything: explicit mutation tools, future tools not vetted,
# typos in the agent's tool name.
# ---------------------------------------------------------------------------
decision := result if {
    is_azure_architect
    input.action == "tool_invoke"
    not input.tool_name in readonly_azure_tools
    result := {
        "decision": "DENY",
        "policy_name": "azure_architect_tool_not_allowlisted",
        "reason": sprintf("Tool '%s' is not in the azure-architect read-only allowlist", [input.tool_name]),
        "metadata": {
            "workload_type": "azure_architect",
            "tool": input.tool_name,
            "severity": "HIGH",
        },
    }
}

# ---------------------------------------------------------------------------
# Rule 2 — Deny mutation by verb pattern (belt-and-braces).
# Even if a future tool is added to the allowlist by mistake, anything whose
# name starts with create_ / update_ / delete_ / set_ / put_ / patch_ / etc.
# is denied. Catches the regression class where a reviewer approves a tool
# without realising it has side effects.
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

decision := result if {
    is_azure_architect
    input.action == "tool_invoke"
    some verb in mutation_verbs
    startswith(input.tool_name, verb)
    result := {
        "decision": "DENY",
        "policy_name": "azure_architect_mutation_verb_blocked",
        "reason": sprintf("Tool '%s' uses a mutation-verb prefix; azure-architect is read-only", [input.tool_name]),
        "metadata": {
            "workload_type": "azure_architect",
            "tool": input.tool_name,
            "matched_verb": verb,
            "severity": "CRITICAL",
        },
    }
}

# ---------------------------------------------------------------------------
# Rule 3 — Deny memory_write / persistence side effects.
# The agent should be stateless; any persistent write must flow through
# the platform's audit chain, not the agent's own writes.
# ---------------------------------------------------------------------------
decision := result if {
    is_azure_architect
    input.action == "memory_write"
    result := {
        "decision": "DENY",
        "policy_name": "azure_architect_no_memory_write",
        "reason": "azure-architect is stateless; persistent writes go through the platform audit chain, not the agent",
        "metadata": {
            "workload_type": "azure_architect",
            "severity": "MEDIUM",
        },
    }
}

# ---------------------------------------------------------------------------
# Rule 4 — Require audit metadata on every LLM call.
# Architecture review output may be cited in compliance audits; every call
# needs a workload_id + run_id (or trace_id) so the output is traceable.
# ---------------------------------------------------------------------------
decision := result if {
    is_azure_architect
    input.action == "llm_call"
    not input.workload_id
    result := {
        "decision": "DENY",
        "policy_name": "azure_architect_audit_workload_id_required",
        "reason": "azure-architect LLM calls require workload_id for audit traceability",
        "metadata": {
            "workload_type": "azure_architect",
            "severity": "HIGH",
        },
    }
}

# ---------------------------------------------------------------------------
# Rule 5 — Cap the per-run LLM call budget.
# A runaway loop (agent retries forever, accidentally recursive) should be
# stopped at the policy layer, not the billing layer. Caller passes
# input.run_call_count for the in-flight run.
# ---------------------------------------------------------------------------
max_llm_calls_per_run := 25

decision := result if {
    is_azure_architect
    input.action == "llm_call"
    input.run_call_count > max_llm_calls_per_run
    result := {
        "decision": "DENY",
        "policy_name": "azure_architect_llm_call_budget_exceeded",
        "reason": sprintf("Run exceeded %d LLM calls — likely a loop", [max_llm_calls_per_run]),
        "metadata": {
            "workload_type": "azure_architect",
            "limit": max_llm_calls_per_run,
            "observed": input.run_call_count,
            "severity": "HIGH",
        },
    }
}

# ---------------------------------------------------------------------------
# Rule 6 — Cross-subscription scope must be explicit.
# Reading a single subscription is the default. Reading more than one in a
# single run requires input.multi_subscription_authorized=true (operator
# consent), preventing accidental data-exfil shape "agent dumps every
# subscription in the tenant."
# ---------------------------------------------------------------------------
decision := result if {
    is_azure_architect
    input.action == "tool_invoke"
    input.tool_name == "list_subscriptions"
    object.get(input, "multi_subscription_authorized", false) == false
    object.get(input, "explicit_subscription_id", "") == ""
    result := {
        "decision": "REVIEW",
        "policy_name": "azure_architect_multi_subscription_review",
        "reason": "list_subscriptions without an explicit_subscription_id or multi_subscription_authorized flag — surface for operator review",
        "metadata": {
            "workload_type": "azure_architect",
            "severity": "MEDIUM",
        },
    }
}
