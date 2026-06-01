"""S82f-1c STAGED calibration harness — drive 18 vendor_risk runs live.

Reads the 10 EXT + 8 INT fixtures, invokes the STAGED engine's
`POST /api/agent-runner/run` SSE endpoint sequentially, captures the full
event stream per run, and appends a row to
`docs/sop-vendor-risk/07-staged-calibration-log.md`.

Local-package + cookie auth: the SDK package (`signallayer`) is imported
for parity with the call-origin decision (Local SDK), but the operator
runner endpoint uses session-cookie auth, not HMAC. Set the auth cookie
via env var (see below) — the harness does not store credentials.

ENV required:
    AIGOVERN_BASE_URL    e.g. https://aigovern.sandboxhub.co
    AIGOVERN_COOKIE      raw value of the signed session cookie (full
                         "name=value" pair) for a CISO/operator session

ENV optional:
    CALIBRATION_LOG      path to the calibration log markdown
                         (default: docs/sop-vendor-risk/07-staged-calibration-log.md)
    DRY_RUN              "1" to skip POSTs and just print the plan
    PER_RUN_TIMEOUT_S    SSE stream timeout per run (default 180)

Per [[run-commands-dont-defer]] this script EXECUTES the runs; per
[[show-handoff-prompt-inline]] it ALSO writes a JSONL transcript next to
the log so the operator can re-inspect locally without re-querying.

Usage:
    python -m agents.vendor_risk.eval.run_calibration            # all 18
    python -m agents.vendor_risk.eval.run_calibration --only ext # 10 EXT
    python -m agents.vendor_risk.eval.run_calibration --only int # 8 INT
    python -m agents.vendor_risk.eval.run_calibration --case ext-05-edge-carveout-eu
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

# Imported for SDK-package parity (calibration call-origin decision is
# "Local SDK package"). The runner endpoint is cookie-authed, not HMAC,
# so the SDK client isn't directly used to drive the chain — but the
# import ensures the public surface is loadable from this harness path
# (mirrors [[sdk-tests-use-public-import-path]] discipline).
import signallayer  # noqa: F401

EVAL_DIR = Path(__file__).parent
EXT_DATASET = EVAL_DIR / "dataset-external.jsonl"
INT_DATASET = EVAL_DIR / "dataset-internal.jsonl"
DEFAULT_LOG = Path("docs/sop-vendor-risk/07-staged-calibration-log.md")
TRANSCRIPT = EVAL_DIR / "calibration-transcript-s82f-1c.jsonl"


def _load_dataset(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _build_prompt(case: dict[str, Any]) -> str:
    """Render a fixture into the operator prompt the agent expects.

    The fixture's `input_vendor_package_ref` points at a relative path on
    disk that the agent's tools resolve. We pass it through verbatim plus
    the label as context — the agent's prompts module is the source of
    truth for what it needs.
    """
    return (
        f"Assess vendor risk for fixture {case['id']}.\n"
        f"Label: {case['label']}\n"
        f"Vendor package: {case['input_vendor_package_ref']}\n"
        f"Category: {case['category']}\n"
        "Return tier, concerns, citations, and any mitigations."
    )


def _stream_run(
    *,
    client: httpx.Client,
    base_url: str,
    cookie: str,
    agent_id: str,
    system_id: str,
    prompt: str,
    timeout_s: float,
) -> list[dict[str, Any]]:
    """POST /api/agent-runner/run and return the full event list.

    Streams SSE and accumulates each event dict (decoded from the `data:`
    line JSON) until `chain.done` arrives.
    """
    url = f"{base_url.rstrip('/')}/api/agent-runner/run"
    headers = {
        "Accept": "text/event-stream",
        "Content-Type": "application/json",
    }
    body = {"agent_id": agent_id, "prompt": prompt, "system_id": system_id}
    events: list[dict[str, Any]] = []
    with client.stream("POST", url, headers=headers, json=body, timeout=timeout_s) as resp:
        resp.raise_for_status()
        current_event: dict[str, str] = {}
        for raw in resp.iter_lines():
            if raw is None:
                continue
            line = raw.strip()
            if not line:
                if "data" in current_event:
                    try:
                        events.append(json.loads(current_event["data"]))
                    except json.JSONDecodeError:
                        pass
                    if events and events[-1].get("event") == "chain.done":
                        return events
                current_event = {}
                continue
            if line.startswith("event:"):
                current_event["event"] = line[6:].strip()
            elif line.startswith("data:"):
                current_event["data"] = line[5:].strip()
    return events


def _extract_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Pull the calibration-row fields out of a chain.* event list."""
    def _find(name: str) -> dict[str, Any]:
        return next((e for e in events if e.get("event") == name), {})

    start = _find("chain.start")
    done = _find("chain.done")
    audit = _find("audit")
    # The agent streams its structured JSON response as llm.delta text chunks;
    # no event carries risk_tier as a parsed field. Concatenate the deltas and
    # regex it out. Resilient to partial / malformed JSON (still gets the tier
    # if the field is present anywhere in the response).
    import re
    body = "".join(e.get("text", "") for e in events if e.get("event") == "llm.delta")
    m = re.search(r'"risk_tier"\s*:\s*"([A-Z]+)"', body)
    actual_tier = m.group(1) if m else ""
    return {
        "run_id": start.get("run_id") or done.get("run_id", ""),
        "system_id": start.get("system_id", ""),
        "actual_tier": str(actual_tier).upper() if actual_tier else "",
        "latency_ms": done.get("total_elapsed_ms", 0),
        "operation_id": audit.get("operation_id", ""),
        "audit_id": audit.get("audit_id", ""),
        "outcome": done.get("outcome", ""),
    }


