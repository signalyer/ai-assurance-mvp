"""Read-side event projection — dispatches events to Postgres materialized tables.

ARCHITECTURAL INVARIANT:
  This module is READ-ONLY with respect to data/events.jsonl.
  It NEVER calls _append_jsonl, NEVER writes to events.jsonl, and
  NEVER reads from vault.jsonl or joins raw_prompt fields.
  Postgres tables are a downstream replica; JSONL is the source of truth.

Every upsert is idempotent: the event_id is recorded in projection_state
inside the same transaction. Replaying the same event twice is a no-op.

Supported event_type → table mappings:
  AGENT_CREATED            → ai_systems
  AGENT_PUBLISHED          → ai_systems (upsert name/owner from payload)
  EVAL_RUN_STARTED         → eval_runs (status=running)
  EVAL_RUN_COMPLETED       → eval_runs (status=passed|failed, pass_rate, metrics)
  FINDING_CREATED          → findings
  FINDING_STATUS_CHANGED   → findings (status column update)
  RELEASE_DECISION_RECORDED→ release_decisions
  POLICY_EVALUATED         → policy_evaluations
  RTF_CASCADE_COMPLETED    → findings (synthetic finding row for audit)
  RTF_CASCADE_STARTED      → findings (synthetic finding row for audit)

All other event_types are recorded in projection_state (idempotency) but
do not produce rows in the domain tables.

Environment variables:
  DATABASE_URL   Full Postgres connection string. If absent the module
                 still imports cleanly; project_event raises RuntimeError.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Whitelisted view names — used by api/projection.py for SQL-injection guard
# ---------------------------------------------------------------------------

PROJECTION_VIEWS: frozenset[str] = frozenset(
    {"ai_systems", "eval_runs", "findings", "release_decisions", "policy_evaluations"}
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _now_utc() -> str:
    """Return current UTC timestamp as ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _jsonb(val: Any) -> str:
    """Serialise *val* to a compact JSON string for psycopg2 JSONB parameters."""
    return json.dumps(val, default=str)


def _already_projected(event_id: str, conn: Any) -> bool:
    """Return True if *event_id* is already recorded in projection_state.

    Args:
        event_id: The UUID string from the audit-chain event.
        conn:     An open psycopg2 connection (autocommit=False).

    Returns:
        True if the event has been projected before; False otherwise.
    """
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM projection_state WHERE event_id = %s", (event_id,))
    row = cur.fetchone()
    cur.close()
    return row is not None


def _mark_projected(event_id: str, conn: Any) -> None:
    """Insert *event_id* into projection_state (idempotent).

    Callers must hold an open transaction and commit/rollback themselves.

    Args:
        event_id: The UUID string from the audit-chain event.
        conn:     An open psycopg2 connection (autocommit=False).
    """
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO projection_state (event_id, projected_at) VALUES (%s, %s)"
        " ON CONFLICT (event_id) DO NOTHING",
        (event_id, _now_utc()),
    )
    cur.close()


# ---------------------------------------------------------------------------
# Per-table upsert handlers
# ---------------------------------------------------------------------------


def _upsert_ai_system(event: dict, conn: Any) -> None:
    """Upsert a row in ai_systems from an AGENT_CREATED or AGENT_PUBLISHED event.

    Args:
        event: The full audit-chain event dict.
        conn:  Open psycopg2 connection inside an active transaction.
    """
    cur = conn.cursor()
    system_id: str = event.get("agent_id") or event.get("system_id") or event.get("event_id", "")
    name: str | None = event.get("name") or event.get("agent_id")
    owner: str | None = event.get("owner") or event.get("team")
    risk_tier: str | None = event.get("risk_tier") or event.get("risk_level")
    created_at: str | None = event.get("ts") or _now_utc()
    metadata: str = _jsonb({k: v for k, v in event.items()
                            if k not in {"event_id", "event_type", "ts", "hash", "prev_hash"}})

    cur.execute(
        """
        INSERT INTO ai_systems (system_id, name, owner, risk_tier, created_at, metadata)
        VALUES (%s, %s, %s, %s, %s, %s::jsonb)
        ON CONFLICT (system_id) DO UPDATE SET
            name      = COALESCE(EXCLUDED.name, ai_systems.name),
            owner     = COALESCE(EXCLUDED.owner, ai_systems.owner),
            risk_tier = COALESCE(EXCLUDED.risk_tier, ai_systems.risk_tier),
            metadata  = ai_systems.metadata || EXCLUDED.metadata
        """,
        (system_id, name, owner, risk_tier, created_at, metadata),
    )
    cur.close()
    logger.debug("projection: upserted ai_systems system_id=%s", system_id)


