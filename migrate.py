"""Postgres schema initialisation script for the AI Assurance Platform.

Runs CREATE TABLE IF NOT EXISTS for all tables introduced in Session 07:
  - agents
  - agent_versions
  - agent_bindings
  - agent_subscribers

Also runs seed_agents() to populate the 6 reference agents with v1.0.0 published.

Safe to run multiple times — all DDL is idempotent (IF NOT EXISTS, ON CONFLICT DO NOTHING).

Usage:
    python migrate.py

Environment variables required:
    DATABASE_URL — full Postgres connection string e.g.
        postgresql://user:pass@host:5432/dbname?sslmode=require
"""

from __future__ import annotations

import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("migrate")

_DATABASE_URL = os.getenv("DATABASE_URL")


def _check_env() -> None:
    """Validate required environment variables before attempting any DB work."""
    if not _DATABASE_URL:
        logger.error(
            "migrate: DATABASE_URL is not set. "
            "Export it before running this script: "
            "export DATABASE_URL=postgresql://user:pass@host/dbname?sslmode=require"
        )
        sys.exit(1)


_FULL_DDL = """
-- agents -------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS agents (
    id                VARCHAR(128) PRIMARY KEY,
    name              VARCHAR(256) NOT NULL,
    description       TEXT         NOT NULL,
    team              VARCHAR(128) NOT NULL,
    owner_type        VARCHAR(16)  NOT NULL
                      CHECK (owner_type IN ('CUSTOM', 'REUSABLE')),
    latest_version_id VARCHAR(128),
    inherent_risk     VARCHAR(16)  NOT NULL
                      CHECK (inherent_risk IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
    framework_refs    JSONB        NOT NULL DEFAULT '[]',
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- agent_versions -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS agent_versions (
    id           VARCHAR(128) PRIMARY KEY,
    agent_id     VARCHAR(128) NOT NULL REFERENCES agents(id),
    semver       VARCHAR(64)  NOT NULL,
    changelog    TEXT         NOT NULL,
    status       VARCHAR(16)  NOT NULL DEFAULT 'DRAFT'
                 CHECK (status IN ('DRAFT', 'PUBLISHED', 'DEPRECATED')),
    config       JSONB        NOT NULL DEFAULT '{}',
    published_at TIMESTAMPTZ,
    published_by VARCHAR(256),
    UNIQUE (agent_id, semver)
);

CREATE INDEX IF NOT EXISTS idx_agent_versions_agent
    ON agent_versions (agent_id);

-- agent_bindings -----------------------------------------------------------
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

-- agent_subscribers --------------------------------------------------------
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


def run_ddl() -> None:
    """Execute the full DDL block against Postgres.

    Each CREATE TABLE IF NOT EXISTS is idempotent.  Existing tables and indexes
    are left untouched.
    """
    logger.info("migrate: connecting to Postgres")

    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(
            _DATABASE_URL,
            pool_pre_ping=True,
            connect_args={"connect_timeout": 10},
        )

        with engine.begin() as conn:
            conn.execute(text(_FULL_DDL))

        logger.info("migrate: DDL complete — agents, agent_versions, agent_bindings, agent_subscribers ready")
        engine.dispose()

    except Exception as exc:
        logger.error(f"migrate: DDL failed: {exc}", exc_info=True)
        sys.exit(1)


def run_seed() -> None:
    """Seed 6 reference agents with v1.0.0 published.

    Idempotent — ON CONFLICT DO NOTHING on agent INSERT; UNIQUE (agent_id, semver)
    on versions prevents duplicates.
    """
    logger.info("migrate: seeding agents")

    try:
        from domain.agents import seed_agents

        agents = seed_agents()
        for a in agents:
            logger.info(
                "migrate: seeded agent",
                extra={"id": a.id, "latest_version_id": a.latest_version_id},
            )
        logger.info(f"migrate: seed complete — {len(agents)} agents")

    except Exception as exc:
        logger.error(f"migrate: seed failed: {exc}", exc_info=True)
        # Non-fatal — schema is already set up; seed failures can be retried
        logger.warning("migrate: continuing despite seed failure")


if __name__ == "__main__":
    _check_env()
    run_ddl()
    run_seed()
    logger.info("migrate: all done")
