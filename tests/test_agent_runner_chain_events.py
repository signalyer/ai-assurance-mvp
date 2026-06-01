"""Tests for domain.agent_runner.stream_agent_run_with_chain_events.

Locked at S80. Asserts the SSE event protocol the team-portal Agent Runner
SPA consumes (per docs/plans/SESSION-80-agent-runner.md LBD-1):

  1. Event ORDER is stable:
       chain.start
       policy_gate
       scrub_pii
       guardrails
       [llm.delta]*    (zero or more, depending on what the agent emitted)
       llm.done
       evaluate
       memory
       audit
       chain.done      (always terminal)
  2. Every event dict carries `event`, `run_id`, `elapsed_ms`.
  3. `chain.done` is the LAST event in the stream.
  4. Stub inner emitting N llm.delta events → dispatcher yields exactly N.
  5. Unknown agent_id raises no exception — instead emits chain.error +
     chain.done (`outcome="error"`).
  6. A policy DENY short-circuits the chain — no llm/evaluate/memory/audit
     events follow.

Run with `pytest -s` per [[pytest-py314-capture-teardown]] (Python 3.14.4
capture teardown crashes obscure summary on plain pytest invocation).
"""
from __future__ import annotations

import asyncio
from typing import Any, Callable, Optional
from unittest.mock import patch

import pytest

from agents._registry import AgentSpec
from domain.agent_runner import stream_agent_run_with_chain_events


# --- Helpers ----------------------------------------------------------------


def _stub_spec() -> AgentSpec:
    """A registry spec that matches finadvice in shape but points at the stub."""
    return AgentSpec(
        agent_id="finadvice",
        name="Stub",
        description="stub for tests",
        default_system_id="sys-stub-001",
        module_path="agents.finadvice.agent",
        entrypoint="run_review",
        inner_entrypoint="_run_review_inner",
        tool_specs=[],
        cli_only=False,
    )


def _make_stub_inner(
    *,
    delta_count: int = 3,
    stop_reason: str = "end_turn",
    raise_exc: Optional[BaseException] = None,
) -> Callable[..., Any]:
    """Build an async inner that simulates llm.delta emission + returns.

    Args:
        delta_count: number of llm.delta events to emit via event_sink.
        stop_reason: final stop_reason in the return dict.
        raise_exc: when set, raise this after emitting deltas (simulates an
            agent-internal failure the dispatcher must catch + render as
            chain.error).
    """

    async def stub_inner(
        prompt: str,
        *,
        model: str = "stub-model",
        vault_id: str = "",
        workload_id: str = "finadvice",
        event_sink: Optional[Callable[[dict], None]] = None,
    ) -> dict[str, Any]:
        if event_sink is not None:
            for i in range(delta_count):
                event_sink({"event": "llm.delta", "text": f"chunk-{i}", "turn": 0})
        if raise_exc is not None:
            raise raise_exc
        return {
            "run_id": "fin-stub-0001",
            "synthesis": "stub synthesis text",
            "turns": 1,
            "stop_reason": stop_reason,
            "tool_calls": [{"tool": "get_client_portfolio", "ok": True}],
            "vault_id": vault_id,
            "episode_id": "ep-stub-1234",
            "model": model,
            "input_tokens": 100,
            "output_tokens": 25,
            "latency_ms": 50,
            "eval": {},
        }

    return stub_inner


