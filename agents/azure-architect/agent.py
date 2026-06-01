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
    PLAN_SYSTEM_PROMPT,
    PLAN_TOOL_SPECS,
    SYSTEM_PROMPT_REVIEW,
    TOKEN_BUDGETS,
    build_user_message,
)

# S60 STEP 2 — agent orchestration loop constants. The 5-turn cap is locked in
# SESSION-60 (cost compounds across turns + Anthropic tool_use can pathologically
# loop on ambiguous tool errors). Bump deliberately, never silently.
PLAN_TURN_CAP: int = 5
PLAN_LOG_PATH = Path(__file__).resolve().parents[2] / "data" / "plans.jsonl"
PLAN_SYNTHESIS_PATH = Path(__file__).resolve().parent / "eval" / "dataset.jsonl"


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

    # Streaming is REQUIRED per CLAUDE.md "Use streaming for any call with
    # max_tokens > 2000" and the [[anthropic-max-tokens-streaming-threshold]]
    # memory. architecture_review is 4096 — non-streaming messages.create()
    # at that budget disconnects mid-response via
    # anthropic.APIConnectionError ("Server disconnected without sending a
    # response"). _run_plan already uses this pattern; call_llm was missed.
    # Caught in S70b STEP 2 when the first real --review smoke ran after
    # S69 added write_episode. The streaming context manager collects the
    # full message via get_final_message() while keeping the connection
    # alive — same downstream contract (msg.content, msg.usage).
    with anthropic.messages.stream(
        model=model,
        max_tokens=TOKEN_BUDGETS["architecture_review"],
        system=SYSTEM_PROMPT_REVIEW,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        msg = stream.get_final_message()

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
            trace_id=trace_id,
            workload_id=workload_id,
            model=model,
        )
        print(f"[eval] metrics={list(eval_result.keys())}")
    except Exception as exc:  # noqa: BLE001
        print(f"[eval] FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)

    # 4. Persist Tier-2 episodic memory. write_episode is NOT a decorator —
    #    it's a POST-call inline, same pattern as trace_call + evaluate_response
    #    above. The decorator chain order (@policy_gate → @scrub_pii →
    #    @guardrails → @trace_llm_call → @evaluate_response) is unchanged;
    #    this extends the inline tail per S70b.
    #
    #    `prompt` here is the SCRUBBED text per the @scrub_pii contract, which
    #    is what agent_memory.write_episode requires. vault_id is the same
    #    synthesised value passed to tracer.trace_call above, so memory rows
    #    are joinable with trace rows on vault_id. Never swallow exceptions
    #    silently per [[bare-except-hides-broken-integrations]] — log the
    #    failure with module+exception, but never block the agent on memory
    #    write failure (memory is observability, not a gate).
    episode_id = ""
    try:
        # S71 Block A: route episode persistence through the SDK rather than
        # importing domain.agent_memory directly. Customer agents now talk to
        # the engine over signed HTTP, so they don't need sqlalchemy /
        # psycopg2 / a Postgres connection string locally. Engine's configured
        # memory backend (postgres in prod, jsonl in dev) decides where the
        # row lands.
        from signallayer import Err, write_episode

        # Outcome derived from eval pass-rate. eval_result shape:
        # {metric_name: {"score": float|None, "passed": bool|None,
        #                "details": str, "skipped": bool}}
        # Canonical skip signal is `payload.skipped` (set by evaluator.py per
        # metric); `score is None` correlates 1:1 today but is the indirect
        # form. Drop skipped metrics before classifying outcome — otherwise
        # an otherwise-passing review would land outcome="failure" because
        # hallucination + faithfulness emit passed=False on empty context.
        if eval_result:
            scored = [
                p for p in eval_result.values()
                if isinstance(p, dict) and not p.get("skipped")
            ]
            any_failed = any(p.get("passed") is False for p in scored)
            any_passed = any(p.get("passed") is True for p in scored)
            if any_failed:
                outcome = "failure"
            elif any_passed:
                outcome = "success"
            else:
                outcome = "review"
        else:
            outcome = "review"

        # eval_summary is a small, self-describing roll-up so the episode row
        # is useful in a future episode browser without rejoining to evals.jsonl.
        eval_summary: dict[str, Any] = {
            metric: {
                "score": payload.get("score"),
                "passed": payload.get("passed"),
                "skipped": bool(payload.get("skipped")),
            }
            for metric, payload in eval_result.items()
            if isinstance(payload, dict)
        }

        result = write_episode(
            workload_id=workload_id,
            prompt=prompt,
            response=response_text,
            outcome=outcome,
            metadata={
                "agent": "azure-architect",
                "model": model,
                "latency_ms": latency_ms,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "trace_id": trace_id,
                "vault_id": vault_id,
                "eval_summary": eval_summary,
            },
        )
        if isinstance(result, Err):
            # Typed SDK error — log full provenance per
            # [[bare-except-hides-broken-integrations]] but never block the
            # agent on memory failure.
            print(
                f"[memory] write_episode SDK Err: status={result.status_code} "
                f"{type(result.error).__name__}: {result.message}",
                file=sys.stderr,
            )
        else:
            episode_id = result.value
            print(f"[memory] episode_id={episode_id} outcome={outcome}")
    except Exception as exc:  # noqa: BLE001
        # Unexpected non-SDK path (e.g. signallayer not init'd). Log module +
        # exception name + message; episode_id stays "".
        print(
            f"[memory] write_episode FAILED: "
            f"{type(exc).__module__}.{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )

    return {
        "response": response_text,
        "model": model,
        "latency_ms": latency_ms,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "trace_id": trace_id,
        "eval": eval_result,
        "vault_id": vault_id,
        "episode_id": episode_id,
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


# --- S60 STEP 2: agent orchestration loop ------------------------------------
#
# Anthropic tool_use loop with a hard 5-turn cap.
# Each turn:
#   1. Call Claude with the current message stack + tool specs
#   2. Append a per-turn row to data/plans.jsonl (turn no, stop_reason, calls)
#   3. If stop_reason != "tool_use", break — model is done
#   4. Otherwise dispatch each tool_use block through the local dispatch
#      table (every tool fn is already governed by @policy_gate); append
#      tool_result blocks; loop
# Final synthesis: one JSONL row to eval/dataset.jsonl in the canonical
# (input, output, context, metadata) shape so S58's eval harness picks it up
# without further plumbing.


def _build_tool_dispatch(subscription_id: str) -> dict[str, Any]:
    """Map tool_name → coroutine factory.

    We pre-bind `subscription_id` here because the Anthropic input_schema
    advertises it as required but the model may still occasionally omit it
    under tight token pressure. A late KeyError inside the loop would burn
    a retry; defaulting to the operator-supplied value is safer.

    Each entry returns an *awaitable* — the loop is responsible for awaiting
    it so we can `gather` parallel tool_use blocks in a future turn.
    """
    from azure.identity import DefaultAzureCredential  # local import — see arm_read
    from tools.arm_read import (
        get_resource_metadata,
        list_resource_groups,
        list_resources_in_group,
    )

    cred = DefaultAzureCredential()

    async def _list_rgs(tool_input: dict) -> Any:
        sub = tool_input.get("subscription_id") or subscription_id
        result = await list_resource_groups(credential=cred, subscription_id=sub)
        return result.model_dump()

    async def _list_resources(tool_input: dict) -> Any:
        sub = tool_input.get("subscription_id") or subscription_id
        rg = tool_input.get("resource_group")
        if not rg:
            # The Anthropic input_schema marks resource_group required, but a
            # missing-arg here would still raise TypeError downstream. Render
            # it back as a typed error so the model self-corrects on the next
            # turn rather than the loop aborting.
            raise ValueError(
                "list_resources_in_group requires 'resource_group' "
                "(name from a prior list_resource_groups call)."
            )
        result = await list_resources_in_group(
            credential=cred, subscription_id=sub, resource_group=rg
        )
        return result.model_dump()

    async def _get_metadata(tool_input: dict) -> Any:
        rid = tool_input.get("resource_id")
        if not rid:
            # Same pattern as _list_resources: surface the missing-arg as a
            # typed error so the model self-corrects rather than the loop
            # aborting on TypeError.
            raise ValueError(
                "get_resource_metadata requires 'resource_id' "
                "(full ARM id from a prior list_resources_in_group call)."
            )
        result = await get_resource_metadata(credential=cred, resource_id=rid)
        return result.model_dump()

    return {
        "list_resource_groups": _list_rgs,
        "list_resources_in_group": _list_resources,
        "get_resource_metadata": _get_metadata,
    }


@signallayer.policy_gate(action="llm_call")
@signallayer.scrub_pii(scope="azure-architect-plan")
@signallayer.guardrails()
async def _run_plan(
    prompt: str,
    subscription_id: str,
    *,
    model: str = MODEL_FAST,
    vault_id: str = "",
    workload_id: str = os.environ.get("SL_WORKLOAD_ID", "azure-architect"),
) -> dict[str, Any]:
    """Drive one --plan run end-to-end.

    S79: now runs under the canonical decorator chain
    (@policy_gate → @scrub_pii → @guardrails) so the operator's request is
    policy-gated, PII-scrubbed, and safety-checked at entry — closing the
    tool-using-agent gap memorialized in [[ui-promise-audit-owed]]. The
    `prompt` kwarg is the scrubbed text by the time the body runs; vault_id
    is injected by @scrub_pii.

    Caveat: tool_result blocks coming back from ARM API calls within the
    5-turn loop are NOT re-scrubbed per turn. Per-turn protection of tool
    args is S85 (Tier-3 health) scope; this session closes the entry gate.

    Returns a dict with: synthesis (str), turns (int), stop_reason (str),
    run_id (str), tool_calls (list of summaries), cost_usd (float),
    episode_id (str), vault_id (str).
    """
    import uuid
    from anthropic import Anthropic
    import storage  # engine root must be on PYTHONPATH

    # Body still reads operator_request for clarity; alias keeps the original
    # message-build / synthesis-log lines unchanged.
    operator_request = prompt

    _init_sdk()
    anthropic = Anthropic(api_key=_require_anthropic_key())
    run_id = f"plan-{uuid.uuid4().hex[:12]}"

    # vault_id fallback mirrors call_llm: when SCRUBBER_ENABLED=false,
    # @scrub_pii is a no-op and vault_id is empty. Synthesise one from the
    # scrubbed prompt hash so trace/episode rows remain joinable.
    if not vault_id:
        vault_id = (
            "azure-architect-plan_nopii_"
            + hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]
        )

    dispatch = _build_tool_dispatch(subscription_id)

    messages: list[dict[str, Any]] = [
        {"role": "user", "content": (
            f"{operator_request.strip()}\n\n"
            f"Subscription scope: {subscription_id}"
        )},
    ]
    tool_call_summaries: list[dict[str, Any]] = []
    final_text = ""
    final_stop = ""
    turn = 0

    for turn in range(PLAN_TURN_CAP):
        started = time.monotonic()
        # Streaming is REQUIRED per CLAUDE.md "Use streaming for any call with
        # max_tokens > 2000". Non-streaming messages.create() at max_tokens
        # 4096 disconnects intermittently via anthropic.APIConnectionError
        # ("Server disconnected without sending a response") — the edge times
        # out before the full payload flushes. The streaming context manager
        # collects the full message via get_final_message() while keeping
        # the connection alive. S62 caught this; prior S61 single-turn run
        # worked at 2048 (under the threshold) and masked the bug.
        with anthropic.messages.stream(
            model=model,
            max_tokens=TOKEN_BUDGETS["plan_turn"],
            system=PLAN_SYSTEM_PROMPT,
            tools=PLAN_TOOL_SPECS,
            messages=messages,
        ) as stream:
            msg = stream.get_final_message()
        elapsed_ms = int((time.monotonic() - started) * 1000)

        # Extract any text blocks emitted this turn (the final turn typically
        # produces only text; intermediate turns may produce text + tool_use).
        turn_text = "".join(
            b.text for b in msg.content if getattr(b, "type", None) == "text"
        )
        tool_uses = [b for b in msg.content if getattr(b, "type", None) == "tool_use"]

        # Per-turn telemetry → data/plans.jsonl (CLAUDE.md storage rule)
        storage._append_jsonl(PLAN_LOG_PATH, {
            "run_id": run_id,
            "turn": turn,
            "model": model,
            "stop_reason": msg.stop_reason,
            "elapsed_ms": elapsed_ms,
            "input_tokens": int(getattr(msg.usage, "input_tokens", 0) or 0),
            "output_tokens": int(getattr(msg.usage, "output_tokens", 0) or 0),
            "tool_calls": [{"name": tu.name, "input": tu.input} for tu in tool_uses],
            "text_chars": len(turn_text),
        })

        final_stop = msg.stop_reason or ""
        if msg.stop_reason != "tool_use":
            final_text = turn_text
            break

        # Append assistant message verbatim so tool_use_id references resolve.
        messages.append({"role": "assistant", "content": msg.content})

        # Dispatch each tool_use → tool_result. The @policy_gate decorator on
        # each tool fn surfaces PolicyDeniedError; we render that back to the
        # model as an error tool_result so the model can self-correct rather
        # than the loop aborting (defense in depth: rego allowlist already
        # constrains which tools the model can call).
        tool_results: list[dict[str, Any]] = []
        for tu in tool_uses:
            fn = dispatch.get(tu.name)
            if fn is None:
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "is_error": True,
                    "content": f"Tool '{tu.name}' is not implemented in this build.",
                })
                tool_call_summaries.append({"tool": tu.name, "ok": False, "reason": "unimplemented"})
                continue
            try:
                result = await fn(tu.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": json.dumps(result, default=str),
                })
                tool_call_summaries.append({"tool": tu.name, "ok": True})
            except Exception as exc:  # noqa: BLE001
                # PolicyDeniedError or any tool runtime error lands here. We
                # surface the message to the model — never swallow silently
                # ([[bare-except-hides-broken-integrations]]).
                err_msg = f"{type(exc).__name__}: {exc}"
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "is_error": True,
                    "content": err_msg,
                })
                tool_call_summaries.append({"tool": tu.name, "ok": False, "reason": err_msg})
                print(f"[plan turn={turn}] tool {tu.name} failed: {err_msg}", file=sys.stderr)

        messages.append({"role": "user", "content": tool_results})
    else:
        # Loop completed without break — hit the turn cap without final synthesis.
        final_stop = "turn_cap_reached"
        final_text = "(no synthesis — agent hit the 5-turn cap)"

    # Final synthesis row to eval/dataset.jsonl. Four canonical fields so
    # S58's eval harness picks it up unchanged.
    PLAN_SYNTHESIS_PATH.parent.mkdir(parents=True, exist_ok=True)
    storage._append_jsonl(PLAN_SYNTHESIS_PATH, {
        "input": operator_request,
        "output": final_text,
        "context": tool_call_summaries,
        "metadata": {
            "run_id": run_id,
            "turns": turn + 1,
            "stop_reason": final_stop,
            "model": model,
            "subscription_id": subscription_id,
            "agent": "azure-architect",
        },
    })

    # S79: persist the plan synthesis to Tier-2 episodic memory via the SDK,
    # same pattern as call_llm. Outcome derived from terminal stop_reason:
    # "end_turn" = model produced clean synthesis = success; turn_cap_reached
    # = the agent exhausted its budget without finishing = failure; anything
    # else (rare — pause_turn, max_tokens) = review.
    if final_stop == "end_turn":
        outcome = "success"
    elif final_stop == "turn_cap_reached":
        outcome = "failure"
    else:
        outcome = "review"

    episode_id = ""
    try:
        from signallayer import Err, write_episode

        result = write_episode(
            workload_id=workload_id,
            prompt=prompt,
            response=final_text,
            outcome=outcome,
            metadata={
                "agent": "azure-architect",
                "surface": "plan",
                "run_id": run_id,
                "model": model,
                "turns": turn + 1,
                "stop_reason": final_stop,
                "subscription_id": subscription_id,
                "tool_calls": tool_call_summaries,
                "vault_id": vault_id,
            },
        )
        if isinstance(result, Err):
            print(
                f"[memory] write_episode SDK Err: status={result.status_code} "
                f"{type(result.error).__name__}: {result.message}",
                file=sys.stderr,
            )
        else:
            episode_id = result.value
            print(f"[memory] episode_id={episode_id} outcome={outcome}")
    except Exception as exc:  # noqa: BLE001
        print(
            f"[memory] write_episode FAILED: "
            f"{type(exc).__module__}.{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )

    return {
        "run_id": run_id,
        "turns": turn + 1,
        "stop_reason": final_stop,
        "synthesis": final_text,
        "tool_calls": tool_call_summaries,
        "vault_id": vault_id,
        "episode_id": episode_id,
    }


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
        f"trace_id={result['trace_id'] or '(none)'}  vault_id={result['vault_id'] or '(none)'}  "
        f"episode_id={result.get('episode_id') or '(none)'}"
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
        "  python agent.py --plan \"<request>\" --subscription <sub-id>\n"
        "                                       # S60 orchestration loop (5-turn cap)\n"
        "Optional:\n"
        "  --fast    Use Sonnet 4.6 instead of Opus 4.7 (cheaper, faster).\n"
        "            --plan defaults to Sonnet because cost compounds per turn.\n"
    )


