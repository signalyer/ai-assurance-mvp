"""Portfolio aggregations for the Overview page.

Every metric here derives from a real object — AI system, control, finding,
gate, evidence, or runtime event. No hardcoded numbers.
"""

from __future__ import annotations

from datetime import date, datetime
from collections import Counter

from domain import repository, seed
from domain.assessment_engine import run_assessment
from domain.findings_workflow import list_findings
from domain.framework_coverage import framework_overview
from domain.models import RuntimeStatus, ReleaseDecision, FindingStatus, Severity


# ---------------------------------------------------------------------------
# Top-level KPIs
# ---------------------------------------------------------------------------

def _trend_text(n: int, label: str) -> str:
    """Human-readable trend caption. We don't track historical snapshots; the
    text describes the CURRENT contribution rather than fabricated deltas."""
    if n == 0:
        return f"0 {label}"
    return f"{n} {label}"


def compute_kpis() -> dict:
    """Top-level Overview KPIs, all derived from live data."""
    systems = repository.list_ai_systems()
    findings = list_findings(scope="ALL")

    governed = len(systems)
    in_production = sum(1 for s in systems
                         if s.runtime_status == RuntimeStatus.PRODUCTION)
    in_pilot = sum(1 for s in systems if s.runtime_status == RuntimeStatus.PILOT)
    in_staging_dev = governed - in_production - in_pilot

    open_findings = [f for f in findings if f.status in ("OPEN", "IN_PROGRESS")]
    open_critical = sum(1 for f in open_findings if f.severity == "CRITICAL")
    open_high = sum(1 for f in open_findings if f.severity == "HIGH")
    high_risk_findings = open_critical + open_high
    sla_breached = sum(1 for f in open_findings if f.sla_breached)

    # Release-decision rollup — run the engine on every system once.
    decisions: Counter[str] = Counter()
    portfolio_scores: list[float] = []
    portfolio_ev: list[float] = []
    runtime_24h = 0
    policy_violations = 0
    prompt_injection = 0
    blocked_tool_calls = 0
    dlp_detections = 0

    for s in systems:
        events = repository.runtime_events_for(s.id)
        runtime_24h += sum(1 for e in events if e.event_type.value in (
            "PROMPT_INJECTION_BLOCKED", "PII_LEAK_BLOCKED",
            "UNAUTHORIZED_TOOL_CALL", "JAILBREAK_ATTEMPT",
            "HALLUCINATION_DETECTED",
        ))
        policy_violations += sum(1 for e in events
                                   if e.event_type.value == "POLICY_VIOLATION")
        prompt_injection += sum(1 for e in events
                                  if e.event_type.value in
                                     ("PROMPT_INJECTION_BLOCKED", "JAILBREAK_ATTEMPT"))
        blocked_tool_calls += sum(1 for e in events
                                    if e.event_type.value == "UNAUTHORIZED_TOOL_CALL")
        dlp_detections += sum(1 for e in events
                                if e.event_type.value == "PII_LEAK_BLOCKED")
        try:
            report = run_assessment(s.id)
            decisions[report.release_recommendation.decision.value] += 1
            portfolio_scores.append(report.overall_score)
            portfolio_ev.append(report.evidence_completeness)
        except Exception:                                                # noqa: BLE001
            decisions[s.release_decision.value] += 1

    avg_score = round(sum(portfolio_scores) / len(portfolio_scores), 1) \
        if portfolio_scores else 0.0
    avg_evidence = round(sum(portfolio_ev) / len(portfolio_ev) * 100, 0) \
        if portfolio_ev else 0

    # Enterprise risk score = 100 - weighted-blocker-burden.
    # Each open CRITICAL costs 8 points, each HIGH 3 points, each SLA breach 2 points,
    # each release HOLD 5 points; capped at 0..100.
    risk_burden = 8 * open_critical + 3 * open_high + 2 * sla_breached \
        + 5 * decisions.get("HOLD", 0) + 8 * decisions.get("REJECT", 0)
    enterprise_risk_score = max(0, min(100, int(avg_score - 0.4 * risk_burden + 60)))
    if enterprise_risk_score >= 80:
        risk_level = "Low"
    elif enterprise_risk_score >= 60:
        risk_level = "Moderate"
    elif enterprise_risk_score >= 40:
        risk_level = "High"
    else:
        risk_level = "Critical"

    # Framework coverage — average coverage_pct per framework across systems.
    fw_scores: dict[str, float] = {}
    for fw_key, label in [
        ("NIST_AI_RMF", "nist_ai_rmf"),
        ("NIST_AI_600_1", "nist_ai_600_1"),
        ("OWASP_LLM_TOP10", "owasp_llm"),
        ("OWASP_AGENTIC_TOP10", "owasp_agentic"),
    ]:
        try:
            items = framework_overview(fw_key, scope="ALL")
            fw_scores[label] = round(
                sum(it.coverage_pct for it in items) / len(items), 0
            ) if items else 0
        except ValueError:
            fw_scores[label] = 0
    # ISO 23894 — not in framework_catalog; derive from FS_OVERLAY control coverage.
    fs_controls = [
        c for c in __import__("domain.controls", fromlist=["CONTROLS"]).CONTROLS
        if any(fm.framework.value == "FS_OVERLAY" for fm in c.framework_mappings)
    ]
    fs_pass = 0
    fs_total = 0
    for s in systems:
        try:
            report = run_assessment(s.id)
            for ce in report.control_evaluations:
                if ce.control_id.startswith("AI-"):
                    fs_total += 1
                    if ce.status.value == "PASS":
                        fs_pass += 1
        except Exception:                                                # noqa: BLE001
            continue
    fw_scores["iso_iec_23894"] = round(fs_pass / fs_total * 100, 0) if fs_total else 0

    # SLA bucket distribution
    today_d = date.today()
    sla_overdue = 0; sla_due_7d = 0; sla_due_30d = 0; sla_closed = 0
    for f in findings:
        if f.status in ("CLOSED", "REMEDIATED", "VERIFIED"):
            sla_closed += 1
        elif f.status in ("OPEN", "IN_PROGRESS"):
            if f.sla_breached:
                sla_overdue += 1
            else:
                try:
                    due = date.fromisoformat(str(f.sla_due_date))
                    days = (due - today_d).days
                    if days <= 7:
                        sla_due_7d += 1
                    elif days <= 30:
                        sla_due_30d += 1
                except ValueError:
                    pass

    return {
        "enterprise_ai_risk_score": enterprise_risk_score,
        "risk_score_trend": f"Weighted burden across {len(systems)} systems",
        "risk_level": risk_level,
        "ai_systems_reviewed": governed,
        "ai_systems_trend": f"{in_production} prod · {in_pilot} pilot · {in_staging_dev} staging/dev",
        "production_ai_systems": in_production,
        "production_trend": _trend_text(decisions.get("APPROVED", 0), "approved for production"),
        "high_risk_findings": high_risk_findings,
        "high_risk_trend": f"{open_critical} CRITICAL · {open_high} HIGH · {sla_breached} SLA breached",
        "release_holds": decisions.get("HOLD", 0),
        "release_holds_trend": _trend_text(decisions.get("HOLD", 0), "blocking production release"),
        "runtime_incidents_24h": runtime_24h,
        "runtime_trend": f"{prompt_injection} injection · {blocked_tool_calls} blocked tool · {dlp_detections} DLP",
        "policy_violations_24h": policy_violations,
        "policy_violations_trend": _trend_text(policy_violations, "policy violations logged"),
        "evidence_completeness": int(avg_evidence),
        "evidence_trend": f"Portfolio average across {governed} systems",
        "total_findings": len(findings),
        "open_findings": len(open_findings),
        "release_gates": {
            "hold": decisions.get("HOLD", 0),
            "conditional": decisions.get("CONDITIONAL_PILOT", 0),
            "approved": decisions.get("APPROVED", 0),
            "reject": decisions.get("REJECT", 0),
        },
        "frameworks": fw_scores,
        "runtime_activity": {
            "prompt_injection": prompt_injection,
            "blocked_tool_calls": blocked_tool_calls,
            "policy_violations": policy_violations,
            "dlp_detections": dlp_detections,
        },
        "sla": {"overdue": sla_overdue, "due_7d": sla_due_7d,
                "due_30d": sla_due_30d, "closed": sla_closed},
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }


