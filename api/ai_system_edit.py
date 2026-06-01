"""AI System Edit endpoints.

GET  /api/ai-systems/{id}/edit-info          field tiers + current pending status
GET  /api/ai-systems/{id}/effective          AISystem with approved revisions folded in
GET  /api/ai-systems/{id}/revisions          full revision history
GET  /api/ai-systems/revisions/{rev_id}      single revision detail
POST /api/ai-systems/{id}/edit               submit an edit (auto-detects tier)
POST /api/ai-systems/revisions/{rev_id}/decide   approve | reject | override

Typed per docs/plans/SESSION-13-api-typing-audit.md §3.2.
decide_revision: validation failures return 409 ConflictDetail
(STATE_TRANSITION conflict_type) per audit §1.2 + CISO Console requirement.
Edit submission validation failures stay 400 with structured detail.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from itsdangerous import BadSignature, URLSafeTimedSerializer
from pydantic import BaseModel, ConfigDict, Field

from domain import ai_system_edit as ase
from domain import repository as repo
from domain.models import RuntimeFlags
from middleware.auth import require_role

from api._models import ConflictDetail


# ADR-004 §8 Q3: default TTL for calibration is 24h. Production tuning
# (4-8h per §8 Q3) is deferred to Phase 9 and configured via env override.
_DEFAULT_RUNTIME_FLAG_TTL_SECONDS = 86400


def _runtime_flag_ttl_seconds() -> int:
    """Resolve TTL window for a runtime-flag attestation.

    Reads ``RUNTIME_FLAG_TTL_SECONDS`` at call time so the deploy can
    tighten the window without a code change. Falls back to 24h.
    """
    raw = os.getenv("RUNTIME_FLAG_TTL_SECONDS", "").strip()
    if not raw:
        return _DEFAULT_RUNTIME_FLAG_TTL_SECONDS
    try:
        v = int(raw)
        return v if v > 0 else _DEFAULT_RUNTIME_FLAG_TTL_SECONDS
    except ValueError:
        return _DEFAULT_RUNTIME_FLAG_TTL_SECONDS


router = APIRouter(prefix="/api/ai-systems", tags=["ai-system-edit"])


def _strict() -> ConfigDict:
    return ConfigDict(extra="forbid")


# ---------- helpers --------------------------------------------------------

def _current_user(request: Request) -> str:
    token = request.cookies.get("aigovern_session")
    secret = os.getenv("SESSION_SECRET", "")
    if not token or not secret:
        return "system"
    try:
        data = URLSafeTimedSerializer(secret, salt="aigovern-session-v1").loads(token, max_age=600)
    except BadSignature:
        return "system"
    if isinstance(data, dict) and data.get("u"):
        return data["u"]
    return "system"


def _user_role(user: str) -> str:
    """Best-effort role mapping from demo username."""
    if not user or user == "system":
        return "system"
    suffix = user.replace("demo-", "").upper()
    mapping = {
        "CISO": "Cloud Security",
        "CRO":  "AI Governance",
        "AUDIT": "Internal Audit",
        "MRM":  "Model Risk Management",
        "AIGOV": "AI Governance",
    }
    return mapping.get(suffix, "AI Governance")


def _base_dict(system_id: str) -> Optional[dict]:
    s = repo.get_ai_system(system_id)
    if s is None:
        return None
    return s.model_dump(mode="json")


# ---------- request payloads ----------------------------------------------

class EditPayload(BaseModel):
    changes: dict[str, Any] = Field(default_factory=dict)
    change_reason: str = ""
    change_category: str = "Other"


class DecidePayload(BaseModel):
    decision: str       # APPROVE | REJECT | OVERRIDE
    note: str = ""
    role: Optional[str] = None  # optional override; otherwise derived from session user


class RuntimeFlagsPatchPayload(BaseModel):
    """Operator-supplied attestation block.

    Server computes ``attested_by`` (from session cookie), ``attested_at``
    (now), and ``expires_at`` (now + RUNTIME_FLAG_TTL_SECONDS). The caller
    cannot set those — that is the entire safety story of ADR-004 Option B.
    """
    model_config = ConfigDict(extra="forbid")

    dlp_completed: bool
    network_egress_lock_engaged: bool
    justification: str = Field(..., min_length=1)


class RuntimeFlagsOut(BaseModel):
    """Response envelope for the PATCH endpoint."""
    model_config = ConfigDict(extra="forbid")

    ai_system_id: str
    runtime_flags: RuntimeFlags
    ttl_seconds: int


# ---------- response models ------------------------------------------------

class EditStatusOut(BaseModel):
    """Pending-edit status for one AI system."""
    model_config = _strict()

    has_pending_material: bool
    release_blocked_by_revision: bool
    pending_revision_id: str | None = None
    revision_count: int
    last_revision_at: str | None = None
    last_revision_tier: str | None = None


class EditInfoOut(BaseModel):
    """Field tiers + rerun matrix + approval rules + current pending status."""
    model_config = _strict()

    ai_system_id: str
    field_tiers: dict[str, list[str]] = Field(
        description="Map of tier name (soft/material/critical) -> list of field names.",
    )
    rerun_matrix: dict[str, list[str]] = Field(
        description="Map of field name -> downstream steps that must re-run on change.",
    )
    approval_roles_by_level: dict[str, list[str]] = Field(
        description="Map of risk level (LOW/MEDIUM/.../CRITICAL) -> required approver roles.",
    )
    valid_change_categories: list[str]
    status: EditStatusOut


class EffectiveStateOut(BaseModel):
    """AI system with approved revisions folded in + the base + status.

    `ai_system` and `base` are typed as opaque dicts because the AI system
    model has 22+ fields and is re-typed in api.grc.AiSystemDetailOut;
    duplicating that here would create drift. Phase 1.5 can unify these.
    """
    model_config = _strict()

    ai_system: dict[str, Any]
    base: dict[str, Any]
    status: EditStatusOut


class FieldChangeOut(BaseModel):
    """One field's before/after in a revision."""
    model_config = ConfigDict(extra="allow")
    field: str


