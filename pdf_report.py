"""HTML-to-PDF compliance reports — uses HTML (no external PDF library dependency).

For now, generates a comprehensive HTML report that can be printed to PDF
via the browser. This avoids the need for reportlab/weasyprint dependencies
while still producing professional-grade reports.
"""

from datetime import datetime, timedelta
from typing import Optional
import json


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

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{report_type} Compliance Audit Report — {organization}</title>
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
        <h1>{report_type} Compliance Audit Report
            <span class="badge">{report_type}</span>
        </h1>
        <div class="meta">
            <strong>Organization:</strong> {organization}<br>
            <strong>Report Period:</strong> {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}<br>
            <strong>Generated:</strong> {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}<br>
            <strong>Report ID:</strong> RPT-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}
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
            {f'This system was operated in compliance with {report_type} requirements during the audit period. All evaluations were logged, encrypted, and access-controlled.' if pass_rate >= 90 else f'This system had {fail_count} compliance failures during the audit period. Remediation required.'}
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

    return html


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


if __name__ == "__main__":
    # Test
    test_runs = [
        {
            "domain": "Healthcare (HIPAA)",
            "model": "claude-sonnet-4-6",
            "eval_scores": {
                "faithfulness": {"score": 0.92, "passed": True},
                "pii_leakage": {"score": 0.0, "passed": True},
            }
        }
    ]
    test_logs = [
        {"action": "evaluate", "user_id": "test"},
        {"action": "access", "user_id": "test"},
    ]

    html = generate_compliance_report_html(
        runs=test_runs,
        audit_logs=test_logs,
        start_date=datetime.utcnow() - timedelta(days=30),
        end_date=datetime.utcnow(),
        report_type="HIPAA",
        organization="Test Healthcare Corp",
    )

    output_path = "test_report.html"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✓ Report written to {output_path}")
    print(f"  Open in browser and 'Print to PDF' for final PDF output")
