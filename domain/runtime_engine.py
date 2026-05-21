"""Runtime governance engine — per-system state, incidents, approval queue.

Persists all state to JSONL overlays under `data/` so the page survives
restarts and can demonstrate the operational mechanics end-to-end.

Public API:
  get_state(ai_system_id) -> SystemRuntimeState
  set_enabled(ai_system_id, enabled, actor, reason) -> RuntimeAction
  trigger_kill_switch(ai_system_id, actor, reason) -> RuntimeAction
  set_monitoring_level(ai_system_id, level, actor) -> RuntimeAction
  require_human_approval(ai_system_id, action_description, requested_by) -> ApprovalRequest
  resolve_approval(approval_id, decision, approver, note) -> ApprovalRequest
  create_incident(from_event_id, severity, summary, owner) -> Incident
  update_incident(incident_id, status, actor, note) -> Incident
  list_approvals(scope) -> list[ApprovalRequest]
  list_incidents(scope, status_filter) -> list[Incident]
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from uuid import uuid4

from domain import seed, repository


_DATA_DIR = Path(__file__).resolve().parents[1] / "data"
_DATA_DIR.mkdir(exist_ok=True)
_STATE_FILE = _DATA_DIR / "runtime_state.jsonl"
_APPROVALS_FILE = _DATA_DIR / "runtime_approvals.jsonl"
_INCIDENTS_FILE = _DATA_DIR / "runtime_incidents.jsonl"


# ---------------------------------------------------------------------------
# State types
# ---------------------------------------------------------------------------

class MonitoringLevel(str, Enum):
    STANDARD = "STANDARD"
    HEIGHTENED = "HEIGHTENED"
    INCIDENT = "INCIDENT"


class ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    MITIGATED = "MITIGATED"
    CLOSED = "CLOSED"


@dataclass
class RuntimeAction:
    """Append-only event recording a runtime control action."""
    id: str
    ai_system_id: str
    ts: str
    action_type: str        # ENABLE / DISABLE / KILL_SWITCH / SET_MONITORING / ...
    actor: str
    payload: dict


@dataclass
class SystemRuntimeState:
    ai_system_id: str
    enabled: bool
    kill_switch_engaged: bool
    monitoring_level: str
    last_change_ts: str | None
    last_change_actor: str | None
    last_change_reason: str | None


@dataclass
class ApprovalRequest:
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


@dataclass
class Incident:
    id: str
    ai_system_id: str
    created_at: str
    created_by: str
    severity: str
    status: str
    summary: str
    owner: str
    from_event_id: str | None
    updates: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Append helpers
# ---------------------------------------------------------------------------

def _append(path: Path, record: dict) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


# ---------------------------------------------------------------------------
# System state
# ---------------------------------------------------------------------------

def _default_state(ai_system_id: str) -> SystemRuntimeState:
    return SystemRuntimeState(
        ai_system_id=ai_system_id, enabled=True, kill_switch_engaged=False,
        monitoring_level=MonitoringLevel.STANDARD.value,
        last_change_ts=None, last_change_actor=None, last_change_reason=None,
    )


def get_state(ai_system_id: str) -> SystemRuntimeState:
    state = _default_state(ai_system_id)
    for rec in _read_jsonl(_STATE_FILE):
        if rec.get("ai_system_id") != ai_system_id:
            continue
        at = rec.get("action_type")
        p = rec.get("payload") or {}
        if at == "DISABLE":      state.enabled = False
        elif at == "ENABLE":     state.enabled = True
        elif at == "KILL_SWITCH":
            state.kill_switch_engaged = True
            state.enabled = False
            state.monitoring_level = MonitoringLevel.INCIDENT.value
        elif at == "RESET_KILL_SWITCH":
            state.kill_switch_engaged = False
        elif at == "SET_MONITORING":
            ml = p.get("level")
            if ml in {l.value for l in MonitoringLevel}:
                state.monitoring_level = ml
        state.last_change_ts = rec.get("ts")
        state.last_change_actor = rec.get("actor")
        state.last_change_reason = p.get("reason")
    return state


def _record_action(ai_system_id: str, action_type: str, actor: str, payload: dict) -> RuntimeAction:
    if not actor or not actor.strip():
        raise ValueError("actor required")
    if repository.get_ai_system(ai_system_id) is None:
        raise ValueError(f"AI system not found: {ai_system_id}")
    ra = RuntimeAction(
        id=f"RA-{uuid4().hex[:8].upper()}", ai_system_id=ai_system_id,
        ts=datetime.utcnow().isoformat() + "Z",
        action_type=action_type, actor=actor.strip(), payload=payload,
    )
    _append(_STATE_FILE, asdict(ra))
    return ra


def set_enabled(ai_system_id: str, enabled: bool, actor: str, reason: str | None = None) -> RuntimeAction:
    return _record_action(ai_system_id, "ENABLE" if enabled else "DISABLE", actor, {"reason": reason})


def trigger_kill_switch(ai_system_id: str, actor: str, reason: str) -> RuntimeAction:
    if not reason or not reason.strip():
        raise ValueError("reason required for kill switch")
    return _record_action(ai_system_id, "KILL_SWITCH", actor, {"reason": reason.strip()})


def reset_kill_switch(ai_system_id: str, actor: str, reason: str | None = None) -> RuntimeAction:
    return _record_action(ai_system_id, "RESET_KILL_SWITCH", actor, {"reason": reason})


def set_monitoring_level(ai_system_id: str, level: str, actor: str) -> RuntimeAction:
    if level not in {l.value for l in MonitoringLevel}:
        raise ValueError(f"level must be one of {[l.value for l in MonitoringLevel]}")
    return _record_action(ai_system_id, "SET_MONITORING", actor, {"level": level})


# ---------------------------------------------------------------------------
# Approval queue
# ---------------------------------------------------------------------------

def _expire_old_approvals(records: list[dict]) -> None:
    """In-memory expiry — when an approval has expired, surface it as EXPIRED."""
    now = datetime.utcnow()
    for r in records:
        if r.get("status") == ApprovalStatus.PENDING.value:
            try:
                exp = datetime.fromisoformat(r["expires_at"].replace("Z", ""))
            except Exception:
                continue
            if exp < now:
                r["status"] = ApprovalStatus.EXPIRED.value


def list_approvals(scope: str = "ALL") -> list[ApprovalRequest]:
    records = _read_jsonl(_APPROVALS_FILE)
    _expire_old_approvals(records)
    if scope != "ALL":
        records = [r for r in records if r.get("ai_system_id") == scope]
    return [ApprovalRequest(**r) for r in records]


def require_human_approval(ai_system_id: str, action_description: str,
                            requested_by: str, ttl_minutes: int = 60) -> ApprovalRequest:
    if not action_description.strip():
        raise ValueError("action_description required")
    if not requested_by.strip():
        raise ValueError("requested_by required")
    if repository.get_ai_system(ai_system_id) is None:
        raise ValueError(f"AI system not found: {ai_system_id}")

    now = datetime.utcnow()
    req = ApprovalRequest(
        id=f"AP-{uuid4().hex[:8].upper()}",
        ai_system_id=ai_system_id,
        action_description=action_description.strip(),
        requested_by=requested_by.strip(),
        requested_at=now.isoformat() + "Z",
        expires_at=(now + timedelta(minutes=ttl_minutes)).isoformat() + "Z",
        status=ApprovalStatus.PENDING.value,
    )
    _append(_APPROVALS_FILE, asdict(req))
    return req


def resolve_approval(approval_id: str, decision: str, approver: str, note: str | None = None) -> ApprovalRequest:
    if decision not in (ApprovalStatus.APPROVED.value, ApprovalStatus.REJECTED.value):
        raise ValueError("decision must be APPROVED or REJECTED")
    if not approver.strip():
        raise ValueError("approver required")

    # We log the decision as a new record that supersedes the pending one.
    records = _read_jsonl(_APPROVALS_FILE)
    original = next((r for r in records if r.get("id") == approval_id), None)
    if not original:
        raise ValueError(f"Approval not found: {approval_id}")
    if original.get("status") != ApprovalStatus.PENDING.value:
        raise ValueError(f"Approval already resolved (status={original.get('status')})")

    resolved = ApprovalRequest(
        id=approval_id, ai_system_id=original["ai_system_id"],
        action_description=original["action_description"],
        requested_by=original["requested_by"],
        requested_at=original["requested_at"],
        expires_at=original["expires_at"],
        status=decision, approver=approver.strip(),
        decision_ts=datetime.utcnow().isoformat() + "Z",
        note=note,
    )
    _append(_APPROVALS_FILE, asdict(resolved))
    return resolved


def _collapse_approvals(records: list[dict]) -> list[dict]:
    """Latest record per approval id wins."""
    by_id: dict[str, dict] = {}
    for r in records:
        by_id[r["id"]] = r
    return list(by_id.values())


# Override the simple list_approvals to collapse history
def list_approvals(scope: str = "ALL") -> list[ApprovalRequest]:  # noqa: F811
    records = _collapse_approvals(_read_jsonl(_APPROVALS_FILE))
    _expire_old_approvals(records)
    if scope != "ALL":
        records = [r for r in records if r.get("ai_system_id") == scope]
    records.sort(key=lambda r: r["requested_at"], reverse=True)
    return [ApprovalRequest(**r) for r in records]


# ---------------------------------------------------------------------------
# Incidents
# ---------------------------------------------------------------------------

def list_incidents(scope: str = "ALL", status: str | None = None) -> list[Incident]:
    records = _collapse_incidents(_read_jsonl(_INCIDENTS_FILE))
    if scope != "ALL":
        records = [r for r in records if r.get("ai_system_id") == scope]
    if status:
        records = [r for r in records if r.get("status") == status]
    records.sort(key=lambda r: r["created_at"], reverse=True)
    return [Incident(**r) for r in records]


def _collapse_incidents(records: list[dict]) -> list[dict]:
    by_id: dict[str, dict] = {}
    for r in records:
        if r["id"] not in by_id:
            by_id[r["id"]] = dict(r)
            by_id[r["id"]].setdefault("updates", [])
        # Apply update record
        if r.get("_update"):
            inc = by_id[r["id"]]
            upd = r["_update"]
            inc["updates"].append(upd)
            inc["status"] = upd.get("new_status", inc["status"])
    return list(by_id.values())


def create_incident(from_event_id: str | None, ai_system_id: str, severity: str,
                    summary: str, owner: str, actor: str) -> Incident:
    if repository.get_ai_system(ai_system_id) is None:
        raise ValueError(f"AI system not found: {ai_system_id}")
    if not (summary or "").strip():
        raise ValueError("summary required")
    if not (owner or "").strip():
        raise ValueError("owner required")

    inc = Incident(
        id=f"INC-{uuid4().hex[:8].upper()}", ai_system_id=ai_system_id,
        created_at=datetime.utcnow().isoformat() + "Z",
        created_by=actor.strip(), severity=severity,
        status=IncidentStatus.OPEN.value, summary=summary.strip(),
        owner=owner.strip(), from_event_id=from_event_id, updates=[],
    )
    _append(_INCIDENTS_FILE, asdict(inc))
    return inc


def update_incident(incident_id: str, new_status: str, actor: str, note: str | None = None) -> Incident:
    if new_status not in {s.value for s in IncidentStatus}:
        raise ValueError(f"status must be one of {[s.value for s in IncidentStatus]}")
    if not (actor or "").strip():
        raise ValueError("actor required")

    existing = next((r for r in _read_jsonl(_INCIDENTS_FILE) if r.get("id") == incident_id), None)
    if not existing:
        raise ValueError(f"Incident not found: {incident_id}")

    update_rec = {
        "id": incident_id,
        "ai_system_id": existing["ai_system_id"],
        "created_at": existing["created_at"],
        "created_by": existing["created_by"],
        "severity": existing["severity"],
        "status": new_status,
        "summary": existing["summary"],
        "owner": existing["owner"],
        "from_event_id": existing.get("from_event_id"),
        "updates": [],
        "_update": {
            "ts": datetime.utcnow().isoformat() + "Z",
            "actor": actor.strip(),
            "new_status": new_status,
            "note": note,
        },
    }
    _append(_INCIDENTS_FILE, update_rec)
    return next(i for i in list_incidents() if i.id == incident_id)


__all__ = [
    "MonitoringLevel", "ApprovalStatus", "IncidentStatus",
    "RuntimeAction", "SystemRuntimeState", "ApprovalRequest", "Incident",
    "get_state", "set_enabled", "trigger_kill_switch", "reset_kill_switch",
    "set_monitoring_level",
    "require_human_approval", "resolve_approval", "list_approvals",
    "create_incident", "update_incident", "list_incidents",
]