class RevisionOut(BaseModel):
    """One revision (edit submission) record.

    Loosely typed -- revisions carry arbitrary domain-specific fields
    (approval_status, fields_changed[], rerun_steps[], etc.) that vary by tier
    and approval state. Phase 1.5 can tighten.
    """
    model_config = ConfigDict(extra="allow")

    revision_id: str
    ai_system_id: str
    created_at: str
    created_by: str
    tier: str
    fields_changed: list[FieldChangeOut]


class RevisionsListOut(BaseModel):
    model_config = _strict()
    revisions: list[RevisionOut]
    count: int


class SubmitEditOut(BaseModel):
    """Response to POST /api/ai-systems/{id}/edit."""
    model_config = _strict()

    revision: RevisionOut
    status: EditStatusOut
    next_step: str = Field(description="pending_approval | applied")


class DecideRevisionOut(BaseModel):
    """Response to POST /api/ai-systems/revisions/{rev_id}/decide."""
    model_config = _strict()

    revision: RevisionOut
    status: EditStatusOut


# ---------- read endpoints -------------------------------------------------

@router.get(
    "/{system_id}/edit-info",
    response_model=EditInfoOut,
    operation_id="ai_systems_edit_info",
)
async def get_edit_info(system_id: str) -> EditInfoOut:
    if _base_dict(system_id) is None:
        raise HTTPException(status_code=404, detail=f"Unknown AI system: {system_id}")
    return EditInfoOut(
        ai_system_id=system_id,
        field_tiers=ase.field_tiers(),
        rerun_matrix={f: list(steps) for f, steps in ase.RERUN_MATRIX.items()},
        approval_roles_by_level={k: list(v) for k, v in ase.APPROVAL_ROLES_BY_LEVEL.items()},
        valid_change_categories=list(ase.VALID_CHANGE_CATEGORIES),
        status=EditStatusOut(**ase.status_for_system(system_id)),
    )


