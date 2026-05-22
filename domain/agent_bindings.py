"""Agent binding lifecycle — bind, update, unbind, and accept upgrades.

An AgentBinding links a specific AgentVersion to an AISystem.  Bindings can be:
  - Unpinned (pinned=False): auto-notified when a new version publishes.
  - Pinned (pinned=True): frozen at the bound version; upgrade_available_version_id
    is populated but NOT auto-applied.

Every bind operation also auto-subscribes the system to future publish events
via domain.agent_subscribers.

Primary storage: Postgres (agent_bindings table).
Audit trail: data/events.jsonl via domain.repository.append_agent_event.

Security:
  - All SQL parameterized — no f-string SQL.
  - DB errors logged and re-raised.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from domain.models import AgentBinding

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
        logger.info("agent_bindings: SQLAlchemy engine created")
    except Exception as _exc:
        logger.warning(f"agent_bindings: failed to create engine: {_exc}")
        _engine = None
else:
    logger.warning("agent_bindings: DATABASE_URL not set — Postgres unavailable")

# ---------------------------------------------------------------------------
# Schema bootstrap
# ---------------------------------------------------------------------------

_BINDINGS_DDL = """
CREATE TABLE IF NOT EXISTS agent_bindings (
    id                           VARCHAR(128) PRIMARY KEY,
    agent_id                     VARCHAR(128) NOT NULL,
    system_id                    VARCHAR(128) NOT NULL,
    version_id                   VARCHAR(128) NOT NULL,
    pinned                       BOOLEAN      NOT NULL DEFAULT FALSE,
    upgrade_available_version_id VARCHAR(128),
    created_at                   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at                   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (agent_id, system_id)
);

CREATE INDEX IF NOT EXISTS idx_bindings_system
    ON agent_bindings (system_id);

CREATE INDEX IF NOT EXISTS idx_bindings_agent
    ON agent_bindings (agent_id);
