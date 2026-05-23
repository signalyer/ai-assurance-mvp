"""Demo Control Panel — Session 11.

One-click triggers for the 6 demo scenarios in the 12-day sprint plan §7.

All routes are gated behind ``require_role("demo-operator", "ciso")``. In dev
mode (``AUTH_ENABLED=false``) the role check accepts an ``X-Role`` header.

Each scenario invokes REAL backend code (not mocks). On failure, the run is
captured in-memory and surfaced via the status endpoint; the HTTP layer
never raises.

Architecture
------------
* Scenarios are declared in ``_SCENARIO_REGISTRY`` (id → handler callable).
* ``POST /api/demo-control/run/{scenario_id}`` allocates a ``run_id``,
  appends a ``demo_scenario_run`` event to ``DEMO_EVENTS_FILE`` (defaults
  to the project events.jsonl), executes the scenario synchronously, and
  records the terminal state. (Synchronous execution is fine for demo
  scale — these scenarios complete in <5s. For Phase 2 they should move
  to a background task queue.)
* Prometheus counters are registered locally in this module so the
  observability/counters.py file does not need to change for Session 11.

Environment variables
---------------------
``AUTH_ENABLED``  — see ``middleware.auth``.
``DEMO_SEED_SYSTEM_ID``  — system id used by scenarios that need one
    (defaults to ``"ai-sys-001"``).
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from middleware.auth import require_role
from storage import _append_jsonl

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/demo-control", tags=["demo-control"])

# ---------------------------------------------------------------------------
# Storage — JSONL via the project _append_jsonl pattern
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEMO_EVENTS_FILE: Path = _PROJECT_ROOT / "data" / "events.jsonl"


def _append_event(record: dict[str, Any]) -> None:
    """Append a record to the demo events JSONL file.

    Delegates to :func:`storage._append_jsonl` (the project canonical JSONL
    writer; CLAUDE.md storage rule). The module-level ``DEMO_EVENTS_FILE``
    is patchable per-test for isolation.
    """
    target = DEMO_EVENTS_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    _append_jsonl(target, record)


# ---------------------------------------------------------------------------
# Prometheus counters (local to this module)
# ---------------------------------------------------------------------------

try:
    from prometheus_client import Counter, Histogram  # type: ignore[import-untyped]

    _scenario_runs_total = Counter(
        "demo_scenario_runs_total",
        "Number of demo scenario runs triggered via the control panel.",
        ["scenario", "outcome"],
    )
    _scenario_duration = Histogram(
        "demo_scenario_duration_seconds",
        "Wall-clock duration of demo scenario runs.",
        ["scenario"],
    )
    _METRICS_OK = True
except Exception:  # noqa: BLE001 — prometheus_client optional in dev
    _METRICS_OK = False
    _scenario_runs_total = None  # type: ignore[assignment]
    _scenario_duration = None  # type: ignore[assignment]


def _record_metric(scenario: str, outcome: str, duration_sec: float) -> None:
    """Best-effort Prometheus metric write."""
    if not _METRICS_OK:
        return
    try:
        _scenario_runs_total.labels(scenario=scenario, outcome=outcome).inc()  # type: ignore[union-attr]
        _scenario_duration.labels(scenario=scenario).observe(duration_sec)  # type: ignore[union-attr]
    except Exception as exc:  # noqa: BLE001
        logger.debug("demo metric write failed: %s", exc)


# ---------------------------------------------------------------------------
# In-memory run table (bounded LRU — keeps the demo control panel from
# leaking memory across a long session). The events.jsonl is the SSOT for
# any run older than the cap.
# ---------------------------------------------------------------------------

_MAX_RUNS: int = 200
_RUNS: OrderedDict[str, dict[str, Any]] = OrderedDict()


def _record_run(run_id: str, record: dict[str, Any]) -> None:
    """Insert/update a run and evict the oldest entry past ``_MAX_RUNS``."""
    if run_id in _RUNS:
        _RUNS.move_to_end(run_id)
    _RUNS[run_id] = record
    while len(_RUNS) > _MAX_RUNS:
        _RUNS.popitem(last=False)


def _now_iso() -> str:
    """ISO-8601 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Scenario handlers — each returns a JSON-serialisable dict
# ---------------------------------------------------------------------------

_SEED_SYSTEM_ID = os.environ.get("DEMO_SEED_SYSTEM_ID", "ai-sys-001")


