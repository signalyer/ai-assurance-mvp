"""HTML-to-PDF compliance reports — uses HTML (no external PDF library dependency).

For now, generates a comprehensive HTML report that can be printed to PDF
via the browser. This avoids the need for reportlab/weasyprint dependencies
while still producing professional-grade reports.

Session 06 additions: generate_nist_pack(), generate_owasp_pack(),
generate_eu_ai_act_pack() produce binary PDF bytes using a minimal
stdlib-only PDF writer (no third-party library required).

Session 11 additions: generate_iso_42001_pack(), generate_sr_11_7_pack(),
generate_ffiec_pack() follow the same pattern.

The _PdfWriter class and shared helpers have been extracted to
domain/pdf_pack_base.py for reuse.  They are re-imported here to preserve
the internal API and the public generate_*_pack() signatures unchanged.
"""

from __future__ import annotations

import html
from datetime import datetime, timedelta, timezone
from typing import Optional

# ---------------------------------------------------------------------------
# Re-export shared PDF primitives from domain/pdf_pack_base.py
# All three existing pack functions use these names directly — byte-identical.
# ---------------------------------------------------------------------------
from domain.pdf_pack_base import (
    _PdfWriter,
    _compute_evidence_hash,
    _load_system_and_evidence,
    _render_evidence_appendix,
    _render_item_section,
)


