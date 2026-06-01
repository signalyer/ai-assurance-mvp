"""Assessment Engine.

Turns an AI system + control library + eval results + evidence + runtime events
into a structured assessment: per-control status, generated findings, residual
risk score, framework coverage, and a release recommendation.

All service functions are PURE (no I/O) except `run_assessment`, which uses
the repository to gather inputs.

Public API:
    run_assessment(ai_system_id) -> AssessmentReport
    classify_risk(ai_system) -> RiskClassification
    apply_required_controls(ai_system) -> list[Control]
    evaluate_control(control, system, evidence, eval_results, runtime_events) -> ControlEvaluation
    generate_findings(system, failed_controls) -> list[GeneratedFinding]
    calculate_residual_risk(system, findings, eval_results) -> ResidualRiskScore
    generate_release_recommendation(system, findings, release_gates, evidence_completeness)
        -> ReleaseRecommendation
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import uuid4

from domain.models import (
    AISystem, Control, Evidence, EvalResult, RuntimeEvent, ReleaseGate, Finding,
    AutonomyLevel, DataClass, CustomerImpact, RegulatoryExposure, RiskLevel,
    ReleaseDecision, Severity, FindingStatus, ReleaseImpact, EvidenceType,
    EvalStatus, EvalType, Priority, FrameworkName, FrameworkMapping,
)
from domain.controls import (
    CONTROLS, get_controls_for_ai_system, get_required_controls,
    is_applicable, map_control_to_frameworks,
)
from domain.risk_classification import classify_inherent_risk, RiskClassification
from domain import repository


# ===========================================================================
# Result dataclasses
# ===========================================================================

class ControlStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    PARTIAL = "PARTIAL"
    NO_EVIDENCE = "NO_EVIDENCE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass
class ControlEvaluation:
    control_id: str
    title: str
    domain: str
    priority: str
    status: ControlStatus
    blocking: bool
    rationale: str
    open_finding_ids: list[str] = field(default_factory=list)
    missing_evidence_types: list[str] = field(default_factory=list)
    failed_evals: list[str] = field(default_factory=list)
    related_runtime_events: int = 0


@dataclass
class GeneratedFinding:
    """A finding the engine would CREATE for a failed control.
    These do not persist automatically — caller decides whether to write them.
    """
    id: str
    ai_system_id: str
    control_id: str
    title: str
    description: str
    severity: str
    framework_mappings: list[dict]
    owner: str
    release_impact: str
    remediation: str


@dataclass
class RiskFactors:
    likelihood: float           # 0..1   — failed evals + open findings
    impact: float               # 0..1   — customer/regulatory exposure
    exposure: float             # 0..1   — user population
    autonomy: float             # 0..1   — autonomy level
    data_sensitivity: float     # 0..1   — most sensitive data class
    control_gap_modifier: float # 1..2   — missing critical controls

    @property
    def raw_score(self) -> float:
        return (self.likelihood * self.impact * self.exposure
                * self.autonomy * self.data_sensitivity * self.control_gap_modifier)


@dataclass
class ResidualRiskScore:
    factors: RiskFactors
    raw_score: float            # likelihood × impact × exposure × autonomy × data × gap
    normalized_score: float     # 0..100
    level: RiskLevel
    explanation: list[str]


@dataclass
class FrameworkCoverage:
    """Per-framework coverage rollup produced by :func:`calculate_framework_coverage`.

    ``framework_refs`` lists the distinct clauses across all applicable controls
    mapped to this framework, giving callers a quick reference to the exact
    regulatory/standard anchors being measured.
    """

    framework: str
    controls_applicable: int
    controls_passing: int
    controls_failing: int
    coverage_pct: float
    framework_refs: list[dict] = field(default_factory=list)  # [{framework, clause}]


@dataclass
class ReleaseRecommendation:
    decision: ReleaseDecision
    rule_fired: str             # which decision rule triggered (R-Rej / R-Hold-* / R-Cond / R-AppPilot / R-AppProd)
    rationale: str
    conditions: list[str] = field(default_factory=list)


@dataclass
class AssessmentReport:
    ai_system_id: str
    ai_system_name: str
    generated_at: str
    overall_score: float        # 0..100, higher = better
    inherent_risk: str
    inherent_risk_rules: list[str]
    residual_risk: ResidualRiskScore
    release_recommendation: ReleaseRecommendation
    control_evaluations: list[ControlEvaluation]
    failed_controls: list[str]
    findings: list[GeneratedFinding]
    required_remediation: list[str]
    framework_coverage: list[FrameworkCoverage]
    evidence_completeness: float        # 0..1


# ===========================================================================
# 1. Risk classification (delegates to risk_classification module)
# ===========================================================================

def classify_risk(system: AISystem) -> RiskClassification:
    """Re-classify inherent risk from a materialized AISystem (audit-friendly)."""
    intake_view = {
        "domain": system.domain,
        "user_population": system.user_population,
        "customer_impact": _customer_impact_to_intake_str(system.customer_impact),
        "data_classes": [_data_class_to_intake(d) for d in system.data_classes],
        "rag_enabled": system.rag_enabled,
        "tools_used": [t.name for t in system.tools],
        "can_call_tools": bool(system.tools),
        "can_write_data": any(t.side_effect for t in system.tools),
        "can_trigger_customer_communication": False,
        "can_influence_fs_workflow": _influences_fs(system),
        "tools_return_sensitive_data": False,
        "autonomy_level": _autonomy_to_intake_str(system.autonomy_level),
    }
    return classify_inherent_risk(intake_view)


def _customer_impact_to_intake_str(ci: CustomerImpact) -> str:
    return {
        CustomerImpact.NONE: "none",
        CustomerImpact.INDIRECT: "indirect",
        CustomerImpact.DIRECT: "direct",
        CustomerImpact.DIRECT_FINANCIAL: "material",
    }[ci]


def _data_class_to_intake(d: DataClass) -> str:
    return {
        DataClass.PUBLIC: "public",
        DataClass.PII: "pii", DataClass.NPI: "npi", DataClass.PCI: "pci",
        DataClass.PHI: "pii",
        DataClass.ACCOUNT_NUMBERS: "payment_data",
        DataClass.TRANSACTION_DATA: "payment_data",
        DataClass.AUTHENTICATION_DATA: "pii",
        DataClass.SAR_DATA: "aml_kyc_data",
        DataClass.KYC_DOCUMENTS: "aml_kyc_data",
        DataClass.BIOMETRIC: "pii",
        DataClass.FINANCIAL_STATEMENTS: "credit_data",
        DataClass.SANCTIONS_LISTS: "aml_kyc_data",
        DataClass.INTERNAL_CREDIT: "credit_data",
        DataClass.MARKET_DATA: "internal",
        DataClass.CUSTOMER_NAMES: "pii",
    }.get(d, "internal")


def _autonomy_to_intake_str(a: AutonomyLevel) -> str:
    return {
        AutonomyLevel.ADVISORY: "answer_only",
        AutonomyLevel.TRIAGE: "recommend",
        AutonomyLevel.DOCUMENT_GENERATION: "draft",
        AutonomyLevel.TOOL_USING_HITL: "execute_with_approval",
        AutonomyLevel.TOOL_USING_AUTONOMOUS: "execute_autonomously",
        AutonomyLevel.FULLY_AUTONOMOUS: "execute_autonomously",
    }[a]


def _influences_fs(system: AISystem) -> bool:
    fs_regs = {
        RegulatoryExposure.GLBA, RegulatoryExposure.BSA_AML, RegulatoryExposure.OFAC,
        RegulatoryExposure.FFIEC, RegulatoryExposure.SOX, RegulatoryExposure.CFPB,
    }
    return bool(set(system.regulatory_exposure) & fs_regs)


# ===========================================================================
# 2. Required controls
# ===========================================================================

def apply_required_controls(system: AISystem) -> list[Control]:
    """The set of P0/P1 controls that this system must satisfy to release."""
    return get_required_controls(system)


# ===========================================================================
# 3. Per-control evaluation
# ===========================================================================

def evaluate_control(
    control: Control,
    system: AISystem,
    evidence: list[Evidence],
    eval_results: list[EvalResult],
    runtime_events: list[RuntimeEvent],
) -> ControlEvaluation:
    """Pure evaluation of a single control against the system's evidence base."""
    if not is_applicable(control, system):
        return ControlEvaluation(
            control_id=control.control_id, title=control.title,
            domain=control.domain.value, priority=control.priority.value,
            status=ControlStatus.NOT_APPLICABLE, blocking=False,
            rationale="Applicability predicate did not match this system.",
        )

    # Findings mapped to this control (open or in_progress)
    open_findings_all = repository.findings_for(system.id)
    open_findings = [
        f for f in open_findings_all
        if f.control_id == control.control_id
        and f.status in (FindingStatus.OPEN, FindingStatus.IN_PROGRESS)
    ]
    open_critical = [f for f in open_findings if f.severity == Severity.CRITICAL]
    open_high_or_critical = [f for f in open_findings if f.severity in (Severity.CRITICAL, Severity.HIGH)]

    # Required evidence types present?
    evidence_types_present = {e.evidence_type for e in evidence}
    missing = [et for et in control.evidence_required if et not in evidence_types_present]

    # Failed evals that map to this control's domain (best-effort heuristic)
    failed_evals = [
        e.eval_type.value for e in eval_results
        if e.status in (EvalStatus.FAIL, EvalStatus.WARN)
        and _eval_relates_to_control(e.eval_type, control)
    ]

    # Runtime events that map to this control (heuristic)
    related_events = sum(1 for ev in runtime_events if _event_relates_to_control(ev, control))

    # Resolve status
    if open_high_or_critical or failed_evals:
        status = ControlStatus.FAIL
        blocking = control.priority == Priority.P0 and (
            bool(open_critical) or bool(failed_evals)
        )
        bits = []
        if open_high_or_critical:
            bits.append(f"{len(open_high_or_critical)} open HIGH/CRITICAL finding(s)")
        if failed_evals:
            bits.append(f"failed evals: {', '.join(sorted(set(failed_evals)))}")
        rationale = "; ".join(bits) + "."
    elif open_findings:
        status = ControlStatus.PARTIAL
        blocking = False
        rationale = f"{len(open_findings)} open MEDIUM/LOW finding(s) mapped to this control."
    elif missing:
        status = ControlStatus.NO_EVIDENCE
        blocking = control.priority == Priority.P0
        rationale = f"Missing evidence: {', '.join(m.value for m in missing)}."
    else:
        status = ControlStatus.PASS
        blocking = False
        rationale = "No open findings; required evidence present; relevant evals pass."

    return ControlEvaluation(
        control_id=control.control_id, title=control.title,
        domain=control.domain.value, priority=control.priority.value,
        status=status, blocking=blocking, rationale=rationale,
        open_finding_ids=[f.id for f in open_findings],
        missing_evidence_types=[m.value for m in missing],
        failed_evals=sorted(set(failed_evals)),
        related_runtime_events=related_events,
    )


