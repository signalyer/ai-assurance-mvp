"""Runtime governance + telemetry API."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from domain.runtime_connectors import fetch_all_events, CONNECTORS
from domain.runtime_engine import (
    MonitoringLevel, IncidentStatus, ApprovalStatus,
    get_state, set_enabled, trigger_kill_switch, reset_kill_switch,
    set_monitoring_level,
    require_human_approval, resolve_approval, list_approvals,
    create_incident, update_incident, list_incidents,
)
from domain import repository


router = APIRouter(prefix="/api/grc/runtime/v2", tags=["runtime-governance"])


def _ser(o):
    if is_dataclass(o):
        return {k: _ser(v) for k, v in asdict(o).items()}
    if isinstance(o, Enum):
        return o.value
    if isinstance(o, datetime):
        return o.isoformat()
    if isinstance(o, (list, tuple)):
        return [_ser(v) for v in o]
    if isinstance(o, dict):
        return {k: _ser(v) for k, v in o.items()}
    return o


# ---------- Telemetry: event stream + connector status ----------

@router.get("/events")
async def events(scope: str = "ALL", source: str | None = None, limit: int = 100) -> dict:
    all_events = fetch_all_events()
    if scope != "ALL":
        all_events = [e for e in all_events if e.ai_system_id == scope]
    if source:
        all_events = [e for e in all_events if e.source.value == source]
    return {
        "scope": scope, "source": source,
        "events": [e.model_dump(mode="json") for e in all_events[:limit]],
    }


@router.get("/connectors")
async def connectors() -> dict:
    """List configured connectors and how many events each currently surfaces."""
    out = []
    for c in CONNECTORS:
        events = c.fetch_events()
        out.append({
            "source": c.source.value,
            "event_count": len(events),
            "latest_ts": max((e.timestamp for e in events), default=None),
            "status": "connected" if events else "no events",
            "implementation": "stub — wire real SDK to enable",
        })
    return {"connectors": out}


# ---------- Per-system state ----------

@router.get("/state/{ai_system_id}")
async def state(ai_system_id: str) -> dict:
    if repository.get_ai_system(ai_system_id) is None:
        raise HTTPException(status_code=404, detail="System not found")
    return _ser(get_state(ai_system_id))


@router.get("/state")
async def all_states() -> dict:
    rows = []
    for s in repository.list_ai_systems():
        st = get_state(s.id)
        rows.append({
            "ai_system_id": s.id, "ai_system_name": s.name,
            "enabled": st.enabled, "kill_switch_engaged": st.kill_switch_engaged,
            "monitoring_level": st.monitoring_level,
            "last_change_ts": st.last_change_ts, "last_change_actor": st.last_change_actor,
        })
    return {"states": rows}


# ---------- Runtime control actions ----------

class EnableRequest(BaseModel):
    enabled: bool
    actor: str
    reason: str | None = None


@router.post("/state/{ai_system_id}/enabled")
async def post_enabled(ai_system_id: str, req: EnableRequest) -> dict:
    try:
        return _ser(set_enabled(ai_system_id, req.enabled, req.actor, req.reason))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


class KillSwitchRequest(BaseModel):
    actor: str
    reason: str


@router.post("/state/{ai_system_id}/kill-switch")
async def post_kill_switch(ai_system_id: str, req: KillSwitchRequest) -> dict:
    try:
        return _ser(trigger_kill_switch(ai_system_id, req.actor, req.reason))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


class ResetRequest(BaseModel):
    actor: str
    reason: str | None = None


@router.post("/state/{ai_system_id}/reset-kill-switch")
async def post_reset_kill(ai_system_id: str, req: ResetRequest) -> dict:
    try:
        return _ser(reset_kill_switch(ai_system_id, req.actor, req.reason))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


class MonitoringRequest(BaseModel):
    level: str
    actor: str


@router.post("/state/{ai_system_id}/monitoring")
async def post_monitoring(ai_system_id: str, req: MonitoringRequest) -> dict:
    try:
        return _ser(set_monitoring_level(ai_system_id, req.level, req.actor))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------- Human approval queue ----------

class ApprovalCreate(BaseModel):
    ai_system_id: str
    action_description: str
    requested_by: str
    ttl_minutes: int = 60


@router.get("/approvals")
async def approvals(scope: str = "ALL") -> dict:
    return {"approvals": [_ser(a) for a in list_approvals(scope=scope)]}


@router.post("/approvals")
async def post_approval(req: ApprovalCreate) -> dict:
    try:
        return _ser(require_human_approval(req.ai_system_id, req.action_description, req.requested_by, req.ttl_minutes))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


class ApprovalResolve(BaseModel):
    decision: str = Field(..., description="APPROVED or REJECTED")
    approver: str
    note: str | None = None


@router.post("/approvals/{approval_id}/resolve")
async def post_approval_resolve(approval_id: str, req: ApprovalResolve) -> dict:
    try:
        return _ser(resolve_approval(approval_id, req.decision, req.approver, req.note))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------- Incidents ----------

class IncidentCreate(BaseModel):
    ai_system_id: str
    severity: str = Field(..., description="CRITICAL|HIGH|MEDIUM|LOW")
    summary: str
    owner: str
    actor: str
    from_event_id: str | None = None


@router.get("/incidents")
async def incidents(scope: str = "ALL", status: str | None = None) -> dict:
    return {"incidents": [_ser(i) for i in list_incidents(scope=scope, status=status)]}


@router.post("/incidents")
async def post_incident(req: IncidentCreate) -> dict:
    try:
        return _ser(create_incident(
            req.from_event_id, req.ai_system_id, req.severity,
            req.summary, req.owner, req.actor,
        ))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


class IncidentUpdate(BaseModel):
    new_status: str
    actor: str
    note: str | None = None


@router.post("/incidents/{incident_id}/update")
async def post_incident_update(incident_id: str, req: IncidentUpdate) -> dict:
    try:
        return _ser(update_incident(incident_id, req.new_status, req.actor, req.note))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------- Meta ----------

@router.get("/_meta")
async def meta() -> dict:
    return {
        "monitoring_levels": [l.value for l in MonitoringLevel],
        "approval_statuses": [s.value for s in ApprovalStatus],
        "incident_statuses": [s.value for s in IncidentStatus],
    }
