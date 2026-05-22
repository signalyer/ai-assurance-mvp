"""Thin repository over the domain layer.

Unifies seed data (the five FS systems hard-coded in `domain.seed`) with
intake-created systems (persisted as JSONL under `data/`). All accessors return
strongly-typed Pydantic models — callers should never see raw dicts.
"""

from __future__ import annotations

import json
from pathlib import Path

from domain.models import (
    AISystem, Assessment, ReleaseGate, Finding, Evidence,
    EvalResult, RuntimeEvent, FindingStatus,
)
from domain import seed


_DATA_DIR = Path(__file__).resolve().parents[1] / "data"
SYSTEMS_FILE = _DATA_DIR / "ai_systems.jsonl"
ASSESSMENTS_FILE = _DATA_DIR / "assessments.jsonl"
GATES_FILE = _DATA_DIR / "release_gates.jsonl"
FINDINGS_EVENTS_FILE = _DATA_DIR / "findings_events.jsonl"
DEMO_OVERLAY_FILE = _DATA_DIR / "demo_overlay.jsonl"


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def list_ai_systems() -> list[AISystem]:
    """All AI systems — seed plus intake-created."""
    intake = [AISystem.model_validate(r) for r in _read_jsonl(SYSTEMS_FILE)]
    return list(seed.AI_SYSTEMS) + intake


def get_ai_system(system_id: str) -> AISystem | None:
    for s in seed.AI_SYSTEMS:
        if s.id == system_id:
            return s
    for r in _read_jsonl(SYSTEMS_FILE):
        if r.get("id") == system_id:
            return AISystem.model_validate(r)
    return None


def _overlays():
    """Lazy-import the connectors overlay to avoid a circular import at module load."""
    from domain import connectors as _c
    return _c


# --- findings_workflow event fold ---------------------------------------------
# The findings workflow appends events to data/findings_events.jsonl. To keep the
# rest of the platform (assessment engine, release gates) consistent with the
# workflow's "current" view, we fold CHANGE_STATUS / MARK_REMEDIATED /
# VERIFY_REMEDIATION / CLOSE / RISK_ACCEPT events into Finding.status.

_STATUS_TERMINAL_EVENTS = {
    "MARK_REMEDIATED": FindingStatus.REMEDIATED,
    "VERIFY_REMEDIATION": FindingStatus.VERIFIED,
    "CLOSE": FindingStatus.CLOSED,
    "RISK_ACCEPT": FindingStatus.RISK_ACCEPTED,
}


def _status_overrides_by_finding() -> dict[str, FindingStatus]:
    """Replay event log (oldest first) and produce the final status per finding."""
    events = _read_jsonl(FINDINGS_EVENTS_FILE)
    events.sort(key=lambda e: e.get("ts", ""))
    out: dict[str, FindingStatus] = {}
    for ev in events:
        fid = ev.get("finding_id")
        et = ev.get("event_type")
        if not fid or not et:
            continue
        if et in _STATUS_TERMINAL_EVENTS:
            out[fid] = _STATUS_TERMINAL_EVENTS[et]
        elif et == "CHANGE_STATUS":
            ns = (ev.get("data") or {}).get("new_status")
            try:
                out[fid] = FindingStatus(ns)
            except (ValueError, TypeError):
                pass
    return out


def _apply_status_overrides(findings: list[Finding]) -> list[Finding]:
    overrides = _status_overrides_by_finding()
    if not overrides:
        return findings
    out: list[Finding] = []
    for f in findings:
        new_status = overrides.get(f.id)
        if new_status and new_status != f.status:
            out.append(f.model_copy(update={"status": new_status}))
        else:
            out.append(f)
    return out


# --- demo overlay -------------------------------------------------------------
# A self-contained overlay used only by the guided demo walkthrough. Each line
# is {"kind": "evidence"|"finding"|..., "ai_system_id": "...", "data": {...}}.
# The demo /reset endpoint truncates this file.