@router.get(
    "/{system_id}/effective",
    response_model=EffectiveStateOut,
    operation_id="ai_systems_effective_get",
)
async def get_effective(system_id: str) -> EffectiveStateOut:
    base = _base_dict(system_id)
    if base is None:
        raise HTTPException(status_code=404, detail=f"Unknown AI system: {system_id}")
    return EffectiveStateOut(
        ai_system=ase.effective_state(system_id, base),
        base=base,
        status=EditStatusOut(**ase.status_for_system(system_id)),
    )


@router.get(
    "/{system_id}/revisions",
    response_model=RevisionsListOut,
    operation_id="ai_systems_revisions_list",
)
async def list_revisions(system_id: str) -> RevisionsListOut:
    if _base_dict(system_id) is None:
        raise HTTPException(status_code=404, detail=f"Unknown AI system: {system_id}")
    revs = ase.revisions_for_system(system_id)
    return RevisionsListOut(
        revisions=[RevisionOut(**r) for r in reversed(revs)],
        count=len(revs),
    )


@router.get(
    "/revisions/pending",
    response_model=RevisionsListOut,
    operation_id="ai_systems_revisions_pending",
)
async def list_pending_revisions() -> RevisionsListOut:
    """All revisions in approval_status='pending' across every AI system.

    Consumer: CISO Console Revisions Queue (G-1, S65). Newest-first. One
    request renders the inbox; the alternative is the SPA fanning
    `GET /edit-info` across every system — O(N) round-trips for an N-system
    org, which scales badly.

    Returns `RevisionsListOut` so the SPA can reuse the same row type as
    `/{system_id}/revisions`. Status filtering is server-side (the domain
    helper walks the revision store once); no `?status=` querystring because
    "pending" is the only useful filter for this view.
    """
    revs = ase.pending_revisions_across_systems()
    return RevisionsListOut(
        revisions=[RevisionOut(**r) for r in revs],
        count=len(revs),
    )


@router.get(
    "/revisions/{revision_id}",
    response_model=RevisionOut,
    operation_id="ai_systems_revision_get",
)
async def get_revision(revision_id: str) -> RevisionOut:
    rev = ase.get_revision(revision_id)
    if rev is None:
        raise HTTPException(status_code=404, detail=f"Unknown revision: {revision_id}")
    return RevisionOut(**rev)


# ---------- write endpoints ------------------------------------------------

@router.post(
    "/{system_id}/edit",
    response_model=SubmitEditOut,
    operation_id="ai_systems_edit_submit",
)
async def submit_edit(
    system_id: str, payload: EditPayload, request: Request,
) -> SubmitEditOut:
    base = _base_dict(system_id)
    if base is None:
        raise HTTPException(status_code=404, detail=f"Unknown AI system: {system_id}")

    risk_level = str(base.get("inherent_risk") or "MEDIUM").upper()
    user = _current_user(request)

    rev, errors = ase.apply_edit(
        ai_system_id=system_id,
        base_state=base,
        proposed_changes=payload.changes,
        change_reason=payload.change_reason,
        change_category=payload.change_category,
        author=user,
        risk_level=risk_level,
    )
    if rev is None:
        raise HTTPException(status_code=400, detail={"errors": errors})

    return SubmitEditOut(
        revision=RevisionOut(**rev),
        status=EditStatusOut(**ase.status_for_system(system_id)),
        next_step=(
            "pending_approval" if rev.get("approval_status") == "pending" else "applied"
        ),
    )


