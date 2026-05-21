"""Inherent-risk classification for AI System intake.

Pure function: given the intake payload, returns
  - the classified RiskLevel (LOW / MEDIUM / HIGH / CRITICAL)
  - the list of rules that fired (audit trail)
  - a human-readable rationale.

The rules implement the policy the platform commits to enforce at intake time.
They are deterministic — running the same intake twice produces the same result.
"""

from __future__ import annotations

from dataclasses import dataclass

from domain.models import RiskLevel


# Domains considered regulated financial workflows
REGULATED_FS_DOMAINS = {
    "Payments", "AML", "KYC", "Credit", "Treasury", "Wealth",
}

# Autonomy levels considered "execute" (vs answer/recommend/draft)
EXECUTE_AUTONOMY = {
    "execute_with_approval", "execute_autonomously",
}

# Data classes treated as sensitive at intake time
SENSITIVE_DATA = {
    "pii", "npi", "pci", "payment_data", "aml_kyc_data", "credit_data",
    "confidential",
}

# User populations treated as customer-facing
CUSTOMER_FACING = {"customer-facing", "third-party", "regulator-facing"}

# Customer impact levels considered material
MATERIAL_IMPACT = {"direct", "material"}


@dataclass
class RiskClassification:
    """Result of applying the classification rules to an intake payload."""
    risk_level: RiskLevel
    rules_fired: list[str]            # ordered, each rule has a stable id like "R3"
    rationale: list[str]              # human-readable reason per rule
    signals: dict[str, bool]          # the resolved boolean signals used


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _max_risk(a: RiskLevel, b: RiskLevel) -> RiskLevel:
    order = [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]
    return a if order.index(a) >= order.index(b) else b


def _norm(v: str | None) -> str:
    return (v or "").strip().lower()


# ---------------------------------------------------------------------------
# Signal extraction
# ---------------------------------------------------------------------------

