"""Findings workflow — overlay state, timeline, and transitions.

Seeded `Finding` objects are the canonical starting state. State changes
(owner assignment, status transitions, comments, risk acceptance, evidence
attachment, remediation verification) are persisted as an append-only event log
in `data/findings_events.jsonl`. The current state of a finding is the fold of
its initial seed + ordered overlay events.

Public API:
  list_findings(scope='ALL'|<system_id>) -> list[FindingView]
  get_finding(finding_id) -> FindingView | None
  apply_event(finding_id, event_type, actor, data) -> FindingEvent
  list_events(finding_id) -> list[FindingEvent]
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from domain.models import Finding, FindingStatus, ReleaseImpact, Severity
from domain.controls import CONTROLS_BY_ID, map_control_to_frameworks
from domain.release_gate_engine import _GATE_TO_CONTROLS, GATE_DEFS
from domain import repository, seed


# ---------------------------------------------------------------------------
# Event log persistence
# ---------------------------------------------------------------------------

_DATA_DIR = Path(__import__("os").environ.get("DATA_ROOT") or (Path(__file__).resolve().parents[1] / "data"))
_DATA_DIR.mkdir(exist_ok=True)
_EVENTS_FILE = _DATA_DIR / "findings_events.jsonl"


ALLOWED_EVENT_TYPES = {
    "ASSIGN_OWNER",
    "CHANGE_STATUS",
    "ATTACH_EVIDENCE",
    "RISK_ACCEPT",
    "MARK_REMEDIATED",
    "VERIFY_REMEDIATION",
    "CLOSE",
    "COMMENT",
}


@dataclass
class FindingEvent:
    id: str
    finding_id: str
    ts: str                            # ISO datetime
    actor: str
    event_type: str                    # one of ALLOWED_EVENT_TYPES
    data: dict                         # event-specific payload
    note: str | None = None


def _read_events() -> list[FindingEvent]:
    if not _EVENTS_FILE.exists():
        return []
    out: list[FindingEvent] = []
    with _EVENTS_FILE.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            out.append(FindingEvent(**r))
    return out


def _append_event(ev: FindingEvent) -> None:
    with _EVENTS_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(ev)) + "\n")


def list_events(finding_id: str) -> list[FindingEvent]:
    return [e for e in _read_events() if e.finding_id == finding_id]


# ---------------------------------------------------------------------------
# View — finding + folded state + drill-down metadata
# ---------------------------------------------------------------------------

@dataclass
class FindingView:
    id: str
    ai_system_id: str
    ai_system_name: str
    title: str
    description: str
    severity: str                       # CRITICAL / HIGH / MEDIUM / LOW
    priority: str                       # P0..P3
    framework_mappings: list[dict]      # [{framework, clause}]
    control_id: str | None
    asset: str | None
    owner: str
    owner_email: str | None
    sla_due_date: str
    sla_breached: bool
    status: str                         # current effective status (after overlay)
    release_impact: str                 # normalized to the new vocabulary
    evidence_ids: list[str]
    discovered: str
    remediation: str | None

    # Drill-down
    mapped_controls: list[dict]         # [{control_id, title, priority}]
    mapped_frameworks: list[str]        # framework names
    release_gates_affected: list[str]
    remediation_guidance: str | None
    timeline: list[dict]                # ordered events with derived display fields
    exception: dict | None              # currently-active RISK_ACCEPT, if any


_SEV_TO_PRIORITY = {
    Severity.CRITICAL.value: "P0",
    Severity.HIGH.value: "P1",
    Severity.MEDIUM.value: "P2",
    Severity.LOW.value: "P3",
    Severity.INFO.value: "P3",
}

_LEGACY_RI_MAP = {
    "BLOCKS_RELEASE": "BLOCK_PRODUCTION",
    "CONDITIONAL": "WARNING",
    "NONE": "NO_IMPACT",
}


def _normalize_release_impact(v: str) -> str:
    return _LEGACY_RI_MAP.get(v, v)


def _gates_for_control(control_id: str | None) -> list[str]:
    if not control_id:
        return []
    return sorted({
        gid for gid, ctrls in _GATE_TO_CONTROLS.items() if control_id in ctrls
    })


def _build_view(f: Finding, events: list[FindingEvent]) -> FindingView:
    # Fold events to compute current state
    status = f.status.value
    owner = f.owner
    owner_email = f.owner_email
    evidence_ids = list(f.evidence_ids)
    exception: dict | None = None
    timeline: list[dict] = []

    fevs = [e for e in events if e.finding_id == f.id]
    fevs.sort(key=lambda e: e.ts)

    for e in fevs:
        d = e.data or {}
        if e.event_type == "ASSIGN_OWNER":
            owner = d.get("owner", owner)
            owner_email = d.get("owner_email", owner_email)
        elif e.event_type == "CHANGE_STATUS":
            status = d.get("new_status", status)
        elif e.event_type == "ATTACH_EVIDENCE":
            for eid in d.get("evidence_ids", []):
                if eid and eid not in evidence_ids:
                    evidence_ids.append(eid)
        elif e.event_type == "RISK_ACCEPT":
            status = FindingStatus.RISK_ACCEPTED.value
            exception = {
                "risk_acceptor": d.get("risk_acceptor"),
                "role": d.get("role"),
                "expires_at": d.get("expires_at"),
                "compensating_controls": d.get("compensating_controls", []),
                "ts": e.ts,
            }
        elif e.event_type == "MARK_REMEDIATED":
            status = FindingStatus.REMEDIATED.value
        elif e.event_type == "VERIFY_REMEDIATION":
            status = FindingStatus.VERIFIED.value
        elif e.event_type == "CLOSE":
            status = FindingStatus.CLOSED.value

        timeline.append({
            "id": e.id,
            "ts": e.ts,
            "actor": e.actor,
            "event_type": e.event_type,
            "data": d,
            "note": e.note,
        })

    # Mapped controls drill-down
    mapped_controls = []
    if f.control_id and f.control_id in CONTROLS_BY_ID:
        c = CONTROLS_BY_ID[f.control_id]
        mapped_controls.append({
            "control_id": c.control_id, "title": c.title,
            "priority": c.priority.value, "domain": c.domain.value,
        })

    mapped_frameworks = sorted({fm.framework.value for fm in f.framework_mappings})
    gates_affected = _gates_for_control(f.control_id)

    sys = repository.get_ai_system(f.ai_system_id)
    sys_name = sys.name if sys else f.ai_system_id

    sla_breached = (
        status not in (FindingStatus.REMEDIATED.value, FindingStatus.VERIFIED.value,
                       FindingStatus.CLOSED.value, FindingStatus.RISK_ACCEPTED.value)
        and f.sla_due_date < date.today()
    )

    return FindingView(
        id=f.id, ai_system_id=f.ai_system_id, ai_system_name=sys_name,
        title=f.title, description=f.description,
        severity=f.severity.value,
        priority=_SEV_TO_PRIORITY.get(f.severity.value, "P3"),
        framework_mappings=[{"framework": fm.framework.value, "clause": fm.clause} for fm in f.framework_mappings],
        control_id=f.control_id, asset=f.asset,
        owner=owner, owner_email=owner_email,
        sla_due_date=f.sla_due_date.isoformat(),
        sla_breached=sla_breached,
        status=status,
        release_impact=_normalize_release_impact(f.release_impact.value),
        evidence_ids=evidence_ids,
        discovered=f.discovered.isoformat(),
        remediation=f.remediation,
        mapped_controls=mapped_controls,
        mapped_frameworks=mapped_frameworks,
        release_gates_affected=gates_affected,
        remediation_guidance=f.remediation,
        timeline=timeline,
        exception=exception,
    )


def list_findings(scope: str = "ALL") -> list[FindingView]:
    events = _read_events()
    if scope == "ALL":
        findings = list(seed.FINDINGS)
    else:
        findings = [f for f in seed.FINDINGS if f.ai_system_id == scope]
    return [_build_view(f, events) for f in findings]


def get_finding(finding_id: str) -> FindingView | None:
    events = _read_events()
    f = next((x for x in seed.FINDINGS if x.id == finding_id), None)
    if not f:
        return None
    return _build_view(f, events)


# ---------------------------------------------------------------------------
# Mutations — append-only event log
# ---------------------------------------------------------------------------

def apply_event(
    finding_id: str, event_type: str, actor: str,
    data: dict[str, Any] | None = None, note: str | None = None,
) -> FindingEvent:
    """Validate + persist an event. Raises ValueError on invalid input."""
    if event_type not in ALLOWED_EVENT_TYPES:
        raise ValueError(f"Unknown event_type: {event_type}")
    if not finding_id:
        raise ValueError("finding_id required")
    if not actor or not actor.strip():
        raise ValueError("actor required")

    # Per-event validation
    d = dict(data or {})
    if event_type == "ASSIGN_OWNER":
        if not d.get("owner"):
            raise ValueError("owner required for ASSIGN_OWNER")
    elif event_type == "CHANGE_STATUS":
        ns = d.get("new_status")
        valid = {s.value for s in FindingStatus}
        if ns not in valid:
            raise ValueError(f"new_status must be one of {sorted(valid)}")
    elif event_type == "ATTACH_EVIDENCE":
        if not d.get("evidence_ids"):
            raise ValueError("evidence_ids required for ATTACH_EVIDENCE")
    elif event_type == "RISK_ACCEPT":
        if not d.get("risk_acceptor") or not d.get("role") or not d.get("expires_at"):
            raise ValueError("risk_acceptor, role, and expires_at required")
        try:
            exp = date.fromisoformat(d["expires_at"])
        except ValueError:
            raise ValueError("expires_at must be ISO date")
        if exp <= date.today() or exp > date.today() + timedelta(days=90):
            raise ValueError("expires_at must be > today and within 90 days (AI-039).")
    elif event_type == "COMMENT":
        if not (note or "").strip():
            raise ValueError("note required for COMMENT")

    # Ensure the finding exists
    if not any(f.id == finding_id for f in seed.FINDINGS):
        raise ValueError(f"Finding not found: {finding_id}")

    ev = FindingEvent(
        id=f"EV-{uuid4().hex[:8].upper()}",
        finding_id=finding_id,
        ts=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        actor=actor.strip(),
        event_type=event_type,
        data=d,
        note=note,
    )
    _append_event(ev)
    return ev


__all__ = [
    "FindingEvent", "FindingView",
    "ALLOWED_EVENT_TYPES",
    "list_findings", "get_finding", "apply_event", "list_events",
]
