"""AI Governance Assistant API — page guides, glossary, framework + control lookup."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from domain import governance_guide as g


router = APIRouter(prefix="/api/guide", tags=["guide"])


@router.get("/page")
async def get_page_guide(path: str = Query(..., description="Page path, e.g. /findings")) -> dict:
    guide = g.page_guide(path)
    if guide is None:
        # Fall back to overview guide so the panel never returns empty
        guide = g.page_guide("/")
    return guide


@router.get("/glossary")
async def get_glossary() -> dict:
    return {"terms": g.all_glossary()}


@router.get("/controls")
async def list_controls() -> dict:
    return {"controls": g.control_index()}


@router.get("/controls/{control_id}")
async def get_control(control_id: str) -> dict:
    d = g.control_detail(control_id)
    if d is None:
        raise HTTPException(404, f"Control not found: {control_id}")
    return d


@router.get("/frameworks")
async def list_framework_items() -> dict:
    return {"items": g.framework_index()}


@router.get("/framework-item")
async def get_framework_item(q: str = Query(..., description="Clause (LLM01) or id (llm01)")) -> dict:
    d = g.framework_item_detail(q)
    if d is None:
        raise HTTPException(404, f"Framework item not found: {q}")
    return d


@router.get("/search")
async def guide_search(q: str = Query(..., min_length=1)) -> dict:
    return g.search(q)


@router.get("/tips")
async def get_tips() -> dict:
    from domain.tooltips import all_tips
    return {"tips": all_tips()}


@router.get("/tips/{tip_id}")
async def get_tip(tip_id: str) -> dict:
    from domain.tooltips import get_tip as _get_tip
    t = _get_tip(tip_id)
    if t is None:
        raise HTTPException(404, f"Unknown tip id: {tip_id}")
    return t
