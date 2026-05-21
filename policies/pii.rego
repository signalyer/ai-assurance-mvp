# pii.rego — PII handling policies (posture-aware)
# Category: posture
# Applies to workloads with PII handling responsibilities
#
# Posture-specific rules:
#   - us-finserv:    Strict (no PII to LLM ever; mandatory scrub)
#   - eu-gdpr:       Strict (consent required; data minimization)
#   - hipaa:         Healthcare (PHI requires explicit authorization)
#   - default:       Moderate (scrub + log)

package aigovern.posture

import future.keywords.if
import future.keywords.in

default decision := {
    "decision": "ALLOW",
    "policy_name": "posture_default_allow",
    "reason": "No posture-specific rule matched",
}

# US-FinServ: Financial advice without disclaimer → REVIEW
decision := result if {
    input.posture == "us-finserv"
    input.action == "llm_call"
    input.domain == "finance"
    is_financial_advice(input.response)
    not has_disclaimer(input.response)
    result := {
        "decision": "REVIEW",
        "policy_name": "us_finserv_disclaimer_required",
        "reason": "Financial advice response missing required disclaimer",
        "metadata": {
            "posture": "us-finserv",
            "regulation": "FINRA Rule 2210",
            "severity": "MEDIUM",
        },
    }
}

# US-FinServ: Stock recommendations without risk disclosure → REVIEW
decision := result if {
    input.posture == "us-finserv"
    input.action == "llm_call"
    has_stock_recommendation(input.response)
    not has_risk_disclosure(input.response)
    result := {
        "decision": "REVIEW",
        "policy_name": "us_finserv_risk_disclosure_required",
        "reason": "Stock recommendations require risk disclosure",
        "metadata": {
            "posture": "us-finserv",
            "regulation": "FINRA Rule 2210",
            "severity": "MEDIUM",
        },
    }
}

# EU GDPR: PII in cross-border transfer → DENY
decision := result if {
    input.posture == "eu-gdpr"
    input.action in ["external_api", "llm_call"]
    input.destination_country != "EU"
    has_eu_pii(input.prompt)
    result := {
        "decision": "DENY",
        "policy_name": "gdpr_cross_border_transfer",
        "reason": "GDPR prohibits unauthorized cross-border PII transfer",
        "metadata": {
            "posture": "eu-gdpr",
            "regulation": "GDPR Article 44",
            "severity": "CRITICAL",
        },
    }
}

# HIPAA: PHI without explicit authorization → DENY
decision := result if {
    input.posture == "hipaa"
    has_phi(input.prompt)
    not input.phi_authorization
    result := {
        "decision": "DENY",
        "policy_name": "hipaa_phi_authorization_required",
        "reason": "PHI handling requires explicit authorization",
        "metadata": {
            "posture": "hipaa",
            "regulation": "HIPAA Privacy Rule",
            "severity": "CRITICAL",
        },
    }
}

# Helpers
is_financial_advice(text) if {
    text != null
    lower_text := lower(text)
    keywords := ["buy", "sell", "invest", "recommend", "guarantee", "should purchase"]
    some keyword in keywords
    contains(lower_text, keyword)
}

has_disclaimer(text) if {
    text != null
    lower_text := lower(text)
    keywords := ["not financial advice", "disclaimer", "consult a financial advisor", "professional advice"]
    some keyword in keywords
    contains(lower_text, keyword)
}

has_stock_recommendation(text) if {
    text != null
    regex.match(`[A-Z]{2,5}\b`, text)  # Stock tickers
    lower_text := lower(text)
    keywords := ["buy", "purchase", "long", "short", "recommend"]
    some keyword in keywords
    contains(lower_text, keyword)
}

has_risk_disclosure(text) if {
    text != null
    lower_text := lower(text)
    keywords := ["risk", "volatility", "may lose", "past performance", "no guarantee"]
    some keyword in keywords
    contains(lower_text, keyword)
}

has_eu_pii(text) if {
    text != null
    # EU-style data: addresses with EU country codes, IBANs, etc.
    regex.match(`[A-Z]{2}\d{2}[A-Z0-9]{11,30}`, text)  # IBAN
}

has_phi(text) if {
    text != null
    lower_text := lower(text)
    keywords := ["diagnosis", "patient", "medical record", "prescription", "treatment", "icd-"]
    some keyword in keywords
    contains(lower_text, keyword)
}
