"""Framework coverage API.

Drives the Governance and Security dashboards. All values are computed live
from controls / findings / evidence / release gates — no hardcoded percentages.

Session 40 (Tier 3 sweep, compound 24b amendment):
    - Replaced bare-dict responses with strict Pydantic v2 response_models
      mirroring the underlying dataclasses (FrameworkItem, ControlRollup,
      FindingSummary, ItemCoverage).
    - Added operation_id values with `framework_*` prefix to avoid collision
      with `frameworks_*` op_ids exposed by api/frameworks.py (plural).
    - Consumers (38a coupling grep): static/governance.html line 112,
      static/security.html line 110 — both call /overview only. /catalog and
      /{item_id} have zero SPA consumers (Tier 1) but are typed uniformly
      for consistency and OpenAPI completeness.
    - extra="forbid" on all response models per compound 27a (strict by
      default); no polymorphic payloads here.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from domain.framework_coverage import (
    framework_catalog, framework_overview, item_coverage,
)


router = APIRouter(prefix="/api/grc/framework", tags=["framework-coverage"])


def _strict() -> ConfigDict:
    return ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Response models — mirror domain dataclasses exactly
# ---------------------------------------------------------------------------


class FrameworkItemOut(BaseModel):
    """One catalog item. Mirrors domain.framework_coverage.FrameworkItem."""
    model_config = _strict()

    id: str
    framework: str
    display_name: str
    description: str
    exact_clauses: list[str] = Field(default_factory=list)
    prefix_clauses: list[str] = Field(default_factory=list)
    recommended_owner: str


class CatalogOut(BaseModel):
    """Wrapped list response for GET /{framework}/catalog (audit §1.1)."""
    model_config = _strict()

    items: list[FrameworkItemOut]


class ControlRollupOut(BaseModel):
    """Per-control rollup. Mirrors domain.framework_coverage.ControlRollup."""
    model_config = _strict()

    control_id: str
    title: str
    priority: str
    domain: str
    status: str = Field(
        description="PASS | FAIL | NO_EVIDENCE | PARTIAL | NOT_APPLICABLE | NOT_EVALUATED",
    )
    open_findings: int


class FindingSummaryOut(BaseModel):
    """Per-finding summary. Mirrors domain.framework_coverage.FindingSummary."""
    model_config = _strict()

    id: str
    system_id: str
    title: str
    severity: str
    status: str
    control_id: str | None = None


class ItemCoverageOut(BaseModel):
    """Full coverage payload for one framework item.

    Mirrors domain.framework_coverage.ItemCoverage. Consumed by
    static/governance.html and static/security.html — every field below is
    read by at least one consumer (see Session 40 sweep notes).
    """
    model_config = _strict()

    item_id: str
    framework: str
    display_name: str
    description: str
    recommended_owner: str
    scope: str = Field(description="'ALL' or a specific ai_system_id")

    mapped_controls: list[ControlRollupOut]
    related_findings: list[FindingSummaryOut]
    release_gates_affected: list[str]
    coverage_pct: float = Field(description="passing / applicable, 0-100")
    evidence_completeness: float = Field(description="0..1 across the item's controls")
    recommended_remediation: list[str]


class OverviewOut(BaseModel):
    """Wrapped response for GET /{framework}/overview."""
    model_config = _strict()

    framework: str
    scope: str
    items: list[ItemCoverageOut]


# ---------------------------------------------------------------------------
# Dataclass -> dict serializer (preserved for input into Pydantic constructors)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/{framework}/catalog",
    response_model=CatalogOut,
    operation_id="framework_get_catalog",
)
async def catalog(framework: str) -> CatalogOut:
    """Return the static catalog for a framework (no system context)."""
    try:
        items = framework_catalog(framework)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return CatalogOut(items=[FrameworkItemOut(**_ser(i)) for i in items])


@router.get(
    "/{framework}/overview",
    response_model=OverviewOut,
    operation_id="framework_get_overview",
)
async def overview(framework: str, scope: str = "ALL") -> OverviewOut:
    """Return per-item coverage rollups for a framework under a scope."""
    try:
        rows = framework_overview(framework, scope=scope)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return OverviewOut(
        framework=framework,
        scope=scope,
        items=[ItemCoverageOut(**_ser(r)) for r in rows],
    )


@router.get(
    "/{framework}/item/{item_id}",
    response_model=ItemCoverageOut,
    operation_id="framework_get_item_coverage",
)
async def item(framework: str, item_id: str, scope: str = "ALL") -> ItemCoverageOut:
    """Return full coverage payload for a single framework item."""
    try:
        coverage = item_coverage(framework, item_id, scope=scope)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return ItemCoverageOut(**_ser(coverage))
