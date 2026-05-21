"""Findings workflow API."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from domain.findings_workflow import (
    list_findings, get_finding, apply_event, list_events,
    ALLOWED_EVENT_TYPES,
)


router = APIRouter(prefix="/api/grc/findings/v2", tags=["findings-workflow"])


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
async def list_(scope: str = "ALL") -> dict:
    rows = list_findings(scope=scope)
    return {"scope": scope, "findings": [_ser(r) for r in rows]}


@router.get("/{finding_id}")
async def get(finding_id: str) -> dict:
    v = get_finding(finding_id)
    if v is None:
        raise HTTPException(status_code=404, detail="Finding not found")
    return _ser(v)


class EventRequest(BaseModel):
    event_type: str
    actor: str
    data: dict = Field(default_factory=dict)
    note: str | None = None


@router.post("/{finding_id}/event")
async def post_event(finding_id: str, req: EventRequest) -> dict:
    try:
        ev = apply_event(finding_id, req.event_type, req.actor, req.data, req.note)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _ser(ev)


@router.get("/{finding_id}/events")
async def get_events(finding_id: str) -> dict:
    return {"events": [_ser(e) for e in list_events(finding_id)]}


@router.get("/_meta/event-types")
async def meta_event_types() -> dict:
    return {"event_types": sorted(ALLOWED_EVENT_TYPES)}
