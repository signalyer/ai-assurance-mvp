"""Executive + audit-view report builders.

Six reports — one portfolio-wide (Executive AI Risk) and five per-system. Each
builder returns a structured dict so it can be rendered, exported as JSON, or
flattened to CSV / a print-ready HTML view.

All builders are PURE — they read through repository + engines and return the
report dict. Persistence is the caller's job.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from enum import Enum

from domain import repository, seed
from domain.assessment_engine import run_assessment
from domain.release_gate_engine import evaluate_gates, list_exceptions
from domain.framework_coverage import framework_overview
from domain.findings_workflow import list_findings
from domain.evidence_repository import (
    completeness_by_ai_system, completeness_by_framework,
    completeness_by_control_domain, list_evidence_sectioned,
)
from domain.models import (
    AISystem, FrameworkName, ReleaseDecision, RiskLevel,
    FindingStatus, ApprovalDecision, WaiverStatus,
)


# ===========================================================================
# Helpers
# ===========================================================================

def _ser(o):
    if is_dataclass(o):
        return {k: _ser(v) for k, v in asdict(o).items()}
    if isinstance(o, Enum):
        return o.value
    if isinstance(o, datetime):
        return o.isoformat() + ("Z" if o.tzinfo is None else "")
    if hasattr(o, "model_dump"):
        return _ser(o.model_dump())
    if isinstance(o, (list, tuple)):
        return [_ser(v) for v in o]
    if isinstance(o, dict):
        return {k: _ser(v) for k, v in o.items()}
    return o


def _system_or_raise(system_id: str) -> AISystem:
    s = repository.get_ai_system(system_id)
    if s is None:
        raise ValueError(f"AI system not found: {system_id}")
    return s


def _system_summary(s: AISystem) -> dict:
    return {
        "id": s.id, "name": s.name, "description": s.description,
        "domain": s.domain,
        "business_owner": s.business_owner,
        "technical_owner": s.technical_owner,
        "cloud_provider": s.cloud_provider.value,
        "model_provider": s.model_provider,
        "models_used": s.models_used,
        "autonomy_level": s.autonomy_level.value,
        "user_population": s.user_population,
        "customer_impact": s.customer_impact.value,
        "regulatory_exposure": [r.value for r in s.regulatory_exposure],
        "data_classes": [d.value for d in s.data_classes],
        "rag_enabled": s.rag_enabled,
        "tool_count": len(s.tools),
        "side_effect_tool_count": sum(1 for t in s.tools if t.side_effect),
        "aws_services": s.aws_services,
        "runtime_status": s.runtime_status.value,
        "release_decision": s.release_decision.value,
        "inherent_risk": s.inherent_risk.value,
        "residual_risk": s.residual_risk.value,
        "human_oversight": s.human_oversight,
        "data_residency": s.data_residency,
    }


def _approval_history(system_id: str) -> list[dict]:
    rows = []
    for a in seed.approvals_for(system_id):
        rows.append({
            "id": a.id, "approver": a.approver, "role": a.role.value,
            "decision": a.decision.value, "comments": a.comments,
            "conditions": a.conditions,
            "assessment_id": a.assessment_id,
            "timestamp": a.timestamp.isoformat(),
        })
    rows.sort(key=lambda r: r["timestamp"], reverse=True)
    return rows


def _exception_history(system_id: str) -> list[dict]:
    rows: list[dict] = []
    for w in seed.waivers_for(system_id):
        rows.append({
            "id": w.id, "control_id": w.control_id, "reason": w.reason,
            "risk_acceptor": w.risk_acceptor,
            "role": w.risk_acceptor_role.value,
            "expiration_date": w.expiration_date.isoformat(),
            "status": w.status.value,
            "compensating_controls": w.compensating_controls,
            "created_at": w.created_at.isoformat(),
            "source": "seed",
        })
    # Demo / gate-engine exceptions (e.g., WV-KYC-*) come through list_exceptions
    for ex in list_exceptions(system_id):
        rows.append({
            "id": ex.id, "control_id": getattr(ex, "control_id", None),
            "reason": getattr(ex, "reason", None),
            "risk_acceptor": getattr(ex, "risk_acceptor", None),
            "role": getattr(getattr(ex, "risk_acceptor_role", None), "value", None),
            "expiration_date": getattr(ex, "expiration_date", None) and ex.expiration_date.isoformat(),
            "status": getattr(getattr(ex, "status", None), "value", None) or "ACTIVE",
            "compensating_controls": getattr(ex, "compensating_controls", []) or [],
            "created_at": None,
            "source": "gate-engine",
            "gate_id": getattr(ex, "gate_id", None),
        })
    return rows


def _eval_rows(system_id: str) -> list[dict]:
    rows = []
    for e in repository.eval_results_for(system_id):
        rows.append({
            "id": e.id, "eval_type": e.eval_type.value,
            "score": e.score, "threshold": e.threshold,
            "status": e.status.value, "tool_source": e.tool_source.value,
            "test_count": e.test_count, "failed_count": e.failed_count,
            "release_impact": e.release_impact.value,
            "control_mappings": e.control_mappings,
            "framework_mappings": [{"framework": fm.framework.value, "clause": fm.clause}
                                    for fm in e.framework_mappings],
            "run_at": e.run_at.isoformat(),
            "notes": e.notes,
        })
    rows.sort(key=lambda r: r["run_at"], reverse=True)
    return rows


def _open_findings(system_id: str) -> list[dict]:
    fs = list_findings(scope=system_id)
    rows = []
    for f in fs:
        if f.status in ("OPEN", "IN_PROGRESS"):
            rows.append({
                "id": f.id, "title": f.title, "severity": f.severity,
                "priority": f.priority, "status": f.status,
                "control_id": f.control_id, "owner": f.owner,
                "sla_due_date": f.sla_due_date,
                "sla_breached": f.sla_breached,
                "release_impact": f.release_impact,
                "framework_mappings": f.framework_mappings,
                "remediation": f.remediation_guidance,
            })
    return rows


def _remediation_plan(system_id: str) -> list[dict]:
    """Open findings + their remediation steps, sorted by severity then SLA."""
    sev_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}
    items = _open_findings(system_id)
    items.sort(key=lambda r: (sev_order.get(r["severity"], 9), r["sla_due_date"]))
    return [
        {
            "finding_id": r["id"], "title": r["title"], "severity": r["severity"],
            "control_id": r["control_id"], "owner": r["owner"],
            "sla_due": r["sla_due_date"], "sla_breached": r["sla_breached"],
            "release_impact": r["release_impact"],
            "remediation": r["remediation"],
        }
        for r in items
    ]


# ===========================================================================
# 1. Executive AI Risk Report — portfolio-wide
# ===========================================================================

_DECISION_RANK = {
    ReleaseDecision.REJECT.value: 0,
    ReleaseDecision.HOLD.value: 1,
    ReleaseDecision.CONDITIONAL_PILOT.value: 2,
    ReleaseDecision.NOT_ASSESSED.value: 3,
    ReleaseDecision.APPROVED.value: 4,
}

_RISK_RANK = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}


def executive_report() -> dict:
    """Portfolio-wide AI risk posture for CISO / CRO / Board / Audit / MRM."""
    systems = repository.list_ai_systems()
    rows: list[dict] = []
    portfolio = {
        "ai_systems_total": 0,
        "in_production": 0,
        "in_pilot": 0,
        "in_staging_or_dev": 0,
        "approved": 0, "conditional_pilot": 0, "hold": 0, "reject": 0,
        "open_critical": 0, "open_high": 0,
        "sla_breached": 0,
        "active_waivers": 0,
        "avg_evidence_completeness": 0.0,
        "avg_overall_score": 0.0,
    }
    completeness_acc = 0.0
    score_acc = 0.0

    framework_rollup: dict[str, dict[str, int]] = {}
    waiver_count_by_role: dict[str, int] = {}

    for s in systems:
        # Run the engine to get an authoritative score / decision
        try:
            report = run_assessment(s.id)
            score = report.overall_score
            decision = report.release_recommendation.decision.value
            rule_fired = report.release_recommendation.rule_fired
            residual_risk = report.residual_risk.level.value
            ev_complete = report.evidence_completeness
            framework_cov = report.framework_coverage
        except Exception as e:                                            # noqa: BLE001
            score = 0.0; decision = "NOT_ASSESSED"; rule_fired = f"engine_error: {e}"
            residual_risk = s.residual_risk.value; ev_complete = 0.0
            framework_cov = []

        findings = list_findings(scope=s.id)
        open_crit = sum(1 for f in findings if f.severity == "CRITICAL"
                        and f.status in ("OPEN", "IN_PROGRESS"))
        open_high = sum(1 for f in findings if f.severity == "HIGH"
                        and f.status in ("OPEN", "IN_PROGRESS"))
        sla_breached = sum(1 for f in findings if f.sla_breached
                           and f.status in ("OPEN", "IN_PROGRESS"))
        waivers = seed.waivers_for(s.id)
        active_waivers = sum(1 for w in waivers if w.status == WaiverStatus.APPROVED)

        rows.append({
            "system_id": s.id, "name": s.name, "domain": s.domain,
            "business_owner": s.business_owner,
            "technical_owner": s.technical_owner,
            "runtime_status": s.runtime_status.value,
            "regulatory_exposure": [r.value for r in s.regulatory_exposure],
            "inherent_risk": s.inherent_risk.value,
            "residual_risk": residual_risk,
            "release_decision": decision,
            "rule_fired": rule_fired,
            "overall_score": score,
            "evidence_completeness": ev_complete,
            "open_critical": open_crit,
            "open_high": open_high,
            "sla_breached": sla_breached,
            "active_waivers": active_waivers,
            "autonomy_level": s.autonomy_level.value,
            "customer_impact": s.customer_impact.value,
        })

        # Portfolio tallies
        portfolio["ai_systems_total"] += 1
        rs = s.runtime_status.value
        if rs == "PRODUCTION": portfolio["in_production"] += 1
        elif rs == "PILOT":    portfolio["in_pilot"] += 1
        else:                   portfolio["in_staging_or_dev"] += 1

        d = decision.lower()
        if d == "approved":           portfolio["approved"] += 1
        elif d == "conditional_pilot": portfolio["conditional_pilot"] += 1
        elif d == "hold":             portfolio["hold"] += 1
        elif d == "reject":           portfolio["reject"] += 1

        portfolio["open_critical"] += open_crit
        portfolio["open_high"] += open_high
        portfolio["sla_breached"] += sla_breached
        portfolio["active_waivers"] += active_waivers
        completeness_acc += ev_complete
        score_acc += score

        for fc in framework_cov:
            r = framework_rollup.setdefault(fc.framework, {"applicable": 0, "passing": 0, "failing": 0})
            r["applicable"] += fc.controls_applicable
            r["passing"] += fc.controls_passing
            r["failing"] += fc.controls_failing

        for w in waivers:
            if w.status == WaiverStatus.APPROVED:
                k = w.risk_acceptor_role.value
                waiver_count_by_role[k] = waiver_count_by_role.get(k, 0) + 1

    if portfolio["ai_systems_total"]:
        portfolio["avg_evidence_completeness"] = round(
            completeness_acc / portfolio["ai_systems_total"], 3)
        portfolio["avg_overall_score"] = round(
            score_acc / portfolio["ai_systems_total"], 1)

    # Sort the system table worst-first (CRITICAL/HOLD on top)
    rows.sort(key=lambda r: (
        _DECISION_RANK.get(r["release_decision"], 9),
        _RISK_RANK.get(r["residual_risk"], 9),
        -r["open_critical"],
    ))

    # Highest-attention systems (top 3 by composite "needs CRO attention" score)
    def _attention_score(r: dict) -> float:
        return (3 * r["open_critical"]
                + 1 * r["open_high"]
                + 2 * r["sla_breached"]
                + (5 if r["release_decision"] in ("HOLD", "REJECT") else 0)
                + (2 if r["residual_risk"] in ("CRITICAL", "HIGH") else 0))
    attention = sorted(rows, key=_attention_score, reverse=True)[:3]

    framework_rollup_rows = [
        {
            "framework": fw,
            "controls_applicable": v["applicable"],
            "controls_passing": v["passing"],
            "controls_failing": v["failing"],
            "coverage_pct": round(v["passing"] / v["applicable"] * 100.0, 1)
                             if v["applicable"] else 0.0,
        }
        for fw, v in sorted(framework_rollup.items())
    ]

    return {
        "report_type": "executive_ai_risk",
        "report_title": "Executive AI Risk Report",
        "audience": ["CISO", "Chief Risk Officer", "AI Governance Board",
                     "Internal Audit", "Model Risk Management"],
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "scope": "Portfolio — all AI systems",
        "portfolio_kpis": portfolio,
        "needs_attention": [
            {
                "system_id": r["system_id"], "name": r["name"],
                "decision": r["release_decision"],
                "residual_risk": r["residual_risk"],
                "open_critical": r["open_critical"],
                "open_high": r["open_high"],
                "sla_breached": r["sla_breached"],
                "rule_fired": r["rule_fired"],
            }
            for r in attention
        ],
        "framework_rollup": framework_rollup_rows,
        "waivers_by_acceptor_role": [
            {"role": k, "count": v} for k, v in
            sorted(waiver_count_by_role.items(), key=lambda kv: -kv[1])
        ],
        "ai_systems": rows,
    }


# ===========================================================================
# 2. AI System Assessment Report
# ===========================================================================

def assessment_report(system_id: str) -> dict:
    s = _system_or_raise(system_id)
    report = run_assessment(system_id)
    framework_cov = [_ser(fc) for fc in report.framework_coverage]
    control_evals = [_ser(ce) for ce in report.control_evaluations]

    failed = [ce for ce in control_evals if ce["status"] in ("FAIL", "NO_EVIDENCE")]
    open_findings = _open_findings(system_id)

    return {
        "report_type": "ai_system_assessment",
        "report_title": f"AI System Assessment Report — {s.name}",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "system_summary": _system_summary(s),
        "risk_classification": {
            "inherent_risk": report.inherent_risk,
            "rules_fired": report.inherent_risk_rules,
            "residual_risk": _ser(report.residual_risk),
        },
        "framework_coverage": framework_cov,
        "control_evaluations": control_evals,
        "failed_controls": failed,
        "eval_results": _eval_rows(system_id),
        "release_decision": _ser(report.release_recommendation),
        "open_findings": open_findings,
        "remediation_plan": _remediation_plan(system_id),
        "evidence_completeness": report.evidence_completeness,
        "approval_history": _approval_history(system_id),
        "exception_history": _exception_history(system_id),
        "overall_score": report.overall_score,
    }


# ===========================================================================
# 3. Release Gate Report
# ===========================================================================

def release_gate_report(system_id: str, target_env: str = "PILOT") -> dict:
    s = _system_or_raise(system_id)
    report = evaluate_gates(system_id, target_environment=target_env)
    report_dict = _ser(report)
    # Normalize gate rows so the CSV/UI sees stable column names.
    gates = []
    for g in report_dict.get("gates", []):
        gates.append({
            "gate_id": g.get("gate_id"),
            "gate_name": g.get("name"),
            "status": g.get("status"),
            "blocking": g.get("blocking"),
            "failed_reason": g.get("failed_reason"),
            "evidence_pct": report_dict.get("evidence_completeness"),
            "remediation": "; ".join(g.get("remediation_required") or []),
            "mapped_controls": g.get("mapped_controls") or [],
            "mapped_frameworks": g.get("mapped_frameworks") or [],
            "exception_id": g.get("exception_id"),
        })
    return {
        "report_type": "release_gate",
        "report_title": f"Release Gate Report — {s.name}",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "system_summary": _system_summary(s),
        "target_environment": target_env,
        "release_decision": {
            "decision": report_dict.get("release_decision"),
            "rationale": report_dict.get("release_rationale"),
        },
        "totals": {
            "pass": report_dict.get("pass_count"),
            "fail": report_dict.get("fail_count"),
            "warning": report_dict.get("warning_count"),
            "blocking_failures": report_dict.get("blocking_failures"),
        },
        "evidence_completeness": report_dict.get("evidence_completeness"),
        "gates": gates,
        "open_findings": _open_findings(system_id),
        "remediation_plan": _remediation_plan(system_id),
        "eval_results": _eval_rows(system_id),
        "approval_history": _approval_history(system_id),
        "exception_history": _exception_history(system_id),
    }


# ===========================================================================
# 4. Framework Coverage Report
# ===========================================================================

# Frameworks the catalog has structured items for. (FS_OVERLAY is covered
# through individual control mappings — the framework_catalog module doesn't
# expose discrete items for it.)
_DEFAULT_FRAMEWORKS = [
    FrameworkName.NIST_AI_RMF,
    FrameworkName.NIST_AI_600_1,
    FrameworkName.OWASP_LLM_TOP10,
    FrameworkName.OWASP_AGENTIC_TOP10,
]


def _completeness_row_dict(r, *, label_field: str = "label") -> dict:
    """Normalize a CompletenessRow into the stable shape the UI expects."""
    return {
        label_field: r.label,
        "applicable_controls": r.required,
        "covered_controls": r.present,
        "completeness_pct": r.pct,
        "missing": list(r.missing or [])[:10],
    }


def framework_coverage_report(system_id: str | None = None) -> dict:
    """Framework coverage at the system or portfolio scope."""
    scope = system_id or "ALL"
    s = None
    title = "Framework Coverage Report — Portfolio"
    sys_summary = None
    if system_id:
        s = _system_or_raise(system_id)
        title = f"Framework Coverage Report — {s.name}"
        sys_summary = _system_summary(s)

    by_framework: list[dict] = []
    for fw in _DEFAULT_FRAMEWORKS:
        try:
            items = framework_overview(fw.value, scope=scope)
        except ValueError:                                                # noqa: PERF203
            continue
        avg_cov = round(sum(it.coverage_pct for it in items) / len(items), 1) if items else 0.0
        avg_ev = round(sum(it.evidence_completeness for it in items) / len(items), 3) if items else 0.0
        by_framework.append({
            "framework": fw.value,
            "items": [_ser(it) for it in items],
            "applicable_items": len(items),
            "passing_items": sum(1 for it in items if it.coverage_pct >= 100.0),
            "avg_coverage_pct": avg_cov,
            "avg_evidence_completeness": avg_ev,
        })

    # Aggregate failed controls + evidence shortfalls
    if system_id:
        ev_by_domain = [_completeness_row_dict(r, label_field="domain")
                         for r in completeness_by_control_domain(scope=system_id)]
        report = run_assessment(system_id)
        failed_controls = [ce.control_id for ce in report.control_evaluations
                           if ce.status.value in ("FAIL", "NO_EVIDENCE")]
        release_decision = _ser(report.release_recommendation)
        eval_results = _eval_rows(system_id)
        open_findings = _open_findings(system_id)
        approvals = _approval_history(system_id)
        exceptions = _exception_history(system_id)
        evidence_completeness = report.evidence_completeness
    else:
        ev_by_domain = [_completeness_row_dict(r, label_field="domain")
                         for r in completeness_by_control_domain(scope="ALL")]
        failed_controls = []
        release_decision = None
        eval_results = []
        open_findings = []
        approvals = []
        exceptions = []
        sys_rows = [_completeness_row_dict(r) for r in completeness_by_ai_system()]
        evidence_completeness = (sum(r["completeness_pct"] for r in sys_rows) / len(sys_rows) / 100.0
                                  if sys_rows else 0.0)

    return {
        "report_type": "framework_coverage",
        "report_title": title,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "system_summary": sys_summary,
        "scope": scope,
        "frameworks": by_framework,
        "evidence_completeness": evidence_completeness,
        "evidence_completeness_by_domain": ev_by_domain,
        "failed_controls": failed_controls,
        "release_decision": release_decision,
        "eval_results": eval_results,
        "open_findings": open_findings,
        "remediation_plan": _remediation_plan(system_id) if system_id else [],
        "approval_history": approvals,
        "exception_history": exceptions,
    }


# ===========================================================================
# 5. Findings & Remediation Report
# ===========================================================================

def findings_remediation_report(system_id: str) -> dict:
    s = _system_or_raise(system_id)
    fs = list_findings(scope=system_id)
    by_status: dict[str, list[dict]] = {}
    for f in fs:
        by_status.setdefault(f.status, []).append({
            "id": f.id, "title": f.title, "severity": f.severity,
            "priority": f.priority, "control_id": f.control_id,
            "owner": f.owner, "sla_due_date": f.sla_due_date,
            "sla_breached": f.sla_breached,
            "release_impact": f.release_impact,
            "framework_mappings": f.framework_mappings,
            "remediation": f.remediation_guidance,
            "discovered": f.discovered,
            "evidence_ids": f.evidence_ids,
            "timeline": f.timeline,
        })

    counts = {k: len(v) for k, v in by_status.items()}
    sev_counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "INFO": 0}
    for f in fs:
        if f.status in ("OPEN", "IN_PROGRESS"):
            sev_counts[f.severity] = sev_counts.get(f.severity, 0) + 1

    return {
        "report_type": "findings_remediation",
        "report_title": f"Findings & Remediation Report — {s.name}",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "system_summary": _system_summary(s),
        "totals": {
            "total": len(fs),
            "open_by_severity": sev_counts,
            "by_status": counts,
        },
        "open_findings": _open_findings(system_id),
        "remediation_plan": _remediation_plan(system_id),
        "findings_by_status": by_status,
        "eval_results": _eval_rows(system_id),
        "release_decision": _ser(run_assessment(system_id).release_recommendation),
        "approval_history": _approval_history(system_id),
        "exception_history": _exception_history(system_id),
    }


# ===========================================================================
# 6. Audit Evidence Report
# ===========================================================================

def audit_evidence_report(system_id: str) -> dict:
    s = _system_or_raise(system_id)
    sections_all = list_evidence_sectioned(scope=system_id)
    sections = {name: [_ser(row) for row in rows] for name, rows in sections_all.items()}
    evidence = repository.evidence_for(system_id)

    # Per-control evidence coverage
    by_control: dict[str, list[str]] = {}
    for e in evidence:
        for cid in e.linked_control_ids:
            by_control.setdefault(cid, []).append(e.id)

    by_framework_coverage = []
    for fw in _DEFAULT_FRAMEWORKS:
        try:
            row = completeness_by_framework(fw, scope=system_id)
            d = _completeness_row_dict(row, label_field="framework")
            d["framework"] = fw.value  # ensure framework name, not label
            by_framework_coverage.append(d)
        except Exception:                                                # noqa: BLE001
            continue

    by_domain = [_completeness_row_dict(r, label_field="domain")
                  for r in completeness_by_control_domain(scope=system_id)]
    sys_complete = [_completeness_row_dict(r) for r in completeness_by_ai_system()
                    if r.label.startswith(system_id)]
    overall = sys_complete[0] if sys_complete else None

    report = run_assessment(system_id)

    return {
        "report_type": "audit_evidence",
        "report_title": f"Audit Evidence Report — {s.name}",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "system_summary": _system_summary(s),
        "evidence_count": len(evidence),
        "evidence_completeness": report.evidence_completeness,
        "evidence_completeness_overall": overall,
        "completeness_by_framework": by_framework_coverage,
        "completeness_by_control_domain": by_domain,
        "evidence_by_section": sections,
        "evidence_by_control": [
            {"control_id": cid, "evidence_ids": ids}
            for cid, ids in sorted(by_control.items())
        ],
        "failed_controls": [ce.control_id for ce in report.control_evaluations
                            if ce.status.value in ("FAIL", "NO_EVIDENCE")],
        "release_decision": _ser(report.release_recommendation),
        "open_findings": _open_findings(system_id),
        "remediation_plan": _remediation_plan(system_id),
        "eval_results": _eval_rows(system_id),
        "approval_history": _approval_history(system_id),
        "exception_history": _exception_history(system_id),
    }


# ===========================================================================
# Dispatch + CSV flatten
# ===========================================================================

BUILDERS = {
    "executive": lambda system_id=None: executive_report(),
    "assessment": assessment_report,
    "release_gate": release_gate_report,
    "framework_coverage": framework_coverage_report,
    "findings": findings_remediation_report,
    "evidence": audit_evidence_report,
}


def build_report(report_type: str, system_id: str | None = None) -> dict:
    if report_type not in BUILDERS:
        raise ValueError(f"Unknown report type: {report_type}")
    if report_type == "executive":
        return BUILDERS[report_type]()
    if report_type == "framework_coverage":
        return framework_coverage_report(system_id)
    if not system_id:
        raise ValueError(f"{report_type} report requires system_id")
    return BUILDERS[report_type](system_id)


# Primary CSV table per report (column order)
CSV_TABLE = {
    "executive": ("ai_systems", [
        "system_id", "name", "domain", "business_owner", "technical_owner",
        "runtime_status", "release_decision", "rule_fired",
        "inherent_risk", "residual_risk", "overall_score",
        "evidence_completeness", "open_critical", "open_high",
        "sla_breached", "active_waivers", "autonomy_level", "customer_impact",
    ]),
    "assessment": ("control_evaluations", [
        "control_id", "title", "domain", "priority", "status", "blocking",
        "rationale", "missing_evidence_types", "failed_evals", "related_runtime_events",
    ]),
    "release_gate": ("gates", [
        "gate_id", "gate_name", "status", "failed_reason",
        "blocking", "evidence_pct", "remediation",
    ]),
    "framework_coverage": ("frameworks", ["framework", "applicable_items", "passing_items"]),
    "findings": ("open_findings", [
        "id", "title", "severity", "priority", "status", "control_id",
        "owner", "sla_due_date", "sla_breached", "release_impact", "remediation",
    ]),
    "evidence": ("evidence_by_control", ["control_id", "evidence_ids"]),
}


def to_csv_table(report: dict, report_type: str) -> tuple[list[str], list[list[str]]]:
    """Return (header, rows) for the primary CSV table of a report."""
    key, cols = CSV_TABLE[report_type]
    if report_type == "release_gate":
        data = report.get("gates", [])
    elif report_type == "framework_coverage":
        data = report.get("frameworks", [])
    else:
        data = report.get(key, [])

    out_rows: list[list[str]] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        flat = []
        for c in cols:
            v = row.get(c)
            if isinstance(v, (list, dict)):
                v = "; ".join(str(x) for x in v) if isinstance(v, list) else str(v)
            flat.append("" if v is None else str(v))
        out_rows.append(flat)
    return cols, out_rows


__all__ = [
    "executive_report", "assessment_report", "release_gate_report",
    "framework_coverage_report", "findings_remediation_report",
    "audit_evidence_report",
    "BUILDERS", "build_report", "CSV_TABLE", "to_csv_table",
]