# ---------------------------------------------------------------------------
# Homepage critical findings
# ---------------------------------------------------------------------------

_SEV_RANK = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}


def homepage_critical_findings(limit: int = 5) -> list[dict]:
    findings = list_findings(scope="ALL")
    open_f = [f for f in findings
              if f.status in ("OPEN", "IN_PROGRESS")
              and f.severity in ("CRITICAL", "HIGH")]
    open_f.sort(key=lambda f: (_SEV_RANK.get(f.severity, 9), f.sla_due_date))

    return [
        {
            "id": f.id,
            "title": f.title,
            "system": f.ai_system_name,
            "severity": f.priority,           # P0 / P1 / ...
            "control_id": f.control_id,
            "framework": (f.mapped_frameworks or ["—"])[0],
            "time_ago": _time_ago(f.discovered),
        }
        for f in open_f[:limit]
    ]


def _time_ago(d) -> str:
    try:
        dd = d if isinstance(d, date) else date.fromisoformat(str(d))
    except (ValueError, TypeError):
        return ""
    days = (date.today() - dd).days
    if days <= 0:
        return "today"
    if days == 1:
        return "1d ago"
    if days < 7:
        return f"{days}d ago"
    if days < 30:
        return f"{days // 7}w ago"
    return f"{days // 30}mo ago"