def _eval_relates_to_control(eval_type: EvalType, control: Control) -> bool:
    """Heuristic mapping of eval types to controls based on control_id."""
    m: dict[EvalType, set[str]] = {
        EvalType.PII_LEAKAGE: {"AI-001", "AI-002", "AI-019"},
        EvalType.PROMPT_INJECTION: {"AI-003", "AI-006", "AI-020"},
        EvalType.JAILBREAK: {"AI-003", "AI-006", "AI-020"},
        EvalType.TOOL_AUTHORIZATION: {"AI-005", "AI-006", "AI-023"},
        EvalType.RAG_GROUNDING: {"AI-004", "AI-021"},
        EvalType.HALLUCINATION: {"AI-022"},
        EvalType.BIAS: set(),
        EvalType.SANCTIONS_SCREENING: {"AI-007"},
        EvalType.REGULATORY_KNOWLEDGE: {"AI-007", "AI-008"},
        EvalType.FACTUALITY: {"AI-008", "AI-022"},
        EvalType.GROUNDEDNESS: {"AI-021", "AI-022"},
        EvalType.TOXICITY: {"AI-002"},
        EvalType.REFUSAL: {"AI-003"},
    }
    return control.control_id in m.get(eval_type, set())


def _event_relates_to_control(event: RuntimeEvent, control: Control) -> bool:
    from domain.models import RuntimeEventType as RT
    m: dict[RT, set[str]] = {
        RT.PROMPT_INJECTION_BLOCKED: {"AI-003", "AI-006", "AI-020"},
        RT.PII_LEAK_BLOCKED: {"AI-001", "AI-002", "AI-019"},
        RT.UNAUTHORIZED_TOOL_CALL: {"AI-005", "AI-006", "AI-023"},
        RT.RATE_LIMIT_TRIPPED: {"AI-028"},
        RT.JAILBREAK_ATTEMPT: {"AI-003"},
        RT.SANCTIONS_HIT: {"AI-007"},
        RT.HITL_ESCALATION: {"AI-007"},
        RT.POLICY_VIOLATION: {"AI-024"},
    }
    return control.control_id in m.get(event.event_type, set())


