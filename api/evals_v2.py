"""Eval results API + Simulated Eval Suite trigger.

These endpoints serve the refactored Evals page. They expose the rich
EvalResult objects (with framework/control mappings + sample failures)
and provide a "Run Simulated Eval Suite" action that re-times the
eval results and re-runs the assessment engine.

Typed per docs/plans/SESSION-13-api-typing-audit.md §3.1.

NOTE on JobResponse: the audit doc §3.1 originally tagged
run_simulated_suite as JobResponse-shaped (async-emitting). On code review,
this endpoint is fully SYNCHRONOUS -- it mutates seed.EVAL_RESULTS in place,
runs assessment + gates inline, returns the full result. No Claude call, no
background queue. Typed as SimulatedRunOut (synchronous result envelope).
Audit doc §3.1 corrected by this implementation.
"""
from __future__ import annotations

import json
import random
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from domain import seed
from domain.repository import get_ai_system, list_ai_systems
from domain.assessment_engine import run_assessment
from domain.release_gate_engine import evaluate_gates


router = APIRouter(prefix="/api/grc/evals/v2", tags=["evals-v2"])


def _strict() -> ConfigDict:
    return ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------

class EvalFrameworkMappingOut(BaseModel):
    model_config = _strict()
    framework: str
    clause: str
    rationale: str | None = None


class EvalResultOut(BaseModel):
    """One eval result with framework/control mappings + sample failures.

    Wire shape from seed.EVAL_RESULTS[*].model_dump(mode='json') + computed
    pass_rate.
    """
    model_config = _strict()

    id: str
    ai_system_id: str
    assessment_id: str | None = None
    eval_type: str
    score: float
    threshold: float
    status: str
    release_impact: str
    tool_source: str
    framework_mappings: list[EvalFrameworkMappingOut]
    control_mappings: list[str]
    evidence_id: str | None = None
    test_count: int | None = None
    failed_count: int | None = None
    sample_failures: list[str] = Field(default_factory=list)
    sample_size: int | None = None
    notes: str | None = None
    run_at: str
    # Computed: passed / test_count when test_count is non-zero.
    pass_rate: float | None = None


class AiSystemContextOut(BaseModel):
    """Compact AI system context surfaced beside the evals list."""
    model_config = _strict()

    id: str
    name: str
    domain: str
    runtime_status: str
    release_decision: str
    inherent_risk: str
    rag_enabled: bool
    has_tools: bool


class SystemEvalsOut(BaseModel):
    model_config = _strict()
    ai_system: AiSystemContextOut
    evals: list[EvalResultOut]


class EvalOverviewRowOut(BaseModel):
    """Per-system summary row for the Evals page index."""
    model_config = _strict()

    ai_system_id: str
    ai_system_name: str
    domain: str
    runtime_status: str
    total: int
    passes: int
    warns: int
    fails: int
    blocking_fails: int
    latest_run: str | None = None


class EvalsOverviewOut(BaseModel):
    model_config = _strict()
    systems: list[EvalOverviewRowOut]


# ---------------------------------------------------------------------------
# Simulated-run result sub-models
# ---------------------------------------------------------------------------

class RefreshedEvalOut(BaseModel):
    model_config = _strict()
    eval_id: str
    eval_type: str
    new_score: float
    status: str


class AssessmentSummaryOut(BaseModel):
    model_config = _strict()
    overall_score: float
    inherent_risk: str
    residual_risk: str
    residual_score: float
    release_recommendation: str
    rule_fired: str | None = None
    rationale: str | None = None
    failed_controls: list[str]
    findings_generated: int
    evidence_completeness: float


class GateRollupOut(BaseModel):
    model_config = _strict()
    decision: str
    rationale: str
    pass_count: int
    fail_count: int
    warning_count: int
    blocking_failures: int = Field(description="Count of blocking gates that failed.")


