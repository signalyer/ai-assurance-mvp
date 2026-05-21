"""FastAPI router for Agent Memory and RAG endpoints.

Exposes episodic memory read/write, semantic recall, context assembly,
and combined memory+RAG stats. Delegates all business logic to
domain.agent_memory and domain.rag_engine — no logic lives here.

Session 04 — AI Assurance Platform.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, field_validator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/memory", tags=["memory"])

# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

VALID_OUTCOMES: frozenset[str] = frozenset({"success", "failure", "review"})


class WriteEpisodeRequest(BaseModel):
    """Body for POST /api/memory/episodes."""

    model_config = ConfigDict(str_strip_whitespace=True)

    workload_id: str
    prompt: str
    response: str
    outcome: Literal["success", "failure", "review"]
    metadata: dict[str, object] = {}
    ttl_seconds: int | None = None

    @field_validator("workload_id")
    @classmethod
    def workload_id_nonempty(cls, v: str) -> str:
        """Reject blank workload_id at the boundary."""
        if not v:
            raise ValueError("workload_id must not be empty")
        return v


class WriteEpisodeResponse(BaseModel):
    """Response from POST /api/memory/episodes."""

    model_config = ConfigDict()

    episode_id: str


class EpisodeItem(BaseModel):
    """Single episode row returned in list responses."""

    model_config = ConfigDict()

    episode_id: str
    workload_id: str
    timestamp: str
    outcome: str
    prompt_preview: str
    response_preview: str
    trace_id: str | None = None
    metadata: dict[str, object] = {}


class EpisodesResponse(BaseModel):
    """Response from GET /api/memory/episodes."""

    model_config = ConfigDict()

    workload_id: str
    episodes: list[EpisodeItem]
    total: int


class RecallItem(BaseModel):
    """Single result from semantic recall."""

    model_config = ConfigDict()

    episode_id: str
    workload_id: str
    timestamp: str
    prompt_preview: str
    response_preview: str
    outcome: str
    relevance_score: float
    metadata: dict[str, object] = {}


class RecallResponse(BaseModel):
    """Response from GET /api/memory/recall."""

    model_config = ConfigDict()

    workload_id: str
    query: str
    results: list[RecallItem]


class StatsResponse(BaseModel):
    """Combined memory + RAG stats from GET /api/memory/stats."""

    model_config = ConfigDict()

    memory: dict[str, object]
    rag: dict[str, object]


class ContextResponse(BaseModel):
    """Response from GET /api/memory/context."""

    model_config = ConfigDict()

    workload_id: str
    context: str
    lookback_days: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_import_memory() -> object:
    """Lazy import of domain.agent_memory to tolerate absent module during testing."""
    try:
        import domain.agent_memory as am  # type: ignore[import]
        return am
    except ModuleNotFoundError as exc:
        logger.error("domain.agent_memory not available: %s", exc)
        raise HTTPException(status_code=503, detail="Memory backend not available")


def _safe_import_rag() -> object:
    """Lazy import of domain.rag_engine to tolerate absent module during testing."""
    try:
        import domain.rag_engine as rag  # type: ignore[import]
        return rag
    except ModuleNotFoundError as exc:
        logger.error("domain.rag_engine not available: %s", exc)
        raise HTTPException(status_code=503, detail="RAG backend not available")


def _episode_row_to_item(row: dict[str, object]) -> EpisodeItem:
    """Convert a raw episode dict from domain layer into an EpisodeItem."""
    prompt = str(row.get("prompt") or "")
    response = str(row.get("response") or "")
    return EpisodeItem(
        episode_id=str(row.get("episode_id") or row.get("id") or ""),
        workload_id=str(row.get("workload_id") or ""),
        timestamp=str(row.get("timestamp") or ""),
        outcome=str(row.get("outcome") or ""),
        prompt_preview=prompt[:80],
        response_preview=response[:80],
        trace_id=str(row["trace_id"]) if row.get("trace_id") else None,
        metadata={k: v for k, v in (row.get("metadata") or {}).items()},
    )


def _recall_row_to_item(row: dict[str, object]) -> RecallItem:
    """Convert a raw recall result dict into a RecallItem."""
    prompt = str(row.get("prompt") or "")
    response = str(row.get("response") or "")
    return RecallItem(
        episode_id=str(row.get("episode_id") or row.get("id") or ""),
        workload_id=str(row.get("workload_id") or ""),
        timestamp=str(row.get("timestamp") or ""),
        prompt_preview=prompt[:80],
        response_preview=response[:80],
        outcome=str(row.get("outcome") or ""),
        relevance_score=float(row.get("relevance_score") or row.get("score") or 0.0),
        metadata={k: v for k, v in (row.get("metadata") or {}).items()},
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/episodes", response_model=WriteEpisodeResponse)
async def write_episode(body: WriteEpisodeRequest) -> WriteEpisodeResponse:
    """Write a new episodic memory entry.

    Validates workload_id and outcome at the boundary via the Pydantic model.
    Delegates persistence to domain.agent_memory.write_episode().
    """
    logger.info(
        "write_episode: workload_id=%s outcome=%s",
        body.workload_id,
        body.outcome,
    )
    am = _safe_import_memory()
    try:
        # Domain functions are sync (blocking SQLAlchemy I/O); run in thread pool
        episode_id: str = await asyncio.to_thread(
            am.write_episode,
            workload_id=body.workload_id,
            prompt=body.prompt,
            response=body.response,
            outcome=body.outcome,
            metadata=body.metadata,
            ttl_seconds=body.ttl_seconds,
        )
        logger.info("write_episode: created episode_id=%s", episode_id)
        return WriteEpisodeResponse(episode_id=episode_id)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "write_episode failed: workload_id=%s error=%s",
            body.workload_id,
            str(exc)[:200],
        )
        raise HTTPException(status_code=500, detail="Failed to write episode")


@router.get("/episodes", response_model=EpisodesResponse)
async def list_episodes(
    workload_id: str = Query(..., description="Workload identifier"),
    limit: int = Query(20, ge=1, le=200, description="Max episodes to return"),
    lookback_days: int = Query(7, ge=1, le=365, description="Days to look back"),
) -> EpisodesResponse:
    """List recent episodes for a workload.

    Calls domain.agent_memory.build_context() internally — the domain layer
    handles filtering and ordering.
    """
    logger.info(
        "list_episodes: workload_id=%s limit=%d lookback_days=%d",
        workload_id,
        limit,
        lookback_days,
    )
    if not workload_id.strip():
        raise HTTPException(status_code=422, detail="workload_id must not be empty")

    am = _safe_import_memory()
    try:
        raw: list[dict[str, object]] = await asyncio.to_thread(
            am.list_episodes,
            workload_id=workload_id,
            limit=limit,
            lookback_days=lookback_days,
        )
        items = [_episode_row_to_item(r) for r in raw]
        logger.info(
            "list_episodes: workload_id=%s returned=%d", workload_id, len(items)
        )
        return EpisodesResponse(
            workload_id=workload_id,
            episodes=items,
            total=len(items),
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "list_episodes failed: workload_id=%s error=%s",
            workload_id,
            str(exc)[:200],
        )
        raise HTTPException(status_code=500, detail="Failed to retrieve episodes")


@router.get("/recall", response_model=RecallResponse)
async def recall(
    workload_id: str = Query(..., description="Workload identifier"),
    query: str = Query(..., description="Semantic search query"),
    top_k: int = Query(5, ge=1, le=50, description="Max results to return"),
    lookback_days: int = Query(30, ge=1, le=365, description="Days to look back"),
) -> RecallResponse:
    """Semantic search over episodic memory for a workload.

    Delegates to domain.agent_memory.selective_recall().
    """
    logger.info(
        "recall: workload_id=%s top_k=%d lookback_days=%d query_len=%d",
        workload_id,
        top_k,
        lookback_days,
        len(query),
    )
    if not workload_id.strip():
        raise HTTPException(status_code=422, detail="workload_id must not be empty")
    if not query.strip():
        raise HTTPException(status_code=422, detail="query must not be empty")

    am = _safe_import_memory()
    try:
        raw: list[dict[str, object]] = await asyncio.to_thread(
            am.selective_recall,
            workload_id=workload_id,
            query=query,
            top_k=top_k,
            lookback_days=lookback_days,
        )
        items = [_recall_row_to_item(r) for r in raw]
        logger.info(
            "recall: workload_id=%s results=%d", workload_id, len(items)
        )
        return RecallResponse(
            workload_id=workload_id,
            query=query,
            results=items,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "recall failed: workload_id=%s error=%s",
            workload_id,
            str(exc)[:200],
        )
        raise HTTPException(status_code=500, detail="Semantic recall failed")


@router.get("/stats", response_model=StatsResponse)
async def get_stats() -> StatsResponse:
    """Return combined memory and RAG statistics.

    Calls domain.agent_memory.memory_stats() and domain.rag_engine.rag_stats()
    concurrently and merges the results.
    """
    logger.info("get_stats: fetching memory and rag stats")

    am = _safe_import_memory()
    rag = _safe_import_rag()

    try:
        # Sync domain functions — wrap in to_thread so gather works
        mem_result, rag_result = await asyncio.gather(
            asyncio.to_thread(am.memory_stats),
            asyncio.to_thread(rag.rag_stats),
            return_exceptions=True,
        )
    except Exception as exc:
        logger.error("get_stats: gather failed: %s", str(exc)[:200])
        raise HTTPException(status_code=500, detail="Stats fetch failed")

    mem_data: dict[str, object] = {}
    rag_data: dict[str, object] = {}

    if isinstance(mem_result, Exception):
        logger.error("get_stats: memory_stats error: %s", str(mem_result)[:200])
        mem_data = {"error": "Memory stats unavailable"}
    else:
        mem_data = dict(mem_result)  # type: ignore[arg-type]

    if isinstance(rag_result, Exception):
        logger.error("get_stats: rag_stats error: %s", str(rag_result)[:200])
        rag_data = {"error": "RAG stats unavailable"}
    else:
        rag_data = dict(rag_result)  # type: ignore[arg-type]

    logger.info("get_stats: complete")
    return StatsResponse(memory=mem_data, rag=rag_data)


@router.get("/context", response_model=ContextResponse)
async def get_context(
    workload_id: str = Query(..., description="Workload identifier"),
    lookback_days: int = Query(7, ge=1, le=365, description="Days to look back"),
    include_rag: bool = Query(True, description="Include RAG tier in context"),
    include_procedural: bool = Query(True, description="Include procedural memory tier"),
    max_episodes: int = Query(10, ge=1, le=50, description="Max episodes to include"),
) -> ContextResponse:
    """Assemble multi-tier context for a workload.

    Delegates to domain.agent_memory.build_context() which handles T1–T4 tiers.
    Returns the assembled context string ready for LLM injection.
    """
    logger.info(
        "get_context: workload_id=%s lookback_days=%d include_rag=%s include_procedural=%s",
        workload_id,
        lookback_days,
        include_rag,
        include_procedural,
    )
    if not workload_id.strip():
        raise HTTPException(status_code=422, detail="workload_id must not be empty")

    am = _safe_import_memory()
    try:
        context_str: str = await asyncio.to_thread(
            am.build_context,
            workload_id=workload_id,
            lookback_days=lookback_days,
            include_rag=include_rag,
            include_procedural=include_procedural,
            max_episodes=max_episodes,
        )
        logger.info(
            "get_context: workload_id=%s context_chars=%d",
            workload_id,
            len(context_str),
        )
        return ContextResponse(
            workload_id=workload_id,
            context=context_str,
            lookback_days=lookback_days,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "get_context failed: workload_id=%s error=%s",
            workload_id,
            str(exc)[:200],
        )
        raise HTTPException(status_code=500, detail="Context assembly failed")
