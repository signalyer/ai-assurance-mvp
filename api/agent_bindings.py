"""FastAPI router for Agent Binding endpoints — Session 07.

Endpoints:
    GET    /api/systems/{system_id}/bindings
    POST   /api/systems/{system_id}/bindings
    PATCH  /api/systems/{system_id}/bindings/{binding_id}
    DELETE /api/systems/{system_id}/bindings/{binding_id}

All domain calls are sync (Postgres); dispatched via asyncio.to_thread.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict, field_validator


class AgentBindingOut(BaseModel):
    """AgentBinding record. Loosely typed; underlying shape from domain.agent_bindings.

    list_bindings returns enriched dicts with agent_name/agent_team/version_semver
    added on top of the binding fields; extra='allow' permits the enrichment.
    """
    model_config = ConfigDict(extra="allow")
    id: str
    system_id: str
    agent_id: str

logger = logging.getLogger(__name__)

router = APIRouter(tags=["agent-bindings"])

# ---------------------------------------------------------------------------
# Lazy domain imports
# ---------------------------------------------------------------------------

def _agent_bindings():
    """Lazy import of domain.agent_bindings."""
    try:
        import domain.agent_bindings as m  # type: ignore[import]
        return m
    except ModuleNotFoundError as exc:
        logger.error("domain.agent_bindings not available: %s", exc)
        raise HTTPException(
            status_code=503,
            detail={"error": "Agent bindings domain not available", "code": "DOMAIN_UNAVAILABLE"},
        )


def _agents():
    """Lazy import of domain.agents."""
    try:
        import domain.agents as m  # type: ignore[import]
        return m
    except ModuleNotFoundError as exc:
        logger.error("domain.agents not available: %s", exc)
        raise HTTPException(
            status_code=503,
            detail={"error": "Agent domain not available", "code": "DOMAIN_UNAVAILABLE"},
        )


def _agent_subscribers():
    """Lazy import of domain.agent_subscribers."""
    try:
        import domain.agent_subscribers as m  # type: ignore[import]
        return m
    except ModuleNotFoundError as exc:
        logger.error("domain.agent_subscribers not available: %s", exc)
        raise HTTPException(
            status_code=503,
            detail={"error": "Agent subscribers domain not available", "code": "DOMAIN_UNAVAILABLE"},
        )


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class CreateBindingRequest(BaseModel):
    """Body for POST /api/systems/{system_id}/bindings."""

    model_config = ConfigDict(str_strip_whitespace=True)

    agent_id: str
    version_id: str | None = None
    pinned: bool = False

    @field_validator("agent_id")
    @classmethod
    def agent_id_nonempty(cls, v: str) -> str:
        """Reject blank agent_id at the boundary."""
        if not v:
            raise ValueError("agent_id must not be empty")
        return v


class UpdateBindingRequest(BaseModel):
    """Body for PATCH /api/systems/{system_id}/bindings/{binding_id}."""

    model_config = ConfigDict(str_strip_whitespace=True)

    version_id: str | None = None
    pinned: bool | None = None
    accept_upgrade: bool | None = None


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def _binding_to_dict(binding: object) -> dict[str, object]:
    """Convert a domain AgentBinding object to a serialisable dict."""
    if hasattr(binding, "model_dump"):
        return binding.model_dump()  # type: ignore[return-value]
    if hasattr(binding, "__dict__"):
        return {k: v for k, v in binding.__dict__.items() if not k.startswith("_")}  # type: ignore[return-value]
    return {}


def _enrich_binding(
    binding_dict: dict[str, object],
    agents_map: dict[str, object],
    versions_map: dict[str, object],
) -> dict[str, object]:
    """Enrich a binding dict with agent name and version semver."""
    agent_id = str(binding_dict.get("agent_id") or "")
    version_id = str(binding_dict.get("version_id") or "")

    agent = agents_map.get(agent_id)
    if agent is not None:
        if hasattr(agent, "model_dump"):
            ad = agent.model_dump()  # type: ignore[union-attr]
        elif hasattr(agent, "__dict__"):
            ad = {k: v for k, v in agent.__dict__.items() if not k.startswith("_")}
        else:
            ad = {}
        binding_dict["agent_name"] = ad.get("name", "")
        binding_dict["agent_team"] = ad.get("team", "")
        binding_dict["agent_owner_type"] = ad.get("owner_type", "")

    version = versions_map.get(version_id)
    if version is not None:
        if hasattr(version, "model_dump"):
            vd = version.model_dump()  # type: ignore[union-attr]
        elif hasattr(version, "__dict__"):
            vd = {k: v for k, v in version.__dict__.items() if not k.startswith("_")}
        else:
            vd = {}
        binding_dict["version_semver"] = vd.get("semver", "")

    return binding_dict


# ---------------------------------------------------------------------------
# GET /api/systems/{system_id}/bindings
# ---------------------------------------------------------------------------

@router.get(
    "/api/systems/{system_id}/bindings",
    response_model=list[AgentBindingOut],
    operation_id="bindings_list",
)
async def list_bindings(system_id: str) -> list[dict[str, object]]:
    """Return all agent bindings for a system, enriched with agent name + version semver.

    Delegates to domain.agent_bindings.list_bindings_for_system().
    Returns 404 if system does not exist (domain raises LookupError).
    """
    start = datetime.now(tz=timezone.utc)
    logger.info("bindings.list.enter system_id=%s", system_id)

    b_mod = _agent_bindings()
    a_mod = _agents()

    try:
        bindings = await asyncio.to_thread(b_mod.list_bindings_for_system, system_id=system_id)
    except HTTPException:
        raise
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"error": str(exc), "code": "NOT_FOUND"})
    except Exception as exc:
        logger.error("bindings.list failed: system_id=%s error=%s", system_id, str(exc)[:200])
        raise HTTPException(status_code=500, detail={"error": "Failed to list bindings", "code": "LIST_FAILED"})

    binding_dicts = [_binding_to_dict(b) for b in bindings]

    # Gather unique agent_ids and version_ids for enrichment
    agent_ids = {str(d.get("agent_id") or "") for d in binding_dicts if d.get("agent_id")}
    version_ids = {str(d.get("version_id") or "") for d in binding_dicts if d.get("version_id")}

    # Fetch agents concurrently
    agents_results = await asyncio.gather(
        *[asyncio.to_thread(a_mod.get_agent, agent_id=aid) for aid in agent_ids],
        return_exceptions=True,
    )
    agents_map: dict[str, object] = {}
    for aid, result in zip(agent_ids, agents_results):
        if not isinstance(result, Exception) and result is not None:
            agents_map[aid] = result

    # Fetch versions concurrently
    versions_results = await asyncio.gather(
        *[asyncio.to_thread(a_mod.get_version, version_id=vid) for vid in version_ids],
        return_exceptions=True,
    )
    versions_map: dict[str, object] = {}
    for vid, result in zip(version_ids, versions_results):
        if not isinstance(result, Exception) and result is not None:
            versions_map[vid] = result

    enriched = [_enrich_binding(d, agents_map, versions_map) for d in binding_dicts]
    elapsed_ms = (datetime.now(tz=timezone.utc) - start).total_seconds() * 1000
    logger.info("bindings.list.exit system_id=%s count=%d elapsed_ms=%.1f", system_id, len(enriched), elapsed_ms)
    return enriched


# ---------------------------------------------------------------------------
# POST /api/systems/{system_id}/bindings
# ---------------------------------------------------------------------------

@router.post(
    "/api/systems/{system_id}/bindings",
    status_code=201,
    response_model=AgentBindingOut,
    operation_id="bindings_create",
)
async def create_binding(system_id: str, body: CreateBindingRequest) -> dict[str, object]:
    """Bind an agent to a system.

    Returns 201 + the created AgentBinding.
    Returns 400 if agent_id does not exist.
    Delegates to domain.agent_bindings.bind_agent_to_system() and
    domain.agent_subscribers.subscribe().
    """
    start = datetime.now(tz=timezone.utc)
    logger.info(
        "bindings.create.enter system_id=%s agent_id=%s pinned=%s",
        system_id,
        body.agent_id,
        body.pinned,
    )

    b_mod = _agent_bindings()
    a_mod = _agents()
    s_mod = _agent_subscribers()

    # Validate agent exists
    agent = await asyncio.to_thread(a_mod.get_agent, agent_id=body.agent_id)
    if agent is None:
        raise HTTPException(
            status_code=400,
            detail={"error": f"Agent '{body.agent_id}' does not exist", "code": "AGENT_NOT_FOUND"},
        )

    try:
        binding = await asyncio.to_thread(
            b_mod.bind_agent_to_system,
            system_id=system_id,
            agent_id=body.agent_id,
            version_id=body.version_id,
            pinned=body.pinned,
        )
    except HTTPException:
        raise
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"error": str(exc), "code": "NOT_FOUND"})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc), "code": "VALIDATION_ERROR"})
    except Exception as exc:
        logger.error(
            "bindings.create failed: system_id=%s agent_id=%s error=%s",
            system_id,
            body.agent_id,
            str(exc)[:200],
        )
        raise HTTPException(status_code=500, detail={"error": "Failed to create binding", "code": "CREATE_FAILED"})

    binding_dict = _binding_to_dict(binding)

    # Subscribe system to agent for version notifications (best-effort)
    binding_id = str(binding_dict.get("id") or binding_dict.get("binding_id") or "")
    try:
        await asyncio.to_thread(
            s_mod.subscribe,
            agent_id=body.agent_id,
            system_id=system_id,
        )
    except Exception as exc:
        logger.error(
            "bindings.create subscribe failed: system_id=%s agent_id=%s error=%s",
            system_id,
            body.agent_id,
            str(exc)[:200],
        )

    elapsed_ms = (datetime.now(tz=timezone.utc) - start).total_seconds() * 1000
    logger.info(
        "bindings.create.exit system_id=%s binding_id=%s elapsed_ms=%.1f",
        system_id,
        binding_id,
        elapsed_ms,
    )
    return binding_dict


# ---------------------------------------------------------------------------
# PATCH /api/systems/{system_id}/bindings/{binding_id}
# ---------------------------------------------------------------------------

@router.patch(
    "/api/systems/{system_id}/bindings/{binding_id}",
    response_model=AgentBindingOut,
    operation_id="bindings_update",
)
async def update_binding(
    system_id: str,
    binding_id: str,
    body: UpdateBindingRequest,
) -> dict[str, object]:
    """Update a binding's version, pinned flag, or accept a pending upgrade.

    Returns 404 if binding does not exist or belongs to a different system.
    Delegates to domain.agent_bindings.update_binding_version() or accept_upgrade().
    """
    start = datetime.now(tz=timezone.utc)
    logger.info(
        "bindings.update.enter system_id=%s binding_id=%s",
        system_id,
        binding_id,
    )

    b_mod = _agent_bindings()

    # Ownership check: binding must belong to this system
    existing = await asyncio.to_thread(
        b_mod.get_binding,
        binding_id=binding_id,
        system_id=system_id,
    )
    if existing is None:
        raise HTTPException(
            status_code=404,
            detail={"error": f"Binding '{binding_id}' not found for system '{system_id}'", "code": "NOT_FOUND"},
        )

    try:
        if body.accept_upgrade:
            updated = await asyncio.to_thread(
                b_mod.accept_upgrade,
                binding_id=binding_id,
            )
        else:
            updated = await asyncio.to_thread(
                b_mod.update_binding_version,
                binding_id=binding_id,
                version_id=body.version_id,
                pinned=body.pinned,
            )
    except HTTPException:
        raise
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"error": str(exc), "code": "NOT_FOUND"})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc), "code": "VALIDATION_ERROR"})
    except Exception as exc:
        logger.error(
            "bindings.update failed: system_id=%s binding_id=%s error=%s",
            system_id,
            binding_id,
            str(exc)[:200],
        )
        raise HTTPException(
            status_code=500,
            detail={"error": "Failed to update binding", "code": "UPDATE_FAILED"},
        )

    result = _binding_to_dict(updated)
    elapsed_ms = (datetime.now(tz=timezone.utc) - start).total_seconds() * 1000
    logger.info(
        "bindings.update.exit system_id=%s binding_id=%s elapsed_ms=%.1f",
        system_id,
        binding_id,
        elapsed_ms,
    )
    return result


# ---------------------------------------------------------------------------
# DELETE /api/systems/{system_id}/bindings/{binding_id}
# ---------------------------------------------------------------------------

@router.delete(
    "/api/systems/{system_id}/bindings/{binding_id}",
    status_code=204,
    operation_id="bindings_delete",
)
async def delete_binding(system_id: str, binding_id: str) -> Response:
    """Remove a binding and unsubscribe the system from agent notifications.

    Returns 204 on success.
    Returns 404 if binding does not exist.
    """
    start = datetime.now(tz=timezone.utc)
    logger.info(
        "bindings.delete.enter system_id=%s binding_id=%s",
        system_id,
        binding_id,
    )

    b_mod = _agent_bindings()
    s_mod = _agent_subscribers()

    # Fetch binding first to get agent_id for unsubscribe
    agent_id: str | None = None
    try:
        existing = await asyncio.to_thread(
            b_mod.get_binding,
            binding_id=binding_id,
            system_id=system_id,
        )
        if existing is None:
            raise HTTPException(
                status_code=404,
                detail={"error": f"Binding '{binding_id}' not found", "code": "NOT_FOUND"},
            )
        bd = _binding_to_dict(existing)
        agent_id = str(bd.get("agent_id") or "")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "bindings.delete fetch failed: system_id=%s binding_id=%s error=%s",
            system_id,
            binding_id,
            str(exc)[:200],
        )
        raise HTTPException(
            status_code=500,
            detail={"error": "Failed to fetch binding", "code": "FETCH_FAILED"},
        )

    try:
        await asyncio.to_thread(
            b_mod.unbind_agent,
            binding_id=binding_id,
            system_id=system_id,
        )
    except HTTPException:
        raise
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"error": str(exc), "code": "NOT_FOUND"})
    except Exception as exc:
        logger.error(
            "bindings.delete unbind failed: system_id=%s binding_id=%s error=%s",
            system_id,
            binding_id,
            str(exc)[:200],
        )
        raise HTTPException(
            status_code=500,
            detail={"error": "Failed to delete binding", "code": "DELETE_FAILED"},
        )

    # Unsubscribe — best-effort
    if agent_id:
        try:
            await asyncio.to_thread(
                s_mod.unsubscribe,
                agent_id=agent_id,
                system_id=system_id,
            )
        except Exception as exc:
            logger.error(
                "bindings.delete unsubscribe failed: system_id=%s agent_id=%s error=%s",
                system_id,
                agent_id,
                str(exc)[:200],
            )

    elapsed_ms = (datetime.now(tz=timezone.utc) - start).total_seconds() * 1000
    logger.info(
        "bindings.delete.exit system_id=%s binding_id=%s elapsed_ms=%.1f",
        system_id,
        binding_id,
        elapsed_ms,
    )
    return Response(status_code=204)