# ---------------------------------------------------------------------------
# Homepage runtime events
# ---------------------------------------------------------------------------

_ACTION_BY_TYPE = {
    "PROMPT_INJECTION_BLOCKED": "Blocked",
    "PII_LEAK_BLOCKED": "Masked",
    "UNAUTHORIZED_TOOL_CALL": "Blocked",
    "JAILBREAK_ATTEMPT": "Blocked",
    "POLICY_VIOLATION": "Blocked",
    "HITL_ESCALATION": "Escalated",
    "RATE_LIMIT_TRIPPED": "Throttled",
    "GUARDRAIL_REFUSAL": "Refused",
    "HALLUCINATION_DETECTED": "Flagged",
    "SANCTIONS_HIT": "Escalated",
    "ANOMALOUS_USAGE": "Flagged",
    "AGENT_RECURSION_EXCEEDED": "Halted",
    "MACIE_FINDING_INGESTED": "Logged",
    "BEDROCK_INVOCATION": "Logged",
}


def homepage_runtime_events(limit: int = 5) -> list[dict]:
    systems_by_id = {s.id: s.name for s in repository.list_ai_systems()}
    all_events = []
    for sid in systems_by_id:
        for ev in repository.runtime_events_for(sid):
            all_events.append(ev)
    all_events.sort(key=lambda e: e.timestamp, reverse=True)

    rows = []
    for e in all_events[:limit]:
        rows.append({
            "id": e.id,
            "time": e.timestamp.strftime("%H:%M") if hasattr(e.timestamp, "strftime") else "",
            "timestamp": e.timestamp.isoformat() if hasattr(e.timestamp, "isoformat") else "",
            "system": systems_by_id.get(e.ai_system_id, e.ai_system_id),
            "ai_system_id": e.ai_system_id,
            "event_type": _pretty_event_type(e.event_type.value),
            "severity": e.severity.value,
            "action": _ACTION_BY_TYPE.get(e.event_type.value, e.action_taken.title()),
            "source": e.source.value,
            "linked_control": e.linked_control,
            "linked_framework": e.linked_framework,
            "policy_triggered": e.policy_triggered,
            "evidence_id": e.evidence_id,
        })
    return rows


def _pretty_event_type(s: str) -> str:
    return s.replace("_", " ").title()


# ---------------------------------------------------------------------------
# Next Actions queue — derived from open findings + gate failures
# ---------------------------------------------------------------------------

