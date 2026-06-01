"""vendor_risk — Third-Party Vendor Risk Analyzer agent (S82d V0).

Three entry points share one body:
  - _run_vendor_risk_inner(case)              eval seam (sync). Used by
                                              `agents.vendor_risk.eval.run_eval`.
                                              Bypasses the SignalLayer
                                              decorator chain so the eval can
                                              run offline against the agent's
                                              reasoning capability without
                                              requiring SL_* env to be set.
  - _run_review_inner(prompt, **kw)           runner seam (async). Caller is
                                              the SPA dispatcher in
                                              `domain.agent_runner`. By
                                              contract `prompt` is the
                                              SCRUBBED text; the dispatcher
                                              runs policy/scrub/guard manually
                                              with per-step timing.
  - run_vendor_risk(prompt, **kw)             decorated public surface for the
                                              CLI path. Runs the full canonical
                                              decorator chain:
                                                @policy_gate → @scrub_pii →
                                                @guardrails → body.

All three converge on `_execute_run(...)` which owns the streaming tool-use
loop. Streaming is REQUIRED (max_tokens 4096 > 2000) per CLAUDE.md and
[[anthropic-max-tokens-streaming-threshold]].

Canonical security rule (project CLAUDE.md): scrubber.tokenise_payload()
runs BEFORE tracer.trace_call(). The CLI surface enforces this via the
decorator chain; the runner dispatcher enforces it manually; the eval
seam runs raw text because eval inputs are deterministic synthetic
fixtures (no real PII to scrub).

S80 chain-event protocol (LBD-1): `_run_review_inner` accepts an
`event_sink` kwarg the dispatcher provides to receive `llm.delta`
events during streaming. When event_sink is None (eval / CLI) the loop
runs identically to the pre-S80 path.
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

# Force utf-8 stdout — mirrors finadvice/azure-architect (Windows cp1252
# can't encode Sonnet's typical output characters).
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from dotenv import load_dotenv

import signallayer

from agents.vendor_risk.prompts import (
    MODEL_DEFAULT,
    MODEL_DEEP,
    SYSTEM_ID_EXT,
    SYSTEM_ID_INT,
    SYSTEM_PROMPT_EXT,
    SYSTEM_PROMPT_INT,
    TOKEN_BUDGETS,
    TOOL_SPECS,
    build_user_message,
)
from agents.vendor_risk.tools import (
    check_regulatory_requirements,
    compare_to_baseline,
    escalate_to_human,
    load_fixture_meta,
    lookup_subprocessor_risk,
    parse_vendor_document,
    search_tprm_corpus,
)

# Mirrors finadvice / azure-architect: hard 5-turn cap on the tool-use loop.
# Cost compounds per turn and tool_use can pathologically loop on ambiguous
# tool errors. Bump deliberately, never silently.
TURN_CAP: int = 6

# Load the agent's own .env if present. ANTHROPIC_API_KEY is the only
# required var for the eval seam; SL_* are required for the decorated
# surfaces. override=True so a shell-exported empty string never wins
# over a real value in .env (PowerShell exports empty strings; see
# azure-architect's load_dotenv comment).
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env", override=True)


# --- Network-egress assertion (defense-in-depth for the INT system) ---------
#
# The INT vendor_risk system (sys-vendor-risk-int-001) is contractually
# "internal-only — no network egress" (see intake_payload_int.json). This
# context manager is the runtime tripwire: any outbound socket.connect() to
# a non-loopback address raises PermissionError. It is NOT a sandbox — a
# determined caller can monkey-patch around it — but it catches accidental
# egress (a tool importing `requests`, a misconfigured provider, a test
# fixture pulling from S3) the way assert statements catch logic bugs.
#
# Threading caveat: this patches `socket.socket.connect` at the class level,
# which means CONCURRENT runs across different event-loop tasks will share
# the patched state. Safe for the current dispatcher (one chain at a time
# per FastAPI request worker); unsafe if the runner ever fans out parallel
# chains. Move to threading.local or a per-loop wrapper before that change.
#
# S82f-1 lands the primitive only. Wiring it into the INT execution path
# (which today still calls Anthropic — a contradiction with "no egress")
# is S82f-2 work alongside the local-provider swap. See
# docs/sop-vendor-risk/00-intent.md.
import contextlib
import socket as _socket_mod
from typing import Iterator

_LOOPBACK_HOSTS: frozenset[str] = frozenset({
    "127.0.0.1", "localhost", "::1", "0.0.0.0",
})


def _is_loopback(address: Any) -> bool:
    """Best-effort loopback check on a socket address tuple."""
    if not isinstance(address, tuple) or not address:
        return False
    host = address[0]
    if not isinstance(host, str):
        return False
    if host in _LOOPBACK_HOSTS:
        return True
    # IPv4 loopback range 127.0.0.0/8
    if host.startswith("127."):
        return True
    return False


@contextlib.contextmanager
def assert_no_egress() -> Iterator[list[str]]:
    """Block non-loopback socket.connect() calls for the duration of the block.

    Yields a list that accumulates blocked address strings — empty on a
    clean run. Raises PermissionError immediately on the first attempted
    egress so the offending call site surfaces in the stack trace.

    Usage::

        with assert_no_egress() as blocked:
            run_internal_only_inference(...)
        assert not blocked  # belt-and-suspenders; the raise already fired
    """
    original_connect = _socket_mod.socket.connect
    blocked: list[str] = []

    def _guarded_connect(self: _socket_mod.socket, address: Any, *a: Any, **kw: Any) -> Any:
        if _is_loopback(address):
            return original_connect(self, address, *a, **kw)
        blocked.append(repr(address))
        raise PermissionError(
            f"vendor_risk INT: outbound network egress blocked to {address!r}. "
            "The internal-only system contract forbids non-loopback connections; "
            "see agents/vendor_risk/agent.py::assert_no_egress."
        )

    _socket_mod.socket.connect = _guarded_connect  # type: ignore[method-assign]
    try:
        yield blocked
    finally:
        _socket_mod.socket.connect = original_connect  # type: ignore[method-assign]


def _init_sdk() -> None:
    """Initialise SignalLayer SDK. Used by decorated surfaces only."""
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
            "agents/vendor_risk/.env (or your shell) before running."
        )
    return key


# --- Output parsing ----------------------------------------------------------


def _coerce_output(
    final_text: str,
    *,
    system_id: str,
    retrieved_doc_ids: list[str],
    state: dict[str, Any],
) -> dict[str, Any]:
    """Parse the agent's final-turn synthesis into the eval-contract dict.

    The synthesis is required to be JSON matching the schema in
    `prompts.OUTPUT_SCHEMA_DOCSTRING`. When parsing fails we degrade to
    a `risk_tier=MEDIUM` fallback with a parse-failure concern — never
    fabricate. The eval will (correctly) penalise this.

    `state` is the mutable per-run dict tracked across tool calls; we
    consult it for `escalation_triggered`.
    """
    raw = final_text.strip()
    # Tolerate code-fence wrappers ```json ... ``` that Sonnet occasionally
    # emits despite the schema instruction.
    if raw.startswith("```"):
        raw = raw.strip("`")
        if "\n" in raw:
            head, _, body = raw.partition("\n")
            if head.strip().lower() in {"json", "json5"}:
                raw = body
    parsed: dict[str, Any] | None = None
    parse_exc: Exception | None = None
    # First attempt: parse raw as-is.
    try:
        candidate = json.loads(raw)
        if isinstance(candidate, dict):
            parsed = candidate
    except (ValueError, json.JSONDecodeError) as exc:
        parse_exc = exc
    # Second attempt: extract the first balanced {...} object from the text.
    # Defends against preamble like "Based on my analysis:\n{...}" — a common
    # Sonnet failure mode that otherwise drops every run to MEDIUM fallback.
    if parsed is None:
        start = raw.find("{")
        if start != -1:
            depth = 0
            in_str = False
            esc = False
            end = -1
            for i in range(start, len(raw)):
                ch = raw[i]
                if in_str:
                    if esc:
                        esc = False
                    elif ch == "\\":
                        esc = True
                    elif ch == '"':
                        in_str = False
                else:
                    if ch == '"':
                        in_str = True
                    elif ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth == 0:
                            end = i
                            break
            if end != -1:
                try:
                    candidate = json.loads(raw[start:end + 1])
                    if isinstance(candidate, dict):
                        parsed = candidate
                except (ValueError, json.JSONDecodeError) as exc:
                    parse_exc = exc
    if parsed is None:
        exc = parse_exc or ValueError("no JSON object found")
        parsed = {
            "risk_tier": "MEDIUM",
            "concerns": [f"Synthesis JSON parse failed: {type(exc).__name__}"],
            "conflicts": [],
            "citations": [],
            "mitigations": [],
            "contract_clauses": [],
            "summary": "Synthesis did not produce valid JSON; degraded to MEDIUM fallback.",
        }
    # Eval-contract keys + state-derived fields.
    return {
        "system_id": system_id,
        "risk_tier": str(parsed.get("risk_tier", "MEDIUM")).upper(),
        "concerns": list(parsed.get("concerns") or []),
        "conflicts": list(parsed.get("conflicts") or []),
        "citations": list(parsed.get("citations") or []),
        "retrieved_doc_ids": list(dict.fromkeys(retrieved_doc_ids)),
        "escalation_triggered": bool(state.get("escalation_triggered", False)),
        "summary": str(parsed.get("summary", "")),
        "mitigations": list(parsed.get("mitigations") or []),
        "contract_clauses": list(parsed.get("contract_clauses") or []),
        "eval_scores": {},  # populated by run_eval against this output; empty in-band.
    }


# --- Tool dispatch builder ---------------------------------------------------


def _build_dispatch(
    fixture_meta: dict[str, Any] | None,
    *,
    state: dict[str, Any],
    retrieved_doc_ids: list[str],
) -> dict[str, Callable[[dict[str, Any]], dict[str, Any]]]:
    """Return a name → callable map closed over fixture + state.

    Closure captures so each tool sees the right per-run context without
    threading kwargs through Anthropic's tool_use protocol.
    """

    def _search(tool_input: dict[str, Any]) -> dict[str, Any]:
        result = search_tprm_corpus(tool_input)
        for r in result.get("results", []):
            retrieved_doc_ids.append(r["doc_id"])
        return result

    def _parse(tool_input: dict[str, Any]) -> dict[str, Any]:
        return parse_vendor_document(tool_input, fixture_meta=fixture_meta)

    def _escalate(tool_input: dict[str, Any]) -> dict[str, Any]:
        return escalate_to_human(tool_input, state=state)

    def _compare(tool_input: dict[str, Any]) -> dict[str, Any]:
        result = compare_to_baseline(tool_input)
        if "doc_id" in result:
            retrieved_doc_ids.append(result["doc_id"])
        return result

    def _check_reg(tool_input: dict[str, Any]) -> dict[str, Any]:
        result = check_regulatory_requirements(tool_input)
        if "doc_id" in result:
            retrieved_doc_ids.append(result["doc_id"])
        return result

    return {
        "search_tprm_corpus": _search,
        "lookup_subprocessor_risk": lookup_subprocessor_risk,
        "parse_vendor_document": _parse,
        "check_regulatory_requirements": _check_reg,
        "compare_to_baseline": _compare,
        "escalate_to_human": _escalate,
    }


# --- Core execution ----------------------------------------------------------


async def _execute_run(
    *,
    prompt: str,
    fixture_meta: dict[str, Any] | None,
    system_id: str,
    model: str,
    vault_id: str,
    workload_id: str,
    event_sink: Optional[Callable[[dict[str, Any]], None]] = None,
) -> dict[str, Any]:
    """Drive the streaming tool-use loop end-to-end.

    Returns the eval-contract dict (system_id, risk_tier, concerns, ...).
    """
    from anthropic import Anthropic

    anthropic = Anthropic(api_key=_require_anthropic_key())
    run_id = f"vrun-{uuid.uuid4().hex[:12]}"

    system_prompt = (
        SYSTEM_PROMPT_INT if system_id == SYSTEM_ID_INT else SYSTEM_PROMPT_EXT
    )

    state: dict[str, Any] = {"escalation_triggered": False}
    retrieved_doc_ids: list[str] = []
    dispatch = _build_dispatch(
        fixture_meta, state=state, retrieved_doc_ids=retrieved_doc_ids
    )

    messages: list[dict[str, Any]] = [
        {"role": "user", "content": prompt},
    ]
    tool_call_summaries: list[dict[str, Any]] = []
    final_text = ""
    final_stop = ""
    turn = 0
    total_input_tokens = 0
    total_output_tokens = 0
    started = time.monotonic()

    for turn in range(TURN_CAP):
        with anthropic.messages.stream(
            model=model,
            max_tokens=TOKEN_BUDGETS["plan_turn"],
            system=system_prompt,
            tools=TOOL_SPECS,
            messages=messages,
        ) as stream:
            if event_sink is not None:
                for chunk in stream.text_stream:
                    if chunk:
                        try:
                            event_sink({"event": "llm.delta", "text": chunk, "turn": turn})
                        except Exception as exc:  # noqa: BLE001
                            print(
                                f"[event_sink] drop turn={turn}: {type(exc).__name__}: {exc}",
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

        messages.append({"role": "assistant", "content": msg.content})

        tool_results: list[dict[str, Any]] = []
        for tu in tool_uses:
            fn = dispatch.get(tu.name)
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
                result = fn(tu.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": json.dumps(result, default=str),
                })
                tool_call_summaries.append({"tool": tu.name, "ok": True})
            except Exception as exc:  # noqa: BLE001
                err_msg = f"{type(exc).__name__}: {exc}"
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "is_error": True,
                    "content": err_msg,
                })
                tool_call_summaries.append({"tool": tu.name, "ok": False, "reason": err_msg})
                print(f"[vendor_risk turn={turn}] tool {tu.name} failed: {err_msg}", file=sys.stderr)

        messages.append({"role": "user", "content": tool_results})
    else:
        # Loop completed without break — hit the turn cap.
        final_stop = "turn_cap_reached"
        final_text = json.dumps({
            "risk_tier": "MEDIUM",
            "concerns": ["Agent hit 5-turn cap without producing a synthesis."],
            "conflicts": [],
            "citations": [],
            "mitigations": [],
            "contract_clauses": [],
            "summary": "Turn cap reached; degraded output.",
        })

    latency_ms = int((time.monotonic() - started) * 1000)

    output = _coerce_output(
        final_text,
        system_id=system_id,
        retrieved_doc_ids=retrieved_doc_ids,
        state=state,
    )
    output["_meta"] = {
        "run_id": run_id,
        "turns": turn + 1,
        "stop_reason": final_stop,
        "tool_calls": tool_call_summaries,
        "vault_id": vault_id,
        "model": model,
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        "latency_ms": latency_ms,
    }
    return output


# --- Eval seam (sync) --------------------------------------------------------


def _run_vendor_risk_inner(case: dict[str, Any]) -> dict[str, Any]:
    """Eval-runner contract: take a dataset case row, return the structured output.

    Synchronous wrapper because `agents.vendor_risk.eval.run_eval` is sync.
    Internally drives the async loop via asyncio.run. Does NOT initialise
    SignalLayer — eval inputs are deterministic synthetic fixtures with
    no real PII to scrub, and the eval is measuring the inner reasoning
    capability (the governance perimeter is tested separately by S82b's
    rego tests and S82f's staged run).
    """
    fixture_ref = case.get("input_vendor_package_ref", "")
    try:
        fixture_meta = load_fixture_meta(fixture_ref)
    except FileNotFoundError as exc:
        return {
            "system_id": case.get("expected_routing", SYSTEM_ID_EXT),
            "risk_tier": "MEDIUM",
            "concerns": [f"Fixture not found: {exc}"],
            "conflicts": [],
            "citations": [],
            "retrieved_doc_ids": [],
            "escalation_triggered": False,
            "summary": "Fixture meta missing; agent cannot run.",
            "mitigations": [],
            "contract_clauses": [],
            "eval_scores": {},
        }

    system_id = case.get("expected_routing", SYSTEM_ID_EXT)
    prompt = build_user_message(
        operator_request=(
            f"Assess vendor '{fixture_meta.get('vendor_name', '(unknown)')}' "
            f"for {case.get('label', '')}."
        ),
        vendor_package_ref=fixture_ref,
        system_id=system_id,
    )
    vault_id = (
        "vendor_risk_eval_" + hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]
    )
    return asyncio.run(_execute_run(
        prompt=prompt,
        fixture_meta=fixture_meta,
        system_id=system_id,
        model=MODEL_DEFAULT,
        vault_id=vault_id,
        workload_id=os.environ.get("SL_WORKLOAD_ID", "vendor_risk"),
        event_sink=None,
    ))


# --- Runner seam (async, undecorated inner) ---------------------------------


async def _run_review_inner(
    prompt: str,
    *,
    model: str = MODEL_DEFAULT,
    vault_id: str = "",
    workload_id: str = os.environ.get("SL_WORKLOAD_ID", "vendor_risk"),
    event_sink: Optional[Callable[[dict[str, Any]], None]] = None,
    system_id: str = SYSTEM_ID_EXT,
    vendor_package_ref: str = "",
) -> dict[str, Any]:
    """Runner-dispatchable inner (undecorated).

    Callers (the SPA dispatcher in domain.agent_runner) MUST have run
    policy_gate / scrub_pii / guardrails BEFORE invoking. By contract
    `prompt` is the SCRUBBED text and `vault_id` is the scrubber's
    de-ID handle (or a synthetic fallback when SCRUBBER_ENABLED=false).
    """
    if not vault_id:
        vault_id = (
            "vendor_risk_nopii_"
            + hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]
        )
    fixture_meta: dict[str, Any] | None = None
    if vendor_package_ref:
        try:
            fixture_meta = load_fixture_meta(vendor_package_ref)
        except FileNotFoundError:
            fixture_meta = None
    return await _execute_run(
        prompt=prompt,
        fixture_meta=fixture_meta,
        system_id=system_id,
        model=model,
        vault_id=vault_id,
        workload_id=workload_id,
        event_sink=event_sink,
    )


# --- Decorated public surface ------------------------------------------------
#
# Canonical decorator order (project CLAUDE.md):
#   policy_gate (OUTERMOST) → scrub_pii → guardrails (INNERMOST) → body
# Applied externally so the CLI path enforces it inline while the runner
# dispatcher (domain.agent_runner) calls _run_review_inner directly with
# manual per-step timing for chain events.


run_vendor_risk = signallayer.policy_gate(action="llm_call")(
    signallayer.scrub_pii(scope="vendor_risk")(
        signallayer.guardrails()(
            _run_review_inner
        )
    )
)