def _upsert_eval_run(event: dict, conn: Any, status_override: str | None = None) -> None:
    """Upsert a row in eval_runs from an EVAL_RUN_* event.

    Args:
        event:           The full audit-chain event dict.
        conn:            Open psycopg2 connection inside an active transaction.
        status_override: If provided, use this as the status column value.
    """
    cur = conn.cursor()
    run_id: str = event.get("run_id") or event.get("event_id", "")
    system_id: str | None = event.get("system_id") or event.get("agent_id")
    status: str = status_override or event.get("status", "unknown")
    pass_rate = event.get("pass_rate")
    started_at: str | None = event.get("started_at") or event.get("ts")
    finished_at: str | None = event.get("finished_at")
    metrics: str = _jsonb(event.get("metrics") or {})

    cur.execute(
        """
        INSERT INTO eval_runs (run_id, system_id, status, pass_rate, started_at, finished_at, metrics)
        VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
        ON CONFLICT (run_id) DO UPDATE SET
            status      = EXCLUDED.status,
            pass_rate   = COALESCE(EXCLUDED.pass_rate, eval_runs.pass_rate),
            finished_at = COALESCE(EXCLUDED.finished_at, eval_runs.finished_at),
            metrics     = eval_runs.metrics || EXCLUDED.metrics
        """,
        (run_id, system_id, status, pass_rate, started_at, finished_at, metrics),
    )
    cur.close()
    logger.debug("projection: upserted eval_runs run_id=%s status=%s", run_id, status)


def _upsert_finding(event: dict, conn: Any) -> None:
    """Upsert a row in findings from a FINDING_* or RTF_* event.

    Args:
        event: The full audit-chain event dict.
        conn:  Open psycopg2 connection inside an active transaction.
    """
    cur = conn.cursor()
    finding_id: str = (
        event.get("finding_id")
        or event.get("cascade_id")
        or event.get("event_id", "")
    )
    system_id: str | None = event.get("system_id") or event.get("agent_id")
    severity: str | None = event.get("severity")
    status: str = event.get("status") or event.get("event_type", "OPEN")
    created_at: str | None = event.get("created_at") or event.get("ts")
    payload: str = _jsonb({k: v for k, v in event.items()
                           if k not in {"event_id", "event_type", "ts", "hash", "prev_hash"}})

    cur.execute(
        """
        INSERT INTO findings (finding_id, system_id, severity, status, created_at, payload)
        VALUES (%s, %s, %s, %s, %s, %s::jsonb)
        ON CONFLICT (finding_id) DO UPDATE SET
            status   = EXCLUDED.status,
            severity = COALESCE(EXCLUDED.severity, findings.severity),
            payload  = findings.payload || EXCLUDED.payload
        """,
        (finding_id, system_id, severity, status, created_at, payload),
    )
    cur.close()
    logger.debug("projection: upserted findings finding_id=%s", finding_id)


def _upsert_release_decision(event: dict, conn: Any) -> None:
    """Upsert a row in release_decisions from a RELEASE_DECISION_RECORDED event.

    Args:
        event: The full audit-chain event dict.
        conn:  Open psycopg2 connection inside an active transaction.
    """
    cur = conn.cursor()
    decision_id: str = event.get("decision_id") or event.get("event_id", "")
    system_id: str | None = event.get("system_id") or event.get("agent_id")
    decision: str | None = event.get("decision")
    decided_at: str | None = event.get("decided_at") or event.get("ts")
    gate_results: str = _jsonb(event.get("gate_results") or {})

    cur.execute(
        """
        INSERT INTO release_decisions (decision_id, system_id, decision, decided_at, gate_results)
        VALUES (%s, %s, %s, %s, %s::jsonb)
        ON CONFLICT (decision_id) DO UPDATE SET
            decision     = COALESCE(EXCLUDED.decision, release_decisions.decision),
            gate_results = release_decisions.gate_results || EXCLUDED.gate_results
        """,
        (decision_id, system_id, decision, decided_at, gate_results),
    )
    cur.close()
    logger.debug("projection: upserted release_decisions decision_id=%s", decision_id)