def _update_log_row(log_path: Path, fixture_id: str, summary: dict[str, Any], expected_tier: str, notes: str) -> None:
    """Find the `_pending_` row for fixture_id and replace it inline."""
    text = log_path.read_text(encoding="utf-8")
    tier_match = "Y" if summary["actual_tier"] == expected_tier else "N"
    # Locate the row by fixture id; replace whole row.
    out_lines: list[str] = []
    replaced = False
    for line in text.splitlines():
        if (
            line.startswith("|")
            and fixture_id in line
            and "_pending_" in line
        ):
            # Reconstruct row preserving the leading `| # |` index column.
            idx = line.split("|", 2)[1].strip()
            out_lines.append(
                f"| {idx} | {summary['run_id']} | {summary['system_id']} | "
                f"{fixture_id} | {expected_tier} | {summary['actual_tier']} | "
                f"{tier_match} | {summary['latency_ms']} | "
                f"{summary['operation_id']} | {summary['audit_id']} | {notes} |"
            )
            replaced = True
        else:
            out_lines.append(line)
    if not replaced:
        print(f"  WARN: no pending row matched fixture_id={fixture_id}; skipping log update.")
    log_path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")


def _append_transcript(record: dict[str, Any]) -> None:
    with TRANSCRIPT.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, default=str) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=["ext", "int"], help="Run only one dataset")
    parser.add_argument("--case", help="Run a single fixture by id")
    parser.add_argument("--log", default=str(DEFAULT_LOG), help="Calibration log path")
    parser.add_argument("--skip-completed", action="store_true",
                        help="Skip fixtures whose row in the log is no longer _pending_")
    args = parser.parse_args()

    base_url = os.environ.get("AIGOVERN_BASE_URL")
    cookie = os.environ.get("AIGOVERN_COOKIE")
    dry_run = os.environ.get("DRY_RUN") == "1"
    timeout_s = float(os.environ.get("PER_RUN_TIMEOUT_S", "180"))
    if not dry_run and (not base_url or not cookie):
        print("ERROR: AIGOVERN_BASE_URL and AIGOVERN_COOKIE must be set "
              "(or pass DRY_RUN=1).", file=sys.stderr)
        return 2

    log_path = Path(args.log)
    if not log_path.exists():
        print(f"ERROR: calibration log not found at {log_path}", file=sys.stderr)
        return 2

    cases: list[tuple[dict[str, Any], str]] = []
    if args.only != "int":
        cases.extend((c, "sys-vendor-risk-ext-001") for c in _load_dataset(EXT_DATASET))
    if args.only != "ext":
        cases.extend((c, "sys-vendor-risk-int-001") for c in _load_dataset(INT_DATASET))
    if args.case:
        cases = [(c, s) for c, s in cases if c["id"] == args.case]
        if not cases:
            print(f"ERROR: no case matching id={args.case}", file=sys.stderr)
            return 2

    if args.skip_completed:
        log_text = log_path.read_text(encoding="utf-8")
        before = len(cases)
        cases = [(c, s) for c, s in cases
                 if any(c["id"] in line and "_pending_" in line
                        for line in log_text.splitlines())]
        print(f"  skip-completed: {before - len(cases)} fixtures already done; "
              f"{len(cases)} remaining")

    print(f"[{datetime.now(tz=timezone.utc).isoformat()}] calibration start "
          f"cases={len(cases)} base_url={base_url} dry_run={dry_run}")

    # Seed the cookie jar from AIGOVERN_COOKIE so sliding-TTL refresh
    # (Set-Cookie on every response) is honored across the run. The env value
    # may be either a bare token or a "name=value" pair.
    jar: dict[str, str] = {}
    if cookie:
        if "=" in cookie:
            name, _, value = cookie.partition("=")
            jar[name.strip()] = value.strip()
        else:
            jar["aigovern_session"] = cookie.strip()

    failures: list[str] = []
    with httpx.Client(cookies=jar) as client:
        for case, system_id in cases:
            fid = case["id"]
            expected = case["expected_risk_tier"]
            print(f"  -> {fid} (expect {expected})")
            if dry_run:
                continue
            t0 = time.monotonic()
            try:
                events = _stream_run(
                    client=client,
                    base_url=base_url,
                    cookie=cookie,
                    agent_id="vendor_risk",
                    system_id=system_id,
                    prompt=_build_prompt(case),
                    timeout_s=timeout_s,
                )
            except Exception as exc:  # noqa: BLE001
                elapsed = (time.monotonic() - t0) * 1000
                failures.append(f"{fid}: {type(exc).__name__}: {exc}")
                print(f"     FAIL ({elapsed:.0f}ms): {exc}")
                _append_transcript({"fixture_id": fid, "error": str(exc)})
                continue
            summary = _extract_summary(events)
            notes = "" if summary["actual_tier"] == expected else "tier_mismatch"
            if summary["outcome"] not in ("success", "review"):
                notes = (notes + ";" if notes else "") + f"outcome={summary['outcome']}"
            _update_log_row(log_path, fid, summary, expected, notes)
            _append_transcript({"fixture_id": fid, "expected_tier": expected,
                                "summary": summary, "events": events})
            print(f"     done run_id={summary['run_id']} tier={summary['actual_tier']} "
                  f"latency_ms={summary['latency_ms']}")

    print(f"[{datetime.now(tz=timezone.utc).isoformat()}] calibration end "
          f"failures={len(failures)}")
    for f in failures:
        print(f"  ! {f}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
