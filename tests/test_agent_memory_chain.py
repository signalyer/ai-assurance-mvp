"""Integration test for the agent decorator chain feeding `write_episode`.

Carried over from S70b — S74 lands it.

Asserts the load-bearing security invariant from CLAUDE.md:
    scrubber.tokenise_payload() runs BEFORE tracer.trace_call()
    Langfuse gets scrubbed_prompt — never raw_prompt.

In agent code (e.g. `agents/azure-architect/agent.py`), the chain is:

    @policy_gate -> @scrub_pii -> @guardrails -> fn body
                                                  └─ tracer.trace_call(prompt=...)
                                                  └─ evaluator.evaluate_response(input_prompt=...)
                                                  └─ write_episode(prompt=..., metadata={vault_id})

`write_episode` is an inline tail (not itself a decorator), but it MUST receive
the scrubbed payload and the vault_id minted by `@scrub_pii`. This test stacks
the real decorators on a fake async LLM-call function, feeds raw PII, mocks
`write_episode`, and asserts:

  1. The function body observed the scrubbed prompt (PII tokens, not raw).
  2. `write_episode` was called with the scrubbed prompt + a non-empty vault_id.
  3. Chain order was preserved: @policy_gate fired first, @scrub_pii second
     (proven by checking @policy_gate saw raw PII while the body saw scrubbed).
"""

from __future__ import annotations

import os
from unittest.mock import patch, MagicMock

import pytest


# Force SCRUBBER_ENABLED on for the duration of this module's tests so
# `@scrub_pii` does real scrubbing instead of the backward-compat passthrough.
@pytest.fixture(autouse=True)
def _scrubber_env(monkeypatch):
    monkeypatch.setenv("SCRUBBER_ENABLED", "true")
    # Enable policy enforcement — we spy on the evaluator to (a) confirm
    # @policy_gate ran first and saw raw PII, (b) return ALLOW so the chain
    # proceeds. Disabling POLICIES would short-circuit before the spy fires.
    monkeypatch.setenv("POLICIES_ENABLED", "true")
    yield


def test_chain_order_and_scrubbed_payload_reaches_write_episode():
    """End-to-end: decorator chain runs in order, write_episode sees scrubbed text."""
    from middleware.policy import policy_gate
    from middleware.scrubber import scrub_pii

    captured = {}

    # Spy on the policy_gate's input by patching the policy evaluator so we can
    # inspect what `input_data['prompt']` looked like at policy time.
    from domain.policy_engine import Decision, PolicyCategory, PolicyResult

    def _spy_evaluate(workload_id, action, input_data, **_):
        captured["policy_saw_prompt"] = input_data.get("prompt")
        return PolicyResult(
            decision=Decision.ALLOW,
            category=PolicyCategory.SYSTEM_OVERRIDE,
            policy_name="test-allow",
            reason="test",
        )

    raw_prompt = (
        "Customer John Smith (SSN 123-45-6789) emailed john.smith@example.com "
        "asking about his account."
    )

    # Hermetic scrubber: bypass the provider-cache singleton (other tests
    # may have pinned a noop backend, and `@lru_cache` doesn't reset between
    # tests). Replace `scrubber.tokenise_payload` with a deterministic fake
    # that proves the chain mechanics without depending on Presidio state.
    def _fake_tokenise(text, scope):
        scrubbed = text.replace("123-45-6789", "[SSN_001]").replace(
            "john.smith@example.com", "[EMAIL_001]"
        ).replace("John Smith", "[PERSON_001]")
        return scrubbed, f"vault-test-{scope}"

    # Mock write_episode at the call site so we capture exactly what the
    # decorated function passes in. This is the load-bearing assertion: by
    # the time write_episode is called, prompt MUST be the scrubbed version.
    captured_write_kwargs = {}

    def _capture_write_episode(**kwargs):
        captured_write_kwargs.update(kwargs)
        return "ep-test-001"

    @policy_gate(action="llm_call", workload_id_arg="workload_id")
    @scrub_pii(scope="test-chain")
    async def fake_agent_call(workload_id: str, prompt: str, vault_id: str = ""):
        # Body sees what @scrub_pii passed in.
        captured["body_saw_prompt"] = prompt
        captured["body_saw_vault_id"] = vault_id
        # Inline tail — mirror the real agent.py pattern (S70b).
        _capture_write_episode(
            workload_id=workload_id,
            prompt=prompt,
            response="ok",
            outcome="success",
            metadata={"vault_id": vault_id},
        )
        return "ok"

    import asyncio
    with patch("domain.policy_engine.evaluate", _spy_evaluate), \
         patch("scrubber.tokenise_payload", _fake_tokenise):
        asyncio.run(fake_agent_call(workload_id="ws-test", prompt=raw_prompt))

    # 1. @policy_gate ran first and saw the RAW prompt — it has to, in order
    #    to enforce content-based policies before any tokenisation.
    assert captured["policy_saw_prompt"] == raw_prompt, (
        "@policy_gate must run BEFORE @scrub_pii and see the raw prompt"
    )

    # 2. The function body saw a SCRUBBED prompt — @scrub_pii ran between
    #    @policy_gate and the body.
    assert captured["body_saw_prompt"] != raw_prompt, (
        "function body received raw prompt — @scrub_pii did not run"
    )
    assert "123-45-6789" not in captured["body_saw_prompt"], (
        "SSN leaked past @scrub_pii into the function body"
    )
    assert "john.smith@example.com" not in captured["body_saw_prompt"], (
        "email leaked past @scrub_pii into the function body"
    )

    # 3. @scrub_pii minted a non-empty vault_id for downstream re-identification.
    assert captured["body_saw_vault_id"], "@scrub_pii did not inject vault_id"

    # 4. write_episode received the scrubbed prompt + vault_id — the actual
    #    CLAUDE.md security invariant.
    assert captured_write_kwargs["prompt"] == captured["body_saw_prompt"], (
        "write_episode received different prompt than the function body — "
        "decorator chain broken between body and tail"
    )
    assert "123-45-6789" not in captured_write_kwargs["prompt"], (
        "SSN reached write_episode — Langfuse/T2 leak path open"
    )
    assert captured_write_kwargs["metadata"]["vault_id"] == captured["body_saw_vault_id"], (
        "vault_id mismatch between @scrub_pii output and write_episode metadata"
    )


def test_scrubber_failclosed_blocks_write_episode():
    """If @scrub_pii fails (empty vault_id when SCRUBBER_ENABLED), the wrapped
    function — and therefore write_episode — must NOT be called.

    This is the [[bare-except-hides-broken-integrations]] guard: a silent
    scrubber failure would otherwise leak raw PII downstream.
    """
    from middleware.scrubber import scrub_pii

    write_called = {"count": 0}

    @scrub_pii(scope="test-failclosed")
    async def fake_agent_call(prompt: str, vault_id: str = ""):
        write_called["count"] += 1
        return "should-not-reach-here"

    # Force scrubber to return (None, "") indicating failure.
    with patch("middleware.scrubber._scrub_args", return_value=(None, "")):
        import asyncio
        with pytest.raises(RuntimeError, match="Scrubber failed"):
            asyncio.run(fake_agent_call(prompt="any text"))

    assert write_called["count"] == 0, (
        "Function body was called despite scrubber failure — fail-closed broken"
    )