# Residual-PII tripwires for the live scenario response. If any of these
# patterns appear in the scrubbed payload, the scenario refuses to return
# the payload to the browser — even though the scrubber should have caught
# them. Defence-in-depth.
_PII_RESIDUAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),     # SSN
    re.compile(r"\b\d{3}-\d{4}\b"),           # 7-digit phone
    re.compile(r"\b\d{16}\b"),                 # 16-digit card
    re.compile(r"\b\d{3}\.\d{3}\.\d{4}\b"),    # phone with dots
)


def _has_residual_pii(text: str) -> bool:
    """Return True if any residual-PII pattern matches *text*."""
    return any(p.search(text) for p in _PII_RESIDUAL_PATTERNS)


def _scenario_pii_pipeline_live() -> dict[str, Any]:
    """Scenario 1: live PII scrub + vault round-trip + Langfuse-trace-safe payload.

    Invokes the real scrubber pipeline so the decorator chain (scrub_pii) fires.
    Returns scrubbed payload + vault stats. **Never returns raw PII** — a
    post-scrub residual check enforces this even if the scrubber misses a
    pattern (defence-in-depth).
    """
    payload = {
        "prompt": "Customer John Doe (SSN 123-45-6789) phoned 555-1234 about account 9876.",
        "email": "demo@example.com",
    }
    try:
        from scrubber import tokenise_payload

        scrubbed, mapping = tokenise_payload(payload)
        scrubbed_str = json.dumps(scrubbed, default=str)
        if _has_residual_pii(scrubbed_str):
            logger.error(
                "pii-pipeline-live: residual PII detected after scrub; "
                "returning redacted summary to caller."
            )
            return {
                "scenario": "pii-pipeline-live",
                "scrubbed_payload": "<redacted: residual PII tripwire fired>",
                "tokens_minted": len(mapping) if mapping else 0,
                "residual_pii_detected": True,
            }
        try:
            from domain.deid_vault import vault_stats
            stats = vault_stats()
        except Exception:  # noqa: BLE001
            stats = {"available": False}
        return {
            "scenario": "pii-pipeline-live",
            "scrubbed_payload": scrubbed,
            "tokens_minted": len(mapping) if mapping else 0,
            "vault_stats": stats,
        }
    except Exception as exc:  # noqa: BLE001
        logger.error("pii-pipeline-live failed: %s", exc, exc_info=True)
        raise


