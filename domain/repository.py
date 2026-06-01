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
    EvalResult, RuntimeEvent, FindingStatus, RuntimeStatus,
)
from domain import seed


_DATA_DIR = Path(__import__("os").environ.get("DATA_ROOT") or (Path(__file__).resolve().parents[1] / "data"))
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


def _fold_runtime_status(sys: AISystem) -> AISystem:
    """Overlay governed runtime_status transitions onto the base AISystem.

    `runtime_status` is in LOCKED_FIELDS of the edit flow — the only legal
    mutator is `domain.ai_system_edit.transition_runtime_status`, which
    appends RUNTIME_STATUS_CHANGED events to ai_system_lifecycle.jsonl.
    This helper replays that log so callers see the current effective
    status without mutating ai_systems.jsonl (which is intake-only).
    """
    # Lazy import to avoid circular dependency at module load.
    from domain.ai_system_edit import current_runtime_status
    effective_str = current_runtime_status(sys.id, sys.runtime_status.value)
    if effective_str == sys.runtime_status.value:
        return sys
    try:
        effective = RuntimeStatus(effective_str)
    except ValueError:
        # Defensive: unknown status string in the lifecycle log → keep base.
        # Logged at debug because this is recoverable; the operator should
        # see the malformed event in the lifecycle file directly.
        return sys
    return sys.model_copy(update={"runtime_status": effective})


def list_ai_systems() -> list[AISystem]:
    """All AI systems — seed plus intake-created, with runtime_status folded."""
    intake = [AISystem.model_validate(r) for r in _read_jsonl(SYSTEMS_FILE)]
    return [_fold_runtime_status(s) for s in (list(seed.AI_SYSTEMS) + intake)]


def get_ai_system(system_id: str) -> AISystem | None:
    for s in seed.AI_SYSTEMS:
        if s.id == system_id:
            return _fold_runtime_status(s)
    for r in _read_jsonl(SYSTEMS_FILE):
        if r.get("id") == system_id:
            return _fold_runtime_status(AISystem.model_validate(r))
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
    # F-023 fix (S66): intake- and operator-added evidence now persist to
    # EVIDENCE_FILE alongside the seed/overlay/demo paths. Order preserves
    # priority: seed first (canonical), then mutable layers, then real
    # operator-written rows. The framework completeness rollup reads
    # `evidence_for()` directly, so adding the new file here is enough for
    # newly-added evidence to flow into the matrix without further wiring.
    intake = [Evidence.model_validate(r) for r in _read_jsonl(EVIDENCE_FILE)
              if r.get("ai_system_id") == system_id]
    return (seed.evidence_for(system_id)
            + _overlays().overlay_evidence_for(system_id)
            + _demo_evidence_for(system_id)
            + intake)


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

# F-023 fix (S66): operator-added evidence (intake Step 5 + Edit modal Evidence
# section). Read by evidence_for() above. JSONL one Evidence per line.
EVIDENCE_FILE = _DATA_DIR / "evidence.jsonl"


def _append_jsonl(path: Path, record: dict) -> None:
    """Append a single JSON record as a line to path, creating parent dirs if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def append_evidence(evidence: Evidence) -> None:
    """Persist a single Evidence row to EVIDENCE_FILE.

    Used by:
      - api.intake.submit_intake — materializes the 8 Step 5 URL fields as
        typed Evidence rows after the AISystem record itself is written.
      - api.grc POST /grc/ai-systems/{id}/evidence — operator-driven add
        from the Edit modal Evidence section.

    Per CLAUDE.md project rule "JSONL only via _append_jsonl pattern".
    `evidence.id` must be unique — callers should generate via uuid; we do
    NOT dedupe on append (the seed/overlay layers already produce stable ids
    and operator adds use uuid4).
    """
    _append_jsonl(EVIDENCE_FILE, evidence.model_dump(mode="json"))


def append_agent_event(event_type: str, payload: dict) -> None:
    """Append an agent lifecycle event to data/events.jsonl via the hash chain.

    Delegates to :func:`domain.audit_chain.append_chained_event` so that every
    event written through this helper is part of the tamper-evident SHA-256
    chain.  The ``event_id``, ``prev_hash``, and ``hash`` fields are added
    automatically by the chain writer.

    Args:
        event_type: e.g. 'AGENT_CREATED', 'AGENT_PUBLISHED', 'AGENT_BINDING_CREATED'
        payload:    Arbitrary dict of context fields (agent_id, version_id, etc.)
    """
    # Late import breaks the potential circular import:
    # repository -> audit_chain -> repository (audit_chain calls _append_jsonl directly)
    from domain import audit_chain as _ac  # noqa: PLC0415

    _ac.append_chained_event(event_type, payload)


def read_chain_tail(n: int) -> list[dict]:
    """Return the last *n* events from data/events.jsonl (oldest-first order).

    Thin wrapper around :func:`domain.audit_chain.read_chain_tail` exposed on
    this module for callers that already import from ``domain.repository``.

    Args:
        n: Number of tail events to return.

    Returns:
        List of event dicts; at most *n* entries.
    """
    from domain import audit_chain as _ac  # noqa: PLC0415

    return _ac.read_chain_tail(n)


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
    "append_agent_event", "read_agent_events", "read_chain_tail", "EVENTS_FILE",
    "append_evidence", "EVIDENCE_FILE",
]
