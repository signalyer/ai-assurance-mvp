"""Agent subscriber tracking — subscribe, unsubscribe, and notify on publish.

REUSABLE agents support org-wide subscriptions.  When a new version is published
domain.agents.publish_version calls notify_subscribers_on_publish here.

For each unpinned binding of a subscriber, upgrade_available_version_id is set
on the agent_bindings row.  The Postgres LISTEN client lives in the API layer
(Implementer 2); this module is the NOTIFY producer and subscriber state manager.

Primary storage: Postgres (agent_subscribers table).
Audit trail: data/events.jsonl via domain.repository.append_agent_event.

Security:
  - All SQL parameterized.
  - DB errors logged and re-raised.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from domain.models import AgentSubscriber

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Engine — mirrors agent_memory.py pattern
# ---------------------------------------------------------------------------

_DATABASE_URL: Optional[str] = os.getenv("DATABASE_URL")
_engine = None  # type: ignore[assignment]

if _DATABASE_URL:
    try:
        from sqlalchemy import create_engine as _create_engine

        _engine = _create_engine(
            _DATABASE_URL,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            pool_recycle=1800,
            connect_args={"connect_timeout": 5},
        )
        logger.info("agent_subscribers: SQLAlchemy engine created")
    except Exception as _exc:
        logger.warning(f"agent_subscribers: failed to create engine: {_exc}")
        _engine = None
else:
    logger.warning("agent_subscribers: DATABASE_URL not set — Postgres unavailable")

# ---------------------------------------------------------------------------
# Schema bootstrap
# ---------------------------------------------------------------------------

_SUBSCRIBERS_DDL = """
CREATE TABLE IF NOT EXISTS agent_subscribers (
    id                       VARCHAR(128) PRIMARY KEY,
    agent_id                 VARCHAR(128) NOT NULL,
    system_id                VARCHAR(128) NOT NULL,
    subscribed_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_notified_version_id VARCHAR(128),
    UNIQUE (agent_id, system_id)
);

CREATE INDEX IF NOT EXISTS idx_subscribers_agent
    ON agent_subscribers (agent_id);

CREATE INDEX IF NOT EXISTS idx_subscribers_system
    ON agent_subscribers (system_id);
"""


def _init_schema() -> None:
    """Bootstrap agent_subscribers table. Idempotent."""
    if _engine is None:
        return
    try:
        from sqlalchemy import text

        with _engine.begin() as conn:
            conn.execute(text(_SUBSCRIBERS_DDL))
        logger.info("agent_subscribers: schema initialised")
    except Exception as exc:
        logger.error(f"agent_subscribers: schema init failed: {exc}", exc_info=True)


if _engine is not None:
    _init_schema()


# ---------------------------------------------------------------------------
# Row mapping
# ---------------------------------------------------------------------------


def _row_to_subscriber(row: object) -> AgentSubscriber:
    """Convert a SQLAlchemy Row to an AgentSubscriber model."""
    return AgentSubscriber(
        id=row[0],
        agent_id=row[1],
        system_id=row[2],
        subscribed_at=row[3],
        last_notified_version_id=row[4],
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def subscribe(agent_id: str, system_id: str) -> AgentSubscriber:
    """Subscribe a system to upgrade notifications for an agent.

    Idempotent — repeated calls return the existing subscription without error.

    Args:
        agent_id:  FK to Agent.id.
        system_id: FK to AISystem.id (the subscribing system).

    Returns:
        AgentSubscriber instance (new or existing).

    Raises:
        Exception: on database error.
    """
    start = datetime.now(timezone.utc)
    logger.info(
        "subscribe: entry",
        extra={"agent_id": agent_id, "system_id": system_id},
    )

    now = datetime.now(timezone.utc)
    sub_id = f"ai-sub-{uuid.uuid4()}"

    subscriber = AgentSubscriber(
        id=sub_id,
        agent_id=agent_id,
        system_id=system_id,
        subscribed_at=now,
        last_notified_version_id=None,
    )

    if _engine is not None:
        try:
            from sqlalchemy import text

            with _engine.begin() as conn:
                # Upsert — if (agent_id, system_id) already exists, keep existing row
                conn.execute(
                    text(
                        """
                        INSERT INTO agent_subscribers
                            (id, agent_id, system_id, subscribed_at)
                        VALUES
                            (:id, :agent_id, :system_id, :subscribed_at)
                        ON CONFLICT (agent_id, system_id) DO NOTHING
                        """
                    ),
                    {
                        "id": sub_id,
                        "agent_id": agent_id,
                        "system_id": system_id,
                        "subscribed_at": now,
                    },
                )

            # Fetch the actual row (may differ from the one we tried to insert)
            with _engine.connect() as conn:
                row = conn.execute(
                    text(
                        """
                        SELECT id, agent_id, system_id, subscribed_at, last_notified_version_id
                        FROM agent_subscribers
                        WHERE agent_id = :agent_id AND system_id = :system_id
                        """
                    ),
                    {"agent_id": agent_id, "system_id": system_id},
                ).fetchone()

            if row is not None:
                subscriber = _row_to_subscriber(row)

        except Exception as exc:
            logger.error(f"subscribe: DB insert failed: {exc}", exc_info=True)
            raise
    else:
        logger.warning("subscribe: engine unavailable — in-memory only")

    elapsed_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
    logger.info(
        "subscribe: exit",
        extra={"subscriber_id": subscriber.id, "elapsed_ms": elapsed_ms},
    )
    return subscriber


def unsubscribe(agent_id: str, system_id: str) -> None:
    """Remove a system's subscription for an agent.

    No-op if the subscription does not exist.

    Args:
        agent_id:  FK to Agent.id.
        system_id: FK to AISystem.id.

    Raises:
        Exception: on database error.
    """
    logger.info("unsubscribe: entry", extra={"agent_id": agent_id, "system_id": system_id})

    if _engine is None:
        logger.warning("unsubscribe: engine unavailable — no-op")
        return

    try:
        from sqlalchemy import text

        with _engine.begin() as conn:
            conn.execute(
                text(
                    """
                    DELETE FROM agent_subscribers
                    WHERE agent_id = :agent_id AND system_id = :system_id
                    """
                ),
                {"agent_id": agent_id, "system_id": system_id},
            )

        logger.info("unsubscribe: exit", extra={"agent_id": agent_id, "system_id": system_id})

    except Exception as exc:
        logger.error(
            f"unsubscribe: failed for agent_id={agent_id}, system_id={system_id}: {exc}",
            exc_info=True,
        )
        raise


def list_subscribers(agent_id: str) -> list[AgentSubscriber]:
    """Return all subscribers for an agent.

    Args:
        agent_id: FK to Agent.id.

    Returns:
        List of AgentSubscriber instances ordered by subscribed_at.
    """
    logger.info("list_subscribers: entry", extra={"agent_id": agent_id})

    if _engine is None:
        logger.warning("list_subscribers: engine unavailable — returning empty list")
        return []

    try:
        from sqlalchemy import text

        with _engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT id, agent_id, system_id, subscribed_at, last_notified_version_id
                    FROM agent_subscribers
                    WHERE agent_id = :agent_id
                    ORDER BY subscribed_at
                    """
                ),
                {"agent_id": agent_id},
            ).fetchall()

        subscribers = [_row_to_subscriber(r) for r in rows]
        logger.info(
            "list_subscribers: exit",
            extra={"agent_id": agent_id, "count": len(subscribers)},
        )
        return subscribers

    except Exception as exc:
        logger.error(
            f"list_subscribers: query failed for agent_id={agent_id}: {exc}", exc_info=True
        )
        raise


