"""Tier 2 episodic memory — Postgres-backed with database-level TTL.

Stores scrubbed prompt/response pairs with outcome labels, eval scores,
and guardrail results. Orchestrates context assembly across T2 (episodic),
T3 (RAG via domain/rag_engine.search_corpus), and T4 (procedural via domains.load_domain).

Environment variables:
  DATABASE_URL          Full Postgres connection string (required unless MEMORY_ENABLED=false)
  EPISODE_TTL_SECONDS   Default TTL in seconds (default: 2592000 = 30 days)
  MEMORY_ENABLED        true|false — if false, all writes are no-ops, reads return empty
  SCRUBBER_ENABLED      true|false — if true, vault_id required in metadata on write

Security constraints:
  - prompt and response stored MUST be pre-scrubbed by caller
  - if SCRUBBER_ENABLED=true and metadata lacks vault_id, write_episode raises ValueError
  - All SQL queries use parameterized statements — never f-string SQL
  - Engine created once at module load; all functions check for None engine
"""

from __future__ import annotations

import logging
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Environment configuration — read once at module load
# ---------------------------------------------------------------------------

_MEMORY_ENABLED: bool = os.getenv("MEMORY_ENABLED", "true").lower() == "true"
_SCRUBBER_ENABLED: bool = os.getenv("SCRUBBER_ENABLED", "false").lower() == "true"
_DATABASE_URL: Optional[str] = os.getenv("DATABASE_URL")

try:
    _EPISODE_TTL_SECONDS: int = int(os.getenv("EPISODE_TTL_SECONDS", "2592000"))
except ValueError:
    _EPISODE_TTL_SECONDS = 2592000

# ---------------------------------------------------------------------------
# SQLAlchemy engine — created once, never per-call
# ---------------------------------------------------------------------------

_engine = None  # type: ignore[assignment]

if _MEMORY_ENABLED:
    if not _DATABASE_URL:
        logger.error(
            "agent_memory: DATABASE_URL is not set. "
            "Episodic memory will be disabled. Set DATABASE_URL or MEMORY_ENABLED=false."
        )
    else:
        try:
            from sqlalchemy import create_engine

            _engine = create_engine(
                _DATABASE_URL,
                pool_size=5,
                max_overflow=10,
                pool_pre_ping=True,          # detect stale connections
                pool_recycle=1800,           # recycle every 30 min
                connect_args={"connect_timeout": 5},
            )
            logger.info("agent_memory: SQLAlchemy engine created (pool_size=5)")
        except Exception as _engine_exc:
            logger.warning(
                f"agent_memory: Failed to create SQLAlchemy engine: {_engine_exc}. "
                "Memory functions will return safe defaults."
            )
            _engine = None

# ---------------------------------------------------------------------------
# Schema bootstrap — inline DDL (no Alembic directory detected at repo root)
# ---------------------------------------------------------------------------

_SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS episodes (
    episode_id         UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    workload_id        VARCHAR(128) NOT NULL,
    timestamp          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    prompt             TEXT         NOT NULL,
    response           TEXT         NOT NULL,
    outcome            VARCHAR(16)  NOT NULL,
    vault_id           VARCHAR(128),
    trace_id           VARCHAR(128),
    eval_scores        JSONB,
    guardrail_result   JSONB,
    metadata           JSONB,
    compressed_summary TEXT,
    expires_at         TIMESTAMPTZ  NOT NULL,
    CONSTRAINT outcome_check CHECK (outcome IN ('success', 'failure', 'review'))
);