@router.post(
    "/revisions/{revision_id}/decide",
    response_model=DecideRevisionOut,
    operation_id="ai_systems_revision_decide",
    responses={
        409: {"model": ConflictDetail, "description": "Decision rejected by state transition or policy."},
    },
)
async def decide_revision(
    revision_id: str, payload: DecidePayload, request: Request,
) -> DecideRevisionOut:
    """Approve / reject / override a revision.

    On state-transition or policy rejection returns 409 with ConflictDetail
    carrying the structured reason (required by CISO Console for audit-artifact
    rendering per audit doc §1.2).
    """
    user = _current_user(request)
    role = payload.role or _user_role(user)

    updated, errors = ase.decide(
        revision_id=revision_id,
        decision=payload.decision,
        user=user,
        role=role,
        note=payload.note,
    )
    if updated is None:
        raise HTTPException(
            status_code=409,
            detail=ConflictDetail(
                reason="; ".join(errors) if errors else "Decision rejected",
                conflict_type="STATE_TRANSITION",
                existing_id=revision_id,
            ).model_dump(),
        )

    return DecideRevisionOut(
        revision=RevisionOut(**updated),
        status=EditStatusOut(**ase.status_for_system(updated["ai_system_id"])),
    )


# ---------- runtime-flag attestation (ADR-004) -----------------------------

@router.patch(
    "/{system_id}/runtime-flags",
    response_model=RuntimeFlagsOut,
    operation_id="ai_systems_runtime_flags_patch",
)
async def patch_runtime_flags(
    system_id: str,
    payload: RuntimeFlagsPatchPayload,
    request: Request,
    _role: None = Depends(require_role("ciso", "tprm-analyst")),
) -> RuntimeFlagsOut:
    """Attest the runtime safety flags for an AI system (ADR-004 Option B).

    The two boolean flags are runtime safety controls consumed by the
    ``vendor-risk-int`` rego policy. They are NOT defaultable and NOT
    inferrable: an operator with the ``ciso`` or ``tprm-analyst`` role
    must explicitly attest. The dispatcher reads the persisted attestation
    server-side at chain time and injects the values into the policy
    engine's ``input_data`` — a fabricated request body cannot bypass this.

    TTL semantics: the attestation expires after ``RUNTIME_FLAG_TTL_SECONDS``
    (default 24h). After expiry the dispatcher reads None and the next
    INT run DENIES at ``policy_gate`` until re-attested. This is the
    SOP-Phase-8 deny-on-expiry drill.

    Two persistence writes happen on success:
      1. Append to ``data/system_runtime_flags.jsonl`` (the overlay the
         repository fold reads).
      2. Append a chained ``RUNTIME_FLAGS_ATTESTED`` event via the audit
         chain (independent of any agent run).

    If the audit-chain write fails, the endpoint returns 500 and the
    attestation is NOT considered persisted (the overlay row exists but
    the read path will replay it on retry — idempotent enough for
    operator workflow).

    Returns the persisted attestation block and the TTL window applied.
    """
    if _base_dict(system_id) is None:
        raise HTTPException(status_code=404, detail=f"Unknown AI system: {system_id}")

    attested_by = _current_user(request)
    if attested_by == "system":
        # _current_user returns "system" when no session cookie / SESSION_SECRET
        # is present. In production with AUTH_ENABLED=true the role gate above
        # would have already 401'd; this is a defense-in-depth check for the
        # dev path where AUTH_ENABLED=false bypasses require_role.
        raise HTTPException(
            status_code=401,
            detail="runtime_flags attestation requires an authenticated session",
        )

    now = datetime.now(timezone.utc)
    ttl = _runtime_flag_ttl_seconds()
    flags = RuntimeFlags(
        dlp_completed=payload.dlp_completed,
        network_egress_lock_engaged=payload.network_egress_lock_engaged,
        attested_by=attested_by,
        attested_at=now,
        justification=payload.justification,
        expires_at=now + timedelta(seconds=ttl),
    )

    try:
        from storage import patch_system_runtime_flags
        patch_system_runtime_flags(system_id, flags)
    except RuntimeError as exc:
        # Audit-chain write failed. Surface as 500 — the operator should
        # retry rather than have the platform silently accept an
        # attestation without an audit row.
        raise HTTPException(status_code=500, detail=str(exc))

    return RuntimeFlagsOut(
        ai_system_id=system_id,
        runtime_flags=flags,
        ttl_seconds=ttl,
    )
