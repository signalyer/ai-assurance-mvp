"""GRC API endpoints — AI risk operations data."""

from fastapi import APIRouter, HTTPException, Query
from mock_data import (
    AI_SYSTEMS,
    FINDINGS,
    RELEASE_GATE_RULES,
    RELEASE_GATE_RESULTS,
    NIST_AI_RMF,
    AI_600_1_PROFILE,
    OWASP_LLM_TOP10,
    OWASP_AGENTIC,
    RUNTIME_EVENTS,
    POLICIES,
    EVIDENCE,
)
# Real-data portfolio aggregations replace the hardcoded mock constants
# (NEXT_ACTIONS, HOMEPAGE_RUNTIME_EVENTS, HOMEPAGE_CRITICAL_FINDINGS, compute_kpis)
# so every Overview metric ties to a real AI system, control, finding, gate,
# evidence, or runtime event.
from domain.portfolio import (
    compute_kpis,
    homepage_runtime_events,
    homepage_critical_findings,
    next_actions,
    threat_series_7d,
)
from domain.notifications import summary as notifications_summary
from domain.notifications import mark_resolved as notifications_mark_resolved
from domain.notifications import clear_resolved as notifications_clear_resolved

router = APIRouter(prefix="/api/grc", tags=["grc"])


# === Command Center ===

@router.get("/kpis")
async def get_kpis() -> dict:
    """Top-level KPIs for command center."""
    return compute_kpis()


@router.get("/next-actions")
async def get_next_actions() -> dict:
    """Next actions queue — derived from open findings, release holds, and waivers."""
    return {"actions": next_actions()}


@router.get("/homepage/runtime-events")
async def get_homepage_runtime_events() -> dict:
    """Most recent runtime events across all governed AI systems."""
    return {"events": homepage_runtime_events()}


@router.get("/homepage/critical-findings")
async def get_homepage_critical_findings() -> dict:
    """Open CRITICAL/HIGH findings across the portfolio, worst-SLA first."""
    return {"findings": homepage_critical_findings()}


@router.get("/homepage/threat-series")
async def get_threat_series() -> dict:
    """7-day threat-activity series, bucketed from real runtime events."""
    return threat_series_7d()


# === Notifications (AI Risk Operations notification center) ===

@router.get("/notifications")
async def get_notifications(tab: str | None = None, severity: str | None = None,
                              category: str | None = None,
                              include_resolved: bool = False) -> dict:
    s = notifications_summary()
    items = s["items"]
    if not include_resolved:
        items = [n for n in items if not n["resolved"]]
    if tab and tab != "all":
        items = [n for n in items if n["tab"] == tab]
    if severity:
        items = [n for n in items if n["severity"] == severity]
    if category:
        items = [n for n in items if n["category"] == category]
    return {**s, "items": items}


@router.post("/notifications/{notif_id}/resolve")
async def resolve_notification(notif_id: str) -> dict:
    rec = notifications_mark_resolved(notif_id, actor="user")
    return {"ok": True, **rec}


@router.post("/notifications/reset")
async def reset_notifications() -> dict:
    """Clear all 'resolved' overrides — restores the inbox to its computed state."""
    notifications_clear_resolved()
    return {"ok": True}


# === AI Systems ===

@router.get("/ai-systems")
async def list_ai_systems() -> dict:
    """List all AI systems."""
    return {"systems": AI_SYSTEMS, "total": len(AI_SYSTEMS)}


@router.get("/ai-systems/{system_id}")
async def get_ai_system(system_id: str) -> dict:
    """Get details of one AI system."""
    system = next((s for s in AI_SYSTEMS if s["id"] == system_id), None)
    if not system:
        raise HTTPException(status_code=404, detail="System not found")

    # Enrich with related data
    findings = [f for f in FINDINGS if f["system_id"] == system_id]
    gates = RELEASE_GATE_RESULTS.get(system_id)
    evidence = [e for e in EVIDENCE if e["system_id"] == system_id]
    events = [e for e in RUNTIME_EVENTS if e["system_id"] == system_id]

    return {
        **system,
        "findings": findings,
        "release_gates": gates,
        "evidence": evidence,
        "recent_events": events,
    }


