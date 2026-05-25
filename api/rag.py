"""FastAPI router for RAG corpus management.

Thin HTTP layer over domain.rag_engine. All business logic — PII scrubbing,
fail-closed semantics, hybrid scoring — lives in the engine. This router
validates input at the Pydantic boundary, hands off to the engine via
asyncio.to_thread (engine is sync httpx + OpenAI SDK), and shapes the
response.

Session 18 — V2 Phase 2 Week 3 close-out. First mutation surface on
/api/rag/*. Engine layer shipped in Session 04 but never had an HTTP router
mounted; this file backfills that gap. See docs/plans/SESSION-18-week3-closeout.md.

Endpoints:
  GET    /api/rag/stats              — index size, doc count, rejections
  POST   /api/rag/search             — hybrid (BM25+vector) corpus search
  POST   /api/rag/documents          — index a document (PII-scrubbed by default)
  DELETE /api/rag/documents/{doc_id} — remove a document from the index

Endpoints intentionally NOT exposed:
  purge_chunks() — internal to RTF cascade, never directly callable by SPA.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel, ConfigDict, Field, field_validator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/rag", tags=["rag"])

# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class RagStatsResponse(BaseModel):
    """Response from GET /api/rag/stats. Mirrors domain.rag_engine.RagStats."""

    model_config = ConfigDict()

    index_size: int
    doc_count: int
    last_updated: Optional[str] = None
    embedding_model: str
    rejections_total: int
    rag_enabled: bool


class SearchRequest(BaseModel):
    """Body for POST /api/rag/search."""

    model_config = ConfigDict(str_strip_whitespace=True)

    query: str = Field(..., min_length=1, max_length=2048)
    top_k: int = Field(5, ge=1, le=50)
    hybrid: bool = True

    @field_validator("query")
    @classmethod
    def query_nonblank(cls, v: str) -> str:
        """Reject all-whitespace queries at the boundary."""
        if not v or not v.strip():
            raise ValueError("query must not be empty or whitespace")
        return v


class SearchResultItem(BaseModel):
    """Single result returned from /api/rag/search."""

    model_config = ConfigDict()

    id: str
    content: str
    score: float
    metadata: dict[str, Any]
    bm25_score: float
    semantic_score: float


class SearchResponse(BaseModel):
    """Response from POST /api/rag/search."""

    model_config = ConfigDict()

    query: str
    results: list[SearchResultItem]
    total: int


class IndexDocumentRequest(BaseModel):
    """Body for POST /api/rag/documents."""

    model_config = ConfigDict(str_strip_whitespace=True)

    doc_id: str = Field(..., min_length=1, max_length=256)
    content: str = Field(..., min_length=1, max_length=100_000)
    metadata: dict[str, Any] = Field(default_factory=dict)
    scrub: bool = True

    @field_validator("doc_id")
    @classmethod
    def doc_id_safe(cls, v: str) -> str:
        """Mirror the Azure Search key constraint — id chars are limited."""
        if not v or not v.strip():
            raise ValueError("doc_id must not be empty")
        # Azure Search keys: letters, digits, dash, underscore, equals.
        allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_=")
        if any(c not in allowed for c in v):
            raise ValueError(
                "doc_id may contain only letters, digits, '-', '_', '='"
            )
        return v


class IndexDocumentResponse(BaseModel):
    """Response from POST /api/rag/documents."""

    model_config = ConfigDict()

    doc_id: str
    indexed: bool
    reason: Optional[str] = None  # populated when indexed=False (e.g. PII reject)


class DeleteDocumentResponse(BaseModel):
    """Response from DELETE /api/rag/documents/{doc_id}."""

    model_config = ConfigDict()

    doc_id: str
    deleted: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_import_rag() -> Any:
    """Lazy import of domain.rag_engine.

    Matches api/memory.py pattern — keeps router importable even when the
    engine module's env-var preconditions can't be met during unit testing.
    """
    try:
        import domain.rag_engine as rag  # type: ignore[import]
        return rag
    except ModuleNotFoundError as exc:
        logger.error("domain.rag_engine not available: %s", exc)
        raise HTTPException(status_code=503, detail="RAG backend not available")


def _rag_enabled_flag() -> bool:
    """Surface the engine's _RAG_ENABLED flag for the stats response."""
    try:
        rag = _safe_import_rag()
        return bool(getattr(rag, "_RAG_ENABLED", False))
    except HTTPException:
        return False


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/stats", response_model=RagStatsResponse, operation_id="rag_get_stats")
async def get_stats() -> RagStatsResponse:
    """Return statistics about the RAG corpus.

    When RAG is disabled (no Azure creds or RAG_ENABLED=false), returns zeroed
    counters with rag_enabled=false — never raises. This is the same fail-soft
    contract domain.rag_engine.rag_stats() honors.
    """
    logger.info("get_stats: entry")
    rag = _safe_import_rag()
    try:
        raw: dict[str, Any] = await asyncio.to_thread(rag.rag_stats)
        result = RagStatsResponse(
            index_size=int(raw.get("index_size") or 0),
            doc_count=int(raw.get("doc_count") or 0),
            last_updated=(raw.get("last_updated") or None),
            embedding_model=str(raw.get("embedding_model") or ""),
            rejections_total=int(raw.get("rejections_total") or 0),
            rag_enabled=_rag_enabled_flag(),
        )
        logger.info(
            "get_stats: exit doc_count=%d index_size=%d enabled=%s",
            result.doc_count,
            result.index_size,
            result.rag_enabled,
        )
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("get_stats failed: %s", str(exc)[:200])
        raise HTTPException(status_code=500, detail="Failed to fetch RAG stats")


