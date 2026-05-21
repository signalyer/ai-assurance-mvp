"""Assessment Engine API."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum

from fastapi import APIRouter, HTTPException

from domain.assessment_engine import run_assessment


router = APIRouter(prefix="/api/grc/assessment", tags=["grc-assessment"])


def _serialize(obj):
    """Recursively convert dataclasses/enums into JSON-safe primitives."""
    if is_dataclass(obj):
        return {k: _serialize(v) for k, v in asdict(obj).items()}
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, (list, tuple)):
        return [_serialize(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    return obj


@router.post("/run/{ai_system_id}")
async def run(ai_system_id: str) -> dict:
    """Run a full assessment against an AI system and return the report."""
    try:
        report = run_assessment(ai_system_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _serialize(report)


@router.get("/{ai_system_id}")
async def get(ai_system_id: str) -> dict:
    """Convenience GET — same as POST /run."""
    return await run(ai_system_id)
