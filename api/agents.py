"""FastAPI router for Agent Library endpoints — Session 07.

Endpoints:
    GET  /api/agents                         list agents
    POST /api/agents                         create agent
    GET  /api/agents/{agent_id}              get agent + versions + subscribers
    POST /api/agents/{agent_id}/publish      publish new version
    GET  /api/agents/{agent_id}/subscribers  list subscribers with binding state
    GET  /api/agents/{agent_id}/eval-summary suite-level eval visibility (S82f-2-extended item 10)

All domain calls are sync (Postgres); dispatched via asyncio.to_thread.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, field_validator

from middleware.data_mode import filter_by_mode, get_data_mode

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
    request: Request,
    team: str | None = Query(None, description="Filter by team"),
    owner_type: str | None = Query(None, description="Filter by owner_type (CUSTOM|REUSABLE)"),
) -> list[dict[str, object]]:
    """Return a list of agents, optionally filtered by team and/or owner_type.

    Returns serialised Agent dicts. Delegates to domain.agents.list_agents().
    Honors X-Data-Mode (v1|v2): V2 hides seed agents.
    """
    start = datetime.now(tz=timezone.utc)
    logger.info("agents.list.enter team=%s owner_type=%s", team, owner_type)

    mod = _agents()
    try:
        agents = await asyncio.to_thread(mod.list_agents, team=team, owner_type=owner_type)
        agents = filter_by_mode(agents, get_data_mode(request))
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


# ---------------------------------------------------------------------------
# GET /api/agents/{agent_id}/eval-summary  (S82f-2-extended item 10 — E1)
# ---------------------------------------------------------------------------
#
# Surfaces the suite-level eval signal that already exists on disk but had no
# UI binding (sibling of [[ui-promise-audit-owed]]). Reads:
#   - agents/<agent_id>/eval/baseline.json    → locked baseline run
#   - data/<agent_id>_eval_runs.jsonl         → every suite run since baseline
# via the canonical DATA_ROOT pattern (2026-06-01 rule).
#
# Agents without an eval suite (finadvice, azure-architect today — both
# demo_only) return has_eval_suite=False so the SPA can render an honest
# "no eval suite — demo-only" affordance rather than blanking.

_DATA_DIR_AGENTS: Path = Path(os.environ.get("DATA_ROOT") or (Path(__file__).resolve().parents[1] / "data"))
_REPO_ROOT_AGENTS: Path = Path(__file__).resolve().parents[1]


def _summarize_run(run: dict[str, Any], *, include_cases: bool = False) -> dict[str, Any]:
    """Reduce one suite-run record to its headline fields + per-system split.

    Source shape is per agents/<agent>/eval/run_eval.py; we re-aggregate the
    per-system pass counts here because the on-disk record only carries the
    overall pass_rate.

    When include_cases=True we also return a `cases` array with one
    compacted row per result (no metrics array — that's behind a per-case
    drill, not the suite-level view).
    """
    by_system: dict[str, dict[str, int]] = {}
    cases: list[dict[str, Any]] = []
    for case in run.get("results", []) or []:
        sys_key = case.get("system") or "unknown"
        bucket = by_system.setdefault(sys_key, {"total": 0, "passed": 0})
        bucket["total"] += 1
        if case.get("passed"):
            bucket["passed"] += 1
        if include_cases:
            cases.append({
                "id": case.get("id"),
                "label": case.get("label"),
                "system": sys_key,
                "category": case.get("category"),
                "passed": bool(case.get("passed")),
                "overall_score": case.get("overall_score"),
                "failures": list(case.get("failures") or []),
                "metric_failures": [
                    {"name": m.get("name"), "score": m.get("score"), "details": m.get("details")}
                    for m in (case.get("metrics") or [])
                    if isinstance(m, dict) and not m.get("passed")
                ],
            })
    per_system = {
        sys_key: {
            **bucket,
            "pass_rate": round(bucket["passed"] / bucket["total"], 4) if bucket["total"] else 0.0,
        }
        for sys_key, bucket in by_system.items()
    }
    out: dict[str, Any] = {
        "run_id": run.get("run_id"),
        "timestamp": run.get("timestamp"),
        "mode": run.get("mode"),
        "status": run.get("status"),
        "cases_total": run.get("cases_total"),
        "cases_passed": run.get("cases_passed"),
        "cases_null": run.get("cases_null"),
        "pass_rate": run.get("pass_rate"),
        "datasets": run.get("datasets") or [],
        "per_system": per_system,
    }
    if include_cases:
        out["cases"] = cases
    return out


def _read_eval_runs_jsonl(agent_id: str) -> list[dict[str, Any]]:
    """Return every suite-run record for `agent_id`, oldest-first.

    Reads `data/<agent_id>_eval_runs.jsonl` via DATA_ROOT (2026-06-01 rule).
    Returns [] when the file is absent.
    """
    safe_id = agent_id.replace("/", "_").replace("..", "_")
    path = _DATA_DIR_AGENTS / f"{safe_id}_eval_runs.jsonl"
    if not path.exists():
        return []
    try:
        from storage import _read_jsonl
        return _read_jsonl(path)
    except ImportError:
        rows: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return rows


def _read_baseline(agent_id: str) -> dict[str, Any] | None:
    """Return the locked baseline run for `agent_id`, or None if absent.

    Repo-relative path — baseline.json is checked in alongside the agent,
    not a runtime artifact, so it does NOT go through DATA_ROOT.
    """
    safe_id = agent_id.replace("/", "_").replace("..", "_")
    path = _REPO_ROOT_AGENTS / "agents" / safe_id / "eval" / "baseline.json"
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("agents.eval_summary: baseline read failed agent_id=%s err=%s", agent_id, exc)
        return None


@router.get(
    "/api/agents/{agent_id}/eval-summary",
    operation_id="agents_eval_summary",
)
async def get_agent_eval_summary(
    agent_id: str,
    history_limit: int = Query(20, ge=1, le=200, description="Most-recent N suite runs to return"),
    include_cases: str = Query(
        "none",
        description="Include per-case results for 'baseline', 'latest', or 'both'. Default 'none'.",
        pattern="^(none|baseline|latest|both)$",
    ),
) -> dict[str, Any]:
    """Return the suite-level eval visibility payload for an agent.

    Response shape:
        {
          "agent_id": "vendor_risk",
          "has_eval_suite": true | false,
          "baseline": {summary} | null,
          "latest_run": {summary} | null,
          "history": [{summary}, ...],   // newest-first, capped at history_limit
          "trend": {
              "runs_total": int,
              "runs_passed": int,        // status == "PASS"
              "pass_rate_mean": float    // mean of pass_rate across history
          }
        }

    Agents without an eval suite (`baseline.json` absent AND no run history)
    return `has_eval_suite: false` and null fields. 404 only when the agent
    itself is not in the domain registry.
    """
    start = datetime.now(tz=timezone.utc)
    logger.info("agents.eval_summary.enter agent_id=%s", agent_id)

    # Verify the agent exists in the domain registry. Honest 404 if not.
    a_mod = _agents()
    agent = await asyncio.to_thread(a_mod.get_agent, agent_id=agent_id)
    if agent is None:
        raise HTTPException(
            status_code=404,
            detail={"error": f"Agent '{agent_id}' not found", "code": "NOT_FOUND"},
        )

    baseline_raw = await asyncio.to_thread(_read_baseline, agent_id)
    runs_raw = await asyncio.to_thread(_read_eval_runs_jsonl, agent_id)

    has_eval_suite = baseline_raw is not None or bool(runs_raw)

    cases_in_baseline = include_cases in ("baseline", "both")
    cases_in_latest = include_cases in ("latest", "both")

    baseline = _summarize_run(baseline_raw, include_cases=cases_in_baseline) if baseline_raw else None
    history_all = [_summarize_run(r) for r in runs_raw]
    history_newest_first = list(reversed(history_all))
    history = history_newest_first[:history_limit]
    latest_run = (
        _summarize_run(runs_raw[-1], include_cases=cases_in_latest)
        if cases_in_latest and runs_raw
        else (history_newest_first[0] if history_newest_first else None)
    )

    runs_passed = sum(1 for r in history_all if r.get("status") == "PASS")
    pass_rates = [r["pass_rate"] for r in history_all if isinstance(r.get("pass_rate"), (int, float))]
    pass_rate_mean = round(sum(pass_rates) / len(pass_rates), 4) if pass_rates else 0.0

    elapsed_ms = (datetime.now(tz=timezone.utc) - start).total_seconds() * 1000
    logger.info(
        "agents.eval_summary.exit agent_id=%s has_suite=%s history=%d elapsed_ms=%.1f",
        agent_id,
        has_eval_suite,
        len(history),
        elapsed_ms,
    )
    return {
        "agent_id": agent_id,
        "has_eval_suite": has_eval_suite,
        "baseline": baseline,
        "latest_run": latest_run,
        "history": history,
        "trend": {
            "runs_total": len(history_all),
            "runs_passed": runs_passed,
            "pass_rate_mean": pass_rate_mean,
        },
    }