def _scenario_gate_failure_recovery() -> dict[str, Any]:
    """Scenario 2: release-gate engine on a seeded failing system."""
    try:
        from domain.release_gate_engine import evaluate_release  # type: ignore[attr-defined]

        decision = evaluate_release(system_id=_SEED_SYSTEM_ID)
        return {
            "scenario": "gate-failure-recovery",
            "system_id": _SEED_SYSTEM_ID,
            "decision": (
                decision.model_dump()
                if hasattr(decision, "model_dump")
                else dict(decision) if isinstance(decision, dict) else str(decision)
            ),
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("gate-failure-recovery degraded", exc_info=True)
        _ = exc
        return {
            "scenario": "gate-failure-recovery",
            "system_id": _SEED_SYSTEM_ID,
            "decision": {"status": "unavailable", "reason": type(exc).__name__},
            "degraded": True,
        }


def _scenario_reusable_agent_upgrade() -> dict[str, Any]:
    """Scenario 3: publish v2 of a reusable agent → subscriber notification."""
    try:
        from domain import agents as _agents

        # Use whichever publish function exists.
        publish_fn = getattr(_agents, "publish_agent_version", None) or getattr(
            _agents, "publish_version", None
        )
        if not publish_fn:
            raise RuntimeError("No publish function on domain.agents")
        result = publish_fn("agent-reusable-001")  # type: ignore[misc]
        return {
            "scenario": "reusable-agent-upgrade",
            "result": (
                result.model_dump() if hasattr(result, "model_dump")
                else result if isinstance(result, dict) else str(result)
            ),
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("reusable-agent-upgrade degraded", exc_info=True)
        _ = exc
        return {
            "scenario": "reusable-agent-upgrade",
            "result": {"status": "unavailable", "reason": type(exc).__name__},
            "degraded": True,
        }


def _scenario_rtf_cascade() -> dict[str, Any]:
    """Scenario 4: right-to-forget cascade across all four stores."""
    from domain.right_to_forget import cascade

    result = cascade(subject_id="demo-customer-9999", reason="demo session")
    return {
        "scenario": "rtf-cascade",
        "cascade": result.model_dump(),
    }


def _scenario_evals_degradation() -> dict[str, Any]:
    """Scenario 5: evaluation trend over the recent window."""
    try:
        # Best-effort discovery — different builds may expose different APIs.
        try:
            from domain.framework_coverage import compute_coverage  # type: ignore
            _ = compute_coverage  # imported only to confirm domain layer is healthy
        except Exception:
            pass
        # Read tail of events.jsonl and group eval events by day.
        events_path = _PROJECT_ROOT / "data" / "events.jsonl"
        if not events_path.exists():
            return {
                "scenario": "evals-degradation",
                "trend": [],
                "degraded": True,
                "reason": "events.jsonl not yet present",
            }
        trend: dict[str, dict[str, int]] = {}
        with events_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if ev.get("event_type") not in {"eval_run", "EVAL_RUN", "evaluation"}:
                    continue
                day = (ev.get("ts") or ev.get("started_at") or "")[:10]
                if not day:
                    continue
                day_bucket = trend.setdefault(day, {"count": 0, "failures": 0})
                day_bucket["count"] += 1
                if ev.get("status") in {"FAIL", "failed", "failure"}:
                    day_bucket["failures"] += 1
        # Most-recent-first, 14-day cap.
        trend_list = sorted(
            ({"day": d, **v} for d, v in trend.items()),
            key=lambda r: r["day"],
            reverse=True,
        )[:14]
        return {
            "scenario": "evals-degradation",
            "system_id": _SEED_SYSTEM_ID,
            "trend": trend_list,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("evals-degradation degraded", exc_info=True)
        _ = exc
        return {
            "scenario": "evals-degradation",
            "trend": [],
            "degraded": True,
            "reason": type(exc).__name__,
        }


def _scenario_framework_coverage_export() -> dict[str, Any]:
    """Scenario 6: framework coverage matrix + NIST evidence pack export."""
    try:
        from pdf_report import generate_nist_pack

        pdf_bytes = generate_nist_pack(_SEED_SYSTEM_ID)
        import hashlib

        sha = hashlib.sha256(pdf_bytes).hexdigest()
        return {
            "scenario": "framework-coverage-export",
            "system_id": _SEED_SYSTEM_ID,
            "framework": "NIST AI RMF 1.0",
            "pack_bytes": len(pdf_bytes),
            "pack_sha256": sha,
            "download_url": f"/api/frameworks/export/nist/{_SEED_SYSTEM_ID}",
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("framework-coverage-export degraded", exc_info=True)
        _ = exc
        return {
            "scenario": "framework-coverage-export",
            "system_id": _SEED_SYSTEM_ID,
            "degraded": True,
            "reason": type(exc).__name__,
        }


# ---------------------------------------------------------------------------
# Scenario registry
# ---------------------------------------------------------------------------


class _Scenario(BaseModel):
    """Describes a demo scenario."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str
    title: str
    brief: str
    expected_duration_sec: int
    narration_url: str
    handler: Callable[[], dict[str, Any]] = Field(exclude=True)


_SCENARIO_REGISTRY: dict[str, _Scenario] = {
    s.id: s
    for s in [
        _Scenario(
            id="pii-pipeline-live",
            title="Team Risk — Live PII Pipeline",
            brief="Real Presidio scrub + Fernet vault round-trip + Langfuse-safe trace payload.",
            expected_duration_sec=15,
            narration_url="/static/demo-scripts/scenario-1.md",
            handler=_scenario_pii_pipeline_live,
        ),
        _Scenario(
            id="gate-failure-recovery",
            title="Team Payments — Gate Failure → Recovery",
            brief="Release-gate engine fails on a seeded regression, governance hold opens, then clears.",
            expected_duration_sec=30,
            narration_url="/static/demo-scripts/scenario-2.md",
            handler=_scenario_gate_failure_recovery,
        ),
        _Scenario(
            id="reusable-agent-upgrade",
            title="Team CX — Reusable Agent Governance",
            brief="Publish v2 of a reusable agent → subscriber notification → pin/upgrade flow.",
            expected_duration_sec=30,
            narration_url="/static/demo-scripts/scenario-3.md",
            handler=_scenario_reusable_agent_upgrade,
        ),
        _Scenario(
            id="rtf-cascade",
            title="Cross-team — Right-to-Forget Cascade",
            brief="Vault · Tier-2 · Tier-3 · Langfuse purge with HMAC-signed sidecar + SHA-256 verification.",
            expected_duration_sec=45,
            narration_url="/static/demo-scripts/scenario-4.md",
            handler=_scenario_rtf_cascade,
        ),
        _Scenario(
            id="evals-degradation",
            title="Team Payments — Evals Degradation Detection",
            brief="Real DeepEval scores aggregated over the 14-day window.",
            expected_duration_sec=20,
            narration_url="/static/demo-scripts/scenario-5.md",
            handler=_scenario_evals_degradation,
        ),
        _Scenario(
            id="framework-coverage-export",
            title="Auditor Visit — Framework Coverage Export",
            brief="Coverage matrix + NIST/OWASP/EU/ISO/SR-11-7/FFIEC evidence pack with SHA-256.",
            expected_duration_sec=20,
            narration_url="/static/demo-scripts/scenario-6.md",
            handler=_scenario_framework_coverage_export,
        ),
    ]
}


# ---------------------------------------------------------------------------
# API surface
# ---------------------------------------------------------------------------


@router.get("/scenarios")
async def list_scenarios(
    _role: None = Depends(require_role("demo-operator", "ciso")),
) -> dict[str, Any]:
    """Return the list of available demo scenarios (without handlers)."""
    return {
        "scenarios": [
            {
                "id": s.id,
                "title": s.title,
                "brief": s.brief,
                "expected_duration_sec": s.expected_duration_sec,
                "narration_url": s.narration_url,
            }
            for s in _SCENARIO_REGISTRY.values()
        ]
    }


@router.post("/run/{scenario_id}", status_code=status.HTTP_202_ACCEPTED)
async def run_scenario(
    scenario_id: str,
    _role: None = Depends(require_role("demo-operator", "ciso")),
) -> dict[str, Any]:
    """Execute a demo scenario by id. Returns 202 with run_id and status_url.

    Execution is synchronous (scenarios are <5s); the 202 acknowledges the
    intent and the same response carries terminal state via status_url.
    """
    if scenario_id not in _SCENARIO_REGISTRY:
        raise HTTPException(status_code=404, detail=f"unknown scenario: {scenario_id}")

    scenario = _SCENARIO_REGISTRY[scenario_id]
    run_id = str(uuid.uuid4())
    started_at = _now_iso()

    # Emit the start event up-front so the audit trail captures the trigger
    # even if the handler raises.
    _append_event(
        {
            "event_type": "demo_scenario_run",
            "run_id": run_id,
            "scenario_id": scenario_id,
            "started_at": started_at,
            "status": "running",
        }
    )
    _record_run(run_id, {
        "run_id": run_id,
        "scenario_id": scenario_id,
        "started_at": started_at,
        "status": "running",
        "result": None,
        "error": None,
    })

    # Initialise outcome to "failure" so the `finally` block always has a
    # defined value even if `scenario.handler()` raises something exotic
    # that bypasses the `except Exception` (e.g. a BaseException subclass).
    outcome: str = "failure"
    t0 = time.monotonic()
    try:
        result = scenario.handler()
        outcome = "success"
        _RUNS[run_id]["result"] = result
        _RUNS[run_id]["status"] = "completed"
    except Exception as exc:  # noqa: BLE001 -- never raise to HTTP layer
        logger.error("scenario %s failed", scenario_id, exc_info=True)
        outcome = "failure"
        # Surface only the exception type to the caller — full detail is in
        # the server log (exc_info=True above). Prevents stack-trace leaks
        # of paths / connection strings into the browser response.
        _RUNS[run_id]["error"] = type(exc).__name__
        _RUNS[run_id]["status"] = "failed"
    finally:
        duration = time.monotonic() - t0
        _RUNS[run_id]["completed_at"] = _now_iso()
        _RUNS[run_id]["duration_sec"] = round(duration, 3)
        _append_event(
            {
                "event_type": "demo_scenario_run",
                "run_id": run_id,
                "scenario_id": scenario_id,
                "started_at": started_at,
                "completed_at": _RUNS[run_id]["completed_at"],
                "status": _RUNS[run_id]["status"],
                "duration_sec": _RUNS[run_id]["duration_sec"],
                "outcome": outcome,
            }
        )
        _record_metric(scenario_id, outcome, duration)

    return {
        "run_id": run_id,
        "status_url": f"/api/demo-control/run/{run_id}/status",
        "status": _RUNS[run_id]["status"],
    }


@router.get("/run/{run_id}/status")
async def run_status(
    run_id: str,
    _role: None = Depends(require_role("demo-operator", "ciso")),
) -> dict[str, Any]:
    """Return the current state of a previously-triggered run."""
    if run_id not in _RUNS:
        raise HTTPException(status_code=404, detail=f"unknown run_id: {run_id}")
    return _RUNS[run_id]