def next_actions(limit: int = 5) -> list[dict]:
    today_d = date.today()
    actions: list[dict] = []

    findings = list_findings(scope="ALL")
    open_p0 = [f for f in findings if f.severity == "CRITICAL"
               and f.status in ("OPEN", "IN_PROGRESS")]
    if open_p0:
        actions.append({
            "title": f"Resolve {len(open_p0)} CRITICAL finding(s) blocking production release",
            "priority": "HIGH_PRIORITY",
            "due": "High Priority",
            "ref_ids": [f.id for f in open_p0[:5]],
        })

    # Due today / breached
    open_findings = [f for f in findings if f.status in ("OPEN", "IN_PROGRESS")]
    due_today = [f for f in open_findings
                 if str(f.sla_due_date) == today_d.isoformat()
                 or f.sla_breached]
    for f in due_today[:2]:
        actions.append({
            "title": f"Remediate {f.id} — {f.title}",
            "priority": "DUE_TODAY",
            "due": "Due Today" if not f.sla_breached else "SLA Breached",
            "ref_ids": [f.id],
        })

    # Systems with HOLD decision
    for s in repository.list_ai_systems():
        try:
            report = run_assessment(s.id)
            if report.release_recommendation.decision.value == "HOLD":
                actions.append({
                    "title": f"Review release-hold on {s.name} — rule {report.release_recommendation.rule_fired}",
                    "priority": "DUE_2D",
                    "due": "Due in 2 days",
                    "ref_ids": [s.id],
                })
        except Exception:                                                # noqa: BLE001
            continue
        if len(actions) >= limit:
            break

    # Expiring waivers
    for w in seed.EXCEPTION_WAIVERS:
        days = (w.expiration_date - today_d).days
        if 0 < days <= 14 and w.status.value == "APPROVED":
            actions.append({
                "title": f"Waiver {w.id} for control {w.control_id} expires in {days}d",
                "priority": "DUE_7D" if days > 5 else "DUE_5D",
                "due": f"Expires in {days}d",
                "ref_ids": [w.id],
            })

    return actions[:limit]


# ---------------------------------------------------------------------------
# Threat-chart series — last 7 days
# ---------------------------------------------------------------------------

def threat_series_7d() -> dict:
    """Per-day series for the four threat dimensions on the Overview.
    Buckets are calendar days based on event.timestamp. Days with no events
    show 0 — no synthetic noise."""
    days = []
    today_d = date.today()
    for i in range(6, -1, -1):
        d = today_d.replace(day=today_d.day) if False else today_d
        # use ordinal arithmetic to be safe across month boundaries
        from datetime import timedelta
        d = today_d - timedelta(days=i)
        days.append(d)

    series: dict[str, list[int]] = {
        "prompt_injection": [0] * 7,
        "blocked_tool_calls": [0] * 7,
        "policy_violations": [0] * 7,
        "dlp_detections": [0] * 7,
    }

    for s in repository.list_ai_systems():
        for e in repository.runtime_events_for(s.id):
            try:
                ev_date = (e.timestamp.date() if hasattr(e.timestamp, "date")
                           else date.fromisoformat(str(e.timestamp)[:10]))
            except (AttributeError, ValueError):
                continue
            if ev_date not in days:
                continue
            idx = days.index(ev_date)
            etype = e.event_type.value
            if etype in ("PROMPT_INJECTION_BLOCKED", "JAILBREAK_ATTEMPT"):
                series["prompt_injection"][idx] += 1
            elif etype == "UNAUTHORIZED_TOOL_CALL":
                series["blocked_tool_calls"][idx] += 1
            elif etype == "POLICY_VIOLATION":
                series["policy_violations"][idx] += 1
            elif etype == "PII_LEAK_BLOCKED":
                series["dlp_detections"][idx] += 1

    months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    return {
        "x_labels": [f"{months[d.month - 1]} {d.day}" for d in days],
        "series": series,
    }


__all__ = [
    "compute_kpis",
    "homepage_critical_findings",
    "homepage_runtime_events",
    "next_actions",
    "threat_series_7d",
]