"""


def _init_schema() -> None:
    """Bootstrap agent_bindings table. Idempotent."""
    if _engine is None:
        return
    try:
        from sqlalchemy import text

        with _engine.begin() as conn:
            conn.execute(text(_BINDINGS_DDL))
        logger.info("agent_bindings: schema initialised")
    except Exception as exc:
        logger.error(f"agent_bindings: schema init failed: {exc}", exc_info=True)


if _engine is not None:
    _init_schema()


# ---------------------------------------------------------------------------
# Row mapping
# ---------------------------------------------------------------------------


def _row_to_binding(row: object) -> AgentBinding:
    """Convert a SQLAlchemy Row to an AgentBinding model."""
    return AgentBinding(
        id=row[0],
        agent_id=row[1],
        system_id=row[2],
        version_id=row[3],
        pinned=bool(row[4]),
        upgrade_available_version_id=row[5],
        created_at=row[6],
        updated_at=row[7],
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def bind_agent_to_system(
    agent_id: str,
    system_id: str,
    version_id: Optional[str] = None,
    pinned: bool = False,
) -> AgentBinding:
    """Bind an agent version to an AI system.

    If version_id is None the agent's current latest_version_id is used.
    If version_id is provided, pinned is forced to True.
    The system is auto-subscribed for future publish notifications.

    Args:
        agent_id:   FK to Agent.id.
        system_id:  FK to AISystem.id.
        version_id: Optional FK to AgentVersion.id.  None = bind to latest.
        pinned:     If True the binding will not auto-upgrade on new publish.

    Returns:
        Persisted AgentBinding.

    Raises:
        ValueError: if agent not found or has no published version and none supplied.
        Exception:  on database error.
    """
    start = datetime.now(timezone.utc)
    logger.info(
        "bind_agent_to_system: entry",
        extra={"agent_id": agent_id, "system_id": system_id, "pinned": pinned},
    )

    # Resolve version_id if not provided
    if version_id is None:
        from domain.agents import get_agent

        agent = get_agent(agent_id)
        if agent is None:
            raise ValueError(f"bind_agent_to_system: agent '{agent_id}' not found")
        if agent.latest_version_id is None:
            raise ValueError(
                f"bind_agent_to_system: agent '{agent_id}' has no published version"
            )
        resolved_version_id = agent.latest_version_id
        effective_pinned = False
    else:
        resolved_version_id = version_id
        effective_pinned = True  # explicit version = pinned

    now = datetime.now(timezone.utc)
    binding_id = f"ai-bind-{uuid.uuid4()}"

    binding = AgentBinding(
        id=binding_id,
        agent_id=agent_id,
        system_id=system_id,
        version_id=resolved_version_id,
        pinned=effective_pinned,
        upgrade_available_version_id=None,
        created_at=now,
        updated_at=now,
    )

    if _engine is not None:
        try:
            from sqlalchemy import text

            with _engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO agent_bindings
                            (id, agent_id, system_id, version_id, pinned,
                             upgrade_available_version_id, created_at, updated_at)
                        VALUES
                            (:id, :agent_id, :system_id, :version_id, :pinned,
                             NULL, :created_at, :updated_at)
                        ON CONFLICT (agent_id, system_id)
                        DO UPDATE SET
                            version_id = EXCLUDED.version_id,
                            pinned     = EXCLUDED.pinned,
                            updated_at = EXCLUDED.updated_at
                        """
                    ),
                    {
                        "id": binding.id,
                        "agent_id": binding.agent_id,
                        "system_id": binding.system_id,
                        "version_id": binding.version_id,
                        "pinned": binding.pinned,
                        "created_at": binding.created_at,
                        "updated_at": binding.updated_at,
                    },
                )
        except Exception as exc:
            logger.error(f"bind_agent_to_system: DB insert failed: {exc}", exc_info=True)
            raise
    else:
        logger.warning("bind_agent_to_system: engine unavailable — in-memory only")

    # Auto-subscribe system for upgrade notifications
    try:
        from domain.agent_subscribers import subscribe

        subscribe(agent_id=agent_id, system_id=system_id)
    except Exception as sub_exc:
        logger.warning(f"bind_agent_to_system: auto-subscribe failed (non-fatal): {sub_exc}")

    # Audit trail
    from domain.repository import append_agent_event

    append_agent_event(
        "AGENT_BINDING_CREATED",
        {
            "binding_id": binding.id,
            "agent_id": agent_id,
            "system_id": system_id,
            "version_id": resolved_version_id,
            "pinned": effective_pinned,
        },
    )

    elapsed_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
    logger.info(
        "bind_agent_to_system: exit",
        extra={"binding_id": binding.id, "elapsed_ms": elapsed_ms},
    )
    return binding


def list_bindings_for_system(system_id: str) -> list[AgentBinding]:
    """Return all agent bindings for a given AI system.

    Args:
        system_id: FK to AISystem.id.

    Returns:
        List of AgentBinding instances ordered by agent_id.
    """
    logger.info("list_bindings_for_system: entry", extra={"system_id": system_id})

    if _engine is None:
        logger.warning("list_bindings_for_system: engine unavailable — returning empty")
        return []

    try:
        from sqlalchemy import text

        with _engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT id, agent_id, system_id, version_id, pinned,
                           upgrade_available_version_id, created_at, updated_at
                    FROM agent_bindings
                    WHERE system_id = :system_id
                    ORDER BY agent_id
                    """
                ),
                {"system_id": system_id},
            ).fetchall()

        bindings = [_row_to_binding(r) for r in rows]
        logger.info(
            "list_bindings_for_system: exit",
            extra={"system_id": system_id, "count": len(bindings)},
        )
        return bindings

    except Exception as exc:
        logger.error(
            f"list_bindings_for_system: query failed for system_id={system_id}: {exc}",
            exc_info=True,
        )
        raise


def list_bindings_for_agent(agent_id: str) -> list[AgentBinding]:
    """Return all system bindings for a given agent.

    Args:
        agent_id: FK to Agent.id.

    Returns:
        List of AgentBinding instances ordered by system_id.
    """
    logger.info("list_bindings_for_agent: entry", extra={"agent_id": agent_id})

    if _engine is None:
        logger.warning("list_bindings_for_agent: engine unavailable — returning empty")
        return []

    try:
        from sqlalchemy import text

        with _engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT id, agent_id, system_id, version_id, pinned,
                           upgrade_available_version_id, created_at, updated_at
                    FROM agent_bindings
                    WHERE agent_id = :agent_id
                    ORDER BY system_id
                    """
                ),
                {"agent_id": agent_id},
            ).fetchall()

        bindings = [_row_to_binding(r) for r in rows]
        logger.info(
            "list_bindings_for_agent: exit",
            extra={"agent_id": agent_id, "count": len(bindings)},
        )
        return bindings

    except Exception as exc:
        logger.error(
            f"list_bindings_for_agent: query failed for agent_id={agent_id}: {exc}",
            exc_info=True,
        )
        raise


