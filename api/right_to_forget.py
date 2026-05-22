"""FastAPI router for Right-to-Forget (RTF) cascade endpoints.

Exposes:
  POST /api/right-to-forget           — initiate a cascade (sync inline)
  POST /api/right-to-forget/{id}/approve — approval stub (auto-approved for MVP)
  GET  /api/right-to-forget/{id}      — fetch cascade result
  GET  /api/right-to-forget           — list all cascades

Domain logic lives entirely in domain.right_to_forget.  This layer handles
HTTP status mapping, Pydantic request validation, and asyncio.to_thread wrapping.

Session 08 — AI Assurance Platform.
"""
from __future__ import annotations

import asyncio
import logging
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, field_validator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/right-to-forget", tags=["right-to-forget"])

# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class CascadeRequest(BaseModel):
    """Body for POST /api/right-to-forget."""

    model_config = ConfigDict(str_strip_whitespace=True)

    subject_id: str
    reason: str

    @field_validator("subject_id")
    @classmethod
    def subject_id_valid(cls, v: str) -> str:
        """Reject blank or oversized subject_id, restrict to safe charset."""
        import re as _re
        if not v:
            raise ValueError("subject_id must not be empty")
        if len(v) > 256:
            raise ValueError("subject_id must be <= 256 characters")
        if not _re.fullmatch(r"[A-Za-z0-9._@\-]+", v):
            raise ValueError(
                "subject_id may contain only letters, digits, '.', '_', '@', '-'"
            )
        return v

    @field_validator("reason")
    @classmethod
    def reason_valid(cls, v: str) -> str:
        """Reject blank or oversized reason."""
        if not v:
            raise ValueError("reason must not be empty")
        if len(v) > 1024:
            raise ValueError("reason must be <= 1024 characters")
        return v


# ---------------------------------------------------------------------------
# Lazy domain import helper
# ---------------------------------------------------------------------------


def _rtf():
    """Lazy import of domain.right_to_forget; raises 503 if unavailable."""
    try:
        import domain.right_to_forget as m  # type: ignore[import]
        return m
    except ModuleNotFoundError as exc:
        logger.error("domain.right_to_forget not available: %s", exc)
        raise HTTPException(status_code=503, detail="Right-to-forget domain not available")


def _repository():
    """Lazy import of domain.repository; raises 503 if unavailable."""
    try:
        import domain.repository as r  # type: ignore[import]
        return r
    except ModuleNotFoundError as exc:
        logger.error("domain.repository not available: %s", exc)
        raise HTTPException(status_code=503, detail="Repository not available")


# ---------------------------------------------------------------------------
# Status → HTTP status code mapping
# ---------------------------------------------------------------------------

_STATUS_CODE: dict[str, int] = {
    "COMPLETED": 201,
    "PARTIAL_FAILURE": 207,
    "ALREADY_COMPLETED": 200,
}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("")
async def initiate_cascade(body: CascadeRequest) -> dict:
    """Initiate a Right-to-Forget cascade for a subject.

    Runs the purge cascade synchronously within the request (Decision 1 from
    SESSION-08 spec: sync inline, saga deferred to Day 10).

    Returns HTTP 201 on COMPLETED, 207 on PARTIAL_FAILURE, 200 on ALREADY_COMPLETED.
    Body is the serialized CascadeResult.
    """
    cascade_id = str(uuid.uuid4())
    logger.info(
        "initiate_cascade: subject_id=%s cascade_id=%s reason_len=%d",
        body.subject_id,
        cascade_id,
        len(body.reason),
    )

    rtf = _rtf()
    try:
        result = await asyncio.to_thread(
            rtf.cascade,
            subject_id=body.subject_id,
            reason=body.reason,
            cascade_id=cascade_id,
        )
    except Exception as exc:
        logger.error(
            "initiate_cascade failed: subject_id=%s cascade_id=%s error=%s",
            body.subject_id,
            cascade_id,
            str(exc)[:300],
        )
        raise HTTPException(status_code=500, detail=f"Cascade failed: {exc!s}")

    status_code = _STATUS_CODE.get(result.status, 200)
    logger.info(
        "initiate_cascade: cascade_id=%s status=%s http=%d",
        cascade_id,
        result.status,
        status_code,
    )

    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=status_code,
        content=result.model_dump(mode="json"),
    )


@router.post("/{cascade_id}/approve")
async def approve_cascade(cascade_id: uuid.UUID) -> dict:
    cascade_id = str(cascade_id)  # type: ignore[assignment]  # normalize for downstream str compares
    """Approval stub for the RTF workflow.

    For MVP, requests are auto-approved.  This endpoint exists for the UI
    approval queue and emits an RTF_APPROVED event via domain.repository.
    """
    logger.info("approve_cascade: cascade_id=%s", cascade_id)

    repo = _repository()
    rtf = _rtf()

    result = await asyncio.to_thread(rtf.get_cascade, cascade_id)
    if result is None:
        logger.error("approve_cascade: cascade_id=%s not found", cascade_id)
        raise HTTPException(status_code=404, detail=f"Cascade {cascade_id!r} not found")

    try:
        await asyncio.to_thread(
            repo.append_agent_event,
            "RTF_APPROVED",
            {
                "cascade_id": cascade_id,
                "subject_id": result.subject_id,
                "auto_approved": True,
            },
        )
    except Exception as exc:
        logger.error(
            "approve_cascade: event write failed: cascade_id=%s error=%s",
            cascade_id,
            str(exc)[:200],
        )
        # Non-fatal — approval event is informational; do not 500 the caller

    logger.info("approve_cascade: cascade_id=%s emitted RTF_APPROVED", cascade_id)
    return result.model_dump(mode="json")


@router.get("/{cascade_id}")
async def get_cascade(cascade_id: uuid.UUID) -> dict:
    cascade_id = str(cascade_id)  # type: ignore[assignment]  # normalize for downstream str compares
    """Fetch a single cascade result by cascade_id.

    Returns 404 if the cascade is not found in the event log.
    """
    logger.info("get_cascade: cascade_id=%s", cascade_id)
    rtf = _rtf()

    result = await asyncio.to_thread(rtf.get_cascade, cascade_id)
    if result is None:
        logger.error("get_cascade: cascade_id=%s not found", cascade_id)
        raise HTTPException(status_code=404, detail=f"Cascade {cascade_id!r} not found")

    logger.info("get_cascade: cascade_id=%s status=%s", cascade_id, result.status)
    return result.model_dump(mode="json")


@router.get("")
async def list_cascades() -> list[dict]:
    """List all cascade results ordered oldest-first.

    Returns an empty list if no cascades have been run.
    """
    logger.info("list_cascades: fetching all cascades")
    rtf = _rtf()

    try:
        results = await asyncio.to_thread(rtf.list_cascades)
    except Exception as exc:
        logger.error("list_cascades failed: error=%s", str(exc)[:200])
        raise HTTPException(status_code=500, detail="Failed to list cascades")

    logger.info("list_cascades: returned %d cascades", len(results))
    return [r.model_dump(mode="json") for r in results]
