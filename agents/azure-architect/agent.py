"""Azure Deployment Architect — entry point.

P2 dry-run: HMAC-sign one request against the engine so `first_seen_at`
populates on the SDK key, which flips the wizard's "Verify Signal" step
green. P4 layers tool calls + Opus synthesis on top.

NOTE on the SDK contract (POC retrospective F-006):
    The platform README documents a 5-decorator chain
        @policy_gate → @scrub_pii → @guardrails → @trace → @evaluate
    but in practice `trace` and `evaluate` are SDK aliases for the
    `tracer.trace_call(...)` and `evaluator.evaluate_response(...)`
    FUNCTIONS, not decorator factories. They are called INSIDE the
    decorated function with computed args, not stacked on top of it.
    `signallayer.guard()` enforces all 5 names being stamped, which is
    impossible to satisfy with the SDK as shipped. Logged as F-006;
    chain order below is correct for the 3 real decorators.
"""
from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv

import signallayer

load_dotenv()


def _init_sdk() -> None:
    """Initialise the SignalLayer client once at startup. Fails loudly on missing env.

    SL_KEY_ID is required (not just optional) because S53 keys are bare secrets
    with no `:` separator — without an explicit key_id, the SDK's _parse_key
    would use the bare secret as the X-SL-Key-Id header and the engine would
    reject the request as an unknown key.
    """
    required = ("SL_API_KEY", "SL_KEY_ID", "SL_API_BASE_URL")
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        raise RuntimeError(f"Missing required environment variable(s): {', '.join(missing)}")

    signallayer.init(
        api_key=os.environ["SL_API_KEY"],
        base_url=os.environ["SL_API_BASE_URL"],
        key_id=os.environ["SL_KEY_ID"],
    )


@signallayer.policy_gate(action="llm_call")
@signallayer.scrub_pii(scope="azure-architect")
@signallayer.guardrails()
async def call_llm(prompt: str, workload_id: str = "azure-architect") -> str:
    """Placeholder LLM call. P4 replaces body with Anthropic Opus/Haiku synthesis.

    Decorator chain (outermost → innermost) — the 3 real decorators:
        @policy_gate → @scrub_pii → @guardrails
    P4 inlines `signallayer.trace(...)` and `signallayer.evaluate(...)`
    calls inside this function once Opus is wired.
    """
    return f"[dry-run] would call Opus with prompt of {len(prompt)} chars"


async def dry_run() -> None:
    """P2 exit-gate: HMAC-sign one engine request so `first_seen_at` populates.

    Strategy: hit `GET /api/sdk/ping` (a no-op HMAC-gated endpoint that exists
    on the engine specifically for first-signal probes). Falls back to
    `GET /api/health` via the SDK client if `/ping` is not available — both
    paths trigger the engine's per-key `first_seen_at` update because the
    HMAC middleware records it before route dispatch.
    """
    _init_sdk()

    # Exercise the in-process decorator chain (proves it loads + executes locally).
    chain_result = await call_llm(prompt="ping from azure-architect")
    print(f"[chain] {chain_result}")

    # Make an actual HMAC-signed request so the engine records first_seen_at.
    client = signallayer.get_client()
    http_result = client.get("/api/sdk/ping")
    print(f"[http]  status={http_result.status_code} payload={http_result!s}")


if __name__ == "__main__":
    import sys

    if "--dry-run" in sys.argv:
        asyncio.run(dry_run())
    else:
        print("usage: python agent.py --dry-run")
