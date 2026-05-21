"""Azure AI Search RAG backend — calls domain.rag_engine._*_impl private functions.

CIRCULAR IMPORT PREVENTION:
  After Session 05 proxy refactoring:
    index_document(...)  -> get_rag_backend().index(...)  -> AzureSearchRag.index(...)
    search_corpus(...)   -> get_rag_backend().search(...) -> AzureSearchRag.search(...)
    rag_stats()          -> get_rag_backend().stats()     -> AzureSearchRag.stats()

  Calling the public functions from these methods creates INFINITE RECURSION.
  Fix: call the private _impl functions that contain the actual logic.

This class provides the RagBackend Protocol adapter surface only.
No new logic is introduced here.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class AzureSearchRag:
    """RagBackend backed by Azure AI Search in domain.rag_engine."""

    def index(
        self,
        doc_id: str,
        content: str,
        metadata: dict,
        scrub: bool,
    ) -> bool:
        """Index a document into Azure AI Search.

        Calls domain.rag_engine._index_document_impl() (private) to avoid the
        infinite recursion that would result from calling the public index_document().

        Args:
            doc_id:   Unique document identifier.
            content:  Document text. Scrubbed at index time when scrub=True.
            metadata: Arbitrary key/value metadata stored alongside the document.
            scrub:    Whether to PII-scrub content before embedding. Default True.

        Returns:
            True on successful index; False if rejected due to PII, RAG is disabled,
            or an upload error occurred.
        """
        logger.debug(
            "AzureSearchRag.index: entry doc_id=%s content_length=%d scrub=%s",
            doc_id, len(content), scrub,
        )
        # Call _index_document_impl (private) NOT index_document (public proxy) — avoids recursion.
        from domain.rag_engine import _index_document_impl

        result = _index_document_impl(doc_id=doc_id, content=content, metadata=metadata, scrub=scrub)
        logger.debug("AzureSearchRag.index: exit doc_id=%s result=%s", doc_id, result)
        return result

    def search(
        self,
        query: str,
        top_k: int,
        hybrid: bool,
    ) -> list[dict[str, Any]]:
        """Search the Azure AI Search corpus.

        Calls domain.rag_engine._search_corpus_impl() (private) to avoid recursion.

        Args:
            query:  Natural language search query.
            top_k:  Maximum number of results.
            hybrid: Include semantic vector reranking. Default True in rag_engine.

        Returns:
            List of dicts with: id, content, score, metadata, bm25_score, semantic_score.
            Empty list when RAG is disabled or Azure Search is unreachable.
        """
        logger.debug(
            "AzureSearchRag.search: entry query_length=%d top_k=%d hybrid=%s",
            len(query), top_k, hybrid,
        )
        # Call _search_corpus_impl (private) NOT search_corpus (public proxy).
        from domain.rag_engine import _search_corpus_impl

        results = _search_corpus_impl(query=query, top_k=top_k, hybrid=hybrid)
        logger.debug("AzureSearchRag.search: exit results=%d", len(results))
        return results

    def stats(self) -> dict[str, Any]:
        """Return Azure AI Search index statistics.

        Calls domain.rag_engine._rag_stats_impl() (private) to avoid recursion.

        Returns:
            Dict with: index_size (bytes), doc_count, last_updated (ISO str|None),
            embedding_model, rejections_total.
        """
        logger.debug("AzureSearchRag.stats: entry")
        # Call _rag_stats_impl (private) NOT rag_stats (public proxy).
        from domain.rag_engine import _rag_stats_impl

        result = _rag_stats_impl()
        logger.debug(
            "AzureSearchRag.stats: exit doc_count=%s",
            result.get("doc_count", 0),
        )
        return result