# ===========================================================================
# 4. Findings generation for failed controls
# ===========================================================================

def generate_findings(
    system: AISystem, failed_controls: list[Control],
) -> list[GeneratedFinding]:
    """One finding per failed control. Severity inherits from control priority."""
    severity_map = {Priority.P0: Severity.CRITICAL, Priority.P1: Severity.HIGH,
                    Priority.P2: Severity.MEDIUM, Priority.P3: Severity.LOW}
    impact_map = {Priority.P0: ReleaseImpact.BLOCKS_RELEASE,
                  Priority.P1: ReleaseImpact.BLOCKS_RELEASE,
                  Priority.P2: ReleaseImpact.CONDITIONAL,
                  Priority.P3: ReleaseImpact.NONE}
    findings: list[GeneratedFinding] = []
    for c in failed_controls:
        findings.append(GeneratedFinding(
            id=f"AUTO-{uuid4().hex[:8].upper()}",
            ai_system_id=system.id,
            control_id=c.control_id,
            title=f"{c.title} — failed evaluation",
            description=(
                f"Control {c.control_id} requires: {c.requirement} "
                f"Failure impact: {c.failure_impact}"
            ),
            severity=severity_map[c.priority].value,
            framework_mappings=[asdict(_fm_to_dict(fm)) if False else
                                {"framework": fm.framework.value, "clause": fm.clause}
                                for fm in c.framework_mappings],
            owner=c.recommended_owner.value,
            release_impact=impact_map[c.priority].value,
            remediation=f"Satisfy pass criteria: {c.pass_criteria}",
        ))
    return findings


