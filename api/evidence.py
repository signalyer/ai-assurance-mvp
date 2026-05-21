"""Evidence Repository API.

Drives the audit-ready Evidence page:
  GET /api/grc/evidence/v2/sectioned?scope=ALL|<id>     — 8-section roll-up
  GET /api/grc/evidence/v2/completeness?axis=...        — 4 axes of coverage
  GET /api/grc/evidence/v2/sections                     — section catalog
  GET /api/grc/evidence/v2/{evidence_id}                — single record
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum

from fastapi import APIRouter, HTTPException

from domain.models import FrameworkName
from domain.evidence_repository import (
    SECTIONS,
    completeness_by_ai_system,
    completeness_by_framework,
    completeness_by_control_domain,
    completeness_by_release_gate,
    list_evidence_sectioned,
)
from domain import repository


router = APIRouter(prefix="/api/grc/evidence/v2", tags=["evidence-repository"])


def _ser(o):
    if is_dataclass(o):
        return {k: _ser(v) for k, v in asdict(o).items()}
    if isinstance(o, Enum):
        return o.value
    if isinstance(o, (list, tuple)):
        return [_ser(v) for v in o]
    if isinstance(o, dict):
        return {k: _ser(v) for k, v in o.items()}
    return o


@router.get("/sections")
async def sections() -> dict:
    """Static section catalog with the evidence types in each."""
    return {
        "sections": [
            {"id": s["id"], "name": s["name"], "types": [t.value for t in s["types"]]}
            for s in SECTIONS
        ]
    }


@router.get("/sectioned")
async def sectioned(scope: str = "ALL") -> dict:
    """All evidence grouped into the 8 spec'd sections."""
    grouped = list_evidence_sectioned(scope=scope)
    out = []
    for s in SECTIONS:
        rows = grouped.get(s["id"], [])
        out.append({
            "section_id": s["id"],
            "section_name": s["name"],
            "type_filter": [t.value for t in s["types"]],
            "count": len(rows),
            "items": [_ser(r) for r in rows],
        })
    other = grouped.get("other", [])
    if other:
        out.append({
            "section_id": "other", "section_name": "Other",
            "type_filter": [], "count": len(other),
            "items": [_ser(r) for r in other],
        })
    return {"scope": scope, "sections": out}


@router.get("/completeness")
async def completeness(axis: str = "ai_system", scope: str = "ALL") -> dict:
    """Evidence completeness along one of four axes."""
    axis = axis.lower()
    if axis == "ai_system":
        rows = completeness_by_ai_system()
    elif axis == "framework":
        rows = [
            completeness_by_framework(FrameworkName.NIST_AI_RMF, scope),
            completeness_by_framework(FrameworkName.NIST_AI_600_1, scope),
            completeness_by_framework(FrameworkName.OWASP_LLM_TOP10, scope),
            completeness_by_framework(FrameworkName.OWASP_AGENTIC_TOP10, scope),
            completeness_by_framework(FrameworkName.FS_OVERLAY, scope),
            completeness_by_framework(FrameworkName.SOC2, scope),
        ]
    elif axis in ("domain", "control_domain"):
        rows = completeness_by_control_domain(scope)
    elif axis in ("release_gate", "gate"):
        rows = completeness_by_release_gate(scope)
    else:
        raise HTTPException(status_code=400, detail="axis must be one of: ai_system, framework, domain, release_gate")
    return {"axis": axis, "scope": scope, "rows": [_ser(r) for r in rows]}


@router.get("/{evidence_id}")
async def evidence_by_id(evidence_id: str) -> dict:
    """Lookup a single evidence record by id (across all systems)."""
    for s in repository.list_ai_systems():
        for e in repository.evidence_for(s.id):
            if e.id == evidence_id:
                return {
                    **e.model_dump(mode="json"),
                    "ai_system_name": s.name,
                }
    raise HTTPException(status_code=404, detail="Evidence not found")
