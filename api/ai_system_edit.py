"""AI System Edit endpoints.

GET  /api/ai-systems/{id}/edit-info          field tiers + current pending status
GET  /api/ai-systems/{id}/effective          AISystem with approved revisions folded in
GET  /api/ai-systems/{id}/revisions          full revision history
GET  /api/ai-systems/revisions/{rev_id}      single revision detail
POST /api/ai-systems/{id}/edit               submit an edit (auto-detects tier)
POST /api/ai-systems/revisions/{rev_id}/decide   approve | reject | override
"""

from __future__ import annotations

import os
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from itsdangerous import BadSignature, URLSafeTimedSerializer
from pydantic import BaseModel, Field

from domain import ai_system_edit as ase
from domain import repository as repo


router = APIRouter(prefix="/api/ai-systems", tags=["ai-system-edit"])


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


# ---------- payloads -------------------------------------------------------

class EditPayload(BaseModel):
    changes: dict[str, Any] = Field(default_factory=dict)
    change_reason: str = ""
    change_category: str = "Other"


class DecidePayload(BaseModel):
    decision: str       # APPROVE | REJECT | OVERRIDE
    note: str = ""
    role: Optional[str] = None  # optional override; otherwise derived from session user


# ---------- read endpoints -------------------------------------------------

@router.get("/{system_id}/edit-info")
async def get_edit_info(system_id: str) -> dict:
    if _base_dict(system_id) is None:
        raise HTTPException(status_code=404, detail=f"Unknown AI system: {system_id}")
    return {
        "ai_system_id": system_id,
        "field_tiers": ase.field_tiers(),
        "rerun_matrix": {f: list(steps) for f, steps in ase.RERUN_MATRIX.items()},
        "approval_roles_by_level": {k: list(v) for k, v in ase.APPROVAL_ROLES_BY_LEVEL.items()},
        "valid_change_categories": list(ase.VALID_CHANGE_CATEGORIES),
        "status": ase.status_for_system(system_id),
    }


@router.get("/{system_id}/effective")
async def get_effective(system_id: str) -> dict:
    base = _base_dict(system_id)
    if base is None:
        raise HTTPException(status_code=404, detail=f"Unknown AI system: {system_id}")
    return {
        "ai_system": ase.effective_state(system_id, base),
        "base": base,
        "status": ase.status_for_system(system_id),
    }


@router.get("/{system_id}/revisions")
async def list_revisions(system_id: str) -> dict:
    if _base_dict(system_id) is None:
        raise HTTPException(status_code=404, detail=f"Unknown AI system: {system_id}")
    revs = ase.revisions_for_system(system_id)
    return {"revisions": list(reversed(revs)), "count": len(revs)}


@router.get("/revisions/{revision_id}")
async def get_revision(revision_id: str) -> dict:
    rev = ase.get_revision(revision_id)
    if rev is None:
        raise HTTPException(status_code=404, detail=f"Unknown revision: {revision_id}")
    return rev


# ---------- write endpoints ------------------------------------------------

@router.post("/{system_id}/edit")
async def submit_edit(system_id: str, payload: EditPayload, request: Request) -> dict:
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

    return {
        "revision": rev,
        "status": ase.status_for_system(system_id),
        "next_step": (
            "pending_approval" if rev.get("approval_status") == "pending"
            else "applied"
        ),
    }


@router.post("/revisions/{revision_id}/decide")
async def decide_revision(revision_id: str, payload: DecidePayload, request: Request) -> dict:
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
        raise HTTPException(status_code=400, detail={"errors": errors})

    return {
        "revision": updated,
        "status": ase.status_for_system(updated["ai_system_id"]),
    }
