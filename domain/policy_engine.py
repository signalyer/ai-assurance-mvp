"""OPA (Open Policy Agent) client wrapper with local Python fallback.

Evaluates policies across 5 categories:
1. org-mandatory   — organization-wide non-negotiable rules
2. posture         — regulatory/compliance posture (US-FinServ, etc.)
3. risk-tier       — risk-tier-specific (CRITICAL/HIGH/MEDIUM/LOW)
4. team            — per-team policies
5. system-override — emergency overrides (audit-logged)

Fail-closed: errors and missing decisions default to DENY.
Decisions logged to data/policy_decisions.jsonl for audit + trust scoring.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Storage for policy decision audit log
_DATA_DIR = Path(__file__).resolve().parents[1] / "data"
_DATA_DIR.mkdir(exist_ok=True)
POLICY_DECISIONS_FILE = _DATA_DIR / "policy_decisions.jsonl"


class Decision(str, Enum):
    """Policy decision outcomes."""
    ALLOW = "ALLOW"
    DENY = "DENY"
    REVIEW = "REVIEW"  # Soft-block: requires human review


class PolicyCategory(str, Enum):
    """The 5 policy categories from DECISIONS.md."""
    ORG_MANDATORY = "org-mandatory"
    POSTURE = "posture"
    RISK_TIER = "risk-tier"
    TEAM = "team"
    SYSTEM_OVERRIDE = "system-override"


class PolicyResult:
    """
    Result of a policy evaluation.

    Attributes:
        decision: ALLOW / DENY / REVIEW
        category: Which category this came from
        policy_name: Specific policy identifier (e.g., 'pii_no_raw_to_langfuse')
        reason: Human-readable explanation
        metadata: Additional context (e.g., violated rules, severity)
    """

    def __init__(
        self,
        decision: Decision,
        category: PolicyCategory,
        policy_name: str,
        reason: str = "",
        metadata: Optional[dict] = None,
    ):
        self.decision = decision
        self.category = category
        self.policy_name = policy_name
        self.reason = reason
        self.metadata = metadata or {}

    def to_dict(self) -> dict:
        """Serialize for logging/JSONL storage."""
        return {
            "decision": self.decision.value,
            "category": self.category.value,
            "policy_name": self.policy_name,
            "reason": self.reason,
            "metadata": self.metadata,
        }

    @property
    def allowed(self) -> bool:
        """True if decision is ALLOW."""
        return self.decision == Decision.ALLOW


def evaluate(
    workload_id: str,
    action: str,
    input_data: dict,
    categories: Optional[list[PolicyCategory]] = None,
) -> PolicyResult:
    """
    Evaluate policies for a given action against an input.

    Tries OPA first (HTTP); falls back to local Python evaluator if OPA unavailable.

    Args:
        workload_id: AI workload identifier (e.g., 'ws-finadvisor-001')
        action: Action being requested (e.g., 'llm_call', 'tool_invoke', 'memory_write')
        input_data: Input context (prompt, tool name, memory content, etc.)
        categories: Optional list of categories to evaluate. Defaults to all.

    Returns:
        PolicyResult — first non-ALLOW result, or ALLOW if all categories pass.
        Errors → DENY (fail-closed).
    """
    if categories is None:
        categories = list(PolicyCategory)

    start = time.time()

    try:
        # Try OPA first
        opa_url = os.getenv("OPA_URL")
        if opa_url:
            result = _evaluate_via_opa(workload_id, action, input_data, categories, opa_url)
        else:
            # No OPA configured: use local Python evaluator
            result = _evaluate_local(workload_id, action, input_data, categories)

        # Log decision (audit trail for trust scoring)
        _log_decision(workload_id, action, input_data, result, latency_ms=int((time.time() - start) * 1000))

        return result

    except Exception as e:
        logger.error(f"Policy evaluation failed: {e}", exc_info=True)
        # Fail-closed: errors default to DENY
        result = PolicyResult(
            decision=Decision.DENY,
            category=PolicyCategory.ORG_MANDATORY,
            policy_name="evaluation_error",
            reason=f"Policy evaluator raised {type(e).__name__}: {e}",
        )
        _log_decision(workload_id, action, input_data, result, latency_ms=int((time.time() - start) * 1000))
        return result


def _evaluate_via_opa(
    workload_id: str,
    action: str,
    input_data: dict,
    categories: list[PolicyCategory],
    opa_url: str,
) -> PolicyResult:
    """Evaluate policies via OPA HTTP API."""
    try:
        import requests
    except ImportError:
        logger.warning("requests library not available; falling back to local evaluator")
        return _evaluate_local(workload_id, action, input_data, categories)

    payload = {
        "input": {
            "workload_id": workload_id,
            "action": action,
            **input_data,
        }
    }

    for category in categories:
        # OPA query path follows convention: /v1/data/aigovern/{category}/decision
        category_path = category.value.replace("-", "_")
        url = f"{opa_url}/v1/data/aigovern/{category_path}/decision"

        try:
            response = requests.post(url, json=payload, timeout=2.0)
            response.raise_for_status()
            result_data = response.json().get("result", {})

            decision_str = result_data.get("decision", "DENY")  # Default DENY if not specified
            decision = Decision(decision_str) if decision_str in Decision._value2member_map_ else Decision.DENY

            if decision != Decision.ALLOW:
                return PolicyResult(
                    decision=decision,
                    category=category,
                    policy_name=result_data.get("policy_name", f"{category.value}_default"),
                    reason=result_data.get("reason", "Policy denied"),
                    metadata=result_data.get("metadata", {}),
                )

        except requests.exceptions.RequestException as e:
            logger.warning(f"OPA query failed for {category.value}: {e}; falling back to local")
            return _evaluate_local(workload_id, action, input_data, [category])

    # All categories ALLOW
    return PolicyResult(
        decision=Decision.ALLOW,
        category=PolicyCategory.ORG_MANDATORY,
        policy_name="all_categories_pass",
        reason="All policy categories returned ALLOW",
    )


def _evaluate_local(
    workload_id: str,
    action: str,
    input_data: dict,
    categories: list[PolicyCategory],
) -> PolicyResult:
    """
    Local Python policy evaluator — fallback when OPA is unavailable.

    Implements the core policies inline. This is a safety net, not a replacement
    for OPA in production. Logs a warning every time it's used.
    """
    logger.debug(f"Local policy evaluation: workload={workload_id}, action={action}")

    # Category 1: org-mandatory — non-negotiable rules
    if PolicyCategory.ORG_MANDATORY in categories:
        result = _check_org_mandatory(workload_id, action, input_data)
        if not result.allowed:
            return result

    # Category 2: posture — regulatory/compliance
    if PolicyCategory.POSTURE in categories:
        result = _check_posture(workload_id, action, input_data)
        if not result.allowed:
            return result

    # Category 3: risk-tier — risk-tier-specific
    if PolicyCategory.RISK_TIER in categories:
        result = _check_risk_tier(workload_id, action, input_data)
        if not result.allowed:
            return result

    # Category 4: team — per-team policies
    if PolicyCategory.TEAM in categories:
        result = _check_team(workload_id, action, input_data)
        if not result.allowed:
            return result

    # Category 5: system-override — emergency overrides
    if PolicyCategory.SYSTEM_OVERRIDE in categories:
        result = _check_system_override(workload_id, action, input_data)
        if not result.allowed:
            return result

    return PolicyResult(
        decision=Decision.ALLOW,
        category=PolicyCategory.ORG_MANDATORY,
        policy_name="all_local_checks_pass",
        reason="All local policy checks passed",
    )


def _check_org_mandatory(workload_id: str, action: str, input_data: dict) -> PolicyResult:
    """Org-mandatory: rules every workload must follow."""
    # Rule 1: PII never sent raw to external services
    # If action is llm_call/trace_call and prompt has raw PII markers, deny
    prompt = input_data.get("prompt", "")

    # Quick PII detection (regex-only; full check via scrubber)
    import re
    has_ssn = bool(re.search(r'\b\d{3}-\d{2}-\d{4}\b', prompt))
    has_email = bool(re.search(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', prompt))
    has_credit_card = bool(re.search(r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b', prompt))

    if action in ("llm_call", "trace_call", "external_api") and (has_ssn or has_email or has_credit_card):
        # Check if scrubbed (has tokens like [EMAIL_001])
        has_tokens = bool(re.search(r'\[(PERSON|EMAIL|SSN|US_SSN|PHONE|CREDIT_CARD)_\d{3}\]', prompt))
        if not has_tokens:
            return PolicyResult(
                decision=Decision.DENY,
                category=PolicyCategory.ORG_MANDATORY,
                policy_name="pii_no_raw_to_external",
                reason="Raw PII detected in prompt; must be scrubbed before external call",
                metadata={"detected": {"ssn": has_ssn, "email": has_email, "credit_card": has_credit_card}},
            )

    return PolicyResult(
        decision=Decision.ALLOW,
        category=PolicyCategory.ORG_MANDATORY,
        policy_name="org_mandatory_pass",
    )


def _check_posture(workload_id: str, action: str, input_data: dict) -> PolicyResult:
    """Posture: regulatory/compliance (US-FinServ, EU AI Act, etc.)."""
    posture = input_data.get("posture", "")

    if posture == "us-finserv":
        # US-FinServ: financial advice tools require disclaimers
        if action == "llm_call" and input_data.get("domain") == "finance":
            response = input_data.get("response", "")
            # If response gives stock picks without disclaimer, REVIEW
            if response and any(
                term in response.lower() for term in ["buy", "sell", "recommend", "guarantee"]
            ):
                if not any(
                    disclaimer in response.lower()
                    for disclaimer in ["not financial advice", "disclaimer", "risk", "consult"]
                ):
                    return PolicyResult(
                        decision=Decision.REVIEW,
                        category=PolicyCategory.POSTURE,
                        policy_name="us_finserv_disclaimer_required",
                        reason="Financial advice response missing required disclaimer",
                        metadata={"posture": posture},
                    )

    return PolicyResult(
        decision=Decision.ALLOW,
        category=PolicyCategory.POSTURE,
        policy_name="posture_pass",
    )


def _check_risk_tier(workload_id: str, action: str, input_data: dict) -> PolicyResult:
    """Risk-tier: CRITICAL tier requires human-in-the-loop."""
    risk_tier = input_data.get("risk_tier", "MEDIUM").upper()

    if risk_tier == "CRITICAL":
        # CRITICAL workloads cannot make autonomous decisions
        if action in ("tool_invoke", "external_api", "memory_write"):
            return PolicyResult(
                decision=Decision.REVIEW,
                category=PolicyCategory.RISK_TIER,
                policy_name="critical_human_in_loop",
                reason="CRITICAL risk-tier workloads require human approval for actions",
                metadata={"risk_tier": risk_tier},
            )

    return PolicyResult(
        decision=Decision.ALLOW,
        category=PolicyCategory.RISK_TIER,
        policy_name="risk_tier_pass",
    )


def _check_team(workload_id: str, action: str, input_data: dict) -> PolicyResult:
    """Team: per-team rules."""
    team = input_data.get("team", "")

    if team == "payments":
        # Payments team: tool invocations require pre-authorization
        if action == "tool_invoke":
            tool_name = input_data.get("tool_name", "")
            if tool_name and not input_data.get("preauthorized", False):
                return PolicyResult(
                    decision=Decision.DENY,
                    category=PolicyCategory.TEAM,
                    policy_name="payments_tool_preauth_required",
                    reason="Payments team requires pre-authorization for tool invocations",
                    metadata={"team": team, "tool": tool_name},
                )

    return PolicyResult(
        decision=Decision.ALLOW,
        category=PolicyCategory.TEAM,
        policy_name="team_pass",
    )


def _check_system_override(workload_id: str, action: str, input_data: dict) -> PolicyResult:
    """System-override: emergency overrides (always last)."""
    if input_data.get("system_override_active"):
        override_reason = input_data.get("override_reason", "unspecified")
        return PolicyResult(
            decision=Decision.ALLOW,
            category=PolicyCategory.SYSTEM_OVERRIDE,
            policy_name="system_override_grant",
            reason=f"System override active: {override_reason}",
            metadata={"override_reason": override_reason, "audit_critical": True},
        )

    return PolicyResult(
        decision=Decision.ALLOW,
        category=PolicyCategory.SYSTEM_OVERRIDE,
        policy_name="no_override_active",
    )


def _log_decision(
    workload_id: str,
    action: str,
    input_data: dict,
    result: PolicyResult,
    latency_ms: int,
) -> None:
    """Append policy decision to audit log (used by trust scorer)."""
    try:
        import storage

        # Don't log full input (could contain PII even after scrubbing)
        sanitized_input = {
            k: v for k, v in input_data.items()
            if k not in ("prompt", "response")  # Skip large/sensitive fields
        }
        sanitized_input["prompt_hash"] = str(hash(str(input_data.get("prompt", ""))) % 10**8)

        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "workload_id": workload_id,
            "action": action,
            "input_summary": sanitized_input,
            "result": result.to_dict(),
            "latency_ms": latency_ms,
        }
        storage._append_jsonl(POLICY_DECISIONS_FILE, record)

    except Exception as e:
        logger.error(f"Failed to log policy decision: {e}")


def policy_stats() -> dict:
    """
    Return policy decision statistics for /api/policies/stats endpoint.

    Returns:
        Dict with total decisions, ALLOW/DENY/REVIEW counts, by category
    """
    try:
        import storage

        if not POLICY_DECISIONS_FILE.exists():
            return {
                "total": 0,
                "by_decision": {"ALLOW": 0, "DENY": 0, "REVIEW": 0},
                "by_category": {},
                "denial_rate": 0.0,
            }

        records = storage._read_jsonl(POLICY_DECISIONS_FILE)
        total = len(records)
        by_decision = {"ALLOW": 0, "DENY": 0, "REVIEW": 0}
        by_category = {}

        for record in records:
            result = record.get("result", {})
            decision = result.get("decision", "DENY")
            category = result.get("category", "unknown")

            by_decision[decision] = by_decision.get(decision, 0) + 1
            by_category[category] = by_category.get(category, 0) + 1

        denial_rate = (by_decision.get("DENY", 0) / total) if total > 0 else 0.0

        return {
            "total": total,
            "by_decision": by_decision,
            "by_category": by_category,
            "denial_rate": round(denial_rate, 4),
        }

    except Exception as e:
        logger.error(f"policy_stats failed: {e}")
        return {"total": 0, "by_decision": {}, "by_category": {}, "denial_rate": 0.0}


if __name__ == "__main__":
    # Smoke test
    print("Testing policy_engine...\n")

    # Test 1: Allow case
    result = evaluate(
        workload_id="ws-test-001",
        action="llm_call",
        input_data={"prompt": "What is the weather?", "domain": "general"},
    )
    print(f"Test 1 (clean prompt): {result.decision.value} — {result.reason}")
    assert result.allowed, "Clean prompt should be ALLOW"

    # Test 2: Deny case (raw PII)
    result = evaluate(
        workload_id="ws-test-002",
        action="llm_call",
        input_data={"prompt": "Client john@example.com SSN 123-45-6789"},
    )
    print(f"Test 2 (raw PII): {result.decision.value} — {result.reason}")
    assert result.decision == Decision.DENY, "Raw PII should be DENY"

    # Test 3: Scrubbed PII (should allow)
    result = evaluate(
        workload_id="ws-test-003",
        action="llm_call",
        input_data={"prompt": "Client [EMAIL_001] SSN [US_SSN_001]"},
    )
    print(f"Test 3 (scrubbed PII): {result.decision.value} — {result.reason}")
    assert result.allowed, "Scrubbed PII should be ALLOW"

    # Test 4: Stats
    stats = policy_stats()
    print(f"Test 4 (stats): {stats}")
    assert stats["total"] > 0

    print("\n[PASS] All policy_engine smoke tests passed")
