"""Eval results API + Simulated Eval Suite trigger.

These endpoints serve the refactored Evals page. They expose the rich
EvalResult objects (with framework/control mappings + sample failures)
and provide a "Run Simulated Eval Suite" action that re-times the
eval results and re-runs the assessment engine.
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path

from fastapi import APIRouter, HTTPException

from domain import seed
from domain.repository import get_ai_system, list_ai_systems
from domain.assessment_engine import run_assessment
from domain.release_gate_engine import evaluate_gates


router = APIRouter(prefix="/api/grc/evals/v2", tags=["evals-v2"])


def _ser(o):
    if is_dataclass(o):
        return {k: _ser(v) for k, v in asdict(o).items()}
    if isinstance(o, Enum):
        return o.value
    if isinstance(o, datetime):
        return o.isoformat()
    if isinstance(o, (list, tuple)):
        return [_ser(v) for v in o]
    if isinstance(o, dict):
        return {k: _ser(v) for k, v in o.items()}
    return o


def _eval_to_dict(e) -> dict:
    """Serialize an EvalResult Pydantic model into the wire shape."""
    d = e.model_dump(mode="json")
    # Surface a coverage% for the UI
    if d.get("test_count"):
        passed = d["test_count"] - (d.get("failed_count") or 0)
        d["pass_rate"] = round(passed / d["test_count"], 4)
    return d


@router.get("/system/{ai_system_id}")
async def system_evals(ai_system_id: str) -> dict:
    """All eval results for one system, with the assessment context."""
    system = get_ai_system(ai_system_id)
    if not system:
        raise HTTPException(status_code=404, detail="System not found")

    evals = [e for e in seed.EVAL_RESULTS if e.ai_system_id == ai_system_id]
    # Sort: FAIL first, then WARN, then PASS, alphabetically within each band
    order = {"FAIL": 0, "WARN": 1, "PASS": 2, "NOT_RUN": 3}
    evals.sort(key=lambda e: (order.get(e.status.value, 9), e.eval_type.value))

    return {
        "ai_system": {
            "id": system.id,
            "name": system.name,
            "domain": system.domain,
            "runtime_status": system.runtime_status.value,
            "release_decision": system.release_decision.value,
            "inherent_risk": system.inherent_risk.value,
            "rag_enabled": system.rag_enabled,
            "has_tools": bool(system.tools),
        },
        "evals": [_eval_to_dict(e) for e in evals],
    }


@router.get("/overview")
async def overview() -> dict:
    """Per-system summary for the Evals page index — counts by status."""
    out = []
    for s in list_ai_systems():
        es = [e for e in seed.EVAL_RESULTS if e.ai_system_id == s.id]
        passes = sum(1 for e in es if e.status.value == "PASS")
        warns = sum(1 for e in es if e.status.value == "WARN")
        fails = sum(1 for e in es if e.status.value == "FAIL")
        blocking_fails = sum(
            1 for e in es
            if e.status.value == "FAIL" and e.release_impact.value == "BLOCKS_RELEASE"
        )
        latest = max((e.run_at for e in es), default=None)
        out.append({
            "ai_system_id": s.id,
            "ai_system_name": s.name,
            "domain": s.domain,
            "runtime_status": s.runtime_status.value,
            "total": len(es),
            "passes": passes, "warns": warns, "fails": fails,
            "blocking_fails": blocking_fails,
            "latest_run": latest.isoformat() if latest else None,
        })
    return {"systems": out}


# ---------------------------------------------------------------------------
# Run Simulated Eval Suite
# ---------------------------------------------------------------------------

_DATA_DIR = Path(__file__).resolve().parents[1] / "data"
_DATA_DIR.mkdir(exist_ok=True)
_SIM_RUNS_FILE = _DATA_DIR / "simulated_eval_runs.jsonl"


@router.post("/run/{ai_system_id}")
async def run_simulated_suite(ai_system_id: str) -> dict:
    """Simulate re-running the eval suite for a system.

    Refreshes the run_at timestamp on each EvalResult, perturbs scores within a
    small band around the current value (so re-runs feel realistic but
    deterministic outcomes are preserved), then re-runs the assessment and
    release gate engines and returns the fresh decisions.
    """
    system = get_ai_system(ai_system_id)
    if not system:
        raise HTTPException(status_code=404, detail="System not found")

    now = datetime.utcnow()
    rng = random.Random(f"{ai_system_id}-{now.timestamp()}")

    refreshed: list[dict] = []
    for e in seed.EVAL_RESULTS:
        if e.ai_system_id != ai_system_id:
            continue
        # Mutate in place — these are domain models in memory, the simulated
        # run treats them as the latest result.
        jitter = rng.uniform(-0.005, 0.005)
        new_score = max(0.0, min(1.0, round(e.score + jitter, 4)))
        # Don't cross the threshold — preserve pass/fail/warn band
        if (e.score >= e.threshold) != (new_score >= e.threshold):
            new_score = e.score
        e.score = new_score
        e.run_at = now
        refreshed.append({
            "eval_id": e.id, "eval_type": e.eval_type.value,
            "new_score": new_score, "status": e.status.value,
        })

    # Persist the simulated run audit trail
    record = {
        "ai_system_id": ai_system_id,
        "ran_at": now.isoformat() + "Z",
        "evals": refreshed,
    }
    with _SIM_RUNS_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")

    # Re-run assessment + gates with the refreshed evals
    assessment = run_assessment(ai_system_id)
    gates = evaluate_gates(ai_system_id, target_environment="PILOT")

    return {
        "ai_system_id": ai_system_id,
        "ran_at": record["ran_at"],
        "eval_count": len(refreshed),
        "evals": refreshed,
        "assessment": {
            "overall_score": assessment.overall_score,
            "inherent_risk": assessment.inherent_risk,
            "residual_risk": assessment.residual_risk.level.value,
            "residual_score": assessment.residual_risk.normalized_score,
            "release_recommendation": assessment.release_recommendation.decision.value,
            "rule_fired": assessment.release_recommendation.rule_fired,
            "rationale": assessment.release_recommendation.rationale,
            "failed_controls": assessment.failed_controls,
            "findings_generated": len(assessment.findings),
            "evidence_completeness": assessment.evidence_completeness,
        },
        "release_gates": {
            "decision": gates.release_decision,
            "rationale": gates.release_rationale,
            "pass_count": gates.pass_count,
            "fail_count": gates.fail_count,
            "warning_count": gates.warning_count,
            "blocking_failures": gates.blocking_failures,
        },
    }
