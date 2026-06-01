"""Agent Runner API surface — S80 LBD-1.

Two endpoints:

  GET  /api/agent-runner/agents
       Returns the registry catalog so the team-portal /agent-runner picker
       can populate. Includes `cli_only` agents so the SPA can render them
       as disabled choices (transparent about what exists).

  POST /api/agent-runner/run
       Streams chain events (SSE / text/event-stream) for one agent run.
       Body: {agent_id, prompt, system_id?, model?, demo_mode?}.
       Each SSE message's `event` field is the chain step name
       (chain.start, policy_gate, scrub_pii, guardrails, llm.delta, llm.done,
       evaluate, memory, audit, chain.done, chain.error). The `data` field
       carries the full event dict as JSON. Consumers terminate on
       `chain.done`.

Auth model: Both endpoints require any role in `_RUNNER_ROLES`. The Agent
Runner is operator-facing (it issues real LLM calls and writes audit rows),
so the role set is broad but every recognised role still authenticates.
When AUTH_ENABLED=false (dev), `require_role` passes through per its
contract — this matches the rest of the engine's API surface.

User attribution: `domain.agent_runner.stream_agent_run_with_chain_events`
accepts a `user` dict that lands on the audit row + chain.start event. We
pull it from the signed session cookie via `middleware.auth._read_cookie`
so the audit reflects the real operator, not "anonymous".

See also:
  - docs/plans/SESSION-80-agent-runner.md (LBD-1 event protocol)
  - domain/agent_runner.py (the streaming dispatcher)
  - agents/_registry.py (catalog source of truth)
"""
from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sse_starlette.sse import EventSourceResponse

from agents._registry import list_registered_agents
from domain.agent_runner import stream_agent_run_with_chain_events
from middleware.auth import require_role, _read_cookie

_log = logging.getLogger(__name__)


router = APIRouter(prefix="/api/agent-runner", tags=["agent-runner"])


# Roles that may invoke the Agent Runner. Kept broad because the runner is
# operator-facing — narrow it later if a least-privilege review comes back
# with specific exclusions. Whitelist not blacklist — `require_role` raises
# 403 for any role not present here.
_RUNNER_ROLES: tuple[str, ...] = (
    "operator",
    "architect",
    "ciso",
    "auditor",
    "admin",
)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


def _strict() -> ConfigDict:
    return ConfigDict(extra="forbid")


class AgentSpecOut(BaseModel):
    """One agent as the picker sees it."""

    model_config = _strict()

    agent_id: str
    name: str
    description: str
    default_system_id: str
    cli_only: bool
    demo_only: bool = False


class AgentsListOut(BaseModel):
    """GET /agents response."""

    model_config = _strict()

    agents: list[AgentSpecOut]


class RunRequest(BaseModel):
    """POST /run body."""

    model_config = _strict()

    agent_id: str = Field(..., min_length=1, description="Registry id, e.g. 'finadvice'.")
    prompt: str = Field(..., min_length=1, description="Raw operator request.")
    system_id: str | None = Field(
        default=None,
        description="Optional override for the onboarded AI system id used in routing + audit.",
    )
    model: str | None = Field(
        default=None,
        description="Optional Anthropic model override. None uses the agent's default.",
    )
    demo_mode: bool | None = Field(
        default=None,
        description=(
            "When True, the scrub_pii event payload includes a raw_preview of "
            "the operator prompt (DEMO_MODE locked at S80 entry). When None, "
            "resolved from the DEMO_MODE env var (default false). Never set "
            "True on a real prod stream."
        ),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/agents", response_model=AgentsListOut)
async def list_agents(
    _role: None = Depends(require_role(*_RUNNER_ROLES)),
) -> AgentsListOut:
    """Return the registry catalog for the team-portal Agent Runner picker.

    Both runner-invocable and cli_only agents are returned. The SPA decides
    rendering (cli_only typically renders as a disabled row with a tooltip).
    """
    return AgentsListOut(
        agents=[
            AgentSpecOut(
                agent_id=spec.agent_id,
                name=spec.name,
                description=spec.description,
                default_system_id=spec.default_system_id,
                cli_only=spec.cli_only,
                demo_only=spec.demo_only,
            )
            for spec in list_registered_agents()
        ]
    )


def _resolve_user(request: Request) -> dict[str, str]:
    """Extract operator identity from the signed session cookie.

    Falls back to 'anonymous' / 'operator' when the cookie is absent
    (AUTH_ENABLED=false test mode) so the audit row stays joinable even
    in dev. The X-Role header path used by `require_role` is for dev
    convenience too; we mirror it here so dev runs attribute correctly.
    """
    payload = _read_cookie(request) or {}
    username = payload.get("u") or request.headers.get("X-User", "anonymous")
    role = payload.get("r") or request.headers.get("X-Role", "operator")
    return {"username": str(username), "role": str(role).lower()}


@router.post("/run")
async def run_agent(
    req: RunRequest,
    request: Request,
    _role: None = Depends(require_role(*_RUNNER_ROLES)),
) -> EventSourceResponse:
    """Stream chain events for one agent run as Server-Sent Events.

    The SPA (S81+) opens an EventSource against this endpoint. Each SSE
    message's `event` matches a chain step; `data` is the JSON-encoded
    event dict. Terminate on `chain.done`.

    Error semantics: the dispatcher never raises — uncaught errors during
    the chain are emitted as `chain.error` followed by `chain.done`. The
    one path that DOES raise is registry/spec resolution (handled inside
    the dispatcher too). The try/except below catches the truly
    unexpected — e.g. EventSourceResponse infrastructure failure — and
    surfaces it as a final chain.error.
    """
    user = _resolve_user(request)

    async def _gen() -> AsyncIterator[dict[str, Any]]:
        try:
            async for evt in stream_agent_run_with_chain_events(
                agent_id=req.agent_id,
                prompt=req.prompt,
                system_id=req.system_id,
                user=user,
                demo_mode=req.demo_mode,
                model=req.model,
            ):
                # sse_starlette expects {"event": str, "data": str}. We JSON-
                # encode the full event dict so the SPA can reconstruct it
                # from event.data on the client without per-step parsers.
                # default=str handles any datetime / float-fallback edge cases.
                yield {
                    "event": evt.get("event", "unknown"),
                    "data": json.dumps(evt, default=str),
                }
        except Exception as exc:  # noqa: BLE001
            # The dispatcher's contract is to never raise; if we land here
            # it's an infrastructure failure (e.g. SSE transport). Emit a
            # final chain.error so the SPA terminates cleanly instead of
            # waiting for chain.done forever.
            _log.exception("Agent Runner SSE generator failed unexpectedly")
            err = {
                "event": "chain.error",
                "step": "sse",
                "error_type": type(exc).__name__,
                "message": str(exc),
            }
            yield {"event": "chain.error", "data": json.dumps(err)}

    return EventSourceResponse(_gen())
