"""AI Risk Operations notification center — feeds the topbar bell.

Ten notification categories, all derived from live data so there is no
hand-curated alert stream. Stable IDs let the UI persist 'resolved' state.

Categories:
  CRITICAL_FINDING        — open CRITICAL findings
  GATE_FAILURE            — release gates failing for a system
  RUNTIME_SECURITY        — HIGH/CRITICAL runtime events
  APPROVAL_REQUEST        — pending/deferred approvals
  EVIDENCE_GAP            — missing required evidence per control
  SLA_BREACH              — open findings past sla_due_date
  POLICY_VIOLATION        — POLICY_VIOLATION runtime events
  REASSESSMENT_REQUIRED   — high-risk systems with stale or no assessment
  FRAMEWORK_DRIFT         — frameworks falling below 70% portfolio coverage
  AWS_TELEMETRY           — AWS Macie/Security Hub/CloudTrail/GuardDuty alerts
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, date, timezone
from pathlib import Path

from domain import repository, seed
from domain.findings_workflow import list_findings
from domain.assessment_engine import run_assessment
from domain.framework_coverage import framework_overview
from domain.release_gate_engine import evaluate_gates
from domain.controls import get_required_controls
from domain.models import (
    RuntimeStatus, ApprovalDecision, WaiverStatus, AutonomyLevel,
    FrameworkName,
)


_DATA_DIR = Path(__import__("os").environ.get("DATA_ROOT") or (Path(__file__).resolve().parents[1] / "data"))
_DATA_DIR.mkdir(exist_ok=True)
RESOLVED_FILE = _DATA_DIR / "notifications_resolved.jsonl"


# ---------------------------------------------------------------------------
# Categories + severities
# ---------------------------------------------------------------------------

CATEGORIES = {
    "CRITICAL_FINDING":      "Critical Findings",
    "GATE_FAILURE":          "Release Gate Failures",
    "RUNTIME_SECURITY":      "Runtime Security Events",
    "APPROVAL_REQUEST":      "Approval Requests",
    "EVIDENCE_GAP":          "Evidence Gaps",
    "SLA_BREACH":            "SLA Breaches",
    "POLICY_VIOLATION":      "Runtime Policy Violations",
    "REASSESSMENT_REQUIRED": "Reassessment Required",
    "FRAMEWORK_DRIFT":       "Framework Coverage Drift",
    "AWS_TELEMETRY":         "AWS Telemetry Alerts",
}

# UI grouping for the filter tabs (so we don't show 10 small bubbles).
TAB_FOR_CATEGORY = {
    "CRITICAL_FINDING":      "critical",
    "GATE_FAILURE":          "release",
    "EVIDENCE_GAP":          "release",
    "SLA_BREACH":            "release",
    "REASSESSMENT_REQUIRED": "release",
    "FRAMEWORK_DRIFT":       "release",
    "RUNTIME_SECURITY":      "runtime",
    "POLICY_VIOLATION":      "runtime",
    "AWS_TELEMETRY":         "runtime",
    "APPROVAL_REQUEST":      "approvals",
}


# ---------------------------------------------------------------------------
# Resolved-state persistence
# ---------------------------------------------------------------------------

def _resolved_ids() -> set[str]:
    if not RESOLVED_FILE.exists():
        return set()
    out: set[str] = set()
    for line in RESOLVED_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
            if r.get("id"):
                out.add(r["id"])
        except json.JSONDecodeError:
            continue
    return out


def mark_resolved(notif_id: str, actor: str = "user") -> dict:
    rec = {"id": notif_id, "actor": actor, "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
    with RESOLVED_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    return rec


def clear_resolved() -> None:
    if RESOLVED_FILE.exists():
        RESOLVED_FILE.unlink()


# ---------------------------------------------------------------------------
# Notification dataclass
# ---------------------------------------------------------------------------

@dataclass
class Notification:
    id: str
    category: str
    tab: str
    severity: str                 # CRITICAL / HIGH / MEDIUM / LOW / INFO
    title: str
    detail: str
    system_id: str | None
    system_name: str | None
    framework: str | None
    control_id: str | None
    gate_id: str | None
    timestamp: str
    action_required: str
    linked_workflow: str          # URL the row navigates to
    ref_id: str | None
    resolved: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Builders — one per category
# ---------------------------------------------------------------------------

def _ts(d) -> str:
    if isinstance(d, datetime):
        return d.isoformat() + ("Z" if d.tzinfo is None else "")
    return str(d)


def _critical_findings() -> list[Notification]:
    out: list[Notification] = []
    for f in list_findings(scope="ALL"):
        if f.severity != "CRITICAL" or f.status not in ("OPEN", "IN_PROGRESS"):
            continue
        primary_fw = (f.mapped_frameworks or ["—"])[0]
        out.append(Notification(
            id=f"crit-{f.id}",
            category="CRITICAL_FINDING",
            tab=TAB_FOR_CATEGORY["CRITICAL_FINDING"],
            severity="CRITICAL",
            title=f"P0 {f.title}",
            detail=f"{f.ai_system_name} · {f.control_id or '—'} · {primary_fw}",
            system_id=f.ai_system_id,
            system_name=f.ai_system_name,
            framework=primary_fw,
            control_id=f.control_id,
            gate_id=(f.release_gates_affected or [None])[0],
            timestamp=_ts(f.discovered),
            action_required="Remediate or accept risk (waiver requires CRO/CISO).",
            linked_workflow=f"/findings?id={f.id}",
            ref_id=f.id,
        ))
    return out


def _gate_failures() -> list[Notification]:
    out: list[Notification] = []
    for s in repository.list_ai_systems():
        try:
            report = evaluate_gates(s.id, target_environment="PILOT")
        except Exception:                                                # noqa: BLE001
            continue
        for g in report.gates:
            status_v = g.status.value if hasattr(g.status, "value") else str(g.status)
            if status_v != "FAIL":
                continue
            out.append(Notification(
                id=f"gate-{s.id}-{g.gate_id}",
                category="GATE_FAILURE",
                tab=TAB_FOR_CATEGORY["GATE_FAILURE"],
                severity="CRITICAL" if g.blocking else "HIGH",
                title=f"{s.name} blocked by {g.gate_id} ({g.name})",
                detail=g.failed_reason or "Gate evaluation failed.",
                system_id=s.id,
                system_name=s.name,
                framework=(g.mapped_frameworks or [None])[0],
                control_id=(g.mapped_controls or [None])[0],
                gate_id=g.gate_id,
                timestamp=report.generated_at,
                action_required="Resolve mapped controls or approve a time-bound exception.",
                linked_workflow=f"/release-gates?system={s.id}#gate={g.gate_id}",
                ref_id=g.gate_id,
            ))
    return out


def _runtime_security() -> list[Notification]:
    out: list[Notification] = []
    sys_by_id = {s.id: s.name for s in repository.list_ai_systems()}
    for sid, sname in sys_by_id.items():
        for ev in repository.runtime_events_for(sid):
            if ev.severity.value not in ("CRITICAL", "HIGH"):
                continue
            if ev.event_type.value == "POLICY_VIOLATION":
                continue  # handled by POLICY_VIOLATION category
            if ev.event_type.value in ("MACIE_FINDING_INGESTED", "BEDROCK_INVOCATION"):
                continue  # handled by AWS_TELEMETRY
            out.append(Notification(
                id=f"rt-sec-{ev.id}",
                category="RUNTIME_SECURITY",
                tab=TAB_FOR_CATEGORY["RUNTIME_SECURITY"],
                severity=ev.severity.value,
                title=_pretty_event_title(ev),
                detail=f"{sname} · {ev.source.value} · {ev.details}",
                system_id=sid,
                system_name=sname,
                framework=ev.linked_framework,
                control_id=ev.linked_control,
                gate_id=None,
                timestamp=_ts(ev.timestamp),
                action_required=_action_for_event(ev.event_type.value, ev.action_taken),
                linked_workflow=f"/runtime?system_id={sid}",
                ref_id=ev.id,
            ))
    return out


def _approval_requests() -> list[Notification]:
    out: list[Notification] = []
    for a in seed.APPROVALS:
        if a.decision == ApprovalDecision.DEFERRED:
            sys = repository.get_ai_system(a.ai_system_id)
            sname = sys.name if sys else a.ai_system_id
            out.append(Notification(
                id=f"appr-{a.id}",
                category="APPROVAL_REQUEST",
                tab=TAB_FOR_CATEGORY["APPROVAL_REQUEST"],
                severity="HIGH",
                title=f"Approval pending: {sname}",
                detail=f"Awaiting {a.role.value} sign-off — {a.comments or 'no comments'}",
                system_id=a.ai_system_id,
                system_name=sname,
                framework=None,
                control_id=None,
                gate_id=None,
                timestamp=_ts(a.timestamp),
                action_required=f"Record approval decision (current acceptor: {a.approver}).",
                linked_workflow=f"/assessment?system={a.ai_system_id}",
                ref_id=a.id,
            ))
    return out


def _evidence_gaps() -> list[Notification]:
    """Per system, flag the highest-priority required evidence types that are
    missing for an applicable P0/P1 control."""
    out: list[Notification] = []
    for s in repository.list_ai_systems():
        try:
            report = run_assessment(s.id)
        except Exception:                                                # noqa: BLE001
            continue
        # NO_EVIDENCE controls produce one notification each, capped per system.
        no_ev = [ce for ce in report.control_evaluations
                 if ce.status.value == "NO_EVIDENCE"][:3]
        for ce in no_ev:
            missing = ", ".join(ce.missing_evidence_types[:2]) or "required evidence"
            out.append(Notification(
                id=f"evgap-{s.id}-{ce.control_id}",
                category="EVIDENCE_GAP",
                tab=TAB_FOR_CATEGORY["EVIDENCE_GAP"],
                severity="HIGH" if ce.priority == "P0" else "MEDIUM",
                title=f"Evidence gap: {ce.control_id} missing {missing}",
                detail=f"{s.name} · control {ce.control_id} ({ce.title})",
                system_id=s.id,
                system_name=s.name,
                framework=None,
                control_id=ce.control_id,
                gate_id=None,
                timestamp=report.generated_at,
                action_required="Attach the missing evidence artifact(s) or document a compensating control.",
                linked_workflow=f"/evidence?system={s.id}",
                ref_id=ce.control_id,
            ))
    return out


def _sla_breaches() -> list[Notification]:
    out: list[Notification] = []
    for f in list_findings(scope="ALL"):
        if not f.sla_breached or f.status not in ("OPEN", "IN_PROGRESS"):
            continue
        out.append(Notification(
            id=f"sla-{f.id}",
            category="SLA_BREACH",
            tab=TAB_FOR_CATEGORY["SLA_BREACH"],
            severity="HIGH",
            title=f"SLA breach: {f.id} overdue",
            detail=f"{f.ai_system_name} · {f.title}",
            system_id=f.ai_system_id,
            system_name=f.ai_system_name,
            framework=(f.mapped_frameworks or [None])[0],
            control_id=f.control_id,
            gate_id=(f.release_gates_affected or [None])[0],
            timestamp=_ts(f.sla_due_date),
            action_required=f"Owner {f.owner} — remediate or escalate to incident-management.",
            linked_workflow=f"/findings?id={f.id}",
            ref_id=f.id,
        ))
    return out


def _policy_violations() -> list[Notification]:
    out: list[Notification] = []
    sys_by_id = {s.id: s.name for s in repository.list_ai_systems()}
    for sid, sname in sys_by_id.items():
        for ev in repository.runtime_events_for(sid):
            if ev.event_type.value != "POLICY_VIOLATION":
                continue
            out.append(Notification(
                id=f"pol-{ev.id}",
                category="POLICY_VIOLATION",
                tab=TAB_FOR_CATEGORY["POLICY_VIOLATION"],
                severity=ev.severity.value if ev.severity.value != "INFO" else "MEDIUM",
                title=f"Policy violation: {ev.policy_triggered or 'policy'} on {sname}",
                detail=f"{ev.source.value} · {ev.details}",
                system_id=sid,
                system_name=sname,
                framework=ev.linked_framework,
                control_id=ev.linked_control,
                gate_id=None,
                timestamp=_ts(ev.timestamp),
                action_required="Review policy trigger and update guardrail or refine policy.",
                linked_workflow=f"/runtime?system_id={sid}",
                ref_id=ev.id,
            ))
    return out


def _reassessment_required() -> list[Notification]:
    """High-risk or pilot/production systems whose latest assessment is older
    than 30 days, or that have no assessment at all."""
    out: list[Notification] = []
    today = datetime.now(timezone.utc).date()
    high_risk_status = {RuntimeStatus.PRODUCTION, RuntimeStatus.PILOT,
                         RuntimeStatus.STAGED}
    high_risk_autonomy = {AutonomyLevel.TOOL_USING_AUTONOMOUS,
                            AutonomyLevel.TOOL_USING_HITL,
                            AutonomyLevel.FULLY_AUTONOMOUS}
    for s in repository.list_ai_systems():
        if s.runtime_status not in high_risk_status \
                and s.autonomy_level not in high_risk_autonomy:
            continue
        assessments = repository.assessments_for(s.id)
        if not assessments:
            severity = "HIGH"
            detail = f"{s.name} has no recorded assessment."
            days_label = "never assessed"
        else:
            latest = max(assessments, key=lambda a: a.started_at)
            age_days = (today - latest.started_at.date()).days
            if age_days < 30:
                continue
            severity = "HIGH" if age_days > 90 else "MEDIUM"
            detail = f"{s.name} last assessed {age_days}d ago — quarterly review overdue."
            days_label = f"{age_days}d since last assessment"

        out.append(Notification(
            id=f"reassess-{s.id}",
            category="REASSESSMENT_REQUIRED",
            tab=TAB_FOR_CATEGORY["REASSESSMENT_REQUIRED"],
            severity=severity,
            title=f"Reassessment required: {s.name}",
            detail=detail,
            system_id=s.id,
            system_name=s.name,
            framework=None,
            control_id=None,
            gate_id=None,
            timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            action_required=f"Run assessment ({days_label}).",
            linked_workflow=f"/assessment?system={s.id}",
            ref_id=s.id,
        ))
    return out


def _framework_drift() -> list[Notification]:
    """Frameworks where average item coverage across the portfolio falls
    below 70% — flagged as drift that needs governance attention."""
    out: list[Notification] = []
    THRESHOLD = 70.0
    for fw_name in ["NIST_AI_RMF", "NIST_AI_600_1", "OWASP_LLM_TOP10",
                    "OWASP_AGENTIC_TOP10"]:
        try:
            items = framework_overview(fw_name, scope="ALL")
        except ValueError:
            continue
        if not items:
            continue
        avg = sum(it.coverage_pct for it in items) / len(items)
        if avg >= THRESHOLD:
            continue
        sev = "HIGH" if avg < 50 else "MEDIUM"
        out.append(Notification(
            id=f"fwdrift-{fw_name}",
            category="FRAMEWORK_DRIFT",
            tab=TAB_FOR_CATEGORY["FRAMEWORK_DRIFT"],
            severity=sev,
            title=f"{fw_name.replace('_', ' ').title()} coverage at {round(avg, 0):.0f}%",
            detail=f"Portfolio average across {len(items)} framework items is below the {int(THRESHOLD)}% threshold.",
            system_id=None,
            system_name=None,
            framework=fw_name,
            control_id=None,
            gate_id=None,
            timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            action_required="Review failing controls + attach missing evidence per framework item.",
            linked_workflow=f"/governance?framework={fw_name}",
            ref_id=fw_name,
        ))
    return out


def _aws_telemetry() -> list[Notification]:
    out: list[Notification] = []
    aws_sources = {"AWS Macie", "AWS Security Hub", "AWS CloudTrail",
                    "AWS GuardDuty", "AWS Bedrock Guardrails"}
    sys_by_id = {s.id: s.name for s in repository.list_ai_systems()}
    for sid, sname in sys_by_id.items():
        for ev in repository.runtime_events_for(sid):
            src = ev.source.value
            if src not in aws_sources:
                continue
            sev = ev.severity.value
            if sev == "INFO":
                sev = "LOW"
            out.append(Notification(
                id=f"aws-{ev.id}",
                category="AWS_TELEMETRY",
                tab=TAB_FOR_CATEGORY["AWS_TELEMETRY"],
                severity=sev,
                title=f"{src}: {_pretty_event_title(ev)}",
                detail=f"{sname} · {ev.details}",
                system_id=sid,
                system_name=sname,
                framework=ev.linked_framework or "AWS_CONTROLS",
                control_id=ev.linked_control,
                gate_id=None,
                timestamp=_ts(ev.timestamp),
                action_required="Triage AWS finding — confirm scope, attach as evidence if relevant.",
                linked_workflow=f"/runtime?system_id={sid}",
                ref_id=ev.id,
            ))
    return out


# ---------------------------------------------------------------------------
# Pretty event helpers
# ---------------------------------------------------------------------------

_EVENT_TITLE = {
    "PROMPT_INJECTION_BLOCKED": "Prompt injection blocked",
    "PII_LEAK_BLOCKED":         "PII/NPI leak blocked",
    "UNAUTHORIZED_TOOL_CALL":   "Unauthorized tool call",
    "JAILBREAK_ATTEMPT":        "Jailbreak attempt",
    "RATE_LIMIT_TRIPPED":       "Rate limit tripped",
    "GUARDRAIL_REFUSAL":        "Guardrail refusal",
    "HALLUCINATION_DETECTED":   "Hallucination detected",
    "POLICY_VIOLATION":         "Policy violation",
    "HITL_ESCALATION":          "HITL escalation",
    "SANCTIONS_HIT":            "Sanctions hit",
    "ANOMALOUS_USAGE":          "Anomalous usage",
    "AGENT_RECURSION_EXCEEDED": "Agent recursion exceeded",
    "BEDROCK_INVOCATION":       "Bedrock invocation",
    "MACIE_FINDING_INGESTED":   "Macie finding ingested",
}


def _pretty_event_title(ev) -> str:
    return _EVENT_TITLE.get(ev.event_type.value,
                              ev.event_type.value.replace("_", " ").title())


def _action_for_event(et: str, action_taken: str) -> str:
    m = {
        "PROMPT_INJECTION_BLOCKED": "Review red-team trace; re-run prompt-injection eval.",
        "PII_LEAK_BLOCKED":         "Verify DLP rule, capture trace as evidence.",
        "UNAUTHORIZED_TOOL_CALL":   "Inspect tool-router authz log; tighten allow-list.",
        "JAILBREAK_ATTEMPT":        "Capture attack pattern; update guardrail suite.",
        "RATE_LIMIT_TRIPPED":       "Investigate session — possible runaway or DoS.",
        "HITL_ESCALATION":          "Approve or deny in queue; capture HITL evidence.",
        "SANCTIONS_HIT":            "Confirm screening rule; escalate to AML investigator.",
    }
    return m.get(et, f"Investigate ({action_taken.lower()}).")


# ---------------------------------------------------------------------------
# Top-level builder
# ---------------------------------------------------------------------------

_BUILDERS = [
    _critical_findings,
    _gate_failures,
    _runtime_security,
    _approval_requests,
    _evidence_gaps,
    _sla_breaches,
    _policy_violations,
    _reassessment_required,
    _framework_drift,
    _aws_telemetry,
]

_SEV_RANK = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}


def all_notifications() -> list[Notification]:
    resolved = _resolved_ids()
    items: list[Notification] = []
    for fn in _BUILDERS:
        try:
            for n in fn():
                n.resolved = n.id in resolved
                items.append(n)
        except Exception as e:                                            # noqa: BLE001
            # One failing builder must not break the bell.
            items.append(Notification(
                id=f"err-{fn.__name__}",
                category="RUNTIME_SECURITY",
                tab="runtime",
                severity="LOW",
                title=f"Notification builder error: {fn.__name__}",
                detail=str(e),
                system_id=None, system_name=None,
                framework=None, control_id=None, gate_id=None,
                timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                action_required="Investigate notifications.py.",
                linked_workflow="/",
                ref_id=None,
                resolved=True,
            ))
    items.sort(key=lambda n: (_SEV_RANK.get(n.severity, 9), n.timestamp), reverse=False)
    return items


def summary() -> dict:
    items = all_notifications()
    unresolved = [n for n in items if not n.resolved]
    counts_by_tab: dict[str, int] = {"all": 0, "critical": 0, "release": 0,
                                       "runtime": 0, "approvals": 0}
    counts_by_severity: dict[str, int] = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0,
                                            "LOW": 0, "INFO": 0}
    counts_by_category: dict[str, int] = {k: 0 for k in CATEGORIES}
    for n in unresolved:
        counts_by_tab["all"] += 1
        counts_by_tab[n.tab] = counts_by_tab.get(n.tab, 0) + 1
        counts_by_severity[n.severity] = counts_by_severity.get(n.severity, 0) + 1
        counts_by_category[n.category] = counts_by_category.get(n.category, 0) + 1

    return {
        "unread": len(unresolved),
        "total": len(items),
        "counts_by_tab": counts_by_tab,
        "counts_by_severity": counts_by_severity,
        "counts_by_category": counts_by_category,
        "items": [n.to_dict() for n in items],
        "categories": CATEGORIES,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


__all__ = [
    "CATEGORIES", "Notification", "all_notifications", "summary",
    "mark_resolved", "clear_resolved", "RESOLVED_FILE",
]
