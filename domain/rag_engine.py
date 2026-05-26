"""Azure AI Search wrapper with hybrid (BM25 + semantic vector) retrieval.

Index-time PII scrubbing is mandatory when scrub=True (default).
Documents with PII confidence > 0.7 are rejected and logged to
data/rag_rejections.jsonl.

Fail-closed behaviour:
- Missing required env vars → raise at module load (clear message)
- RAG_ENABLED=false → all mutating functions no-op, searches return []
- Azure Search unreachable → searches return [], index attempts raise (logged)

Hybrid scoring: combined = (semantic_weight * norm_semantic) + ((1 - semantic_weight) * norm_bm25)
Default semantic_weight = 0.6 (configurable via RAG_HYBRID_SEMANTIC_WEIGHT).
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx
from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level configuration — read once at import time
# ---------------------------------------------------------------------------

def _require_env(name: str) -> str:
    """Return env var value or raise at module load with a clear message."""
    value = os.getenv(name, "")
    if not value:
        raise EnvironmentError(
            f"Missing required environment variable: {name}. "
            "Set it in your shell or App Service configuration before importing rag_engine."
        )
    return value


def _optional_env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


# Feature flag — when false, module loads but no Azure calls are made
_RAG_ENABLED: bool = _optional_env("RAG_ENABLED", "true").lower() in ("true", "1", "yes")

# Load Azure creds (optional at import — RAG auto-disables if any are missing)
_SEARCH_ENDPOINT: str = _optional_env("AZURE_SEARCH_ENDPOINT", "").rstrip("/")
_SEARCH_KEY: str = _optional_env("AZURE_SEARCH_KEY", "")
_SEARCH_INDEX: str = _optional_env("AZURE_SEARCH_INDEX", "aigovern-rag-index")
_OPENAI_API_KEY: str = _optional_env("OPENAI_API_KEY", "")

# Auto-disable RAG if any required cred is missing (import must succeed for tests/dev)
_missing_creds = [
    name for name, value in [
        ("AZURE_SEARCH_ENDPOINT", _SEARCH_ENDPOINT),
        ("AZURE_SEARCH_KEY", _SEARCH_KEY),
        ("OPENAI_API_KEY", _OPENAI_API_KEY),
    ]
    if not value
]
if _RAG_ENABLED and _missing_creds:
    logger.warning(
        f"RAG auto-disabled: missing env vars {_missing_creds}. "
        "Set them in App Service or .env to enable. All RAG operations will return safe defaults."
    )
    _RAG_ENABLED = False
elif not _RAG_ENABLED:
    logger.warning("RAG_ENABLED=false — all RAG operations are no-ops")

_EMBEDDING_MODEL: str = _optional_env("RAG_EMBEDDING_MODEL", "text-embedding-3-small")
_TOP_K: int = int(_optional_env("RAG_TOP_K", "5"))
_SEMANTIC_WEIGHT: float = float(_optional_env("RAG_HYBRID_SEMANTIC_WEIGHT", "0.6"))

# Clamp semantic weight to valid range
_SEMANTIC_WEIGHT = max(0.0, min(1.0, _SEMANTIC_WEIGHT))
_BM25_WEIGHT: float = 1.0 - _SEMANTIC_WEIGHT

# Vector dimensions for text-embedding-3-small
_EMBEDDING_DIMENSIONS: int = 1536

# Azure AI Search API version
_SEARCH_API_VERSION: str = "2023-11-01"

# Storage paths
_DATA_DIR = Path(__import__("os").environ.get("DATA_ROOT") or (Path(__file__).resolve().parents[1] / "data"))
_DATA_DIR.mkdir(exist_ok=True)
_REJECTIONS_FILE: Path = _DATA_DIR / "rag_rejections.jsonl"

# PII confidence threshold — documents above this are rejected at index time
_PII_REJECTION_THRESHOLD: float = 0.7

# ---------------------------------------------------------------------------
# Pydantic response models
# ---------------------------------------------------------------------------


class SearchResult(BaseModel):
    """A single document returned from hybrid search."""

    model_config = ConfigDict(extra="forbid")

    id: str
    content: str
    score: float
    metadata: dict[str, Any]
    bm25_score: float
    semantic_score: float


class RagStats(BaseModel):
    """Statistics about the RAG index."""

    model_config = ConfigDict(extra="forbid")

    index_size: int
    doc_count: int
    last_updated: Optional[str]
    embedding_model: str
    rejections_total: int


# ---------------------------------------------------------------------------
# Azure AI Search REST helpers
# ---------------------------------------------------------------------------

def _search_headers() -> dict[str, str]:
    """Build standard Azure Search request headers."""
    return {
        "Content-Type": "application/json",
        "api-key": _SEARCH_KEY,
    }


def _index_url(path: str = "") -> str:
    return f"{_SEARCH_ENDPOINT}/indexes/{_SEARCH_INDEX}{path}?api-version={_SEARCH_API_VERSION}"


def _ensure_index_exists() -> None:
    """Create the Azure AI Search index if it does not already exist.

    Called lazily on the first index_document() call. Schema follows the
    spec: id, content, contentVector, metadata, indexed_at, scrub_score.
    """
    check_url = f"{_SEARCH_ENDPOINT}/indexes/{_SEARCH_INDEX}?api-version={_SEARCH_API_VERSION}"
    with httpx.Client(timeout=10.0) as client:
        resp = client.get(check_url, headers=_search_headers())
        if resp.status_code == 200:
            logger.debug("RAG index %s already exists", _SEARCH_INDEX)
            return
        if resp.status_code != 404:
            logger.error(
                "Unexpected status %s checking index existence: %s",
                resp.status_code, resp.text,
            )
            resp.raise_for_status()

    # Index does not exist — create it
    schema = {
        "name": _SEARCH_INDEX,
        "fields": [
            {
                "name": "id",
                "type": "Edm.String",
                "key": True,
                "searchable": False,
                "filterable": True,
                "sortable": False,
                "facetable": False,
                "retrievable": True,
            },
            {
                "name": "content",
                "type": "Edm.String",
                "searchable": True,
                "filterable": False,
                "sortable": False,
                "facetable": False,
                "retrievable": True,
                "analyzerName": "en.microsoft",
            },
            {
                "name": "contentVector",
                "type": "Collection(Edm.Single)",
                "searchable": True,
                "retrievable": True,
                "dimensions": _EMBEDDING_DIMENSIONS,
                "vectorSearchProfile": "hnsw-profile",
            },
            {
                "name": "metadata",
                "type": "Edm.String",
                "searchable": False,
                "filterable": False,
                "sortable": False,
                "facetable": False,
                "retrievable": True,
            },
            {
                "name": "indexed_at",
                "type": "Edm.DateTimeOffset",
                "searchable": False,
                "filterable": True,
                "sortable": True,
                "facetable": False,
                "retrievable": True,
            },
            {
                "name": "scrub_score",
                "type": "Edm.Double",
                "searchable": False,
                "filterable": True,
                "sortable": True,
                "facetable": False,
                "retrievable": True,
            },
        ],
        "vectorSearch": {
            "algorithms": [
                {
                    "name": "hnsw-algo",
                    "kind": "hnsw",
                    "hnswParameters": {
                        "metric": "cosine",
                        "m": 4,
                        "efConstruction": 400,
                        "efSearch": 500,
                    },
                }
            ],
            "profiles": [
                {
                    "name": "hnsw-profile",
                    "algorithm": "hnsw-algo",
                }
            ],
        },
        "semantic": {
            "configurations": [
                {
                    "name": "semantic-config",
                    "prioritizedFields": {
                        "contentFields": [{"fieldName": "content"}],
                    },
                }
            ]
        },
    }

    create_url = f"{_SEARCH_ENDPOINT}/indexes?api-version={_SEARCH_API_VERSION}"
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(create_url, headers=_search_headers(), json=schema)
        if resp.status_code not in (200, 201):
            logger.error("Failed to create index %s: %s", _SEARCH_INDEX, resp.text)
            resp.raise_for_status()

    logger.info("Created Azure AI Search index: %s", _SEARCH_INDEX)


# ---------------------------------------------------------------------------
# Embedding generation
# ---------------------------------------------------------------------------

def _generate_embedding(text: str) -> list[float]:
    """Generate a text embedding via OpenAI text-embedding-3-small.

    Args:
        text: Input text (already scrubbed of PII).

    Returns:
        List of 1536 floats.

    Raises:
        RuntimeError: On API failure after logging.
    """
    start = time.monotonic()
    logger.info(
        "Generating embedding via %s — content_length=%d chars",
        _EMBEDDING_MODEL, len(text),
    )
    try:
        from openai import OpenAI  # noqa: PLC0415 — deferred to avoid heavy import at module load

        client = OpenAI(api_key=_OPENAI_API_KEY)
        response = client.embeddings.create(
            model=_EMBEDDING_MODEL,
            input=text,
            dimensions=_EMBEDDING_DIMENSIONS,
        )
        embedding: list[float] = response.data[0].embedding
        elapsed = int((time.monotonic() - start) * 1000)
        logger.info(
            "Embedding generated — model=%s dims=%d latency_ms=%d",
            _EMBEDDING_MODEL, len(embedding), elapsed,
        )
        return embedding
    except Exception as exc:
        logger.error("Embedding generation failed: %s", exc, exc_info=True)
        raise RuntimeError(f"Embedding generation failed: {exc}") from exc


# ---------------------------------------------------------------------------
# PII confidence scoring
# ---------------------------------------------------------------------------

def _pii_confidence(text: str) -> float:
    """Return a PII confidence score in [0.0, 1.0] for the given text.

    Combines two layers:
    1. Regex patterns for SSN, credit card, email, phone — entities Presidio
       frequently misses or scores low on in this deployment.
    2. Presidio NER for PERSON, EMAIL_ADDRESS, PHONE_NUMBER and other high-signal
       types (DATE_TIME, URL, LOCATION excluded — too many false positives).

    Both layers contribute to the combined score. Saturation: 3 strong
    detections (total weighted score >= 3.0) → confidence 1.0.

    Args:
        text: Raw text to assess.

    Returns:
        Float in [0.0, 1.0]. 0.0 = no PII detected.
    """
    if not text:
        return 0.0

    import re as _re  # noqa: PLC0415

    # --- Layer 1: Regex patterns (high specificity, weighted by pattern confidence) ---
    _REGEX_PATTERNS: list[tuple[str, float]] = [
        (r"\b\d{3}-\d{2}-\d{4}\b", 0.9),                                # SSN
        (r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b", 0.85),         # credit card
        (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", 0.8),  # email
        (r"\+?1?[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b", 0.75),  # phone
    ]

    regex_scores: list[float] = []
    for pattern, weight in _REGEX_PATTERNS:
        if _re.search(pattern, text, _re.IGNORECASE):
            regex_scores.append(weight)

    # --- Layer 2: Presidio NER (high-signal entity types only) ---
    _HIGH_SIGNAL_ENTITIES = {
        "PERSON",
        "EMAIL_ADDRESS",
        "PHONE_NUMBER",
        "US_SSN",
        "CREDIT_CARD",
        "IBAN_CODE",
        "IP_ADDRESS",
        "US_BANK_NUMBER",
        "MEDICAL_LICENSE",
        "US_PASSPORT",
        "US_ITIN",
    }

    presidio_scores: list[float] = []
    try:
        from presidio_analyzer import AnalyzerEngine  # noqa: PLC0415

        analyzer = AnalyzerEngine()
        results = analyzer.analyze(text=text, language="en")
        presidio_scores = [
            r.score
            for r in results
            if r.entity_type in _HIGH_SIGNAL_ENTITIES and r.score >= 0.6
        ]
    except ImportError:
        pass
    except Exception as exc:
        logger.warning("Presidio PII scoring failed: %s — relying on regex layer only", exc)

    # --- Combine both layers ---
    all_scores = regex_scores + presidio_scores
    if not all_scores:
        return 0.0

    # Sum top-5 signals (de-duplicates same PII appearing in both layers).
    # Saturation: total >= 3.0 → confidence 1.0
    total = sum(sorted(all_scores, reverse=True)[:5])
    confidence = min(1.0, total / 3.0)
    return round(confidence, 4)


# ---------------------------------------------------------------------------
# Core public API
# ---------------------------------------------------------------------------

def _index_document_impl(
    doc_id: str,
    content: str,
    metadata: dict[str, Any],
    scrub: bool = True,
) -> bool:
    """Internal implementation of index_document — called by AzureSearchRag backend.

    Contains the actual Azure AI Search upload logic without the provider proxy layer.
    Exists to break the circular call chain:
      index_document -> get_rag_backend().index -> AzureSearchRag.index
      -> index_document -> ... (infinite recursion)

    Args and returns identical to index_document() — see that docstring.
    """
    start = time.monotonic()
    logger.info(
        "index_document entry — doc_id=%s content_length=%d scrub=%s rag_enabled=%s",
        doc_id, len(content), scrub, _RAG_ENABLED,
    )

    if not _RAG_ENABLED:
        logger.warning("index_document: RAG_ENABLED=false — skipping (doc_id=%s)", doc_id)
        return False

    pii_score: float = 0.0
    indexed_content: str = content

    if scrub:
        # Step 1: Assess PII confidence BEFORE scrubbing (raw text has detectable PII)
        pii_score = _pii_confidence(content)
        logger.info("PII confidence for doc_id=%s: %.4f", doc_id, pii_score)

        if pii_score > _PII_REJECTION_THRESHOLD:
            _log_rejection(doc_id, content, pii_score, metadata)
            logger.warning(
                "index_document REJECTED — doc_id=%s pii_score=%.4f threshold=%.1f",
                doc_id, pii_score, _PII_REJECTION_THRESHOLD,
            )
            return False

        # Step 2: Scrub PII tokens (safe to index now)
        try:
            from scrubber import tokenise_payload  # noqa: PLC0415

            scrubbed_content, vault_id = tokenise_payload(content, scope=f"rag_index_{doc_id}")
            indexed_content = scrubbed_content
            logger.info(
                "PII scrubbed for doc_id=%s vault_id=%s",
                doc_id, vault_id or "(no entities found)",
            )
        except Exception as exc:
            logger.error(
                "Scrubber error for doc_id=%s: %s — aborting index (fail-closed)",
                doc_id, exc, exc_info=True,
            )
            return False

    # Step 3: Generate embedding
    try:
        embedding = _generate_embedding(indexed_content)
    except RuntimeError as exc:
        logger.error("index_document failed at embedding step — doc_id=%s: %s", doc_id, exc)
        return False

    # Step 4: Ensure index exists (idempotent)
    try:
        _ensure_index_exists()
    except Exception as exc:
        logger.error("index_document failed at index-creation step — doc_id=%s: %s", doc_id, exc)
        return False

    # Step 5: Upload document to Azure AI Search
    document = {
        "id": doc_id,
        "content": indexed_content,
        "contentVector": embedding,
        "metadata": json.dumps(metadata, default=str),
        "indexed_at": datetime.now(timezone.utc).isoformat(),
        "scrub_score": pii_score,
    }

    upload_url = _index_url(f"/docs/index")
    payload = {"value": [{"@search.action": "mergeOrUpload", **document}]}

    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(upload_url, headers=_search_headers(), json=payload)
            resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.error(
            "index_document upload failed — doc_id=%s status=%s body=%s",
            doc_id, exc.response.status_code, exc.response.text,
        )
        return False
    except Exception as exc:
        logger.error("index_document upload error — doc_id=%s: %s", doc_id, exc, exc_info=True)
        return False

    elapsed = int((time.monotonic() - start) * 1000)
    logger.info(
        "_index_document_impl success — doc_id=%s pii_score=%.4f latency_ms=%d",
        doc_id, pii_score, elapsed,
    )
    return True


def index_document(
    doc_id: str,
    content: str,
    metadata: dict[str, Any],
    scrub: bool = True,
) -> bool:
    """Index a document into Azure AI Search with optional PII scrubbing.

    Proxies through providers.get_rag_backend().index(). The azure_search backend
    delegates back to _index_document_impl() to avoid circular imports.

    When scrub=True (default), runs scrubber.tokenise_payload() on the content
    before generating embeddings. Documents with PII confidence > 0.7 are
    REJECTED (returns False) and logged to data/rag_rejections.jsonl.

    Args:
        doc_id:   Unique document identifier (maps to 'id' field in index).
        content:  Document text to index.
        metadata: Arbitrary key/value metadata — stored as JSON string.
        scrub:    Whether to run PII scrubbing before indexing. Default True.

    Returns:
        True on successful index; False if rejected due to PII or disabled.
    """
    from providers import get_rag_backend
    return get_rag_backend().index(
        doc_id=doc_id,
        content=content,
        metadata=metadata,
        scrub=scrub,
    )


def _search_corpus_impl(
    query: str,
    top_k: int = _TOP_K,
    hybrid: bool = True,
) -> list[dict[str, Any]]:
    """Internal implementation of search_corpus — called by AzureSearchRag backend.

    Exists to break the circular call chain:
      search_corpus -> get_rag_backend().search -> AzureSearchRag.search
      -> search_corpus -> ... (infinite recursion)

    Args and returns identical to search_corpus() — see that docstring.
    """
    start = time.monotonic()
    logger.info(
        "search_corpus entry — query_length=%d top_k=%d hybrid=%s rag_enabled=%s",
        len(query), top_k, hybrid, _RAG_ENABLED,
    )

    if not _RAG_ENABLED:
        logger.warning("search_corpus: RAG_ENABLED=false — returning []")
        return []

    try:
        query_vector: Optional[list[float]] = None
        if hybrid:
            try:
                query_vector = _generate_embedding(query)
            except RuntimeError as exc:
                logger.warning(
                    "search_corpus: embedding failed (%s) — falling back to BM25-only", exc
                )

        results = _execute_search(query, top_k, query_vector)

        elapsed = int((time.monotonic() - start) * 1000)
        logger.info(
            "search_corpus exit — results=%d latency_ms=%d",
            len(results), elapsed,
        )
        return results

    except Exception as exc:
        logger.error("search_corpus failed: %s", exc, exc_info=True)
        return []


def search_corpus(
    query: str,
    top_k: int = _TOP_K,
    hybrid: bool = True,
) -> list[dict[str, Any]]:
    """Search the RAG corpus with hybrid (BM25 + semantic vector) retrieval.

    Proxies through providers.get_rag_backend().search(). The azure_search backend
    delegates back to _search_corpus_impl() to avoid circular imports.

    When hybrid=True, combines BM25 full-text scores with semantic vector
    similarity. When hybrid=False, performs BM25-only full-text search.

    Args:
        query:  Natural language query string.
        top_k:  Maximum number of results to return.
        hybrid: Whether to include semantic vector reranking. Default True.

    Returns:
        List of dicts with keys: id, content, score, metadata, bm25_score, semantic_score.
        Returns empty list if RAG is disabled or Azure Search is unreachable.
    """
    from providers import get_rag_backend
    return get_rag_backend().search(
        query=query,
        top_k=top_k,
        hybrid=hybrid,
    )


def _execute_search(
    query: str,
    top_k: int,
    query_vector: Optional[list[float]],
) -> list[dict[str, Any]]:
    """Execute BM25 (and optionally semantic) search against Azure AI Search REST API.

    Args:
        query:        Full-text query string.
        top_k:        Number of results to return.
        query_vector: Pre-computed query embedding, or None for BM25-only.

    Returns:
        List of result dicts with hybrid scores.
    """
    # Retrieve 2x top_k from both channels so we have enough to merge/rerank
    fetch_k = min(top_k * 2, 50)

    search_payload: dict[str, Any] = {
        "search": query,
        "queryType": "simple",
        "top": fetch_k,
        "select": "id,content,metadata,indexed_at,scrub_score",
        "count": True,
    }

    if query_vector is not None:
        search_payload["vectorQueries"] = [
            {
                "kind": "vector",
                "vector": query_vector,
                "fields": "contentVector",
                "k": fetch_k,
            }
        ]

    search_url = _index_url("/docs/search")

    with httpx.Client(timeout=15.0) as client:
        resp = client.post(search_url, headers=_search_headers(), json=search_payload)
        resp.raise_for_status()

    data = resp.json()
    raw_results: list[dict[str, Any]] = data.get("value", [])

    if not raw_results:
        return []

    # Extract BM25 and semantic scores from the Azure response
    # Azure Search returns '@search.score' for BM25 and '@search.rerankerScore' for semantic
    bm25_scores = [r.get("@search.score", 0.0) for r in raw_results]
    semantic_scores = [r.get("@search.rerankerScore", 0.0) for r in raw_results]

    # Normalize scores to [0, 1]
    def _normalize(scores: list[float]) -> list[float]:
        max_s = max(scores) if scores else 1.0
        if max_s == 0.0:
            return [0.0] * len(scores)
        return [s / max_s for s in scores]

    norm_bm25 = _normalize(bm25_scores)
    norm_semantic = _normalize(semantic_scores)

    # Compute combined hybrid score
    combined: list[tuple[float, float, float, dict[str, Any]]] = []
    for i, raw in enumerate(raw_results):
        nb = norm_bm25[i]
        ns = norm_semantic[i]
        score = (_SEMANTIC_WEIGHT * ns) + (_BM25_WEIGHT * nb)

        # Deserialize metadata JSON stored at index time
        raw_meta = raw.get("metadata", "{}")
        try:
            meta = json.loads(raw_meta) if isinstance(raw_meta, str) else raw_meta
        except json.JSONDecodeError:
            meta = {"raw": raw_meta}

        combined.append((score, nb, ns, {
            "id": raw.get("id", ""),
            "content": raw.get("content", ""),
            "metadata": meta,
        }))

    # Sort by combined score descending
    combined.sort(key=lambda x: x[0], reverse=True)

    # Build final result list, trimmed to top_k
    results: list[dict[str, Any]] = []
    for score, nb, ns, doc in combined[:top_k]:
        results.append(
            SearchResult(
                id=doc["id"],
                content=doc["content"],
                score=round(score, 6),
                metadata=doc["metadata"],
                bm25_score=round(nb, 6),
                semantic_score=round(ns, 6),
            ).model_dump()
        )

    return results


def _rag_stats_impl() -> dict[str, Any]:
    """Internal implementation of rag_stats — called by AzureSearchRag backend.

    Exists to break the circular call chain:
      rag_stats -> get_rag_backend().stats -> AzureSearchRag.stats
      -> rag_stats -> ... (infinite recursion)
    """
    start = time.monotonic()
    logger.info("rag_stats entry — rag_enabled=%s", _RAG_ENABLED)

    empty_stats = RagStats(
        index_size=0,
        doc_count=0,
        last_updated=None,
        embedding_model=_EMBEDDING_MODEL,
        rejections_total=_count_rejections(),
    ).model_dump()

    if not _RAG_ENABLED:
        logger.warning("rag_stats: RAG_ENABLED=false — returning empty stats")
        return empty_stats

    try:
        stats_url = f"{_SEARCH_ENDPOINT}/indexes/{_SEARCH_INDEX}/stats?api-version={_SEARCH_API_VERSION}"
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(stats_url, headers=_search_headers())
            resp.raise_for_status()

        data = resp.json()
        doc_count: int = data.get("documentCount", 0)
        index_size: int = data.get("storageSize", 0)

        # Fetch the most recent indexed_at timestamp
        last_updated: Optional[str] = _fetch_last_updated()

        result = RagStats(
            index_size=index_size,
            doc_count=doc_count,
            last_updated=last_updated,
            embedding_model=_EMBEDDING_MODEL,
            rejections_total=_count_rejections(),
        ).model_dump()

        elapsed = int((time.monotonic() - start) * 1000)
        logger.info("rag_stats exit — doc_count=%d latency_ms=%d", doc_count, elapsed)
        return result

    except Exception as exc:
        logger.error("_rag_stats_impl failed: %s", exc, exc_info=True)
        return empty_stats


def rag_stats() -> dict[str, Any]:
    """Return statistics about the RAG index.

    Proxies through providers.get_rag_backend().stats(). The azure_search backend
    delegates back to _rag_stats_impl() to avoid circular imports.

    Returns:
        Dict with keys: index_size, doc_count, last_updated,
        embedding_model, rejections_total.
        Returns zeroed stats if RAG is disabled or Azure Search is unreachable.
    """
    from providers import get_rag_backend
    return get_rag_backend().stats()


def delete_document(doc_id: str) -> bool:
    """Remove a document from the Azure AI Search index.

    Args:
        doc_id: The document ID to delete.

    Returns:
        True on successful deletion; False if RAG is disabled or on error.
    """
    start = time.monotonic()
    logger.info("delete_document entry — doc_id=%s rag_enabled=%s", doc_id, _RAG_ENABLED)

    if not _RAG_ENABLED:
        logger.warning("delete_document: RAG_ENABLED=false — skipping (doc_id=%s)", doc_id)
        return False

    try:
        _ensure_index_exists()
    except Exception as exc:
        logger.error("delete_document: index check failed — doc_id=%s: %s", doc_id, exc)
        return False

    payload = {"value": [{"@search.action": "delete", "id": doc_id}]}
    delete_url = _index_url("/docs/index")

    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(delete_url, headers=_search_headers(), json=payload)
            resp.raise_for_status()

        elapsed = int((time.monotonic() - start) * 1000)
        logger.info("delete_document success — doc_id=%s latency_ms=%d", doc_id, elapsed)
        return True

    except httpx.HTTPStatusError as exc:
        logger.error(
            "delete_document failed — doc_id=%s status=%s body=%s",
            doc_id, exc.response.status_code, exc.response.text,
        )
        return False
    except Exception as exc:
        logger.error("delete_document error — doc_id=%s: %s", doc_id, exc, exc_info=True)
        return False


def purge_chunks(subject_id: str) -> dict:
    """Delete all Azure AI Search chunks where ``source_id == subject_id``.

    When ``AZURE_SEARCH_ENDPOINT`` is not configured (dev mode), returns a
    simulated digest with ``chunks_removed=0`` rather than raising.

    Steps:

    1. Query the index for documents whose ``metadata`` JSON contains
       ``source_id == subject_id`` (filter on the metadata field text).
    2. Issue delete-by-id actions for every matched document ID.
    3. Emit a ``T3_CHUNK_PURGED`` audit event via ``append_agent_event``.
    4. Return ``chunks_removed`` and ``sha256_digest_after``.

    Args:
        subject_id: The source_id / data subject identifier to purge.

    Returns:
        Dict with keys:

        * ``chunks_removed`` — number of index documents deleted.
        * ``sha256_digest_after`` — SHA-256 of
          ``"t3_purged:<subject_id>:<count>"``.
    """
    import hashlib

    logger.info(
        "purge_chunks: entry subject_id=%s rag_enabled=%s", subject_id, _RAG_ENABLED
    )

    from domain.repository import append_agent_event  # late import

    if not _RAG_ENABLED:
        # Dev mode — simulated digest, no Azure calls
        digest = hashlib.sha256(
            f"t3_purged:{subject_id}:0".encode("utf-8")
        ).hexdigest()
        logger.info(
            "purge_chunks: RAG_ENABLED=false — simulated return subject_id=%s",
            subject_id,
        )
        append_agent_event("T3_CHUNK_PURGED", {
            "subject_id": subject_id,
            "chunks_removed": 0,
            "mode": "dev_simulated",
            "sha256_digest_after": digest,
        })
        return {"chunks_removed": 0, "sha256_digest_after": digest}

    try:
        # Step 1 — search for docs belonging to subject_id using $skip pagination.
        # Azure Search caps top=1000 per request; iterate with $skip until the
        # response value array is empty.  Bound at 100 iterations (100k chunks)
        # as a sanity cap.  Log when the cap is hit.
        _PAGE_SIZE: int = 1000
        _MAX_ITERATIONS: int = 100  # 100 * 1000 = 100k chunks per subject max

        matched_ids: list[str] = []
        skip: int = 0

        with httpx.Client(timeout=30.0) as client:
            search_url = _index_url("/docs/search")
            for iteration in range(_MAX_ITERATIONS):
                search_payload: dict[str, Any] = {
                    "search": "*",
                    "top": _PAGE_SIZE,
                    "skip": skip,
                    "select": "id,metadata",
                }
                resp = client.post(
                    search_url, headers=_search_headers(), json=search_payload
                )
                resp.raise_for_status()
                raw_docs: list[dict[str, Any]] = resp.json().get("value", [])
                if not raw_docs:
                    break
                for doc in raw_docs:
                    raw_meta = doc.get("metadata", "{}")
                    try:
                        meta = json.loads(raw_meta) if isinstance(raw_meta, str) else raw_meta
                    except json.JSONDecodeError:
                        meta = {}
                    if meta.get("source_id") == subject_id:
                        matched_ids.append(doc["id"])
                skip += len(raw_docs)
                if len(raw_docs) < _PAGE_SIZE:
                    break
            else:
                # Fail-closed: hitting the iteration cap means we cannot guarantee
                # complete erasure for this subject. Raising propagates as cascade
                # PARTIAL_FAILURE — operator must increase the cap or split the purge.
                # Returning a "completed" result here would silently violate GDPR
                # erasure for the chunks beyond the cap.
                logger.error(
                    "purge_chunks: $skip pagination hit %d-iteration cap for subject_id=%s; "
                    "raising to force PARTIAL_FAILURE",
                    _MAX_ITERATIONS, subject_id,
                )
                raise RuntimeError(
                    f"purge_chunks pagination cap exceeded for subject_id={subject_id}; "
                    f"increase _MAX_ITERATIONS or split the purge"
                )

        if not matched_ids:
            digest = hashlib.sha256(
                f"t3_purged:{subject_id}:0".encode("utf-8")
            ).hexdigest()
            logger.info(
                "purge_chunks: no matching chunks subject_id=%s", subject_id
            )
            append_agent_event("T3_CHUNK_PURGED", {
                "subject_id": subject_id,
                "chunks_removed": 0,
                "sha256_digest_after": digest,
            })
            return {"chunks_removed": 0, "sha256_digest_after": digest}

        # Step 2 — delete matched documents
        delete_actions = [
            {"@search.action": "delete", "id": doc_id}
            for doc_id in matched_ids
        ]

        deleted = 0
        # Azure Search batch limit is 1000 docs per request
        batch_size = 1000
        for i in range(0, len(delete_actions), batch_size):
            batch = delete_actions[i : i + batch_size]
            delete_url = _index_url("/docs/index")
            with httpx.Client(timeout=30.0) as client:
                del_resp = client.post(
                    delete_url,
                    headers=_search_headers(),
                    json={"value": batch},
                )
                del_resp.raise_for_status()
            deleted += len(batch)
            logger.info(
                "purge_chunks: deleted batch i=%d size=%d subject_id=%s",
                i, len(batch), subject_id,
            )

        digest = hashlib.sha256(
            f"t3_purged:{subject_id}:{deleted}".encode("utf-8")
        ).hexdigest()

        append_agent_event("T3_CHUNK_PURGED", {
            "subject_id": subject_id,
            "chunks_removed": deleted,
            "sha256_digest_after": digest,
        })

        logger.info(
            "purge_chunks: exit subject_id=%s chunks_removed=%d digest=%s…",
            subject_id, deleted, digest[:12],
        )
        return {"chunks_removed": deleted, "sha256_digest_after": digest}

    except Exception as exc:
        logger.error(
            "purge_chunks: failed subject_id=%s: %s", subject_id, exc, exc_info=True
        )
        raise


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _log_rejection(
    doc_id: str,
    content: str,
    pii_score: float,
    metadata: dict[str, Any],
) -> None:
    """Append a PII rejection record to data/rag_rejections.jsonl.

    Uses storage._append_jsonl() — never writes directly to the file.
    Security: doc was rejected BECAUSE it contains PII — storing any preview
    (even truncated) violates the de-ID vault contract. Log only id/score/length.
    """
    import storage  # noqa: PLC0415 — deferred to match policy_engine pattern

    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "doc_id": doc_id,
        "pii_score": pii_score,
        "threshold": _PII_REJECTION_THRESHOLD,
        "content_length": len(content),
        "metadata": {k: v for k, v in metadata.items() if k != "content"},
        "reason": f"PII confidence {pii_score:.4f} exceeds threshold {_PII_REJECTION_THRESHOLD}",
    }
    try:
        storage._append_jsonl(_REJECTIONS_FILE, record)
        logger.info("Rejection logged to %s — doc_id=%s", _REJECTIONS_FILE.name, doc_id)
    except Exception as exc:
        logger.error("Failed to log rejection for doc_id=%s: %s", doc_id, exc)


def _count_rejections() -> int:
    """Return total number of PII rejection records in data/rag_rejections.jsonl."""
    import storage  # noqa: PLC0415

    try:
        records = storage._read_jsonl(_REJECTIONS_FILE)
        return len(records)
    except Exception:
        return 0


def _fetch_last_updated() -> Optional[str]:
    """Query Azure Search for the most recently indexed document's timestamp.

    Returns ISO 8601 string or None if index is empty / query fails.
    """
    try:
        payload = {
            "search": "*",
            "top": 1,
            "select": "indexed_at",
            "orderby": "indexed_at desc",
        }
        search_url = _index_url("/docs/search")
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(search_url, headers=_search_headers(), json=payload)
            resp.raise_for_status()

        docs = resp.json().get("value", [])
        if docs:
            return docs[0].get("indexed_at")
        return None

    except Exception as exc:
        logger.warning("_fetch_last_updated failed: %s", exc)
        return None
