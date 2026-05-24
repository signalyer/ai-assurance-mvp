"""Runtime governance + telemetry API.

Typed per docs/plans/SESSION-13-api-typing-audit.md §3.1.
The previous _ser() dataclass->dict helper is removed -- Pydantic v2 response
models do the conversion directly via .model_dump() at the FastAPI layer.

NOTE on state-mutation responses: per audit doc §10 res #4, state-changing
mutations echo the resource. Here, the "resource" returned by set_enabled /
trigger_kill_switch / etc. is the RuntimeAction audit-log entry (proof of what
happened), NOT the new RuntimeState. The original V1 contract returned the
action; preserved. Clients that want the new state read it via GET /state/{id}.
"""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

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


def _strict() -> ConfigDict:
    return ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Telemetry models
# ---------------------------------------------------------------------------

class RuntimeEventOut(BaseModel):
    """One runtime event (Langfuse / AWS / Datadog / etc.).

    Distinct from api.grc.RuntimeEventOut and api.grc.HomepageRuntimeEventOut
    -- three shapes named "runtime event" for three consumers.
    """
    model_config = _strict()

    id: str
    ai_system_id: str
    timestamp: str
    event_type: str
    severity: str
    source: str
    action_taken: str
    policy_triggered: str | None = None
    linked_control: str | None = None
    linked_framework: str | None = None
    evidence_id: str | None = None
    details: str | None = None
    user_id: str | None = None
    session_id: str | None = None


class RuntimeEventsOut(BaseModel):
    model_config = _strict()

    scope: str
    source: str | None = None
    events: list[RuntimeEventOut]


class ConnectorStatusOut(BaseModel):
    """Status of one runtime connector (Langfuse / AWS CloudTrail / Datadog)."""
    model_config = _strict()

    source: str
    event_count: int
    latest_ts: str | None = None
    status: str
    implementation: str


class ConnectorsOut(BaseModel):
    model_config = _strict()
    connectors: list[ConnectorStatusOut]


# ---------------------------------------------------------------------------
# State models
# ---------------------------------------------------------------------------

class RuntimeStateOut(BaseModel):
    """Per-system runtime state (enabled / kill-switch / monitoring level)."""
    model_config = _strict()

    ai_system_id: str
    enabled: bool
    kill_switch_engaged: bool
    monitoring_level: str
    last_change_ts: str | None = None
    last_change_actor: str | None = None
    last_change_reason: str | None = None


class RuntimeStateRowOut(BaseModel):
    """One row in the all-systems state view (denormalised with name)."""
    model_config = _strict()

    ai_system_id: str
    ai_system_name: str
    enabled: bool
    kill_switch_engaged: bool
    monitoring_level: str
    last_change_ts: str | None = None
    last_change_actor: str | None = None


class RuntimeStatesOut(BaseModel):
    model_config = _strict()
    states: list[RuntimeStateRowOut]


# ---------------------------------------------------------------------------
# RuntimeAction model (returned by mutating endpoints -- audit log entry)
# ---------------------------------------------------------------------------

class RuntimeActionOut(BaseModel):
    """Audit-log entry produced by every runtime state mutation."""
    model_config = _strict()

    id: str
    ai_system_id: str
    ts: str
    action_type: str = Field(
        description="ENABLE | DISABLE | KILL_SWITCH | RESET_KILL_SWITCH | SET_MONITORING etc.",
    )
    actor: str
    payload: dict[str, str | int | bool | None] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Approval models
# ---------------------------------------------------------------------------

class ApprovalOut(BaseModel):
    """A human-approval request (gates a high-risk action)."""
    model_config = _strict()

    id: str
    ai_system_id: str
    action_description: str
    requested_by: str
    requested_at: str
    expires_at: str
    status: str
    approver: str | None = None
    decision_ts: str | None = None
    note: str | None = None


class ApprovalsOut(BaseModel):
    model_config = _strict()
    approvals: list[ApprovalOut]


# ---------------------------------------------------------------------------
# Incident models
# ---------------------------------------------------------------------------

class IncidentUpdateOut(BaseModel):
    """One status-change entry in an incident's update timeline."""
    model_config = _strict()

    ts: str
    actor: str
    new_status: str
    note: str | None = None


