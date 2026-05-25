"""Evidence Repository API.

Drives the audit-ready Evidence page:
  GET /api/grc/evidence/v2/sectioned?scope=ALL|<id>     — 8-section roll-up
  GET /api/grc/evidence/v2/completeness?axis=...        — 4 axes of coverage
  GET /api/grc/evidence/v2/sections                     — section catalog
  GET /api/grc/evidence/v2/{evidence_id}                — single record

Session 29 — Track A OpenAPI sweep, per-router #5.
All four routes get strict Pydantic v2 response models and stable
operation_ids. Live UI consumer: static/evidence.html (sectioned +
completeness only). All field shapes are deterministic upstream
(dataclasses with fixed fields and the Evidence Pydantic model), so
strict (no extra="allow") fits per compound rule 27a.

The single-record endpoint mirrors the Evidence domain model field-by-
field rather than typing it as dict — Evidence is stable and audit
clients fetching by id genuinely benefit from a typed response shape.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

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


# ===========================================================================
# Response models (Session 29 — Track A OpenAPI sweep, per-router #5)
# ===========================================================================

class SectionCatalogItem(BaseModel):
    """One entry in the static section catalog."""
    id: str
    name: str
    types: list[str]


class SectionsResponse(BaseModel):
    """Envelope for GET /sections."""
    sections: list[SectionCatalogItem]


class EvidenceRowOut(BaseModel):
    """Single evidence record as rendered in the sectioned roll-up.

    Mirrors domain.evidence_repository.EvidenceRow (dataclass). 18
    fields, all always present. Optionals reflect the source dataclass:
    assessment_id / hash / uri may be None.
    """
    id: str
    ai_system_id: str
    ai_system_name: str
    assessment_id: Optional[str] = None
    evidence_type: str
    evidence_type_pretty: str
    section_id: str
    section_name: str
    source: str
    collected_at: str
    hash: Optional[str] = None
    immutable: bool
    summary: str
    uri: Optional[str] = None
    linked_control_ids: list[str]
    linked_finding_ids: list[str]
    linked_frameworks: list[str]


class SectionedSection(BaseModel):
    """One section in the sectioned roll-up response."""
    section_id: str
    section_name: str
    type_filter: list[str]
    count: int
    items: list[EvidenceRowOut]


class SectionedResponse(BaseModel):
    """Envelope for GET /sectioned."""
    scope: str
    sections: list[SectionedSection]


class CompletenessRowOut(BaseModel):
    """Single completeness row.

    Mirrors domain.evidence_repository.CompletenessRow (dataclass).
    `pct` is rounded to 1 decimal upstream; `missing` is already capped
    at 10-15 items per row depending on axis.
    """
    label: str
    present: int
    required: int
    pct: float
    missing: list[str]


class CompletenessResponse(BaseModel):
    """Envelope for GET /completeness."""
    axis: str
    scope: str
    rows: list[CompletenessRowOut]


class EvidenceDetailResponse(BaseModel):
    """Single Evidence record + resolved AI system name.

    Mirrors domain.models.Evidence (Pydantic v2) field-by-field with
    datetimes serialized as ISO strings (model_dump(mode="json")), plus
    the resolved `ai_system_name` joined from the parent AI system. Kept
    strict — the Evidence domain model is stable and audit clients
    fetching by id benefit from a typed shape.
    """
    id: str
    ai_system_id: str
    ai_system_name: str
    assessment_id: Optional[str] = None
    evidence_type: str
    source: str
    uri: Optional[str] = None
    hash: Optional[str] = None
    collected_at: str
    summary: str
    immutable: bool
    linked_control_ids: list[str]
    linked_finding_ids: list[str]
    linked_frameworks: list[str]


# ===========================================================================
# Serialization helper
# ===========================================================================

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


# ===========================================================================
# Routes
# ===========================================================================

@router.get(
    "/sections",
    response_model=SectionsResponse,
    operation_id="evidence_v2_sections_get",
)
async def sections() -> dict:
    """Static section catalog with the evidence types in each."""
    return {
        "sections": [
            {"id": s["id"], "name": s["name"], "types": [t.value for t in s["types"]]}
            for s in SECTIONS
        ]
    }


@router.get(
    "/sectioned",
    response_model=SectionedResponse,
    operation_id="evidence_v2_sectioned_get",
)
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


@router.get(
    "/completeness",
    response_model=CompletenessResponse,
    operation_id="evidence_v2_completeness_get",
)
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


@router.get(
    "/{evidence_id}",
    response_model=EvidenceDetailResponse,
    operation_id="evidence_v2_record_get",
)
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