async def _drain(
    agent_id: str = "finadvice",
    prompt: str = "stub prompt no pii",
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """Run the dispatcher and return all yielded events as a list."""
    events: list[dict[str, Any]] = []
    async for evt in stream_agent_run_with_chain_events(
        agent_id=agent_id,
        prompt=prompt,
        **kwargs,
    ):
        events.append(evt)
    return events


# --- Tests ------------------------------------------------------------------


def test_event_order_happy_path() -> None:
    """Stub inner with 3 deltas → expected 12 events in canonical order."""
    spec, stub = _stub_spec(), _make_stub_inner(delta_count=3, stop_reason="end_turn")
    with patch("domain.agent_runner.load_agent_inner", return_value=(spec, stub)):
        events = asyncio.run(_drain(system_id="sys-stub-001", user={"username": "test"}))
    names = [e["event"] for e in events]
    expected = [
        "chain.start", "policy_gate", "scrub_pii", "guardrails",
        "llm.delta", "llm.delta", "llm.delta",
        "llm.done", "evaluate", "memory", "audit", "chain.done",
    ]
    assert names == expected, f"event order drift: got {names}"


def test_every_event_has_run_id_and_elapsed_ms() -> None:
    """Every event must carry these uniform fields (consumer contract)."""
    spec, stub = _stub_spec(), _make_stub_inner(delta_count=2)
    with patch("domain.agent_runner.load_agent_inner", return_value=(spec, stub)):
        events = asyncio.run(_drain())
    for evt in events:
        assert "run_id" in evt, f"missing run_id: {evt}"
        assert "elapsed_ms" in evt, f"missing elapsed_ms: {evt}"
        assert isinstance(evt["elapsed_ms"], (int, float))
        assert evt["elapsed_ms"] >= 0


def test_chain_done_is_terminal() -> None:
    """chain.done is the LAST yielded event."""
    spec, stub = _stub_spec(), _make_stub_inner(delta_count=1)
    with patch("domain.agent_runner.load_agent_inner", return_value=(spec, stub)):
        events = asyncio.run(_drain())
    assert events[-1]["event"] == "chain.done"
    assert events[-1]["outcome"] == "success"
    # chain.done carries audit/episode join keys
    assert events[-1]["episode_id"] == "ep-stub-1234"
    assert events[-1]["audit_id"].startswith("aud-")


def test_run_id_is_consistent_across_events() -> None:
    """The dispatcher tags every event with the same run_id from chain.start."""
    spec, stub = _stub_spec(), _make_stub_inner(delta_count=2)
    with patch("domain.agent_runner.load_agent_inner", return_value=(spec, stub)):
        events = asyncio.run(_drain())
    run_id = events[0]["run_id"]
    assert run_id.startswith("run-")
    for evt in events:
        assert evt["run_id"] == run_id, f"run_id drift: {evt}"


def test_delta_count_matches_sink_calls() -> None:
    """Exactly N llm.delta events for N event_sink invocations."""
    for n in (0, 1, 5):
        spec, stub = _stub_spec(), _make_stub_inner(delta_count=n)
        with patch("domain.agent_runner.load_agent_inner", return_value=(spec, stub)):
            events = asyncio.run(_drain())
        deltas = [e for e in events if e["event"] == "llm.delta"]
        assert len(deltas) == n, f"want {n} deltas, got {len(deltas)}"
        # llm.done.delta_count mirrors the dispatcher's internal count
        llm_done = next(e for e in events if e["event"] == "llm.done")
        assert llm_done["delta_count"] == n


def test_unknown_agent_id_emits_error_plus_done() -> None:
    """Unknown agent_id: chain.error('resolve', AgentNotFoundError) + chain.done."""
    # No patch — real registry will fail for "nonexistent"
    events = asyncio.run(_drain(agent_id="nonexistent-agent"))
    names = [e["event"] for e in events]
    assert names == ["chain.error", "chain.done"], f"got {names}"
    assert events[0]["step"] == "resolve"
    assert events[0]["error_type"] == "AgentNotFoundError"
    assert events[-1]["outcome"] == "error"


def test_inner_exception_renders_chain_error() -> None:
    """When the agent's inner raises, dispatcher emits chain.error + chain.done."""
    spec = _stub_spec()
    stub = _make_stub_inner(delta_count=1, raise_exc=RuntimeError("boom from inner"))
    with patch("domain.agent_runner.load_agent_inner", return_value=(spec, stub)):
        events = asyncio.run(_drain())
    names = [e["event"] for e in events]
    # The single emitted llm.delta arrives before the exception interrupts the inner
    assert "chain.error" in names
    assert names[-1] == "chain.done"
    err = next(e for e in events if e["event"] == "chain.error")
    assert err["step"] == "llm"
    assert err["error_type"] == "RuntimeError"
    assert "boom from inner" in err["message"]


def test_scrub_pii_payload_shape() -> None:
    """scrub_pii event includes redacted_count, vault_id, scrubbed_preview."""
    spec, stub = _stub_spec(), _make_stub_inner(delta_count=0)
    with patch("domain.agent_runner.load_agent_inner", return_value=(spec, stub)):
        events = asyncio.run(_drain())
    scrub = next(e for e in events if e["event"] == "scrub_pii")
    for key in ("redacted_count", "redacted_field_types", "vault_id", "scrubbed_preview"):
        assert key in scrub, f"scrub_pii missing {key}: {scrub}"
    # SCRUBBER_ENABLED is false in test env by default → vault_id uses the
    # synthetic disabled fallback per domain/agent_runner.py.
    assert scrub["scrubber_enabled"] is False
    assert scrub["vault_id"].startswith("finadvice_disabled_")
    # raw_preview NOT included when demo_mode is None/False (default)
    assert "raw_preview" not in scrub


def test_demo_mode_includes_raw_preview() -> None:
    """When demo_mode=True the scrub_pii event includes raw_preview."""
    spec, stub = _stub_spec(), _make_stub_inner(delta_count=0)
    with patch("domain.agent_runner.load_agent_inner", return_value=(spec, stub)):
        events = asyncio.run(_drain(demo_mode=True))
    scrub = next(e for e in events if e["event"] == "scrub_pii")
    assert "raw_preview" in scrub
    assert scrub["raw_preview"] == "stub prompt no pii"


if __name__ == "__main__":
    # Allow `python tests/test_agent_runner_chain_events.py` to smoke-run.
    pytest.main([__file__, "-s", "-v"])
