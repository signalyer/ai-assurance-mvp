"""Assessment Engine API.

Session 39 — Track A Tier 3 OpenAPI sweep (one SPA consumer: static/assessment.html).
Strict Pydantic v2 response models mirror the domain dataclasses in
domain.assessment_engine (AssessmentReport and its nested types). The top-level
response carries permissive config so future additive fields in the assessment
report do not break the contract; nested models stay strict because their
shapes are anchored in the domain layer.

Both routes share the same response shape (GET is a convenience alias for POST).
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from domain.assessment_engine import run_assessment


router = APIRouter(prefix="/api/grc/assessment", tags=["grc-assessment"])


# ===========================================================================
# Response models (Session 39 — Track A Tier 3 OpenAPI sweep)
# Mirror domain.assessment_engine dataclasses field-by-field.
# ===========================================================================


class _RiskFactorsOut(BaseModel):
    likelihood: float
    impact: float
    exposure: float
    autonomy: float
    data_sensitivity: float
    control_gap_modifier: float


class _ResidualRiskScoreOut(BaseModel):
    factors: _RiskFactorsOut
    raw_score: float
    normalized_score: float
    level: str
    explanation: list[str]


class _ReleaseRecommendationOut(BaseModel):
    decision: str
    rule_fired: str
    rationale: str
    conditions: list[str] = []


class _ControlEvaluationOut(BaseModel):
    control_id: str
    title: str
    domain: str
    priority: str
    status: str
    blocking: bool
    rationale: str
    open_finding_ids: list[str] = []
    missing_evidence_types: list[str] = []
    failed_evals: list[str] = []
    related_runtime_events: int = 0


class _GeneratedFindingOut(BaseModel):
    id: str
    ai_system_id: str
    control_id: str
    title: str
    description: str
    severity: str
    framework_mappings: list[dict]
    owner: str
    release_impact: str
    remediation: str


class _FrameworkCoverageOut(BaseModel):
    framework: str
    controls_applicable: int
    controls_passing: int
    controls_failing: int
    coverage_pct: float
    framework_refs: list[dict] = []


class AssessmentReportResponse(BaseModel):
    """Full assessment report.

    Mirrors domain.assessment_engine.AssessmentReport. Permissive at the top
    level so the engine layer can add fields without breaking the SPA. Nested
    models are strict — their domain shapes are stable.
    """
    ai_system_id: str
    ai_system_name: str
    generated_at: str
    overall_score: float
    inherent_risk: str
    inherent_risk_rules: list[str]
    residual_risk: _ResidualRiskScoreOut
    release_recommendation: _ReleaseRecommendationOut
    control_evaluations: list[_ControlEvaluationOut]
    failed_controls: list[str]
    findings: list[_GeneratedFindingOut]
    required_remediation: list[str]
    framework_coverage: list[_FrameworkCoverageOut]
    evidence_completeness: float

    model_config = ConfigDict(extra="allow")


# ===========================================================================
# Routes
# ===========================================================================


def _serialize(obj):
    """Recursively convert dataclasses/enums into JSON-safe primitives."""
    if is_dataclass(obj):
        return {k: _serialize(v) for k, v in asdict(obj).items()}
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, (list, tuple)):
        return [_serialize(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    return obj


@router.post(
    "/run/{ai_system_id}",
    response_model=AssessmentReportResponse,
    operation_id="assessment_run_post",
)
async def run(ai_system_id: str) -> dict:
    """Run a full assessment against an AI system and return the report."""
    try:
        report = run_assessment(ai_system_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _serialize(report)


@router.get(
    "/{ai_system_id}",
    response_model=AssessmentReportResponse,
    operation_id="assessment_get",
)
async def get(ai_system_id: str) -> dict:
    """Convenience GET — same as POST /run."""
    return await run(ai_system_id)