def _fm_to_dict(fm: FrameworkMapping) -> dict:  # kept for future
    return {"framework": fm.framework.value, "clause": fm.clause}


# ===========================================================================
# 5. Residual-risk scoring
# ===========================================================================

# Look-up tables for scoring factors (deterministic, transparent)
_EXPOSURE_BY_USER_POP = {
    "internal": 0.3, "third-party": 0.6, "regulator-facing": 0.5,
    "customer-facing": 1.0,
}
_AUTONOMY_FACTOR = {
    AutonomyLevel.ADVISORY: 0.2,
    AutonomyLevel.TRIAGE: 0.4,
    AutonomyLevel.DOCUMENT_GENERATION: 0.5,
    AutonomyLevel.TOOL_USING_HITL: 0.7,
    AutonomyLevel.TOOL_USING_AUTONOMOUS: 1.0,
    AutonomyLevel.FULLY_AUTONOMOUS: 1.0,
}
_DATA_FACTOR = {
    DataClass.PUBLIC: 0.1,
    DataClass.MARKET_DATA: 0.2,
    DataClass.CUSTOMER_NAMES: 0.5,
    DataClass.PII: 1.0, DataClass.NPI: 1.0, DataClass.PCI: 1.0,
    DataClass.PHI: 1.0, DataClass.BIOMETRIC: 1.0,
    DataClass.ACCOUNT_NUMBERS: 0.9,
    DataClass.AUTHENTICATION_DATA: 1.0,
    DataClass.TRANSACTION_DATA: 0.8,
    DataClass.SAR_DATA: 0.9, DataClass.KYC_DOCUMENTS: 0.9,
    DataClass.FINANCIAL_STATEMENTS: 0.7,
    DataClass.SANCTIONS_LISTS: 0.6,
    DataClass.INTERNAL_CREDIT: 0.7,
}


