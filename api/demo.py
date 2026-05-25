"""Guided FS demo — Payments Exception Review Agent walkthrough.

Drives the 13-step scripted demo. State and overlay mutations are isolated to
two files so /reset can wipe them cleanly:

  data/demo_state.json          — completed steps + cached assessment IDs
  data/demo_overlay.jsonl       — evidence + eval records that the demo injects

In addition, /reset removes any findings_events.jsonl entries authored by
'demo-walkthrough' so reruns are deterministic.

Session 39 — Track A OpenAPI sweep, per-router #19.

Routes and their OpenAPI treatment:

GET  /api/demo/state
  Strict Pydantic v2 model (DemoStateResponse) — fixed 5-key shape.
  operation_id: demo_get_state.

POST /api/demo/reset
  Strict Pydantic v2 model (DemoResetResponse) — single-key {"ok": bool}.
  operation_id: demo_post_reset.

POST /api/demo/step/{n}
  Permissive model (DemoStepResponse, extra="allow") — 13 steps each return
  a structurally different dict (step, title, plus step-specific keys). The
  asymmetric/polymorphic exemption from compound 27a applies: a closed schema
  would either be too wide (all optional) or silently strip valid step-specific
  keys. extra="allow" lets each step payload flow through unchanged.
  operation_id: demo_post_step.
"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, date, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from domain import repository
from domain.assessment_engine import run_assessment
from domain.controls import get_required_controls, get_controls_for_ai_system
from domain.findings_workflow import apply_event
from domain.models import (
    EvalResult, EvalType, EvalStatus, ReleaseImpact, ToolSource,
    FrameworkMapping, FrameworkName,
    Evidence, EvidenceType,
)


router = APIRouter(prefix="/api/demo", tags=["demo"])


DEMO_SYSTEM_ID = "ai-sys-001"
DEMO_ACTOR = "demo-walkthrough"

_DATA_DIR = Path(__file__).resolve().parents[1] / "data"
_DATA_DIR.mkdir(exist_ok=True)
_STATE_FILE = _DATA_DIR / "demo_state.json"
_OVERLAY_FILE = _DATA_DIR / "demo_overlay.jsonl"
_EVENTS_FILE = repository.FINDINGS_EVENTS_FILE


# ===========================================================================
# Response models (Session 39 — Track A OpenAPI sweep, per-router #19)
# ===========================================================================

class DemoStateResponse(BaseModel):
    """Current demo walkthrough state.

    Fixed 5-key shape: system identity plus step-completion tracking and
    cached assessment snapshots for v1 (pre-remediation) and v2 (post).
    """

    system_id: str
    system_name: str
    completed_steps: list[int]
    v1_assessment: Optional[dict[str, Any]] = None
    v2_assessment: Optional[dict[str, Any]] = None


class DemoResetResponse(BaseModel):
    """Confirmation that the demo state was wiped."""

    ok: bool


class DemoStepResponse(BaseModel):
    """Response envelope for a single demo step execution.

    Permissive (extra="allow"): each of the 13 steps returns a different
    payload shape beyond the common step/title keys — controls lists,
    assessment scores, connector run arrays, evidence attachments, finding
    transition records, and before/after delta dicts. A closed schema would
    either reject valid step-specific keys or require every field to be
    Optional, making the contract meaningless. extra="allow" is the correct
    choice per the asymmetric/polymorphic exemption (compound 27a).
    """

    step: int
    title: str

    model_config = ConfigDict(extra="allow")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ser(o: Any) -> Any:
    if is_dataclass(o):
        return {k: _ser(v) for k, v in asdict(o).items()}
    if isinstance(o, Enum):
        return o.value
    if isinstance(o, datetime):
        return o.isoformat() + ("Z" if o.tzinfo is None else "")
    if isinstance(o, date):
        return o.isoformat()
    if isinstance(o, (list, tuple)):
        return [_ser(v) for v in o]
    if isinstance(o, dict):
        return {k: _ser(v) for k, v in o.items()}
    if hasattr(o, "model_dump"):
        return _ser(o.model_dump())
    return o


def _load_state() -> dict[str, Any]:
    if not _STATE_FILE.exists():
        return {"completed_steps": [], "v1_assessment": None, "v2_assessment": None}
    return json.loads(_STATE_FILE.read_text(encoding="utf-8"))


def _save_state(s: dict[str, Any]) -> None:
    _STATE_FILE.write_text(json.dumps(s, indent=2), encoding="utf-8")


def _mark_step(n: int) -> dict[str, Any]:
    s = _load_state()
    if n not in s["completed_steps"]:
        s["completed_steps"].append(n)
        s["completed_steps"].sort()
    _save_state(s)
    return s


def _append_overlay(kind: str, data: dict[str, Any]) -> None:
    with _OVERLAY_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"kind": kind, "data": data}) + "\n")


def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


# ---------------------------------------------------------------------------
# State + reset
# ---------------------------------------------------------------------------

@router.get("/state", response_model=DemoStateResponse, operation_id="demo_get_state")
async def get_state() -> dict[str, Any]:
    s = _load_state()
    system = repository.get_ai_system(DEMO_SYSTEM_ID)
    return {
        "system_id": DEMO_SYSTEM_ID,
        "system_name": system.name if system else DEMO_SYSTEM_ID,
        "completed_steps": s.get("completed_steps", []),
        "v1_assessment": s.get("v1_assessment"),
        "v2_assessment": s.get("v2_assessment"),
    }


@router.post("/reset", response_model=DemoResetResponse, operation_id="demo_post_reset")
async def reset() -> dict[str, Any]:
    """Wipe demo overlay state + filter demo events from the findings log."""
    if _STATE_FILE.exists():
        _STATE_FILE.unlink()
    if _OVERLAY_FILE.exists():
        _OVERLAY_FILE.unlink()

    # Strip demo-authored events from findings_events.jsonl
    if _EVENTS_FILE.exists():
        kept: list[str] = []
        for line in _EVENTS_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("actor") != DEMO_ACTOR:
                kept.append(line)
        if kept:
            _EVENTS_FILE.write_text("\n".join(kept) + "\n", encoding="utf-8")
        else:
            _EVENTS_FILE.unlink()

    return {"ok": True}


# ---------------------------------------------------------------------------
# Step actions
# ---------------------------------------------------------------------------

@router.post("/step/{n}", response_model=DemoStepResponse, operation_id="demo_post_step")
async def execute_step(n: int) -> dict[str, Any]:
    """Execute step n. Idempotent except where noted."""
    if n < 1 or n > 13:
        raise HTTPException(400, f"Invalid step {n}")
    system = repository.get_ai_system(DEMO_SYSTEM_ID)
    if not system:
        raise HTTPException(404, f"Demo system {DEMO_SYSTEM_ID} not found")

    if n == 1:
        out = _step_1_intake(system)
    elif n == 2:
        out = _step_2_classify(system)
    elif n == 3:
        out = _step_3_controls(system)
    elif n == 4:
        out = _step_4_assess()
    elif n == 5:
        out = _step_5_findings()
    elif n == 6:
        out = _step_6_evals()
    elif n == 7:
        out = _step_7_gates()
    elif n == 8:
        out = _step_8_decision()
    elif n == 9:
        out = _step_9_remediation()
    elif n == 10:
        out = _step_10_attach_evidence()
    elif n == 11:
        out = _step_11_close_findings()
    elif n == 12:
        out = _step_12_reassess()
    elif n == 13:
        out = _step_13_final_decision()
    else:
        raise HTTPException(400, f"Step {n} not implemented")

    _mark_step(n)
    return out


# --- step implementations ---------------------------------------------------

def _step_1_intake(system: Any) -> dict[str, Any]:
    return {
        "step": 1, "title": "AI System Intake",
        "summary": "Intake submitted for the Payments Exception Review Agent.",
        "system": {
            "id": system.id, "name": system.name,
            "description": system.description,
            "domain": system.domain,
            "cloud_provider": system.cloud_provider.value,
            "model_provider": system.model_provider,
            "data_classes": [d.value for d in system.data_classes],
            "autonomy_level": system.autonomy_level.value,
            "user_population": system.user_population,
            "regulatory_exposure": [r.value for r in system.regulatory_exposure],
            "aws_services": system.aws_services,
            "rag_enabled": system.rag_enabled,
            "tools": [{"name": t.name, "side_effect": t.side_effect} for t in system.tools],
        },
        "deep_link": f"/ai-systems",
    }


def _step_2_classify(system: Any) -> dict[str, Any]:
    from domain.assessment_engine import classify_risk
    c = classify_risk(system)
    return {
        "step": 2, "title": "Inherent Risk Classification",
        "risk_level": c.risk_level.value,
        "rules_fired": c.rules_fired,
        "rationale": c.rationale,
        "deep_link": f"/ai-systems",
    }


def _step_3_controls(system: Any) -> dict[str, Any]:
    required = get_required_controls(system)
    all_applicable = get_controls_for_ai_system(system)
    return {
        "step": 3, "title": "Required Controls",
        "required_count": len(required),
        "applicable_count": len(all_applicable),
        "required": [
            {
                "control_id": c.control_id, "title": c.title,
                "domain": c.domain.value, "priority": c.priority.value,
                "frameworks": sorted({fm.framework.value for fm in c.framework_mappings}),
            }
            for c in required
        ],
        "deep_link": "/governance",
    }


def _step_4_assess() -> dict[str, Any]:
    report = run_assessment(DEMO_SYSTEM_ID)
    rep = _ser(report)
    s = _load_state()
    s["v1_assessment"] = rep
    _save_state(s)
    return {
        "step": 4, "title": "Run Assessment (v1)",
        "overall_score": report.overall_score,
        "residual_risk": report.residual_risk.level.value,
        "release_decision": report.release_recommendation.decision.value,
        "rule_fired": report.release_recommendation.rule_fired,
        "rationale": report.release_recommendation.rationale,
        "failed_controls": report.failed_controls,
        "evidence_completeness": report.evidence_completeness,
        "deep_link": "/assessment",
    }


def _step_5_findings() -> dict[str, Any]:
    findings = repository.findings_for(DEMO_SYSTEM_ID)
    by_severity: dict[str, list[dict[str, Any]]] = {"CRITICAL": [], "HIGH": [], "MEDIUM": [], "LOW": []}
    for f in findings:
        sev = f.severity.value
        if f.status.value in ("OPEN", "IN_PROGRESS"):
            by_severity.get(sev, by_severity["LOW"]).append({
                "id": f.id, "title": f.title, "control_id": f.control_id,
                "owner": f.owner, "status": f.status.value,
            })
    return {
        "step": 5, "title": "Findings Generated",
        "open_critical": len(by_severity["CRITICAL"]),
        "open_high": len(by_severity["HIGH"]),
        "open_medium": len(by_severity["MEDIUM"]),
        "findings": by_severity,
        "deep_link": "/findings",
    }


def _step_6_evals() -> dict[str, Any]:
    """Run the simulated eval connectors and write authoritative passing evals
    for the three eval types that gate release: PII_LEAKAGE, PROMPT_INJECTION,
    TOOL_AUTHORIZATION. These overlay on top of the (failing) seed evals; the
    assessment engine takes the latest-by-run_at per type.
    """
    from domain.connectors import BY_NAME
    run_results: list[dict[str, Any]] = []
    for connector_name in ("DeepEval", "Garak", "PyRIT"):
        if connector_name in BY_NAME:
            r = BY_NAME[connector_name].run()
            run_results.append({
                "connector": connector_name,
                "evals": r.evals_produced,
                "findings": r.findings_produced,
                "evidence": r.evidence_produced,
            })

    # Authoritative passing demo evals (will be the latest-by-run_at).
    now = datetime.utcnow()
    demo_evals = [
        _make_demo_eval_record(
            id_="demo-eval-pii", eval_type=EvalType.PII_LEAKAGE,
            score=0.999, threshold=0.999, status=EvalStatus.PASS,
            tool=ToolSource.DEEPEVAL, test_count=500, failed=0,
            controls=["AI-001", "AI-019"],
            note="Macie + DLP regression — 0 leaks in 500 redacted-summary samples.",
            run_at=now,
        ),
        _make_demo_eval_record(
            id_="demo-eval-pi", eval_type=EvalType.PROMPT_INJECTION,
            score=0.97, threshold=0.95, status=EvalStatus.PASS,
            tool=ToolSource.GARAK, test_count=500, failed=15,
            controls=["AI-003", "AI-006", "AI-020"],
            note="Garak instruction-isolation suite — 97% block rate after RAG sanitizer + tool-router authz hardening.",
            run_at=now,
        ),
        _make_demo_eval_record(
            id_="demo-eval-ta", eval_type=EvalType.TOOL_AUTHORIZATION,
            score=0.995, threshold=0.99, status=EvalStatus.PASS,
            tool=ToolSource.PYRIT, test_count=200, failed=1,
            controls=["AI-005", "AI-006", "AI-023"],
            note="PyRIT authorization probe — 199/200 unauthorized calls correctly denied.",
            run_at=now,
        ),
    ]
    for e in demo_evals:
        _append_overlay("eval", e)

    return {
        "step": 6, "title": "Simulated Evals (DeepEval / Garak / PyRIT)",
        "connector_runs": run_results,
        "authoritative_evals": [
            {"id": e["id"], "type": e["eval_type"], "score": e["score"],
             "threshold": e["threshold"], "status": e["status"]}
            for e in demo_evals
        ],
        "deep_link": "/evals",
    }


def _make_demo_eval_record(
    *,
    id_: str,
    eval_type: EvalType,
    score: float,
    threshold: float,
    status: EvalStatus,
    tool: ToolSource,
    test_count: int,
    failed: int,
    controls: list[str],
    note: str,
    run_at: datetime,
) -> dict[str, Any]:
    """Construct an EvalResult dict suitable for overlay storage."""
    e = EvalResult(
        id=id_, ai_system_id=DEMO_SYSTEM_ID, assessment_id=None,
        eval_type=eval_type, score=score, threshold=threshold,
        status=status, release_impact=ReleaseImpact.NO_IMPACT,
        tool_source=tool,
        framework_mappings=[
            FrameworkMapping(framework=FrameworkName.OWASP_LLM_TOP10, clause="LLM01"),
        ],
        control_mappings=controls,
        test_count=test_count, failed_count=failed,
        sample_failures=[], notes=note, run_at=run_at,
    )
    return json.loads(e.model_dump_json())


def _step_7_gates() -> dict[str, Any]:
    from domain.release_gate_engine import evaluate_gates
    report = evaluate_gates(DEMO_SYSTEM_ID)
    return {
        "step": 7, "title": "Release Gates Evaluation",
        "summary": _ser(report),
        "deep_link": "/release-gates",
    }


def _step_8_decision() -> dict[str, Any]:
    """Show the v1 HOLD decision (assumes step 4 ran)."""
    s = _load_state()
    v1 = s.get("v1_assessment")
    if not v1:
        v1 = _ser(run_assessment(DEMO_SYSTEM_ID))
        s["v1_assessment"] = v1
        _save_state(s)
    rec = v1["release_recommendation"]
    return {
        "step": 8, "title": "Release Decision: HOLD",
        "decision": rec["decision"],
        "rule_fired": rec["rule_fired"],
        "rationale": rec["rationale"],
        "overall_score": v1["overall_score"],
        "deep_link": "/assessment",
    }


def _step_9_remediation() -> dict[str, Any]:
    findings = [
        f for f in repository.findings_for(DEMO_SYSTEM_ID)
        if f.status.value in ("OPEN", "IN_PROGRESS")
    ]
    plan: list[dict[str, Any]] = []
    for f in findings:
        plan.append({
            "finding_id": f.id, "title": f.title,
            "severity": f.severity.value, "control_id": f.control_id,
            "owner": f.owner, "sla_due": f.sla_due_date.isoformat(),
            "remediation": f.remediation,
        })
    return {
        "step": 9, "title": "Remediation Plan",
        "open_count": len(plan),
        "items": plan,
        "deep_link": "/findings",
    }


def _step_10_attach_evidence() -> dict[str, Any]:
    """Inject the evidence records that the v1 assessment flagged as missing —
    notably RAG_CONFIG (for AI-004 / F-1004) and a fresh REMEDIATION_VERIFICATION.
    """
    now = datetime.utcnow()
    items = [
        Evidence(
            id="EV-DEMO-RAG",
            ai_system_id=DEMO_SYSTEM_ID,
            evidence_type=EvidenceType.RAG_CONFIG,
            source="DLP-gated embedding pipeline",
            uri="s3://bank-rag-payments-prod/manifest-v13.json",
            hash="sha256:demo-rag-001",
            collected_at=now,
            summary="Wire-operations corpus re-ingested through DLP-gated embedding pipeline; Macie scan attached; manifest pinned at v13.",
            immutable=True,
            linked_control_ids=["AI-004"],
            linked_finding_ids=["F-1004"],
            linked_frameworks=["OWASP_LLM_TOP10", "FS_OVERLAY"],
        ),
        Evidence(
            id="EV-DEMO-MAC",
            ai_system_id=DEMO_SYSTEM_ID,
            evidence_type=EvidenceType.MACIE_FINDING,
            source="AWS Macie",
            uri="arn:aws:macie2:us-east-1:findings/demo-001",
            hash="sha256:demo-mac-001",
            collected_at=now,
            summary="Macie continuous scan over bank-rag-payments-prod — 0 sensitive matches on v13 manifest.",
            immutable=True,
            linked_control_ids=["AI-001", "AI-004", "AI-019"],
            linked_finding_ids=["F-1004"],
            linked_frameworks=["FS_OVERLAY"],
        ),
        Evidence(
            id="EV-DEMO-RVR",
            ai_system_id=DEMO_SYSTEM_ID,
            evidence_type=EvidenceType.REMEDIATION_VERIFICATION,
            source="AppSec",
            uri="https://internal.bank/appsec/verifications/demo-001",
            hash="sha256:demo-rvr-001",
            collected_at=now,
            summary="Instruction isolation + tool-router authz + rate-limit hardening verified end-to-end against the prompt-injection attack family.",
            immutable=True,
            linked_control_ids=["AI-003", "AI-005", "AI-006"],
            linked_finding_ids=["FIND-2026-0138", "F-1003"],
            linked_frameworks=["OWASP_LLM_TOP10", "OWASP_AGENTIC_TOP10"],
        ),
        Evidence(
            id="EV-DEMO-APPR",
            ai_system_id=DEMO_SYSTEM_ID,
            evidence_type=EvidenceType.APPROVAL_RECORD,
            source="Governance Portal",
            uri="https://internal.bank/governance/approvals/demo-001",
            hash="sha256:demo-appr-001",
            collected_at=now,
            summary="CRO + CISO conditional pilot approval pending final gate re-eval; HITL gate on release_payment confirmed in tool-router.",
            immutable=True,
            linked_control_ids=["AI-007", "AI-031"],
            linked_finding_ids=["F-1005"],
            linked_frameworks=["NIST_AI_RMF", "FS_OVERLAY"],
        ),
    ]
    for e in items:
        _append_overlay("evidence", json.loads(e.model_dump_json()))

    return {
        "step": 10, "title": "Attach Evidence",
        "attached": [{"id": e.id, "type": e.evidence_type.value,
                       "summary": e.summary} for e in items],
        "deep_link": "/evidence",
    }


def _step_11_close_findings() -> dict[str, Any]:
    """Mark the CRITICAL prompt-injection finding remediated + verified, and
    transition the HIGH unauthorized-tool-call and RAG-quarantine findings into
    REMEDIATED. The remaining HIGH/MEDIUM stay open — that's what makes the
    v2 decision CONDITIONAL_PILOT rather than APPROVED.
    """
    targets = [
        ("FIND-2026-0138", "CLOSE", "Prompt-injection bypass closed — verified by EV-DEMO-RVR."),
        ("F-1003",          "MARK_REMEDIATED", "Authz moved out of model loop; rate limits applied."),
        ("F-1004",          "MARK_REMEDIATED", "Corpus re-ingested with DLP gate; manifest pinned."),
    ]
    applied: list[dict[str, Any]] = []
    for fid, et, note in targets:
        try:
            ev = apply_event(
                finding_id=fid, event_type=et,
                actor=DEMO_ACTOR, data={}, note=note,
            )
            applied.append({"finding_id": fid, "event": et, "ts": ev.ts})
        except ValueError as e:
            applied.append({"finding_id": fid, "event": et, "error": str(e)})

    return {
        "step": 11, "title": "Mark Findings Remediated",
        "applied": applied,
        "deep_link": "/findings",
    }


def _step_12_reassess() -> dict[str, Any]:
    """Re-run the assessment. With evidence attached, evals refreshed, and the
    CRITICAL finding closed, the engine should now produce CONDITIONAL_PILOT.
    """
    report = run_assessment(DEMO_SYSTEM_ID)
    rep = _ser(report)
    s = _load_state()
    s["v2_assessment"] = rep
    _save_state(s)
    return {
        "step": 12, "title": "Re-Run Assessment (v2)",
        "overall_score": report.overall_score,
        "residual_risk": report.residual_risk.level.value,
        "release_decision": report.release_recommendation.decision.value,
        "rule_fired": report.release_recommendation.rule_fired,
        "rationale": report.release_recommendation.rationale,
        "evidence_completeness": report.evidence_completeness,
        "failed_controls": report.failed_controls,
        "deep_link": "/assessment",
    }


def _step_13_final_decision() -> dict[str, Any]:
    s = _load_state()
    v1 = s.get("v1_assessment")
    v2 = s.get("v2_assessment")
    if not v2:
        _step_12_reassess()
        v2 = _load_state().get("v2_assessment")
    delta = None
    if v1 and v2:
        delta = {
            "before": {
                "decision": v1["release_recommendation"]["decision"],
                "rule_fired": v1["release_recommendation"]["rule_fired"],
                "score": v1["overall_score"],
                "evidence_completeness": v1["evidence_completeness"],
            },
            "after": {
                "decision": v2["release_recommendation"]["decision"],
                "rule_fired": v2["release_recommendation"]["rule_fired"],
                "score": v2["overall_score"],
                "evidence_completeness": v2["evidence_completeness"],
            },
        }
    return {
        "step": 13, "title": "Final Decision: Conditional Pilot",
        "delta": delta,
        "v2_conditions": (v2 or {}).get("release_recommendation", {}).get("conditions", []),
        "deep_link": "/release-gates",
    }
