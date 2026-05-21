# base.rego — Org-mandatory policies (non-negotiable across all workloads)
# Category: org-mandatory
# Decision precedence: highest (always evaluated first)
#
# Enforcement points:
#   - Before any external API call (LLM, third-party tools)
#   - Before any data persistence (memory write, log write)
#   - Before any cross-workload data flow

package aigovern.org_mandatory

import future.keywords.if
import future.keywords.in

# Default decision: DENY (fail-closed)
default decision := {
    "decision": "DENY",
    "policy_name": "default_deny",
    "reason": "No matching ALLOW policy",
}

# Rule 1: Raw PII MUST be scrubbed before any external call
decision := result if {
    input.action in ["llm_call", "trace_call", "external_api"]
    has_raw_pii(input.prompt)
    not has_scrubber_tokens(input.prompt)
    result := {
        "decision": "DENY",
        "policy_name": "pii_no_raw_to_external",
        "reason": "Raw PII detected in prompt; must be scrubbed via @scrub_pii before external call",
        "metadata": {
            "violation_type": "raw_pii_leak",
            "severity": "CRITICAL",
        },
    }
}

# Rule 2: Memory writes must have scrubbed content
decision := result if {
    input.action == "memory_write"
    has_raw_pii(input.content)
    result := {
        "decision": "DENY",
        "policy_name": "memory_pii_required_scrub",
        "reason": "Memory writes must contain scrubbed content only",
        "metadata": {
            "violation_type": "memory_pii_leak",
            "severity": "HIGH",
        },
    }
}

# Rule 3: All other actions ALLOW by default if no rule violated
decision := result if {
    not has_raw_pii(input.prompt)
    result := {
        "decision": "ALLOW",
        "policy_name": "org_mandatory_pass",
        "reason": "No org-mandatory violations detected",
    }
}

# Helper: detect raw PII patterns
has_raw_pii(text) if {
    text != null
    regex.match(`\b\d{3}-\d{2}-\d{4}\b`, text)  # SSN
}

has_raw_pii(text) if {
    text != null
    regex.match(`\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b`, text)  # Email
}

has_raw_pii(text) if {
    text != null
    regex.match(`\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b`, text)  # Credit card
}

# Helper: detect scrubber tokens
has_scrubber_tokens(text) if {
    text != null
    regex.match(`\[(PERSON|EMAIL|EMAIL_ADDRESS|SSN|US_SSN|PHONE|PHONE_NUMBER|CREDIT_CARD)_\d{3}\]`, text)
}
