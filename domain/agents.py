"""Agent registry — create, version, publish, and list agents.

Primary storage: Postgres (agents + agent_versions tables).
Audit trail: data/events.jsonl via domain.repository.append_agent_event.
Notifications: pg_notify on publish so API-layer LISTEN clients fire within ~100 ms.

Environment variables (inherited from domain/agent_memory.py):
  DATABASE_URL   Full Postgres connection string (required for live DB).

Security constraints:
  - All SQL is parameterized — no f-string SQL.
  - publish_version is atomic: if ANY step fails the agent.latest_version_id
    is NOT updated (fail-closed).
  - Database errors are logged and re-raised; never silently swallowed.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from domain.models import Agent, AgentOwnerType, AgentStatus, AgentVersion, RiskLevel

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Engine — follows agent_memory.py singleton pattern exactly
# ---------------------------------------------------------------------------

_DATABASE_URL: Optional[str] = os.getenv("DATABASE_URL")
_engine = None  # type: ignore[assignment]

# In-memory fallback when Postgres is not configured (App Service B1 demo).
# Day-12 fix: create_agent already returned an Agent object without persisting
# (line 236), but list_agents returned [] because it only queries the DB. This
# dict bridges the two so seed_agents() at startup is actually visible to the
# /api/agents endpoint. Lives for the lifetime of the worker process.
_inmem_agents: dict[str, Agent] = {}
# Session 16 #18 extension of Session 12B pattern: versions also need an
# in-memory fallback so the publish workflow works in dev (no DATABASE_URL).
_inmem_versions: dict[str, AgentVersion] = {}

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
        logger.info("agents: SQLAlchemy engine created")
    except Exception as _exc:
        logger.warning(f"agents: failed to create engine: {_exc}")
        _engine = None
else:
    logger.warning("agents: DATABASE_URL not set — Postgres unavailable")

# ---------------------------------------------------------------------------
# Schema bootstrap
# ---------------------------------------------------------------------------

_AGENTS_DDL = """
CREATE TABLE IF NOT EXISTS agents (
    id               VARCHAR(128) PRIMARY KEY,
    name             VARCHAR(256) NOT NULL,
    description      TEXT         NOT NULL,
    team             VARCHAR(128) NOT NULL,
    owner_type       VARCHAR(16)  NOT NULL,
    latest_version_id VARCHAR(128),
    inherent_risk    VARCHAR(16)  NOT NULL,
    framework_refs   JSONB        NOT NULL DEFAULT '[]',
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agent_versions (
    id           VARCHAR(128) PRIMARY KEY,
    agent_id     VARCHAR(128) NOT NULL REFERENCES agents(id),
    semver       VARCHAR(64)  NOT NULL,
    changelog    TEXT         NOT NULL,
    status       VARCHAR(16)  NOT NULL DEFAULT 'DRAFT',
    config       JSONB        NOT NULL DEFAULT '{}',
    published_at TIMESTAMPTZ,
    published_by VARCHAR(256),
    UNIQUE (agent_id, semver)
);

CREATE INDEX IF NOT EXISTS idx_agent_versions_agent
    ON agent_versions (agent_id);
"""


def _init_schema() -> None:
    """Bootstrap agents + agent_versions tables. Idempotent (IF NOT EXISTS)."""
    if _engine is None:
        return
    try:
        from sqlalchemy import text

        with _engine.begin() as conn:
            conn.execute(text(_AGENTS_DDL))
        logger.info("agents: schema initialised")
    except Exception as exc:
        logger.error(f"agents: schema init failed: {exc}", exc_info=True)


if _engine is not None:
    _init_schema()


# ---------------------------------------------------------------------------
# CRUD helpers
# ---------------------------------------------------------------------------


def _row_to_agent(row: object) -> Agent:
    """Convert a SQLAlchemy Row to an Agent model."""
    return Agent(
        id=row[0],
        name=row[1],
        description=row[2],
        team=row[3],
        owner_type=AgentOwnerType(row[4]),
        latest_version_id=row[5],
        inherent_risk=RiskLevel(row[6]),
        framework_refs=row[7] if isinstance(row[7], list) else json.loads(row[7] or "[]"),
        created_at=row[8],
        updated_at=row[9],
    )


def _row_to_version(row: object) -> AgentVersion:
    """Convert a SQLAlchemy Row to an AgentVersion model."""
    config_raw = row[5]
    config = (
        config_raw
        if isinstance(config_raw, dict)
        else json.loads(config_raw or "{}")
    )
    return AgentVersion(
        id=row[0],
        agent_id=row[1],
        semver=row[2],
        changelog=row[3],
        status=AgentStatus(row[4]),
        config=config,
        published_at=row[6],
        published_by=row[7],
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def create_agent(
    name: str,
    description: str,
    team: str,
    owner_type: AgentOwnerType,
    inherent_risk: RiskLevel,
    framework_refs: Optional[list[str]] = None,
    agent_id: Optional[str] = None,
) -> Agent:
    """Create and persist a new agent record.

    Args:
        name:           Human-readable agent name.
        description:    What this agent does.
        team:           Owning team slug e.g. 'payments', 'platform'.
        owner_type:     CUSTOM (team-only) or REUSABLE (org-wide).
        inherent_risk:  Baseline risk classification.
        framework_refs: Optional list of framework clause refs.
        agent_id:       Override generated id (used by seed_agents).

    Returns:
        Persisted Agent instance.

    Raises:
        Exception: on database error (logged and re-raised).
    """
    start = datetime.now(timezone.utc)
    logger.info(
        "create_agent: entry",
        extra={"name": name, "team": team, "owner_type": owner_type.value},
    )

    now = datetime.now(timezone.utc)
    aid = agent_id or f"ai-agent-{name.lower().replace(' ', '-')}-{uuid.uuid4().hex[:6]}"
    refs = framework_refs or []

    agent = Agent(
        id=aid,
        name=name,
        description=description,
        team=team,
        owner_type=owner_type,
        inherent_risk=inherent_risk,
        framework_refs=refs,
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
                        INSERT INTO agents
                            (id, name, description, team, owner_type, latest_version_id,
                             inherent_risk, framework_refs, created_at, updated_at)
                        VALUES
                            (:id, :name, :description, :team, :owner_type, NULL,
                             :inherent_risk, :framework_refs, :created_at, :updated_at)
                        ON CONFLICT (id) DO NOTHING
                        """
                    ),
                    {
                        "id": agent.id,
                        "name": agent.name,
                        "description": agent.description,
                        "team": agent.team,
                        "owner_type": agent.owner_type.value,
                        "inherent_risk": agent.inherent_risk.value,
                        "framework_refs": json.dumps(agent.framework_refs),
                        "created_at": agent.created_at,
                        "updated_at": agent.updated_at,
                    },
                )
        except Exception as exc:
            logger.error(f"create_agent: DB insert failed: {exc}", exc_info=True)
            raise
    else:
        logger.warning("create_agent: engine unavailable — storing in _inmem_agents")
        _inmem_agents[agent.id] = agent

    from domain.repository import append_agent_event

    append_agent_event("AGENT_CREATED", {"agent_id": agent.id, "team": team, "owner_type": owner_type.value})

    elapsed_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
    logger.info(
        "create_agent: exit",
        extra={"agent_id": agent.id, "elapsed_ms": elapsed_ms},
    )
    return agent


