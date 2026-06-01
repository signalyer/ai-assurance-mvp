"""Agent registry — single source of truth for runner-dispatchable agents.

Locked at S80 (LBD-2 in docs/plans/SESSION-80-agent-runner.md):

- The Agent Runner picker (team-portal /agent-runner) calls
  `list_registered_agents()` to populate the dropdown.
- The runner dispatcher (`domain.agent_runner.stream_agent_run_with_chain_events`)
  calls `get_agent(agent_id)` to resolve the spec, imports `module_path`,
  and invokes `entrypoint(prompt=..., **kwargs)`.

`cli_only=True` agents (e.g. `azure-architect`, whose directory name
contains a hyphen and is not a valid Python module path) appear in the
picker for transparency but raise `AgentNotRunnerInvocableError` if the
runner tries to dispatch them. Renaming `azure-architect` would touch
~39 files including engine-loaded `.rego` policies referenced by sha256
— deliberately out of S80 scope.

Adding a new runner-dispatchable agent:
  1. Create `agents/<agent_id>/__init__.py`, `agent.py`, `prompts.py`.
  2. Implement `async def <entrypoint>(prompt: str, **kwargs) -> dict`.
  3. Append an `AgentSpec(...)` to `REGISTRY` below.
  4. Confirm `dashboard.py` lifespan eager-imports `agents._registry`
     (per [[lazy-imports-skip-module-load-bootstrap]]).
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any, Callable


class AgentNotFoundError(KeyError):
    """Raised when `get_agent` is called with an unknown agent_id."""


class AgentNotRunnerInvocableError(RuntimeError):
    """Raised when the runner attempts to dispatch a `cli_only=True` agent."""


@dataclass(frozen=True)
class AgentSpec:
    """Describes one agent the Agent Runner knows about.

    Attributes:
        agent_id: Stable identifier used in URLs, SSE events, audit rows.
            Must be a valid Python identifier (used as part of the module
            path for runner-invocable agents). Lowercase, no hyphens.
        name: Human-readable display name shown in the picker.
        description: One-sentence summary shown in the picker.
        default_system_id: The onboarded AI system this agent belongs to
            by default. Used as the `system_id` for routing / audit when
            the operator does not override it from the UI.
        module_path: Dotted import path to the agent module (e.g.
            "agents.finadvice.agent"). `None` for cli_only agents.
        entrypoint: Name of the async callable inside `module_path` that
            the runner invokes when it wants the FULLY DECORATED chain
            run inline (policy_gate → scrub_pii → guardrails enforced by
            the agent itself). Signature must be
            `async def <name>(prompt: str, **kwargs) -> dict`. `None`
            for cli_only agents.
        inner_entrypoint: Name of the UNDECORATED inner callable inside
            `module_path` that the chain-event dispatcher invokes after
            running policy / scrub / guard manually with per-step timing.
            Optional — when None, the dispatcher falls back to
            `entrypoint`. The inner MUST accept an `event_sink` kwarg
            (sync callable) for per-token `llm.delta` emission. See
            `docs/plans/SESSION-80-agent-runner.md` LBD-1.
        tool_specs: Anthropic-format tool specs the agent declares. The
            runner does not use these directly (the agent's own
            implementation owns the tool-use loop) but the picker may
            surface them for operator visibility.
        cli_only: When True, the agent is listed in the picker but cannot
            be dispatched by the runner. Used for legacy agents whose
            directory layout is not import-compatible.
    """

    agent_id: str
    name: str
    description: str
    default_system_id: str
    module_path: str | None
    entrypoint: str | None
    inner_entrypoint: str | None = None
    tool_specs: list[dict[str, Any]] = field(default_factory=list)
    cli_only: bool = False
    demo_only: bool = False
    """When True, the agent has not completed `docs/SOP-agent-onboarding.md`
    (notably Phase 4 Behavioral Spec / eval suite + Phase 9 Pre-Release
    Assessment). The runner still dispatches it, but the API + picker
    surface a "DEMO ONLY — not production-governed" badge so operators
    can't mistake it for a production-onboarded agent. Removing this flag
    requires executing the missing SOP phases, not just flipping the bool."""


# Registry is a tuple, not a dict, so iteration order is stable for the
# picker. `get_agent` indexes by agent_id at call time.
REGISTRY: tuple[AgentSpec, ...] = (
    AgentSpec(
        agent_id="finadvice",
        name="Financial Advisor Risk Reviewer",
        description=(
            "Reviews a client's portfolio against their risk profile and "
            "recommends rebalancing actions. Uses deterministic mock data "
            "(portfolios, market snapshot, risk profiles) so the demo is "
            "reproducible without live financial APIs."
        ),
        default_system_id="sys-demo-finadvice-001",
        module_path="agents.finadvice.agent",
        entrypoint="run_review",
        inner_entrypoint="_run_review_inner",
        tool_specs=[],  # populated by the agent module at import time; see note below
        cli_only=False,
        demo_only=True,  # S80 shipped without Phase 4 eval suite / Phase 9 assessment — see docs/SOP-agent-onboarding.md
    ),
    AgentSpec(
        agent_id="azure-architect",
        name="Azure Architect (CLI only)",
        description=(
            "Plans Azure deployments via ARM read-only tools. CLI-invokable "
            "only — directory name contains a hyphen and is not a valid "
            "Python module path. Listed here for transparency; the runner "
            "cannot dispatch it."
        ),
        default_system_id="sys-demo-azurearch-001",
        module_path=None,
        entrypoint=None,
        tool_specs=[],
        cli_only=True,
        demo_only=True,  # CLI-only PoC; no Phase 1-12 SOP execution — see docs/SOP-agent-onboarding.md
    ),
    AgentSpec(
        agent_id="vendor_risk",
        name="Vendor Risk Analyzer",
        description=(
            "Third-party vendor risk assessment for TPRM onboarding. "
            "Parses vendor-disclosed documents (SOC2, ISO 27001, DPA, "
            "subprocessor list, questionnaire), retrieves grounding from "
            "the TPRM policy + regulatory corpus, and produces a "
            "structured risk tier with concerns, conflicts, mitigations, "
            "and citations. Two AI systems: ext (cloud LLM) + int "
            "(internal-only, no network egress) — operator picks via the "
            "system_id kwarg. Onboarded per docs/SOP-agent-onboarding.md "
            "(S82a–S82i)."
        ),
        # Defaults to EXT system; the runner can override via system_id kwarg.
        # The two AI System rows are seeded by
        # agents/vendor_risk/onboarding/bootstrap.py at engine startup.
        default_system_id="sys-vendor-risk-ext-001",
        module_path="agents.vendor_risk.agent",
        entrypoint="run_vendor_risk",
        inner_entrypoint="_run_review_inner",
        tool_specs=[],  # surfaced via prompts.TOOL_SPECS when the picker grows that view
        cli_only=False,
        # S82d V0 — eval baseline just landed; iteration to lock thresholds
        # is S82e (Phase 6). Pre-Release Assessment + Pilot + Release are
        # S82g/h/i. Flip to False only after S82i.
        demo_only=True,
    ),
)


_BY_ID: dict[str, AgentSpec] = {spec.agent_id: spec for spec in REGISTRY}


def list_registered_agents() -> tuple[AgentSpec, ...]:
    """Return every registered agent in declaration order.

    Used by `GET /api/agent-runner/agents` to populate the picker. Both
    runner-invocable and `cli_only` specs are returned; the SPA decides
    how to render them.
    """
    return REGISTRY


def get_agent(agent_id: str) -> AgentSpec:
    """Look up an agent spec by id.

    Raises:
        AgentNotFoundError: when `agent_id` is not in the registry.
    """
    try:
        return _BY_ID[agent_id]
    except KeyError as exc:
        known = ", ".join(spec.agent_id for spec in REGISTRY) or "(none)"
        raise AgentNotFoundError(
            f"Unknown agent_id={agent_id!r}. Registered: {known}."
        ) from exc


def load_agent_entrypoint(agent_id: str) -> tuple[AgentSpec, Callable[..., Any]]:
    """Resolve an agent and import its entrypoint callable.

    The runner uses this to dispatch. Imports are deferred (not at module
    load) so a broken agent module does not prevent the registry itself
    from importing — the picker continues to work even if one entry is
    quarantined.

    Returns:
        (spec, entrypoint_callable) tuple.

    Raises:
        AgentNotFoundError: when `agent_id` is unknown.
        AgentNotRunnerInvocableError: when the spec is `cli_only=True`.
        ImportError: when `module_path` cannot be imported.
        AttributeError: when `entrypoint` is missing on the module.
    """
    spec = get_agent(agent_id)
    if spec.cli_only or spec.module_path is None or spec.entrypoint is None:
        raise AgentNotRunnerInvocableError(
            f"Agent {agent_id!r} is CLI-only and cannot be dispatched by the runner."
        )
    module: ModuleType = importlib.import_module(spec.module_path)
    entrypoint = getattr(module, spec.entrypoint)
    return spec, entrypoint


def load_agent_inner(agent_id: str) -> tuple[AgentSpec, Callable[..., Any]]:
    """Resolve an agent and import its UNDECORATED inner entrypoint.

    Used by `domain.agent_runner.stream_agent_run_with_chain_events` so the
    chain-event dispatcher can run policy / scrub / guard manually with
    per-step timing, then invoke the agent body without re-running the
    decorator chain. The returned callable MUST accept an `event_sink`
    kwarg (sync callable) for per-token `llm.delta` emission.

    Falls back to `entrypoint` (decorated) when `inner_entrypoint` is None
    — agents written before the S80 refactor still work, but the
    dispatcher's policy/scrub/guard events will be redundant with the
    decorator chain re-running them inside.

    Raises:
        AgentNotFoundError: when `agent_id` is unknown.
        AgentNotRunnerInvocableError: when the spec is `cli_only=True`.
        ImportError: when `module_path` cannot be imported.
        AttributeError: when the resolved entrypoint name is missing on
            the module.
    """
    spec = get_agent(agent_id)
    if spec.cli_only or spec.module_path is None:
        raise AgentNotRunnerInvocableError(
            f"Agent {agent_id!r} is CLI-only and cannot be dispatched by the runner."
        )
    module: ModuleType = importlib.import_module(spec.module_path)
    name = spec.inner_entrypoint or spec.entrypoint
    if name is None:
        raise AgentNotRunnerInvocableError(
            f"Agent {agent_id!r} has neither inner_entrypoint nor entrypoint."
        )
    return spec, getattr(module, name)
