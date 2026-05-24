"""Reports API — JSON, CSV, and print-ready HTML (used as 'PDF') exports.

Six report types:
  - executive            (portfolio, no system_id)
  - assessment           (per-system)
  - release_gate         (per-system)
  - framework_coverage   (per-system or portfolio if system_id omitted)
  - findings             (per-system)
  - evidence             (per-system)

PDF strategy: there is no native PDF generator wired in this build. The
'.pdf' endpoint returns an HTML document with print-only styles — auditors
hit Ctrl+P / Cmd+P → 'Save as PDF' in their browser. This matches the
existing `/api/report/compliance` pattern in dashboard.py.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse, HTMLResponse, PlainTextResponse, Response
from pydantic import BaseModel, ConfigDict

from domain import repository
from domain.reports import build_report, to_csv_table, BUILDERS


router = APIRouter(prefix="/api/reports", tags=["reports"])


# ===========================================================================
# Response models (Session 26 — Track A OpenAPI sweep, per-router #2)
# ===========================================================================

class ReportCatalogItem(BaseModel):
    """One entry in the report-type catalog. Stable shape — UI keys off `type`/`title`/`scope`."""
    type: str
    title: str
    scope: str
    requires_system: bool
    audience: list[str]
    description: str


class ReportCatalogResponse(BaseModel):
    reports: list[ReportCatalogItem]


class ReportSystemItem(BaseModel):
    """One AI system entry for the per-system selector dropdown."""
    id: str
    name: str
    domain: str
    runtime_status: str
    release_decision: str


class ReportSystemsResponse(BaseModel):
    systems: list[ReportSystemItem]


class ReportDataResponse(BaseModel):
    """Permissive — the report payload shape diverges across the six report
    types (executive / assessment / release_gate / framework_coverage /
    findings / evidence). Pin only the three discriminators that every
    builder populates; surface the rest via `extra="allow"` rather than
    freezing internal builder shapes on the first sweep (compound rule 25a).
    """
    model_config = ConfigDict(extra="allow")
    report_title: str | None = None
    generated_at: str | None = None
    audience: list[str] | None = None


_PER_SYSTEM_TYPES = {"assessment", "release_gate", "findings", "evidence"}


def _validate(report_type: str, system_id: str | None) -> None:
    if report_type not in BUILDERS:
        raise HTTPException(404, f"Unknown report type: {report_type}")
    if report_type in _PER_SYSTEM_TYPES and not system_id:
        raise HTTPException(400, f"{report_type} report requires system_id")


def _safe_build(report_type: str, system_id: str | None) -> dict:
    try:
        return build_report(report_type, system_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


# ===========================================================================
# Catalog + JSON
# ===========================================================================

@router.get("/catalog", response_model=ReportCatalogResponse, operation_id="reports_catalog_list")
async def catalog() -> dict:
    """List the six report types with metadata for the UI."""
    return {"reports": [
        {
            "type": "executive", "title": "Executive AI Risk Report",
            "scope": "portfolio", "requires_system": False,
            "audience": ["CISO", "Chief Risk Officer", "AI Governance Board",
                          "Internal Audit", "Model Risk Management"],
            "description": "Portfolio-wide AI risk posture. Top-of-house view across every AI system in flight or in production.",
        },
        {
            "type": "assessment", "title": "AI System Assessment Report",
            "scope": "system", "requires_system": True,
            "audience": ["Model Risk Management", "AI Governance Board", "Internal Audit"],
            "description": "Full assessment for one AI system — risk classification, control evaluations, eval results, findings, release decision.",
        },
        {
            "type": "release_gate", "title": "Release Gate Report",
            "scope": "system", "requires_system": True,
            "audience": ["AppSec", "CISO", "AI Governance Board"],
            "description": "Per-gate evaluation (RG-001..RG-010) with pass / fail / waiver state and the supporting remediation steps.",
        },
        {
            "type": "framework_coverage", "title": "Framework Coverage Report",
            "scope": "system or portfolio", "requires_system": False,
            "audience": ["Internal Audit", "Compliance", "AI Governance Board"],
            "description": "Coverage across NIST AI RMF, NIST 600-1, OWASP LLM Top 10, OWASP Agentic Top 10, and the FS overlay.",
        },
        {
            "type": "findings", "title": "Findings & Remediation Report",
            "scope": "system", "requires_system": True,
            "audience": ["AppSec", "Engineering Leadership", "AI Governance Board"],
            "description": "Open findings, SLAs, owners, and the remediation plan — plus the workflow timeline for each finding.",
        },
        {
            "type": "evidence", "title": "Audit Evidence Report",
            "scope": "system", "requires_system": True,
            "audience": ["Internal Audit", "External Audit", "Compliance"],
            "description": "Evidence catalog organized into 8 audit sections with 4-axis completeness (system, framework, control domain, gate).",
        },
    ]}


@router.get("/systems", response_model=ReportSystemsResponse, operation_id="reports_systems_list")
async def systems() -> dict:
    """List AI systems for the per-system selector."""
    return {"systems": [
        {"id": s.id, "name": s.name, "domain": s.domain,
         "runtime_status": s.runtime_status.value,
         "release_decision": s.release_decision.value}
        for s in repository.list_ai_systems()
    ]}


@router.get("/{report_type}", response_model=ReportDataResponse, operation_id="reports_report_get")
async def get_report(report_type: str, system_id: str | None = Query(None)) -> JSONResponse:
    _validate(report_type, system_id)
    return JSONResponse(_safe_build(report_type, system_id))


# ===========================================================================
# Exports
# ===========================================================================

@router.get("/{report_type}/export.json", operation_id="reports_report_export_json")
async def export_json(report_type: str, system_id: str | None = Query(None)) -> Response:
    _validate(report_type, system_id)
    data = _safe_build(report_type, system_id)
    body = json.dumps(data, indent=2, default=str)
    fname = _filename(report_type, system_id, "json")
    return Response(
        content=body, media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/{report_type}/export.csv", operation_id="reports_report_export_csv")
async def export_csv(report_type: str, system_id: str | None = Query(None)) -> Response:
    _validate(report_type, system_id)
    data = _safe_build(report_type, system_id)
    header, rows = to_csv_table(data, report_type)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    # Report metadata header lines (commented out so CSV stays valid for most tools)
    w.writerow([f"# {data.get('report_title', report_type)}"])
    w.writerow([f"# Generated: {data.get('generated_at')}"])
    if system_id:
        w.writerow([f"# System: {system_id}"])
    w.writerow([])
    w.writerow(header)
    for r in rows:
        w.writerow(r)
    fname = _filename(report_type, system_id, "csv")
    return Response(
        content=buf.getvalue(), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/{report_type}/export.pdf", operation_id="reports_report_export_pdf")
async def export_pdf(report_type: str, system_id: str | None = Query(None)) -> HTMLResponse:
    """Print-ready HTML view. Browser print → Save as PDF.
    A native PDF generator is not wired in this build; this matches the
    existing /api/report/compliance pattern.
    """
    _validate(report_type, system_id)
    data = _safe_build(report_type, system_id)
    html = _render_print_html(data, report_type)
    return HTMLResponse(content=html)


def _filename(report_type: str, system_id: str | None, ext: str) -> str:
    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M")
    parts = ["report", report_type]
    if system_id:
        parts.append(system_id)
    parts.append(stamp)
    return "_".join(parts) + "." + ext


# ===========================================================================
# Print HTML — used as the 'PDF' export
# ===========================================================================

def _render_print_html(data: dict, report_type: str) -> str:
    title = data.get("report_title") or report_type
    generated = data.get("generated_at") or ""
    sections: list[str] = []

    sys = data.get("system_summary")
    if sys:
        sections.append(_section("AI System Summary", _kv_html({
            "ID": sys.get("id"),
            "Name": sys.get("name"),
            "Domain": sys.get("domain"),
            "Business owner": sys.get("business_owner"),
            "Technical owner": sys.get("technical_owner"),
            "Cloud / Model": f"{sys.get('cloud_provider')} · {sys.get('model_provider')}",
            "Models used": ", ".join(sys.get("models_used", [])),
            "Autonomy level": sys.get("autonomy_level"),
            "User population": sys.get("user_population"),
            "Customer impact": sys.get("customer_impact"),
            "Regulatory exposure": ", ".join(sys.get("regulatory_exposure", [])),
            "Data classes": ", ".join(sys.get("data_classes", [])),
            "AWS services": ", ".join(sys.get("aws_services", [])),
            "Runtime status": sys.get("runtime_status"),
            "Release decision (recorded)": sys.get("release_decision"),
            "Inherent risk / Residual risk": f"{sys.get('inherent_risk')} → {sys.get('residual_risk')}",
            "Human oversight": sys.get("human_oversight"),
        })))

    if report_type == "executive":
        sections.append(_section("Portfolio KPIs", _kv_html(data.get("portfolio_kpis", {}))))
        sections.append(_section("Systems Needing Attention",
            _table(["system_id", "name", "decision", "residual_risk",
                    "open_critical", "open_high", "sla_breached", "rule_fired"],
                   data.get("needs_attention", []))))
        sections.append(_section("Framework Coverage Rollup",
            _table(["framework", "controls_applicable", "controls_passing",
                    "controls_failing", "coverage_pct"],
                   data.get("framework_rollup", []))))
        sections.append(_section("All AI Systems",
            _table(["name", "domain", "business_owner", "runtime_status",
                    "release_decision", "residual_risk", "overall_score",
                    "evidence_completeness", "open_critical", "open_high",
                    "sla_breached", "active_waivers"],
                   data.get("ai_systems", []))))

    if report_type == "assessment":
        rc = data.get("risk_classification", {})
        sections.append(_section("Risk Classification", _kv_html({
            "Inherent risk": rc.get("inherent_risk"),
            "Rules fired": ", ".join(rc.get("rules_fired", [])),
            "Residual risk": (rc.get("residual_risk") or {}).get("level"),
            "Normalized score": (rc.get("residual_risk") or {}).get("normalized_score"),
            "Raw score": (rc.get("residual_risk") or {}).get("raw_score"),
        })))
        sections.append(_section("Framework Coverage",
            _table(["framework", "controls_applicable", "controls_passing",
                    "controls_failing", "coverage_pct"],
                   data.get("framework_coverage", []))))
        sections.append(_section("Failed Controls",
            _table(["control_id", "title", "domain", "priority", "status",
                    "blocking", "rationale"],
                   data.get("failed_controls", []))))
        sections.append(_section("Eval Results",
            _table(["eval_type", "score", "threshold", "status", "tool_source",
                    "test_count", "failed_count", "run_at"],
                   data.get("eval_results", []))))
        sections.append(_release_decision_section(data.get("release_decision")))
        sections.append(_section("Open Findings",
            _table(["id", "severity", "title", "control_id", "owner",
                    "sla_due_date", "release_impact"],
                   data.get("open_findings", []))))
        sections.append(_section("Remediation Plan",
            _table(["finding_id", "severity", "title", "owner", "sla_due",
                    "remediation"],
                   data.get("remediation_plan", []))))
        sections.append(_kv_section("Evidence Completeness",
                                     {"%": f"{round((data.get('evidence_completeness') or 0)*100, 1)}%"}))
        sections.append(_section("Approval History",
            _table(["approver", "role", "decision", "timestamp", "comments"],
                   data.get("approval_history", []))))
        sections.append(_section("Exception History",
            _table(["id", "control_id", "risk_acceptor", "role",
                    "expiration_date", "status", "reason"],
                   data.get("exception_history", []))))

    if report_type == "release_gate":
        sections.append(_release_decision_section(data.get("release_decision")))
        sections.append(_section("Gates",
            _table(["gate_id", "gate_name", "status", "blocking",
                    "failed_reason", "remediation"],
                   data.get("gates", []))))
        sections.append(_section("Eval Results",
            _table(["eval_type", "score", "threshold", "status", "tool_source"],
                   data.get("eval_results", []))))
        sections.append(_section("Open Findings",
            _table(["id", "severity", "title", "control_id", "owner",
                    "sla_due_date"],
                   data.get("open_findings", []))))
        sections.append(_section("Remediation Plan",
            _table(["finding_id", "severity", "title", "owner", "sla_due",
                    "remediation"],
                   data.get("remediation_plan", []))))
        sections.append(_section("Approval History",
            _table(["approver", "role", "decision", "timestamp", "comments"],
                   data.get("approval_history", []))))
        sections.append(_section("Exception History",
            _table(["id", "control_id", "risk_acceptor", "role",
                    "expiration_date", "status", "reason"],
                   data.get("exception_history", []))))

    if report_type == "framework_coverage":
        for fw in data.get("frameworks", []):
            sections.append(_section(f"Framework — {fw['framework']}",
                _kv_html({
                    "Applicable items": fw.get("applicable_items"),
                    "Passing items (100%)": fw.get("passing_items"),
                    "Avg coverage %": fw.get("avg_coverage_pct"),
                    "Avg evidence completeness": fw.get("avg_evidence_completeness"),
                }) + _table(
                    ["item_id", "display_name", "coverage_pct",
                     "evidence_completeness"],
                    fw.get("items", []))))
        sections.append(_section("Evidence Completeness by Control Domain",
            _table(["domain", "applicable_controls", "covered_controls",
                    "completeness_pct"],
                   data.get("evidence_completeness_by_domain", []))))
        if data.get("release_decision"):
            sections.append(_release_decision_section(data.get("release_decision")))
        sections.append(_section("Failed Controls",
            _table(["control_id"],
                   [{"control_id": c} for c in data.get("failed_controls", [])])))
        sections.append(_section("Eval Results",
            _table(["eval_type", "score", "threshold", "status", "tool_source"],
                   data.get("eval_results", []))))
        sections.append(_section("Open Findings",
            _table(["id", "severity", "title", "control_id", "owner",
                    "sla_due_date"],
                   data.get("open_findings", []))))
        sections.append(_section("Remediation Plan",
            _table(["finding_id", "severity", "title", "owner", "sla_due",
                    "remediation"],
                   data.get("remediation_plan", []))))
        sections.append(_section("Approval History",
            _table(["approver", "role", "decision", "timestamp", "comments"],
                   data.get("approval_history", []))))
        sections.append(_section("Exception History",
            _table(["id", "control_id", "risk_acceptor", "role",
                    "expiration_date", "status", "reason"],
                   data.get("exception_history", []))))

    if report_type == "findings":
        sections.append(_section("Totals",
            _kv_html({k: (v if not isinstance(v, dict) else
                          ", ".join(f"{kk}={vv}" for kk, vv in v.items()))
                       for k, v in (data.get("totals") or {}).items()})))
        sections.append(_section("Open Findings",
            _table(["id", "severity", "title", "control_id", "owner",
                    "sla_due_date", "sla_breached", "release_impact"],
                   data.get("open_findings", []))))
        sections.append(_section("Remediation Plan",
            _table(["finding_id", "severity", "title", "owner", "sla_due",
                    "remediation"],
                   data.get("remediation_plan", []))))
        sections.append(_section("Eval Results",
            _table(["eval_type", "score", "threshold", "status", "tool_source"],
                   data.get("eval_results", []))))
        sections.append(_release_decision_section(data.get("release_decision")))
        sections.append(_section("Approval History",
            _table(["approver", "role", "decision", "timestamp", "comments"],
                   data.get("approval_history", []))))
        sections.append(_section("Exception History",
            _table(["id", "control_id", "risk_acceptor", "role",
                    "expiration_date", "status", "reason"],
                   data.get("exception_history", []))))

    if report_type == "evidence":
        sections.append(_section("Evidence Summary", _kv_html({
            "Evidence records": data.get("evidence_count"),
            "Evidence completeness": f"{round((data.get('evidence_completeness') or 0) * 100, 1)}%",
        })))
        sections.append(_section("Completeness by Framework",
            _table(["framework", "applicable_controls", "covered_controls",
                    "completeness_pct"],
                   data.get("completeness_by_framework", []))))
        sections.append(_section("Completeness by Control Domain",
            _table(["domain", "applicable_controls", "covered_controls",
                    "completeness_pct"],
                   data.get("completeness_by_control_domain", []))))
        for sec_name, rows in (data.get("evidence_by_section") or {}).items():
            sections.append(_section(f"Evidence — {sec_name}",
                _table(["id", "evidence_type", "source", "summary",
                        "collected_at"], rows)))
        sections.append(_section("Evidence by Control",
            _table(["control_id", "evidence_ids"],
                   data.get("evidence_by_control", []))))
        sections.append(_release_decision_section(data.get("release_decision")))
        sections.append(_section("Failed Controls",
            _table(["control_id"],
                   [{"control_id": c} for c in data.get("failed_controls", [])])))
        sections.append(_section("Open Findings",
            _table(["id", "severity", "title", "control_id", "owner",
                    "sla_due_date"],
                   data.get("open_findings", []))))
        sections.append(_section("Remediation Plan",
            _table(["finding_id", "severity", "title", "owner", "sla_due",
                    "remediation"],
                   data.get("remediation_plan", []))))
        sections.append(_section("Approval History",
            _table(["approver", "role", "decision", "timestamp", "comments"],
                   data.get("approval_history", []))))
        sections.append(_section("Exception History",
            _table(["id", "control_id", "risk_acceptor", "role",
                    "expiration_date", "status", "reason"],
                   data.get("exception_history", []))))

    audience = ""
    if data.get("audience"):
        audience = f"<div class='audience'>Audience: {', '.join(data['audience'])}</div>"

    return f"""<!DOCTYPE html>