def _upsert_policy_evaluation(event: dict, conn: Any) -> None:
    """Upsert a row in policy_evaluations from a POLICY_EVALUATED event.

    Args:
        event: The full audit-chain event dict.
        conn:  Open psycopg2 connection inside an active transaction.
    """
    cur = conn.cursor()
    eval_id: str = event.get("eval_id") or event.get("event_id", "")
    system_id: str | None = event.get("system_id") or event.get("agent_id")
    category: str | None = event.get("category")
    decision: str | None = event.get("decision")
    evaluated_at: str | None = event.get("evaluated_at") or event.get("ts")
    inputs: str = _jsonb(event.get("inputs") or {})

    cur.execute(
        """
        INSERT INTO policy_evaluations (eval_id, system_id, category, decision, evaluated_at, inputs)
        VALUES (%s, %s, %s, %s, %s, %s::jsonb)
        ON CONFLICT (eval_id) DO UPDATE SET
            decision = COALESCE(EXCLUDED.decision, policy_evaluations.decision),
            inputs   = policy_evaluations.inputs || EXCLUDED.inputs
        """,
        (eval_id, system_id, category, decision, evaluated_at, inputs),
    )
    cur.close()
    logger.debug("projection: upserted policy_evaluations eval_id=%s", eval_id)


# ---------------------------------------------------------------------------
# Dispatch table (removed in Session 10 -- was dead code alongside _dispatch()
# if/elif body; the if/elif body is the single source of truth).
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def project_event(event: dict, conn: Any) -> None:
    """Project a single audit-chain event into the appropriate Postgres table.

    The function is idempotent: if the event_id already appears in
    projection_state the function returns immediately without touching any
    domain table.  The idempotency record and the domain upsert are committed
    in a single transaction.

    Args:
        event: Full audit-chain event dict including ``event_id``, ``event_type``,
               ``ts``, ``hash``, ``prev_hash`` and any payload fields.  The
               ``raw_prompt`` field and vault.jsonl are never accessed here.
        conn:  Open psycopg2 connection.  The caller is responsible for
               transaction management (this function calls conn.commit() on
               success and conn.rollback() on error).

    Raises:
        RuntimeError: If DATABASE_URL is not configured and conn is None.
        Exception:    Re-raised after rollback on any upsert failure.
    """
    event_id: str = event.get("event_id", "")
    event_type: str = event.get("event_type", "")

    if not event_id:
        logger.warning("project_event: skipping event with no event_id event_type=%s", event_type)
        return

    logger.debug("project_event: entry event_id=%s event_type=%s", event_id, event_type)

    try:
        # Fast idempotency check — no transaction needed for the read
        if _already_projected(event_id, conn):
            logger.debug("project_event: already projected event_id=%s — skipping", event_id)
            return

        # Dispatch to the correct handler, then record idempotency marker
        _dispatch(event_type, event, conn)
        _mark_projected(event_id, conn)
        conn.commit()

        logger.debug("project_event: exit event_id=%s event_type=%s committed", event_id, event_type)

    except Exception:
        # Wrap rollback in its own try/except so a secondary rollback failure
        # does not replace the original exception (Session 10 debt fix).
        try:
            conn.rollback()
        except Exception as _rb_exc:  # noqa: BLE001
            logger.warning(
                "project_event: rollback failed event_id=%s: %s", event_id, _rb_exc
            )
        logger.exception(
            "project_event: rollback event_id=%s event_type=%s", event_id, event_type
        )
        raise


def _dispatch(event_type: str, event: dict, conn: Any) -> None:
    """Route *event* to the correct upsert handler based on *event_type*.

    Unknown event types are silently ignored (projection_state still records
    the event_id for idempotency via the caller in :func:`project_event`).

    Args:
        event_type: The ``event_type`` field from the audit-chain record.
        event:      The full event dict.
        conn:       Open psycopg2 connection inside an active transaction.
    """
    if event_type in ("AGENT_CREATED", "AGENT_PUBLISHED"):
        _upsert_ai_system(event, conn)
    elif event_type == "EVAL_RUN_STARTED":
        _upsert_eval_run(event, conn, status_override="running")
    elif event_type == "EVAL_RUN_COMPLETED":
        status = "passed" if (event.get("pass_rate") or 0) >= 0.8 else "failed"
        _upsert_eval_run(event, conn, status_override=status)
    elif event_type in ("FINDING_CREATED", "FINDING_STATUS_CHANGED",
                        "RTF_CASCADE_STARTED", "RTF_CASCADE_COMPLETED"):
        _upsert_finding(event, conn)
    elif event_type == "RELEASE_DECISION_RECORDED":
        _upsert_release_decision(event, conn)
    elif event_type == "POLICY_EVALUATED":
        _upsert_policy_evaluation(event, conn)
    else:
        logger.debug(
            "_dispatch: no handler for event_type=%s — recording in projection_state only",
            event_type,
        )


__all__ = [
    "project_event",
    "PROJECTION_VIEWS",
]
