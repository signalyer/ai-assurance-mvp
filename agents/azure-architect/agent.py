"""Azure Deployment Architect — entry point.

P2 wizard pastes the SDK init block + decorator chain into this file.
P4 layers tool calls + Opus synthesis on top. Until then this is a dry-run shell.
"""
from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv

import signallayer

load_dotenv()


def _init_sdk() -> None:
    """Initialise the SignalLayer client once at startup. Fails loudly on missing env."""
    required = ("SL_API_KEY", "SL_API_BASE_URL")
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        raise RuntimeError(f"Missing required environment variable(s): {', '.join(missing)}")

    signallayer.init(
        api_key=os.environ["SL_API_KEY"],
        base_url=os.environ["SL_API_BASE_URL"],
    )


@signallayer.policy_gate(action="llm_call")
@signallayer.scrub_pii(scope="azure-architect")
@signallayer.guardrails()
async def call_llm(prompt: str, workload_id: str = "azure-architect") -> str:
    """Placeholder LLM call. P4 replaces body with Anthropic Opus/Haiku synthesis."""
    return f"[dry-run] would call Opus with prompt of {len(prompt)} chars"


signallayer.guard(call_llm)


async def dry_run() -> None:
    """P2 exit-gate: one decorated call to register `first_seen_at` on the SDK key."""
    _init_sdk()
    result = await call_llm(prompt="ping from azure-architect")
    print(result)


if __name__ == "__main__":
    import sys

    if "--dry-run" in sys.argv:
        asyncio.run(dry_run())
    else:
        print("usage: python agent.py --dry-run")
