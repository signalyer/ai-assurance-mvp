"""finadvice — Financial Advisor Risk Reviewer agent entry point.

The entry point the Agent Runner dispatches is `run_review(prompt, **kwargs)`.
Registered in `agents/_registry.py` as `agent_id="finadvice"`.

Governance pipeline (mirrors agents/azure-architect/agent.py `_run_plan`):

  Decorator chain (mandatory order, enforced by signallayer):
    @policy_gate(action="llm_call")    # OPA-style allow/deny on the action
    @scrub_pii(scope="finadvice")      # tokenise_payload replaces PII in
                                         # `prompt` with [TYPE_NNN] tokens
                                         # and injects vault_id kwarg
    @guardrails()                      # input-side safety (jailbreak / topics)

  Post-call inline (after the tool-use loop synthesises):
    write_episode(...)                 # Tier-2 episodic memory via the SDK

Security rule (project CLAUDE.md): scrubber.tokenise_payload() runs BEFORE
anything downstream. The @scrub_pii decorator already enforces this — by
the time the function body runs, `prompt` holds the SCRUBBED text and
`vault_id` is injected. All downstream call sites use the scrubbed text.

S79 caveat (inherited from azure-architect `_run_plan`): tool_result blocks
coming back from mock lookups within the 5-turn loop are NOT re-scrubbed
per turn. Per-turn protection of tool results is S85 (Tier-3 health) scope.
For finadvice the mocks contain PII fields (client_name, account_number,
tax_id, dob) deliberately — those land in tool_result content. The
demo-side redaction story focuses on the ENTRY scrub (operator prompt),
which is the load-bearing surface for the @scrub_pii event in the
chain-event protocol.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Optional

# Windows consoles default to cp1252 which can't encode characters Sonnet
# routinely emits (→, ✓, –, etc.). Force utf-8 so CLI output prints cleanly.
# Safe no-op on already-utf-8 terminals.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from dotenv import load_dotenv

import signallayer

# Absolute imports — finadvice is a real package (no hyphen in dir name),
# so the same import path works whether the module is dispatched by the
# Agent Runner (cwd=engine root) or invoked from the CLI (PYTHONPATH=.).
from agents.finadvice.prompts import (
    MODEL_DEFAULT,
    MODEL_DEEP,
    SYSTEM_PROMPT,
    TOKEN_BUDGETS,
    TOOL_SPECS,
    build_user_message,
)

# Locked S80 (mirrors azure-architect): 5-turn cap on the tool-use loop
# because cost compounds per turn and tool_use can pathologically loop on
# ambiguous tool errors. Bump deliberately, never silently.
TURN_CAP: int = 5

_MOCKS_DIR = Path(__file__).resolve().parent / "mocks"

# Load the agent's own .env if present. Same rationale as azure-architect:
# the agent's .env is the authoritative config home for this workload, not
# the inherited shell. override=True because shells sometimes export the
# var as empty (PowerShell `$env:ANTHROPIC_API_KEY=""` leaves it set-but-
# empty); without override the empty shell value wins over a real value
# in .env and _require_anthropic_key() rejects it.
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env", override=True)


# --- Mock data loaders -------------------------------------------------------
#
# Module-level cache so each JSON file is read once per process. Tests that
# need to override should monkeypatch the loader functions, not the cache
# (per [[provider-cache-singleton-test-pollution]] — mock at the lazy-
# import seam, not the cached value).


_MOCK_CACHE: dict[str, Any] = {}


def _load_mock(name: str) -> Any:
    """Load (and memoize) one mock JSON file by stem name."""
    if name not in _MOCK_CACHE:
        path = _MOCKS_DIR / f"{name}.json"
        with path.open("r", encoding="utf-8") as fh:
            _MOCK_CACHE[name] = json.load(fh)
    return _MOCK_CACHE[name]


# --- SDK init + key probe ----------------------------------------------------


def _init_sdk() -> None:
    """Initialise the SignalLayer client. Fails loudly on missing env.

    The Agent Runner endpoint normally pre-initialises the SDK at engine
    startup (via dashboard.py lifespan), but calling init twice is a
    cheap no-op and lets the CLI path work standalone too.
    """
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
            "agents/finadvice/.env (or your shell) before running."
        )
    return key


# --- Tool dispatch -----------------------------------------------------------
#
# Each tool returns a JSON-serialisable dict that Anthropic's tool_result
# protocol will accept. Unknown ids return an explicit `{"error": "..."}`
# payload so the model self-corrects on the next turn rather than the loop
# aborting on a KeyError.


def _tool_get_client_portfolio(tool_input: dict) -> dict[str, Any]:
    client_id = (tool_input or {}).get("client_id", "")
    portfolios = _load_mock("portfolios")
    client = portfolios.get("clients", {}).get(client_id)
    if not client:
        return {"error": f"Unknown client_id={client_id!r}.", "client_id": client_id}
    return {
        "as_of": portfolios.get("as_of"),
        "client_id": client_id,
        "client_name": client.get("client_name"),
        "account_number": client.get("account_number"),
        "tax_id": client.get("tax_id"),
        "dob": client.get("dob"),
        "positions": client.get("positions", []),
        "balances": client.get("balances", {}),
    }


def _tool_get_market_snapshot(tool_input: dict) -> dict[str, Any]:
    symbols = list((tool_input or {}).get("symbols") or [])
    if not symbols:
        return {"error": "symbols list is required and must be non-empty."}
    market = _load_mock("market")
    universe = market.get("symbols", {})
    return {
        "as_of": market.get("as_of"),
        "quotes": {sym: universe.get(sym) for sym in symbols},
    }


def _tool_get_client_risk_profile(tool_input: dict) -> dict[str, Any]:
    client_id = (tool_input or {}).get("client_id", "")
    profiles = _load_mock("profiles")
    profile = profiles.get("profiles", {}).get(client_id)
    if not profile:
        return {"error": f"Unknown client_id={client_id!r}.", "client_id": client_id}
    return {"client_id": client_id, **profile}


_TOOL_DISPATCH: dict[str, Any] = {
    "get_client_portfolio": _tool_get_client_portfolio,
    "get_market_snapshot": _tool_get_market_snapshot,
    "get_client_risk_profile": _tool_get_client_risk_profile,
}


# --- The governed agent ------------------------------------------------------
#
# Public API:
#   run_review(...)         — fully governed (policy_gate → scrub_pii → guardrails).
#                              Used by the CLI and any future direct caller that
#                              wants the decorator chain enforced inline.
#
#   _run_review_inner(...)  — same body, NO decorators. Used by
#                              domain.agent_runner.stream_agent_run_with_chain_events
#                              so the dispatcher can run policy / scrub / guard
#                              manually with per-step timing + emit chain events.
#                              Callers are responsible for performing those
#                              checks themselves before invoking.
#
# Both surfaces share one body. Decorators on run_review are applied at module
# bottom via signallayer.policy_gate(...)(signallayer.scrub_pii(...)(
# signallayer.guardrails()(_run_review_inner))). Calibration semantics are
# unchanged — the CLI path still hits all three decorators in canonical order.
#
# S80 chain-event protocol (LBD-1): _run_review_inner accepts an `event_sink`
# kwarg — a sync callable the dispatcher provides to receive llm.delta events
# during the streaming tool-use loop. When event_sink is None (the CLI path)
# the loop runs identically to pre-refactor.


async def _run_review_inner(
    prompt: str,
    *,
    model: str = MODEL_DEFAULT,
    vault_id: str = "",
    workload_id: str = os.environ.get("SL_WORKLOAD_ID", "finadvice"),
    event_sink: Optional[Callable[[dict[str, Any]], None]] = None,
) -> dict[str, Any]:
    """Drive one finadvice portfolio review end-to-end (undecorated inner).

    Callers must run policy_gate / scrub_pii / guardrails BEFORE invoking
    this function. The `run_review` decorated wrapper at the bottom of this
    module does this automatically for the CLI path. The dispatcher in
    domain/agent_runner.py does it manually with timing for chain events.

    By contract, `prompt` is the SCRUBBED text and `vault_id` is the
    scrubber's de-ID handle (or a synthetic fallback when SCRUBBER_ENABLED=
    false). Callers MUST honor this — passing raw operator text bypasses
    the security rule in project CLAUDE.md.

    Args:
        prompt: scrubbed operator text
        model: Anthropic model id (defaults to Sonnet 4.6)
        vault_id: scrubber's de-ID handle (or synthetic fallback)
        workload_id: governance workload identifier
        event_sink: optional sync callable invoked with `{"step": "llm.delta",
            "text": "..."}` for each streamed text chunk across all turns.
            When None the loop runs identically to the pre-S80 path.

    Returns:
        dict with keys: run_id, synthesis, turns, stop_reason, tool_calls,
        vault_id, episode_id, model, input_tokens, output_tokens, latency_ms.
    """
    from anthropic import Anthropic
    import storage  # engine module — requires project root on PYTHONPATH

    operator_request = prompt  # alias to keep "prompt" semantics explicit
    _init_sdk()
    anthropic = Anthropic(api_key=_require_anthropic_key())
    run_id = f"fin-{uuid.uuid4().hex[:12]}"

    # vault_id fallback mirrors azure-architect: when SCRUBBER_ENABLED=false
    # at the engine level, @scrub_pii is a no-op and vault_id is empty.
    # Synthesise one from the scrubbed-prompt hash so audit/episode rows
    # remain joinable on vault_id even in the noop case.
    if not vault_id:
        vault_id = (
            "finadvice_nopii_"
            + hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]
        )

    messages: list[dict[str, Any]] = [
        {"role": "user", "content": build_user_message(operator_request)},
    ]
    tool_call_summaries: list[dict[str, Any]] = []
    final_text = ""
    final_stop = ""
    turn = 0
    total_input_tokens = 0
    total_output_tokens = 0
    started_overall = time.monotonic()

    for turn in range(TURN_CAP):
        # Streaming context manager — required per CLAUDE.md "max_tokens > 2000
        # MUST stream" and [[anthropic-max-tokens-streaming-threshold]]. Non-
        # streaming at 4096 disconnects mid-response with APIConnectionError.
        # S80: if the caller provided event_sink, drain text_stream first to
        # emit per-chunk llm.delta events (drives the SPA chain ticker). Then
        # get_final_message() returns the assembled message — calling it after
        # text_stream is fully consumed is the documented Anthropic SDK pattern.
        # When event_sink is None we skip the iteration so the CLI path stays
        # byte-identical to the pre-S80 behavior.
        with anthropic.messages.stream(
            model=model,
            max_tokens=TOKEN_BUDGETS["plan_turn"],
            system=SYSTEM_PROMPT,
            tools=TOOL_SPECS,
            messages=messages,
        ) as stream:
            if event_sink is not None:
                for chunk in stream.text_stream:
                    if chunk:
                        try:
                            # Event shape MUST match domain.agent_runner's
                            # public chain-event protocol (LBD-1): the dispatcher
                            # forwards sink events verbatim, and SPA consumers
                            # discriminate on the `event` field. Sink and
                            # dispatcher share one protocol.
                            event_sink({"event": "llm.delta", "text": chunk, "turn": turn})
                        except Exception as exc:  # noqa: BLE001
                            # Sink failure must never break the agent — log + drop.
                            print(
                                f"[event_sink] llm.delta drop turn={turn}: "
                                f"{type(exc).__name__}: {exc}",
                                file=sys.stderr,
                            )
            msg = stream.get_final_message()

        total_input_tokens += int(getattr(msg.usage, "input_tokens", 0) or 0)
        total_output_tokens += int(getattr(msg.usage, "output_tokens", 0) or 0)

        turn_text = "".join(
            b.text for b in msg.content if getattr(b, "type", None) == "text"
        )
        tool_uses = [b for b in msg.content if getattr(b, "type", None) == "tool_use"]

        final_stop = msg.stop_reason or ""
        if msg.stop_reason != "tool_use":
            final_text = turn_text
            break

        # Append assistant turn verbatim so tool_use_id references resolve.
        messages.append({"role": "assistant", "content": msg.content})

        tool_results: list[dict[str, Any]] = []
        for tu in tool_uses:
            fn = _TOOL_DISPATCH.get(tu.name)
            if fn is None:
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "is_error": True,
                    "content": f"Tool '{tu.name}' is not implemented.",
                })
                tool_call_summaries.append({"tool": tu.name, "ok": False, "reason": "unimplemented"})
                continue
            try:
                # Tools are synchronous (in-memory dict lookups). Run inline.
                result = fn(tu.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": json.dumps(result, default=str),
                })
                tool_call_summaries.append({"tool": tu.name, "ok": True, "input": tu.input})
            except Exception as exc:  # noqa: BLE001
                # Never swallow per [[bare-except-hides-broken-integrations]].
                # Surface to the model so it can self-correct.
                err_msg = f"{type(exc).__name__}: {exc}"
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "is_error": True,
                    "content": err_msg,
                })
                tool_call_summaries.append({"tool": tu.name, "ok": False, "reason": err_msg})
                print(f"[finadvice turn={turn}] tool {tu.name} failed: {err_msg}", file=sys.stderr)

        messages.append({"role": "user", "content": tool_results})
    else:
        # Loop completed without break — hit the turn cap without synthesis.
        final_stop = "turn_cap_reached"
        final_text = "(no synthesis — agent hit the 5-turn cap)"

    latency_ms = int((time.monotonic() - started_overall) * 1000)

    # Outcome derivation mirrors azure-architect _run_plan: end_turn = success,
    # turn_cap_reached = failure, anything else (pause_turn / max_tokens / etc) =
    # review. write_episode persists the Tier-2 row via the SDK.
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
                "agent": "finadvice",
                "surface": "agent_runner",
                "run_id": run_id,
                "model": model,
                "turns": turn + 1,
                "stop_reason": final_stop,
                "tool_calls": tool_call_summaries,
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
                "latency_ms": latency_ms,
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
        "synthesis": final_text,
        "turns": turn + 1,
        "stop_reason": final_stop,
        "tool_calls": tool_call_summaries,
        "vault_id": vault_id,
        "episode_id": episode_id,
        "model": model,
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        "latency_ms": latency_ms,
    }


# --- Decorated public surface ------------------------------------------------
#
# Apply the governance chain externally so the CLI path enforces it inline
# while the dispatcher (domain/agent_runner.py) can call _run_review_inner
# directly with manual per-step timing for chain events.
#
# Decorator order is the canonical one declared in project CLAUDE.md and
# documented in agents/azure-architect/agent.py:124-131:
#   policy_gate (OUTERMOST) → scrub_pii → guardrails (INNERMOST) → body.
# functools.wraps inside each decorator preserves the inner signature, so
# `event_sink` remains a valid kwarg even though the CLI never passes it.

run_review = signallayer.policy_gate(action="llm_call")(
    signallayer.scrub_pii(scope="finadvice")(
        signallayer.guardrails()(
            _run_review_inner
        )
    )
)


# --- CLI calibration entry point ---------------------------------------------


def _usage() -> str:
    return (
        "finadvice — usage:\n"
        "  PYTHONPATH=. python agents/finadvice/agent.py --prompt \"<request>\"\n"
        "Optional:\n"
        "  --deep       Use Opus 4.7 instead of the default Sonnet 4.6.\n"
        "\n"
        "Example (calibration seed for cln-001):\n"
        "  --prompt \"Review portfolio for client cln-001 (Marcus Chen,\n"
        "    account AC-48201-7733, tax_id 412-58-9023, DOB 1978-03-14).\n"
        "    Identify the dominant risk and recommend 2-3 rebalancing actions.\"\n"
    )


def _arg_value(argv: list[str], flag: str) -> str | None:
    if flag not in argv:
        return None
    idx = argv.index(flag)
    if idx + 1 >= len(argv):
        raise SystemExit(f"{flag} requires a value")
    return argv[idx + 1]


def _print_result(result: dict[str, Any]) -> None:
    print("\n" + "=" * 72)
    print(
        f"FINADVICE RUN {result['run_id']}  turns={result['turns']}  "
        f"stop={result['stop_reason']}  tools={len(result['tool_calls'])}  "
        f"latency={result['latency_ms']}ms"
    )
    print("=" * 72 + "\n")
    print(result["synthesis"])
    print("\n" + "=" * 72)
    print(
        f"model={result['model']}  "
        f"in_tokens={result['input_tokens']}  out_tokens={result['output_tokens']}  "
        f"vault_id={result['vault_id'] or '(none)'}  "
        f"episode_id={result.get('episode_id') or '(none)'}"
    )
    print("=" * 72 + "\n")


if __name__ == "__main__":
    argv = sys.argv[1:]
    if not argv or "--help" in argv or "-h" in argv:
        print(_usage())
        raise SystemExit(0)

    request = _arg_value(argv, "--prompt")
    if not request or not request.strip():
        raise SystemExit("--prompt requires a non-empty request string.")

    model = MODEL_DEEP if "--deep" in argv else MODEL_DEFAULT
    result = asyncio.run(run_review(prompt=request, model=model))
    _print_result(result)
