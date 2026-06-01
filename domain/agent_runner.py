"""Agent Runner chain-event dispatcher.

Locked at S80 (LBD-1 in docs/plans/SESSION-80-agent-runner.md).

`stream_agent_run_with_chain_events` is the single backend surface the
Agent Runner SPA (S81+) consumes via SSE. It runs the governance chain
manually so the per-step events the SPA renders have honest per-step
elapsed_ms — calling the fully-decorated agent surface would hide step
boundaries inside the decorator chain.

Event protocol (every event dict has `event`, `run_id`, `elapsed_ms`):

  chain.start   — dispatcher entry; agent + system + provider resolved
  policy_gate   — after policy_engine.evaluate; decision/rule/reason
  scrub_pii     — after scrubber.tokenise_payload; redacted_count, vault_id
  guardrails    — after GuardrailsMiddleware.check_input
  llm.delta     — per token chunk; emitted from the agent's stream loop
                  via the event_sink kwarg
  llm.done      — terminal LLM event; model + token counts + cost estimate
  evaluate      — eval scores (mirrors agent's internal eval; S83 enriches)
  memory        — write_episode outcome from the agent's return dict
  audit         — audit row identifier + deep-link URLs (Langfuse + AppInsights)
                  S83 wires the real URL builders; S80 emits null URLs
  chain.done    — terminal; total_elapsed_ms + outcome + episode_id + audit_id
  chain.error   — any uncaught exception; `step` names which event failed

The dispatcher only catches per-step errors so a downstream failure doesn't
mask the prior step's output. A `chain.error` is always followed by a
`chain.done` so consumers can rely on a terminal event.

S80 caveats (resolved in later sessions):
  - `audit` event emits null Langfuse / AppInsights URLs. S83 fills them
    from LANGFUSE_PROJECT_URL + APPLICATIONINSIGHTS_RESOURCE_ID env.
  - `evaluate` event mirrors the agent's INTERNAL eval result. The
    Agent Runner does not currently run an additional eval pass against
    the synthesis. S85 wires the eval suite → real episodes path.
  - `audit` payload's `audit_id` and `trace_id` are run-scoped synthetic
    ids when no real provider audit row was created. The full
    domain.assurance_providers integration (create_provider_audit_event)
    lands in S82 when the dual-path columns need both Anthropic and
    local-simulated to deep-link to the same trace.
  - `policy_gate` event's `decision` may be ALLOW even when the agent
    later raises mid-run — the dispatcher emits chain.error in that case.

See also:
  - agents/_registry.py:load_agent_inner for the undecorated lookup.
  - agents/finadvice/agent.py:_run_review_inner for the canonical
    event_sink contract.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable

from agents._registry import (
    AgentNotFoundError,
    AgentNotRunnerInvocableError,
    load_agent_inner,
)

_log = logging.getLogger(__name__)


# --- Helpers -----------------------------------------------------------------


def _now_ms() -> float:
    """Monotonic wall-clock in ms for elapsed measurements."""
    return time.monotonic() * 1000.0


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _truncate(s: str, n: int = 200) -> str:
    """Truncate to n chars with an ellipsis marker. None-safe."""
    if not isinstance(s, str):
        return ""
    return s if len(s) <= n else s[: n - 1] + "…"


def _is_demo_mode(explicit: bool | None) -> bool:
    """Resolve DEMO_MODE from explicit kwarg or env.

    Per the S80 raw_preview decision: include raw operator-prompt preview
    in scrub_pii events only when DEMO_MODE=true. Default off so a real
    prod stream never carries raw operator text back to the SPA.
    """
    if explicit is not None:
        return bool(explicit)
    return os.environ.get("DEMO_MODE", "false").lower() == "true"


def _redacted_token_count(scrubbed: str) -> int:
    """Count [TYPE_NNN] tokens in a scrubbed payload."""
    if not scrubbed:
        return 0
    # Match the same shape policy_engine uses: alphanumeric + underscore type + 3-digit idx
    import re
    return len(re.findall(r"\[[A-Z_]+_\d{3}\]", scrubbed))


def _redacted_field_types(scrubbed: str) -> list[str]:
    """Distinct PII type labels present in a scrubbed payload."""
    if not scrubbed:
        return []
    import re
    return sorted({m.group(1) for m in re.finditer(r"\[([A-Z_]+)_\d{3}\]", scrubbed)})


# --- The dispatcher ----------------------------------------------------------


async def stream_agent_run_with_chain_events(
    agent_id: str,
    prompt: str,
    *,
    system_id: str | None = None,
    user: dict[str, Any] | None = None,
    demo_mode: bool | None = None,
    model: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Yield chain events for one Agent Runner invocation.

    Args:
        agent_id: registry id (e.g. "finadvice").
        prompt: raw operator request text (pre-scrub).
        system_id: optional override for the onboarded AI system id used
            in routing + audit. Falls back to spec.default_system_id.
        user: optional dict with at least `username` / `role` so audit
            rows can attribute the run. Not authoritative — the API
            layer (api/agent_runner.py) populates from session cookie.
        demo_mode: when True, scrub_pii event includes raw_preview of
            the operator prompt. When None, resolved from DEMO_MODE env.
        model: optional Anthropic model override; the agent's default
            (per its prompts module) applies otherwise.

    Yields:
        Event dicts. See module docstring for the event schema.

    The generator NEVER raises — every error path emits `chain.error`
    followed by `chain.done`. Callers can rely on `chain.done` as the
    terminal signal.
    """
    run_id = f"run-{uuid.uuid4().hex[:12]}"
    started = _now_ms()
    demo = _is_demo_mode(demo_mode)
    user_username = (user or {}).get("username") or "anonymous"

    # ------------------------------------------------------------------ resolve
    try:
        spec, inner = load_agent_inner(agent_id)
    except AgentNotFoundError as exc:
        yield _error(run_id, "resolve", "AgentNotFoundError", str(exc), started)
        yield _done(run_id, started, outcome="error", episode_id="", audit_id="")
        return
    except AgentNotRunnerInvocableError as exc:
        yield _error(run_id, "resolve", "AgentNotRunnerInvocableError", str(exc), started)
        yield _done(run_id, started, outcome="error", episode_id="", audit_id="")
        return

    effective_system_id = system_id or spec.default_system_id
    # Provider resolution: S80 hardcodes "anthropic" as the default. S82's
    # dual-path mechanic flips this via system_id routing (NPI-tagged systems
    # route to "local-simulated" per domain/assurance_providers.py). Doing
    # that lookup honestly requires the provider catalog API which is out of
    # this session's tight scope; we surface system_id so consumers can infer.
    provider_id = "anthropic"

    yield {
        "event": "chain.start",
        "run_id": run_id,
        "agent_id": agent_id,
        "agent_name": spec.name,
        "provider_id": provider_id,
        "system_id": effective_system_id,
        "user": user_username,
        "started_at": _utcnow_iso(),
        "elapsed_ms": 0,
    }

    # ------------------------------------------------------------- policy_gate
    step_started = _now_ms()
    try:
        from domain.policy_engine import evaluate as policy_evaluate, Decision

        # S82f-1c: propagate operator_role so workload rego policies that
        # use `required_operator_roles` (e.g. vendor-risk-{ext,int}.rego) can
        # evaluate. The role lives on the user dict resolved from the signed
        # session cookie in api.agent_runner._resolve_user. Without this the
        # policy sees operator_role='' and DENIES every run for any workload
        # that gates on role.
        operator_role = (user or {}).get("role", "")
        policy_input: dict[str, Any] = {
            "prompt": prompt,
            "operator_role": operator_role,
        }

        # S82f-2 (ADR-004): inject persisted runtime-flag attestation for
        # INT systems so the rego `required_true_flags` gate can evaluate.
        # We read server-side state — the caller's request body cannot
        # fabricate these. Absent / expired attestation surfaces as False
        # values, producing the rego DENY path (workload_required_flag_not_set)
        # which is the SOP-Phase-8 deny-on-expiry drill outcome.
        #
        # Scoped narrowly to vendor_risk INT system IDs to avoid changing
        # the policy_input shape for any other workload. When a second
        # system type adopts this pattern, broaden via AISystem.runtime_flags
        # (already folded by domain.repository._fold) rather than a prefix
        # match here.
        if effective_system_id and effective_system_id.startswith("sys-vendor-risk-int-"):
            try:
                from storage import read_system_runtime_flags

                flags = read_system_runtime_flags(effective_system_id)
            except Exception as exc:  # noqa: BLE001
                # Fail closed: if the overlay read fails for any reason
                # (corrupt JSONL, unexpected schema), inject False values
                # so the rego gate DENIES. Logged for operator visibility.
                _log.warning(
                    "runtime_flags read failed for system_id=%s: %s: %s",
                    effective_system_id, type(exc).__name__, exc,
                )
                flags = None
            policy_input["dlp_completed"] = bool(flags.dlp_completed) if flags else False
            policy_input["network_egress_lock_engaged"] = (
                bool(flags.network_egress_lock_engaged) if flags else False
            )

        policy_result = policy_evaluate(
            workload_id=effective_system_id,
            action="llm_call",
            input_data=policy_input,
        )
        elapsed = _now_ms() - step_started
        decision_str = policy_result.decision.value if hasattr(policy_result.decision, "value") else str(policy_result.decision)
        yield {
            "event": "policy_gate",
            "run_id": run_id,
            "decision": decision_str,
            "rule": policy_result.policy_name,
            "reason": policy_result.reason,
            "elapsed_ms": round(elapsed, 1),
        }
        if policy_result.decision != Decision.ALLOW and policy_result.decision != Decision.REVIEW:
            # Hard DENY — chain stops here. No memory/audit row makes sense for
            # a denied call; emit chain.done immediately so consumers terminate.
            yield _done(
                run_id, started,
                outcome="denied",
                episode_id="",
                audit_id="",
                terminal_reason=f"policy_deny:{policy_result.policy_name}",
            )
            return
    except Exception as exc:  # noqa: BLE001
        _log.exception("policy_gate step failed")
        yield _error(run_id, "policy_gate", type(exc).__name__, str(exc), step_started)
        yield _done(run_id, started, outcome="error", episode_id="", audit_id="")
        return

    # ---------------------------------------------------------------- scrub_pii
    step_started = _now_ms()
    scrubbed_prompt = prompt
    vault_id = ""
    try:
        scrubber_enabled = os.environ.get("SCRUBBER_ENABLED", "false").lower() == "true"
        if scrubber_enabled:
            # Import path matches middleware/scrubber.py:153 — top-level
            # `scrubber` module is the canonical seam, not a deeper submodule
            # (per [[provider-cache-singleton-test-pollution]]).
            from scrubber import tokenise_payload

            scrubbed_prompt, vault_id = tokenise_payload(prompt, "finadvice")
            if not vault_id and prompt:
                vault_id = "finadvice_nopii_" + hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]
        else:
            scrubbed_prompt = prompt
            vault_id = "finadvice_disabled_" + hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]

        elapsed = _now_ms() - step_started
        payload: dict[str, Any] = {
            "event": "scrub_pii",
            "run_id": run_id,
            "scrubber_enabled": scrubber_enabled,
            "redacted_count": _redacted_token_count(scrubbed_prompt),
            "redacted_field_types": _redacted_field_types(scrubbed_prompt),
            "vault_id": vault_id,
            "scrubbed_preview": _truncate(scrubbed_prompt, 200),
            "elapsed_ms": round(elapsed, 1),
        }
        if demo:
            # DEMO_MODE only — never on a real prod stream. Aligned with the
            # answer to the S80-entry question on raw_preview policy.
            payload["raw_preview"] = _truncate(prompt, 200)
        yield payload
    except Exception as exc:  # noqa: BLE001
        _log.exception("scrub_pii step failed")
        yield _error(run_id, "scrub_pii", type(exc).__name__, str(exc), step_started)
        yield _done(run_id, started, outcome="error", episode_id="", audit_id="")
        return

    # ---------------------------------------------------------------- guardrails
    step_started = _now_ms()
    try:
        from middleware.guardrails import GuardrailsMiddleware

        guardrails = GuardrailsMiddleware(strict=False)
        gr_result = await guardrails.check_input(
            prompt=scrubbed_prompt,
            workload_id=effective_system_id,
        )
        elapsed = _now_ms() - step_started

        injection_score = None
        if gr_result.injection_result is not None:
            injection_score = getattr(gr_result.injection_result, "score", None)
        topic_in_scope = None
        if gr_result.topic_result is not None:
            topic_in_scope = getattr(gr_result.topic_result, "passed", None)
        safety_pass = None
        if gr_result.safety_result is not None:
            safety_pass = getattr(gr_result.safety_result, "safe", None)

        yield {
            "event": "guardrails",
            "run_id": run_id,
            "passed": bool(gr_result.passed),
            "violations": list(gr_result.violations),
            "injection_score": injection_score,
            "topic_in_scope": topic_in_scope,
            "safety_pass": safety_pass,
            "elapsed_ms": round(elapsed, 1),
        }
        if not gr_result.passed:
            yield _done(
                run_id, started,
                outcome="guardrail_block",
                episode_id="",
                audit_id="",
                terminal_reason="guardrail_violation",
            )
            return
    except Exception as exc:  # noqa: BLE001
        _log.exception("guardrails step failed")
        yield _error(run_id, "guardrails", type(exc).__name__, str(exc), step_started)
        yield _done(run_id, started, outcome="error", episode_id="", audit_id="")
        return

    # ---------------------------------------------------------------------- LLM
    # The agent's inner function runs the tool-use loop and emits llm.delta
    # events via the event_sink we provide. We drain a queue between the
    # agent task (background asyncio.Task) and this generator so deltas
    # interleave with the agent's progress rather than dumping at the end.
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    SENTINEL: dict[str, Any] = {"event": "__sink_closed__"}

    def _sink(event: dict[str, Any]) -> None:
        # Synchronous callback the agent invokes from inside its stream loop.
        # put_nowait is safe here — we never bound the queue. Worst case is
        # memory growth proportional to the agent's text output (~few KB).
        try:
            queue.put_nowait(event)
        except Exception as exc:  # noqa: BLE001
            _log.warning("event_sink put_nowait failed: %s: %s", type(exc).__name__, exc)

    llm_started = _now_ms()
    agent_kwargs: dict[str, Any] = {
        "prompt": scrubbed_prompt,
        "vault_id": vault_id,
        "event_sink": _sink,
    }
    if model is not None:
        agent_kwargs["model"] = model

    # S82f-2: thread agent-specific context (system_id, vendor_package_ref)
    # into the inner call when the agent's signature accepts them. The
    # dispatcher historically only knew about finadvice's kwargs (prompt,
    # vault_id, event_sink, model); vendor_risk also wants system_id (to
    # pick EXT vs INT system prompt) and vendor_package_ref (so the
    # parse_vendor_document tool has a fixture to bind to). Without this,
    # vendor_risk runs via the SPA degrade silently: parsers return "no
    # fixture" errors and the agent synthesizes from corpus signal alone.
    #
    # We inspect-filter so finadvice (which doesn't declare these kwargs)
    # is unaffected. The vendor_package_ref is extracted from the prompt
    # body since the API's RunRequest schema is extra="forbid" — clients
    # cannot send a separate field, but the calibration harness format
    # inlines "Vendor package: fixtures/<id>/" which the regex below
    # picks up.
    import inspect
    import re as _re
    try:
        _sig = inspect.signature(inner)
        _params = _sig.parameters
        if "system_id" in _params and effective_system_id:
            agent_kwargs["system_id"] = effective_system_id
        if "vendor_package_ref" in _params:
            _m = _re.search(r"Vendor package:\s*(\S+)", prompt or "")
            if _m:
                agent_kwargs["vendor_package_ref"] = _m.group(1).rstrip("/")
    except (TypeError, ValueError):
        # Builtin / C-level callable without a signature — skip the threading.
        pass

    async def _run_agent() -> dict[str, Any]:
        try:
            return await inner(**agent_kwargs)
        finally:
            # Always signal end-of-stream so the dispatcher doesn't deadlock
            # on the drain loop even if the agent raised mid-run.
            queue.put_nowait(SENTINEL)

    agent_task: asyncio.Task[dict[str, Any]] = asyncio.create_task(_run_agent())
    delta_count = 0
    try:
        while True:
            evt = await queue.get()
            if evt is SENTINEL:
                break
            # All sink events are llm.delta in S80; tag with run_id and re-emit.
            evt = {**evt, "run_id": run_id, "elapsed_ms": round(_now_ms() - llm_started, 1)}
            delta_count += 1
            yield evt

        agent_result = await agent_task
    except Exception as exc:  # noqa: BLE001
        _log.exception("agent inner raised")
        # Make sure the task is done before we leave the function.
        if not agent_task.done():
            agent_task.cancel()
        yield _error(run_id, "llm", type(exc).__name__, str(exc), llm_started)
        yield _done(run_id, started, outcome="error", episode_id="", audit_id="")
        return

    # llm.done — taken from the agent's own observed token counts.
    yield {
        "event": "llm.done",
        "run_id": run_id,
        "model": agent_result.get("model", "unknown"),
        "input_tokens": int(agent_result.get("input_tokens", 0) or 0),
        "output_tokens": int(agent_result.get("output_tokens", 0) or 0),
        "delta_count": delta_count,
        "stop_reason": agent_result.get("stop_reason", ""),
        "turns": int(agent_result.get("turns", 0) or 0),
        "elapsed_ms": round(_now_ms() - llm_started, 1),
    }

    # ----------------------------------------------------------------- evaluate
    # S80: mirror the agent's internal eval (which today is empty for finadvice
    # because run_review doesn't call evaluator.evaluate_response). Emit a
    # zero-score placeholder. S85 wires real per-run eval and surfaces metric
    # scores here. Contract is stable; only payload values change.
    step_started = _now_ms()
    try:
        eval_scores = agent_result.get("eval") or {}
        avg_score: float | None = None
        if eval_scores:
            score_values = [
                p.get("score") for p in eval_scores.values()
                if isinstance(p, dict) and isinstance(p.get("score"), (int, float))
            ]
            if score_values:
                avg_score = sum(score_values) / len(score_values)
        yield {
            "event": "evaluate",
            "run_id": run_id,
            "scores": eval_scores,
            "avg_score": avg_score,
            "scored_metric_count": len(eval_scores),
            "deferred_to_s85": True,
            "elapsed_ms": round(_now_ms() - step_started, 1),
        }
    except Exception as exc:  # noqa: BLE001
        _log.exception("evaluate step failed")
        yield _error(run_id, "evaluate", type(exc).__name__, str(exc), step_started)
        # Non-fatal — continue to memory + audit; the agent run itself succeeded.

    # ------------------------------------------------------------------- memory
    episode_id = str(agent_result.get("episode_id") or "")
    outcome = "success" if agent_result.get("stop_reason") == "end_turn" else (
        "failure" if agent_result.get("stop_reason") == "turn_cap_reached" else "review"
    )
    yield {
        "event": "memory",
        "run_id": run_id,
        "episode_id": episode_id,
        "outcome": outcome,
        "workload_id": effective_system_id,
        "elapsed_ms": 0,  # write_episode happens inside the agent; no separate timing
    }

    # -------------------------------------------------------------------- audit
    # S80: synthesize an audit_id from run_id so SSE consumers always have a
    # stable join key. S82 wires the real domain.assurance_providers
    # create_provider_audit_event call so the audit row lands in the JSONL
    # store and the SPA can deep-link to it. Langfuse + AppInsights URLs are
    # nullable per LBD-3 in the plan — S83 fills them.
    audit_id = "aud-" + hashlib.sha256(run_id.encode()).hexdigest()[:12]
    # S82f-1: telemetry deep-links. operation_id derives from the current
    # OTel trace context (works today). Langfuse URL stays None until S83
    # wires the real Langfuse trace_id through the chain — the builder is
    # in place so that's a one-line fix at the call site, not a new module.
    from domain.telemetry_links import (
        appinsights_operation_id_from_context,
        build_appinsights_url,
        build_langfuse_url,
    )
    operation_id = appinsights_operation_id_from_context()
    appinsights_url = build_appinsights_url(operation_id)
    langfuse_trace_id = ""  # S83 — wire real Langfuse trace_id
    langfuse_url = build_langfuse_url(langfuse_trace_id)
    yield {
        "event": "audit",
        "run_id": run_id,
        "audit_id": audit_id,
        "decision": "LIVE" if provider_id == "anthropic" else "SIMULATED",
        "trace_id": langfuse_trace_id,
        "operation_id": operation_id,
        "langfuse_url": langfuse_url,
        "appinsights_url": appinsights_url,
        "elapsed_ms": 0,
    }

    # -------------------------------------------------------------- chain.done
    yield _done(
        run_id, started,
        outcome=outcome,
        episode_id=episode_id,
        audit_id=audit_id,
    )


# --- Terminal event helpers --------------------------------------------------


def _error(
    run_id: str,
    step: str,
    error_type: str,
    message: str,
    step_started: float,
) -> dict[str, Any]:
    """Build a chain.error event. Always followed by chain.done."""
    return {
        "event": "chain.error",
        "run_id": run_id,
        "step": step,
        "error_type": error_type,
        "message": message,
        "elapsed_ms": round(_now_ms() - step_started, 1),
    }


def _done(
    run_id: str,
    started: float,
    *,
    outcome: str,
    episode_id: str,
    audit_id: str,
    terminal_reason: str | None = None,
) -> dict[str, Any]:
    """Build the terminal chain.done event."""
    total = round(_now_ms() - started, 1)
    payload: dict[str, Any] = {
        "event": "chain.done",
        "run_id": run_id,
        "outcome": outcome,
        "episode_id": episode_id,
        "audit_id": audit_id,
        # `elapsed_ms` honors the protocol's uniform-key contract documented
        # at module top. `total_elapsed_ms` is the semantic name consumers
        # use for clarity. Both carry the same value.
        "elapsed_ms": total,
        "total_elapsed_ms": total,
    }
    if terminal_reason is not None:
        payload["terminal_reason"] = terminal_reason
    return payload
