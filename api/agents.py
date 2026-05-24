"""FastAPI router for Agent Library endpoints — Session 07.

Endpoints:
    GET  /api/agents                         list agents
    POST /api/agents                         create agent
    GET  /api/agents/{agent_id}              get agent + versions + subscribers
    POST /api/agents/{agent_id}/publish      publish new version
    GET  /api/agents/{agent_id}/subscribers  list subscribers with binding state

All domain calls are sync (Postgres); dispatched via asyncio.to_thread.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, field_validator

# Session 13 typing: loosely-typed Agent/Version/Subscriber response models.
# Underlying domain models (domain.agents.Agent etc.) carry the authoritative
# field list; duplicating here creates drift. extra='allow' so domain field
# additions don't break the API surface immediately -- tighten in Phase 1.5.


class AgentOut(BaseModel):
    """Agent record. Loosely typed; underlying shape from domain.agents.Agent."""
    model_config = ConfigDict(extra="allow")
    id: str
    name: str
    team: str


class AgentVersionOut(BaseModel):
    """AgentVersion record. Loosely typed; underlying shape from domain.agents.AgentVersion."""
    model_config = ConfigDict(extra="allow")
    id: str
    agent_id: str
    semver: str


class AgentSubscriberOut(BaseModel):
    """AgentSubscriber record. Loosely typed; underlying shape from domain.agent_subscribers."""
    model_config = ConfigDict(extra="allow")
    agent_id: str
    system_id: str


class AgentDetailOut(AgentOut):
    """Agent + versions + subscribers (nested)."""
    versions: list[AgentVersionOut] = []
    subscribers: list[AgentSubscriberOut] = []

logger = logging.getLogger(__name__)

router = APIRouter(tags=["agents"])

# ---------------------------------------------------------------------------
# Lazy domain imports — tolerate absent module until Implementer 1 lands
# ---------------------------------------------------------------------------

def _agents():
    """Lazy import of domain.agents."""
    try:
        import domain.agents as m  # type: ignore[import]
        return m
    except ModuleNotFoundError as exc:
        logger.error("domain.agents not available: %s", exc)
        raise HTTPException(status_code=503, detail={"error": "Agent domain not available", "code": "DOMAIN_UNAVAILABLE"})


def _agent_subscribers():
    """Lazy import of domain.agent_subscribers."""
    try:
        import domain.agent_subscribers as m  # type: ignore[import]
        return m
    except ModuleNotFoundError as exc:
        logger.error("domain.agent_subscribers not available: %s", exc)
        raise HTTPException(status_code=503, detail={"error": "Agent subscribers domain not available", "code": "DOMAIN_UNAVAILABLE"})


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class CreateAgentRequest(BaseModel):
    """Body for POST /api/agents."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str
    description: str = ""
    team: str
    owner_type: Literal["CUSTOM", "REUSABLE"]
    inherent_risk: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "MEDIUM"

    @field_validator("name")
    @classmethod
    def name_nonempty(cls, v: str) -> str:
        """Reject blank name at the boundary."""
        if not v:
            raise ValueError("name must not be empty")
        return v

    @field_validator("team")
    @classmethod
    def team_nonempty(cls, v: str) -> str:
        """Reject blank team at the boundary."""
        if not v:
            raise ValueError("team must not be empty")
        return v


class PublishVersionRequest(BaseModel):
    """Body for POST /api/agents/{agent_id}/publish."""

    model_config = ConfigDict(str_strip_whitespace=True)

    semver: str
    changelog: str = ""
    config: dict[str, object] = {}

    @field_validator("semver")
    @classmethod
    def semver_format(cls, v: str) -> str:
        """Validate semver format: MAJOR.MINOR.PATCH."""
        import re
        pattern = r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([\w.-]+))?(?:\+([\w.-]+))?$"
        if not re.match(pattern, v.strip()):
            raise ValueError(f"semver must match MAJOR.MINOR.PATCH format, got: {v!r}")
        return v.strip()


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def _agent_to_dict(agent: object) -> dict[str, object]:
    """Convert a domain Agent object to a serialisable dict."""
    if hasattr(agent, "model_dump"):
        return agent.model_dump()  # type: ignore[return-value]
    if hasattr(agent, "__dict__"):
        return {k: v for k, v in agent.__dict__.items() if not k.startswith("_")}  # type: ignore[return-value]
    return {}


def _to_iso(val: object) -> str | None:
    """Convert a datetime-like value to ISO 8601 string, or None."""
    if val is None:
        return None
    if hasattr(val, "isoformat"):
        return val.isoformat()  # type: ignore[union-attr]
    return str(val)


# ---------------------------------------------------------------------------
# GET /api/agents
# ---------------------------------------------------------------------------

