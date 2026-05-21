"""Tooltip content registry — keyed by stable IDs.

Each entry is what hover-help shows for a single visual element: what it
measures, how it's computed, where the data comes from. Same backbone the
AI Governance Assistant uses, so there's one source of truth.

Phase A scope: 8 Overview KPIs. Add entries here as more pages are wired.
"""

from __future__ import annotations


TIPS: dict[str, dict] = {

    # ---- Overview KPIs ----

    "kpi.enterprise_ai_risk_score": {
        "title": "Enterprise AI Risk Score",
        "description": (
            "Portfolio AI risk posture on a 0–100 scale (higher = safer). "
            "Single number that summarizes how much exposure remains across every "
            "governed AI system right now."
        ),
        "formula": (
            "score = clamp(0..100, avg_overall_score − 0.4 × (8·CRIT + 3·HIGH + "
            "2·SLA_breached + 5·HOLD + 8·REJECT) + 60)"
        ),
        "source": (
            "Derived live from run_assessment() across every governed system + "
            "open findings + release decisions."
        ),
    },

    "kpi.ai_systems_governed": {
        "title": "AI Systems Governed",
        "description": (
            "Every AI system in scope of the assurance platform — production, "
            "pilot, staged, or in design. Includes seed systems plus any "
            "intake-registered systems."
        ),
        "formula": "len(repository.list_ai_systems())",
        "source": (
            "Seed AI_SYSTEMS in domain/seed.py plus intake records in "
            "data/ai_systems.jsonl."
        ),
    },

    "kpi.production_ai_systems": {
        "title": "Production AI Systems",
        "description": (
            "Systems whose runtime_status = PRODUCTION. These have passed every "
            "release gate and carry full executive approval."
        ),
        "formula": "count(s where s.runtime_status = PRODUCTION)",
        "source": "AISystem.runtime_status field on every governed system.",
    },

    "kpi.high_risk_findings": {
        "title": "High-Risk Findings",
        "description": (
            "Open findings with severity CRITICAL or HIGH across the portfolio. "
            "Each one maps to ≥1 control and ≥1 framework; the CRITICAL bucket "
            "always blocks production release."
        ),
        "formula": (
            "count(f where f.severity ∈ {CRITICAL, HIGH} and "
            "f.status ∈ {OPEN, IN_PROGRESS})"
        ),
        "source": (
            "Findings workflow (seed FINDINGS + connector overlay + workflow "
            "events). Trend line breaks the total into CRITICAL / HIGH / "
            "SLA-breached so you can see the shape, not just the count."
        ),
    },

    "kpi.release_holds": {
        "title": "Release Holds",
        "description": (
            "Number of governed AI systems whose latest assessment returned "
            "release_decision = HOLD. Each hold blocks the system from "
            "production until the rule fired is resolved."
        ),
        "formula": (
            "count(s where run_assessment(s).release_recommendation.decision = HOLD)"
        ),
        "source": (
            "Assessment Engine — generate_release_recommendation. The rule "
            "fired (R-Hold-P0-Open, R-Hold-PII-Eval, …) is shown on the system's "
            "page and on the Reports view."
        ),
    },

    "kpi.runtime_incidents": {
        "title": "Runtime Incidents",
        "description": (
            "Lifetime count of runtime events worth investigator attention: "
            "prompt injection blocked, PII leak blocked, unauthorized tool "
            "calls, jailbreak attempts, hallucinations detected."
        ),
        "formula": (
            "count(ev where ev.event_type ∈ {PROMPT_INJECTION_BLOCKED, "
            "PII_LEAK_BLOCKED, UNAUTHORIZED_TOOL_CALL, JAILBREAK_ATTEMPT, "
            "HALLUCINATION_DETECTED})"
        ),
        "source": (
            "Runtime events ingested from Langfuse, AWS CloudTrail / Security "
            "Hub / Macie / GuardDuty, Bedrock Guardrails, and policy gateways."
        ),
    },

    "kpi.policy_violations": {
        "title": "Policy Violations",
        "description": (
            "Runtime events of type POLICY_VIOLATION — guardrail policy fired "
            "and blocked or escalated the action. Each violation is mapped to "
            "the policy id that triggered."
        ),
        "formula": "count(ev where ev.event_type = POLICY_VIOLATION)",
        "source": "Runtime events filtered by event_type.",
    },

    "kpi.evidence_completeness": {
        "title": "Evidence Completeness",
        "description": (
            "Portfolio average of evidence_completeness across every system. "
            "Each system's score is the fraction of (control, required_evidence_type) "
            "pairs that have a matching evidence record. Anything below 85% is a "
            "release-gate concern."
        ),
        "formula": (
            "mean( count(present_pairs) / count(required_pairs) ) over all "
            "governed systems"
        ),
        "source": (
            "domain/evidence_repository.completeness_by_ai_system + each control's "
            "evidence_required list."
        ),
    },
}


def get_tip(tip_id: str) -> dict | None:
    return TIPS.get(tip_id)


def all_tips() -> dict[str, dict]:
    return TIPS


__all__ = ["TIPS", "get_tip", "all_tips"]