CREATE INDEX IF NOT EXISTS idx_episodes_workload
    ON episodes (workload_id, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_episodes_expires
    ON episodes (expires_at);

CREATE INDEX IF NOT EXISTS idx_episodes_fts
    ON episodes
    USING gin(to_tsvector('english', prompt || ' ' || response));

CREATE INDEX IF NOT EXISTS idx_episodes_subject_id
    ON episodes ((metadata->>'subject_id'));
"""


def _init_schema() -> None:
    """Create the episodes table and indexes if they do not exist.

    Called once at module load when engine is available. Idempotent (IF NOT EXISTS).
    """
    if _engine is None:
        return

    try:
        from sqlalchemy import text

        with _engine.begin() as conn:
            conn.execute(text(_SCHEMA_DDL))
        logger.info("agent_memory: schema initialised (episodes table ready)")
    except Exception as exc:
        logger.error(f"agent_memory: schema init failed: {exc}", exc_info=True)


# Run schema bootstrap eagerly at module load
if _engine is not None:
    _init_schema()

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _write_episode_impl(
    workload_id: str,
    prompt: str,
    response: str,
    outcome: str,
    metadata: Optional[dict] = None,
    ttl_seconds: Optional[int] = None,
) -> str:
    """Internal implementation of episode persistence — called by PostgresMemory backend.

    Contains the actual Postgres INSERT logic without the provider proxy layer.
    Exists to break the circular call chain that would occur if the PostgresMemory
    backend called the public write_episode() proxy:
      write_episode -> get_memory_backend().write -> PostgresMemory.write
      -> write_episode -> ... (infinite recursion)

    Args and returns are identical to write_episode() — see that docstring.
    """
    start = datetime.now(timezone.utc)
    logger.info(
        "write_episode: entry",
        extra={"workload_id": workload_id, "outcome": outcome},
    )

    if not _MEMORY_ENABLED:
        logger.debug("write_episode: MEMORY_ENABLED=false — no-op")
        return str(uuid.uuid4())  # Return a plausible UUID so callers don't break

    meta = metadata or {}

    # Security gate: mirror tracer.py vault_id requirement
    if _SCRUBBER_ENABLED and not meta.get("vault_id"):
        raise ValueError(
            "write_episode: SCRUBBER_ENABLED=true but metadata is missing 'vault_id'. "
            "Ensure prompt and response are scrubbed via scrubber.tokenise_payload() "
            "and pass the returned vault_id in metadata."
        )

    if _engine is None:
        logger.warning("write_episode: engine unavailable — returning placeholder UUID")
        return str(uuid.uuid4())

    valid_outcomes = {"success", "failure", "review"}
    if outcome not in valid_outcomes:
        raise ValueError(f"write_episode: outcome must be one of {valid_outcomes}, got '{outcome}'")

    effective_ttl = ttl_seconds if ttl_seconds is not None else _EPISODE_TTL_SECONDS
    episode_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=effective_ttl)

    # Extract known keys from metadata into dedicated columns
    vault_id: Optional[str] = meta.get("vault_id")
    trace_id: Optional[str] = meta.get("trace_id")
    eval_scores: Optional[dict] = meta.get("eval_scores")
    guardrail_result: Optional[dict] = meta.get("guardrail_result")

    # Everything else stays in the generic metadata column
    extra_meta = {k: v for k, v in meta.items() if k not in ("vault_id", "trace_id", "eval_scores", "guardrail_result")}

    try:
        import json as _json

        from sqlalchemy import text

        insert_sql = text(
            """
            INSERT INTO episodes
                (episode_id, workload_id, timestamp, prompt, response, outcome,
                 vault_id, trace_id, eval_scores, guardrail_result, metadata, expires_at)
            VALUES
                (:episode_id, :workload_id, :timestamp, :prompt, :response, :outcome,
                 :vault_id, :trace_id, :eval_scores, :guardrail_result, :metadata, :expires_at)
            """
        )

        with _engine.begin() as conn:
            conn.execute(
                insert_sql,
                {
                    "episode_id": episode_id,
                    "workload_id": workload_id,
                    "timestamp": now,
                    "prompt": prompt,
                    "response": response,
                    "outcome": outcome,
                    "vault_id": vault_id,
                    "trace_id": trace_id,
                    "eval_scores": _json.dumps(eval_scores) if eval_scores is not None else None,
                    "guardrail_result": _json.dumps(guardrail_result) if guardrail_result is not None else None,
                    "metadata": _json.dumps(extra_meta) if extra_meta else None,
                    "expires_at": expires_at,
                },
            )

        elapsed_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
        logger.info(
            "write_episode: exit",
            extra={
                "episode_id": episode_id,
                "workload_id": workload_id,
                "elapsed_ms": elapsed_ms,
                "ttl_seconds": effective_ttl,
            },
        )
        return episode_id

    except Exception as exc:
        logger.error(
            f"write_episode: DB insert failed for workload={workload_id}: {exc}",
            exc_info=True,
        )
        raise


def write_episode(
    workload_id: str,
    prompt: str,
    response: str,
    outcome: str,
    metadata: Optional[dict] = None,
    ttl_seconds: Optional[int] = None,
) -> str:
    """Insert a scrubbed episode into Postgres. Returns episode_id (UUID string).

    Proxies through providers.get_memory_backend().write(). The postgres backend
    delegates back to _write_episode_impl() to avoid circular imports.

    The prompt and response MUST be already scrubbed by the caller. When
    SCRUBBER_ENABLED=true, this function enforces that metadata contains a
    non-empty 'vault_id' — mirroring the tracer.py hardening pattern.

    Args:
        workload_id: AI workload identifier (e.g., 'financial_advisor').
        prompt:      Pre-scrubbed prompt text.
        response:    Pre-scrubbed response text.
        outcome:     One of 'success', 'failure', 'review'.
        metadata:    Optional dict. May include: vault_id, trace_id, eval_scores,
                     guardrail_result. vault_id is required when SCRUBBER_ENABLED.
        ttl_seconds: Override default TTL. Defaults to EPISODE_TTL_SECONDS env (30 days).

    Returns:
        episode_id as a UUID string.

    Raises:
        ValueError: if SCRUBBER_ENABLED=true and metadata lacks vault_id.
    """
    from providers import get_memory_backend
    backend = get_memory_backend()
    return backend.write(
        workload_id=workload_id,
        prompt=prompt,
        response=response,
        outcome=outcome,
        metadata=metadata or {},
        ttl_seconds=ttl_seconds if ttl_seconds is not None else 0,
    )


def build_context(
    workload_id: str,
    lookback_days: int = 7,
    include_rag: bool = True,
    include_procedural: bool = True,
    max_episodes: int = 10,
) -> str:
    """Assemble a multi-tier context string from T2 + T3 + T4.

    Sections returned (clearly labeled):
      [T2: EPISODIC MEMORY]   — recent Postgres episodes (scrubbed text)
      [T3: RAG CORPUS]        — top-k matches from domain/rag_engine.search_corpus
      [T4: PROCEDURAL MEMORY] — domain definition from domains.load_domain

    Args:
        workload_id:       Workload identifier; used as domain name for T4 lookup.
        lookback_days:     How many days back to pull T2 episodes (default 7).
        include_rag:       Whether to include T3 RAG results (default True).
        include_procedural: Whether to include T4 procedural domain def (default True).
        max_episodes:      Maximum number of T2 episodes to include (default 10).

    Returns:
        Single string with all sections. Empty string on total failure.
    """
    start = datetime.now(timezone.utc)
    logger.info(
        "build_context: entry",
        extra={
            "workload_id": workload_id,
            "lookback_days": lookback_days,
            "include_rag": include_rag,
            "include_procedural": include_procedural,
        },
    )

    sections: list[str] = []

    # ------------------------------------------------------------------
    # T2 — Episodic (Postgres)
    # ------------------------------------------------------------------
    t2_header = "[T2: EPISODIC MEMORY]"
    if not _MEMORY_ENABLED or _engine is None:
        sections.append(f"{t2_header}\n(episodic memory unavailable)")
    else:
        try:
            from sqlalchemy import text

            cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)

            query = text(
                """
                SELECT episode_id, timestamp, prompt, response, outcome,
                       compressed_summary, eval_scores, guardrail_result
                FROM episodes
                WHERE workload_id = :workload_id
                  AND timestamp >= :cutoff
                  AND expires_at > NOW()
                ORDER BY timestamp DESC
                LIMIT :max_episodes
                """
            )

            with _engine.connect() as conn:
                rows = conn.execute(
                    query,
                    {
                        "workload_id": workload_id,
                        "cutoff": cutoff,
                        "max_episodes": max_episodes,
                    },
                ).fetchall()

            if not rows:
                sections.append(f"{t2_header}\n(no recent episodes)")
            else:
                episode_lines: list[str] = []
                for row in rows:
                    # SELECT order: episode_id[0], timestamp[1], prompt[2],
                    #               response[3], outcome[4], compressed_summary[5]
                    summary = row[5]  # compressed_summary
                    ts_label = row[1].isoformat() if row[1] else ""
                    if summary:
                        episode_lines.append(
                            f"  [{ts_label}] outcome={row[4]} summary={summary}"
                        )
                    else:
                        prompt_snippet = (row[2] or "")[:120]
                        response_snippet = (row[3] or "")[:120]
                        episode_lines.append(
                            f"  [{ts_label}] outcome={row[4]}\n"
                            f"    prompt: {prompt_snippet}\n"
                            f"    response: {response_snippet}"
                        )

                sections.append(f"{t2_header}\n" + "\n".join(episode_lines))

        except Exception as exc:
            logger.error(f"build_context: T2 query failed: {exc}", exc_info=True)
            sections.append(f"{t2_header}\n(error fetching episodes)")

    # ------------------------------------------------------------------
    # T3 — RAG corpus (domain/rag_engine.search_corpus)
    # ------------------------------------------------------------------
    if include_rag:
        t3_header = "[T3: RAG CORPUS]"
        try:
            from domain.rag_engine import search_corpus  # type: ignore[import]

            rag_results = search_corpus(workload_id, top_k=5)
            if not rag_results:
                sections.append(f"{t3_header}\n(no corpus matches)")
            else:
                rag_lines: list[str] = []
                for i, hit in enumerate(rag_results, start=1):
                    content = hit.get("content", hit.get("text", ""))[:200]
                    score = hit.get("score", hit.get("relevance", ""))
                    rag_lines.append(f"  [{i}] score={score} {content}")
                sections.append(f"{t3_header}\n" + "\n".join(rag_lines))
        except ImportError:
            logger.warning("build_context: domain.rag_engine not available (expected in parallel build)")
            sections.append("[T3: RAG CORPUS]\n(rag_engine module not yet available)")
        except Exception as exc:
            logger.error(f"build_context: T3 RAG search failed: {exc}", exc_info=True)
            sections.append("[T3: RAG CORPUS]\n(error fetching RAG results)")

    # ------------------------------------------------------------------
    # T4 — Procedural (domains.load_domain)
    # ------------------------------------------------------------------
    if include_procedural:
        t4_header = "[T4: PROCEDURAL MEMORY]"
        try:
            from domains import load_domain

            domain = load_domain(workload_id)
            domain_lines: list[str] = [
                f"  name: {domain.name}",
                f"  description: {domain.description}",
            ]
            if domain.context:
                context_snippet = "; ".join(str(c)[:80] for c in domain.context[:5])
                domain_lines.append(f"  regulatory_context: {context_snippet}")
            if domain.eval_weights:
                domain_lines.append(f"  eval_weights: {domain.eval_weights}")
            sections.append(f"{t4_header}\n" + "\n".join(domain_lines))
        except FileNotFoundError:
            logger.debug(f"build_context: no domain definition for workload_id={workload_id}")
            sections.append(f"[T4: PROCEDURAL MEMORY]\n(no domain definition for '{workload_id}')")
        except Exception as exc:
            logger.error(f"build_context: T4 domain load failed: {exc}", exc_info=True)
            sections.append("[T4: PROCEDURAL MEMORY]\n(error loading domain)")

    context_str = "\n\n".join(sections)
    elapsed_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
    logger.info(
        "build_context: exit",
        extra={
            "workload_id": workload_id,
            "sections": len(sections),
            "total_chars": len(context_str),
            "elapsed_ms": elapsed_ms,
        },
    )
    return context_str


def compress_episode(workload_id: str, episode_id: str) -> str:
    """Summarize a single episode to a 1-2 sentence compressed summary.

    Uses a heuristic approach (truncation + key metadata extraction) — no Claude
    API call. The compressed_summary column in Postgres is updated in-place.
    Phase 5 will replace this with LLM-based compression.

    Args:
        workload_id: Workload identifier (used for logging context).
        episode_id:  UUID of the episode to compress.

    Returns:
        The compressed summary string. Returns empty string if episode not found
        or engine unavailable.
    """
    logger.info(
        "compress_episode: entry",
        extra={"workload_id": workload_id, "episode_id": episode_id},
    )

    if not _MEMORY_ENABLED or _engine is None:
        logger.warning("compress_episode: memory unavailable — returning empty")
        return ""

    try:
        from sqlalchemy import text

        select_sql = text(
            """
            SELECT prompt, response, outcome, timestamp, eval_scores
            FROM episodes
            WHERE episode_id = :episode_id
              AND workload_id = :workload_id
            """
        )

        with _engine.connect() as conn:
            row = conn.execute(
                select_sql,
                {"episode_id": episode_id, "workload_id": workload_id},
            ).fetchone()

        if row is None:
            logger.warning(
                f"compress_episode: episode not found — id={episode_id}, workload={workload_id}"
            )
            return ""

        prompt_text: str = row[0] or ""
        response_text: str = row[1] or ""
        outcome: str = row[2] or ""
        timestamp: datetime = row[3]
        eval_scores = row[4]

        # Heuristic compression: truncate prompt + response to 200 chars combined
        combined = (prompt_text + " " + response_text).strip()
        truncated = combined[:200].rstrip()
        if len(combined) > 200:
            truncated += "..."

        ts_str = timestamp.strftime("%Y-%m-%dT%H:%M:%SZ") if timestamp else "unknown"
        summary_parts = [f"[{ts_str}] outcome={outcome}: {truncated}"]

        if eval_scores and isinstance(eval_scores, dict):
            score_items = ", ".join(f"{k}={v}" for k, v in list(eval_scores.items())[:3])
            summary_parts.append(f"eval=({score_items})")

        summary = " | ".join(summary_parts)

        # Persist to compressed_summary column
        update_sql = text(
            """
            UPDATE episodes
            SET compressed_summary = :summary
            WHERE episode_id = :episode_id
            """
        )

        with _engine.begin() as conn:
            conn.execute(update_sql, {"summary": summary, "episode_id": episode_id})

        logger.info(
            "compress_episode: exit",
            extra={
                "episode_id": episode_id,
                "summary_len": len(summary),
            },
        )
        return summary

    except Exception as exc:
        logger.error(
            f"compress_episode: failed for episode_id={episode_id}: {exc}",
            exc_info=True,
        )
        return ""


def selective_recall(
    workload_id: str,
    query: str,
    top_k: int = 5,
    lookback_days: int = 30,
) -> list[dict]:
    """Search episodes by full-text match using Postgres tsvector.

    Uses parameterized queries exclusively — no f-string SQL. The full-text
    index (gin/tsvector) covers the combined prompt + response columns.

    Args:
        workload_id:   Workload to search within.
        query:         Search terms (plain English — passed to plainto_tsquery).
        top_k:         Maximum results to return (default 5).
        lookback_days: How many days back to search (default 30).

    Returns:
        List of episode dicts ranked by FTS relevance, newest first on ties.
        Empty list if engine unavailable or no matches.
    """
    logger.info(
        "selective_recall: entry",
        extra={"workload_id": workload_id, "query_preview": query[:50], "top_k": top_k},
    )

    if not _MEMORY_ENABLED or _engine is None:
        logger.warning("selective_recall: memory unavailable — returning empty list")
        return []

    if not query or not query.strip():
        return []

    try:
        from sqlalchemy import text

        cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)

        fts_query = text(
            """
            SELECT
                episode_id,
                workload_id,
                timestamp,
                prompt,
                response,
                outcome,
                vault_id,
                trace_id,
                eval_scores,
                guardrail_result,
                metadata,
                compressed_summary,
                expires_at,
                ts_rank(
                    to_tsvector('english', prompt || ' ' || response),
                    plainto_tsquery('english', :query)
                ) AS rank
            FROM episodes
            WHERE workload_id = :workload_id
              AND timestamp >= :cutoff
              AND expires_at > NOW()
              AND to_tsvector('english', prompt || ' ' || response)
                  @@ plainto_tsquery('english', :query)
            ORDER BY rank DESC, timestamp DESC
            LIMIT :top_k
            """
        )

        with _engine.connect() as conn:
            rows = conn.execute(
                fts_query,
                {
                    "workload_id": workload_id,
                    "query": query,
                    "cutoff": cutoff,
                    "top_k": top_k,
                },
            ).fetchall()

        results: list[dict] = []
        for row in rows:
            results.append(
                {
                    "episode_id": str(row[0]),
                    "workload_id": str(row[1]),
                    "timestamp": row[2].isoformat() if row[2] else None,
                    "prompt": row[3],
                    "response": row[4],
                    "outcome": row[5],
                    "vault_id": row[6],
                    "trace_id": row[7],
                    "eval_scores": row[8],
                    "guardrail_result": row[9],
                    "metadata": row[10],
                    "compressed_summary": row[11],
                    "expires_at": row[12].isoformat() if row[12] else None,
                    "fts_rank": float(row[13]),
                }
            )

        logger.info(
            "selective_recall: exit",
            extra={"workload_id": workload_id, "hits": len(results)},
        )
        return results

    except Exception as exc:
        logger.error(
            f"selective_recall: query failed for workload={workload_id}: {exc}",
            exc_info=True,
        )
        return []


def list_episodes(
    workload_id: str,
    limit: int = 50,
    lookback_days: int = 30,
) -> list[dict]:
    """List recent episodes for a workload, newest first (no search filtering).

    Used by the memory browser UI to display a chronological feed of
    interactions. Excludes expired episodes (expires_at <= NOW()).

    Args:
        workload_id:   Workload to list episodes for.
        limit:         Maximum episodes to return (default 50).
        lookback_days: How many days back to include (default 30).

    Returns:
        List of episode dicts ordered by timestamp DESC.
        Empty list if engine unavailable.
    """
    logger.info(
        "list_episodes: entry",
        extra={"workload_id": workload_id, "limit": limit, "lookback_days": lookback_days},
    )

    if not _MEMORY_ENABLED or _engine is None:
        logger.warning("list_episodes: memory unavailable — returning empty list")
        return []

    try:
        from sqlalchemy import text

        cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)

        list_query = text(
            """
            SELECT
                episode_id,
                workload_id,
                timestamp,
                prompt,
                response,
                outcome,
                vault_id,
                trace_id,
                eval_scores,
                guardrail_result,
                metadata,
                compressed_summary,
                expires_at
            FROM episodes
            WHERE workload_id = :workload_id
              AND timestamp >= :cutoff
              AND expires_at > NOW()
            ORDER BY timestamp DESC
            LIMIT :limit
            """
        )

        with _engine.connect() as conn:
            rows = conn.execute(
                list_query,
                {
                    "workload_id": workload_id,
                    "cutoff": cutoff,
                    "limit": limit,
                },
            ).fetchall()

        results: list[dict] = []
        for row in rows:
            results.append(
                {
                    "episode_id": str(row[0]),
                    "workload_id": str(row[1]),
                    "timestamp": row[2].isoformat() if row[2] else None,
                    "prompt": row[3],
                    "response": row[4],
                    "outcome": row[5],
                    "vault_id": row[6],
                    "trace_id": row[7],
                    "eval_scores": row[8],
                    "guardrail_result": row[9],
                    "metadata": row[10],
                    "compressed_summary": row[11],
                    "expires_at": row[12].isoformat() if row[12] else None,
                }
            )

        logger.info(
            "list_episodes: exit",
            extra={"workload_id": workload_id, "count": len(results)},
        )
        return results

    except Exception as exc:
        logger.error(
            f"list_episodes: query failed for workload={workload_id}: {exc}",
            exc_info=True,
        )
        return []


def memory_stats() -> dict:
    """Return aggregate memory statistics across all episodes.

    Returns:
        Dict with keys:
          total_episodes       — int
          episodes_by_workload — dict[workload_id, count]
          oldest_episode       — ISO timestamp string or None
          expired_count        — int (already-expired rows not yet purged)
          ttl_default_seconds  — int (current EPISODE_TTL_SECONDS)
    """
    logger.info("memory_stats: entry")

    empty: dict = {
        "total_episodes": 0,
        "episodes_by_workload": {},
        "oldest_episode": None,
        "expired_count": 0,
        "ttl_default_seconds": _EPISODE_TTL_SECONDS,
    }

    if not _MEMORY_ENABLED or _engine is None:
        logger.warning("memory_stats: memory unavailable — returning zeros")
        return empty

    try:
        from sqlalchemy import text

        stats_sql = text(
            """
            SELECT
                COUNT(*)                                          AS total_episodes,
                MIN(timestamp)                                    AS oldest_episode,
                SUM(CASE WHEN expires_at < NOW() THEN 1 ELSE 0 END) AS expired_count
            FROM episodes
            """
        )

        by_workload_sql = text(
            """
            SELECT workload_id, COUNT(*) AS cnt
            FROM episodes
            GROUP BY workload_id
            ORDER BY cnt DESC
            """
        )

        with _engine.connect() as conn:
            stats_row = conn.execute(stats_sql).fetchone()
            workload_rows = conn.execute(by_workload_sql).fetchall()

        total = int(stats_row[0]) if stats_row and stats_row[0] is not None else 0
        oldest = stats_row[1].isoformat() if stats_row and stats_row[1] is not None else None
        expired = int(stats_row[2]) if stats_row and stats_row[2] is not None else 0

        by_workload: dict[str, int] = {
            str(r[0]): int(r[1]) for r in workload_rows
        }

        result = {
            "total_episodes": total,
            "episodes_by_workload": by_workload,
            "oldest_episode": oldest,
            "expired_count": expired,
            "ttl_default_seconds": _EPISODE_TTL_SECONDS,
        }

        logger.info(
            "memory_stats: exit",
            extra={"total_episodes": total, "expired_count": expired},
        )
        return result

    except Exception as exc:
        logger.error(f"memory_stats: failed: {exc}", exc_info=True)
        return empty


def purge_episodes(
    subject_id: str,
    workload_id: str | None = None,
) -> dict:
    """Tombstone episodic memory rows belonging to *subject_id*.

    Scans the ``episodes`` Postgres table (or all ``data/episodes_*.jsonl``
    files when Postgres is unavailable) for rows whose ``metadata`` JSON
    contains ``subject_id`` equal to *subject_id*.

    When *workload_id* is provided, only episodes for that workload are
    considered; otherwise all workloads are searched.

    Tombstoning is implemented via an UPDATE that sets
    ``compressed_summary = 'PURGED'`` and clears ``prompt`` / ``response``
    columns so the row is no longer queryable through normal read paths.
    A ``T2_EPISODE_PURGED`` audit event is emitted via ``append_agent_event``
    for every purged episode (which flows through the hash chain).

    When the Postgres engine is unavailable (dev/test), the function falls back
    to scanning ``data/episodes_*.jsonl`` and appending tombstone records.

    Args:
        subject_id:  Identifier of the data subject to purge.
        workload_id: Optional workload scope.  None = purge across all workloads.

    Returns:
        Dict with keys:

        * ``episodes_removed`` — number of episodes tombstoned.
        * ``sha256_digest_after`` — SHA-256 of ``"purged:<subject_id>:<count>"``.
    """
    import hashlib
    import json as _json
    from pathlib import Path as _Path

    logger.info(
        "purge_episodes: entry subject_id=%s workload_id=%s",
        subject_id, workload_id,
    )

    from domain.repository import append_agent_event  # late import — avoids circular

    purged_count = 0

    # ------------------------------------------------------------------
    # Postgres path
    # ------------------------------------------------------------------
    if _engine is not None:
        try:
            from sqlalchemy import text

            # Build filter clause using JSONB extraction operator to avoid
            # false-positive purges from short subject_ids that are substrings
            # of other fields (Session 10 debt fix -- replaces LIKE %subject_id%).
            # Uses idx_episodes_subject_id index (created in schema bootstrap below).
            if workload_id:
                select_sql = text(
                    """
                    SELECT episode_id, workload_id
                    FROM episodes
                    WHERE workload_id = :workload_id
                      AND metadata->>'subject_id' = :subject_id
                    """
                )
                rows = []
                with _engine.connect() as conn:
                    rows = conn.execute(
                        select_sql,
                        {
                            "workload_id": workload_id,
                            "subject_id": subject_id,
                        },
                    ).fetchall()
            else:
                select_sql = text(
                    """
                    SELECT episode_id, workload_id
                    FROM episodes
                    WHERE metadata->>'subject_id' = :subject_id
                    """
                )
                with _engine.connect() as conn:
                    rows = conn.execute(
                        select_sql,
                        {"subject_id": subject_id},
                    ).fetchall()

            purge_sql = text(
                """
                UPDATE episodes
                SET prompt = 'PURGED',
                    response = 'PURGED',
                    compressed_summary = 'PURGED',
                    metadata = NULL
                WHERE episode_id = :episode_id
                """
            )

            for row in rows:
                episode_id_val = str(row[0])
                wid = str(row[1])
                with _engine.begin() as conn:
                    conn.execute(purge_sql, {"episode_id": episode_id_val})

                append_agent_event("T2_EPISODE_PURGED", {
                    "subject_id": subject_id,
                    "episode_id": episode_id_val,
                    "workload_id": wid,
                })
                purged_count += 1

            logger.info(
                "purge_episodes: Postgres path complete subject_id=%s purged=%d",
                subject_id, purged_count,
            )

        except Exception as exc:
            logger.error(
                "purge_episodes: Postgres purge failed subject_id=%s: %s",
                subject_id, exc, exc_info=True,
            )
            raise

    else:
        # ------------------------------------------------------------------
        # JSONL fallback path (dev / no Postgres)
        # ------------------------------------------------------------------
        data_dir = _Path(__file__).resolve().parents[1] / "data"
        pattern = "episodes_*.jsonl"
        if workload_id:
            pattern = f"episodes_{workload_id}.jsonl"

        import json as _json2

        for ep_file in sorted(data_dir.glob(pattern)):
            if not ep_file.exists():
                continue

            try:
                with ep_file.open("r", encoding="utf-8") as fh:
                    lines = fh.readlines()

                kept_lines: list[str] = []
                file_purged = 0
                for line in lines:
                    raw = line.strip()
                    if not raw:
                        continue
                    try:
                        record = _json2.loads(raw)
                    except _json2.JSONDecodeError:
                        kept_lines.append(raw)
                        continue

                    meta = record.get("metadata") or {}
                    if isinstance(meta, str):
                        try:
                            meta = _json2.loads(meta)
                        except Exception:  # noqa: BLE001
                            meta = {}

                    is_match = (
                        meta.get("subject_id") == subject_id
                        or record.get("subject_id") == subject_id
                    )
                    is_prior_tombstone = (
                        record.get("op") == "PURGE"
                        and record.get("subject_id") == subject_id
                    )

                    if is_match or is_prior_tombstone:
                        # Genuine erasure: drop the record from the compacted file.
                        if is_match and record.get("op") != "PURGE":
                            file_purged += 1
                            append_agent_event("T2_EPISODE_PURGED", {
                                "subject_id": subject_id,
                                "episode_id": record.get("episode_id", ""),
                                "workload_id": record.get("workload_id", ep_file.stem),
                                "source": "jsonl_fallback",
                            })
                        continue

                    kept_lines.append(raw)

                if file_purged > 0:
                    # Append a non-PII tombstone marker for the audit trail
                    kept_lines.append(_json2.dumps({
                        "op": "PURGE",
                        "subject_id": subject_id,
                        "episodes_purged_count": file_purged,
                        "ts": datetime.now(timezone.utc).isoformat(),
                    }))
                    tmp = ep_file.with_suffix(ep_file.suffix + ".tmp")
                    with tmp.open("w", encoding="utf-8") as fout:
                        for ln in kept_lines:
                            fout.write(ln + "\n")
                    tmp.replace(ep_file)

                purged_count += file_purged

            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "purge_episodes: JSONL fallback failed for file=%s: %s",
                    ep_file.name, exc,
                )

        logger.info(
            "purge_episodes: JSONL fallback complete subject_id=%s purged=%d",
            subject_id, purged_count,
        )

    digest = hashlib.sha256(
        f"purged:{subject_id}:{purged_count}".encode("utf-8")
    ).hexdigest()

    logger.info(
        "purge_episodes: exit subject_id=%s episodes_removed=%d digest=%s…",
        subject_id, purged_count, digest[:12],
    )
    return {
        "episodes_removed": purged_count,
        "sha256_digest_after": digest,
    }


def purge_expired() -> int:
    """Delete all episodes where expires_at < NOW(). Returns count purged.

    Designed to be called from a scheduled cron job (Session 10). Safe to call
    at any time — idempotent, row-level deletes only.

    Returns:
        Number of rows deleted. 0 if engine unavailable.
    """
    logger.info("purge_expired: entry")

    if not _MEMORY_ENABLED or _engine is None:
        logger.warning("purge_expired: memory unavailable — returning 0")
        return 0

    try:
        from sqlalchemy import text

        delete_sql = text(
            """
            DELETE FROM episodes
            WHERE expires_at < NOW()
            """
        )

        with _engine.begin() as conn:
            result = conn.execute(delete_sql)
            purged = result.rowcount

        logger.info(
            "purge_expired: exit",
            extra={"purged": purged},
        )
        return purged

    except Exception as exc:
        logger.error(f"purge_expired: failed: {exc}", exc_info=True)
        return 0
