"""Connectors API — list, run sync, fetch cumulative outputs.

Session 28 — Track A OpenAPI sweep, per-router #4.
Four routes get strict Pydantic v2 response models and stable
operation_ids. No UI consumers (verified via Grep across static/ and
team-portal/) so blast radius is limited to OpenAPI clients (none
generated yet) and spec-diff CI — ideal target for strict shapes.

Domain-model payloads (EvalResult/Finding/RuntimeEvent/Evidence) flow
through as list[dict]: they are already validated by the domain layer
on the way in via model_dump(mode="json"), and typing them as the full
Pydantic models here would re-validate on every response and tightly
couple the connectors OpenAPI surface to every domain schema bump.
list[dict] is the right boundary.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from domain.connectors import (
    ALL_CONNECTORS, BY_NAME, list_connectors_summary,
)


router = APIRouter(prefix="/api/grc/connectors/v2", tags=["connectors-v2"])


# ===========================================================================
# Response models (Session 28 — Track A OpenAPI sweep, per-router #4)
# ===========================================================================

class ConnectorSummary(BaseModel):
    """Per-connector status + cumulative output counts.

    Shape produced by domain.connectors.list_connectors_summary().
    All 11 fields always present — strict (no extra="allow").
    """
    name: str
    category: str
    description: str
    status: str
    last_synced_at: Optional[str] = None
    sync_count: int
    evals_produced: int
    findings_produced: int
    runtime_events_produced: int
    evidence_produced: int
    config_keys: list[str]


class ConnectorListResponse(BaseModel):
    """Envelope for GET /list."""
    connectors: list[ConnectorSummary]


class SyncResultModel(BaseModel):
    """Single connector sync outcome.

    Mirrors domain.connectors.SyncResult (dataclass). `error` is None on
    success. `sample_ids` carries up to 3 ids per produced category and
    is keyed on the four fixed category names (evals/findings/
    runtime_events/evidence) — typed as dict[str, list[str]].
    """
    connector: str
    category: str
    ran_at: str
    evals_produced: int
    findings_produced: int
    runtime_events_produced: int
    evidence_produced: int
    error: Optional[str] = None
    sample_ids: dict[str, list[str]] = {}


class SyncAllTotals(BaseModel):
    """Cross-connector totals from POST /sync-all."""
    evals: int
    findings: int
    runtime_events: int
    evidence: int
    errors: int


class SyncAllResponse(BaseModel):
    """Envelope for POST /sync-all."""
    results: list[SyncResultModel]
    totals: SyncAllTotals


class ConnectorResultsResponse(BaseModel):
    """Cumulative outputs for a single connector across all syncs.

    Each list contains domain-model dumps (EvalResult / Finding /
    RuntimeEvent / Evidence). Typed as list[dict] — see module docstring
    for why we don't bind to the full domain Pydantic models here.
    """
    evals: list[dict]
    findings: list[dict]
    runtime_events: list[dict]
    evidence: list[dict]
    sync_count: int


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
    "/list",
    response_model=ConnectorListResponse,
    operation_id="connectors_list_get",
)
async def list_() -> dict:
    return {"connectors": list_connectors_summary()}


@router.post(
    "/{name}/sync",
    response_model=SyncResultModel,
    operation_id="connectors_sync_run",
)
async def sync(name: str) -> dict:
    if name not in BY_NAME:
        raise HTTPException(status_code=404, detail=f"Unknown connector: {name}")
    result = BY_NAME[name].run()
    return _ser(result)


@router.post(
    "/sync-all",
    response_model=SyncAllResponse,
    operation_id="connectors_sync_all_run",
)
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


@router.get(
    "/{name}/results",
    response_model=ConnectorResultsResponse,
    operation_id="connectors_results_get",
)
async def results(name: str) -> dict:
    if name not in BY_NAME:
        raise HTTPException(status_code=404, detail=f"Unknown connector: {name}")
    return BY_NAME[name].fetch_results()
