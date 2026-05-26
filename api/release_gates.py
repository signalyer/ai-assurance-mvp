"""Release Gate Engine API.

Typed per docs/plans/SESSION-13-api-typing-audit.md §3.1.
create_exception: ValueError -> 409 with typed ConflictDetail per audit §1.2
(was 400 plain string -- upgraded to give CISO Console the structured fields
required for audit-artifact rendering).
"""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from domain.release_gate_engine import (
    evaluate_gates, apply_exception, list_exceptions, define_gates,
)
from domain.repository import list_ai_systems
from middleware.data_mode import filter_by_mode, get_data_mode

from api._models import ConflictDetail


router = APIRouter(prefix="/api/grc/release-gates/v2", tags=["release-gates-v2"])


def _strict() -> ConfigDict:
    return ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------

class FrameworkRefOut(BaseModel):
    model_config = _strict()
    framework: str
    clause: str


class GateDefinitionOut(BaseModel):
    """Static catalog definition of a release gate."""
    model_config = _strict()

    gate_id: str
    name: str
    rule_text: str
    mapped_controls: list[str]
    mapped_frameworks: list[str]
    evidence_required: list[str]
    default_blocking: bool
    framework_refs: list[FrameworkRefOut]


class GateCatalogOut(BaseModel):
    model_config = _strict()
    gates: list[GateDefinitionOut]


class GateEvaluationOut(BaseModel):
    """Per-gate evaluation result for one system."""
    model_config = _strict()

    gate_id: str
    name: str
    status: str
    blocking: bool
    failed_reason: str | None = None
    mapped_controls: list[str]
    mapped_frameworks: list[str]
    evidence_required: list[str]
    remediation_required: list[str]
    exception_id: str | None = None


class GateReportOut(BaseModel):
    """Full gate report for one system (target environment)."""
    model_config = _strict()

    ai_system_id: str
    ai_system_name: str
    target_environment: str
    generated_at: str
    gates: list[GateEvaluationOut]
    release_decision: str
    release_rationale: str
    pass_count: int
    fail_count: int
    warning_count: int
    blocking_failures: int = Field(description="Count of blocking gates that failed.")
    evidence_completeness: float


class SystemGateSummaryOut(BaseModel):
    """One-line gate summary per system for the index view.

    `error` is populated when evaluate_gates raised; mutually exclusive with the
    success fields. Using Optional[...] everywhere keeps OpenAPI a single
    consistent shape clients can branch on.
    """
    model_config = _strict()

    ai_system_id: str
    ai_system_name: str
    domain: str | None = None
    runtime_status: str | None = None
    release_decision: str | None = None
    release_rationale: str | None = None
    pass_count: int | None = None
    fail_count: int | None = None
    warning_count: int | None = None
    blocking_failures: int | None = Field(default=None, description="Count of blocking gates that failed.")
    evidence_completeness: float | None = None
    error: str | None = None


class SystemGateSummariesOut(BaseModel):
    model_config = _strict()
    systems: list[SystemGateSummaryOut]


class GateExceptionOut(BaseModel):
    """An approved exception/waiver for a failed gate."""
    model_config = _strict()

    id: str
    ai_system_id: str
    gate_id: str
    reason: str
    risk_acceptor: str
    risk_acceptor_role: str
    expires_at: str
    status: str
    compensating_controls: list[str]
    created_at: str


class GateExceptionsListOut(BaseModel):
    model_config = _strict()
    exceptions: list[GateExceptionOut]


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class ExceptionRequest(BaseModel):
    ai_system_id: str
    gate_id: str
    reason: str = Field(..., min_length=1, max_length=1000)
    risk_acceptor: str
    risk_acceptor_role: str
    expires_at: str = Field(..., description="ISO date YYYY-MM-DD")
    compensating_controls: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/catalog",
    response_model=GateCatalogOut,
    operation_id="release_gates_v2_catalog",
)
async def catalog() -> GateCatalogOut:
    """The static catalog of 10 release gates with mappings."""
    return GateCatalogOut(
        gates=[GateDefinitionOut(**asdict(g)) for g in define_gates()],
    )


@router.get(
    "/systems",
    response_model=SystemGateSummariesOut,
    operation_id="release_gates_v2_systems_summary",
)
async def systems_summary(request: Request) -> SystemGateSummariesOut:
    """One-line gate summary per AI system, for the index view.

    Honors X-Data-Mode (v1|v2): V2 hides seed systems so the SPA's
    empty-state copy renders until a real system is registered.
    """
    out: list[SystemGateSummaryOut] = []
    systems = filter_by_mode(list_ai_systems(), get_data_mode(request))
    for s in systems:
        try:
            r = evaluate_gates(s.id, target_environment="PILOT")
        except Exception as e:                            # noqa: BLE001
            out.append(SystemGateSummaryOut(
                ai_system_id=s.id, ai_system_name=s.name, error=str(e),
            ))
            continue
        out.append(SystemGateSummaryOut(
            ai_system_id=s.id,
            ai_system_name=s.name,
            domain=s.domain,
            runtime_status=s.runtime_status.value,
            release_decision=r.release_decision,
            release_rationale=r.release_rationale,
            pass_count=r.pass_count,
            fail_count=r.fail_count,
            warning_count=r.warning_count,
            blocking_failures=r.blocking_failures,
            evidence_completeness=r.evidence_completeness,
        ))
    return SystemGateSummariesOut(systems=out)


@router.get(
    "/system/{ai_system_id}",
    response_model=GateReportOut,
    operation_id="release_gates_v2_system_detail",
)
async def system_detail(ai_system_id: str, target: str = "PILOT") -> GateReportOut:
    """Full gate report for one system."""
    target = target.upper()
    if target not in ("PILOT", "PRODUCTION"):
        raise HTTPException(status_code=400, detail="target must be PILOT or PRODUCTION")
    try:
        r = evaluate_gates(ai_system_id, target_environment=target)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return GateReportOut(**asdict(r))


@router.post(
    "/exception",
    response_model=GateExceptionOut,
    operation_id="release_gates_v2_exception_create",
    responses={
        409: {"model": ConflictDetail, "description": "Exception rejected by policy."},
    },
)
async def create_exception(req: ExceptionRequest) -> GateExceptionOut:
    """Approve a time-bounded exception/waiver for a failed gate.

    On policy/validation rejection, returns 409 with a ConflictDetail body
    carrying the structured reason -- required by CISO Console for audit-artifact
    rendering per audit doc §1.2.
    """
    try:
        ex = apply_exception(
            ai_system_id=req.ai_system_id,
            gate_id=req.gate_id,
            reason=req.reason,
            risk_acceptor=req.risk_acceptor,
            risk_acceptor_role=req.risk_acceptor_role,
            expires_at=req.expires_at,
            compensating_controls=req.compensating_controls,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=409,
            detail=ConflictDetail(
                reason=str(e),
                conflict_type="POLICY_DENIED",
                policy_id=req.gate_id,
            ).model_dump(),
        )
    return GateExceptionOut(**asdict(ex))


@router.get(
    "/exceptions",
    response_model=GateExceptionsListOut,
    operation_id="release_gates_v2_exceptions_list",
)
async def get_exceptions(ai_system_id: str | None = None) -> GateExceptionsListOut:
    return GateExceptionsListOut(
        exceptions=[GateExceptionOut(**asdict(e)) for e in list_exceptions(ai_system_id)],
    )
