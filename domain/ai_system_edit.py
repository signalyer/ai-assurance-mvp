"""AI System Edit — first-class revision flow.

Every edit to an AISystem produces an append-only revision record. The platform
classifies each changed field as either SOFT (auto-applied, audit only) or
MATERIAL (requires re-classification + reviewer approval; release is blocked).

This module is the single source of truth for what is editable and what triggers
re-runs of downstream steps.

Storage: data/ai_system_revisions.jsonl  (append-only)
Reads:   fold_for_system() applies approved revisions onto the base AISystem.

Re-trigger registry: Steps 4-10 don't all exist yet, so triggered_reruns is
recorded as a list of step names — when the platform builds the downstream
steps, they read this list and act.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


DATA_DIR = Path(__import__("os").environ.get("DATA_ROOT") or (Path(__file__).resolve().parent.parent / "data"))
DATA_DIR.mkdir(exist_ok=True)
REVISIONS_FILE = DATA_DIR / "ai_system_revisions.jsonl"


# ---------- Field tiers -----------------------------------------------------

# Auto-applied on save, no approval needed. Audit event recorded.
SOFT_FIELDS: frozenset[str] = frozenset({
    "name",
    "description",
    "business_owner",
    "technical_owner",
    "domain",
    "use_case",
    "human_oversight",
    "data_residency",
})

# Require approval; system enters `pending_revision`; release is blocked.
MATERIAL_FIELDS: frozenset[str] = frozenset({
    "cloud_provider",
    "environment",
    "model_provider",
    "models_used",
    "data_classes",
    "autonomy_level",
    "user_population",
    "customer_impact",
    "regulatory_exposure",
    "rag_enabled",
    "rag_sources",
    "tools",
    "aws_services",
})

# Never editable via this flow (system-controlled).
LOCKED_FIELDS: frozenset[str] = frozenset({
    "id",
    "created_at",
    "updated_at",
    "runtime_status",
    "release_decision",
    "inherent_risk",
    "residual_risk",
})


# Material-field -> list of downstream steps that must re-run after approval.
RERUN_MATRIX: dict[str, tuple[str, ...]] = {
    "cloud_provider":      ("required_controls", "evidence", "runtime_monitoring"),
    "environment":         ("release_gates", "runtime_monitoring"),
    "model_provider":      ("risk_classification", "required_controls", "evals", "release_gates", "evidence"),
    "models_used":         ("risk_classification", "evals"),
    "data_classes":        ("risk_classification", "required_controls", "evals", "release_gates", "evidence", "runtime_monitoring"),
    "autonomy_level":      ("risk_classification", "required_controls", "evals", "release_gates"),
    "user_population":     ("risk_classification", "required_controls"),
    "customer_impact":     ("risk_classification", "required_controls", "release_gates"),
    "regulatory_exposure": ("risk_classification", "required_controls", "release_gates", "evidence"),
    "rag_enabled":         ("risk_classification", "required_controls", "evals", "evidence", "runtime_monitoring"),
    "rag_sources":         ("evals", "evidence"),
    "tools":               ("risk_classification", "required_controls", "evals", "release_gates", "evidence", "runtime_monitoring"),
    "aws_services":        ("required_controls", "evidence"),
}

# Approval requirements based on material-edit risk
APPROVAL_ROLES_BY_LEVEL: dict[str, tuple[str, ...]] = {
    "LOW":      ("AI Governance",),
    "MEDIUM":   ("AI Governance",),
    "MODERATE": ("AI Governance",),
    "HIGH":     ("AI Governance", "Cloud Security"),
    "CRITICAL": ("AI Governance", "Cloud Security", "Internal Audit"),
}

VALID_CHANGE_CATEGORIES = (
    "Drift", "Architecture Change", "Scope Expansion",
    "Risk Reduction", "Compliance Update", "Other",
)


# ---------- Model -----------------------------------------------------------

@dataclass
class FieldChange:
    field: str
    before: Any
    after: Any


@dataclass
class Approval:
    user: str
    role: str
    decision: str       # APPROVE | REJECT
    signed_at: str
    note: str = ""


@dataclass
class AISystemRevision:
    revision_id: str
    ai_system_id: str
    created_at: str
    created_by: str

    tier: str           # soft | material
    fields_changed: list[dict]      # [{field, before, after}]
    soft_changes: list[str]
    material_changes: list[str]

    change_reason: str
    change_category: str

    prior_hash: str     # hash of effective state BEFORE this revision
    new_hash: str       # hash of proposed state AFTER

    triggered_reruns: list[str]                # step names
    rerun_status: dict[str, str] = field(default_factory=dict)   # {step: pending|done|n/a}

    approval_status: str = "auto_applied"      # auto_applied | pending | approved | rejected | overridden
    required_approver_roles: list[str] = field(default_factory=list)
    approvers: list[dict] = field(default_factory=list)

    # When in pending state, the proposed full-state snapshot (only material fields)
    proposed_state: dict[str, Any] = field(default_factory=dict)


# ---------- Helpers ---------------------------------------------------------

def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append(rec: dict) -> None:
    with REVISIONS_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")


def _load_all() -> list[dict]:
    if not REVISIONS_FILE.exists():
        return []
    out: list[dict] = []
    with REVISIONS_FILE.open("r", encoding="utf-8") as fh:
        for line in fh:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _hash_state(state: dict) -> str:
    canonical = json.dumps(state, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def classify_field(field_name: str) -> str:
    """Return 'soft' | 'material' | 'locked' | 'unknown'."""
    if field_name in LOCKED_FIELDS:
        return "locked"
    if field_name in SOFT_FIELDS:
        return "soft"
    if field_name in MATERIAL_FIELDS:
        return "material"
    return "unknown"


def field_tiers() -> dict[str, list[str]]:
    return {
        "soft": sorted(SOFT_FIELDS),
        "material": sorted(MATERIAL_FIELDS),
        "locked": sorted(LOCKED_FIELDS),
    }


# ---------- Revision store accessors ---------------------------------------

def revisions_for_system(ai_system_id: str) -> list[dict]:
    """All revisions for a system, oldest first, latest state per revision_id.

    Each revision_id collapses to its most recent appended record (which contains
    the accumulated approvers + current approval_status).
    """
    latest_by_id: dict[str, dict] = {}
    insertion_order: list[str] = []
    for r in _load_all():
        if r.get("ai_system_id") != ai_system_id:
            continue
        rid = r.get("revision_id")
        if not rid:
            continue
        if rid not in latest_by_id:
            insertion_order.append(rid)
        latest_by_id[rid] = r
    return [latest_by_id[rid] for rid in insertion_order]


def get_revision(revision_id: str) -> Optional[dict]:
    """Return the LATEST appended state for this revision_id.

    The store is append-only — every decision writes a new record sharing the
    revision_id. The latest record wins (it contains the accumulated approvers
    and final approval_status).
    """
    latest: Optional[dict] = None
    for r in _load_all():
        if r.get("revision_id") == revision_id:
            latest = r
    return latest


def _all_revision_ids() -> list[str]:
    seen: list[str] = []
    seen_set: set[str] = set()
    for r in _load_all():
        rid = r.get("revision_id")
        if rid and rid not in seen_set:
            seen.append(rid)
            seen_set.add(rid)
    return seen


def pending_revision(ai_system_id: str) -> Optional[dict]:
    """Most recent pending revision for this system, if any."""
    for rid in reversed(_all_revision_ids()):
        latest = get_revision(rid)
        if latest and latest.get("ai_system_id") == ai_system_id \
           and latest.get("approval_status") == "pending":
            return latest
    return None


def has_pending_material(ai_system_id: str) -> bool:
    return pending_revision(ai_system_id) is not None


def pending_revisions_across_systems() -> list[dict]:
    """Every revision currently in approval_status=='pending', org-wide.

    Newest-first. Mirrors the shape used by RTF's `?status=pending` queue —
    consumer is the CISO Console Revisions Queue (G-1, S65), which needs
    one fetch to render the inbox rather than N+1 per-system polls. Server-
    side walk is O(N) over the revision store once, vs the client otherwise
    fanning `GET /edit-info` across every AI system to discover pending state.
    """
    out: list[dict] = []
    seen: set[str] = set()
    # _all_revision_ids walks the underlying jsonl in append order;
    # reversed = newest-first for the CISO inbox UX.
    for rid in reversed(_all_revision_ids()):
        if rid in seen:
            continue
        seen.add(rid)
        rev = get_revision(rid)
        if rev and rev.get("approval_status") == "pending":
            out.append(rev)
    return out


# ---------- Effective state (fold revisions onto base) ---------------------

_TERMINAL_DECISIONS_FOR_FOLD = {"approved", "auto_applied", "overridden"}


def fold_for_system(ai_system_id: str, base: dict) -> dict:
    """Apply all effective revisions to the base AI system dict.

    Material revisions only apply once they reach 'approved' (or 'overridden').
    Soft revisions apply immediately (status='auto_applied').
    Returns a NEW dict — does not mutate input.
    """
    out = dict(base)
    for r in revisions_for_system(ai_system_id):
        if r.get("approval_status") not in _TERMINAL_DECISIONS_FOR_FOLD:
            continue
        for ch in r.get("fields_changed", []) or []:
            field_name = ch.get("field")
            if field_name and field_name not in LOCKED_FIELDS:
                out[field_name] = ch.get("after")
    return out


def effective_state(ai_system_id: str, base: dict) -> dict:
    """Alias for fold_for_system — public API name."""
    return fold_for_system(ai_system_id, base)


# ---------- Apply edit (the core operation) --------------------------------

def apply_edit(
    *,
    ai_system_id: str,
    base_state: dict,
    proposed_changes: dict[str, Any],
    change_reason: str,
    change_category: str,
    author: str,
    risk_level: str = "MEDIUM",
) -> tuple[Optional[dict], list[str]]:
    """Apply an edit. Returns (revision_record, errors).

    Behavior:
    - Strips locked fields (cannot be edited)
    - Drops no-op fields (same value)
    - Splits remaining into soft / material
    - If ALL soft: revision is auto_applied (no approval needed)
    - If ANY material: revision is pending; system enters pending_revision until
      approval, blocking release. change_reason + change_category required.
    """
    errors: list[str] = []

    if not ai_system_id:
        errors.append("ai_system_id is required")
    if not isinstance(proposed_changes, dict) or not proposed_changes:
        errors.append("proposed_changes must be a non-empty object")
    if errors:
        return None, errors

    # Reject if a material-edit is already pending — must resolve first
    if has_pending_material(ai_system_id):
        return None, ["A material revision is already pending. Approve or reject it before submitting another."]

    soft_changes: list[FieldChange] = []
    material_changes: list[FieldChange] = []
    rejected_locked: list[str] = []
    unknown: list[str] = []

    effective_before = effective_state(ai_system_id, base_state)
    prior_hash = _hash_state(effective_before)

    for field_name, after in proposed_changes.items():
        tier = classify_field(field_name)
        before = effective_before.get(field_name)

        if tier == "locked":
            rejected_locked.append(field_name)
            continue
        if tier == "unknown":
            unknown.append(field_name)
            continue
        if before == after:
            continue  # no-op

        ch = FieldChange(field=field_name, before=before, after=after)
        if tier == "soft":
            soft_changes.append(ch)
        else:
            material_changes.append(ch)

    if rejected_locked:
        errors.append("locked_fields_cannot_be_edited: " + ", ".join(sorted(rejected_locked)))
    if unknown:
        errors.append("unknown_fields: " + ", ".join(sorted(unknown)))
    if not soft_changes and not material_changes:
        errors.append("no_effective_changes")
    if errors:
        return None, errors

    is_material = bool(material_changes)
    if is_material:
        if not change_reason or not change_reason.strip():
            return None, ["change_reason is required for material edits"]
        if change_category not in VALID_CHANGE_CATEGORIES:
            return None, ["change_category must be one of: " + ", ".join(VALID_CHANGE_CATEGORIES)]

    # Build effective-after state
    effective_after = dict(effective_before)
    for ch in (soft_changes + material_changes):
        effective_after[ch.field] = ch.after
    new_hash = _hash_state(effective_after)

    # Compute downstream re-runs
    triggered: list[str] = []
    for ch in material_changes:
        for step in RERUN_MATRIX.get(ch.field, ()):
            if step not in triggered:
                triggered.append(step)

    rev = AISystemRevision(
        revision_id=f"rev-{uuid.uuid4().hex[:12]}",
        ai_system_id=ai_system_id,
        created_at=_iso_now(),
        created_by=author or "system",
        tier=("material" if is_material else "soft"),
        fields_changed=[asdict(c) for c in (soft_changes + material_changes)],
        soft_changes=[c.field for c in soft_changes],
        material_changes=[c.field for c in material_changes],
        change_reason=change_reason.strip() if change_reason else "",
        change_category=change_category if is_material else (change_category or "Other"),
        prior_hash=prior_hash,
        new_hash=new_hash,
        triggered_reruns=triggered,
        rerun_status={s: "pending" for s in triggered},
        approval_status=("pending" if is_material else "auto_applied"),
        required_approver_roles=(
            list(APPROVAL_ROLES_BY_LEVEL.get(risk_level.upper(), ("AI Governance",)))
            if is_material else []
        ),
        approvers=[],
        proposed_state={c.field: c.after for c in material_changes},
    )

    _append(asdict(rev))
    return asdict(rev), []


# ---------- Approve / reject / override ------------------------------------

def decide(
    *,
    revision_id: str,
    decision: str,         # APPROVE | REJECT | OVERRIDE
    user: str,
    role: str,
    note: str = "",
) -> tuple[Optional[dict], list[str]]:
    """Record an approver decision. Append a new revision record reflecting
    the decision state (append-only — original record is preserved by hash).
    """
    decision_u = decision.upper()
    if decision_u not in ("APPROVE", "REJECT", "OVERRIDE"):
        return None, ["decision must be APPROVE, REJECT, or OVERRIDE"]

    rev = get_revision(revision_id)
    if rev is None:
        return None, ["unknown_revision"]
    if rev.get("approval_status") != "pending":
        return None, [f"revision is not pending (current: {rev.get('approval_status')})"]

    approval = {
        "user": user or "system",
        "role": role or "AI Governance",
        "decision": decision_u,
        "signed_at": _iso_now(),
        "note": (note or "").strip(),
    }
    approvers = list(rev.get("approvers") or [])
    approvers.append(approval)

    required_roles = list(rev.get("required_approver_roles") or [])
    approved_roles = {a["role"] for a in approvers if a["decision"] == "APPROVE"}

    if decision_u == "OVERRIDE":
        new_status = "overridden"
    elif decision_u == "REJECT":
        new_status = "rejected"
    elif approved_roles.issuperset(required_roles):
        new_status = "approved"
    else:
        new_status = "pending"   # need more approvals

    updated = dict(rev)
    updated["approvers"] = approvers
    updated["approval_status"] = new_status
    if new_status in ("approved", "rejected", "overridden"):
        updated["decided_at"] = _iso_now()
    _append(updated)
    return updated, []


# ---------- Status for a system --------------------------------------------

# ---------- Runtime-status lifecycle (governed transitions) ----------------
#
# `runtime_status` is in LOCKED_FIELDS — it cannot be mutated via the soft /
# material edit flow above. The intent is that runtime_status moves through
# a small, governed lattice (DESIGN → STAGED → PILOT → PRODUCTION → DECOMMISSIONED)
# and every transition is a first-class audit event, never a free write.
#
# Storage: data/ai_system_lifecycle.jsonl (append-only, mirrors the revisions
# store). repository.get_ai_system / list_ai_systems replay this log on read
# to overlay the latest runtime_status onto the base AISystem.
#
# The synthetic actor "system:bootstrap" is a documented first-class value
# (NOT a back door). Future auditors can grep for "system:*" to find every
# transition the platform made on its own behalf.

LIFECYCLE_FILE = DATA_DIR / "ai_system_lifecycle.jsonl"

# Allowed transitions matrix. Adding STAGED→PILOT or PILOT→PRODUCTION later
# means appending tuples here — no API change required.
ALLOWED_RUNTIME_TRANSITIONS: frozenset[tuple[str, str]] = frozenset({
    ("DESIGN", "STAGED"),
    ("DESIGN", "DEV"),
    ("DEV", "STAGED"),
    ("STAGED", "PILOT"),
    ("PILOT", "PRODUCTION"),
    ("PRODUCTION", "DECOMMISSIONED"),
    ("PILOT", "DECOMMISSIONED"),
    ("STAGED", "DECOMMISSIONED"),
})


def _append_lifecycle(rec: dict) -> None:
    with LIFECYCLE_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")


def lifecycle_events_for_system(ai_system_id: str) -> list[dict]:
    """All lifecycle events for a system, oldest first."""
    if not LIFECYCLE_FILE.exists():
        return []
    out: list[dict] = []
    with LIFECYCLE_FILE.open("r", encoding="utf-8") as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("ai_system_id") == ai_system_id:
                out.append(rec)
    return out


def current_runtime_status(ai_system_id: str, base_status: str) -> str:
    """Replay lifecycle events for this system and return the latest status.

    base_status is the runtime_status read from ai_systems.jsonl (or the seed
    AISystem). If no lifecycle events exist, base_status is returned unchanged.
    """
    latest = base_status
    for ev in lifecycle_events_for_system(ai_system_id):
        if ev.get("event_type") == "RUNTIME_STATUS_CHANGED":
            to_status = ev.get("to_status")
            if isinstance(to_status, str):
                latest = to_status
    return latest


def transition_runtime_status(
    *,
    ai_system_id: str,
    base_status: str,
    to_status: str,
    actor: str,
    reason: str,
) -> tuple[Optional[dict], list[str]]:
    """Append a governed RUNTIME_STATUS_CHANGED event.

    Args:
        ai_system_id: Target system id.
        base_status:  runtime_status from the base AISystem record.
        to_status:    Destination runtime status (must form an allowed pair
                      with the current effective status).
        actor:        User id, or "system:bootstrap" / "system:<name>" for
                      platform-initiated transitions.
        reason:       Free-text rationale recorded in the audit event.

    Returns:
        (event_record, errors). event_record is None on validation failure.
    """
    errors: list[str] = []
    if not ai_system_id:
        errors.append("ai_system_id is required")
    if not isinstance(to_status, str) or not to_status:
        errors.append("to_status is required")
    if not isinstance(actor, str) or not actor.strip():
        errors.append("actor is required")
    if not isinstance(reason, str) or not reason.strip():
        errors.append("reason is required")
    if errors:
        return None, errors

    from_status = current_runtime_status(ai_system_id, base_status)
    if from_status == to_status:
        return None, [f"no-op: already {to_status}"]
    if (from_status, to_status) not in ALLOWED_RUNTIME_TRANSITIONS:
        return None, [f"transition {from_status}->{to_status} is not allowed"]

    event = {
        "event_id": f"lc-{uuid.uuid4().hex[:12]}",
        "ai_system_id": ai_system_id,
        "event_type": "RUNTIME_STATUS_CHANGED",
        "from_status": from_status,
        "to_status": to_status,
        "actor": actor.strip(),
        "reason": reason.strip(),
        "occurred_at": _iso_now(),
    }
    _append_lifecycle(event)
    return event, []


def promote_to_staged(
    *,
    ai_system_id: str,
    base_status: str,
    actor: str,
    reason: str,
) -> tuple[Optional[dict], list[str]]:
    """Convenience wrapper: transition the system to STAGED.

    Thin shim around `transition_runtime_status` for the common Phase-7
    bootstrap path. The general function is preferred for new code that
    might target other destinations.
    """
    return transition_runtime_status(
        ai_system_id=ai_system_id,
        base_status=base_status,
        to_status="STAGED",
        actor=actor,
        reason=reason,
    )


def status_for_system(ai_system_id: str) -> dict:
    """Compute high-level edit status for a system.

    Returns:
        {
          "has_pending_material": bool,
          "release_blocked_by_revision": bool,
          "pending_revision_id": str | None,
          "revision_count": int,
          "last_revision_at": iso str | None,
          "last_revision_tier": str | None,
        }
    """
    revs = revisions_for_system(ai_system_id)
    pending = pending_revision(ai_system_id)
    return {
        "has_pending_material": pending is not None,
        "release_blocked_by_revision": pending is not None,
        "pending_revision_id": (pending or {}).get("revision_id"),
        "revision_count": len(revs),
        "last_revision_at": (revs[-1].get("created_at") if revs else None),
        "last_revision_tier": (revs[-1].get("tier") if revs else None),
    }