def get_agent(agent_id: str) -> Optional[Agent]:
    """Fetch a single agent by id from Postgres.

    Args:
        agent_id: The agent's stable id e.g. 'ai-agent-pay-fraud'.

    Returns:
        Agent instance or None if not found or engine unavailable.
    """
    logger.info("get_agent: entry", extra={"agent_id": agent_id})

    if _engine is None:
        return _inmem_agents.get(agent_id)

    try:
        from sqlalchemy import text

        with _engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT id, name, description, team, owner_type, latest_version_id,
                           inherent_risk, framework_refs, created_at, updated_at
                    FROM agents
                    WHERE id = :agent_id
                    """
                ),
                {"agent_id": agent_id},
            ).fetchone()

        if row is None:
            logger.info("get_agent: not found", extra={"agent_id": agent_id})
            return None

        agent = _row_to_agent(row)
        logger.info("get_agent: exit", extra={"agent_id": agent_id})
        return agent

    except Exception as exc:
        logger.error(f"get_agent: query failed for id={agent_id}: {exc}", exc_info=True)
        raise


def list_agents(
    team: Optional[str] = None,
    owner_type: Optional[AgentOwnerType] = None,
) -> list[Agent]:
    """List agents with optional filters.

    Args:
        team:       Filter by team slug. None returns all teams.
        owner_type: Filter by CUSTOM or REUSABLE. None returns both.

    Returns:
        List of Agent instances ordered by name.
    """
    logger.info(
        "list_agents: entry",
        extra={"team": team, "owner_type": owner_type.value if owner_type else None},
    )

    if _engine is None:
        # Serve from in-memory fallback populated by create_agent (Day-12).
        items = list(_inmem_agents.values())
        if team is not None:
            items = [a for a in items if a.team == team]
        if owner_type is not None:
            items = [a for a in items if a.owner_type == owner_type]
        items.sort(key=lambda a: a.name)
        logger.info("list_agents: in-memory fallback — count=%d", len(items))
        return items

    try:
        from sqlalchemy import text

        conditions = []
        params: dict = {}
        if team is not None:
            conditions.append("team = :team")
            params["team"] = team
        if owner_type is not None:
            conditions.append("owner_type = :owner_type")
            params["owner_type"] = owner_type.value

        where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        with _engine.connect() as conn:
            rows = conn.execute(
                text(
                    f"""
                    SELECT id, name, description, team, owner_type, latest_version_id,
                           inherent_risk, framework_refs, created_at, updated_at
                    FROM agents
                    {where_clause}
                    ORDER BY name
                    """  # noqa: S608 — where_clause contains only safe enum/literal values
                ),
                params,
            ).fetchall()

        agents = [_row_to_agent(r) for r in rows]
        logger.info("list_agents: exit", extra={"count": len(agents)})
        return agents

    except Exception as exc:
        logger.error(f"list_agents: query failed: {exc}", exc_info=True)
        raise


def create_version(
    agent_id: str,
    semver: str,
    changelog: str,
    config: Optional[dict] = None,
) -> AgentVersion:
    """Create a new DRAFT version for an existing agent.

    Validates the agent exists and the semver is unique for that agent.

    Args:
        agent_id:  FK to Agent.id.
        semver:    Semver 2.0.0 string e.g. '1.0.0'.  Validated by AgentVersion.
        changelog: Human-readable description of changes.
        config:    Dict of prompt/tool/model settings.

    Returns:
        Persisted AgentVersion in DRAFT status.

    Raises:
        ValueError: if agent not found.
        Exception:  on database error.
    """
    start = datetime.now(timezone.utc)
    logger.info(
        "create_version: entry",
        extra={"agent_id": agent_id, "semver": semver},
    )

    version = AgentVersion(
        id=f"ai-agent-ver-{uuid.uuid4()}",
        agent_id=agent_id,
        semver=semver,
        changelog=changelog,
        status=AgentStatus.DRAFT,
        config=config or {},
    )

    if _engine is not None:
        try:
            from sqlalchemy import text

            with _engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO agent_versions
                            (id, agent_id, semver, changelog, status, config)
                        VALUES
                            (:id, :agent_id, :semver, :changelog, :status, :config)
                        """
                    ),
                    {
                        "id": version.id,
                        "agent_id": version.agent_id,
                        "semver": version.semver,
                        "changelog": version.changelog,
                        "status": version.status.value,
                        "config": json.dumps(version.config),
                    },
                )
        except Exception as exc:
            logger.error(f"create_version: DB insert failed: {exc}", exc_info=True)
            raise
    else:
        logger.warning("create_version: engine unavailable — storing in _inmem_versions")
        _inmem_versions[version.id] = version

    from domain.repository import append_agent_event

    append_agent_event(
        "AGENT_VERSION_CREATED",
        {"agent_id": agent_id, "version_id": version.id, "semver": semver},
    )

    elapsed_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
    logger.info(
        "create_version: exit",
        extra={"version_id": version.id, "elapsed_ms": elapsed_ms},
    )
    return version


