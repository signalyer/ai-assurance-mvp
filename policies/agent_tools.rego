# agent_tools.rego — Tool authorization policies
# Category: team
# Controls which tools each team's workloads can invoke
#
# Common patterns:
#   - File system access: explicit allowlist
#   - Network calls: domain allowlist
#   - Code execution: sandbox-only
#   - Database writes: require pre-authorization
#   - Email/SMS: rate-limited + audit-logged

package aigovern.team

import future.keywords.if
import future.keywords.in

default decision := {
    "decision": "ALLOW",
    "policy_name": "team_default_allow",
    "reason": "No team-specific tool restriction matched",
}

# Per-team allowed tools
allowed_tools := {
    "payments": ["check_balance", "verify_account", "list_transactions"],
    "support": ["search_kb", "create_ticket", "lookup_customer"],
    "engineering": ["search_docs", "run_test", "deploy_preview"],
    "marketing": ["compose_email", "schedule_post", "analytics_query"],
    "data": ["query_db", "export_data", "run_pipeline"],
}

# Rule 1: Payments team requires preauthorization for ALL tool invocations
decision := result if {
    input.action == "tool_invoke"
    input.team == "payments"
    not input.preauthorized
    result := {
        "decision": "DENY",
        "policy_name": "payments_tool_preauth_required",
        "reason": "Payments team requires pre-authorization for tool invocations",
        "metadata": {
            "team": "payments",
            "tool": input.tool_name,
            "severity": "HIGH",
        },
    }
}

# Rule 2: Tools must be in team's allowlist
decision := result if {
    input.action == "tool_invoke"
    input.team != null
    input.tool_name != null
    team_allowed := allowed_tools[input.team]
    not input.tool_name in team_allowed
    result := {
        "decision": "DENY",
        "policy_name": "tool_not_in_team_allowlist",
        "reason": sprintf("Tool '%s' not in allowlist for team '%s'", [input.tool_name, input.team]),
        "metadata": {
            "team": input.team,
            "tool": input.tool_name,
            "allowed_tools": team_allowed,
            "severity": "MEDIUM",
        },
    }
}

# Rule 3: Code execution tools require sandbox
decision := result if {
    input.action == "tool_invoke"
    input.tool_name in ["execute_code", "run_shell", "eval_python"]
    not input.sandbox_enabled
    result := {
        "decision": "DENY",
        "policy_name": "code_execution_sandbox_required",
        "reason": "Code execution tools must run in sandbox",
        "metadata": {
            "tool": input.tool_name,
            "severity": "CRITICAL",
        },
    }
}

# Rule 4: Network calls must be to allowed domains
decision := result if {
    input.action == "tool_invoke"
    input.tool_name == "http_request"
    input.target_domain != null
    not domain_allowed(input.target_domain)
    result := {
        "decision": "DENY",
        "policy_name": "network_destination_not_allowed",
        "reason": sprintf("HTTP request to '%s' not in allowed domains", [input.target_domain]),
        "metadata": {
            "target": input.target_domain,
            "severity": "HIGH",
        },
    }
}

# Helper: check if domain is allowed
domain_allowed(domain) if {
    allowed := [
        "api.anthropic.com",
        "api.openai.com",
        "cloud.langfuse.com",
        "search.windows.net",
        "azure.com",
    ]
    some allowed_domain in allowed
    endswith(domain, allowed_domain)
}