def notify_subscribers_on_publish(agent_id: str, new_version_id: str) -> int:
    """Mark upgrade_available_version_id on all unpinned bindings for subscribers.

    Called by domain.agents.publish_version after a successful publish.
    Pinned bindings (pinned=True) are skipped — the user must manually accept.
    Unpinned bindings get upgrade_available_version_id set to new_version_id.

    Args:
        agent_id:       FK to Agent.id (the agent that was just published).
        new_version_id: FK to AgentVersion.id (the newly published version).

    Returns:
        Count of bindings notified (upgrade_available_version_id set).
    """
    start = datetime.now(timezone.utc)
    logger.info(
        "notify_subscribers_on_publish: entry",
        extra={"agent_id": agent_id, "new_version_id": new_version_id},
    )

    if _engine is None:
        logger.warning("notify_subscribers_on_publish: engine unavailable — returning 0")
        return 0

    try:
        from sqlalchemy import text

        now = datetime.now(timezone.utc)

        with _engine.begin() as conn:
            result = conn.execute(
                text(
                    """
                    UPDATE agent_bindings
                    SET upgrade_available_version_id = :new_version_id,
                        updated_at = :now
                    WHERE agent_id = :agent_id
                      AND pinned = FALSE
                      AND version_id <> :new_version_id
                    """
                ),
                {
                    "new_version_id": new_version_id,
                    "now": now,
                    "agent_id": agent_id,
                },
            )
            notified = result.rowcount

        # Update last_notified_version_id on subscriber rows
        with _engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE agent_subscribers
                    SET last_notified_version_id = :new_version_id
                    WHERE agent_id = :agent_id
                    """
                ),
                {"new_version_id": new_version_id, "agent_id": agent_id},
            )

        from domain.repository import append_agent_event

        append_agent_event(
            "AGENT_SUBSCRIBERS_NOTIFIED",
            {
                "agent_id": agent_id,
                "new_version_id": new_version_id,
                "notified_count": notified,
            },
        )

        elapsed_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
        logger.info(
            "notify_subscribers_on_publish: exit",
            extra={
                "agent_id": agent_id,
                "notified": notified,
                "elapsed_ms": elapsed_ms,
            },
        )
        return notified

    except Exception as exc:
        logger.error(
            f"notify_subscribers_on_publish: failed for agent_id={agent_id}: {exc}",
            exc_info=True,
        )
        raise


def mark_notified(subscriber_id: str, version_id: str) -> None:
    """Update last_notified_version_id for a specific subscriber record.

    Called from the API layer after delivering a notification to a client.

    Args:
        subscriber_id: FK to AgentSubscriber.id.
        version_id:    FK to AgentVersion.id that was just delivered.

    Raises:
        ValueError: if subscriber not found.
        Exception:  on database error.
    """
    logger.info(
        "mark_notified: entry",
        extra={"subscriber_id": subscriber_id, "version_id": version_id},
    )

    if _engine is None:
        logger.warning("mark_notified: engine unavailable — no-op")
        return

    try:
        from sqlalchemy import text

        with _engine.begin() as conn:
            result = conn.execute(
                text(
                    """
                    UPDATE agent_subscribers
                    SET last_notified_version_id = :version_id
                    WHERE id = :subscriber_id
                    """
                ),
                {"version_id": version_id, "subscriber_id": subscriber_id},
            )

            if result.rowcount == 0:
                raise ValueError(f"mark_notified: subscriber '{subscriber_id}' not found")

        logger.info("mark_notified: exit", extra={"subscriber_id": subscriber_id})

    except ValueError:
        raise
    except Exception as exc:
        logger.error(
            f"mark_notified: failed for subscriber_id={subscriber_id}: {exc}", exc_info=True
        )
        raise


__all__ = [
    "subscribe",
    "unsubscribe",
    "list_subscribers",
    "notify_subscribers_on_publish",
    "mark_notified",
]