class SimulatedRunOut(BaseModel):
    """Synchronous result of re-running the simulated eval suite for one system.

    NOT a JobResponse -- this endpoint completes inline; no background work.
    """
    model_config = _strict()

    ai_system_id: str
    ran_at: str
    eval_count: int
    evals: list[RefreshedEvalOut]
    assessment: AssessmentSummaryOut
    release_gates: GateRollupOut


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _eval_to_out(e: Any) -> EvalResultOut:
    """Build EvalResultOut from a seed.EVAL_RESULTS item, with pass_rate computed."""
    d = e.model_dump(mode="json")
    if d.get("test_count"):
        passed = d["test_count"] - (d.get("failed_count") or 0)
        d["pass_rate"] = round(passed / d["test_count"], 4)
    return EvalResultOut(**d)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/system/{ai_system_id}",
    response_model=SystemEvalsOut,
    operation_id="evals_v2_system",
)
async def system_evals(ai_system_id: str) -> SystemEvalsOut:
    """All eval results for one system, with the assessment context."""
    system = get_ai_system(ai_system_id)
    if not system:
        raise HTTPException(status_code=404, detail="System not found")

    evals = [e for e in seed.EVAL_RESULTS if e.ai_system_id == ai_system_id]
    order = {"FAIL": 0, "WARN": 1, "PASS": 2, "NOT_RUN": 3}
    evals.sort(key=lambda e: (order.get(e.status.value, 9), e.eval_type.value))

    return SystemEvalsOut(
        ai_system=AiSystemContextOut(
            id=system.id,
            name=system.name,
            domain=system.domain,
            runtime_status=system.runtime_status.value,
            release_decision=system.release_decision.value,
            inherent_risk=system.inherent_risk.value,
            rag_enabled=system.rag_enabled,
            has_tools=bool(system.tools),
        ),
        evals=[_eval_to_out(e) for e in evals],
    )


@router.get(
    "/overview",
    response_model=EvalsOverviewOut,
    operation_id="evals_v2_overview",
)
async def overview() -> EvalsOverviewOut:
    """Per-system summary for the Evals page index -- counts by status."""
    out: list[EvalOverviewRowOut] = []
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
        out.append(EvalOverviewRowOut(
            ai_system_id=s.id,
            ai_system_name=s.name,
            domain=s.domain,
            runtime_status=s.runtime_status.value,
            total=len(es),
            passes=passes,
            warns=warns,
            fails=fails,
            blocking_fails=blocking_fails,
            latest_run=latest.isoformat() if latest else None,
        ))
    return EvalsOverviewOut(systems=out)


# ---------------------------------------------------------------------------
# Run Simulated Eval Suite
# ---------------------------------------------------------------------------

_DATA_DIR = Path(__file__).resolve().parents[1] / "data"
_DATA_DIR.mkdir(exist_ok=True)
_SIM_RUNS_FILE = _DATA_DIR / "simulated_eval_runs.jsonl"


@router.post(
    "/run/{ai_system_id}",
    response_model=SimulatedRunOut,
    operation_id="evals_v2_run_simulated_suite",
)
async def run_simulated_suite(ai_system_id: str) -> SimulatedRunOut:
    """Simulate re-running the eval suite for a system (synchronous).

    Refreshes the run_at timestamp on each EvalResult, perturbs scores within a
    small band around the current value (so re-runs feel realistic but
    deterministic outcomes are preserved), then re-runs the assessment and
    release gate engines and returns the fresh decisions inline.
    """
    system = get_ai_system(ai_system_id)
    if not system:
        raise HTTPException(status_code=404, detail="System not found")

    now = datetime.utcnow()
    rng = random.Random(f"{ai_system_id}-{now.timestamp()}")

    refreshed: list[RefreshedEvalOut] = []
    for e in seed.EVAL_RESULTS:
        if e.ai_system_id != ai_system_id:
            continue
        jitter = rng.uniform(-0.005, 0.005)
        new_score = max(0.0, min(1.0, round(e.score + jitter, 4)))
        if (e.score >= e.threshold) != (new_score >= e.threshold):
            new_score = e.score
        e.score = new_score
        e.run_at = now
        refreshed.append(RefreshedEvalOut(
            eval_id=e.id,
            eval_type=e.eval_type.value,
            new_score=new_score,
            status=e.status.value,
        ))

    ran_at = now.isoformat() + "Z"
    with _SIM_RUNS_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "ai_system_id": ai_system_id,
            "ran_at": ran_at,
            "evals": [r.model_dump() for r in refreshed],
        }) + "\n")

    assessment = run_assessment(ai_system_id)
    gates = evaluate_gates(ai_system_id, target_environment="PILOT")

    return SimulatedRunOut(
        ai_system_id=ai_system_id,
        ran_at=ran_at,
        eval_count=len(refreshed),
        evals=refreshed,
        assessment=AssessmentSummaryOut(
            overall_score=assessment.overall_score,
            inherent_risk=assessment.inherent_risk,
            residual_risk=assessment.residual_risk.level.value,
            residual_score=assessment.residual_risk.normalized_score,
            release_recommendation=assessment.release_recommendation.decision.value,
            rule_fired=assessment.release_recommendation.rule_fired,
            rationale=assessment.release_recommendation.rationale,
            failed_controls=assessment.failed_controls,
            findings_generated=len(assessment.findings),
            evidence_completeness=assessment.evidence_completeness,
        ),
        release_gates=GateRollupOut(
            decision=gates.release_decision,
            rationale=gates.release_rationale,
            pass_count=gates.pass_count,
            fail_count=gates.fail_count,
            warning_count=gates.warning_count,
            blocking_failures=gates.blocking_failures,
        ),
    )
