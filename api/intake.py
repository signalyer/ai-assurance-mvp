"""AI System Intake API.

POST /api/grc/intake/preview  — classify risk + resolve controls (no persistence)
POST /api/grc/intake/submit   — create AISystem, assessment, release gates; persist
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Session 13 response models
# ---------------------------------------------------------------------------

class RequiredControlOut(BaseModel):
    """One required control in the intake preview."""
    model_config = ConfigDict(extra="forbid")

    control_id: str
    title: str
    domain: str
    priority: str
    frameworks: dict[str, list[str]] = Field(
        description="Map of framework name -> list of clause IDs covered by this control.",
    )
    recommended_owner: str


class ControlsBreakdownOut(BaseModel):
    """Breakdown of controls by priority + domain."""
    model_config = ConfigDict(extra="forbid")

    applicable_total: int
    required_total: int
    by_priority: dict[str, int]
    by_domain: dict[str, int]
    required: list[RequiredControlOut]


class IntakePreviewOut(BaseModel):
    """Live preview: classified risk + applicable controls (not persisted)."""
    model_config = ConfigDict(extra="forbid")

    risk_level: str
    rules_fired: list[str]
    rationale: list[str] = Field(
        description="Multi-line rationale; each entry is one rule outcome explanation.",
    )
    signals: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    controls: ControlsBreakdownOut
    regulatory_exposure: list[str]


class IntakeSubmitOut(BaseModel):
    """Result of POST /api/grc/intake/submit -- the new system_id + redirect.

    S55 #7: `status` distinguishes "active" (system + assessment + gates all
    persisted) from "draft" (system persisted but downstream creation failed —
    operator can recover from the inventory page; F-009/F-010-style data
    loss is no longer possible at the intake layer).
    """
    model_config = ConfigDict(extra="forbid")

    ai_system_id: str
    assessment_id: str | None = None  # None on draft saves
    gate_count: int = 0
    inherent_risk: str
    rules_fired: list[str]
    redirect_to: str
    status: str = "active"  # "active" | "draft"
    draft_reason: str | None = None  # populated when status == "draft"


class IntakeSystemsListOut(BaseModel):
    """Intake-created systems (read from JSONL).

    `systems` is list[dict] -- the AISystem domain model has 30+ fields and
    is already typed in api.grc.AiSystemDetailOut. Phase 1.5 can unify.
    """
    model_config = ConfigDict(extra="forbid")

    systems: list[dict] = Field(default_factory=list)
    total: int | None = None

from domain.models import (
    AISystem, Assessment, ReleaseGate, RAGSource, AgentTool,
    Environment, RuntimeStatus, CloudProvider, AutonomyLevel,
    CustomerImpact, RegulatoryExposure, DataClass, ReleaseDecision,
    AssessmentType, AssessmentStatus, EvalStatus, RiskLevel, Priority,
)
from domain.risk_classification import classify_inherent_risk
from domain.controls import (
    get_controls_for_ai_system, get_required_controls,
    map_control_to_frameworks,
)


router = APIRouter(prefix="/api/grc/intake", tags=["grc-intake"])


DATA_DIR = Path(__import__("os").environ.get("DATA_ROOT") or (Path(__file__).resolve().parents[1] / "data"))
DATA_DIR.mkdir(exist_ok=True)
SYSTEMS_FILE = DATA_DIR / "ai_systems.jsonl"
ASSESSMENTS_FILE = DATA_DIR / "assessments.jsonl"
GATES_FILE = DATA_DIR / "release_gates.jsonl"


# ---------------------------------------------------------------------------
# Intake payload schema (loose by design — wizard fields evolve)
# ---------------------------------------------------------------------------

class IntakePayload(BaseModel):
    """All fields gathered across the 5 wizard steps. Most are optional during
    preview; submit performs final validation.
    """
    # Step 1 — Business Context
    name: str | None = None
    description: str | None = None
    business_owner: str | None = None
    technical_owner: str | None = None
    domain: str | None = None
    use_case: str | None = None
    user_population: str | None = None
    customer_impact: str | None = None

    # Step 2 — Architecture
    cloud_provider: str | None = "AWS"
    aws_services: list[str] = Field(default_factory=list)
    model_provider: str | None = None
    models_used: list[str] = Field(default_factory=list)
    rag_enabled: bool = False
    rag_sources: list[str] = Field(default_factory=list)
    vector_store: str | None = None
    tools_used: list[str] = Field(default_factory=list)
    external_integrations: list[str] = Field(default_factory=list)

    # Step 3 — Data Classification
    data_classes: list[str] = Field(default_factory=list)
    data_in_prompts: bool = False
    data_in_rag: bool = False
    tools_return_sensitive_data: bool = False
    logs_contain_sensitive_data: bool = False

    # Step 4 — Agent Autonomy
    autonomy_level: str | None = None
    can_call_tools: bool = False
    can_write_data: bool = False
    can_trigger_customer_communication: bool = False
    can_influence_fs_workflow: bool = False
    human_approval_required: bool = True

    # Step 5 — Evidence Upload (links/paths, not file content)
    architecture_diagram_url: str | None = None
    iac_url: str | None = None
    iam_policy_url: str | None = None
    bedrock_config_url: str | None = None
    rag_pipeline_config_url: str | None = None
    eval_report_url: str | None = None
    logging_config_url: str | None = None
    security_review_url: str | None = None


# ---------------------------------------------------------------------------
# Mapping intake -> domain models
# ---------------------------------------------------------------------------

# UI value -> domain enum
_DATA_CLASS_MAP: dict[str, DataClass] = {
    "public": DataClass.PUBLIC,
    "internal": DataClass.PUBLIC,
    "confidential": DataClass.NPI,
    "pii": DataClass.PII,
    "npi": DataClass.NPI,
    "pci": DataClass.PCI,
    "payment_data": DataClass.TRANSACTION_DATA,
    "aml_kyc_data": DataClass.SAR_DATA,
    "credit_data": DataClass.INTERNAL_CREDIT,
}

_AUTONOMY_MAP: dict[str, AutonomyLevel] = {
    "answer_only": AutonomyLevel.ADVISORY,
    "recommend": AutonomyLevel.ADVISORY,
    "draft": AutonomyLevel.DOCUMENT_GENERATION,
    "execute_with_approval": AutonomyLevel.TOOL_USING_HITL,
    "execute_autonomously": AutonomyLevel.TOOL_USING_AUTONOMOUS,
}

_DOMAIN_REG_MAP: dict[str, list[RegulatoryExposure]] = {
    "payments":         [RegulatoryExposure.GLBA, RegulatoryExposure.OFAC, RegulatoryExposure.FFIEC, RegulatoryExposure.SOX],
    "aml":              [RegulatoryExposure.BSA_AML, RegulatoryExposure.OFAC, RegulatoryExposure.FFIEC],
    "kyc":              [RegulatoryExposure.BSA_AML, RegulatoryExposure.OFAC, RegulatoryExposure.GLBA],
    "credit":           [RegulatoryExposure.CFPB, RegulatoryExposure.FFIEC, RegulatoryExposure.SOX],
    "customer service": [RegulatoryExposure.GLBA, RegulatoryExposure.CFPB, RegulatoryExposure.CCPA],
    "wealth":           [RegulatoryExposure.FFIEC, RegulatoryExposure.SOX],
    "treasury":         [RegulatoryExposure.SOX, RegulatoryExposure.FFIEC],
}

_USER_POP_TO_IMPACT: dict[str, CustomerImpact] = {
    "internal": CustomerImpact.NONE,
    "customer-facing": CustomerImpact.DIRECT,
    "third-party": CustomerImpact.INDIRECT,
    "regulator-facing": CustomerImpact.INDIRECT,
}

_IMPACT_MAP: dict[str, CustomerImpact] = {
    "none": CustomerImpact.NONE,
    "indirect": CustomerImpact.INDIRECT,
    "direct": CustomerImpact.DIRECT,
    "material": CustomerImpact.DIRECT_FINANCIAL,
}


def _build_ai_system(p: IntakePayload, *, system_id: str, risk: RiskLevel) -> AISystem:
    """Materialize an AISystem from the intake payload + classified risk."""
    domain = (p.domain or "").strip()
    user_pop = (p.user_population or "internal").strip().lower()
    impact_raw = (p.customer_impact or "").strip().lower()

    data_classes = list({
        _DATA_CLASS_MAP.get(d.lower(), DataClass.PUBLIC) for d in p.data_classes
    }) or [DataClass.PUBLIC]

    regulatory_exposure = _DOMAIN_REG_MAP.get(domain.lower(), [])

    autonomy = _AUTONOMY_MAP.get((p.autonomy_level or "").lower(), AutonomyLevel.ADVISORY)

    customer_impact = (
        _IMPACT_MAP.get(impact_raw)
        or _USER_POP_TO_IMPACT.get(user_pop, CustomerImpact.NONE)
    )

    side_effect_tools = (
        p.can_write_data
        or p.can_trigger_customer_communication
        or p.can_influence_fs_workflow
    )
    tools = [
        AgentTool(
            name=t, description=f"Tool: {t}",
            side_effect=side_effect_tools,
            authorization_required=True,
        )
        for t in p.tools_used
    ]

    rag_sources = [
        RAGSource(name=src, type="vector_store", classification=data_classes,
                  version_controlled=False)
        for src in p.rag_sources
    ] if p.rag_enabled else []

    now = datetime.utcnow()

    return AISystem(
        id=system_id,
        name=p.name or "Untitled AI System",
        description=p.description or "",
        business_owner=p.business_owner or "",
        technical_owner=p.technical_owner or "",
        domain=domain or "Unknown",
        cloud_provider=CloudProvider.AWS,
        environment=Environment.DEV,
        model_provider=p.model_provider or "",
        models_used=p.models_used or [],
        data_classes=data_classes,
        autonomy_level=autonomy,
        user_population=user_pop,
        customer_impact=customer_impact,
        regulatory_exposure=regulatory_exposure,
        rag_enabled=p.rag_enabled,
        rag_sources=rag_sources,
        tools=tools,
        aws_services=p.aws_services or [],
        runtime_status=RuntimeStatus.DESIGN,
        release_decision=ReleaseDecision.NOT_ASSESSED,
        inherent_risk=risk,
        residual_risk=risk,                # residual == inherent until controls evaluated
        use_case=p.use_case,
        human_oversight="Required" if p.human_approval_required else "Not specified",
        data_residency="us-east-1",
        data_source="real",  # S52: intake creates real customer systems, not demo seed data
        created_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/preview",
    response_model=IntakePreviewOut,
    operation_id="intake_preview",
)
async def preview_intake(payload: IntakePayload) -> IntakePreviewOut:
    """Live classification: returns inherent risk + required-control set
    without persisting anything. Called by the wizard on every change.
    """
    intake_dict = payload.model_dump()
    rc = classify_inherent_risk(intake_dict)
    preview_system = _build_ai_system(payload, system_id="preview", risk=rc.risk_level)

    applicable = get_controls_for_ai_system(preview_system)
    required = get_required_controls(preview_system)

    # Compact view for the panel
    by_priority: dict[str, int] = {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
    by_domain: dict[str, int] = {}
    for c in applicable:
        by_priority[c.priority.value] = by_priority.get(c.priority.value, 0) + 1
        by_domain[c.domain.value] = by_domain.get(c.domain.value, 0) + 1

    required_summary = [
        {
            "control_id": c.control_id,
            "title": c.title,
            "domain": c.domain.value,
            "priority": c.priority.value,
            "frameworks": map_control_to_frameworks(c),
            "recommended_owner": c.recommended_owner.value,
        }
        for c in required
    ]

    return IntakePreviewOut(
        risk_level=rc.risk_level.value,
        rules_fired=rc.rules_fired,
        rationale=rc.rationale,
        signals=rc.signals,
        controls=ControlsBreakdownOut(
            applicable_total=len(applicable),
            required_total=len(required),
            by_priority=by_priority,
            by_domain=by_domain,
            required=[RequiredControlOut(**c) for c in required_summary],
        ),
        regulatory_exposure=[r.value for r in preview_system.regulatory_exposure],
    )


def _append_jsonl(path: Path, record: dict) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")


@router.post(
    "/submit",
    response_model=IntakeSubmitOut,
    operation_id="intake_submit",
)
async def submit_intake(payload: IntakePayload) -> IntakeSubmitOut:
    """Persist the AI System, create initial assessment + release gate checks.

    Pipeline:
      1. Classify inherent risk
      2. Materialize AISystem
      3. Resolve required controls (P0/P1)
      4. Create initial PRE_RELEASE Assessment
      5. Generate one ReleaseGate per required control
      6. Persist all three to JSONL
      7. Return the new system id + redirect target
    """
    if not (payload.name and payload.business_owner and payload.technical_owner and payload.domain):
        raise HTTPException(
            status_code=400,
            detail="name, business_owner, technical_owner, and domain are required.",
        )

    intake_dict = payload.model_dump()
    rc = classify_inherent_risk(intake_dict)

    system_id = f"ai-sys-{uuid4().hex[:8]}"
    system = _build_ai_system(payload, system_id=system_id, risk=rc.risk_level)

    required = get_required_controls(system)

    now = datetime.utcnow()
    assessment = Assessment(
        id=f"assess-{uuid4().hex[:8]}",
        ai_system_id=system_id,
        assessment_type=AssessmentType.INITIAL,
        status=AssessmentStatus.IN_PROGRESS,
        started_at=now,
        assessor="(unassigned — pending intake review)",
        framework_versions={
            "NIST_AI_RMF": "1.0",
            "NIST_AI_600_1": "1.0",
            "OWASP_LLM_TOP10": "2025",
            "OWASP_AGENTIC_TOP10": "2025",
            "FS_OVERLAY": "2026.1",
        },
        overall_score=None,
        release_recommendation=ReleaseDecision.NOT_ASSESSED,
        notes=(
            f"Initial intake. Inherent risk {rc.risk_level.value}. "
            f"Rules fired: {', '.join(rc.rules_fired) or 'none'}. "
            f"{len(required)} P0/P1 control(s) required for release."
        ),
    )

    gates: list[ReleaseGate] = []
    for control in required:
        gates.append(ReleaseGate(
            id=f"gate-{uuid4().hex[:8]}",
            ai_system_id=system_id,
            gate_name=control.title,
            rule=control.pass_criteria,
            rule_expression=control.gate_expression,
            status=EvalStatus.NOT_RUN,
            failed_reason=None,
            blocking=control.priority == Priority.P0,
            data_source="real",  # S52: inherits real-mode tag from the intake-created system
            last_evaluated=now,
        ))

    # Persist (JSON-mode dumps handle enums and datetimes).
    #
    # S55 #7 (save-as-draft contract): the AI system itself MUST be persisted
    # first; if any downstream step fails (assessment write, individual gate
    # write), we return the row as a "draft" rather than 500-ing and losing
    # the operator's intake work entirely. The system is fully recoverable
    # from the inventory page; the operator can re-trigger assessment + gate
    # creation later. F-009/F-010-style silent data loss is no longer possible
    # at the intake layer.
    _append_jsonl(SYSTEMS_FILE, system.model_dump(mode="json"))

    import logging as _logging
    _log = _logging.getLogger(__name__)

    try:
        _append_jsonl(ASSESSMENTS_FILE, assessment.model_dump(mode="json"))
    except Exception as e:  # noqa: BLE001 — intentionally broad: any failure becomes a draft, never a 500
        _log.exception("intake_submit: assessment write failed for %s; saving as draft", system_id)
        return IntakeSubmitOut(
            ai_system_id=system_id,
            assessment_id=None,
            gate_count=0,
            inherent_risk=rc.risk_level.value,
            rules_fired=rc.rules_fired,
            redirect_to=f"/ai-systems?id={system_id}",
            status="draft",
            draft_reason=f"Assessment creation failed: {type(e).__name__}. System saved; retry from inventory page.",
        )

    gates_written = 0
    gates_failed_reason: str | None = None
    for g in gates:
        try:
            _append_jsonl(GATES_FILE, g.model_dump(mode="json"))
            gates_written += 1
        except Exception as e:  # noqa: BLE001
            _log.exception("intake_submit: gate write failed for %s/%s; partial draft", system_id, g.id)
            gates_failed_reason = (
                f"{gates_written}/{len(gates)} gates persisted before {type(e).__name__}. "
                "Retry from inventory page."
            )
            break

    if gates_failed_reason is not None:
        return IntakeSubmitOut(
            ai_system_id=system_id,
            assessment_id=assessment.id,
            gate_count=gates_written,
            inherent_risk=rc.risk_level.value,
            rules_fired=rc.rules_fired,
            redirect_to=f"/ai-systems?id={system_id}",
            status="draft",
            draft_reason=gates_failed_reason,
        )

    # F-023 fix (S66): materialize Step 5 URL fields as typed Evidence rows.
    # Previously these 8 fields were collected by the wizard and silently
    # dropped — the AISystem model has no URL fields, no Evidence rows were
    # written, and the framework completeness rollup saw nothing. This loop
    # closes that gap. Failures here are non-fatal: the system + assessment
    # + gates already shipped successfully; missing evidence becomes a
    # ticked-down completeness %, not a 500 or a draft status.
    try:
        from datetime import datetime, timezone
        from uuid import uuid4
        from domain.models import Evidence, EvidenceType
        from domain.repository import append_evidence

        _INTAKE_URL_TO_TYPE: dict[str, EvidenceType] = {
            "architecture_diagram_url": EvidenceType.ARCHITECTURE_DIAGRAM,
            "iac_url": EvidenceType.TERRAFORM_SNAPSHOT,
            "iam_policy_url": EvidenceType.IAM_POLICY_SNAPSHOT,
            "bedrock_config_url": EvidenceType.BEDROCK_CONFIG,
            "rag_pipeline_config_url": EvidenceType.RAG_CONFIG,
            "eval_report_url": EvidenceType.EVAL_RUN,
            "logging_config_url": EvidenceType.AUDIT_LOG,
            "security_review_url": EvidenceType.PEN_TEST,
        }
        for field_name, et in _INTAKE_URL_TO_TYPE.items():
            url = getattr(payload, field_name, None)
            if not url:
                continue
            ev = Evidence(
                id=f"ev-{uuid4().hex[:12]}",
                ai_system_id=system_id,
                evidence_type=et,
                source="intake",
                uri=url,
                hash=None,
                collected_at=datetime.now(timezone.utc),
                summary=f"Evidence linked at intake (field: {field_name}).",
                immutable=True,
                data_source="real",
            )
            append_evidence(ev)
    except Exception as e:  # noqa: BLE001
        _log.exception("intake_submit: evidence materialisation failed for %s", system_id)

    return IntakeSubmitOut(
        ai_system_id=system_id,
        assessment_id=assessment.id,
        gate_count=len(gates),
        inherent_risk=rc.risk_level.value,
        rules_fired=rc.rules_fired,
        redirect_to=f"/ai-systems?id={system_id}",
        status="active",
    )


@router.get(
    "/systems",
    response_model=IntakeSystemsListOut,
    operation_id="intake_systems_list",
)
async def list_intake_systems() -> IntakeSystemsListOut:
    """List intake-created systems (read from JSONL — separate from mock systems)."""
    if not SYSTEMS_FILE.exists():
        return IntakeSystemsListOut(systems=[])
    out = []
    with SYSTEMS_FILE.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return IntakeSystemsListOut(systems=out, total=len(out))