class IncidentOut(BaseModel):
    """A runtime incident (created from a runtime event or directly)."""
    model_config = _strict()

    id: str
    ai_system_id: str
    created_at: str
    created_by: str
    severity: str
    status: str
    summary: str
    owner: str
    from_event_id: str | None = None
    updates: list[IncidentUpdateOut]


class IncidentsOut(BaseModel):
    model_config = _strict()
    incidents: list[IncidentOut]


# ---------------------------------------------------------------------------
# Meta model
# ---------------------------------------------------------------------------

class RuntimeMetaOut(BaseModel):
    """Enum vocabulary for clients (monitoring levels, approval/incident statuses)."""
    model_config = _strict()

    monitoring_levels: list[str]
    approval_statuses: list[str]
    incident_statuses: list[str]


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class EnableRequest(BaseModel):
    enabled: bool
    actor: str
    reason: str | None = None


class KillSwitchRequest(BaseModel):
    actor: str
    reason: str


class ResetRequest(BaseModel):
    actor: str
    reason: str | None = None


class MonitoringRequest(BaseModel):
    level: str
    actor: str


class ApprovalCreate(BaseModel):
    ai_system_id: str
    action_description: str
    requested_by: str
    ttl_minutes: int = 60


class ApprovalResolve(BaseModel):
    decision: str = Field(..., description="APPROVED or REJECTED")
    approver: str
    note: str | None = None


class IncidentCreate(BaseModel):
    ai_system_id: str
    severity: str = Field(..., description="CRITICAL|HIGH|MEDIUM|LOW")
    summary: str
    owner: str
    actor: str
    from_event_id: str | None = None


class IncidentUpdate(BaseModel):
    new_status: str
    actor: str
    note: str | None = None


# ===========================================================================
# Telemetry: event stream + connector status
# ===========================================================================

@router.get(
    "/events",
    response_model=RuntimeEventsOut,
    operation_id="runtime_v2_events",
)
async def events(
    scope: str = "ALL",
    source: str | None = None,
    limit: int = 100,
) -> RuntimeEventsOut:
    all_events = fetch_all_events()
    if scope != "ALL":
        all_events = [e for e in all_events if e.ai_system_id == scope]
    if source:
        all_events = [e for e in all_events if e.source == source]
    return RuntimeEventsOut(
        scope=scope,
        source=source,
        events=[RuntimeEventOut(**e.model_dump(mode="json")) for e in all_events[:limit]],
    )


@router.get(
    "/connectors",
    response_model=ConnectorsOut,
    operation_id="runtime_v2_connectors",
)
async def connectors() -> ConnectorsOut:
    """List configured connectors and how many events each currently surfaces."""
    out: list[ConnectorStatusOut] = []
    for c in CONNECTORS:
        evs = c.fetch_events()
        latest = max((e.timestamp for e in evs), default=None)
        out.append(ConnectorStatusOut(
            source=c.source.value,
            event_count=len(evs),
            latest_ts=latest.isoformat() if latest else None,
            status="connected" if evs else "no events",
            implementation="stub -- wire real SDK to enable",
        ))
    return ConnectorsOut(connectors=out)


# ===========================================================================
# Per-system state
# ===========================================================================

@router.get(
    "/state/{ai_system_id}",
    response_model=RuntimeStateOut,
    operation_id="runtime_v2_state_get",
)
async def state(ai_system_id: str) -> RuntimeStateOut:
    if repository.get_ai_system(ai_system_id) is None:
        raise HTTPException(status_code=404, detail="System not found")
    return RuntimeStateOut(**asdict(get_state(ai_system_id)))


@router.get(
    "/state",
    response_model=RuntimeStatesOut,
    operation_id="runtime_v2_state_list",
)
async def all_states() -> RuntimeStatesOut:
    rows: list[RuntimeStateRowOut] = []
    for s in repository.list_ai_systems():
        st = get_state(s.id)
        rows.append(RuntimeStateRowOut(
            ai_system_id=s.id,
            ai_system_name=s.name,
            enabled=st.enabled,
            kill_switch_engaged=st.kill_switch_engaged,
            monitoring_level=st.monitoring_level,
            last_change_ts=st.last_change_ts,
            last_change_actor=st.last_change_actor,
        ))
    return RuntimeStatesOut(states=rows)


# ===========================================================================
# Runtime control actions (mutating -- return RuntimeActionOut audit entry)
# ===========================================================================

