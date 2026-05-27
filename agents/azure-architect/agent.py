"""Azure Deployment Architect — agent entry point.

Modes:
  --dry-run                  : HMAC-sign one /api/sdk/health probe (no LLM call).
                               Useful for verifying the SignalLayer signed
                               transport without spending tokens.
  --review "<text>"          : Real Anthropic-backed WAF review of the supplied
                               Azure architecture description. Full SignalLayer
                               governance: policy_gate → scrub_pii → guardrails
                               (pre-call), then trace_call + evaluate_response
                               (post-call, inline per F-006).
  --review-file <path>       : Same as --review but reads the description from
                               a file. Handy for multi-paragraph inputs.
  --fast                     : Use Sonnet 4.6 instead of Opus 4.7. ~5x cheaper,
                               ~3x faster, slightly less rigorous reasoning.

Governance pipeline (per the platform README + F-006 retrospective):
  PRE-call decorators (mandatory order, enforced by signallayer.guard()):
    @policy_gate    : OPA-style allow/deny on the requested action
    @scrub_pii      : tokenise_payload() replaces PII with [TYPE_NNN] tokens
                      and returns a vault_id for de-ID traceability
    @guardrails     : input-side safety checks (jailbreak / injection / topics)

  POST-call inline calls (not decorators — they need computed args):
    tracer.trace_call(...)        : ship SCRUBBED prompt + response to the engine
    evaluator.evaluate_response() : run 5 metrics against the response

Security rule (project CLAUDE.md): scrubber.tokenise_payload() runs BEFORE
tracer.trace_call(). The @scrub_pii decorator already enforces this — the
`prompt` variable inside call_llm holds the SCRUBBED text, and `vault_id`
is injected by the decorator. We pass both downstream.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

# Windows consoles default to cp1252 which can't encode characters Opus +
# Sonnet routinely emit (→, ✓, –, etc.). Force utf-8 so --review output
# prints cleanly. Safe no-op on already-utf-8 terminals.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from dotenv import load_dotenv

import signallayer

# Engine-side functions for the post-call inline pipeline. Import lazily inside
# call_llm to keep the dry-run path independent of the engine modules being
# importable (avoids the F-006 "must run from engine root" requirement for
# anything that doesn't actually need trace/eval).
#
# from tracer import trace_call           # imported in call_llm
# from evaluator import evaluate_response # imported in call_llm

from prompts import (
    MODEL_DEEP,
    MODEL_FAST,
    SYSTEM_PROMPT_REVIEW,
    TOKEN_BUDGETS,
    build_user_message,
)


# Load the agent's own .env regardless of cwd. We're typically launched
# from the engine root (`PYTHONPATH=. python agents/azure-architect/agent.py`)
# because the SDK decorators need engine modules importable; the default
# load_dotenv() would then look for .env in the engine root and miss the
# agent's. Explicit path-based load matches the agent's actual config home.
# override=True because shells sometimes export the var as empty (PowerShell
# `$env:ANTHROPIC_API_KEY=""` leaves it set-but-empty); without override the
# empty shell value wins over a real value in .env and _require_anthropic_key()
# rejects it. The agent's .env is the authoritative config home for this
# workload, not the inherited shell.
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env", override=True)


# --- SignalLayer SDK init ----------------------------------------------------


def _init_sdk() -> None:
    """Initialise the SignalLayer client. Fails loudly on missing env."""
    required = ("SL_API_KEY", "SL_KEY_ID", "SL_API_BASE_URL")
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        raise RuntimeError(
            f"Missing required SignalLayer env var(s): {', '.join(missing)}"
        )
    signallayer.init(
        api_key=os.environ["SL_API_KEY"],
        base_url=os.environ["SL_API_BASE_URL"],
        key_id=os.environ["SL_KEY_ID"],
    )


def _require_anthropic_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set. Add it to "
            "agents/azure-architect/.env (or your shell) before --review."
        )
    return key


# --- The governed LLM call ---------------------------------------------------
#
# The decorator chain runs in this order on call entry:
#   1. policy_gate    : allows the action OR raises PolicyDenied
#   2. scrub_pii      : replaces PII in `prompt`, injects vault_id kwarg
#   3. guardrails     : input safety; can refuse or proceed
# Then the function body runs (real Anthropic call), and we inline-invoke
# trace_call + evaluate_response on the way out.


@signallayer.policy_gate(action="llm_call")
@signallayer.scrub_pii(scope="azure-architect")
@signallayer.guardrails()
async def call_llm(
    prompt: str,
    *,
    model: str = MODEL_DEEP,
    vault_id: str = "",
    workload_id: str = os.environ.get("SL_WORKLOAD_ID", "azure-architect"),
) -> dict[str, Any]:
    """Governed Anthropic call for one architecture review.

    By the time this function body runs, the decorator chain has already:
      - confirmed policy allows action="llm_call" for this workload
      - replaced PII in `prompt` (now holds scrubbed text) + injected `vault_id`
      - run input-side guardrails

    This function body:
      1. Calls Anthropic Claude with the scrubbed prompt + WAF system prompt
      2. Inlines tracer.trace_call(...) with the SCRUBBED prompt + response
      3. Inlines evaluator.evaluate_response(...) to score the output
      4. Returns a structured result so the caller can render / persist

    Returns a dict with keys:
      - response: str   — the LLM markdown review
      - model: str
      - latency_ms: int
      - input_tokens: int
      - output_tokens: int
      - trace_id: str   — engine-assigned trace identifier (or "" on failure)
      - eval: dict      — metric_name → {score, passed, details} (or {} on fail)
      - vault_id: str   — scrubber's de-ID handle for this request
    """
    # 1. The real LLM call. Anthropic client is constructed per-call to keep
    #    this function self-contained; for high-volume use a module-level
    #    client would be more efficient (CLAUDE.md guidance).
    from anthropic import Anthropic

    anthropic = Anthropic(api_key=_require_anthropic_key())
    started = time.monotonic()

    msg = anthropic.messages.create(
        model=model,
        max_tokens=TOKEN_BUDGETS["architecture_review"],
        system=SYSTEM_PROMPT_REVIEW,
        messages=[{"role": "user", "content": prompt}],
    )

    latency_ms = int((time.monotonic() - started) * 1000)
    # Anthropic responses are a list of content blocks; concat text blocks.
    response_text = "".join(
        block.text for block in msg.content if getattr(block, "type", None) == "text"
    )
    input_tokens = int(getattr(msg.usage, "input_tokens", 0) or 0)
    output_tokens = int(getattr(msg.usage, "output_tokens", 0) or 0)
    total_tokens = input_tokens + output_tokens

    print(
        f"[llm] model={model} latency_ms={latency_ms} "
        f"in={input_tokens} out={output_tokens} (total={total_tokens})"
    )

    # 2. Trace the call. Per the security rule, the prompt passed to
    #    trace_call MUST be the scrubbed text — which is what `prompt`
    #    already holds at this point thanks to @scrub_pii.
    #
    #    vault_id fallback: when SCRUBBER_ENABLED is false at the engine
    #    level, @scrub_pii is a no-op and returns an empty vault_id, but
    #    tracer.trace_call() requires a non-empty value for de-ID
    #    traceability. Synthesise one from the scrubbed-prompt hash so
    #    trace records remain joinable. Mirrors the scrubber's own
    #    "no PII detected" fallback (middleware/scrubber.py:160).
    if not vault_id:
        vault_id = (
            "azure-architect_nopii_"
            + hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]
        )
    trace_id = ""
    try:
        from tracer import trace_call

        trace_id = trace_call(
            model=model,
            prompt=prompt,
            response=response_text,
            latency_ms=latency_ms,
            tokens_used=total_tokens,
            metadata={
                "workload_id": workload_id,
                "vault_id": vault_id,
                "agent": "azure-architect",
            },
        )
        print(f"[trace] trace_id={trace_id}")
    except Exception as exc:  # noqa: BLE001
        # Never block the agent on telemetry failure — log + carry on.
        print(f"[trace] FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)

    # 3. Evaluate the response. Five-metric scoring; context can be empty
    #    for a "design review" task — we don't have ground truth to compare
    #    against, so hallucination/faithfulness metrics will report N/A.
    eval_result: dict[str, Any] = {}
    try:
        from evaluator import evaluate_response

        eval_result = evaluate_response(
            input_prompt=prompt,
            actual_output=response_text,
            expected_output="",
            context=[],
        )
        print(f"[eval] metrics={list(eval_result.keys())}")
    except Exception as exc:  # noqa: BLE001
        print(f"[eval] FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)

    return {
        "response": response_text,
        "model": model,
        "latency_ms": latency_ms,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "trace_id": trace_id,
        "eval": eval_result,
        "vault_id": vault_id,
    }


# --- Public entry points -----------------------------------------------------


async def review_architecture(architecture_text: str, *, fast: bool = False) -> dict[str, Any]:
    """End-to-end: SDK init + governed Anthropic review + trace + eval."""
    _init_sdk()
    model = MODEL_FAST if fast else MODEL_DEEP
    user_message = build_user_message(architecture_text)
    return await call_llm(prompt=user_message, model=model)


async def dry_run() -> None:
    """P2 exit-gate kept intact: HMAC-sign one /api/sdk/health probe."""
    _init_sdk()
    client = signallayer.get_client()
    http_result = client.get("/api/sdk/health")
    print(f"[http] status={http_result.status_code} payload={http_result!s}")


def _print_review(result: dict[str, Any]) -> None:
    """Render the review + the eval scoreboard to stdout."""
    print("\n" + "=" * 72)
    print("AZURE ARCHITECTURE REVIEW")
    print("=" * 72 + "\n")
    print(result["response"])
    print("\n" + "=" * 72)
    print("EVAL SCOREBOARD")
    print("=" * 72)
    if not result["eval"]:
        print("  (evaluation skipped or failed — see stderr)")
    else:
        for metric, payload in result["eval"].items():
            passed = payload.get("passed")
            mark = "✓" if passed is True else "✗" if passed is False else "~"
            score = payload.get("score")
            score_str = f"{score:.2f}" if isinstance(score, (int, float)) else "N/A"
            details = payload.get("details", "")
            print(f"  {mark} {metric:24s} {score_str:>6s}   {details}")
    print("=" * 72)
    print(
        f"model={result['model']}  latency_ms={result['latency_ms']}  "
        f"tokens_in={result['input_tokens']}  tokens_out={result['output_tokens']}  "
        f"trace_id={result['trace_id'] or '(none)'}  vault_id={result['vault_id'] or '(none)'}"
    )
    print("=" * 72 + "\n")


def _load_architecture_text(args: list[str]) -> str:
    """Resolve the architecture description from CLI args.

    Supports `--review "<text>"` and `--review-file <path>` and (for piped
    input) `--review -` to read stdin.
    """
    if "--review-file" in args:
        idx = args.index("--review-file")
        if idx + 1 >= len(args):
            raise SystemExit("--review-file requires a path argument")
        path = Path(args[idx + 1])
        if not path.exists():
            raise SystemExit(f"--review-file: not found: {path}")
        return path.read_text(encoding="utf-8")

    if "--review" in args:
        idx = args.index("--review")
        if idx + 1 >= len(args):
            raise SystemExit("--review requires a text argument (or '-' for stdin)")
        text = args[idx + 1]
        if text == "-":
            return sys.stdin.read()
        return text

    raise SystemExit("internal: _load_architecture_text called without --review*")


def _usage() -> str:
    return (
        "Azure Deployment Architect — usage:\n"
        "  python agent.py --dry-run\n"
        "  python agent.py --review \"<architecture description>\"\n"
        "  python agent.py --review-file <path>\n"
        "  python agent.py --review -          # read description from stdin\n"
        "Optional:\n"
        "  --fast    Use Sonnet 4.6 instead of Opus 4.7 (cheaper, faster)\n"
    )


if __name__ == "__main__":
    argv = sys.argv[1:]
    if not argv or "--help" in argv or "-h" in argv:
        print(_usage())
        raise SystemExit(0)

    fast = "--fast" in argv

    if "--dry-run" in argv:
        asyncio.run(dry_run())
    elif "--review" in argv or "--review-file" in argv:
        text = _load_architecture_text(argv)
        if not text.strip():
            raise SystemExit("Empty architecture description.")
        result = asyncio.run(review_architecture(text, fast=fast))
        _print_review(result)
    else:
        print(_usage())
        raise SystemExit(2)