def _demo_records(kind: str, system_id: str) -> list[dict]:
    out: list[dict] = []
    for r in _read_jsonl(DEMO_OVERLAY_FILE):
        if r.get("kind") != kind:
            continue
        data = r.get("data") or {}
        if data.get("ai_system_id") == system_id:
            out.append(data)
    return out


def _demo_evidence_for(system_id: str) -> list[Evidence]:
    out: list[Evidence] = []
    for r in _demo_records("evidence", system_id):
        try:
            out.append(Evidence.model_validate(r))
        except Exception:                                                # noqa: BLE001
            pass
    return out


def _demo_evals_for(system_id: str) -> list[EvalResult]:
    out: list[EvalResult] = []
    for r in _demo_records("eval", system_id):
        try:
            out.append(EvalResult.model_validate(r))
        except Exception:                                                # noqa: BLE001
            pass
    return out


# --- accessors ---------------------------------------------------------------

def findings_for(system_id: str) -> list[Finding]:
    base = seed.findings_for(system_id) + _overlays().overlay_findings_for(system_id)
    return _apply_status_overrides(base)


def evidence_for(system_id: str) -> list[Evidence]:
    return (seed.evidence_for(system_id)
            + _overlays().overlay_evidence_for(system_id)
            + _demo_evidence_for(system_id))


def eval_results_for(system_id: str) -> list[EvalResult]:
    return ([e for e in seed.EVAL_RESULTS if e.ai_system_id == system_id]
            + _overlays().overlay_evals_for(system_id)
            + _demo_evals_for(system_id))


def runtime_events_for(system_id: str) -> list[RuntimeEvent]:
    return seed.events_for(system_id) + _overlays().overlay_runtime_events_for(system_id)


def release_gates_for(system_id: str) -> list[ReleaseGate]:
    seeded = seed.gates_for(system_id)
    intake = [ReleaseGate.model_validate(r) for r in _read_jsonl(GATES_FILE)
              if r.get("ai_system_id") == system_id]
    return seeded + intake


def assessments_for(system_id: str) -> list[Assessment]:
    seeded = [a for a in seed.ASSESSMENTS if a.ai_system_id == system_id]
    intake = [Assessment.model_validate(r) for r in _read_jsonl(ASSESSMENTS_FILE)
              if r.get("ai_system_id") == system_id]
    return seeded + intake


EVENTS_FILE = _DATA_DIR / "events.jsonl"


def _append_jsonl(path: Path, record: dict) -> None:
    """Append a single JSON record as a line to path, creating parent dirs if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def append_agent_event(event_type: str, payload: dict) -> None:
    """Append an agent lifecycle event to data/events.jsonl.

    Every event receives an ISO timestamp at write time.  This JSONL file is
    the immutable audit trail for the agent registry — Postgres is the live
    query store; this file is the append-only record for compliance purposes.

    Args:
        event_type: e.g. 'AGENT_CREATED', 'AGENT_PUBLISHED', 'AGENT_BINDING_CREATED'
        payload:    Arbitrary dict of context fields (agent_id, version_id, etc.)
    """
    from datetime import datetime, timezone

    record = {
        "event_type": event_type,
        "ts": datetime.now(timezone.utc).isoformat(),
        **payload,
    }
    _append_jsonl(EVENTS_FILE, record)


def read_agent_events(event_type: str | None = None) -> list[dict]:
    """Read agent lifecycle events from data/events.jsonl.

    Args:
        event_type: Optional filter; if supplied only events matching this type
                    are returned.  Pass None to return all events.

    Returns:
        List of event dicts ordered oldest-first (file insertion order).
    """
    records = _read_jsonl(EVENTS_FILE)
    if event_type is None:
        return records
    return [r for r in records if r.get("event_type") == event_type]


__all__ = [
    "list_ai_systems", "get_ai_system",
    "findings_for", "evidence_for", "eval_results_for",
    "runtime_events_for", "release_gates_for", "assessments_for",
    "DEMO_OVERLAY_FILE", "FINDINGS_EVENTS_FILE",
    "append_agent_event", "read_agent_events", "EVENTS_FILE",
]