def publish_version(version_id: str, published_by: str) -> AgentVersion:
    """Atomically publish an agent version.

    Steps (all inside a single transaction):
      1. Fetch the version and verify it is DRAFT.
      2. Set status=PUBLISHED, published_at=now, published_by.
      3. Update agents.latest_version_id.
      4. pg_notify('agent_update_{agent_id}', version_id).
    Then (outside transaction, best-effort):
      5. Append AGENT_PUBLISHED event to events.jsonl.
      6. Notify subscribers via domain.agent_subscribers.notify_subscribers_on_publish.

    Fail-closed: if the transaction rolls back, agent.latest_version_id is NOT updated.

    Args:
        version_id:   FK to AgentVersion.id (must be in DRAFT status).
        published_by: User/system identifier performing the publish.

    Returns:
        Updated AgentVersion with status=PUBLISHED.

    Raises:
        ValueError: if version not found or already published.
        Exception:  on database error.
    """
    start = datetime.now(timezone.utc)
    logger.info(
        "publish_version: entry",
        extra={"version_id": version_id, "published_by": published_by},
    )

    if _engine is None:
        # In-memory fallback — mirrors Session 12B pattern for agents.
        v = _inmem_versions.get(version_id)
        if v is None:
            raise ValueError(f"publish_version: version_id='{version_id}' not found")
        if v.status != AgentStatus.DRAFT:
            raise ValueError(
                f"publish_version: version '{version_id}' is {v.status.value}, "
                "only DRAFT versions can be published"
            )
        now = datetime.now(timezone.utc)
        published_version = v.model_copy(update={
            "status": AgentStatus.PUBLISHED,
            "published_at": now,
            "published_by": published_by,
        })
        _inmem_versions[version_id] = published_version
        agent = _inmem_agents.get(v.agent_id)
        if agent is not None:
            _inmem_agents[v.agent_id] = agent.model_copy(update={
                "latest_version_id": version_id,
                "updated_at": now,
            })
        # Best-effort audit + subscriber notify (same as DB path, outside transaction).
        try:
            from domain.repository import append_agent_event
            append_agent_event("AGENT_PUBLISHED", {
                "agent_id": published_version.agent_id,
                "version_id": version_id,
                "semver": published_version.semver,
                "published_by": published_by,
            })
        except Exception as audit_exc:
            logger.warning(f"publish_version: audit event write failed (non-fatal): {audit_exc}")
        try:
            from domain.agent_subscribers import notify_subscribers_on_publish
            notify_subscribers_on_publish(published_version.agent_id, version_id)
        except Exception as sub_exc:
            logger.warning(f"publish_version: subscriber notification failed (non-fatal): {sub_exc}")
        return published_version

    try:
        from sqlalchemy import text

        now = datetime.now(timezone.utc)

        with _engine.begin() as conn:
            # 1. Fetch version
            row = conn.execute(
                text(
                    """
                    SELECT id, agent_id, semver, changelog, status, config,
                           published_at, published_by
                    FROM agent_versions
                    WHERE id = :version_id
                    FOR UPDATE
                    """
                ),
                {"version_id": version_id},
            ).fetchone()

            if row is None:
                raise ValueError(f"publish_version: version_id='{version_id}' not found")

            current_status = AgentStatus(row[4])
            if current_status != AgentStatus.DRAFT:
                raise ValueError(
                    f"publish_version: version '{version_id}' is {current_status.value}, "
                    "only DRAFT versions can be published"
                )

            agent_id: str = row[1]

            # 2. Set status=PUBLISHED
            conn.execute(
                text(
                    """
                    UPDATE agent_versions
                    SET status = 'PUBLISHED',
                        published_at = :now,
                        published_by = :published_by
                    WHERE id = :version_id
                    """
                ),
                {"now": now, "published_by": published_by, "version_id": version_id},
            )

            # 3. Update agent.latest_version_id + updated_at
            conn.execute(
                text(
                    """
                    UPDATE agents
                    SET latest_version_id = :version_id,
                        updated_at = :now
                    WHERE id = :agent_id
                    """
                ),
                {"version_id": version_id, "now": now, "agent_id": agent_id},
            )

            # 4. pg_notify — channel name is agent_update_{agent_id}
            channel = f"agent_update_{agent_id}"
            conn.execute(
                text("SELECT pg_notify(:channel, :payload)"),
                {"channel": channel, "payload": version_id},
            )

        # Fetch the updated row outside the transaction
        with _engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT id, agent_id, semver, changelog, status, config,
                           published_at, published_by
                    FROM agent_versions
                    WHERE id = :version_id
                    """
                ),
                {"version_id": version_id},
            ).fetchone()

        published_version = _row_to_version(row)

    except (ValueError, RuntimeError):
        raise
    except Exception as exc:
        logger.error(
            f"publish_version: transaction failed for version_id={version_id}: {exc}",
            exc_info=True,
        )
        raise

    # 5. Audit trail (best-effort, outside transaction)
    try:
        from domain.repository import append_agent_event

        append_agent_event(
            "AGENT_PUBLISHED",
            {
                "agent_id": published_version.agent_id,
                "version_id": version_id,
                "semver": published_version.semver,
                "published_by": published_by,
            },
        )
    except Exception as audit_exc:
        logger.warning(f"publish_version: audit event write failed (non-fatal): {audit_exc}")

    # 6. Notify subscribers (best-effort)
    try:
        from domain.agent_subscribers import notify_subscribers_on_publish

        notified = notify_subscribers_on_publish(published_version.agent_id, version_id)
        logger.info(
            "publish_version: subscribers notified",
            extra={"agent_id": published_version.agent_id, "notified": notified},
        )
    except Exception as sub_exc:
        logger.warning(f"publish_version: subscriber notification failed (non-fatal): {sub_exc}")

    elapsed_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
    logger.info(
        "publish_version: exit",
        extra={"version_id": version_id, "elapsed_ms": elapsed_ms},
    )
    return published_version


def get_version(version_id: str) -> Optional[AgentVersion]:
    """Fetch a single AgentVersion by id.

    Args:
        version_id: AgentVersion.id (FK target).

    Returns:
        AgentVersion if found, else None. Returns None on engine unavailable.
    """
    logger.info("get_version: entry", extra={"version_id": version_id})

    if _engine is None:
        return _inmem_versions.get(version_id)

    try:
        from sqlalchemy import text

        with _engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT id, agent_id, semver, changelog, status, config,
                           published_at, published_by
                    FROM agent_versions
                    WHERE id = :version_id
                    """
                ),
                {"version_id": version_id},
            ).fetchone()

        if row is None:
            return None
        return _row_to_version(row)

    except Exception as exc:
        logger.error(f"get_version: query failed for version_id={version_id}: {exc}", exc_info=True)
        raise