<html><head><meta charset='UTF-8'><title>{_h(title)}</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
          color: #1a1a1a; max-width: 1100px; margin: 24px auto; padding: 0 24px; }}
  h1 {{ font-size: 22px; margin: 0 0 4px; }}
  h2 {{ font-size: 14px; text-transform: uppercase; letter-spacing: 0.06em;
        margin: 24px 0 6px; border-bottom: 1px solid #ddd; padding-bottom: 4px; color: #444; }}
  .meta {{ color: #666; font-size: 12px; margin-bottom: 4px; }}
  .audience {{ color: #444; font-size: 12px; margin-bottom: 16px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 11px; margin-top: 6px; }}
  th, td {{ border: 1px solid #d8d8d8; padding: 4px 6px; text-align: left;
            vertical-align: top; word-wrap: break-word; }}
  th {{ background: #f3f3f5; }}
  .kv {{ display: grid; grid-template-columns: 220px 1fr; gap: 2px 12px; font-size: 12px; }}
  .kv .k {{ color: #555; }}
  .empty {{ color: #888; font-style: italic; font-size: 12px; }}
  .pill {{ display: inline-block; padding: 1px 6px; border-radius: 10px;
           background: #eef; font-size: 10px; }}
  .toolbar {{ margin: 0 0 16px; font-size: 11px; }}
  .toolbar a {{ color: #226; margin-right: 12px; }}
  @media print {{
    .toolbar {{ display: none; }}
    body {{ margin: 0; padding: 0 12px; }}
    h2 {{ page-break-after: avoid; }}
    table {{ page-break-inside: avoid; }}
  }}
</style></head>
<body>
  <div class='toolbar'>
    <a href='javascript:window.print()'>Print / Save as PDF</a>
    <a href='javascript:window.close()'>Close</a>
  </div>
  <h1>{_h(title)}</h1>
  <div class='meta'>Generated {_h(generated)}</div>
  {audience}
  {''.join(sections)}
</body></html>
"""


def _h(s) -> str:
    if s is None:
        return ""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _section(title: str, body: str) -> str:
    return f"<h2>{_h(title)}</h2>{body or '<div class=\"empty\">No data.</div>'}"


def _kv_section(title: str, d: dict) -> str:
    return _section(title, _kv_html(d))


def _kv_html(d: dict) -> str:
    if not d:
        return "<div class='empty'>No data.</div>"
    parts = ["<div class='kv'>"]
    for k, v in d.items():
        if isinstance(v, list):
            v = ", ".join(str(x) for x in v) if v else "—"
        parts.append(f"<div class='k'>{_h(k)}</div><div class='v'>{_h(v)}</div>")
    parts.append("</div>")
    return "".join(parts)


def _table(cols: list[str], rows: list[dict]) -> str:
    if not rows:
        return "<div class='empty'>No data.</div>"
    head = "".join(f"<th>{_h(c)}</th>" for c in cols)
    body = []
    for r in rows:
        cells = []
        for c in cols:
            v = r.get(c) if isinstance(r, dict) else None
            if isinstance(v, list):
                v = ", ".join(str(x) for x in v) if v else ""
            elif isinstance(v, dict):
                v = json.dumps(v, default=str)
            cells.append(f"<td>{_h(v) if v is not None else ''}</td>")
        body.append(f"<tr>{''.join(cells)}</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def _release_decision_section(rd: dict | None) -> str:
    if not rd:
        return ""
    return _section("Release Decision", _kv_html({
        "Decision": rd.get("decision"),
        "Rule fired": rd.get("rule_fired"),
        "Rationale": rd.get("rationale"),
        "Conditions": rd.get("conditions") or [],
    }))