def calculate_residual_risk(
    system: AISystem,
    findings: list[Finding] | list[GeneratedFinding],
    eval_results: list[EvalResult],
) -> ResidualRiskScore:
    """Residual = Likelihood × Impact × Exposure × Autonomy × Data × Gap-Modifier."""

    # Likelihood — based on failed evals + open finding density
    failed = sum(1 for e in eval_results if e.status in (EvalStatus.FAIL, EvalStatus.WARN))
    total_evals = len(eval_results) or 1
    open_crit = sum(1 for f in findings if _fld(f, "severity") == "CRITICAL")
    open_high = sum(1 for f in findings if _fld(f, "severity") == "HIGH")
    likelihood = min(1.0, 0.2 + 0.5 * (failed / total_evals) + 0.15 * open_crit + 0.05 * open_high)

    # Impact — customer/regulatory exposure
    impact_table = {
        CustomerImpact.NONE: 0.2, CustomerImpact.INDIRECT: 0.5,
        CustomerImpact.DIRECT: 0.8, CustomerImpact.DIRECT_FINANCIAL: 1.0,
    }
    impact = impact_table[system.customer_impact]
    # Regulatory uplift
    if _influences_fs(system):
        impact = min(1.0, impact + 0.1)

    # Exposure — user population
    exposure = _EXPOSURE_BY_USER_POP.get(system.user_population.lower(), 0.5)

    # Autonomy
    autonomy = _AUTONOMY_FACTOR[system.autonomy_level]

    # Data sensitivity — most sensitive class present
    data_sensitivity = max(
        (_DATA_FACTOR.get(d, 0.3) for d in system.data_classes), default=0.1,
    )

    # Control gap modifier
    applicable_p0_p1 = [c for c in get_controls_for_ai_system(system)
                        if c.priority in (Priority.P0, Priority.P1)]
    failed_critical = sum(
        1 for c in applicable_p0_p1
        if any(_fld(f, "control_id") == c.control_id and _fld(f, "severity") in ("CRITICAL", "HIGH")
               for f in findings)
    )
    gap_modifier = min(2.0, 1.0 + 0.15 * failed_critical)

    factors = RiskFactors(
        likelihood=round(likelihood, 3),
        impact=round(impact, 3),
        exposure=round(exposure, 3),
        autonomy=round(autonomy, 3),
        data_sensitivity=round(data_sensitivity, 3),
        control_gap_modifier=round(gap_modifier, 3),
    )

    raw = factors.raw_score
    # Normalize: max realistic raw is 2.0 (all factors 1.0 × gap 2.0). Scale to 100.
    normalized = round(min(100.0, raw / 2.0 * 100.0), 1)

    if raw >= 1.0:
        level = RiskLevel.CRITICAL
    elif raw >= 0.6:
        level = RiskLevel.HIGH
    elif raw >= 0.3:
        level = RiskLevel.MEDIUM
    else:
        level = RiskLevel.LOW

    explanation = [
        f"Likelihood {factors.likelihood} = baseline 0.20 + 0.50·(failed/total evals = {failed}/{total_evals}) + 0.15·CRIT({open_crit}) + 0.05·HIGH({open_high}).",
        f"Impact {factors.impact} from customer_impact={system.customer_impact.value}" + (" + 0.10 regulatory uplift" if _influences_fs(system) else ""),
        f"Exposure {factors.exposure} from user_population={system.user_population}.",
        f"Autonomy {factors.autonomy} from autonomy_level={system.autonomy_level.value}.",
        f"Data sensitivity {factors.data_sensitivity} = max class factor across {[d.value for d in system.data_classes]}.",
        f"Control gap modifier {factors.control_gap_modifier} = 1.0 + 0.15·{failed_critical} (failed P0/P1 controls).",
    ]

    return ResidualRiskScore(
        factors=factors, raw_score=round(raw, 3),
        normalized_score=normalized, level=level, explanation=explanation,
    )


def _fld(obj, name: str):
    """Read a field by name from either a dataclass or Pydantic model."""
    if hasattr(obj, name):
        v = getattr(obj, name)
        # Enums -> value
        return v.value if hasattr(v, "value") and not isinstance(v, str) else v
    return None


# ===========================================================================
# 6. Framework coverage
# ===========================================================================

