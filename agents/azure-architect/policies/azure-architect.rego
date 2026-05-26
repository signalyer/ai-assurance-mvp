# azure-architect.rego — OPA policy for the Azure Deployment Architect agent
# Category: workload (per-system)
# Workload: azure-architect (AI System ID populated post-P1 intake)
# Autonomy: draft (HITL — produces documents, never mutates Azure)
#
# Defense-in-depth: the agent already runs with an Azure Reader role assignment
# (no mutate permissions at the cloud IAM layer). This policy is the SECOND
# trust boundary — even if a future maintainer accidentally widens the agent's
# Azure RBAC, the OPA gate STILL refuses any mutation tool call.
#
# Per CLAUDE.md project rule:
#   "Policy engine errors → default DENY, never ALLOW"
#
# This package follows that rule literally: the default decision is DENY,
# and only the explicit read-only allowlist below flips it to ALLOW.

package aigovern.workload.azure_architect

import future.keywords.if
import future.keywords.in

# ---------------------------------------------------------------------------
# Default decision — DENY. Allow only what the rules below explicitly permit.
# ---------------------------------------------------------------------------

default decision := {
    "decision": "DENY",
    "policy_name": "azure_architect_default_deny",
    "reason": "Tool not on the read-only allowlist; default-DENY policy.",
}

# ---------------------------------------------------------------------------
# The read-only ARM tool allowlist
# ---------------------------------------------------------------------------

allowed_tools := {
    "list_subscriptions",
    "list_resource_groups",
    "get_resource_metadata",
    "list_role_assignments",
    "get_network_topology",
    "render_mermaid_diagram",  # local renderer, no Azure call
}

# ---------------------------------------------------------------------------
# Rule 1: Tool must be on the allowlist
# ---------------------------------------------------------------------------

decision := result if {
    input.action == "tool_invoke"
    input.tool_name in allowed_tools
    result := {
        "decision": "ALLOW",
        "policy_name": "azure_architect_read_only_allowlist",
        "reason": sprintf("Tool %q is on the read-only allowlist.", [input.tool_name]),
        "metadata": {
            "workload": "azure-architect",
            "autonomy": "draft",
            "tool": input.tool_name,
        },
    }
}

# ---------------------------------------------------------------------------
# Rule 2: Explicit denylist for mutating ARM verbs (defense-in-depth)
#
# Even if some future maintainer adds a name to allowed_tools that LOOKS
# read-only but verbs like "create_", "delete_", "update_", "deploy_" sneak
# in, this rule slaps them back to DENY with a louder reason string.
# ---------------------------------------------------------------------------

mutation_verb_prefixes := {"create_", "delete_", "update_", "patch_", "deploy_", "put_", "post_", "write_", "begin_"}

decision := result if {
    input.action == "tool_invoke"
    some prefix in mutation_verb_prefixes
    startswith(input.tool_name, prefix)
    result := {
        "decision": "DENY",
        "policy_name": "azure_architect_no_mutations",
        "reason": sprintf("Tool %q starts with mutation prefix %q; the azure-architect agent has autonomy=draft and MUST NOT mutate Azure resources.", [input.tool_name, prefix]),
        "metadata": {
            "workload": "azure-architect",
            "tool": input.tool_name,
            "severity": "CRITICAL",
        },
    }
}

# ---------------------------------------------------------------------------
# Rule 3: Mermaid source must not be sent to external renderer without scrub
#
# The local mermaid-cli renderer is the default and is always ALLOW (covered
# by Rule 1). A future maintainer who adds a "render_via_kroki" tool MUST
# add the scrub-and-waive flow before this rule allows it.
# ---------------------------------------------------------------------------

decision := result if {
    input.action == "tool_invoke"
    input.tool_name == "render_via_kroki"
    not input.scrubbed
    result := {
        "decision": "DENY",
        "policy_name": "azure_architect_kroki_requires_scrub",
        "reason": "render_via_kroki requires input.scrubbed=true (Mermaid source can carry inferred resource names — treat as PII-adjacent).",
        "metadata": {
            "workload": "azure-architect",
            "tool": "render_via_kroki",
            "severity": "HIGH",
        },
    }
}

# ---------------------------------------------------------------------------
# Rule 4: All actions outside tool_invoke fall through to default DENY
#
# This is implicit — `default decision := DENY` above handles it. Listed here
# as a comment so a future maintainer doesn't add an `action == "*"` rule that
# silently widens the policy.
# ---------------------------------------------------------------------------