@router.post("/search", response_model=SearchResponse, operation_id="rag_search")
async def search(body: SearchRequest) -> SearchResponse:
    """Hybrid (BM25 + semantic vector) search over the RAG corpus.

    When RAG is disabled the engine returns an empty list — we surface that
    as results=[] / total=0 (200 OK), not as an error.
    """
    logger.info(
        "search: query_len=%d top_k=%d hybrid=%s",
        len(body.query),
        body.top_k,
        body.hybrid,
    )
    rag = _safe_import_rag()
    try:
        raw: list[dict[str, Any]] = await asyncio.to_thread(
            rag.search_corpus,
            query=body.query,
            top_k=body.top_k,
            hybrid=body.hybrid,
        )
        items = [
            SearchResultItem(
                id=str(r.get("id") or ""),
                content=str(r.get("content") or ""),
                score=float(r.get("score") or 0.0),
                metadata=dict(r.get("metadata") or {}),
                bm25_score=float(r.get("bm25_score") or 0.0),
                semantic_score=float(r.get("semantic_score") or 0.0),
            )
            for r in raw
        ]
        logger.info("search: exit results=%d", len(items))
        return SearchResponse(query=body.query, results=items, total=len(items))
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("search failed: %s", str(exc)[:200])
        raise HTTPException(status_code=500, detail="Corpus search failed")


@router.post("/documents", response_model=IndexDocumentResponse, operation_id="rag_index_document")
async def index_document(body: IndexDocumentRequest) -> IndexDocumentResponse:
    """Index a document with optional PII scrubbing.

    The engine returns False (not an exception) for two distinct cases:
      1. RAG disabled — no Azure creds.
      2. PII confidence > 0.7 — document rejected and logged.
    We can't distinguish them from the engine's return value alone, so the
    response uses indexed=False with a generic 'rejected_or_disabled' reason.
    Engineers can correlate with data/rag_rejections.jsonl or stats.rag_enabled
    if they need specifics — both surfaces already exist.
    """
    logger.info(
        "index_document: doc_id=%s content_len=%d scrub=%s",
        body.doc_id,
        len(body.content),
        body.scrub,
    )
    rag = _safe_import_rag()
    try:
        indexed: bool = await asyncio.to_thread(
            rag.index_document,
            doc_id=body.doc_id,
            content=body.content,
            metadata=body.metadata,
            scrub=body.scrub,
        )
        reason: Optional[str] = None
        if not indexed:
            reason = (
                "RAG disabled — set AZURE_SEARCH_ENDPOINT/KEY and OPENAI_API_KEY"
                if not _rag_enabled_flag()
                else "rejected by PII filter or upstream failure — see logs"
            )
        logger.info(
            "index_document: doc_id=%s indexed=%s reason=%s",
            body.doc_id,
            indexed,
            reason or "-",
        )
        return IndexDocumentResponse(doc_id=body.doc_id, indexed=indexed, reason=reason)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("index_document failed: doc_id=%s err=%s", body.doc_id, str(exc)[:200])
        raise HTTPException(status_code=500, detail="Failed to index document")


@router.delete("/documents/{doc_id}", response_model=DeleteDocumentResponse, operation_id="rag_delete_document")
async def delete_document(
    doc_id: str = Path(..., min_length=1, max_length=256, description="Document ID to remove"),
) -> DeleteDocumentResponse:
    """Remove a single document from the Azure AI Search index.

    Returns deleted=False when RAG is disabled — same fail-soft contract as
    the engine. 404 is NOT used: Azure Search delete is idempotent and the
    engine has no read-before-delete, so we can't distinguish 'didn't exist'
    from 'deleted successfully' without an extra round trip we don't want.
    """
    logger.info("delete_document: doc_id=%s", doc_id)
    rag = _safe_import_rag()
    try:
        deleted: bool = await asyncio.to_thread(rag.delete_document, doc_id=doc_id)
        logger.info("delete_document: doc_id=%s deleted=%s", doc_id, deleted)
        return DeleteDocumentResponse(doc_id=doc_id, deleted=deleted)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("delete_document failed: doc_id=%s err=%s", doc_id, str(exc)[:200])
        raise HTTPException(status_code=500, detail="Failed to delete document")