def list_versions(agent_id: str) -> list[AgentVersion]:
    """List all versions for an agent, ordered by creation (oldest first).

    Args:
        agent_id: FK to Agent.id.

    Returns:
        List of AgentVersion instances. Empty list if none found or engine down.
    """
    logger.info("list_versions: entry", extra={"agent_id": agent_id})

    if _engine is None:
        return sorted(
            [v for v in _inmem_versions.values() if v.agent_id == agent_id],
            key=lambda v: v.id,
        )

    try:
        from sqlalchemy import text

        with _engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT id, agent_id, semver, changelog, status, config,
                           published_at, published_by
                    FROM agent_versions
                    WHERE agent_id = :agent_id
                    ORDER BY id
                    """
                ),
                {"agent_id": agent_id},
            ).fetchall()

        versions = [_row_to_version(r) for r in rows]
        logger.info("list_versions: exit", extra={"agent_id": agent_id, "count": len(versions)})
        return versions

    except Exception as exc:
        logger.error(f"list_versions: query failed for agent_id={agent_id}: {exc}", exc_info=True)
        raise


# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------

_SEED_AGENTS: list[dict] = [
    # Team-owned
    {
        "agent_id": "ai-agent-pay-fraud",
        "name": "Payment Fraud Detector",
        "description": "Detects fraudulent payment patterns using transaction context.",
        "team": "payments",
        "owner_type": AgentOwnerType.CUSTOM,
        "inherent_risk": RiskLevel.HIGH,
        "framework_refs": ["NIST_AI_RMF:GOVERN-1.1", "SR_11_7:MRM-1"],
        "semver": "1.0.0",
        "changelog": "Initial release — rule-based fraud pattern matching.",
    },
    {
        "agent_id": "ai-agent-cx-router",
        "name": "CX Intent Router",
        "description": "Routes customer queries to the appropriate service channel.",
        "team": "cx",
        "owner_type": AgentOwnerType.CUSTOM,
        "inherent_risk": RiskLevel.MEDIUM,
        "framework_refs": ["OWASP_LLM_TOP10:LLM01"],
        "semver": "1.0.0",
        "changelog": "Initial release — intent classification with confidence thresholds.",
    },
    {
        "agent_id": "ai-agent-risk-classifier",
        "name": "Risk Tier Classifier",
        "description": "Classifies incoming AI workloads into risk tiers for governance routing.",
        "team": "risk",
        "owner_type": AgentOwnerType.CUSTOM,
        "inherent_risk": RiskLevel.HIGH,
        "framework_refs": ["SR_11_7:MRM-2", "EU_AI_ACT:Art.9"],
        "semver": "1.0.0",
        "changelog": "Initial release — five-tier risk classification model.",
    },
    # Reusable
    {
        "agent_id": "ai-agent-pii-redactor",
        "name": "PII Redactor",
        "description": "Detects and redacts personally identifiable information from text.",
        "team": "platform",
        "owner_type": AgentOwnerType.REUSABLE,
        "inherent_risk": RiskLevel.CRITICAL,
        "framework_refs": ["NIST_AI_RMF:MANAGE-1.1", "EU_AI_ACT:Art.10", "GDPR:Art.25"],
        "semver": "1.0.0",
        "changelog": "Initial release — Presidio NER + regex layer.",
    },
    {
        "agent_id": "ai-agent-sentiment",
        "name": "Sentiment Analyser",
        "description": "Classifies text sentiment (positive/negative/neutral) for customer feedback.",
        "team": "platform",
        "owner_type": AgentOwnerType.REUSABLE,
        "inherent_risk": RiskLevel.LOW,
        "framework_refs": [],
        "semver": "1.0.0",
        "changelog": "Initial release — lightweight sentiment classification.",
    },
    {
        "agent_id": "ai-agent-doc-summarizer",
        "name": "Document Summariser",
        "description": "Summarises long documents into structured briefs for analyst review.",
        "team": "platform",
        "owner_type": AgentOwnerType.REUSABLE,
        "inherent_risk": RiskLevel.MEDIUM,
        "framework_refs": ["NIST_AI_RMF:GOVERN-1.2"],
        "semver": "1.0.0",
        "changelog": "Initial release — extractive + abstractive summarisation pipeline.",
    },
    # ------------------------------------------------------------------
    # S82f-2: backfill runtime-registry agents into the domain registry
    # so the Agent Library page (/api/agents → /agent-library) surfaces
    # them. These mirror entries in agents/_registry.py; the runtime
    # registry is the source of truth for execution, the domain entries
    # below are for catalog visibility + versioning + framework mapping.
    #
    # Pattern: agent_id matches the runtime registry slug exactly so
    # cross-references (bindings, evidence, audit) join correctly.
    # ------------------------------------------------------------------
    {
        "agent_id": "vendor_risk",
        "name": "Third-Party Vendor Risk Analyzer",
        "description": (
            "Reviews a vendor package (SOC 2, ISO 27001, DPA, subprocessor "
            "list, security questionnaire) and returns a structured risk "
            "tier with concerns, citations, and mitigations. Two AI systems: "
            "EXT (sys-vendor-risk-ext-001, cloud LLM) and INT "
            "(sys-vendor-risk-int-001, internal-policy-controlled). INT "
            "requires runtime-flag attestation (dlp_completed + "
            "network_egress_lock_engaged) per ADR-004."
        ),
        "team": "risk",
        "owner_type": AgentOwnerType.REUSABLE,
        "inherent_risk": RiskLevel.HIGH,
        "framework_refs": [
            "NIST_AI_RMF:MANAGE-2.1",
            "NIST_AI_RMF:GOVERN-6.1",
            "OWASP_LLM_TOP10:LLM01",
            "OWASP_LLM_TOP10:LLM05",
            "US_FINSERV_OVERLAY:AI-006",
        ],
        "semver": "1.0.0",
        "changelog": (
            "Initial release — locked baseline 17/18 (S82e) · 10/10 EXT "
            "tier-match · INT calibration unblocked S82f-2 via "
            "ADR-004 Option B (sticky PATCH runtime-flag attestation)."
        ),
    },
]


def seed_agents() -> list[Agent]:
    """Create 6 seed agents (3 CUSTOM, 3 REUSABLE) each with v1.0.0 published.

    Idempotent — uses ON CONFLICT DO NOTHING on agent INSERT and UNIQUE on
    (agent_id, semver) for versions.  Safe to call multiple times.

    Returns:
        List of Agent instances (fetched from DB after seeding, or created in-memory
        if engine unavailable).
    """
    logger.info("seed_agents: entry")

    created: list[Agent] = []

    for spec in _SEED_AGENTS:
        try:
            agent = create_agent(
                name=spec["name"],
                description=spec["description"],
                team=spec["team"],
                owner_type=spec["owner_type"],
                inherent_risk=spec["inherent_risk"],
                framework_refs=spec["framework_refs"],
                agent_id=spec["agent_id"],
            )

            # Create and immediately publish v1.0.0
            try:
                version = create_version(
                    agent_id=agent.id,
                    semver=spec["semver"],
                    changelog=spec["changelog"],
                    config={},
                )
                publish_version(version.id, published_by="seed_agents")
            except Exception as ver_exc:
                # ON CONFLICT for semver — version already exists; skip
                logger.debug(f"seed_agents: version already exists for {agent.id}: {ver_exc}")

            # Re-fetch to get latest_version_id populated
            refreshed = get_agent(agent.id)
            created.append(refreshed if refreshed is not None else agent)

        except Exception as exc:
            logger.warning(f"seed_agents: failed to seed agent {spec['agent_id']}: {exc}")

    logger.info("seed_agents: exit", extra={"seeded": len(created)})
    return created


__all__ = [
    "create_agent",
    "get_agent",
    "list_agents",
    "create_version",
    "publish_version",
    "list_versions",
    "seed_agents",
]
