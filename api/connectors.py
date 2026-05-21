"""Connectors API — list, run sync, fetch cumulative outputs."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum

from fastapi import APIRouter, HTTPException

from domain.connectors import (
    ALL_CONNECTORS, BY_NAME, list_connectors_summary,
)


router = APIRouter(prefix="/api/grc/connectors/v2", tags=["connectors-v2"])


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


@router.get("/list")
async def list_() -> dict:
    return {"connectors": list_connectors_summary()}


@router.post("/{name}/sync")
async def sync(name: str) -> dict:
    if name not in BY_NAME:
        raise HTTPException(status_code=404, detail=f"Unknown connector: {name}")
    result = BY_NAME[name].run()
    return _ser(result)


@router.post("/sync-all")
async def sync_all() -> dict:
    """Run every connector once. Useful for a single demo button."""
    results = [c.run() for c in ALL_CONNECTORS]
    totals = {
        "evals": sum(r.evals_produced for r in results),
        "findings": sum(r.findings_produced for r in results),
        "runtime_events": sum(r.runtime_events_produced for r in results),
        "evidence": sum(r.evidence_produced for r in results),
        "errors": sum(1 for r in results if r.error),
    }
    return {"results": [_ser(r) for r in results], "totals": totals}


@router.get("/{name}/results")
async def results(name: str) -> dict:
    if name not in BY_NAME:
        raise HTTPException(status_code=404, detail=f"Unknown connector: {name}")
    return BY_NAME[name].fetch_results()