@router.get(
    "/api/agents",
    response_model=list[AgentOut],
    operation_id="agents_list",
)
async def list_agents(
    team: str | None = Query(None, description="Filter by team"),
    owner_type: str | None = Query(None, description="Filter by owner_type (CUSTOM|REUSABLE)"),
) -> list[dict[str, object]]:
    """Return a list of agents, optionally filtered by team and/or owner_type.

    Returns serialised Agent dicts. Delegates to domain.agents.list_agents().
    """
    start = datetime.now(tz=timezone.utc)
    logger.info("agents.list.enter team=%s owner_type=%s", team, owner_type)

    mod = _agents()
    try:
        agents = await asyncio.to_thread(mod.list_agents, team=team, owner_type=owner_type)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("agents.list failed: %s", str(exc)[:200])
        raise HTTPException(status_code=500, detail={"error": "Failed to list agents", "code": "LIST_FAILED"})

    result = [_agent_to_dict(a) for a in agents]
    elapsed_ms = (datetime.now(tz=timezone.utc) - start).total_seconds() * 1000
    logger.info("agents.list.exit count=%d elapsed_ms=%.1f", len(result), elapsed_ms)
    return result


# ---------------------------------------------------------------------------
# POST /api/agents
# ---------------------------------------------------------------------------

@router.post(
    "/api/agents",
    status_code=201,
    response_model=AgentOut,
    operation_id="agents_create",
)
async def create_agent(body: CreateAgentRequest) -> dict[str, object]:
    """Create a new agent in the registry.

    Returns 201 + the created Agent object.
    Delegates to domain.agents.create_agent().
    """
    start = datetime.now(tz=timezone.utc)
    logger.info("agents.create.enter name=%s team=%s owner_type=%s", body.name, body.team, body.owner_type)

    mod = _agents()
    # domain.agents.create_agent expects enums (AgentOwnerType, RiskLevel) and
    # calls .value on them. Pydantic Literal validates the string but does not
    # coerce; coerce at the boundary.
    from domain.models import AgentOwnerType, RiskLevel
    try:
        agent = await asyncio.to_thread(
            mod.create_agent,
            name=body.name,
            description=body.description,
            team=body.team,
            owner_type=AgentOwnerType(body.owner_type),
            inherent_risk=RiskLevel(body.inherent_risk),
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc), "code": "VALIDATION_ERROR"})
    except Exception as exc:
        logger.error("agents.create failed: name=%s error=%s", body.name, str(exc)[:200])
        raise HTTPException(status_code=500, detail={"error": "Failed to create agent", "code": "CREATE_FAILED"})

    result = _agent_to_dict(agent)
    elapsed_ms = (datetime.now(tz=timezone.utc) - start).total_seconds() * 1000
    logger.info(
        "agents.create.exit agent_id=%s elapsed_ms=%.1f",
        result.get("id") or result.get("agent_id"),
        elapsed_ms,
    )
    return result


# ---------------------------------------------------------------------------
# GET /api/agents/{agent_id}
# ---------------------------------------------------------------------------

