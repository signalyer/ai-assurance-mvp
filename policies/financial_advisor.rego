# financial_advisor.rego — Specific policies for financial advisor workloads
# Category: risk-tier (HIGH for financial advisors)
# Applies to workloads with workload_type == "financial_advisor"
#
# Stacking with base.rego (org-mandatory) and pii.rego (posture):
#   - base.rego runs first (PII checks)
#   - This file runs as risk-tier specific overlay
#   - Most strict policy wins

package aigovern.risk_tier

import future.keywords.if
import future.keywords.in

default decision := {
    "decision": "ALLOW",
    "policy_name": "risk_tier_default_allow",
    "reason": "No risk-tier rule matched",
}

# Rule 1: CRITICAL risk-tier workloads require human-in-the-loop for actions
decision := result if {
    input.risk_tier == "CRITICAL"
    input.action in ["tool_invoke", "external_api", "memory_write"]
    not input.human_approval
    result := {
        "decision": "REVIEW",
        "policy_name": "critical_human_in_loop_required",
        "reason": "CRITICAL risk-tier workloads require human approval for actions",
        "metadata": {
            "risk_tier": "CRITICAL",
            "action": input.action,
            "severity": "HIGH",
        },
    }
}

# Rule 2: Financial advisor responses with specific dollar amounts → REVIEW
decision := result if {
    input.workload_type == "financial_advisor"
    input.action == "llm_call"
    has_specific_dollar_amount(input.response)
    result := {
        "decision": "REVIEW",
        "policy_name": "financial_advisor_specific_amount_review",
        "reason": "Financial advisor response contains specific dollar amounts; requires review",
        "metadata": {
            "workload_type": "financial_advisor",
            "regulation": "FINRA Rule 2210",
            "severity": "MEDIUM",
        },
    }
}

# Rule 3: Financial advisor must not make guaranteed-return claims
decision := result if {
    input.workload_type == "financial_advisor"
    input.action == "llm_call"
    has_guarantee_claim(input.response)
    result := {
        "decision": "DENY",
        "policy_name": "financial_advisor_no_guarantees",
        "reason": "Financial advisor response contains guaranteed-return claims (prohibited)",
        "metadata": {
            "workload_type": "financial_advisor",
            "regulation": "FINRA Rule 2210, SEC Rule 156",
            "severity": "CRITICAL",
        },
    }
}

# Rule 4: HIGH risk-tier requires audit metadata on every call
decision := result if {
    input.risk_tier in ["HIGH", "CRITICAL"]
    input.action == "llm_call"
    not input.audit_session_id
    result := {
        "decision": "DENY",
        "policy_name": "high_risk_audit_required",
        "reason": "HIGH/CRITICAL risk-tier requires audit_session_id on every call",
        "metadata": {
            "risk_tier": input.risk_tier,
            "severity": "HIGH",
        },
    }
}

# Helpers
has_specific_dollar_amount(text) if {
    text != null
    regex.match(`\$\s?\d{2,}[,.\d]*`, text)  # $100, $1,000.00, etc.
}

has_guarantee_claim(text) if {
    text != null
    lower_text := lower(text)
    keywords := [
        "guaranteed return",
        "guarantee returns",
        "risk-free",
        "no risk",
        "definitely make",
        "guaranteed profit",
        "100% return",
        "double your money",
    ]
    some keyword in keywords
    contains(lower_text, keyword)
}