def calculate_framework_coverage(
    evaluations: list[ControlEvaluation],
) -> list[FrameworkCoverage]:
    """Aggregate per-control results into per-framework coverage rows.

    Each returned :class:`FrameworkCoverage` includes a ``framework_refs`` list
    with the distinct ``{framework, clause}`` pairs sourced from the controls
    mapped to that framework, giving downstream consumers direct links to the
    regulatory/standard clauses being measured.
    """
    # Build map control_id -> list of (framework, clause) pairs and framework names
    cid_to_frameworks: dict[str, list[str]] = {}
    cid_to_refs: dict[str, list[dict]] = {}
    for c in CONTROLS:
        cid_to_frameworks[c.control_id] = sorted({fm.framework.value for fm in c.framework_mappings})
        cid_to_refs[c.control_id] = [
            {"framework": fm.framework.value, "clause": fm.clause}
            for fm in c.framework_mappings
        ]

    per_fw: dict[str, dict] = {}
    for ev in evaluations:
        if ev.status == ControlStatus.NOT_APPLICABLE:
            continue
        for fw in cid_to_frameworks.get(ev.control_id, []):
            row = per_fw.setdefault(fw, {"applicable": 0, "passing": 0, "failing": 0, "refs": []})
            row["applicable"] += 1
            if ev.status == ControlStatus.PASS:
                row["passing"] += 1
            elif ev.status in (ControlStatus.FAIL, ControlStatus.NO_EVIDENCE):
                row["failing"] += 1
            # Accumulate clause refs for this framework from this control
            for ref in cid_to_refs.get(ev.control_id, []):
                if ref["framework"] == fw:
                    row["refs"].append(ref)

    rows = []
    for fw, r in per_fw.items():
        cov = (r["passing"] / r["applicable"] * 100.0) if r["applicable"] else 0.0
        # Deduplicate refs by clause
        seen_clauses: set[str] = set()
        deduped_refs: list[dict] = []
        for ref in r["refs"]:
            key = ref["clause"]
            if key not in seen_clauses:
                seen_clauses.add(key)
                deduped_refs.append(ref)
        rows.append(FrameworkCoverage(
            framework=fw,
            controls_applicable=r["applicable"],
            controls_passing=r["passing"],
            controls_failing=r["failing"],
            coverage_pct=round(cov, 1),
            framework_refs=deduped_refs,
        ))
    rows.sort(key=lambda r: r.framework)
    return rows


def evidence_completeness(
    system: AISystem,
    evidence: list[Evidence],
    required_controls: list[Control],
) -> float:
    """Fraction of required evidence types present across all required controls."""
    required_types: set[str] = set()
    for c in required_controls:
        for et in c.evidence_required:
            required_types.add(et.value)
    if not required_types:
        return 1.0
    present_types = {e.evidence_type.value for e in evidence}
    return round(len(required_types & present_types) / len(required_types), 3)


# ===========================================================================
# 7. Release recommendation rules
# ===========================================================================

# Hard architectural policy: certain shapes are auto-rejected
def _violates_hard_policy(system: AISystem) -> tuple[bool, str | None]:
    if system.autonomy_level in (AutonomyLevel.TOOL_USING_AUTONOMOUS,
                                  AutonomyLevel.FULLY_AUTONOMOUS):
        fs_payment_reg = (RegulatoryExposure.GLBA in system.regulatory_exposure
                          or RegulatoryExposure.OFAC in system.regulatory_exposure)
        side_effects = any(t.side_effect for t in system.tools)
        hitl_present = "required" in (system.human_oversight or "").lower()
        if fs_payment_reg and side_effects and not hitl_present:
            return True, (
                "Autonomous tool execution on a regulated FS workflow without a "
                "human approval gate. Architectural policy violation."
            )
    return False, None


