"""Findings workflow API.

Typed per docs/plans/SESSION-13-api-typing-audit.md §3.1.
Pattern: inline Pydantic v2 response models with extra='forbid', explicit
operation_id + response_model on every route, no _ser() helper.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from domain.findings_workflow import (
    list_findings, get_finding, apply_event, list_events,
    ALLOWED_EVENT_TYPES,
)


router = APIRouter(prefix="/api/grc/findings/v2", tags=["findings-workflow"])


def _strict() -> ConfigDict:
    return ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------

class FrameworkMappingOut(BaseModel):
    model_config = _strict()
    framework: str
    clause: str


class ControlMappingOut(BaseModel):
    model_config = _strict()
    control_id: str
    title: str
    priority: str
    domain: str


class FindingExceptionOut(BaseModel):
    """Exception/waiver attached to a finding. Sparse model -- tightened in Phase 1.5."""
    model_config = ConfigDict(extra="allow")


class FindingTimelineEventOut(BaseModel):
    """One event embedded inline in a finding's timeline (no finding_id -- implicit)."""
    model_config = _strict()

    id: str
    ts: str
    actor: str
    event_type: str
    data: dict[str, Any] = Field(default_factory=dict)
    note: str | None = None


class FindingEventOut(BaseModel):
    """One event from apply_event() or list_events() -- includes finding_id."""
    model_config = _strict()

    id: str
    finding_id: str
    ts: str
    actor: str
    event_type: str
    data: dict[str, Any] = Field(default_factory=dict)
    note: str | None = None


# ---------------------------------------------------------------------------
# Main Finding model
# ---------------------------------------------------------------------------

class FindingV2Out(BaseModel):
    """Full finding record (workflow shape from domain.findings_workflow).

    Differs from api.grc.FindingOut: this is the workflow view (has timeline,
    exception, mapped controls/frameworks expanded), GRC view is the summary.
    Two intentional shapes for two consumers.
    """
    model_config = _strict()

    id: str
    ai_system_id: str
    ai_system_name: str
    title: str
    description: str
    severity: str
    priority: str
    framework_mappings: list[FrameworkMappingOut]
    control_id: str | None = None
    asset: str | None = None
    owner: str
    owner_email: str
    sla_due_date: str
    sla_breached: bool
    status: str
    release_impact: str
    evidence_ids: list[str]
    discovered: str
    remediation: str | None = None
    mapped_controls: list[ControlMappingOut]
    mapped_frameworks: list[str]
    release_gates_affected: list[str]
    remediation_guidance: str | None = None
    timeline: list[FindingTimelineEventOut]
    exception: FindingExceptionOut | None = None


class FindingsListOut(BaseModel):
    model_config = _strict()

    scope: str
    findings: list[FindingV2Out]


class FindingEventsOut(BaseModel):
    model_config = _strict()
    events: list[FindingEventOut]


class EventTypesMetaOut(BaseModel):
    model_config = _strict()
    event_types: list[str]


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class EventRequest(BaseModel):
    # Request models: extra fields ignored (audit §8 asymmetry rule).
    event_type: str
    actor: str
    data: dict = Field(default_factory=dict)
    note: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _finding_to_out(f: object) -> FindingV2Out:
    """Convert a domain Finding dataclass to the API response model."""
    return FindingV2Out(**asdict(f))


def _event_to_out(e: object) -> FindingEventOut:
    return FindingEventOut(**asdict(e))


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/list", response_model=FindingsListOut, operation_id="findings_v2_list")
async def list_(scope: str = "ALL") -> FindingsListOut:
    rows = list_findings(scope=scope)
    return FindingsListOut(
        scope=scope,
        findings=[_finding_to_out(r) for r in rows],
    )


@router.get("/{finding_id}", response_model=FindingV2Out, operation_id="findings_v2_get")
async def get(finding_id: str) -> FindingV2Out:
    v = get_finding(finding_id)
    if v is None:
        raise HTTPException(status_code=404, detail="Finding not found")
    return _finding_to_out(v)


@router.post(
    "/{finding_id}/event",
    response_model=FindingEventOut,
    operation_id="findings_v2_event_create",
)
async def post_event(finding_id: str, req: EventRequest) -> FindingEventOut:
    try:
        ev = apply_event(finding_id, req.event_type, req.actor, req.data, req.note)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _event_to_out(ev)


@router.get(
    "/{finding_id}/events",
    response_model=FindingEventsOut,
    operation_id="findings_v2_events_list",
)
async def get_events(finding_id: str) -> FindingEventsOut:
    return FindingEventsOut(events=[_event_to_out(e) for e in list_events(finding_id)])


@router.get(
    "/_meta/event-types",
    response_model=EventTypesMetaOut,
    operation_id="findings_v2_event_types_meta",
)
async def meta_event_types() -> EventTypesMetaOut:
    return EventTypesMetaOut(event_types=sorted(ALLOWED_EVENT_TYPES))