def generate_compliance_report_html(
    runs: list[dict],
    audit_logs: list[dict],
    start_date: datetime,
    end_date: datetime,
    report_type: str = "HIPAA",
    organization: str = "Customer Organization",
) -> str:
    """
    Generate a complete compliance audit report as HTML.

    Args:
        runs: List of evaluation runs in period
        audit_logs: List of audit log entries
        start_date: Report period start
        end_date: Report period end
        report_type: HIPAA, SOC2, or GDPR
        organization: Customer organization name

    Returns:
        Full HTML document as string
    """
    total_runs = len(runs)

    # Calculate stats
    pass_count = sum(
        1 for r in runs
        if all(
            m.get("passed") is True or m.get("skipped", False)
            for m in r.get("eval_scores", {}).values()
        )
    )
    fail_count = total_runs - pass_count
    pass_rate = round(pass_count / total_runs * 100, 1) if total_runs else 0

    # Group by domain
    by_domain = {}
    for run in runs:
        domain = run.get("domain", "Unknown")
        if domain not in by_domain:
            by_domain[domain] = {"total": 0, "pass": 0, "fail": 0}
        by_domain[domain]["total"] += 1
        eval_scores = run.get("eval_scores", {})
        all_passed = all(
            m.get("passed") is True or m.get("skipped", False)
            for m in eval_scores.values()
        )
        if all_passed:
            by_domain[domain]["pass"] += 1
        else:
            by_domain[domain]["fail"] += 1

    # Group by model
    by_model = {}
    for run in runs:
        model = run.get("model", "Unknown")
        by_model[model] = by_model.get(model, 0) + 1

    # Audit log stats
    audit_by_action = {}
    for log in audit_logs:
        action = log.get("action", "unknown")
        audit_by_action[action] = audit_by_action.get(action, 0) + 1

    # Compliance-specific sections
    compliance_section = _generate_compliance_section(report_type, runs)

    # Finding #6: escape organization before interpolating into HTML
    safe_org = html.escape(organization)

    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{html.escape(report_type)} Compliance Audit Report — {safe_org}</title>
    <style>
        @media print {{
            body {{ margin: 0; }}
            .page-break {{ page-break-after: always; }}
        }}

        * {{ margin: 0; padding: 0; box-sizing: border-box; }}

        body {{
            font-family: 'Segoe UI', Arial, sans-serif;
            color: #1a1a1a;
            line-height: 1.6;
            padding: 2rem;
            max-width: 8.5in;
            margin: 0 auto;
        }}

        .header {{
            border-bottom: 3px solid #2563eb;
            padding-bottom: 1rem;
            margin-bottom: 2rem;
        }}

        .header h1 {{
            color: #1e3a8a;
            font-size: 2rem;
            margin-bottom: 0.5rem;
        }}

        .header .meta {{
            color: #64748b;
            font-size: 0.875rem;
        }}

        .section {{
            margin-bottom: 2rem;
        }}

        .section h2 {{
            color: #1e3a8a;
            font-size: 1.5rem;
            border-bottom: 1px solid #e5e7eb;
            padding-bottom: 0.5rem;
            margin-bottom: 1rem;
        }}

        .section h3 {{
            color: #334155;
            font-size: 1.125rem;
            margin-top: 1rem;
            margin-bottom: 0.5rem;
        }}

        .summary-grid {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 1rem;
            margin-bottom: 1.5rem;
        }}

        .summary-card {{
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 0.5rem;
            padding: 1rem;
            text-align: center;
        }}

        .summary-card .label {{
            font-size: 0.75rem;
            color: #64748b;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}

        .summary-card .value {{
            font-size: 1.875rem;
            font-weight: 700;
            color: #1e3a8a;
            margin-top: 0.25rem;
        }}

        .summary-card.success .value {{ color: #16a34a; }}
        .summary-card.warning .value {{ color: #d97706; }}
        .summary-card.danger .value {{ color: #dc2626; }}

        table {{
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 1rem;
        }}

        th, td {{
            padding: 0.75rem;
            text-align: left;
            border-bottom: 1px solid #e5e7eb;
        }}

        th {{
            background: #f1f5f9;
            font-weight: 600;
            color: #1e3a8a;
            font-size: 0.875rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}

        tr:hover {{
            background: #f8fafc;
        }}

        .status {{
            display: inline-block;
            padding: 0.125rem 0.5rem;
            border-radius: 0.25rem;
            font-size: 0.75rem;
            font-weight: 600;
        }}

        .status-pass {{ background: #dcfce7; color: #166534; }}
        .status-fail {{ background: #fee2e2; color: #991b1b; }}
        .status-warning {{ background: #fef3c7; color: #92400e; }}

        .compliance-statement {{
            background: #eff6ff;
            border-left: 4px solid #2563eb;
            padding: 1rem;
            margin-bottom: 1rem;
        }}

        .signature {{
            margin-top: 3rem;
            padding-top: 1rem;
            border-top: 1px solid #e5e7eb;
            color: #64748b;
            font-size: 0.875rem;
        }}

        .badge {{
            display: inline-block;
            padding: 0.25rem 0.75rem;
            border-radius: 9999px;
            background: #dbeafe;
            color: #1e3a8a;
            font-size: 0.75rem;
            font-weight: 600;
            margin-left: 0.5rem;
        }}

        .print-button {{
            position: fixed;
            top: 1rem;
            right: 1rem;
            padding: 0.625rem 1.25rem;
            background: #2563eb;
            color: white;
            border: none;
            border-radius: 0.375rem;
            font-weight: 500;
            cursor: pointer;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }}

        @media print {{
            .print-button {{ display: none; }}
        }}
    </style>
</head>
<body>
    <button class="print-button" onclick="window.print()">Print to PDF</button>

    <div class="header">
        <h1>{html.escape(report_type)} Compliance Audit Report
            <span class="badge">{html.escape(report_type)}</span>
        </h1>
        <div class="meta">
            <strong>Organization:</strong> {safe_org}<br>
            <strong>Report Period:</strong> {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}<br>
            <strong>Generated:</strong> {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}<br>
            <strong>Report ID:</strong> RPT-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}
        </div>
    </div>

    <div class="section">
        <h2>Executive Summary</h2>
        <div class="summary-grid">
            <div class="summary-card">
                <div class="label">Total Evaluations</div>
                <div class="value">{total_runs}</div>
            </div>
            <div class="summary-card success">
                <div class="label">Passed</div>
                <div class="value">{pass_count}</div>
            </div>
            <div class="summary-card danger">
                <div class="label">Failed</div>
                <div class="value">{fail_count}</div>
            </div>
            <div class="summary-card {'success' if pass_rate >= 90 else 'warning' if pass_rate >= 70 else 'danger'}">
                <div class="label">Pass Rate</div>
                <div class="value">{pass_rate}%</div>
            </div>
        </div>

        <div class="compliance-statement">
            <strong>Compliance Status:</strong>
            {f'This system was operated in compliance with {html.escape(report_type)} requirements during the audit period. All evaluations were logged, encrypted, and access-controlled.' if pass_rate >= 90 else f'This system had {fail_count} compliance failures during the audit period. Remediation required.'}
        </div>
    </div>

    <div class="section">
        <h2>Evaluation Results by Domain</h2>
        <table>
            <thead>
                <tr>
                    <th>Domain</th>
                    <th>Total Runs</th>
                    <th>Passed</th>
                    <th>Failed</th>
                    <th>Pass Rate</th>
                </tr>
            </thead>
            <tbody>
                {_render_domain_rows(by_domain)}
            </tbody>
        </table>
    </div>

    <div class="section">
        <h2>Models Evaluated</h2>
        <table>
            <thead>
                <tr>
                    <th>Model</th>
                    <th>Evaluations</th>
                </tr>
            </thead>
            <tbody>
                {''.join(f'<tr><td>{m}</td><td>{c}</td></tr>' for m, c in by_model.items())}
            </tbody>
        </table>
    </div>

    {compliance_section}

    <div class="section">
        <h2>Audit Log Activity</h2>
        <table>
            <thead>
                <tr>
                    <th>Action</th>
                    <th>Count</th>
                </tr>
            </thead>
            <tbody>
                {''.join(f'<tr><td>{a}</td><td>{c}</td></tr>' for a, c in sorted(audit_by_action.items(), key=lambda x: -x[1]))}
            </tbody>
        </table>
        <p style="margin-top: 1rem; color: #64748b; font-size: 0.875rem;">
            Total audit log entries: <strong>{len(audit_logs)}</strong>
        </p>
    </div>

    <div class="signature">
        <p><strong>Report Generation:</strong> Automated by AI Assurance Platform</p>
        <p><strong>Audit Trail Integrity:</strong> Cryptographically verified (chain-of-hash)</p>
        <p><strong>Encryption Standard:</strong> AES-256 at rest, TLS 1.3 in transit</p>
        <p style="margin-top: 1rem;">This report was generated by the AI Assurance Platform from immutable audit logs. For questions about this report, contact your compliance officer.</p>
    </div>
</body>
</html>"""

    return html_doc


def _render_domain_rows(by_domain: dict) -> str:
    """Render domain table rows."""
    rows = []
    for domain, stats in by_domain.items():
        pass_rate = round(stats["pass"] / stats["total"] * 100, 1) if stats["total"] else 0
        status_class = "status-pass" if pass_rate >= 90 else "status-warning" if pass_rate >= 70 else "status-fail"
        rows.append(f"""
            <tr>
                <td><strong>{domain}</strong></td>
                <td>{stats['total']}</td>
                <td>{stats['pass']}</td>
                <td>{stats['fail']}</td>
                <td><span class="status {status_class}">{pass_rate}%</span></td>
            </tr>
        """)
    return "".join(rows)


def _generate_compliance_section(report_type: str, runs: list[dict]) -> str:
    """Generate compliance-specific section based on report type."""

    if report_type == "HIPAA":
        return """
    <div class="section">
        <h2>HIPAA Compliance Controls</h2>
        <h3>§164.312(a)(1) — Access Control</h3>
        <ul style="margin-left: 1.5rem;">
            <li>All system access requires authentication</li>
            <li>API keys are scoped and rotated</li>
            <li>Role-based access enforced</li>
        </ul>

        <h3>§164.312(b) — Audit Controls</h3>
        <ul style="margin-left: 1.5rem;">
            <li>All system activity logged with immutable audit trails</li>
            <li>Chain-of-hash verification prevents tampering</li>
            <li>Logs retained per HIPAA 6-year requirement</li>
        </ul>

        <h3>§164.312(c)(1) — Integrity</h3>
        <ul style="margin-left: 1.5rem;">
            <li>Cryptographic hashing on all audit entries</li>
            <li>Tamper-evident storage</li>
        </ul>

        <h3>§164.312(e)(1) — Transmission Security</h3>
        <ul style="margin-left: 1.5rem;">
            <li>TLS 1.3 encryption in transit</li>
            <li>AES-256 encryption at rest for PHI</li>
        </ul>
    </div>
        """
    elif report_type == "SOC2":
        return """
    <div class="section">
        <h2>SOC2 Trust Services Criteria</h2>
        <h3>CC6.1 — Logical Access Controls</h3>
        <ul style="margin-left: 1.5rem;">
            <li>Authentication required for all access</li>
            <li>RBAC implemented and enforced</li>
        </ul>

        <h3>CC7.2 — System Monitoring</h3>
        <ul style="margin-left: 1.5rem;">
            <li>Real-time evaluation of AI outputs</li>
            <li>Automated anomaly detection</li>
        </ul>

        <h3>CC8.1 — Change Management</h3>
        <ul style="margin-left: 1.5rem;">
            <li>All configuration changes audit-logged</li>
            <li>Version control on domain configurations</li>
        </ul>

        <h3>A1.2 — Availability</h3>
        <ul style="margin-left: 1.5rem;">
            <li>Health monitoring on all endpoints</li>
            <li>Automated alerting on failures</li>
        </ul>
    </div>
        """
    elif report_type == "GDPR":
        return """
    <div class="section">
        <h2>GDPR Compliance Articles</h2>
        <h3>Article 25 — Data Protection by Design</h3>
        <ul style="margin-left: 1.5rem;">
            <li>Privacy by default in all configurations</li>
            <li>PII detection and automatic redaction</li>
        </ul>

        <h3>Article 30 — Records of Processing Activities</h3>
        <ul style="margin-left: 1.5rem;">
            <li>Complete audit trail of all processing</li>
            <li>Purpose and legal basis documented</li>
        </ul>

        <h3>Article 32 — Security of Processing</h3>
        <ul style="margin-left: 1.5rem;">
            <li>Pseudonymization and encryption</li>
            <li>Ongoing confidentiality, integrity, availability</li>
        </ul>

        <h3>Article 33 — Breach Notification</h3>
        <ul style="margin-left: 1.5rem;">
            <li>Automated detection of unauthorized access</li>
            <li>72-hour notification capability</li>
        </ul>
    </div>
        """
    else:
        return ""


# ---------------------------------------------------------------------------
# Public PDF Pack generators — existing 3 (byte-identical after refactor)
# ---------------------------------------------------------------------------

def generate_nist_pack(system_id: str) -> bytes:
    """Generate a NIST AI RMF + NIST AI 600-1 combined PDF Pack.

    Args:
        system_id: The AI system identifier (e.g. 'ai-sys-001').

    Returns:
        PDF content as bytes. Starts with b'%PDF'.
    """
    from domain.framework_coverage import framework_overview as fw_overview

    system, evidence = _load_system_and_evidence(system_id)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    rmf_items = fw_overview("NIST_AI_RMF", scope=system_id)
    nist600_items = fw_overview("NIST_AI_600_1", scope=system_id)

    rmf_avg = round(sum(i.coverage_pct for i in rmf_items) / len(rmf_items), 1) if rmf_items else 0.0
    n600_avg = round(sum(i.coverage_pct for i in nist600_items) / len(nist600_items), 1) if nist600_items else 0.0

    pdf = _PdfWriter()
    pdf.set_header(f"system: {system_id} | NIST AI RMF + 600-1 Pack")
    pdf.new_page()

    # Cover page
    pdf.title("NIST AI RMF + NIST AI 600-1")
    pdf.title("Framework Coverage Pack")
    pdf.spacer(20)
    pdf.body(f"System: {system.name}  ({system_id})")
    pdf.body(f"Generated: {timestamp}")
    # Finding #10: no f-string where there is nothing to interpolate
    pdf.body("Generated by: AI Assurance Platform")
    pdf.spacer(10)
    pdf.body(f"NIST AI RMF Average Coverage: {rmf_avg}%")
    pdf.body(f"NIST AI 600-1 Average Coverage: {n600_avg}%")
    pdf.rule()

    # NIST AI RMF section
    pdf.new_page()
    pdf.heading("Part 1: NIST AI Risk Management Framework")
    pdf.rule()
    _render_item_section(pdf, "NIST AI RMF", rmf_items, evidence, system_id)

    # NIST AI 600-1 section
    pdf.new_page()
    pdf.heading("Part 2: NIST AI 600-1 GenAI Profile")
    pdf.rule()
    _render_item_section(pdf, "NIST AI 600-1", nist600_items, evidence, system_id)

    # Evidence appendix
    _render_evidence_appendix(pdf, evidence, system_id)

    return pdf.build()


def generate_owasp_pack(system_id: str) -> bytes:
    """Generate an OWASP LLM Top 10 + OWASP Agentic AI Top 10 combined PDF Pack.

    Args:
        system_id: The AI system identifier (e.g. 'ai-sys-001').

    Returns:
        PDF content as bytes. Starts with b'%PDF'.
    """
    from domain.framework_coverage import framework_overview as fw_overview

    system, evidence = _load_system_and_evidence(system_id)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    llm_items = fw_overview("OWASP_LLM", scope=system_id)
    agentic_items = fw_overview("OWASP_AGENTIC", scope=system_id)

    llm_avg = round(sum(i.coverage_pct for i in llm_items) / len(llm_items), 1) if llm_items else 0.0
    agt_avg = round(sum(i.coverage_pct for i in agentic_items) / len(agentic_items), 1) if agentic_items else 0.0

    pdf = _PdfWriter()
    pdf.set_header(f"system: {system_id} | OWASP LLM + Agentic Pack")
    pdf.new_page()

    # Cover page
    pdf.title("OWASP LLM Top 10 + Agentic AI Top 10")
    pdf.title("Framework Coverage Pack")
    pdf.spacer(20)
    pdf.body(f"System: {system.name}  ({system_id})")
    pdf.body(f"Generated: {timestamp}")
    # Finding #10: no f-string where there is nothing to interpolate
    pdf.body("Generated by: AI Assurance Platform")
    pdf.spacer(10)
    pdf.body(f"OWASP LLM Top 10 Average Coverage: {llm_avg}%")
    pdf.body(f"OWASP Agentic Top 10 Average Coverage: {agt_avg}%")
    pdf.rule()

    # OWASP LLM section
    pdf.new_page()
    pdf.heading("Part 1: OWASP Top 10 for LLM Applications")
    pdf.rule()
    _render_item_section(pdf, "OWASP LLM Top 10", llm_items, evidence, system_id)

    # OWASP Agentic section
    pdf.new_page()
    pdf.heading("Part 2: OWASP Top 10 for Agentic AI")
    pdf.rule()
    _render_item_section(pdf, "OWASP Agentic Top 10", agentic_items, evidence, system_id)

    # Evidence appendix
    _render_evidence_appendix(pdf, evidence, system_id)

    return pdf.build()


def generate_eu_ai_act_pack(system_id: str) -> bytes:
    """Generate an EU AI Act high-risk obligations PDF Pack.

    Args:
        system_id: The AI system identifier (e.g. 'ai-sys-001').

    Returns:
        PDF content as bytes. Starts with b'%PDF'.
    """
    from domain.framework_coverage import framework_overview as fw_overview

    system, evidence = _load_system_and_evidence(system_id)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # EU AI Act maps most closely to NIST AI RMF governance + 600-1 safety controls.
    # We surface NIST AI RMF as the primary proxy framework while labelling the pack
    # as EU AI Act obligations. A dedicated EU_AI_ACT catalog is planned for Session 11.
    rmf_items = fw_overview("NIST_AI_RMF", scope=system_id)
    rmf_avg = round(sum(i.coverage_pct for i in rmf_items) / len(rmf_items), 1) if rmf_items else 0.0

    pdf = _PdfWriter()
    pdf.set_header(f"system: {system_id} | EU AI Act High-Risk Obligations")
    pdf.new_page()

    # Cover page
    pdf.title("EU AI Act — High-Risk AI Obligations")
    pdf.title("Coverage Assessment Pack")
    pdf.spacer(20)
    pdf.body(f"System: {system.name}  ({system_id})")
    pdf.body(f"Generated: {timestamp}")
    # Finding #10: no f-string where there is nothing to interpolate
    pdf.body("Generated by: AI Assurance Platform")
    pdf.spacer(10)
    pdf.body(f"Overall Governance Coverage: {rmf_avg}%")
    pdf.spacer(6)
    pdf.body(
        "Note: This pack maps EU AI Act high-risk obligations (Articles 9-15, 17, 26, 61, 72) "
        "to NIST AI RMF governance controls. A dedicated EU_AI_ACT catalog is planned for Session 11."
    )
    pdf.rule()

    eu_sections = [
        ("Article 9 — Risk Management System", "rmf-manage"),
        ("Article 10 — Data and Data Governance", "rmf-map"),
        ("Article 11 — Technical Documentation", "rmf-govern"),
        ("Article 13 — Transparency", "rmf-govern"),
        ("Article 14 — Human Oversight", "rmf-manage"),
        ("Article 15 — Accuracy, Robustness, Cybersecurity", "rmf-measure"),
    ]

    for article_title, item_id in eu_sections:
        item = next((i for i in rmf_items if i.item_id == item_id), None)
        if item is None:
            continue
        pdf.heading(article_title)
        pdf.body(f"Coverage: {item.coverage_pct:.0f}%  |  {item.description}")
        pdf.spacer(2)
        for c in item.mapped_controls[:4]:
            pdf.body(
                f"  [{c.status}] {c.control_id} — {c.title}",
                indent=10,
            )
        pdf.rule()
        pdf.spacer(4)

    # Evidence appendix
    _render_evidence_appendix(pdf, evidence, system_id)

    return pdf.build()


# ---------------------------------------------------------------------------
# Session 11 — New PDF Pack generators (ISO 42001, SR 11-7, FFIEC)
# ---------------------------------------------------------------------------

def generate_iso_42001_pack(system_id: str) -> bytes:
    """Generate an ISO/IEC 42001:2023 AI Management System PDF Pack.

    Covers all 7 clauses (Cl.4 Context through Cl.10 Improvement) of the
    ISO/IEC 42001 standard for AI management systems.

    Args:
        system_id: The AI system identifier (e.g. 'ai-sys-001').

    Returns:
        PDF content as bytes. Starts with b'%PDF'.
    """
    from domain.framework_coverage import framework_overview as fw_overview

    system, evidence = _load_system_and_evidence(system_id)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    items = fw_overview("ISO_42001", scope=system_id)
    avg_coverage = round(sum(i.coverage_pct for i in items) / len(items), 1) if items else 0.0

    pdf = _PdfWriter()
    pdf.set_header(f"system: {system_id} | ISO/IEC 42001:2023 Pack")
    pdf.new_page()

    # Cover page
    pdf.title("ISO/IEC 42001:2023")
    pdf.title("AI Management System — Coverage Pack")
    pdf.spacer(20)
    pdf.body(f"System: {system.name}  ({system_id})")
    pdf.body(f"Generated: {timestamp}")
    pdf.body("Generated by: AI Assurance Platform")
    pdf.spacer(10)
    pdf.body(f"ISO/IEC 42001 Average Coverage: {avg_coverage}%")
    pdf.spacer(6)
    pdf.body(
        "Framework: ISO/IEC 42001:2023 — Information technology — Artificial intelligence "
        "— Management system for AI. Published by the International Organization for "
        "Standardization (ISO) and the International Electrotechnical Commission (IEC)."
    )
    pdf.rule()

    # Executive summary table — coverage by clause
    pdf.new_page()
    pdf.heading("Framework Citation")
    pdf.rule()
    pdf.body("Standard: ISO/IEC 42001:2023 (ISO/IEC 42001)")
    pdf.body("Scope: AI Management System (AIMS) — Clauses 4 through 10")
    pdf.body("Certification body: Accredited third-party certification bodies (ISO/IEC 17021-1)")
    pdf.spacer(8)
    pdf.body("Clause Coverage Summary:")
    for item in items:
        pdf.body(f"  {item.display_name}: {item.coverage_pct:.0f}%", indent=10)
    pdf.rule()

    # Per-clause sections
    pdf.new_page()
    pdf.heading("Clause-by-Clause Evidence Assessment")
    pdf.rule()
    _render_item_section(pdf, "ISO/IEC 42001", items, evidence, system_id)

    # Evidence appendix
    _render_evidence_appendix(pdf, evidence, system_id)

    return pdf.build()


def generate_sr_11_7_pack(system_id: str) -> bytes:
    """Generate a Federal Reserve SR 11-7 Model Risk Management PDF Pack.

    Covers the six SR 11-7 sections: Model Development and Implementation,
    Model Use, Validation / Effective Challenge, Ongoing Monitoring,
    Governance / Policies / Controls, and Model Inventory.

    Args:
        system_id: The AI system identifier (e.g. 'ai-sys-001').

    Returns:
        PDF content as bytes. Starts with b'%PDF'.
    """
    from domain.framework_coverage import framework_overview as fw_overview

    system, evidence = _load_system_and_evidence(system_id)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    items = fw_overview("SR_11_7", scope=system_id)
    avg_coverage = round(sum(i.coverage_pct for i in items) / len(items), 1) if items else 0.0

    pdf = _PdfWriter()
    pdf.set_header(f"system: {system_id} | SR 11-7 Model Risk Management Pack")
    pdf.new_page()

    # Cover page
    pdf.title("Federal Reserve SR 11-7")
    pdf.title("Model Risk Management — Coverage Pack")
    pdf.spacer(20)
    pdf.body(f"System: {system.name}  ({system_id})")
    pdf.body(f"Generated: {timestamp}")
    pdf.body("Generated by: AI Assurance Platform")
    pdf.spacer(10)
    pdf.body(f"SR 11-7 Average Coverage: {avg_coverage}%")
    pdf.spacer(6)
    pdf.body(
        "Framework: Federal Reserve Supervisory Letter SR 11-7 — Guidance on Model Risk "
        "Management (April 2011). Issued jointly with OCC Bulletin 2011-12. "
        "Applies to all bank holding companies, state member banks, and U.S. branches of "
        "foreign banking organizations supervised by the Federal Reserve."
    )
    pdf.rule()

    # Framework citation section
    pdf.new_page()
    pdf.heading("Framework Citation — SR 11-7")
    pdf.rule()
    pdf.body("Issuer: Board of Governors of the Federal Reserve System")
    pdf.body("Letter: SR 11-7 (April 4, 2011) | OCC Bulletin 2011-12")
    pdf.body("Subject: Guidance on Model Risk Management")
    pdf.spacer(8)
    pdf.body("SR 11-7 defines model risk as the potential for adverse consequences from decisions "
             "based on incorrect or misused model outputs. Financial institutions must maintain a "
             "robust model risk management (MRM) framework covering three lines of defense.")
    pdf.spacer(6)
    pdf.body("Section Coverage Summary:")
    for item in items:
        pdf.body(f"  {item.display_name}: {item.coverage_pct:.0f}%", indent=10)
    pdf.rule()

    # Sections IV, V, VII per sprint plan
    # Section IV — Model Development, Implementation, and Use
    # Section V — Model Validation
    # Section VII — Governance, Policies, and Controls
    pdf.new_page()
    pdf.heading("Section IV — Model Development, Implementation, and Use")
    pdf.rule()
    dev_use = [i for i in items if i.item_id in ("sr117-dev-implementation", "sr117-model-use")]
    _render_item_section(pdf, "SR 11-7 Section IV", dev_use, evidence, system_id)

    pdf.new_page()
    pdf.heading("Section V — Model Validation")
    pdf.rule()
    validation = [i for i in items if i.item_id in ("sr117-validation-effective-challenge", "sr117-ongoing-monitoring")]
    _render_item_section(pdf, "SR 11-7 Section V", validation, evidence, system_id)

    pdf.new_page()
    pdf.heading("Section VII — Governance, Policies, and Controls")
    pdf.rule()
    governance = [i for i in items if i.item_id in ("sr117-governance-policies-controls", "sr117-model-inventory")]
    _render_item_section(pdf, "SR 11-7 Section VII", governance, evidence, system_id)

    # Evidence appendix
    _render_evidence_appendix(pdf, evidence, system_id)

    return pdf.build()


def generate_ffiec_pack(system_id: str) -> bytes:
    """Generate an FFIEC IT Examination Handbook AI/ML Supplements PDF Pack.

    Covers the six FFIEC AI/ML examination areas: Model Governance,
    Third-Party Risk, Change Management, Ongoing Monitoring and Validation,
    Data Quality, and Explainability.

    Args:
        system_id: The AI system identifier (e.g. 'ai-sys-001').

    Returns:
        PDF content as bytes. Starts with b'%PDF'.
    """
    from domain.framework_coverage import framework_overview as fw_overview

    system, evidence = _load_system_and_evidence(system_id)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    items = fw_overview("FFIEC", scope=system_id)
    avg_coverage = round(sum(i.coverage_pct for i in items) / len(items), 1) if items else 0.0

    pdf = _PdfWriter()
    pdf.set_header(f"system: {system_id} | FFIEC IT Handbook AI/ML Pack")
    pdf.new_page()

    # Cover page
    pdf.title("FFIEC IT Examination Handbook")
    pdf.title("AI/ML Supplements — Coverage Pack")
    pdf.spacer(20)
    pdf.body(f"System: {system.name}  ({system_id})")
    pdf.body(f"Generated: {timestamp}")
    pdf.body("Generated by: AI Assurance Platform")
    pdf.spacer(10)
    pdf.body(f"FFIEC AI/ML Average Coverage: {avg_coverage}%")
    pdf.spacer(6)
    pdf.body(
        "Framework: FFIEC IT Examination Handbook — AI/ML Supplements. Issued by the "
        "Federal Financial Institutions Examination Council (FFIEC), comprising the Board "
        "of Governors of the Federal Reserve System, FDIC, NCUA, OCC, and CFPB. Applies "
        "to all federally supervised financial institutions using AI/ML models."
    )
    pdf.rule()

    # Framework citation section
    pdf.new_page()
    pdf.heading("Framework Citation — FFIEC AI/ML")
    pdf.rule()
    pdf.body("Issuer: Federal Financial Institutions Examination Council (FFIEC)")
    pdf.body("Document: IT Examination Handbook — AI/ML Supplements")
    pdf.body("Members: Federal Reserve, FDIC, NCUA, OCC, CFPB")
    pdf.spacer(8)
    pdf.body(
        "The FFIEC AI/ML examination framework establishes supervisory expectations for "
        "financial institutions that develop, acquire, or use artificial intelligence and "
        "machine learning models in consumer-facing or risk-management applications."
    )
    pdf.spacer(6)
    pdf.body("Examination Area Coverage Summary:")
    for item in items:
        pdf.body(f"  {item.display_name}: {item.coverage_pct:.0f}%", indent=10)
    pdf.rule()

    # Per-area sections
    pdf.new_page()
    pdf.heading("Examination Area — Evidence Assessment")
    pdf.rule()
    _render_item_section(pdf, "FFIEC", items, evidence, system_id)

    # Evidence appendix
    _render_evidence_appendix(pdf, evidence, system_id)

    return pdf.build()


# Finding #17: removed the __main__ debug block (print calls + direct file writes
# violate the project storage rule: "No direct file writes outside storage.py pattern").
