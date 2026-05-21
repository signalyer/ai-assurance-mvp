"""Postgres-backed memory backend — wraps domain.agent_memory.

CIRCULAR IMPORT PREVENTION for write():
  domain.agent_memory.write_episode() is a proxy:
    write_episode(...) -> get_memory_backend().write(...) -> PostgresMemory.write(...)

  Calling domain.agent_memory.write_episode() from this method creates INFINITE RECURSION.
  Fix: call domain.agent_memory._write_episode_impl() (private implementation function).

All other domain.agent_memory functions (selective_recall, memory_stats) are NOT proxied,
so they can be imported directly without circular import risk.

This class provides the MemoryBackend Protocol adapter surface only —
no new logic is introduced here.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_EPISODE_TTL_SECONDS_DEFAULT: int = 2592000  # 30 days


class PostgresMemory:
    """MemoryBackend backed by the Postgres episodic store in domain.agent_memory."""

    def write(
        self,
        workload_id: str,
        prompt: str,
        response: str,
        outcome: str,
        metadata: dict,
        ttl_seconds: int,
    ) -> str:
        """Persist a scrubbed episode to Postgres.

        Calls domain.agent_memory._write_episode_impl() (private) to avoid the
        infinite recursion that would result from calling the public write_episode()
        proxy:
          write_episode -> get_memory_backend().write -> PostgresMemory.write
          -> write_episode -> ... (stack overflow)

        The SCRUBBER_ENABLED vault_id check is enforced inside _write_episode_impl.

        Args:
            workload_id: AI workload identifier (e.g. 'financial_advisor').
            prompt:      Pre-scrubbed prompt text.
            response:    Pre-scrubbed response text.
            outcome:     One of 'success', 'failure', 'review'.
            metadata:    Dict; must include 'vault_id' when SCRUBBER_ENABLED=true.
            ttl_seconds: Seconds until the episode expires. 0 means use module default.

        Returns:
            Episode ID as a UUID string.

        Raises:
            ValueError: If SCRUBBER_ENABLED=true and vault_id is absent from metadata.
        """
        logger.debug(
            "PostgresMemory.write: entry workload_id=%s outcome=%s ttl_seconds=%d",
            workload_id, outcome, ttl_seconds,
        )
        # Call _write_episode_impl (private) NOT write_episode (public proxy) — avoids recursion.
        from domain.agent_memory import _write_episode_impl

        episode_id = _write_episode_impl(
            workload_id=workload_id,
            prompt=prompt,
            response=response,
            outcome=outcome,
            metadata=metadata if metadata else None,
            ttl_seconds=ttl_seconds if ttl_seconds > 0 else None,
        )
        logger.debug("PostgresMemory.write: exit episode_id=%s", episode_id)
        return episode_id

    def read(
        self,
        workload_id: str,
        query: str,
        top_k: int,
        lookback_days: int,
    ) -> list[dict]:
        """Full-text search episodes for *workload_id* using Postgres tsvector.

        Delegates to domain.agent_memory.selective_recall() — this function is NOT
        proxied through providers, so it can be imported directly without circular risk.

        Args:
            workload_id:   Workload to search within.
            query:         Search terms (plain English via plainto_tsquery).
            top_k:         Maximum results to return.
            lookback_days: How many calendar days back to search.

        Returns:
            List of episode dicts ordered by FTS rank then recency.
            Empty list when memory is disabled or unavailable.
        """
        logger.debug(
            "PostgresMemory.read: entry workload_id=%s query_preview=%s top_k=%d",
            workload_id, query[:50], top_k,
        )
        from domain.agent_memory import selective_recall  # not proxied — safe direct import

        results = selective_recall(
            workload_id=workload_id,
            query=query,
            top_k=top_k,
            lookback_days=lookback_days,
        )
        logger.debug(
            "PostgresMemory.read: exit workload_id=%s hits=%d",
            workload_id, len(results),
        )
        return results

    def stats(self) -> dict:
        """Return aggregate memory statistics across all episodes.

        Delegates to domain.agent_memory.memory_stats() — not proxied, direct import safe.

        Returns:
            Dict with keys: total_episodes, episodes_by_workload, oldest_episode,
            expired_count, ttl_default_seconds.
        """
        logger.debug("PostgresMemory.stats: entry")
        from domain.agent_memory import memory_stats  # not proxied — safe direct import

        result = memory_stats()
        logger.debug(
            "PostgresMemory.stats: exit total_episodes=%s",
            result.get("total_episodes", 0),
        )
        return result