# === Findings ===

@router.get("/findings")
async def list_findings(
    severity: str = Query(None),
    status: str = Query(None),
    system_id: str = Query(None),
) -> dict:
    """List findings with optional filters."""
    findings = FINDINGS

    if severity:
        findings = [f for f in findings if f["severity"] == severity.upper()]
    if status:
        findings = [f for f in findings if f["status"] == status.upper()]
    if system_id:
        findings = [f for f in findings if f["system_id"] == system_id]

    # Sort: CRITICAL first, then by SLA remaining
    severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    findings = sorted(findings, key=lambda f: (
        severity_order.get(f["severity"], 99),
        f.get("sla_remaining_hours", 9999)
    ))

    return {"findings": findings, "total": len(findings)}


@router.get("/findings/{finding_id}")
async def get_finding(finding_id: str) -> dict:
    """Get a specific finding."""
    finding = next((f for f in FINDINGS if f["id"] == finding_id), None)
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")
    return finding


# === Release Gates ===

@router.get("/release-gates/rules")
async def get_gate_rules() -> dict:
    """Get gate rule definitions."""
    return {"rules": RELEASE_GATE_RULES}


@router.get("/release-gates/results")
async def get_all_gate_results() -> dict:
    """Get gate results for all systems."""
    return {"results": list(RELEASE_GATE_RESULTS.values())}


@router.get("/release-gates/{system_id}")
async def get_gate_result(system_id: str) -> dict:
    """Get gate results for a specific system."""
    result = RELEASE_GATE_RESULTS.get(system_id)
    if not result:
        raise HTTPException(status_code=404, detail="Gate results not found")
    return result


# === Governance ===

@router.get("/governance/nist-ai-rmf")
async def get_nist_rmf() -> dict:
    """NIST AI Risk Management Framework posture."""
    return NIST_AI_RMF


@router.get("/governance/ai-600-1")
async def get_ai_600_1() -> dict:
    """NIST AI 600-1 GenAI Profile coverage."""
    return AI_600_1_PROFILE


# === Security ===

@router.get("/security/owasp-llm")
async def get_owasp_llm() -> dict:
    """OWASP Top 10 for LLM Applications status."""
    return {"items": OWASP_LLM_TOP10}


@router.get("/security/owasp-agentic")
async def get_owasp_agentic() -> dict:
    """OWASP Top 10 for Agentic AI status."""
    return {"items": OWASP_AGENTIC}


# === Runtime ===

@router.get("/runtime/events")
async def get_runtime_events(limit: int = Query(50, ge=1, le=500)) -> dict:
    """Get recent runtime events."""
    events = sorted(RUNTIME_EVENTS, key=lambda e: e["timestamp"], reverse=True)[:limit]
    return {"events": events}


# === Policies ===

@router.get("/policies")
async def list_policies() -> dict:
    """List all policy controls."""
    return {"policies": POLICIES, "total": len(POLICIES)}


@router.get("/policies/{policy_id}")
async def get_policy(policy_id: str) -> dict:
    """Get a specific policy."""
    policy = next((p for p in POLICIES if p["id"] == policy_id), None)
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    return policy


# === Evidence ===

@router.get("/evidence")
async def list_evidence(
    system_id: str = Query(None),
    evidence_type: str = Query(None),
) -> dict:
    """List evidence with optional filters."""
    evidence = EVIDENCE
    if system_id:
        evidence = [e for e in evidence if e["system_id"] == system_id]
    if evidence_type:
        evidence = [e for e in evidence if e["type"] == evidence_type]
    return {"evidence": evidence, "total": len(evidence)}