@router.post(
    "/state/{ai_system_id}/enabled",
    response_model=RuntimeActionOut,
    operation_id="runtime_v2_enabled_set",
)
async def post_enabled(ai_system_id: str, req: EnableRequest) -> RuntimeActionOut:
    try:
        return RuntimeActionOut(**asdict(
            set_enabled(ai_system_id, req.enabled, req.actor, req.reason),
        ))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/state/{ai_system_id}/kill-switch",
    response_model=RuntimeActionOut,
    operation_id="runtime_v2_kill_switch",
)
async def post_kill_switch(ai_system_id: str, req: KillSwitchRequest) -> RuntimeActionOut:
    try:
        return RuntimeActionOut(**asdict(
            trigger_kill_switch(ai_system_id, req.actor, req.reason),
        ))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/state/{ai_system_id}/reset-kill-switch",
    response_model=RuntimeActionOut,
    operation_id="runtime_v2_reset_kill_switch",
)
async def post_reset_kill(ai_system_id: str, req: ResetRequest) -> RuntimeActionOut:
    try:
        return RuntimeActionOut(**asdict(
            reset_kill_switch(ai_system_id, req.actor, req.reason),
        ))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/state/{ai_system_id}/monitoring",
    response_model=RuntimeActionOut,
    operation_id="runtime_v2_monitoring_set",
)
async def post_monitoring(ai_system_id: str, req: MonitoringRequest) -> RuntimeActionOut:
    try:
        return RuntimeActionOut(**asdict(
            set_monitoring_level(ai_system_id, req.level, req.actor),
        ))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ===========================================================================
# Human approval queue
# ===========================================================================

@router.get(
    "/approvals",
    response_model=ApprovalsOut,
    operation_id="runtime_v2_approvals_list",
)
async def approvals(scope: str = "ALL") -> ApprovalsOut:
    return ApprovalsOut(
        approvals=[ApprovalOut(**asdict(a)) for a in list_approvals(scope=scope)],
    )


@router.post(
    "/approvals",
    response_model=ApprovalOut,
    operation_id="runtime_v2_approval_create",
)
async def post_approval(req: ApprovalCreate) -> ApprovalOut:
    try:
        return ApprovalOut(**asdict(require_human_approval(
            req.ai_system_id, req.action_description, req.requested_by, req.ttl_minutes,
        )))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/approvals/{approval_id}/resolve",
    response_model=ApprovalOut,
    operation_id="runtime_v2_approval_resolve",
)
async def post_approval_resolve(approval_id: str, req: ApprovalResolve) -> ApprovalOut:
    try:
        return ApprovalOut(**asdict(resolve_approval(
            approval_id, req.decision, req.approver, req.note,
        )))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ===========================================================================
# Incidents
# ===========================================================================

@router.get(
    "/incidents",
    response_model=IncidentsOut,
    operation_id="runtime_v2_incidents_list",
)
async def incidents(scope: str = "ALL", status: str | None = None) -> IncidentsOut:
    return IncidentsOut(
        incidents=[IncidentOut(**asdict(i)) for i in list_incidents(scope=scope, status=status)],
    )


@router.post(
    "/incidents",
    response_model=IncidentOut,
    operation_id="runtime_v2_incident_create",
)
async def post_incident(req: IncidentCreate) -> IncidentOut:
    try:
        return IncidentOut(**asdict(create_incident(
            req.from_event_id, req.ai_system_id, req.severity,
            req.summary, req.owner, req.actor,
        )))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/incidents/{incident_id}/update",
    response_model=IncidentOut,
    operation_id="runtime_v2_incident_update",
)
async def post_incident_update(incident_id: str, req: IncidentUpdate) -> IncidentOut:
    try:
        return IncidentOut(**asdict(update_incident(
            incident_id, req.new_status, req.actor, req.note,
        )))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ===========================================================================
# Meta
# ===========================================================================

@router.get(
    "/_meta",
    response_model=RuntimeMetaOut,
    operation_id="runtime_v2_meta",
)
async def meta() -> RuntimeMetaOut:
    return RuntimeMetaOut(
        monitoring_levels=[l.value for l in MonitoringLevel],
        approval_statuses=[s.value for s in ApprovalStatus],
        incident_statuses=[s.value for s in IncidentStatus],
    )
