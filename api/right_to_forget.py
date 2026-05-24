"""FastAPI router for Right-to-Forget (RTF) cascade endpoints.

Exposes:
  POST /api/right-to-forget           -- initiate a cascade (sync inline)
  POST /api/right-to-forget/{id}/approve -- approval stub (auto-approved for MVP)
  GET  /api/right-to-forget/{id}      -- fetch cascade result
  GET  /api/right-to-forget           -- list all cascades

Domain logic lives entirely in domain.right_to_forget.  This layer handles
HTTP status mapping, Pydantic request validation, and asyncio.to_thread wrapping.

Session 08 -- AI Assurance Platform.
Session 13: typed responses per audit doc §3.2. The `governance` field is
declared on every response per §1.6 but populated as None for now
(plumbing chain_hash through is Phase 1.5 per audit §9).
"""
from __future__ import annotations

import asyncio
import logging
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from api._models import GovernanceMetadata

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/right-to-forget", tags=["right-to-forget"])


def _strict() -> ConfigDict:
    return ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class PurgeStepOut(BaseModel):
    """Per-store result of one cascade purge step."""
    model_config = _strict()

    store: str
    items_removed: int
    sha256_digest_after: str
    error: str | None = None


class CascadeResultOut(BaseModel):
    """Full result of a Right-to-Forget cascade.

    `governance` carries chain_hash + trace_id when populated (Phase 1.5).
    The per-step sha256_digest_after fields already provide tamper-evident
    digests of each store post-purge; chain_hash is the audit-log event hash.
    """
    model_config = _strict()

    cascade_id: str
    subject_id: str
    status: str = Field(description="COMPLETED | PARTIAL_FAILURE | ALREADY_COMPLETED")
    steps: dict[str, PurgeStepOut]
    started_at: str
    completed_at: str
    governance: GovernanceMetadata | None = None


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
# Lazy domain import helpers
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
# Status -> HTTP status code mapping
# ---------------------------------------------------------------------------

_STATUS_CODE: dict[str, int] = {
    "COMPLETED": 201,
    "PARTIAL_FAILURE": 207,
    "ALREADY_COMPLETED": 200,
}


# ---------------------------------------------------------------------------
# Endpoints
#
# NOTE on response_model: initiate_cascade returns a JSONResponse with a
# custom status code (201/207/200) -- FastAPI's response_model validation
# does not apply to JSONResponse. Declare response_model anyway so the
# OpenAPI spec advertises the shape; clients consume the same dict.
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=CascadeResultOut,
    operation_id="right_to_forget_initiate",
    responses={
        201: {"model": CascadeResultOut, "description": "Cascade completed."},
        207: {"model": CascadeResultOut, "description": "Partial failure (some stores errored)."},
        200: {"model": CascadeResultOut, "description": "Already completed (idempotent re-request)."},
    },
)
async def initiate_cascade(body: CascadeRequest) -> CascadeResultOut:
    """Initiate a Right-to-Forget cascade for a subject."""
    cascade_id = str(uuid.uuid4())
    logger.info(
        "initiate_cascade: subject_id=%s cascade_id=%s reason_len=%d",
        body.subject_id, cascade_id, len(body.reason),
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
            body.subject_id, cascade_id, str(exc)[:300],
        )
        raise HTTPException(status_code=500, detail=f"Cascade failed: {exc!s}")

    status_code = _STATUS_CODE.get(result.status, 200)
    logger.info(
        "initiate_cascade: cascade_id=%s status=%s http=%d",
        cascade_id, result.status, status_code,
    )

    return JSONResponse(
        status_code=status_code,
        content=result.model_dump(mode="json"),
    )


@router.post(
    "/{cascade_id}/approve",
    response_model=CascadeResultOut,
    operation_id="right_to_forget_approve",
)
async def approve_cascade(cascade_id: uuid.UUID) -> CascadeResultOut:
    """Approval stub for the RTF workflow. Auto-approved in MVP."""
    cascade_id = str(cascade_id)  # type: ignore[assignment]
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
            cascade_id, str(exc)[:200],
        )

    logger.info("approve_cascade: cascade_id=%s emitted RTF_APPROVED", cascade_id)
    return CascadeResultOut(**result.model_dump(mode="json"))


@router.get(
    "/{cascade_id}",
    response_model=CascadeResultOut,
    operation_id="right_to_forget_get",
)
async def get_cascade(cascade_id: uuid.UUID) -> CascadeResultOut:
    """Fetch a single cascade result by cascade_id."""
    cascade_id = str(cascade_id)  # type: ignore[assignment]
    logger.info("get_cascade: cascade_id=%s", cascade_id)
    rtf = _rtf()

    result = await asyncio.to_thread(rtf.get_cascade, cascade_id)
    if result is None:
        logger.error("get_cascade: cascade_id=%s not found", cascade_id)
        raise HTTPException(status_code=404, detail=f"Cascade {cascade_id!r} not found")

    logger.info("get_cascade: cascade_id=%s status=%s", cascade_id, result.status)
    return CascadeResultOut(**result.model_dump(mode="json"))


class CascadeListOut(BaseModel):
    """List of cascade results (oldest-first)."""
    model_config = _strict()
    cascades: list[CascadeResultOut]


@router.get(
    "",
    response_model=CascadeListOut,
    operation_id="right_to_forget_list",
)
async def list_cascades() -> CascadeListOut:
    """List all cascade results ordered oldest-first.

    Wrapped in a CascadeListOut envelope (per audit §1.1: no bare-list responses).
    The legacy V1 contract returned a bare list; SPAs / SDK target the envelope.
    """
    logger.info("list_cascades: fetching all cascades")
    rtf = _rtf()

    try:
        results = await asyncio.to_thread(rtf.list_cascades)
    except Exception as exc:
        logger.error("list_cascades failed: error=%s", str(exc)[:200])
        raise HTTPException(status_code=500, detail="Failed to list cascades")

    logger.info("list_cascades: returned %d cascades", len(results))
    return CascadeListOut(
        cascades=[CascadeResultOut(**r.model_dump(mode="json")) for r in results],
    )
