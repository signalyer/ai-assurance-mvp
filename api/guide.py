"""AI Governance Assistant API — page guides, glossary, framework + control lookup.

Session 42 (Tier 3 sweep — last known Tier 3 router):
    - 8 of 9 endpoints consumed by static/shared.js (the Governance Assistant
      panel, shared across every V1 page). 38a coupling grep: heaviest sweep
      target to date — but all shapes are bounded (no event-type polymorphism).
    - All endpoints return strict Pydantic v2 envelopes / models with
      extra="forbid" per 27a default. The tips payload is a `dict[str, dict]`
      (registry keyed by tip_id) — strict envelope, inner tip records left
      as plain dict (consumer reads as map).
    - Operation_id prefix `guide_*` (no collision risk).
    - Verified consumer field-reads in static/shared.js lines 189-414; all
      explicit fields below cover the read paths.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from domain import governance_guide as g


router = APIRouter(prefix="/api/guide", tags=["guide"])


def _strict() -> ConfigDict:
    return ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Response models — /page
# ---------------------------------------------------------------------------


class SeeAlsoLink(BaseModel):
    model_config = _strict()
    label: str
    href: str


class PageGuideOut(BaseModel):
    """Per-page contextual guide. Mirrors domain.governance_guide.PageGuide."""
    model_config = _strict()

    page: str
    title: str
    primary_question: str
    what_it_means: str
    frameworks: list[str]
    next_actions: list[str]
    blocks_production: list[str]
    required_evidence: list[str]
    recommended_remediation: list[str]
    see_also: list[SeeAlsoLink] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Response models — /glossary
# ---------------------------------------------------------------------------


class GlossaryTermOut(BaseModel):
    """Mirrors domain.governance_guide.GlossaryTerm."""
    model_config = _strict()

    term: str
    category: str
    definition: str
    see_also: list[str] = Field(default_factory=list)


class GlossaryOut(BaseModel):
    model_config = _strict()
    terms: list[GlossaryTermOut]


# ---------------------------------------------------------------------------
# Response models — /controls + /controls/{id}
# ---------------------------------------------------------------------------


class ControlIndexRow(BaseModel):
    """Lightweight control summary for /controls listing."""
    model_config = _strict()

    control_id: str
    title: str
    domain: str
    priority: str


class ControlsListOut(BaseModel):
    model_config = _strict()
    controls: list[ControlIndexRow]


class FrameworkMappingOut(BaseModel):
    model_config = _strict()
    framework: str
    clause: str
    rationale: str


class ControlDetailOut(BaseModel):
    """Full control payload for /controls/{control_id}."""
    model_config = _strict()

    control_id: str
    title: str
    domain: str
    priority: str
    requirement: str
    pass_criteria: str
    gate_expression: str | None = None
    failure_impact: str
    recommended_owner: str
    evidence_required: list[str]
    framework_mappings: list[FrameworkMappingOut]
    automated: bool


# ---------------------------------------------------------------------------
# Response models — /frameworks + /framework-item
# ---------------------------------------------------------------------------


class FrameworkIndexRow(BaseModel):
    """Lightweight framework-item summary for /frameworks listing."""
    model_config = _strict()

    id: str
    framework: str
    display_name: str
    snippet: str


class FrameworksListOut(BaseModel):
    model_config = _strict()
    items: list[FrameworkIndexRow]


class FrameworkItemDetailOut(BaseModel):
    """Full framework-item payload for /framework-item."""
    model_config = _strict()

    id: str
    framework: str
    display_name: str
    description: str
    exact_clauses: list[str]
    prefix_clauses: list[str]
    recommended_owner: str


# ---------------------------------------------------------------------------
# Response models — /search
# ---------------------------------------------------------------------------


class SearchControlHit(BaseModel):
    model_config = _strict()
    control_id: str
    title: str
    priority: str
    domain: str


class SearchFrameworkHit(BaseModel):
    model_config = _strict()
    id: str
    framework: str
    display_name: str
    snippet: str


class SearchOut(BaseModel):
    """Aggregate search response."""
    model_config = _strict()

    glossary: list[GlossaryTermOut]
    controls: list[SearchControlHit]
    framework_items: list[SearchFrameworkHit]


# ---------------------------------------------------------------------------
# Response models — /tips + /tips/{tip_id}
# ---------------------------------------------------------------------------


class TipsRegistryOut(BaseModel):
    """Tip registry envelope.

    `tips` is a registry dict keyed by tip_id. Inner shape varies per tip
    type (text vs. action vs. linked-control) and is consumed as a map by
    static/shared.js (line 698), so the inner value is left as `dict[str, Any]`
    rather than a strict model. Outer envelope stays strict.
    """
    model_config = _strict()

    tips: dict[str, dict[str, Any]]


class TipOut(BaseModel):
    """Single tip detail. Polymorphic inner shape — extra=allow per 27a sub-rule."""
    model_config = ConfigDict(extra="allow")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/page",
    response_model=PageGuideOut,
    operation_id="guide_get_page",
)
async def get_page_guide(path: str = Query(..., description="Page path, e.g. /findings")) -> PageGuideOut:
    """Return the contextual guide for a page path; falls back to overview."""
    guide = g.page_guide(path)
    if guide is None:
        guide = g.page_guide("/")
    return PageGuideOut(**guide)  # type: ignore[arg-type]


@router.get(
    "/glossary",
    response_model=GlossaryOut,
    operation_id="guide_get_glossary",
)
async def get_glossary() -> GlossaryOut:
    """Return the full glossary."""
    return GlossaryOut(terms=[GlossaryTermOut(**t) for t in g.all_glossary()])


@router.get(
    "/controls",
    response_model=ControlsListOut,
    operation_id="guide_list_controls",
)
async def list_controls() -> ControlsListOut:
    """Return the control index (lightweight rows)."""
    return ControlsListOut(controls=[ControlIndexRow(**c) for c in g.control_index()])


@router.get(
    "/controls/{control_id}",
    response_model=ControlDetailOut,
    operation_id="guide_get_control",
)
async def get_control(control_id: str) -> ControlDetailOut:
    """Return full detail for a single control."""
    d = g.control_detail(control_id)
    if d is None:
        raise HTTPException(404, f"Control not found: {control_id}")
    return ControlDetailOut(**d)


@router.get(
    "/frameworks",
    response_model=FrameworksListOut,
    operation_id="guide_list_frameworks",
)
async def list_framework_items() -> FrameworksListOut:
    """Return the framework-item index (lightweight rows)."""
    return FrameworksListOut(items=[FrameworkIndexRow(**i) for i in g.framework_index()])


@router.get(
    "/framework-item",
    response_model=FrameworkItemDetailOut,
    operation_id="guide_get_framework_item",
)
async def get_framework_item(q: str = Query(..., description="Clause (LLM01) or id (llm01)")) -> FrameworkItemDetailOut:
    """Return full detail for a framework item by clause or slug."""
    d = g.framework_item_detail(q)
    if d is None:
        raise HTTPException(404, f"Framework item not found: {q}")
    return FrameworkItemDetailOut(**d)


@router.get(
    "/search",
    response_model=SearchOut,
    operation_id="guide_search",
)
async def guide_search(q: str = Query(..., min_length=1)) -> SearchOut:
    """Search across glossary, controls, and framework items."""
    raw = g.search(q)
    return SearchOut(
        glossary=[GlossaryTermOut(**t) for t in raw.get("glossary", [])],
        controls=[SearchControlHit(**c) for c in raw.get("controls", [])],
        framework_items=[SearchFrameworkHit(**i) for i in raw.get("framework_items", [])],
    )


@router.get(
    "/tips",
    response_model=TipsRegistryOut,
    operation_id="guide_list_tips",
)
async def get_tips() -> TipsRegistryOut:
    """Return the full tip registry as a map keyed by tip_id."""
    from domain.tooltips import all_tips
    return TipsRegistryOut(tips=all_tips())


@router.get(
    "/tips/{tip_id}",
    response_model=TipOut,
    operation_id="guide_get_tip",
)
async def get_tip(tip_id: str) -> TipOut:
    """Return a single tip by id."""
    from domain.tooltips import get_tip as _get_tip
    t = _get_tip(tip_id)
    if t is None:
        raise HTTPException(404, f"Unknown tip id: {tip_id}")
    return TipOut(**t)
