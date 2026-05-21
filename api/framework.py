"""Framework coverage API.

Drives the Governance and Security dashboards. All values are computed live
from controls / findings / evidence / release gates — no hardcoded percentages.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum

from fastapi import APIRouter, HTTPException

from domain.framework_coverage import (
    framework_catalog, framework_overview, item_coverage,
)


router = APIRouter(prefix="/api/grc/framework", tags=["framework-coverage"])


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


@router.get("/{framework}/catalog")
async def catalog(framework: str) -> dict:
    try:
        items = framework_catalog(framework)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"items": [_ser(i) for i in items]}


@router.get("/{framework}/overview")
async def overview(framework: str, scope: str = "ALL") -> dict:
    try:
        rows = framework_overview(framework, scope=scope)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {
        "framework": framework,
        "scope": scope,
        "items": [_ser(r) for r in rows],
    }


@router.get("/{framework}/item/{item_id}")
async def item(framework: str, item_id: str, scope: str = "ALL") -> dict:
    try:
        coverage = item_coverage(framework, item_id, scope=scope)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _ser(coverage)
