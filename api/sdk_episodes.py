"""SDK-facing endpoint for Tier-2 episode persistence.

Lets customer agents (running outside the engine VPC) write episodes to
Postgres via signed HTTP rather than importing ``domain.agent_memory``
directly. Closes the architectural gap surfaced in S70b: the agent box
should not ship sqlalchemy + psycopg2 + a direct Postgres connection
just to record one row per LLM call.

Auth: HMACAuthMiddleware guards everything under ``/api/sdk/`` by prefix
(see middleware/hmac_auth.py). No SessionAuth — agents have no cookies.

Storage rule (CLAUDE.md): we delegate to
``domain.agent_memory.write_episode()`` which proxies through the
providers registry. The engine's configured MEMORY backend (postgres in
prod, jsonl in dev) decides where the row lands; this endpoint stays
backend-agnostic.

Security:
  - Prompt/response MUST already be scrubbed by the caller (same contract
    as the direct write_episode call). The SDK's @scrub_pii decorator
    already enforces this on the agent side.
  - When SCRUBBER_ENABLED=true at the engine, metadata MUST contain a
    non-empty vault_id — agent_memory will raise ValueError otherwise,
    which we surface as 400.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from domain.agent_memory import write_episode

logger = logging.getLogger(__name__)

# Prefix is /api/sdk so HMACAuthMiddleware (guards /api/sdk/) picks it up.
router = APIRouter(prefix="/api/sdk", tags=["sdk-episodes"])


_VALID_OUTCOMES = frozenset({"success", "failure", "review"})


class EpisodeWriteRequest(BaseModel):
    """Body of ``POST /api/sdk/episodes``.

    Mirrors ``domain.agent_memory.write_episode`` parameters 1:1. ``metadata``
    is a free-form dict per the underlying schema; ``vault_id`` / ``trace_id``
    / ``eval_scores`` / ``guardrail_result`` are hot-extracted into dedicated
    columns by ``_write_episode_impl`` — the rest stays in the metadata JSONB.
    """

    workload_id: str = Field(..., min_length=1, max_length=128)
    prompt: str = Field(..., min_length=1)
    response: str = Field(..., min_length=1)
    outcome: str = Field(..., description="One of: success | failure | review")
    metadata: Optional[dict[str, Any]] = None
    ttl_seconds: Optional[int] = Field(default=None, ge=0)

    model_config = ConfigDict(extra="forbid")


class EpisodeWriteResponse(BaseModel):
    """Body of a successful ``POST /api/sdk/episodes``."""

    episode_id: str

    model_config = ConfigDict(extra="forbid")


@router.post(
    "/episodes",
    response_model=EpisodeWriteResponse,
    operation_id="sdk_episodes_write",
    status_code=201,
)
async def sdk_write_episode(payload: EpisodeWriteRequest) -> EpisodeWriteResponse:
    """Persist one scrubbed episode on behalf of an SDK caller.

    Returns 201 + episode_id on success, 400 on validation/vault errors,
    500 on DB failure. Auth is enforced upstream by HMACAuthMiddleware.
    """
    if payload.outcome not in _VALID_OUTCOMES:
        raise HTTPException(
            status_code=400,
            detail=f"outcome must be one of {sorted(_VALID_OUTCOMES)}",
        )

    try:
        episode_id = await asyncio.to_thread(
            write_episode,
            workload_id=payload.workload_id,
            prompt=payload.prompt,
            response=payload.response,
            outcome=payload.outcome,
            metadata=payload.metadata or {},
            ttl_seconds=payload.ttl_seconds,
        )
    except ValueError as exc:
        # Surfaced when SCRUBBER_ENABLED=true and metadata lacks vault_id.
        logger.warning("sdk_write_episode: validation failed: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        # Per [[bare-except-hides-broken-integrations]]: log full provenance.
        logger.error(
            "sdk_write_episode: backend failure %s.%s: %s",
            type(exc).__module__,
            type(exc).__name__,
            exc,
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="episode_write_failed") from exc

    logger.info(
        "sdk_write_episode: wrote episode_id=%s workload_id=%s outcome=%s",
        episode_id,
        payload.workload_id,
        payload.outcome,
    )
    return EpisodeWriteResponse(episode_id=episode_id)