def _arg_value(argv: list[str], flag: str) -> str | None:
    """Pull the value following `flag` from argv, or None."""
    if flag not in argv:
        return None
    idx = argv.index(flag)
    if idx + 1 >= len(argv):
        raise SystemExit(f"{flag} requires a value")
    return argv[idx + 1]


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
    elif "--plan" in argv:
        request = _arg_value(argv, "--plan")
        if not request or not request.strip():
            raise SystemExit("--plan requires a non-empty request string.")
        subscription = _arg_value(argv, "--subscription")
        if not subscription:
            subscription = os.environ.get("AZURE_SUBSCRIPTION_ID", "").strip()
        if not subscription:
            raise SystemExit(
                "--plan requires --subscription <sub-id> or AZURE_SUBSCRIPTION_ID env var."
            )
        # Default Sonnet for --plan: cost compounds per turn (S60 lock).
        # --fast is a no-op here but harmless; --deep can force Opus.
        model = MODEL_DEEP if "--deep" in argv else MODEL_FAST
        result = asyncio.run(_run_plan(prompt=request, subscription_id=subscription, model=model))
        print("\n" + "=" * 72)
        print(f"PLAN RUN {result['run_id']}  turns={result['turns']}  "
              f"stop={result['stop_reason']}  tools={len(result['tool_calls'])}")
        print("=" * 72 + "\n")
        print(result["synthesis"])
        print("\n" + "=" * 72)
        print(f"plans.jsonl: {PLAN_LOG_PATH}")
        print(f"dataset.jsonl: {PLAN_SYNTHESIS_PATH}")
    else:
        print(_usage())
        raise SystemExit(2)