@router.get(
    "/api/agents/{agent_id}",
    response_model=AgentDetailOut,
    operation_id="agents_get",
)
async def get_agent(agent_id: str) -> dict[str, object]:
    """Return a single agent with its version history and subscriber list.

    Returns 404 if the agent does not exist.
    Calls domain.agents.get_agent() + list_versions() + domain.agent_subscribers.list_subscribers()
    concurrently.
    """
    start = datetime.now(tz=timezone.utc)
    logger.info("agents.get.enter agent_id=%s", agent_id)

    a_mod = _agents()
    s_mod = _agent_subscribers()

    try:
        agent_task = asyncio.to_thread(a_mod.get_agent, agent_id=agent_id)
        versions_task = asyncio.to_thread(a_mod.list_versions, agent_id=agent_id)
        subscribers_task = asyncio.to_thread(s_mod.list_subscribers, agent_id=agent_id)

        agent, versions, subscribers = await asyncio.gather(
            agent_task, versions_task, subscribers_task, return_exceptions=True
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("agents.get gather failed: agent_id=%s error=%s", agent_id, str(exc)[:200])
        raise HTTPException(status_code=500, detail={"error": "Failed to fetch agent", "code": "FETCH_FAILED"})

    if isinstance(agent, Exception):
        logger.error("agents.get agent error: agent_id=%s error=%s", agent_id, str(agent)[:200])
        raise HTTPException(status_code=404, detail={"error": f"Agent '{agent_id}' not found", "code": "NOT_FOUND"})

    if agent is None:
        raise HTTPException(status_code=404, detail={"error": f"Agent '{agent_id}' not found", "code": "NOT_FOUND"})

    result = _agent_to_dict(agent)
    result["versions"] = [_agent_to_dict(v) for v in (versions if not isinstance(versions, Exception) else [])]
    result["subscribers"] = [_agent_to_dict(s) for s in (subscribers if not isinstance(subscribers, Exception) else [])]

    elapsed_ms = (datetime.now(tz=timezone.utc) - start).total_seconds() * 1000
    logger.info("agents.get.exit agent_id=%s elapsed_ms=%.1f", agent_id, elapsed_ms)
    return result


# ---------------------------------------------------------------------------
# POST /api/agents/{agent_id}/publish
# ---------------------------------------------------------------------------

@router.post(
    "/api/agents/{agent_id}/publish",
    status_code=201,
    response_model=AgentVersionOut,
    operation_id="agents_publish_version",
)
async def publish_version(agent_id: str, body: PublishVersionRequest) -> dict[str, object]:
    """Create and publish a new version for the given agent.

    Returns 201 + the new AgentVersion.
    Triggers subscriber notifications via domain.agent_subscribers.notify_subscribers_on_publish().
    Returns 404 if the agent does not exist.
    Returns 400 if the semver is already taken or invalid.
    """
    start = datetime.now(tz=timezone.utc)
    logger.info(
        "agents.publish.enter agent_id=%s semver=%s",
        agent_id,
        body.semver,
    )

    a_mod = _agents()
    s_mod = _agent_subscribers()

    try:
        version = await asyncio.to_thread(
            a_mod.create_version,
            agent_id=agent_id,
            semver=body.semver,
            changelog=body.changelog,
            config=body.config,
        )
    except HTTPException:
        raise
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"error": str(exc), "code": "NOT_FOUND"})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc), "code": "VALIDATION_ERROR"})
    except Exception as exc:
        logger.error(
            "agents.publish create_version failed: agent_id=%s semver=%s error=%s",
            agent_id,
            body.semver,
            str(exc)[:200],
        )
        raise HTTPException(status_code=500, detail={"error": "Failed to create version", "code": "CREATE_FAILED"})

    version_dict = _agent_to_dict(version)
    version_id = str(version_dict.get("id") or version_dict.get("version_id") or "")

    try:
        await asyncio.to_thread(
            a_mod.publish_version,
            version_id=version_id,
            published_by="api",
        )
    except Exception as exc:
        logger.error(
            "agents.publish publish_version failed: version_id=%s error=%s",
            version_id,
            str(exc)[:200],
        )
        raise HTTPException(
            status_code=500,
            detail={"error": "Version created but publish failed", "code": "PUBLISH_FAILED", "version_id": version_id},
        )

    try:
        await asyncio.to_thread(
            s_mod.notify_subscribers_on_publish,
            agent_id=agent_id,
            new_version_id=version_id,
        )
    except Exception as exc:
        logger.error(
            "agents.publish notify_subscribers failed: agent_id=%s error=%s",
            agent_id,
            str(exc)[:200],
        )
        # Non-fatal: notifications are best-effort

    elapsed_ms = (datetime.now(tz=timezone.utc) - start).total_seconds() * 1000
    logger.info(
        "agents.publish.exit agent_id=%s version_id=%s elapsed_ms=%.1f",
        agent_id,
        version_id,
        elapsed_ms,
    )
    return version_dict


# ---------------------------------------------------------------------------
# GET /api/agents/{agent_id}/subscribers
# ---------------------------------------------------------------------------

@router.get(
    "/api/agents/{agent_id}/subscribers",
    response_model=list[AgentSubscriberOut],
    operation_id="agents_subscribers_list",
)
async def list_agent_subscribers(agent_id: str) -> list[dict[str, object]]:
    """Return the list of AgentSubscribers with their binding state.

    Returns 404 if the agent does not exist.
    Delegates to domain.agent_subscribers.list_subscribers().
    """
    start = datetime.now(tz=timezone.utc)
    logger.info("agents.subscribers.enter agent_id=%s", agent_id)

    a_mod = _agents()
    s_mod = _agent_subscribers()

    agent = await asyncio.to_thread(a_mod.get_agent, agent_id=agent_id)
    if agent is None:
        raise HTTPException(
            status_code=404,
            detail={"error": f"Agent '{agent_id}' not found", "code": "NOT_FOUND"},
        )

    try:
        subscribers = await asyncio.to_thread(s_mod.list_subscribers, agent_id=agent_id)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "agents.subscribers failed: agent_id=%s error=%s",
            agent_id,
            str(exc)[:200],
        )
        raise HTTPException(status_code=500, detail={"error": "Failed to list subscribers", "code": "LIST_FAILED"})

    result = [_agent_to_dict(s) for s in subscribers]
    elapsed_ms = (datetime.now(tz=timezone.utc) - start).total_seconds() * 1000
    logger.info(
        "agents.subscribers.exit agent_id=%s count=%d elapsed_ms=%.1f",
        agent_id,
        len(result),
        elapsed_ms,
    )
    return result