def generate_release_recommendation(
    system: AISystem,
    findings: list[Finding] | list[GeneratedFinding],
    release_gates: list[ReleaseGate],
    evidence_completeness_pct: float,
    eval_results: list[EvalResult] | None = None,
) -> ReleaseRecommendation:
    """Apply the decision rules in priority order. First match wins."""

    # R-Rej — hard policy violation
    violates, why = _violates_hard_policy(system)
    if violates:
        return ReleaseRecommendation(
            decision=ReleaseDecision.REJECT,
            rule_fired="R-Reject-HardPolicy",
            rationale=f"REJECT: {why}",
        )

    # Findings buckets
    open_p0 = [f for f in findings if _fld(f, "severity") == "CRITICAL"
               and _fld(f, "status") in (None, "OPEN", "IN_PROGRESS")]
    open_p1 = [f for f in findings if _fld(f, "severity") == "HIGH"
               and _fld(f, "status") in (None, "OPEN", "IN_PROGRESS")]

    # R-Hold-P0
    if open_p0:
        return ReleaseRecommendation(
            decision=ReleaseDecision.HOLD,
            rule_fired="R-Hold-P0-Open",
            rationale=f"HOLD: {len(open_p0)} open P0/CRITICAL finding(s) — production release blocked until remediation verified.",
        )

    # Eval-driven holds — for each eval type, use the LATEST run_at so newer
    # connector results override stale seed evals deterministically.
    evals = eval_results or []
    latest_by_type: dict[EvalType, EvalResult] = {}
    for e in evals:
        cur = latest_by_type.get(e.eval_type)
        if cur is None or e.run_at > cur.run_at:
            latest_by_type[e.eval_type] = e

    pii_eval = latest_by_type.get(EvalType.PII_LEAKAGE)
    if pii_eval and pii_eval.status == EvalStatus.FAIL:
        return ReleaseRecommendation(
            decision=ReleaseDecision.HOLD,
            rule_fired="R-Hold-PII-Eval",
            rationale=f"HOLD: PII leakage eval failed (score {pii_eval.score} < threshold {pii_eval.threshold}).",
        )

    tool_auth_eval = latest_by_type.get(EvalType.TOOL_AUTHORIZATION)
    if tool_auth_eval and tool_auth_eval.status == EvalStatus.FAIL:
        return ReleaseRecommendation(
            decision=ReleaseDecision.HOLD,
            rule_fired="R-Hold-UnauthorizedToolCall",
            rationale=f"HOLD: Unauthorized tool calls detected in eval (score {tool_auth_eval.score} < threshold {tool_auth_eval.threshold}).",
        )

    pi_eval = latest_by_type.get(EvalType.PROMPT_INJECTION)
    if pi_eval and pi_eval.score < 0.95:
        return ReleaseRecommendation(
            decision=ReleaseDecision.HOLD,
            rule_fired="R-Hold-PromptInjection-Low",
            rationale=f"HOLD: Prompt injection resistance {pi_eval.score:.2%} < 95% threshold.",
        )

    # Conditional pilot: only P1/P2 remain AND HITL is present
    hitl_present = "required" in (system.human_oversight or "").lower()
    if open_p1 and hitl_present:
        return ReleaseRecommendation(
            decision=ReleaseDecision.CONDITIONAL_PILOT,
            rule_fired="R-Conditional-P1-with-HITL",
            rationale=(
                f"CONDITIONAL PILOT: {len(open_p1)} P1 finding(s) remain; "
                "HITL gate is in place. Pilot at limited scope while remediation continues."
            ),
            conditions=[
                f"Remediate P1: {_fld(f, 'title') or 'finding'}" for f in open_p1[:5]
            ] + [
                "Weekly eval re-run during pilot",
                "Mandatory HITL on all high-risk actions",
            ],
        )

    # Approved pilot — no P0/P1 blockers and evidence >= 85%
    if not open_p0 and not open_p1 and evidence_completeness_pct >= 0.85:
        if evidence_completeness_pct >= 0.95:
            return ReleaseRecommendation(
                decision=ReleaseDecision.APPROVED,
                rule_fired="R-Approved-Production",
                rationale=(
                    f"APPROVED for PRODUCTION: no P0/P1 blockers; "
                    f"evidence completeness {evidence_completeness_pct:.0%} >= 95%."
                ),
            )
        return ReleaseRecommendation(
            decision=ReleaseDecision.APPROVED,
            rule_fired="R-Approved-Pilot",
            rationale=(
                f"APPROVED for PILOT: no P0/P1 blockers; "
                f"evidence completeness {evidence_completeness_pct:.0%} >= 85%."
            ),
            conditions=[
                "Promote to production only after evidence completeness >= 95%.",
            ],
        )

    # Default catch-all — conditional pilot with caveat
    return ReleaseRecommendation(
        decision=ReleaseDecision.CONDITIONAL_PILOT,
        rule_fired="R-Conditional-Default",
        rationale=(
            "CONDITIONAL PILOT: no P0 blockers but evidence completeness "
            f"{evidence_completeness_pct:.0%} below pilot threshold or open P1 findings. "
            "Operate at limited scope until coverage improves."
        ),
        conditions=[
            "Close evidence gaps to >= 85% before broader rollout.",
            "Re-run eval pack before next assessment cycle.",
        ],
    )


