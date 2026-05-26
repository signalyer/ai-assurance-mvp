"""GRC API endpoints -- AI risk operations data.

Typed per docs/plans/SESSION-13-api-typing-audit.md §3.1 + §4.
Pattern follows the api/frameworks.py exemplar: inline Pydantic v2 response models
with model_config = ConfigDict(extra='forbid'), explicit operation_id on every route,
response_model on every route.

NOTE on opaque dict fields (notifications counts_by_*, generated_at, etc.): the
notifications domain emits a stable summary contract that the V1 UI deeply
introspects. Until that contract is itself typed in domain/notifications.py, we
type the outer envelope here and pass the inner `counts_by_*` maps through as
`dict[str, int]`. This is intentional pragmatic scoping; tightening these is a
Phase 1.5 follow-up.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from middleware.data_mode import filter_by_mode, get_data_mode

# S55 #3 / F-010: intake-written AI systems live in data/ai_systems.jsonl;
# the inventory list endpoint used to ONLY read mock_data.AI_SYSTEMS (the
# 5 seeds), so real-mode customer intakes never appeared in the portfolio.
# Pull the intake rows via the repository at request time and merge into
# the view-shape AiSystemSummaryOut below.
from domain.repository import list_ai_systems as _list_intake_systems

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

from api._models import OkResponse

router = APIRouter(prefix="/api/grc", tags=["grc"])


# ---------------------------------------------------------------------------
# Cross-cutting helpers
# ---------------------------------------------------------------------------

def _strict() -> ConfigDict:
    """Pydantic config shared by every response model in this router."""
    return ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Command Center models
# ---------------------------------------------------------------------------

class KpisOut(BaseModel):
    """Top-level KPI dashboard for command center.

    All fields populated by domain.portfolio.compute_kpis() against live mock data.
    Adding a field here = minor __version__ bump.
    """
    model_config = _strict()

    enterprise_ai_risk_score: int
    risk_score_trend: str
    risk_level: str
    ai_systems_reviewed: int
    ai_systems_trend: str
    production_ai_systems: int
    production_trend: str
    high_risk_findings: int
    high_risk_trend: str
    release_holds: int
    release_holds_trend: str
    runtime_incidents_24h: int
    runtime_trend: str
    policy_violations_24h: int
    policy_violations_trend: str
    evidence_completeness: int
    evidence_trend: str
    total_findings: int
    open_findings: int
    # Aggregated stats blobs -- typed as dicts for now; tighten in Phase 1.5
    # if SPA needs per-key typing. Keys are stable.
    release_gates: dict[str, int] = Field(
        description="Counts by gate decision (hold/conditional/approved/reject).",
    )
    frameworks: dict[str, float] = Field(
        description="Per-framework coverage % (nist_ai_rmf, nist_ai_600_1, owasp_*, iso_iec_23894).",
    )
    runtime_activity: dict[str, int] = Field(
        description="24h runtime activity counts (prompt_injection, blocked_tool_calls, etc.).",
    )
    sla: dict[str, int] = Field(
        description="Finding SLA buckets (overdue, due_7d, due_30d, closed).",
    )
    generated_at: str


class NextActionOut(BaseModel):
    model_config = _strict()

    title: str
    priority: str
    due: str
    ref_ids: list[str]


class NextActionsOut(BaseModel):
    model_config = _strict()
    actions: list[NextActionOut]


class HomepageRuntimeEventOut(BaseModel):
    """Homepage runtime event row (portfolio aggregation shape).

    NOTE: this is a DIFFERENT shape from RuntimeEventOut below. The homepage
    strip is fed by domain.portfolio.homepage_runtime_events() which joins
    runtime events with policy/control/framework context; the /runtime/events
    endpoint returns the raw mock_data shape (id/timestamp/system_id/...).
    Two different shapes for two different consumers -- locked here so
    Schemathesis catches future drift.
    """
    model_config = _strict()

    id: str
    time: str = Field(description="HH:MM display string, derived from timestamp.")
    timestamp: str
    system: str = Field(description="System name (denormalised).")
    ai_system_id: str
    event_type: str
    severity: str
    action: str
    source: str
    linked_control: str | None = None
    linked_framework: str | None = None
    policy_triggered: str | None = None
    evidence_id: str | None = None


class HomepageEventsOut(BaseModel):
    model_config = _strict()
    events: list[HomepageRuntimeEventOut]


class HomepageFindingOut(BaseModel):
    """Homepage critical-finding row (portfolio aggregation shape).

    NOTE: different shape from FindingOut. Portfolio aggregator returns a
    pre-formatted row with `system` (name) and `time_ago` (display), not the
    full finding record.
    """
    model_config = _strict()

    id: str
    title: str
    system: str = Field(description="System name (denormalised).")
    severity: str = Field(description="P0 / P1 / etc. — portfolio uses priority labels, not CRITICAL/HIGH.")
    control_id: str | None = None
    framework: str | None = None
    time_ago: str = Field(description="Human display like '6d ago'.")


class HomepageFindingsOut(BaseModel):
    model_config = _strict()
    findings: list[HomepageFindingOut]


class ThreatSeriesOut(BaseModel):
    """7-day threat-activity series, bucketed from real runtime events."""
    model_config = _strict()

    x_labels: list[str]
    series: dict[str, list[int]] = Field(
        description=(
            "Map of series_name -> daily counts. Series keys are stable: "
            "prompt_injection, blocked_tool_calls, policy_violations, dlp_detections."
        ),
    )


# ---------------------------------------------------------------------------
# Notifications models
# ---------------------------------------------------------------------------

class NotificationItemOut(BaseModel):
    """One notification in the AI Risk Operations notification center."""
    model_config = _strict()

    id: str
    category: str
    tab: str
    severity: str
    title: str
    detail: str
    system_id: str | None = None
    system_name: str | None = None
    framework: str | None = None
    control_id: str | None = None
    gate_id: str | None = None
    timestamp: str
    action_required: str
    linked_workflow: str | None = None
    ref_id: str | None = None
    resolved: bool


class NotificationsOut(BaseModel):
    """Notification center summary + filtered items."""
    model_config = _strict()

    unread: int
    total: int
    counts_by_tab: dict[str, int]
    counts_by_severity: dict[str, int]
    counts_by_category: dict[str, int]
    items: list[NotificationItemOut]
    categories: dict[str, str] = Field(
        description="Map of category enum -> display label (CRITICAL_FINDING -> 'Critical Findings' etc.).",
    )
    generated_at: str


# ---------------------------------------------------------------------------
# AI Systems models
# ---------------------------------------------------------------------------

class AiSystemSummaryOut(BaseModel):
    """Compact AI system row for the portfolio list view."""
    model_config = _strict()

    id: str
    name: str
    business_owner: str
    technical_owner: str
    domain: str
    description: str
    risk_level: str
    autonomy_level: str
    data_classes: list[str]
    model: str
    runtime_status: str
    release_decision: str
    open_findings: int
    critical_findings: int
    last_assessment: str
    next_assessment: str
    deployment_target: str
    use_case: str
    human_oversight: str
    data_residency: str
    trust_boundaries: str
    data_source: str = "seed"


class AiSystemsListOut(BaseModel):
    """Portfolio list response. `total` is cheap to compute (mock data)."""
    model_config = _strict()

    systems: list[AiSystemSummaryOut]
    total: int


class AiSystemDetailOut(AiSystemSummaryOut):
    """AI system detail view: summary fields + enrichments.

    Extending AiSystemSummaryOut keeps the field list authoritative in one place.
    `model_config` is inherited; `extra='forbid'` still applies.
    """
    findings: list[dict[str, Any]] = Field(
        description="Findings linked to this system (FindingDetailOut shape; loosely typed for V1 compat).",
    )
    release_gates: dict[str, Any] | None = Field(
        default=None,
        description="GateResultOut shape if results exist; null otherwise. Loosely typed for V1 compat.",
    )
    evidence: list[dict[str, Any]] = Field(
        description="Evidence linked to this system (EvidenceSummaryOut shape; loosely typed for V1 compat).",
    )
    recent_events: list[dict[str, Any]] = Field(
        description="Runtime events for this system (HomepageRuntimeEventOut shape; loosely typed for V1 compat).",
    )


# ---------------------------------------------------------------------------
# Findings models
# ---------------------------------------------------------------------------

class FindingOut(BaseModel):
    """A single governance finding."""
    model_config = _strict()

    id: str
    severity: str
    title: str
    system_id: str
    system_name: str
    framework_mapping: list[str]
    owner: str
    owner_email: str
    sla_days: int
    sla_remaining_hours: int
    status: str
    release_impact: str
    discovered: str
    description: str
    evidence_ids: list[str]
    data_source: str = "seed"


class FindingsListOut(BaseModel):
    """Findings collection response."""
    model_config = _strict()

    findings: list[FindingOut]
    total: int


# ---------------------------------------------------------------------------
# Release Gates models
# ---------------------------------------------------------------------------

class GateRuleOut(BaseModel):
    model_config = _strict()

    id: str
    name: str
    rule: str
    severity: str


class GateRulesOut(BaseModel):
    model_config = _strict()
    rules: list[GateRuleOut]


class GateCheckOut(BaseModel):
    model_config = _strict()

    id: str
    passed: bool
    actual: str
    note: str | None = None


class GateResultOut(BaseModel):
    model_config = _strict()

    system_id: str
    system_name: str
    overall_status: str
    decision: str
    approver: str
    decision_date: str
    gates: list[GateCheckOut]


class GateResultsOut(BaseModel):
    model_config = _strict()
    results: list[GateResultOut]


# ---------------------------------------------------------------------------
# Governance framework models
# ---------------------------------------------------------------------------

class NistFunctionOut(BaseModel):
    """One NIST AI RMF function (GOVERN / MAP / MEASURE / MANAGE)."""
    model_config = _strict()

    function: str
    score: int
    required_controls: int
    passing_controls: int
    failing_controls: int
    evidence_completeness: float
    key_gaps: list[str]


class NistRmfOut(BaseModel):
    """NIST AI Risk Management Framework posture."""
    model_config = _strict()
    frameworks: list[NistFunctionOut]


class AI600_1RiskAreaOut(BaseModel):
    """One risk area in the NIST AI 600-1 GenAI Profile."""
    model_config = _strict()

    id: str
    name: str
    coverage: float
    status: str


class AI600_1Out(BaseModel):
    """NIST AI 600-1 GenAI Profile coverage."""
    model_config = _strict()

    title: str
    overall_coverage: float
    risk_areas: list[AI600_1RiskAreaOut]


# ---------------------------------------------------------------------------
# OWASP models
# ---------------------------------------------------------------------------

class OwaspItemOut(BaseModel):
    """One OWASP Top 10 item (LLM or Agentic AI)."""
    model_config = _strict()

    id: str
    name: str
    open_findings: int
    critical: int
    systems_affected: int
    status: str


class OwaspListOut(BaseModel):
    model_config = _strict()
    items: list[OwaspItemOut]


# ---------------------------------------------------------------------------
# Runtime models
# ---------------------------------------------------------------------------

class RuntimeEventOut(BaseModel):
    """A single runtime event."""
    model_config = _strict()

    id: str
    timestamp: str
    system_id: str
    system_name: str
    event_type: str
    severity: str
    description: str
    action_taken: str | None = None
    evidence_id: str | None = None


class RuntimeEventsOut(BaseModel):
    model_config = _strict()
    events: list[RuntimeEventOut]


# ---------------------------------------------------------------------------
# Policies models
# ---------------------------------------------------------------------------

class PolicyOut(BaseModel):
    """A governance policy / control requirement."""
    model_config = _strict()

    id: str
    requirement: str
    framework_mappings: list[str]
    severity: str
    evidence_required: list[str]
    pass_criteria: str
    owner: str
    automation_status: str
    compliant_systems: int
    non_compliant_systems: int
    data_source: str = "seed"


class PoliciesOut(BaseModel):
    model_config = _strict()

    policies: list[PolicyOut]
    total: int


# ---------------------------------------------------------------------------
# Evidence models
# ---------------------------------------------------------------------------

class EvidenceOut(BaseModel):
    """An evidence artifact attached to systems/findings/controls."""
    model_config = _strict()

    id: str
    type: str
    system_id: str
    system_name: str
    title: str
    created: str
    linked_findings: list[str]
    author: str
    format: str
    data_source: str = "seed"


class EvidenceListOut(BaseModel):
    model_config = _strict()

    evidence: list[EvidenceOut]
    total: int


# ---------------------------------------------------------------------------
# Notification resolve response (echoes the resolved item per audit §10 res #4)
# ---------------------------------------------------------------------------

class NotificationResolveOut(BaseModel):
    """Echo of the resolved notification + ok flag.

    Per audit doc §10 resolution #4: state-changing mutations echo the resource
    state so the client doesn't need a re-fetch.
    """
    model_config = _strict()

    ok: bool = True
    id: str
    resolved: bool
    resolved_at: str | None = None
    resolved_by: str | None = None


# ===========================================================================
# === Command Center endpoints
# ===========================================================================

@router.get("/kpis", response_model=KpisOut, operation_id="grc_kpis")
async def get_kpis() -> KpisOut:
    """Top-level KPIs for command center."""
    return KpisOut(**compute_kpis())


@router.get(
    "/next-actions",
    response_model=NextActionsOut,
    operation_id="grc_next_actions",
)
async def get_next_actions() -> NextActionsOut:
    """Next actions queue -- derived from open findings, release holds, and waivers."""
    return NextActionsOut(actions=[NextActionOut(**a) for a in next_actions()])


@router.get(
    "/homepage/runtime-events",
    response_model=HomepageEventsOut,
    operation_id="grc_homepage_runtime_events",
)
async def get_homepage_runtime_events() -> HomepageEventsOut:
    """Most recent runtime events across all governed AI systems."""
    return HomepageEventsOut(
        events=[HomepageRuntimeEventOut(**e) for e in homepage_runtime_events()],
    )


@router.get(
    "/homepage/critical-findings",
    response_model=HomepageFindingsOut,
    operation_id="grc_homepage_critical_findings",
)
async def get_homepage_critical_findings() -> HomepageFindingsOut:
    """Open CRITICAL/HIGH findings across the portfolio, worst-SLA first."""
    return HomepageFindingsOut(
        findings=[HomepageFindingOut(**f) for f in homepage_critical_findings()],
    )


@router.get(
    "/homepage/threat-series",
    response_model=ThreatSeriesOut,
    operation_id="grc_homepage_threat_series",
)
async def get_threat_series() -> ThreatSeriesOut:
    """7-day threat-activity series, bucketed from real runtime events."""
    return ThreatSeriesOut(**threat_series_7d())


# ===========================================================================
# === Notifications (AI Risk Operations notification center)
# ===========================================================================

@router.get(
    "/notifications",
    response_model=NotificationsOut,
    operation_id="notifications_list",
)
async def get_notifications(
    tab: str | None = None,
    severity: str | None = None,
    category: str | None = None,
    include_resolved: bool = False,
) -> NotificationsOut:
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
    return NotificationsOut(
        unread=s["unread"],
        total=s["total"],
        counts_by_tab=s["counts_by_tab"],
        counts_by_severity=s["counts_by_severity"],
        counts_by_category=s["counts_by_category"],
        items=[NotificationItemOut(**n) for n in items],
        categories=s["categories"],
        generated_at=s["generated_at"],
    )


@router.post(
    "/notifications/{notif_id}/resolve",
    response_model=NotificationResolveOut,
    operation_id="notifications_resolve",
)
async def resolve_notification(notif_id: str) -> NotificationResolveOut:
    """Mark a notification as resolved. Echoes the resolved state."""
    rec = notifications_mark_resolved(notif_id, actor="user")
    return NotificationResolveOut(
        id=rec.get("id", notif_id),
        resolved=rec.get("resolved", True),
        resolved_at=rec.get("resolved_at"),
        resolved_by=rec.get("resolved_by", "user"),
    )


@router.post(
    "/notifications/reset",
    response_model=OkResponse,
    operation_id="notifications_reset",
)
async def reset_notifications() -> OkResponse:
    """Clear all 'resolved' overrides -- restores the inbox to its computed state."""
    notifications_clear_resolved()
    return OkResponse()


# ===========================================================================
# === AI Systems
# ===========================================================================

@router.get(
    "/ai-systems",
    response_model=AiSystemsListOut,
    operation_id="ai_systems_list",
)
async def list_ai_systems(request: Request) -> AiSystemsListOut:
    """List all AI systems in the portfolio. Honors X-Data-Mode (v1|v2).

    S55 #3 / F-010: merges the V1 mock_data seed rows (which already match
    the AiSystemSummaryOut view shape) with intake-written rows from
    domain.repository.list_ai_systems() (which uses the canonical AISystem
    Pydantic shape). The intake rows are mapped to the view shape via
    `_intake_to_summary_view` below, filling computed fields with sensible
    zero defaults — proper enrichment from FINDINGS / GATES / EVIDENCE
    follows the seed pattern and is a sibling improvement (S56 backlog).
    """
    seed_rows = list(AI_SYSTEMS)
    intake_rows = [_intake_to_summary_view(s) for s in _list_intake_systems() if not _is_seed(s.id)]
    merged = seed_rows + intake_rows
    rows = filter_by_mode(merged, get_data_mode(request))
    return AiSystemsListOut(
        systems=[AiSystemSummaryOut(**s) for s in rows],
        total=len(rows),
    )


_SEED_SYSTEM_IDS: frozenset[str] = frozenset(s["id"] for s in AI_SYSTEMS)


def _is_seed(system_id: str) -> bool:
    """Skip intake rows that duplicate seed IDs (defensive — never expected)."""
    return system_id in _SEED_SYSTEM_IDS


def _intake_to_summary_view(s: "Any") -> dict[str, Any]:
    """Map an AISystem (Pydantic) → AiSystemSummaryOut dict shape.

    Computed fields (open_findings, critical_findings, last_assessment,
    next_assessment) default to zero/empty because FINDINGS + assessment
    enrichment for intake-written systems is a separate workstream
    (S56 backlog). The portfolio view will show the system with empty
    counts until that lands — better than the prior behavior of hiding
    the system entirely.
    """
    def _enum_value(v: Any) -> str:
        return getattr(v, "value", v) if v is not None else ""

    models = list(getattr(s, "models_used", []) or [])
    model_label = models[0] if models else (getattr(s, "model_provider", "") or "")

    return {
        "id": s.id,
        "name": s.name,
        "business_owner": s.business_owner or "",
        "technical_owner": s.technical_owner or "",
        "domain": s.domain or "",
        "description": s.description or "",
        "risk_level": _enum_value(getattr(s, "inherent_risk", "")),
        "autonomy_level": _enum_value(getattr(s, "autonomy_level", "")),
        "data_classes": [_enum_value(d) for d in (getattr(s, "data_classes", []) or [])],
        "model": model_label,
        "runtime_status": _enum_value(getattr(s, "runtime_status", "")),
        "release_decision": _enum_value(getattr(s, "release_decision", "")),
        "open_findings": 0,
        "critical_findings": 0,
        "last_assessment": "",
        "next_assessment": "",
        "deployment_target": _enum_value(getattr(s, "environment", "")),
        "use_case": getattr(s, "use_case", "") or "",
        "human_oversight": getattr(s, "human_oversight", "") or "",
        "data_residency": getattr(s, "data_residency", "") or "",
        "trust_boundaries": "",
        "data_source": getattr(s, "data_source", "real") or "real",
    }


@router.get(
    "/ai-systems/{system_id}",
    response_model=AiSystemDetailOut,
    operation_id="ai_systems_get",
)
async def get_ai_system(system_id: str) -> AiSystemDetailOut:
    """Get details of one AI system, enriched with findings, gates, evidence, events.

    S55 #3 / F-010: falls back to intake-written rows for systems registered
    via the wizard. Intake rows currently render with empty findings/gates/
    evidence/events arrays — proper enrichment for these is a sibling
    improvement (S56 backlog), but at minimum the detail page now resolves
    instead of 404'ing.
    """
    system = next((s for s in AI_SYSTEMS if s["id"] == system_id), None)
    if system is None:
        intake_system = next(
            (s for s in _list_intake_systems() if s.id == system_id and not _is_seed(s.id)),
            None,
        )
        if intake_system is not None:
            system = _intake_to_summary_view(intake_system)
    if not system:
        raise HTTPException(status_code=404, detail="System not found")

    findings = [f for f in FINDINGS if f["system_id"] == system_id]
    gates = RELEASE_GATE_RESULTS.get(system_id)
    evidence = [e for e in EVIDENCE if e["system_id"] == system_id]
    events = [e for e in RUNTIME_EVENTS if e["system_id"] == system_id]

    return AiSystemDetailOut(
        **system,
        findings=findings,
        release_gates=gates,
        evidence=evidence,
        recent_events=events,
    )


# ===========================================================================
# === Findings
# ===========================================================================

@router.get(
    "/findings",
    response_model=FindingsListOut,
    operation_id="findings_list",
)
async def list_findings(
    request: Request,
    severity: str = Query(None),
    status: str = Query(None),
    system_id: str = Query(None),
) -> FindingsListOut:
    """List findings with optional filters, sorted CRITICAL first then by SLA remaining.

    Honors X-Data-Mode (v1|v2) via the data-mode middleware.
    """
    findings = filter_by_mode(FINDINGS, get_data_mode(request))

    if severity:
        findings = [f for f in findings if f["severity"] == severity.upper()]
    if status:
        findings = [f for f in findings if f["status"] == status.upper()]
    if system_id:
        findings = [f for f in findings if f["system_id"] == system_id]

    severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    findings = sorted(
        findings,
        key=lambda f: (
            severity_order.get(f["severity"], 99),
            f.get("sla_remaining_hours", 9999),
        ),
    )

    return FindingsListOut(
        findings=[FindingOut(**f) for f in findings],
        total=len(findings),
    )


@router.get(
    "/findings/{finding_id}",
    response_model=FindingOut,
    operation_id="findings_get",
)
async def get_finding(finding_id: str) -> FindingOut:
    """Get a specific finding."""
    finding = next((f for f in FINDINGS if f["id"] == finding_id), None)
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")
    return FindingOut(**finding)


# ===========================================================================
# === Release Gates
# ===========================================================================

@router.get(
    "/release-gates/rules",
    response_model=GateRulesOut,
    operation_id="release_gate_rules_list",
)
async def get_gate_rules() -> GateRulesOut:
    """Get gate rule definitions."""
    return GateRulesOut(rules=[GateRuleOut(**r) for r in RELEASE_GATE_RULES])


@router.get(
    "/release-gates/results",
    response_model=GateResultsOut,
    operation_id="release_gate_results_list",
)
async def get_all_gate_results() -> GateResultsOut:
    """Get gate results for all systems."""
    return GateResultsOut(
        results=[GateResultOut(**r) for r in RELEASE_GATE_RESULTS.values()],
    )


@router.get(
    "/release-gates/{system_id}",
    response_model=GateResultOut,
    operation_id="release_gate_result_get",
)
async def get_gate_result(system_id: str) -> GateResultOut:
    """Get gate results for a specific system."""
    result = RELEASE_GATE_RESULTS.get(system_id)
    if not result:
        raise HTTPException(status_code=404, detail="Gate results not found")
    return GateResultOut(**result)


# ===========================================================================
# === Governance
# ===========================================================================

@router.get(
    "/governance/nist-ai-rmf",
    response_model=NistRmfOut,
    operation_id="nist_rmf_get",
)
async def get_nist_rmf() -> NistRmfOut:
    """NIST AI Risk Management Framework posture."""
    return NistRmfOut(**NIST_AI_RMF)


@router.get(
    "/governance/ai-600-1",
    response_model=AI600_1Out,
    operation_id="nist_ai_600_1_get",
)
async def get_ai_600_1() -> AI600_1Out:
    """NIST AI 600-1 GenAI Profile coverage."""
    return AI600_1Out(**AI_600_1_PROFILE)


# ===========================================================================
# === Security
# ===========================================================================

@router.get(
    "/security/owasp-llm",
    response_model=OwaspListOut,
    operation_id="owasp_llm_get",
)
async def get_owasp_llm() -> OwaspListOut:
    """OWASP Top 10 for LLM Applications status."""
    return OwaspListOut(items=[OwaspItemOut(**i) for i in OWASP_LLM_TOP10])


@router.get(
    "/security/owasp-agentic",
    response_model=OwaspListOut,
    operation_id="owasp_agentic_get",
)
async def get_owasp_agentic() -> OwaspListOut:
    """OWASP Top 10 for Agentic AI status."""
    return OwaspListOut(items=[OwaspItemOut(**i) for i in OWASP_AGENTIC])


# ===========================================================================
# === Runtime
# ===========================================================================

@router.get(
    "/runtime/events",
    response_model=RuntimeEventsOut,
    operation_id="runtime_events_list",
)
async def get_runtime_events(limit: int = Query(50, ge=1, le=500)) -> RuntimeEventsOut:
    """Get recent runtime events, newest first."""
    events = sorted(RUNTIME_EVENTS, key=lambda e: e["timestamp"], reverse=True)[:limit]
    return RuntimeEventsOut(events=[RuntimeEventOut(**e) for e in events])


# ===========================================================================
# === Policies
# ===========================================================================

@router.get(
    "/policies",
    response_model=PoliciesOut,
    operation_id="policies_list",
)
async def list_policies(request: Request) -> PoliciesOut:
    """List all policy controls. Honors X-Data-Mode (v1|v2)."""
    rows = filter_by_mode(POLICIES, get_data_mode(request))
    return PoliciesOut(
        policies=[PolicyOut(**p) for p in rows],
        total=len(rows),
    )


@router.get(
    "/policies/{policy_id}",
    response_model=PolicyOut,
    operation_id="policies_get",
)
async def get_policy(policy_id: str) -> PolicyOut:
    """Get a specific policy."""
    policy = next((p for p in POLICIES if p["id"] == policy_id), None)
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    return PolicyOut(**policy)


# ===========================================================================
# === Evidence
# ===========================================================================

@router.get(
    "/evidence",
    response_model=EvidenceListOut,
    operation_id="evidence_list",
)
async def list_evidence(
    request: Request,
    system_id: str = Query(None),
    evidence_type: str = Query(None),
) -> EvidenceListOut:
    """List evidence with optional filters. Honors X-Data-Mode (v1|v2)."""
    evidence = filter_by_mode(EVIDENCE, get_data_mode(request))
    if system_id:
        evidence = [e for e in evidence if e["system_id"] == system_id]
    if evidence_type:
        evidence = [e for e in evidence if e["type"] == evidence_type]
    return EvidenceListOut(
        evidence=[EvidenceOut(**e) for e in evidence],
        total=len(evidence),
    )
