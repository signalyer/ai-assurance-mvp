"""Release Gate Engine API."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from domain.release_gate_engine import (
    evaluate_gates, apply_exception, list_exceptions, define_gates,
)
from domain.repository import list_ai_systems


router = APIRouter(prefix="/api/grc/release-gates/v2", tags=["release-gates-v2"])


def _ser(obj):
    if is_dataclass(obj):
        return {k: _ser(v) for k, v in asdict(obj).items()}
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, (list, tuple)):
        return [_ser(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _ser(v) for k, v in obj.items()}
    return obj


@router.get("/catalog")
async def catalog() -> dict:
    """The static catalog of 10 release gates with mappings."""
    return {"gates": [_ser(g) for g in define_gates()]}


@router.get("/systems")
async def systems_summary() -> dict:
    """One-line gate summary per AI system, for the index view."""
    out = []
    for s in list_ai_systems():
        try:
            r = evaluate_gates(s.id, target_environment="PILOT")
        except Exception as e:                            # noqa: BLE001
            out.append({"ai_system_id": s.id, "ai_system_name": s.name, "error": str(e)})
            continue
        out.append({
            "ai_system_id": s.id,
            "ai_system_name": s.name,
            "domain": s.domain,
            "runtime_status": s.runtime_status.value,
            "release_decision": r.release_decision,
            "release_rationale": r.release_rationale,
            "pass_count": r.pass_count,
            "fail_count": r.fail_count,
            "warning_count": r.warning_count,
            "blocking_failures": r.blocking_failures,
            "evidence_completeness": r.evidence_completeness,
        })
    return {"systems": out}


@router.get("/system/{ai_system_id}")
async def system_detail(ai_system_id: str, target: str = "PILOT") -> dict:
    """Full gate report for one system."""
    target = target.upper()
    if target not in ("PILOT", "PRODUCTION"):
        raise HTTPException(status_code=400, detail="target must be PILOT or PRODUCTION")
    try:
        r = evaluate_gates(ai_system_id, target_environment=target)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _ser(r)


class ExceptionRequest(BaseModel):
    ai_system_id: str
    gate_id: str
    reason: str = Field(..., min_length=1, max_length=1000)
    risk_acceptor: str
    risk_acceptor_role: str
    expires_at: str = Field(..., description="ISO date YYYY-MM-DD")
    compensating_controls: list[str] = Field(default_factory=list)


@router.post("/exception")
async def create_exception(req: ExceptionRequest) -> dict:
    """Approve a time-bounded exception/waiver for a failed gate."""
    try:
        ex = apply_exception(
            ai_system_id=req.ai_system_id, gate_id=req.gate_id, reason=req.reason,
            risk_acceptor=req.risk_acceptor, risk_acceptor_role=req.risk_acceptor_role,
            expires_at=req.expires_at, compensating_controls=req.compensating_controls,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _ser(ex)


@router.get("/exceptions")
async def get_exceptions(ai_system_id: str | None = None) -> dict:
    return {"exceptions": [_ser(e) for e in list_exceptions(ai_system_id)]}