def get_binding(binding_id: str, system_id: Optional[str] = None) -> Optional[AgentBinding]:
    """Fetch a single AgentBinding by id, optionally enforcing system ownership.

    Args:
        binding_id: AgentBinding.id.
        system_id:  If provided, the binding must belong to this system; else returns None.

    Returns:
        AgentBinding if found and (system_id is None or binding.system_id == system_id), else None.
    """
    logger.info(
        "get_binding: entry",
        extra={"binding_id": binding_id, "system_id": system_id},
    )

    if _engine is None:
        logger.warning("get_binding: engine unavailable — returning None")
        return None

    try:
        from sqlalchemy import text

        with _engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT id, agent_id, system_id, version_id, pinned,
                           upgrade_available_version_id, created_at, updated_at
                    FROM agent_bindings
                    WHERE id = :binding_id
                    """
                ),
                {"binding_id": binding_id},
            ).fetchone()

        if row is None:
            return None

        binding = _row_to_binding(row)
        if system_id is not None and binding.system_id != system_id:
            logger.warning(
                "get_binding: ownership mismatch",
                extra={"binding_id": binding_id, "expected_system": system_id, "actual_system": binding.system_id},
            )
            return None
        return binding

    except Exception as exc:
        logger.error(f"get_binding: query failed for binding_id={binding_id}: {exc}", exc_info=True)
        raise


def update_binding_version(
    binding_id: str,
    version_id: str,
    pinned: bool = False,
) -> AgentBinding:
    """Update the version a binding points to.

    Clears upgrade_available_version_id on update.

    Args:
        binding_id: FK to AgentBinding.id.
        version_id: New FK to AgentVersion.id.
        pinned:     Whether to pin this version.

    Returns:
        Updated AgentBinding.

    Raises:
        ValueError: if binding not found.
        Exception:  on database error.
    """
    logger.info(
        "update_binding_version: entry",
        extra={"binding_id": binding_id, "version_id": version_id},
    )

    if _engine is None:
        raise RuntimeError("update_binding_version: database engine unavailable")

    try:
        from sqlalchemy import text

        now = datetime.now(timezone.utc)

        with _engine.begin() as conn:
            result = conn.execute(
                text(
                    """
                    UPDATE agent_bindings
                    SET version_id = :version_id,
                        pinned = :pinned,
                        upgrade_available_version_id = NULL,
                        updated_at = :now
                    WHERE id = :binding_id
                    """
                ),
                {
                    "version_id": version_id,
                    "pinned": pinned,
                    "now": now,
                    "binding_id": binding_id,
                },
            )
            if result.rowcount == 0:
                raise ValueError(f"update_binding_version: binding '{binding_id}' not found")

        with _engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT id, agent_id, system_id, version_id, pinned,
                           upgrade_available_version_id, created_at, updated_at
                    FROM agent_bindings
                    WHERE id = :binding_id
                    """
                ),
                {"binding_id": binding_id},
            ).fetchone()

        if row is None:
            raise ValueError(f"update_binding_version: binding '{binding_id}' not found after update")

        binding = _row_to_binding(row)
        logger.info(
            "update_binding_version: exit",
            extra={"binding_id": binding_id},
        )
        return binding

    except ValueError:
        raise
    except Exception as exc:
        logger.error(
            f"update_binding_version: failed for binding_id={binding_id}: {exc}",
            exc_info=True,
        )
        raise


