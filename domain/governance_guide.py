"""AI Governance Assistant content.

Static page-context guidance + glossary + dynamic lookups against the
existing control library and framework catalog. NOT a chatbot — every answer
is structured content authored against the platform's operating model.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Optional

from domain.controls import CONTROLS, CONTROLS_BY_ID
from domain.framework_coverage import (
    NIST_RMF_ITEMS, NIST_600_1_ITEMS, OWASP_LLM_ITEMS, OWASP_AGENTIC_ITEMS,
)


# ===========================================================================
# Page guides — one static guide per primary page
# ===========================================================================

@dataclass
class PageGuide:
    page: str
    title: str
    primary_question: str
    what_it_means: str
    frameworks: list[str]
    next_actions: list[str]
    blocks_production: list[str]
    required_evidence: list[str]
    recommended_remediation: list[str]
    see_also: list[dict] = field(default_factory=list)


PAGE_GUIDES: dict[str, PageGuide] = {
    "/": PageGuide(
        page="/",
        title="Overview — Command Center",
        primary_question="Can each AI system safely operate in production?",
        what_it_means=(
            "Portfolio-wide view of every AI system under governance. Every metric "
            "ties to a real AI system, control, finding, gate, evidence record, or "
            "runtime event — there are no vanity numbers. The release-gate split + "
            "open-finding counts answer the primary question for the whole portfolio "
            "in one glance."
        ),
        frameworks=["NIST AI RMF (MEASURE-2 / MANAGE-2)", "NIST AI 600-1 (Governance)"],
        next_actions=[
            "Open the system with the highest needs-attention score in the Reports panel.",
            "Resolve open CRITICAL findings — each one is a release blocker.",
            "Address SLA-breached findings before they become incidents.",
        ],
        blocks_production=[
            "Any system with an open P0/CRITICAL finding → release HOLD.",
            "Any system whose RG-001 / RG-002 / RG-005 fail → production blocked.",
        ],
        required_evidence=[
            "Every governed system carries an Assessment record (PRE_RELEASE or QUARTERLY).",
            "Approval records from AI Governance, CRO, CISO before production rollout.",
        ],
        recommended_remediation=[
            "Use the Next Actions panel as your daily work queue.",
            "Triage Runtime Security alerts from the notification center first.",
        ],
        see_also=[
            {"label": "AI Systems Inventory", "href": "/ai-systems"},
            {"label": "Reports → Executive AI Risk", "href": "/reports"},
        ],
    ),
    "/ai-systems": PageGuide(
        page="/ai-systems",
        title="AI Systems Inventory",
        primary_question="Which AI systems are under governance and what is each one's release posture?",
        what_it_means=(
            "Every AI system in scope — production, pilot, staged, or in design. "
            "Each row carries business + technical owner, regulatory exposure, "
            "autonomy level, inherent + residual risk, and the current release "
            "decision. New systems enter governance through the Intake workflow."
        ),
        frameworks=[
            "NIST AI RMF — MAP-1 (system context) + MAP-2 (categorization)",
            "NIST AI 600-1 — Governance & Documentation",
            "FS overlay — AI-009 (model version pinning), AI-010 (data lineage)",
        ],
        next_actions=[
            "Open a system to view its assessment + open findings + release gates.",
            "Register a new AI system via the intake form to start governance.",
            "Confirm business + technical owner are current for every system.",
        ],
        blocks_production=[
            "Missing business or technical owner.",
            "Inherent risk = CRITICAL without compensating HITL.",
        ],
        required_evidence=[
            "ARCHITECTURE_DIAGRAM — required for every system before pilot.",
            "MODEL_CARD — required for any FS-domain model.",
            "DATA_LINEAGE — required when DataClass contains PII / NPI / PCI / SAR / KYC.",
        ],
        recommended_remediation=[
            "Run the Assessment Engine on each system to refresh the release decision.",
            "Capture missing evidence via the Evidence repository.",
        ],
        see_also=[
            {"label": "Register new AI system", "href": "/ai-systems/new"},
            {"label": "Assessment engine", "href": "/assessment"},
        ],
    ),
    "/governance": PageGuide(
        page="/governance",
        title="Governance — Framework Coverage",
        primary_question="How well does each AI system satisfy NIST AI RMF and the GenAI Profile (600-1)?",
        what_it_means=(
            "Live coverage across NIST AI RMF (Govern / Map / Measure / Manage) and "
            "the NIST AI 600-1 GenAI Profile. Coverage is derived from real control "
            "evaluations on each AI system, not a survey. Items show pass / partial / "
            "fail / no-evidence based on the engine's per-control output."
        ),
        frameworks=[
            "NIST AI RMF 1.0 — GOVERN, MAP, MEASURE, MANAGE",
            "NIST AI 600-1 — GenAI Profile (9 risk areas)",
        ],
        next_actions=[
            "Open any framework item to see which controls map to it.",
            "Click a failing item to drill into the underlying findings + evidence gaps.",
            "Reassess systems whose framework coverage dropped below 70%.",
        ],
        blocks_production=[
            "NIST RMF GOVERN-1.1 (policies + accountability) → P0 if missing.",
            "AI 600-1 GAI-2.1 (data privacy) → P0 for systems with PII/NPI.",
        ],
        required_evidence=[
            "POLICY_ATTESTATION for governance controls.",
            "EVAL_RUN for measure-stage controls.",
            "AUDIT_LOG for manage-stage controls.",
        ],
        recommended_remediation=[
            "For each red framework item: open the mapped controls, attach evidence.",
            "Re-run the assessment after evidence is attached — coverage updates immediately.",
        ],
        see_also=[
            {"label": "Security — OWASP LLM + Agentic", "href": "/security"},
            {"label": "Reports → Framework Coverage", "href": "/reports"},
        ],
    ),
    "/security": PageGuide(
        page="/security",
        title="Security — OWASP LLM + Agentic AI Top 10",
        primary_question="Is each AI system defended against the OWASP LLM Top 10 and the Agentic AI Top 10?",
        what_it_means=(
            "Live coverage across OWASP LLM Top 10 (2025) and OWASP Agentic AI Top 10. "
            "Failing items mean either a confirmed exploit (red-team or runtime), "
            "an open finding mapped to the item, or missing eval evidence."
        ),
        frameworks=[
            "OWASP LLM Top 10 (2025) — LLM01..LLM10",
            "OWASP Agentic AI Top 10 — AAI-01..AAI-10",
        ],
        next_actions=[
            "Open LLM01 to see prompt-injection posture across systems.",
            "Re-run the Garak / PyRIT eval connectors after each remediation.",
            "Investigate any item showing red-team confirmed exploits.",
        ],
        blocks_production=[
            "LLM01 (prompt injection) eval below 95% → R-Hold-PromptInjection-Low.",
            "LLM02 (sensitive info disclosure) — failing PII eval → R-Hold-PII-Eval.",
            "AAI-04 (tool misuse) — failing tool-authz eval → R-Hold-UnauthorizedToolCall.",
        ],
        required_evidence=[
            "GARAK_REPORT — required to close prompt-injection / jailbreak items.",
            "PYRIT_REPORT — required to close tool-authorization items.",
            "RED_TEAM_REPORT — required for high-risk customer-facing systems.",
        ],
        recommended_remediation=[
            "Move tool authorization out of the model prompt into a separate authz service.",
            "Add a DLP regex pre-filter at output layer to catch SSN / account-number leaks.",
            "Sanitize HTML / markdown from retrieved RAG chunks to prevent indirect injection.",
        ],
        see_also=[
            {"label": "Findings — open security issues", "href": "/findings"},
            {"label": "Runtime — live event stream", "href": "/runtime"},
        ],
    ),
    "/runtime": PageGuide(
        page="/runtime",
        title="Runtime Governance & Telemetry",
        primary_question="What is each production AI system doing right now — and are guardrails holding?",
        what_it_means=(
            "Live event stream from Langfuse, AWS CloudTrail / Security Hub / Macie / "
            "GuardDuty, Bedrock Guardrails, and policy gateways. The page surfaces "
            "every prompt-injection block, PII leak block, unauthorized tool call, "
            "policy violation, and HITL escalation — each event mapped to the "
            "control and framework it informs."
        ),
        frameworks=[
            "NIST AI RMF — MANAGE-2.3 (real-time monitoring)",
            "AWS controls — IAM, CloudTrail, Security Hub, Macie, GuardDuty",
        ],
        next_actions=[
            "Triage any HIGH/CRITICAL runtime event in the last 24 hours.",
            "If a guardrail is firing repeatedly, capture the pattern as a finding.",
            "Use the system kill switch to halt a misbehaving agent immediately.",
        ],
        blocks_production=[
            "Recurring prompt-injection bypass on a system with side-effect tools.",
            "PII/NPI leak that wasn't caught by Macie → P0.",
            "Unauthorized tool call against a customer-facing system → P0.",
        ],
        required_evidence=[
            "RUNTIME_TELEMETRY — Langfuse trace + AWS CloudTrail event.",
            "MACIE_FINDING / SECURITY_HUB_FINDING — for any DLP detection.",
        ],
        recommended_remediation=[
            "Activate kill switch on the affected system → declare incident.",
            "Add the event to a finding; assign owner with 24h SLA for CRITICAL.",
            "Tighten the guardrail or policy; re-run the relevant eval suite.",
        ],
        see_also=[
            {"label": "Findings", "href": "/findings"},
            {"label": "Policies", "href": "/policies"},
        ],
    ),
    "/evals": PageGuide(
        page="/evals",
        title="Evaluation Suite",
        primary_question="Do the evals running against each system meet release-gate thresholds?",
        what_it_means=(
            "Evals are not vanity benchmarks — every eval has a threshold and a "
            "release-impact. Failing PII / prompt-injection / tool-authorization "
            "evals directly produce release HOLD decisions via the Release Gate Engine."
        ),
        frameworks=[
            "NIST AI RMF — MEASURE-2 (test & evaluation)",
            "OWASP LLM Top 10 — LLM01, LLM02, LLM06, LLM08, LLM09",
            "OWASP Agentic Top 10 — AAI-04 (tool misuse), AAI-02 (prompt injection)",
        ],
        next_actions=[
            "Run the simulated eval suite for any system that hasn't been evaluated.",
            "Investigate failing evals → open finding, attach as evidence.",
            "Re-run evals after every prompt / tool / guardrail change.",
        ],
        blocks_production=[
            "PII_LEAKAGE eval status = FAIL → R-Hold-PII-Eval.",
            "PROMPT_INJECTION score < 95% → R-Hold-PromptInjection-Low.",
            "TOOL_AUTHORIZATION status = FAIL → R-Hold-UnauthorizedToolCall.",
        ],
        required_evidence=[
            "EVAL_RUN record for each EvalType.",
            "GARAK_REPORT / PYRIT_REPORT / LANGFUSE_TRACE as supporting artifacts.",
        ],
        recommended_remediation=[
            "If PI is low, harden instruction isolation + sanitize RAG inputs.",
            "If tool-authz fails, move authz out of the model prompt.",
            "If PII leakage trips, add output-side regex filter + Macie scan.",
        ],
        see_also=[
            {"label": "Connectors — DeepEval / Garak / PyRIT", "href": "/connectors"},
            {"label": "Release Gates — how evals trigger holds", "href": "/release-gates"},
        ],
    ),
    "/findings": PageGuide(
        page="/findings",
        title="Findings & Remediation",
        primary_question="Which open issues are blocking a system from production?",
        what_it_means=(
            "Each finding maps to ≥1 control and ≥1 framework, and where relevant, "
            "to specific release gates. Severity reflects exploitability + impact; "
            "release-impact (BLOCK_PRODUCTION / BLOCK_PILOT / WARNING / NO_IMPACT) "
            "is the gating signal. Workflow: OPEN → IN_PROGRESS → REMEDIATED → VERIFIED → CLOSED."
        ),
        frameworks=["NIST AI RMF — MANAGE-1", "AI-024 — finding lifecycle (FS overlay)"],
        next_actions=[
            "Open every CRITICAL → assign owner with 24h SLA.",
            "For HIGH findings on systems with HITL, you can ship as Conditional Pilot.",
            "Verify remediation with a control re-evaluation before closing.",
        ],
        blocks_production=[
            "Any open finding where severity = CRITICAL → release HOLD.",
            "Any open finding where release_impact = BLOCK_PRODUCTION on a HOLD system.",
        ],
        required_evidence=[
            "Each closed finding requires REMEDIATION_VERIFICATION.",
            "Risk-accepted findings require an EXCEPTION_WAIVER (≤90 days, AI-039).",
        ],
        recommended_remediation=[
            "Severity CRITICAL: route to a P0 incident channel — 24h SLA, daily standup.",
            "Severity HIGH: 7-day SLA; OK to operate under Conditional Pilot with HITL.",
            "Severity MEDIUM: 30-day SLA; can run in production with compensating controls.",
        ],
        see_also=[
            {"label": "Release Gates", "href": "/release-gates"},
            {"label": "Policies — waivers", "href": "/policies"},
        ],
    ),
    "/release-gates": PageGuide(
        page="/release-gates",
        title="Release Gates",
        primary_question="Why is this AI system blocked from production — and what unblocks it?",
        what_it_means=(
            "Ten deterministic release gates (RG-001 through RG-010) evaluate every "
            "system against PII leakage, prompt injection, RAG security, tool authz, "
            "human approval, critical findings, evidence completeness, runtime "
            "monitoring, AWS telemetry, and audit-trail integrity. A gate FAIL "
            "produces R-Hold-* decisions. Time-bound exception waivers can override "
            "a FAIL → WARNING (capped at 90 days under AI-039)."
        ),
        frameworks=[
            "Each gate carries an explicit mapping to NIST AI RMF + AI 600-1 + OWASP",
            "FS overlay — AI-031 (release gate enforcement), AI-039 (waiver TTL)",
        ],
        next_actions=[
            "Open the failing gate to see its mapped controls + required remediation.",
            "Run an evaluation cycle after each fix to re-evaluate the gate.",
            "If a fix isn't possible in time, file an exception waiver with compensating controls.",
        ],
        blocks_production=[
            "Any P0 gate FAIL with blocking=True → production HOLD.",
            "Three or more gates failing simultaneously → REJECT (re-architect).",
        ],
        required_evidence=[
            "Each gate has its own list of required evidence types (see gate detail).",
            "Waivers require: reason, risk_acceptor, role, expires_at (≤90d), compensating_controls.",
        ],
        recommended_remediation=[
            "RG-001 (PII): output regex filter + Macie scan + DLP eval re-run.",
            "RG-002 (prompt injection): instruction isolation + sanitize RAG inputs.",
            "RG-004 (tool authz): move authz out of model prompt; dual-key on side-effect tools.",
            "RG-005 (HITL): make HITL gate a separate service outside the agent loop.",
        ],
        see_also=[
            {"label": "Findings — open blockers", "href": "/findings"},
            {"label": "Policies — waiver registry", "href": "/policies"},
        ],
    ),
    "/evidence": PageGuide(
        page="/evidence",
        title="Audit Evidence Repository",
        primary_question="Do we have the evidence an external auditor would require for every system?",
        what_it_means=(
            "Audit-ready evidence indexed into 8 sections (Assessment, Eval, Runtime, "
            "Approval, Architecture, Model, Versions, Waiver) with 4-axis completeness "
            "(by system, framework, control domain, release gate). Each evidence "
            "record carries linked control_ids, finding_ids, and frameworks."
        ),
        frameworks=[
            "NIST AI RMF — GOVERN-1.5 (documentation), MEASURE-3.3 (auditability)",
            "SOC2 — CC4 (monitoring), CC7 (incident response)",
            "FS overlay — AI-037 (audit completeness)",
        ],
        next_actions=[
            "Identify sections at <85% completeness — those are audit risk.",
            "For each missing evidence type, attach the artifact via the connector that produces it.",
            "Cross-check evidence has linked_control_ids + linked_finding_ids set.",
        ],
        blocks_production=[
            "Evidence completeness < 85% for a P0 control → HOLD.",
            "Missing AUDIT_LOG for any production system → P0.",
        ],
        required_evidence=[
            "Architecture diagram, IAM policy snapshot, model card, eval runs, audit logs.",
            "AWS-specific: BEDROCK_CONFIG, MACIE_FINDING, SECURITY_HUB_FINDING, CLOUDTRAIL_EVENT.",
            "Version records: PROMPT_VERSION_RECORD, TOOL_VERSION_RECORD, POLICY_VERSION_RECORD.",
        ],
        recommended_remediation=[
            "Run sync on Langfuse, Macie, CloudTrail, Security Hub connectors.",
            "Capture the Bedrock guardrail config as an evidence artifact.",
            "Pin model + prompt + tool versions in deploy manifest; export as evidence.",
        ],
        see_also=[
            {"label": "Connectors — AWS telemetry", "href": "/connectors"},
            {"label": "Reports → Audit Evidence", "href": "/reports"},
        ],
    ),
    "/policies": PageGuide(
        page="/policies",
        title="Policy Control Library",
        primary_question="Which automated and manual policies are enforced — and which systems do they apply to?",
        what_it_means=(
            "Catalog of the 40 controls (AI-001..AI-040) that make up the FS overlay, "
            "plus the OWASP / NIST framework mappings for each. Each control specifies "
            "its applicability predicate, evidence requirements, machine-evaluable "
            "gate expression, failure impact, and recommended owner role."
        ),
        frameworks=[
            "FS overlay — AI-001..AI-040 (40 controls)",
            "Maps to NIST AI RMF, AI 600-1, OWASP LLM Top 10, OWASP Agentic Top 10",
        ],
        next_actions=[
            "Open a control to see its full requirement + gate expression + framework mappings.",
            "Check which systems each control is applicable to via the Applicability predicate.",
            "Review the waiver registry for any controls currently in exception state.",
        ],
        blocks_production=[
            "P0 controls (AI-001 PII, AI-006 tool authz, AI-007 HITL) are always blocking.",
            "Controls with an active waiver convert FAIL → WARNING (non-blocking).",
        ],
        required_evidence=[
            "Every control lists `evidence_required: list[EvidenceType]`.",
            "Active waivers must reference compensating controls.",
        ],
        recommended_remediation=[
            "If a control is consistently failing across systems, raise its priority + re-train teams.",
            "Cap waivers at 90 days (AI-039); auto-expire and re-evaluate.",
        ],
        see_also=[
            {"label": "Governance — framework coverage", "href": "/governance"},
            {"label": "Findings — open control failures", "href": "/findings"},
        ],
    ),
    "/reports": PageGuide(
        page="/reports",
        title="Reports — Executive + Audit Views",
        primary_question="What report do I hand the CRO, AI Governance Board, or Internal Audit?",
        what_it_means=(
            "Six structured reports: Executive AI Risk (portfolio), AI System Assessment "
            "(per system), Release Gate, Framework Coverage, Findings & Remediation, "
            "and Audit Evidence. Each report includes system summary, owners, "
            "classification, framework coverage, failed controls, evals, release "
            "decision, open findings, remediation plan, evidence, approvals, exceptions. "
            "All three export formats are supported: PDF (print HTML), CSV, JSON."
        ),
        frameworks=[
            "NIST AI RMF — GOVERN-1.5 (documentation)",
            "FS overlay — AI-036, AI-037, AI-040 (reporting and audit packs)",
        ],
        next_actions=[
            "For Board meetings: Executive AI Risk Report.",
            "For external auditor: Audit Evidence Report per system + Findings Report.",
            "For an MRM review: AI System Assessment Report.",
        ],
        blocks_production=[
            "Missing Executive Approval Record → cannot promote a system to production.",
        ],
        required_evidence=[
            "Each report is itself an evidence artifact when archived.",
            "PDF view captures the report as printed; CSV exports the primary table.",
        ],
        recommended_remediation=[
            "Schedule quarterly Executive Report distribution to the AI Governance Board.",
            "Archive the per-system Audit Evidence Report at every production release.",
        ],
        see_also=[
            {"label": "Overview", "href": "/"},
            {"label": "Audit Evidence", "href": "/evidence"},
        ],
    ),
    "/demo": PageGuide(
        page="/demo",
        title="Guided FS Demo Walkthrough",
        primary_question="How does the platform handle a regulated FS AI system end-to-end?",
        what_it_means=(
            "13-step walkthrough of the Payments Exception Review Agent on AWS Bedrock — "
            "from intake → risk classification → controls → assessment → findings → "
            "evals → gate failure → HOLD → remediation → re-assessment → Conditional Pilot. "
            "Every step runs live against the real engines."
        ),
        frameworks=["Demonstrates the full FS overlay + NIST RMF + OWASP coverage end-to-end."],
        next_actions=[
            "Hit 'Run All Steps' for a one-click full demo.",
            "Step into individual stages to deep-link into the relevant page.",
            "Use 'Reset Demo' to wipe overlay state before a fresh walkthrough.",
        ],
        blocks_production=[
            "Step 8 demonstrates the HOLD decision — what production-readiness failure looks like.",
        ],
        required_evidence=["Step 10 attaches the evidence required to flip the decision."],
        recommended_remediation=["Step 11 closes the CRITICAL finding via the workflow."],
        see_also=[{"label": "Reports", "href": "/reports"}, {"label": "Connectors", "href": "/connectors"}],
    ),
    "/connectors": PageGuide(
        page="/connectors",
        title="Connectors — External Tool Adapters",
        primary_question="Which external tools feed the assurance object model — and what do they produce?",
        what_it_means=(
            "Adapters that normalize external eval, security-test, observability, "
            "and AWS-telemetry tools into the four canonical objects: Eval, Finding, "
            "Runtime Event, Evidence. Five categories: Eval (DeepEval, Ragas), "
            "Security Test (Garak, PyRIT), Observability (Langfuse), Guardrail "
            "(NeMo), Cloud Telemetry (CloudTrail, Security Hub, Macie, GuardDuty)."
        ),
        frameworks=[
            "FS overlay — AI-033 (AWS telemetry ingestion)",
            "AI-034 (eval connector evidence)",
        ],
        next_actions=[
            "Run sync on each connector to produce fresh artifacts.",
            "Open a connector's results to see the records it has produced.",
            "Use 'Sync All' before assembling an audit pack.",
        ],
        blocks_production=[
            "AWS telemetry connectors (CloudTrail, Security Hub) must be syncing → RG-009.",
            "Eval connectors must produce recent EVAL_RUN evidence to satisfy RG-007.",
        ],
        required_evidence=[
            "Each connector's sync produces RUNTIME_TELEMETRY / EVAL_RUN / EVIDENCE records.",
        ],
        recommended_remediation=[
            "If a connector stops syncing, raise it as a runtime incident.",
            "Replace placeholder pulls with real SDK calls before production use.",
        ],
        see_also=[{"label": "Evidence", "href": "/evidence"}, {"label": "Runtime", "href": "/runtime"}],
    ),
    "/assessment": PageGuide(
        page="/assessment",
        title="Assessment Engine",
        primary_question="What is the structured assessment for this AI system?",
        what_it_means=(
            "Runs the full assessment pipeline against live data: classifies inherent "
            "risk, evaluates every applicable control, generates findings for failed "
            "controls, computes residual-risk score, framework coverage, evidence "
            "completeness, and produces a release recommendation with rule fired + "
            "rationale + conditions."
        ),
        frameworks=[
            "NIST AI RMF — MEASURE-1.1 (assessment process)",
            "FS overlay — AI-030 (pre-release assessment)",
        ],
        next_actions=[
            "Run an assessment for any registered system.",
            "Inspect the per-control evaluation to see what is failing and why.",
            "Use the release recommendation as the input to the AI Governance Board decision.",
        ],
        blocks_production=[
            "No prior assessment → cannot enter release pipeline.",
            "Assessment older than 90 days for a HIGH/CRITICAL system → reassess required.",
        ],
        required_evidence=["Every assessment is itself a stored Evidence record."],
        recommended_remediation=[
            "If the recommendation is HOLD, address the rule fired (see the rule_fired field).",
            "If CONDITIONAL_PILOT, satisfy the explicit conditions in the report.",
        ],
        see_also=[{"label": "Release Gates", "href": "/release-gates"}, {"label": "Reports", "href": "/reports"}],
    ),
}


# ===========================================================================
# Glossary
# ===========================================================================

@dataclass
class GlossaryTerm:
    term: str
    category: str
    definition: str
    see_also: list[str] = field(default_factory=list)


GLOSSARY: list[GlossaryTerm] = [
    GlossaryTerm("P0", "Priority", "Highest-criticality finding or control. Always blocking for production release. SLA: 24h."),
    GlossaryTerm("P1", "Priority", "High-priority finding or control. Blocking by default; can be waived with compensating controls + CRO/CISO sign-off."),
    GlossaryTerm("P2", "Priority", "Medium-priority finding or control. Non-blocking; tracked for the next review cycle."),
    GlossaryTerm("P3", "Priority", "Informational / hygiene. No release impact."),
    GlossaryTerm("Conditional Pilot", "Release decision", "System may operate at limited scope while remediation continues. Requires HITL gate on high-risk actions and weekly eval re-runs."),
    GlossaryTerm("HOLD", "Release decision", "System cannot be released to production. Triggered by R-Hold-P0-Open, R-Hold-PII-Eval, R-Hold-PromptInjection-Low, or R-Hold-UnauthorizedToolCall."),
    GlossaryTerm("REJECT", "Release decision", "Hard policy violation — e.g., autonomous tool execution on a regulated FS workflow without HITL. Re-architect required."),
    GlossaryTerm("HITL", "Operational", "Human-in-the-loop. A human reviewer must approve before the agent takes a high-risk action (e.g., releasing a wire transfer, opening an account)."),
    GlossaryTerm("RAG", "Operational", "Retrieval-Augmented Generation — the agent looks up text in a vector store and adds it to the prompt. Major source of indirect prompt injection if retrieved content isn't sanitized."),
    GlossaryTerm("Inherent risk", "Risk model", "Risk classification at intake time, before controls are applied. Driven by data sensitivity + autonomy + regulatory exposure + RAG + tools."),
    GlossaryTerm("Residual risk", "Risk model", "Risk remaining AFTER controls + evals + evidence are accounted for. Likelihood × Impact × Exposure × Autonomy × Data × Control-gap modifier."),
    GlossaryTerm("PII", "Data class", "Personally Identifiable Information — names, addresses, phone numbers. Must never reach the model in raw form on FS systems."),
    GlossaryTerm("NPI", "Data class", "Non-public Personal Information (GLBA). Includes financial profiles, account balances, transaction history. Same handling rules as PII."),
    GlossaryTerm("SAR", "Data class", "Suspicious Activity Report (BSA). Used in AML workflows; must be de-identified before any indexing."),
    GlossaryTerm("KYC", "Workflow", "Know Your Customer onboarding. Identification + sanctions screening + risk scoring. PEP detection is a P0 control."),
    GlossaryTerm("AML", "Workflow", "Anti-Money Laundering. Investigative + SAR filing. Most workloads are advisory-only."),
    GlossaryTerm("OFAC", "Regulator", "U.S. Treasury Office of Foreign Assets Control. Maintains the Specially Designated Nationals (SDN) sanctions list."),
    GlossaryTerm("GLBA", "Regulator", "Gramm-Leach-Bliley Act. Governs the protection of NPI in financial services."),
    GlossaryTerm("FFIEC", "Regulator", "Federal Financial Institutions Examination Council. Issues IT and AI guidance for regulated US financial institutions."),
    GlossaryTerm("BSA", "Regulator", "Bank Secrecy Act. Foundational AML framework — SAR + CTR filing."),
    GlossaryTerm("CFPB", "Regulator", "Consumer Financial Protection Bureau. Fair-lending + consumer-facing AI scrutiny."),
    GlossaryTerm("DLP", "Control", "Data Loss Prevention. Output-side filter that scans for PII/NPI/PCI patterns before the response leaves the model boundary."),
    GlossaryTerm("Kill switch", "Operational", "Per-system flag that halts all inference. Used during incidents — drains in-flight requests, blocks new ones."),
    GlossaryTerm("Release impact", "Workflow", "Tag on every finding indicating its release effect: BLOCK_PRODUCTION, BLOCK_PILOT, WARNING, or NO_IMPACT."),
    GlossaryTerm("Macie", "AWS", "AWS Macie — managed DLP service for S3. Continuously scans RAG corpora + log buckets for sensitive data."),
    GlossaryTerm("CloudTrail", "AWS", "AWS audit log of every API call. Source of evidence for IAM + Bedrock invocation traces."),
    GlossaryTerm("Security Hub", "AWS", "AWS Security Hub — aggregates findings from Macie, GuardDuty, Inspector, IAM Access Analyzer."),
    GlossaryTerm("GuardDuty", "AWS", "AWS threat-detection service. Useful for VPC + IAM anomaly detection around the AI workload."),
    GlossaryTerm("Bedrock Guardrails", "AWS", "AWS Bedrock-native filtering (PII redaction, denied topics, contextual grounding). One layer of defense; not sufficient on its own."),
    GlossaryTerm("Langfuse", "Tool", "Self-hosted LLM observability — captures every prompt, retrieval, tool call, and response. Source of LANGFUSE_TRACE evidence."),
    GlossaryTerm("Garak", "Tool", "Adversarial-prompt test harness. Used for prompt-injection + jailbreak coverage. Produces GARAK_REPORT evidence."),
    GlossaryTerm("PyRIT", "Tool", "Microsoft's adversarial testing toolkit. Primarily used for tool-authorization probing."),
    GlossaryTerm("DeepEval", "Tool", "Eval framework for LLM outputs (factuality, groundedness, hallucination). Produces EVAL_RUN evidence."),
    GlossaryTerm("Waiver", "Workflow", "Time-bound exception that converts a gate FAIL to a WARNING. Capped at 90 days under AI-039; requires compensating controls + CRO/CISO sign-off."),
    GlossaryTerm("Excessive Agency", "Risk", "OWASP LLM06 (2025) — the agent has more capability than its task warrants (e.g., write access where read would suffice). Source of unauthorized side-effect risk."),
]


# ===========================================================================
# Lookups
# ===========================================================================

def page_guide(path: str) -> dict | None:
    g = PAGE_GUIDES.get(path)
    if g is None:
        # Try to match a parent path (e.g., /ai-systems/new -> /ai-systems)
        for k in PAGE_GUIDES:
            if k != "/" and path.startswith(k):
                g = PAGE_GUIDES[k]
                break
    return asdict(g) if g else None


def all_glossary() -> list[dict]:
    return [asdict(t) for t in GLOSSARY]


def control_detail(query: str) -> dict | None:
    q = query.strip().upper()
    c = CONTROLS_BY_ID.get(q)
    if c is None:
        # Try fuzzy match on title
        ql = q.lower()
        for ctrl in CONTROLS:
            if ql in ctrl.title.lower():
                c = ctrl
                break
    if c is None:
        return None
    return {
        "control_id": c.control_id,
        "title": c.title,
        "domain": c.domain.value,
        "priority": c.priority.value,
        "requirement": c.requirement,
        "pass_criteria": c.pass_criteria,
        "gate_expression": c.gate_expression,
        "failure_impact": c.failure_impact,
        "recommended_owner": c.recommended_owner.value,
        "evidence_required": [et.value for et in c.evidence_required],
        "framework_mappings": [
            {"framework": fm.framework.value, "clause": fm.clause, "rationale": fm.rationale}
            for fm in c.framework_mappings
        ],
        "automated": c.automated,
    }


_FRAMEWORK_ITEMS = list(NIST_RMF_ITEMS) + list(NIST_600_1_ITEMS) \
                    + list(OWASP_LLM_ITEMS) + list(OWASP_AGENTIC_ITEMS)


def framework_item_detail(query: str) -> dict | None:
    q = query.strip().upper()
    for it in _FRAMEWORK_ITEMS:
        if it.id.upper() == q.lower().upper() or q in it.exact_clauses:
            return _item_to_dict(it)
        if any(q.startswith(p) for p in it.prefix_clauses):
            return _item_to_dict(it)
        if q.lower() in it.display_name.lower():
            return _item_to_dict(it)
    return None


def _item_to_dict(it) -> dict:
    return {
        "id": it.id, "framework": it.framework,
        "display_name": it.display_name,
        "description": it.description,
        "exact_clauses": list(it.exact_clauses),
        "prefix_clauses": list(it.prefix_clauses),
        "recommended_owner": it.recommended_owner,
    }


def search(query: str, limit: int = 25) -> dict:
    """Search across glossary, controls, and framework items."""
    q = (query or "").strip().lower()
    if not q:
        return {"glossary": [], "controls": [], "framework_items": []}

    gloss = [
        asdict(t) for t in GLOSSARY
        if q in t.term.lower() or q in t.definition.lower() or q in t.category.lower()
    ][:limit]

    ctrls = []
    for c in CONTROLS:
        hay = f"{c.control_id} {c.title} {c.requirement} {c.failure_impact}".lower()
        if q in hay:
            ctrls.append({
                "control_id": c.control_id,
                "title": c.title,
                "priority": c.priority.value,
                "domain": c.domain.value,
            })
            if len(ctrls) >= limit:
                break

    items = []
    for it in _FRAMEWORK_ITEMS:
        hay = f"{it.id} {it.framework} {it.display_name} {it.description}".lower()
        hay += " " + " ".join(c.lower() for c in it.exact_clauses)
        if q in hay:
            items.append({
                "id": it.id, "framework": it.framework,
                "display_name": it.display_name,
                "snippet": (it.description[:150] + "…") if len(it.description) > 150 else it.description,
            })
            if len(items) >= limit:
                break

    return {"glossary": gloss, "controls": ctrls, "framework_items": items}


def control_index() -> list[dict]:
    return [
        {"control_id": c.control_id, "title": c.title,
         "domain": c.domain.value, "priority": c.priority.value}
        for c in CONTROLS
    ]


def framework_index() -> list[dict]:
    return [
        {"id": it.id, "framework": it.framework,
         "display_name": it.display_name,
         "snippet": (it.description[:120] + "…") if len(it.description) > 120 else it.description}
        for it in _FRAMEWORK_ITEMS
    ]


__all__ = [
    "PAGE_GUIDES", "PageGuide", "GLOSSARY", "GlossaryTerm",
    "page_guide", "all_glossary", "control_detail", "framework_item_detail",
    "search", "control_index", "framework_index",
]