# ===========================================================================
# 8. Orchestrator
# ===========================================================================

def run_assessment(ai_system_id: str) -> AssessmentReport:
    """Run the full assessment pipeline end-to-end against repository data."""
    system = repository.get_ai_system(ai_system_id)
    if system is None:
        raise ValueError(f"AI system not found: {ai_system_id}")

    findings = repository.findings_for(ai_system_id)
    evidence = repository.evidence_for(ai_system_id)
    eval_results = repository.eval_results_for(ai_system_id)
    runtime_events = repository.runtime_events_for(ai_system_id)
    release_gates = repository.release_gates_for(ai_system_id)

    # 1. Classify inherent risk
    inherent = classify_risk(system)

    # 2. Required controls
    required = apply_required_controls(system)

    # 3+4+5+6. Per-control evaluation
    all_applicable = get_controls_for_ai_system(system)
    evaluations = [
        evaluate_control(c, system, evidence, eval_results, runtime_events)
        for c in all_applicable
    ]

    failed_controls = [
        next(c for c in CONTROLS if c.control_id == ev.control_id)
        for ev in evaluations
        if ev.status in (ControlStatus.FAIL, ControlStatus.NO_EVIDENCE)
    ]

    # 7. Generated findings for failed controls
    generated = generate_findings(system, failed_controls)

    # 8. Residual risk
    residual = calculate_residual_risk(system, list(findings) + list(generated), eval_results)

    # 9. Framework coverage
    framework_cov = calculate_framework_coverage(evaluations)

    # Evidence completeness vs required controls
    ev_complete = evidence_completeness(system, evidence, required)

    # 10. Release recommendation — driven by PERSISTED findings only. The
    # `generated` findings are derivative of failed controls; folding them in
    # would re-trip P0/P1 holds every run regardless of workflow state. Evidence
    # gaps already surface via `ev_complete`.
    recommendation = generate_release_recommendation(
        system, list(findings), release_gates, ev_complete, eval_results,
    )

    # Overall score: passing applicable / total applicable * 100, weighted by priority
    weights = {Priority.P0: 3.0, Priority.P1: 2.0, Priority.P2: 1.0, Priority.P3: 0.5}
    cid_to_priority = {c.control_id: c.priority for c in CONTROLS}
    earned = 0.0
    possible = 0.0
    for ev in evaluations:
        if ev.status == ControlStatus.NOT_APPLICABLE:
            continue
        w = weights.get(cid_to_priority.get(ev.control_id, Priority.P2), 1.0)
        possible += w
        if ev.status == ControlStatus.PASS:
            earned += w
        elif ev.status == ControlStatus.PARTIAL:
            earned += w * 0.5
    overall = round(earned / possible * 100.0, 1) if possible else 0.0

    required_remediation = [
        f"{f.control_id} — {f.title}" for f in generated[:10]
    ]

    return AssessmentReport(
        ai_system_id=ai_system_id,
        ai_system_name=system.name,
        generated_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        overall_score=overall,
        inherent_risk=inherent.risk_level.value,
        inherent_risk_rules=inherent.rules_fired,
        residual_risk=residual,
        release_recommendation=recommendation,
        control_evaluations=evaluations,
        failed_controls=[c.control_id for c in failed_controls],
        findings=generated,
        required_remediation=required_remediation,
        framework_coverage=framework_cov,
        evidence_completeness=ev_complete,
    )


__all__ = [
    "run_assessment", "classify_risk", "apply_required_controls",
    "evaluate_control", "generate_findings", "calculate_residual_risk",
    "calculate_framework_coverage", "evidence_completeness",
    "generate_release_recommendation",
    "ControlStatus", "ControlEvaluation", "GeneratedFinding",
    "RiskFactors", "ResidualRiskScore", "FrameworkCoverage",
    "ReleaseRecommendation", "AssessmentReport",
]