def unbind_agent(binding_id: str) -> None:
    """Remove an agent binding and its subscription.

    Args:
        binding_id: FK to AgentBinding.id.

    Raises:
        ValueError: if binding not found.
        Exception:  on database error.
    """
    logger.info("unbind_agent: entry", extra={"binding_id": binding_id})

    if _engine is None:
        raise RuntimeError("unbind_agent: database engine unavailable")

    try:
        from sqlalchemy import text

        # Fetch binding first for subscription removal
        with _engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT id, agent_id, system_id FROM agent_bindings WHERE id = :binding_id"
                ),
                {"binding_id": binding_id},
            ).fetchone()

        if row is None:
            raise ValueError(f"unbind_agent: binding '{binding_id}' not found")

        agent_id: str = row[1]
        system_id: str = row[2]

        with _engine.begin() as conn:
            conn.execute(
                text("DELETE FROM agent_bindings WHERE id = :binding_id"),
                {"binding_id": binding_id},
            )

    except ValueError:
        raise
    except Exception as exc:
        logger.error(f"unbind_agent: failed for binding_id={binding_id}: {exc}", exc_info=True)
        raise

    # Remove subscription (best-effort)
    try:
        from domain.agent_subscribers import unsubscribe

        unsubscribe(agent_id=agent_id, system_id=system_id)
    except Exception as sub_exc:
        logger.warning(f"unbind_agent: unsubscribe failed (non-fatal): {sub_exc}")

    from domain.repository import append_agent_event

    append_agent_event(
        "AGENT_BINDING_REMOVED",
        {"binding_id": binding_id, "agent_id": agent_id, "system_id": system_id},
    )

    logger.info("unbind_agent: exit", extra={"binding_id": binding_id})


def accept_upgrade(binding_id: str) -> AgentBinding:
    """Accept the pending upgrade on a binding.

    Moves upgrade_available_version_id → version_id and clears the pending field.
    Sets pinned=False (user accepted the upgrade, binding follows latest again).

    Args:
        binding_id: FK to AgentBinding.id.

    Returns:
        Updated AgentBinding.

    Raises:
        ValueError: if binding not found or no upgrade available.
        Exception:  on database error.
    """
    logger.info("accept_upgrade: entry", extra={"binding_id": binding_id})

    if _engine is None:
        raise RuntimeError("accept_upgrade: database engine unavailable")

    try:
        from sqlalchemy import text

        with _engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT id, agent_id, system_id, version_id, pinned,
                           upgrade_available_version_id, created_at, updated_at
                    FROM agent_bindings
                    WHERE id = :binding_id
                    """
                ),
                {"binding_id": binding_id},
            ).fetchone()

        if row is None:
            raise ValueError(f"accept_upgrade: binding '{binding_id}' not found")

        upgrade_version_id: Optional[str] = row[5]
        if upgrade_version_id is None:
            raise ValueError(
                f"accept_upgrade: binding '{binding_id}' has no pending upgrade"
            )

        now = datetime.now(timezone.utc)

        with _engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE agent_bindings
                    SET version_id = :new_version_id,
                        upgrade_available_version_id = NULL,
                        pinned = FALSE,
                        updated_at = :now
                    WHERE id = :binding_id
                    """
                ),
                {"new_version_id": upgrade_version_id, "now": now, "binding_id": binding_id},
            )

        with _engine.connect() as conn:
            updated_row = conn.execute(
                text(
                    """
                    SELECT id, agent_id, system_id, version_id, pinned,
                           upgrade_available_version_id, created_at, updated_at
                    FROM agent_bindings
                    WHERE id = :binding_id
                    """
                ),
                {"binding_id": binding_id},
            ).fetchone()

        if updated_row is None:
            raise ValueError(f"accept_upgrade: binding '{binding_id}' disappeared after update")

        binding = _row_to_binding(updated_row)

        from domain.repository import append_agent_event

        append_agent_event(
            "AGENT_BINDING_UPGRADED",
            {
                "binding_id": binding_id,
                "agent_id": binding.agent_id,
                "system_id": binding.system_id,
                "new_version_id": upgrade_version_id,
            },
        )

        logger.info("accept_upgrade: exit", extra={"binding_id": binding_id})
        return binding

    except ValueError:
        raise
    except Exception as exc:
        logger.error(f"accept_upgrade: failed for binding_id={binding_id}: {exc}", exc_info=True)
        raise


__all__ = [
    "bind_agent_to_system",
    "list_bindings_for_system",
    "list_bindings_for_agent",
    "update_binding_version",
    "unbind_agent",
    "accept_upgrade",
]