def _signals(intake: dict) -> dict[str, bool]:
    """Resolve boolean signals used by the rules from the raw intake payload."""
    data_classes = {_norm(d) for d in intake.get("data_classes", [])}
    has_sensitive_data = bool(data_classes & SENSITIVE_DATA)

    domain = _norm(intake.get("domain"))
    is_regulated_fs = any(d.lower() == domain for d in REGULATED_FS_DOMAINS) or \
                       domain in {d.lower() for d in REGULATED_FS_DOMAINS}

    autonomy = _norm(intake.get("autonomy_level"))
    is_execute_autonomy = autonomy in EXECUTE_AUTONOMY

    user_population = _norm(intake.get("user_population"))
    is_customer_facing = user_population in CUSTOMER_FACING

    customer_impact = _norm(intake.get("customer_impact"))
    is_material_impact = customer_impact in MATERIAL_IMPACT

    rag_enabled = bool(intake.get("rag_enabled"))

    tools = intake.get("tools_used") or intake.get("tools") or []
    has_tools = (bool(intake.get("can_call_tools"))) or bool(tools)

    can_write = bool(intake.get("can_write_data"))
    triggers_customer_comm = bool(intake.get("can_trigger_customer_communication"))
    influences_fs = bool(intake.get("can_influence_fs_workflow"))
    tools_return_sensitive = bool(intake.get("tools_return_sensitive_data"))
    logs_contain_sensitive = bool(intake.get("logs_contain_sensitive_data"))
    data_in_prompts = bool(intake.get("data_in_prompts"))
    data_in_rag = bool(intake.get("data_in_rag"))

    return {
        "has_sensitive_data": has_sensitive_data,
        "is_regulated_fs": is_regulated_fs,
        "is_execute_autonomy": is_execute_autonomy,
        "is_customer_facing": is_customer_facing,
        "is_material_impact": is_material_impact,
        "rag_enabled": rag_enabled,
        "has_tools": has_tools,
        "can_write": can_write,
        "triggers_customer_comm": triggers_customer_comm,
        "influences_fs": influences_fs,
        "tools_return_sensitive": tools_return_sensitive,
        "logs_contain_sensitive": logs_contain_sensitive,
        "data_in_prompts": data_in_prompts,
        "data_in_rag": data_in_rag,
    }


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify_inherent_risk(intake: dict) -> RiskClassification:
    """Apply the six rules in order; final risk is the max across all that fire.

    Rules (ordered for explainability — order does NOT affect outcome because
    we take the max risk across all firing rules):

      R1: Sensitive data + RAG + tools                                  -> HIGH
      R2: Execute autonomy on a regulated FS workflow                   -> CRITICAL
      R3: Customer-facing + sensitive data                              -> HIGH
      R4: Tools return sensitive data                                   -> HIGH
      R5: Payment / Credit / AML / KYC / Treasury / Wealth impact       -> HIGH (floor)
      R6: Internal-only + no sensitive data + no tools                  -> LOW (anchor)

    A system that triggers no rule defaults to MEDIUM.
    """
    s = _signals(intake)
    risk = RiskLevel.MEDIUM  # default if nothing fires beyond R6
    rules_fired: list[str] = []
    rationale: list[str] = []
    baseline_low_anchor = False

    # R1
    if s["has_sensitive_data"] and s["rag_enabled"] and s["has_tools"]:
        risk = _max_risk(risk, RiskLevel.HIGH)
        rules_fired.append("R1")
        rationale.append(
            "R1 (HIGH): Sensitive data class + RAG + agent tools — combined surface for "
            "data exfiltration via retrieval or tool output."
        )

    # R2
    if s["is_execute_autonomy"] and s["is_regulated_fs"]:
        risk = _max_risk(risk, RiskLevel.CRITICAL)
        rules_fired.append("R2")
        rationale.append(
            "R2 (CRITICAL): Execute-level autonomy on a regulated FS workflow "
            "(Payments, AML, KYC, Credit, Treasury, Wealth) — model action carries "
            "regulatory and financial consequence."
        )

    # R3
    if s["is_customer_facing"] and s["has_sensitive_data"]:
        risk = _max_risk(risk, RiskLevel.HIGH)
        rules_fired.append("R3")
        rationale.append(
            "R3 (HIGH): Customer-facing system handling sensitive data — direct "
            "customer harm potential and GLBA / CFPB exposure."
        )

    # R4
    if s["tools_return_sensitive"]:
        risk = _max_risk(risk, RiskLevel.HIGH)
        rules_fired.append("R4")
        rationale.append(
            "R4 (HIGH): Tools return sensitive data — tool output becomes an "
            "exfiltration channel back into the prompt or response."
        )

    # R5 — domain floor
    if s["is_regulated_fs"] or s["influences_fs"]:
        risk = _max_risk(risk, RiskLevel.HIGH)
        rules_fired.append("R5")
        rationale.append(
            "R5 (HIGH floor): Workflow influences Payments / Credit / AML / KYC / "
            "Treasury / Wealth — regulatory exposure floors inherent risk at HIGH."
        )

    # R6 — low anchor only if NOTHING else fired
    if not rules_fired:
        if (not s["is_customer_facing"]
                and not s["has_sensitive_data"]
                and not s["has_tools"]
                and not s["is_execute_autonomy"]
                and not s["rag_enabled"]):
            risk = RiskLevel.LOW
            rules_fired.append("R6")
            baseline_low_anchor = True
            rationale.append(
                "R6 (LOW anchor): Internal-only, no sensitive data, no tools, no RAG, "
                "no execute autonomy — minimal attack surface and consequence."
            )

    # Secondary amplifiers (add rationale only; do not lower risk)
    if s["is_execute_autonomy"] and not s["is_regulated_fs"]:
        risk = _max_risk(risk, RiskLevel.HIGH)
        if "R2" not in rules_fired:
            rules_fired.append("R2b")
            rationale.append(
                "R2b (HIGH): Execute-level autonomy outside a regulated FS workflow — "
                "model takes action with real-world side effects."
            )

    if s["triggers_customer_comm"] and s["has_sensitive_data"]:
        risk = _max_risk(risk, RiskLevel.HIGH)
        if "R3" not in rules_fired:
            rules_fired.append("R3b")
            rationale.append(
                "R3b (HIGH): Triggers customer communications carrying sensitive data — "
                "outbound channel for PII/NPI leakage."
            )

    # If MEDIUM remained because nothing fired and we couldn't anchor to LOW
    if not rules_fired and not baseline_low_anchor:
        rationale.append(
            "No specific risk rule fired. Defaulting to MEDIUM pending review."
        )

    return RiskClassification(
        risk_level=risk,
        rules_fired=rules_fired,
        rationale=rationale,
        signals=s,
    )


__all__ = ["classify_inherent_risk", "RiskClassification"]
