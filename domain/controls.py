"""Executable control library for the Enterprise AI Assurance Platform.

Forty controls (AI-001..AI-040) spanning six domains:
  - Governance
  - Architecture
  - Security
  - Runtime Assurance
  - Operations
  - Audit & Evidence

Each control is mapped to NIST AI RMF, NIST AI 600-1, OWASP LLM Top 10,
OWASP Agentic AI Top 10, and AWS service controls (IAM, CloudTrail,
Security Hub, Macie, GuardDuty, KMS, VPC Endpoints, Bedrock Guardrails).

The library is executable:
  - `get_controls_for_ai_system(system)` resolves applicability
  - `get_required_controls(system)` filters to P0/P1
  - `map_control_to_frameworks(control)` returns mapping table
  - `calculate_control_coverage(system, findings, evidence)` computes a
    deterministic pass/fail/partial score per control, suitable for
    feeding release gates.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from domain.models import (
    Control, Applicability, FrameworkMapping,
    ControlDomain, Priority, FrameworkName, EvidenceType,
    AutonomyLevel, DataClass, RegulatoryExposure, CustomerImpact,
    RiskLevel, Environment, ApproverRole, FindingStatus, Severity,
    CloudProvider,
)

if TYPE_CHECKING:
    from domain.models import AISystem, Finding, Evidence


# ---------------------------------------------------------------------------
# Helpers for compact control definitions
# ---------------------------------------------------------------------------

def _fm(framework: FrameworkName, clause: str, rationale: str | None = None) -> FrameworkMapping:
    return FrameworkMapping(framework=framework, clause=clause, rationale=rationale)


def _C(
    control_id: str, title: str, domain: ControlDomain, requirement: str,
    priority: Priority, automated: bool, evidence_required: list[EvidenceType],
    pass_criteria: str, failure_impact: str, recommended_owner: ApproverRole,
    framework_mappings: list[FrameworkMapping],
    applicable_when: Applicability | None = None,
    gate_expression: str | None = None,
) -> Control:
    return Control(
        id=f"ctrl-{control_id.lower()}",
        control_id=control_id,
        title=title,
        domain=domain,
        requirement=requirement,
        priority=priority,
        automated=automated,
        applicable_when=applicable_when or Applicability(always=True),
        evidence_required=evidence_required,
        pass_criteria=pass_criteria,
        gate_expression=gate_expression,
        failure_impact=failure_impact,
        recommended_owner=recommended_owner,
        framework_mappings=framework_mappings,
    )


# Standing applicability rules used by several controls
ANY_REGULATED = Applicability(
    always=False,
    regulatory_exposures_any=[
        RegulatoryExposure.GLBA, RegulatoryExposure.BSA_AML, RegulatoryExposure.OFAC,
        RegulatoryExposure.FFIEC, RegulatoryExposure.SOX, RegulatoryExposure.CFPB,
        RegulatoryExposure.PCI_DSS, RegulatoryExposure.GDPR, RegulatoryExposure.CCPA,
        RegulatoryExposure.MULTI,
    ],
)
ANY_RESTRICTED_DATA = Applicability(
    always=False,
    data_classes_any=[
        DataClass.PII, DataClass.NPI, DataClass.PCI, DataClass.PHI,
        DataClass.ACCOUNT_NUMBERS, DataClass.AUTHENTICATION_DATA, DataClass.SAR_DATA,
        DataClass.KYC_DOCUMENTS, DataClass.BIOMETRIC, DataClass.SANCTIONS_LISTS,
        DataClass.FINANCIAL_STATEMENTS, DataClass.INTERNAL_CREDIT,
    ],
)
TOOL_USING = Applicability(
    always=False,
    autonomy_levels=[
        AutonomyLevel.TOOL_USING_HITL,
        AutonomyLevel.TOOL_USING_AUTONOMOUS,
        AutonomyLevel.FULLY_AUTONOMOUS,
    ],
)
SIDE_EFFECT_TOOLS = Applicability(always=False, side_effect_tools_required=True)
RAG_SYSTEMS = Applicability(always=False, rag_required=True)
PROD_OR_PILOT = Applicability(
    always=False, environments=[Environment.PILOT, Environment.PRODUCTION],
)
HIGH_RISK = Applicability(always=False, inherent_risk_min=RiskLevel.HIGH)
CUSTOMER_FACING = Applicability(always=False, customer_impact_min=CustomerImpact.DIRECT)
AWS_PROD_OR_PILOT = Applicability(
    always=False,
    cloud_providers=[CloudProvider.AWS, CloudProvider.MULTI],
    environments=[Environment.PILOT, Environment.PRODUCTION],
)


# ---------------------------------------------------------------------------
# The 40 controls
# ---------------------------------------------------------------------------

CONTROLS: list[Control] = [

    # =====================================================================
    # GOVERNANCE
    # =====================================================================

    _C("AI-011", "Model Inventory Required", ControlDomain.GOVERNANCE,
       "Every AI system in scope must be registered in the central AI inventory with model, version, owner, business purpose, and data classes before any non-DEV deployment.",
       Priority.P1, automated=True,
       evidence_required=[EvidenceType.POLICY_ATTESTATION, EvidenceType.MODEL_CARD],
       pass_criteria="System is present in AI inventory and inventory record is < 90 days old.",
       gate_expression="ai_system.registered == True AND ai_system.inventory_age_days <= 90",
       failure_impact="Shadow AI risk: ungoverned systems escape risk assessment, audit, and incident response.",
       recommended_owner=ApproverRole.AI_GOVERNANCE,
       framework_mappings=[
           _fm(FrameworkName.NIST_AI_RMF, "GOVERN-1.6", "Inventory of AI systems"),
           _fm(FrameworkName.NIST_AI_RMF, "MAP-1.1"),
       ]),

    _C("AI-012", "Business Owner Required", ControlDomain.GOVERNANCE,
       "Each AI system must have a named, accountable business owner (VP-level or higher for HIGH/CRITICAL inherent risk).",
       Priority.P1, automated=True,
       evidence_required=[EvidenceType.POLICY_ATTESTATION],
       pass_criteria="ai_system.business_owner is non-empty and resolves to an active employee record.",
       gate_expression="ai_system.business_owner is not null",
       failure_impact="No accountable executive for business decisions, risk acceptance, or customer harm.",
       recommended_owner=ApproverRole.AI_GOVERNANCE,
       framework_mappings=[
           _fm(FrameworkName.NIST_AI_RMF, "GOVERN-2.1", "Roles, responsibilities, accountability"),
           _fm(FrameworkName.NIST_AI_600_1, "Accountability"),
       ]),

    _C("AI-013", "Technical Owner Required", ControlDomain.GOVERNANCE,
       "Each AI system must have a named technical owner accountable for engineering decisions, deployment, and incident response.",
       Priority.P1, automated=True,
       evidence_required=[EvidenceType.POLICY_ATTESTATION],
       pass_criteria="ai_system.technical_owner is non-empty and resolves to an active engineer record.",
       gate_expression="ai_system.technical_owner is not null",
       failure_impact="No accountable engineer; incident escalations have no clear path.",
       recommended_owner=ApproverRole.AI_GOVERNANCE,
       framework_mappings=[
           _fm(FrameworkName.NIST_AI_RMF, "GOVERN-2.1"),
           _fm(FrameworkName.NIST_AI_600_1, "Accountability"),
       ]),

    _C("AI-014", "Approved Model Provider Required", ControlDomain.GOVERNANCE,
       "Only models from the enterprise-approved provider list may be used in non-DEV environments. Third-party providers must have a current vendor risk assessment.",
       Priority.P1, automated=True,
       evidence_required=[EvidenceType.POLICY_ATTESTATION, EvidenceType.THIRD_PARTY_REPORT],
       pass_criteria="model_provider IN approved_provider_list AND vendor_assessment_age_days <= 365.",
       gate_expression="model_provider in approved_providers AND vendor_assessment_age <= 365d",
       failure_impact="Unvetted provider may have data-handling, IP, or security gaps; concentration risk untracked.",
       recommended_owner=ApproverRole.CRO,
       applicable_when=PROD_OR_PILOT,
       framework_mappings=[
           _fm(FrameworkName.NIST_AI_RMF, "GOVERN-6.1", "Third-party risk management"),
           _fm(FrameworkName.OWASP_LLM_TOP10, "LLM05", "Supply chain"),
           _fm(FrameworkName.OWASP_LLM_TOP10, "LLM03"),
           _fm(FrameworkName.NIST_AI_600_1, "Misuse", "Vendor controls reduce misuse vectors at the provider tier"),
       ]),

    _C("AI-010", "Critical Findings Block Production Release", ControlDomain.GOVERNANCE,
       "Any open CRITICAL finding with release_impact = BLOCKS_RELEASE must prevent promotion to PRODUCTION.",
       Priority.P0, automated=True,
       evidence_required=[EvidenceType.AUDIT_LOG, EvidenceType.APPROVAL_RECORD],
       pass_criteria="0 open CRITICAL findings with BLOCKS_RELEASE impact against this system.",
       gate_expression="count(findings[ai_system_id=this, severity=CRITICAL, status in (OPEN, IN_PROGRESS), release_impact=BLOCKS_RELEASE]) == 0",
       failure_impact="Production exposure to known-critical defects (PII leak, prompt injection, unsafe tool use).",
       recommended_owner=ApproverRole.AI_GOVERNANCE,
       framework_mappings=[
           _fm(FrameworkName.NIST_AI_RMF, "MANAGE-1.1"),
           _fm(FrameworkName.NIST_AI_RMF, "MANAGE-2.3"),
       ]),

    _C("AI-039", "Exception / Waiver Expiration Required", ControlDomain.GOVERNANCE,
       "Every control exception or waiver must have a finite expiration date (max 90 days) and a named risk acceptor at the role level required by the waived control's priority.",
       Priority.P2, automated=True,
       evidence_required=[EvidenceType.APPROVAL_RECORD],
       pass_criteria="All active waivers have expiration_date <= 90 days from creation and a valid risk_acceptor_role.",
       gate_expression="all(waivers[ai_system_id=this, status=APPROVED].expiration_date <= today() + 90d)",
       failure_impact="Indefinite waivers accumulate untracked risk; control library decays.",
       recommended_owner=ApproverRole.AI_GOVERNANCE,
       framework_mappings=[
           _fm(FrameworkName.NIST_AI_RMF, "GOVERN-4.1"),
       ]),

    _C("AI-040", "Continuous Reassessment Required", ControlDomain.GOVERNANCE,
       "Production AI systems must be reassessed quarterly; HIGH/CRITICAL inherent-risk systems reassessed every 90 days plus on any of: model rev, prompt rev, RAG corpus change > 10%, regulatory event.",
       Priority.P2, automated=True,
       evidence_required=[EvidenceType.AUDIT_LOG, EvidenceType.APPROVAL_RECORD],
       pass_criteria="last_assessment within the required cadence for this system's risk tier.",
       gate_expression="days_since(last_assessment) <= cadence_days_for(inherent_risk)",
       failure_impact="Drift, silent regressions, and stale risk posture.",
       recommended_owner=ApproverRole.MODEL_RISK,
       applicable_when=PROD_OR_PILOT,
       framework_mappings=[
           _fm(FrameworkName.NIST_AI_RMF, "MANAGE-4.1"),
           _fm(FrameworkName.NIST_AI_RMF, "MEASURE-3.1"),
       ]),

    # =====================================================================
    # ARCHITECTURE
    # =====================================================================

    _C("AI-004", "RAG Source Quarantine Required", ControlDomain.ARCHITECTURE,
       "RAG corpora must be ingested through a quarantined pipeline that enforces classification, PII scrubbing, and version pinning before embedding.",
       Priority.P1, automated=True,
       evidence_required=[EvidenceType.DATA_LINEAGE, EvidenceType.EVAL_RUN],
       pass_criteria="0 unredacted-PII hits in corpus and corpus_version_pinned == True.",
       gate_expression="macie_pii_hits(rag_corpus) == 0 AND rag_corpus.version_pinned == True",
       failure_impact="Customer PII embedded in vector store; cross-customer leakage at retrieval time.",
       recommended_owner=ApproverRole.MODEL_RISK,
       applicable_when=RAG_SYSTEMS,
       framework_mappings=[
           _fm(FrameworkName.OWASP_LLM_TOP10, "LLM04", "Data and model poisoning"),
           _fm(FrameworkName.OWASP_LLM_TOP10, "LLM08", "Vector and embedding weaknesses"),
           _fm(FrameworkName.NIST_AI_600_1, "RAG Risks"),
           _fm(FrameworkName.AWS_CONTROLS, "Macie"),
       ]),

    _C("AI-015", "AWS Private Connectivity for Regulated Workloads", ControlDomain.ARCHITECTURE,
       "Model inference traffic for regulated workloads must traverse VPC endpoints (interface endpoints for Bedrock) — no traffic egresses the VPC to public endpoints.",
       Priority.P1, automated=True,
       evidence_required=[EvidenceType.AUDIT_LOG, EvidenceType.POLICY_ATTESTATION],
       pass_criteria="Bedrock InvokeModel calls observed only via VPC endpoint ARN; 0 calls via public endpoint in last 7 days.",
       gate_expression="vpc_endpoint_only(bedrock_calls, window=7d) == True",
       failure_impact="Regulated data crosses public internet; FFIEC / GLBA exposure; SAR data leakage risk.",
       recommended_owner=ApproverRole.CISO,
       applicable_when=Applicability(
           always=False,
           cloud_providers=[CloudProvider.AWS, CloudProvider.MULTI],
           regulatory_exposures_any=[
               RegulatoryExposure.GLBA, RegulatoryExposure.BSA_AML, RegulatoryExposure.PCI_DSS,
               RegulatoryExposure.OFAC, RegulatoryExposure.FFIEC, RegulatoryExposure.SOX,
           ],
       ),
       framework_mappings=[
           _fm(FrameworkName.AWS_CONTROLS, "VPC Endpoints"),
           _fm(FrameworkName.AWS_CONTROLS, "Bedrock"),
           _fm(FrameworkName.NIST_AI_RMF, "MANAGE-2.2"),
       ]),

    _C("AI-016", "Bedrock Configuration Evidence Required", ControlDomain.ARCHITECTURE,
       "AWS Bedrock model invocations must be configured with: KMS-encrypted prompts/responses, Guardrails attached, model invocation logging to CloudWatch, and per-system IAM role.",
       Priority.P2, automated=True,
       evidence_required=[EvidenceType.POLICY_ATTESTATION, EvidenceType.AUDIT_LOG],
       pass_criteria="Bedrock InvocationLoggingConfiguration enabled AND guardrailIdentifier set AND KMS CMK present.",
       gate_expression="bedrock.invocation_logging == enabled AND bedrock.guardrail_id is not null AND bedrock.kms_key is not null",
       failure_impact="Audit-trail gap, plaintext prompts at rest, no provider-side guardrails.",
       recommended_owner=ApproverRole.CISO,
       applicable_when=AWS_PROD_OR_PILOT,
       framework_mappings=[
           _fm(FrameworkName.AWS_CONTROLS, "Bedrock"),
           _fm(FrameworkName.AWS_CONTROLS, "KMS"),
           _fm(FrameworkName.AWS_CONTROLS, "CloudTrail"),
       ]),

    _C("AI-017", "RAG Document Provenance Required", ControlDomain.ARCHITECTURE,
       "Every document in a RAG corpus must carry verifiable provenance: source URI, ingest timestamp, classification, owner, hash. Retrieval responses must surface provenance to the model.",
       Priority.P2, automated=True,
       evidence_required=[EvidenceType.DATA_LINEAGE],
       pass_criteria="100% of RAG documents have all provenance fields populated.",
       gate_expression="provenance_coverage(rag_corpus) >= 1.0",
       failure_impact="Inability to trace hallucinated citations, retract poisoned documents, or audit retrievals.",
       recommended_owner=ApproverRole.MODEL_RISK,
       applicable_when=RAG_SYSTEMS,
       framework_mappings=[
           _fm(FrameworkName.OWASP_LLM_TOP10, "LLM03", "Training/RAG data poisoning"),
           _fm(FrameworkName.NIST_AI_600_1, "Transparency"),
           _fm(FrameworkName.NIST_AI_600_1, "Content Provenance"),
       ]),

    _C("AI-018", "Vector Store Access Control Required", ControlDomain.ARCHITECTURE,
       "Vector stores backing RAG must enforce per-tenant / per-user authorization at retrieval time. Cross-tenant retrieval is prohibited.",
       Priority.P1, automated=True,
       evidence_required=[EvidenceType.PEN_TEST, EvidenceType.EVAL_RUN],
       pass_criteria="0 cross-tenant retrievals in red-team eval; retrieval queries scoped by IAM/ACL principal.",
       gate_expression="cross_tenant_retrievals(red_team_run) == 0 AND retrieval_authz == enforced",
       failure_impact="Customer A retrieves Customer B's data via collision in vector neighborhood.",
       recommended_owner=ApproverRole.CISO,
       applicable_when=RAG_SYSTEMS,
       framework_mappings=[
           _fm(FrameworkName.OWASP_LLM_TOP10, "LLM08", "Vector and embedding weaknesses"),
           _fm(FrameworkName.OWASP_LLM_TOP10, "LLM02", "Sensitive information disclosure"),
           _fm(FrameworkName.AWS_CONTROLS, "IAM"),
       ]),

    _C("AI-030", "Signed Tool Registry Required", ControlDomain.ARCHITECTURE,
       "All agent tools must be registered in a signed, version-pinned registry. Tool definitions are immutable per version; new versions require re-approval.",
       Priority.P1, automated=True,
       evidence_required=[EvidenceType.POLICY_ATTESTATION, EvidenceType.AUDIT_LOG],
       pass_criteria="Every tool invocation references a registry entry with valid signature and approved version.",
       gate_expression="all(tool_invocations.registry_signature_valid == True)",
       failure_impact="Tool definition swap allows privilege escalation post-approval; supply-chain attack surface.",
       recommended_owner=ApproverRole.APPSEC,
       applicable_when=TOOL_USING,
       framework_mappings=[
           _fm(FrameworkName.OWASP_AGENTIC_TOP10, "AAI-04", "Unsafe tool use"),
           _fm(FrameworkName.OWASP_AGENTIC_TOP10, "AAI-06", "Delegation abuse"),
           _fm(FrameworkName.OWASP_LLM_TOP10, "LLM05"),
       ]),

    _C("AI-031", "SBOM Required for AI Supply Chain", ControlDomain.ARCHITECTURE,
       "An SBOM covering model artifacts, prompts, tools, RAG sources, libraries, and base images must be produced per release and stored alongside evidence.",
       Priority.P2, automated=True,
       evidence_required=[EvidenceType.POLICY_ATTESTATION, EvidenceType.DATA_LINEAGE],
       pass_criteria="SBOM exists for the current release and was generated within 7 days of release date.",
       gate_expression="sbom.exists AND days_since(sbom.generated_at) <= 7",
       failure_impact="Cannot trace upstream vulnerabilities (model, library, container) to deployed systems.",
       recommended_owner=ApproverRole.APPSEC,
       applicable_when=PROD_OR_PILOT,
       framework_mappings=[
           _fm(FrameworkName.OWASP_LLM_TOP10, "LLM05", "Supply chain"),
           _fm(FrameworkName.NIST_AI_RMF, "MAP-4.1"),
       ]),

    # =====================================================================
    # SECURITY
    # =====================================================================

    _C("AI-001", "No Raw PII/NPI/PCI in Prompts", ControlDomain.SECURITY,
       "Raw PII, NPI, or PCI must not be passed to model inference. Tokenization / redaction is required before prompt assembly.",
       Priority.P0, automated=True,
       evidence_required=[EvidenceType.EVAL_RUN, EvidenceType.AUDIT_LOG, EvidenceType.RUNTIME_TELEMETRY],
       pass_criteria="PII leak eval >= 0.999 AND 0 confirmed PII-in-prompt runtime events in last 14 days.",
       gate_expression="eval.PII_LEAKAGE.score >= 0.999 AND count(runtime_events[ai_system_id=this, event_type=PII_LEAK_BLOCKED, severity=CRITICAL, age<=14d]) == 0",
       failure_impact="GLBA / PCI / GDPR breach; regulatory fines; consent decree exposure.",
       recommended_owner=ApproverRole.CISO,
       applicable_when=ANY_RESTRICTED_DATA,
       framework_mappings=[
           _fm(FrameworkName.OWASP_LLM_TOP10, "LLM02", "Sensitive information disclosure"),
           _fm(FrameworkName.NIST_AI_600_1, "Data Privacy"),
           _fm(FrameworkName.AWS_CONTROLS, "Macie"),
       ]),

    _C("AI-002", "DLP Before Model Context Assembly", ControlDomain.SECURITY,
       "An enforcing DLP layer must inspect every assembled context (system prompt + user input + RAG hits + tool outputs) prior to model invocation. Detections block or redact.",
       Priority.P0, automated=True,
       evidence_required=[EvidenceType.POLICY_ATTESTATION, EvidenceType.RUNTIME_TELEMETRY],
       pass_criteria="DLP middleware present in the inference path AND block rate on synthetic injection >= 99.5%.",
       gate_expression="dlp_middleware.enabled == True AND dlp_block_rate(synthetic_probes) >= 0.995",
       failure_impact="PII bypasses pre-prompt scrubbing via RAG, tool output, or context-window manipulation.",
       recommended_owner=ApproverRole.CISO,
       applicable_when=ANY_RESTRICTED_DATA,
       framework_mappings=[
           _fm(FrameworkName.OWASP_LLM_TOP10, "LLM02"),
           _fm(FrameworkName.NIST_AI_600_1, "Data Privacy"),
           _fm(FrameworkName.AWS_CONTROLS, "Macie"),
       ]),

    _C("AI-003", "Prompt Injection Testing Required", ControlDomain.SECURITY,
       "Each AI system must undergo prompt-injection adversarial testing (Garak or equivalent) with a current corpus before any pilot or production release.",
       Priority.P1, automated=True,
       evidence_required=[EvidenceType.RED_TEAM_REPORT, EvidenceType.EVAL_RUN],
       pass_criteria="A red-team report exists, dated within 30 days, with >= 500 probes across at least 5 attack families.",
       gate_expression="red_team_report.age <= 30d AND red_team_report.probe_count >= 500 AND red_team_report.attack_families >= 5",
       failure_impact="Unknown injection surface; attackers find bypasses in production.",
       recommended_owner=ApproverRole.APPSEC,
       applicable_when=PROD_OR_PILOT,
       framework_mappings=[
           _fm(FrameworkName.OWASP_LLM_TOP10, "LLM01", "Prompt injection"),
           _fm(FrameworkName.NIST_AI_600_1, "Prompt Injection"),
           _fm(FrameworkName.NIST_AI_RMF, "MEASURE-2.6"),
       ]),

    _C("AI-005", "Tool Allowlisting Mandatory", ControlDomain.SECURITY,
       "Agents may only invoke tools from an explicit, system-scoped allowlist. Allowlist is enforced at the tool-router layer, not within the model prompt.",
       Priority.P0, automated=True,
       evidence_required=[EvidenceType.POLICY_ATTESTATION, EvidenceType.AUDIT_LOG],
       pass_criteria="0 invocations of tools outside the allowlist in last 30 days; allowlist enforced server-side.",
       gate_expression="count(tool_invocations[tool not in allowlist, age<=30d]) == 0",
       failure_impact="Agent-driven privilege escalation; jailbreak unlocks unsafe tools.",
       recommended_owner=ApproverRole.APPSEC,
       applicable_when=TOOL_USING,
       framework_mappings=[
           _fm(FrameworkName.OWASP_AGENTIC_TOP10, "AAI-04", "Unsafe tool use"),
           _fm(FrameworkName.OWASP_AGENTIC_TOP10, "AAI-05", "Excessive agency"),
           _fm(FrameworkName.OWASP_LLM_TOP10, "LLM06"),
       ]),

    _C("AI-006", "Tool Authorization Mandatory", ControlDomain.SECURITY,
       "Side-effectful tools require per-call authorization against the requesting user's principal. The model never carries authorization; the tool-router does.",
       Priority.P0, automated=True,
       evidence_required=[EvidenceType.EVAL_RUN, EvidenceType.AUDIT_LOG, EvidenceType.PEN_TEST],
       pass_criteria="100% of side-effect tool calls have an authz log entry AND 0 unauthorized-tool-call findings open.",
       gate_expression="authz_coverage(side_effect_tool_calls) >= 1.0 AND count(findings[control_id='AI-006', status in (OPEN, IN_PROGRESS)]) == 0",
       failure_impact="Unauthorized money movement, customer data modification, or third-party action.",
       recommended_owner=ApproverRole.APPSEC,
       applicable_when=SIDE_EFFECT_TOOLS,
       framework_mappings=[
           _fm(FrameworkName.OWASP_AGENTIC_TOP10, "AAI-04"),
           _fm(FrameworkName.OWASP_AGENTIC_TOP10, "AAI-05", "Excessive agency"),
           _fm(FrameworkName.OWASP_LLM_TOP10, "LLM06"),
           _fm(FrameworkName.NIST_AI_600_1, "Human-AI Interaction"),
       ]),

    _C("AI-019", "Tool Output DLP Required", ControlDomain.SECURITY,
       "Tool responses must pass through DLP before being incorporated into model context. Sensitive data returned by tools is redacted or refused.",
       Priority.P0, automated=True,
       evidence_required=[EvidenceType.RUNTIME_TELEMETRY, EvidenceType.EVAL_RUN],
       pass_criteria="DLP on tool-response path block rate >= 99.5% on synthetic injection.",
       gate_expression="dlp_tool_output_block_rate(synthetic_probes) >= 0.995",
       failure_impact="Tools become exfiltration channel; agent ingests and echoes PII into responses or logs.",
       recommended_owner=ApproverRole.CISO,
       applicable_when=TOOL_USING,
       framework_mappings=[
           _fm(FrameworkName.OWASP_LLM_TOP10, "LLM02", "Sensitive information disclosure"),
           _fm(FrameworkName.OWASP_LLM_TOP10, "LLM05", "Improper output handling"),
           _fm(FrameworkName.OWASP_AGENTIC_TOP10, "AAI-04"),
       ]),

    _C("AI-020", "Prompt-Injection Resistance Threshold", ControlDomain.SECURITY,
       "The system must maintain a prompt-injection bypass rate < 2% on the current red-team corpus to remain in pilot/production.",
       Priority.P1, automated=True,
       evidence_required=[EvidenceType.EVAL_RUN, EvidenceType.RED_TEAM_REPORT],
       pass_criteria="eval.PROMPT_INJECTION.score >= 0.98 AND eval.run_at within last 30 days.",
       gate_expression="eval.PROMPT_INJECTION.score >= 0.98 AND eval.PROMPT_INJECTION.age <= 30d",
       failure_impact="Stale defenses; new injection families bypass production.",
       recommended_owner=ApproverRole.APPSEC,
       applicable_when=PROD_OR_PILOT,
       framework_mappings=[
           _fm(FrameworkName.OWASP_LLM_TOP10, "LLM01"),
           _fm(FrameworkName.NIST_AI_600_1, "Prompt Injection"),
       ]),

    _C("AI-023", "Unauthorized Tool-Call Threshold", ControlDomain.SECURITY,
       "Eval-measured rate of unauthorized tool calls must be 0 on the standard test suite.",
       Priority.P0, automated=True,
       evidence_required=[EvidenceType.EVAL_RUN],
       pass_criteria="eval.TOOL_AUTHORIZATION.score == 1.0 (0 unauthorized calls in test).",
       gate_expression="eval.TOOL_AUTHORIZATION.score >= 0.99",
       failure_impact="A single unauthorized side-effect call in production can move money or modify a customer record.",
       recommended_owner=ApproverRole.APPSEC,
       applicable_when=TOOL_USING,
       framework_mappings=[
           _fm(FrameworkName.OWASP_AGENTIC_TOP10, "AAI-04"),
           _fm(FrameworkName.OWASP_AGENTIC_TOP10, "AAI-05"),
       ]),

    _C("AI-027", "No Persistent Memory for Restricted Data", ControlDomain.SECURITY,
       "Agent persistent memory (long-lived per-user state) must not retain PII, NPI, PCI, SAR, or authentication data beyond the session.",
       Priority.P1, automated=True,
       evidence_required=[EvidenceType.POLICY_ATTESTATION, EvidenceType.AUDIT_LOG],
       pass_criteria="Memory store class for restricted data = ephemeral OR encrypted with TTL <= session length.",
       gate_expression="memory_store.classification == ephemeral OR memory_store.ttl <= session_length",
       failure_impact="Memory poisoning + persistence: future sessions inherit attacker-controlled state.",
       recommended_owner=ApproverRole.CISO,
       applicable_when=ANY_RESTRICTED_DATA,
       framework_mappings=[
           _fm(FrameworkName.OWASP_AGENTIC_TOP10, "AAI-03", "Memory poisoning"),
           _fm(FrameworkName.OWASP_AGENTIC_TOP10, "AAI-08", "Autonomous persistence"),
           _fm(FrameworkName.NIST_AI_600_1, "Data Privacy"),
       ]),

    _C("AI-028", "Agent Recursion Depth Limit", ControlDomain.SECURITY,
       "Agent reasoning loops must enforce a hard maximum depth and tool-call count. Exceeding either triggers a kill switch and human escalation.",
       Priority.P1, automated=True,
       evidence_required=[EvidenceType.POLICY_ATTESTATION, EvidenceType.AUDIT_LOG],
       pass_criteria="max_depth and max_tool_calls configured AND 0 production incidents where limits were exceeded.",
       gate_expression="agent.max_recursion_depth is not null AND agent.max_tool_calls is not null",
       failure_impact="Runaway agent loops drive cost spikes, DoS the tool surface, or escape goal scope.",
       recommended_owner=ApproverRole.APPSEC,
       applicable_when=TOOL_USING,
       framework_mappings=[
           _fm(FrameworkName.OWASP_AGENTIC_TOP10, "AAI-05", "Excessive agency"),
           _fm(FrameworkName.OWASP_AGENTIC_TOP10, "AAI-01", "Goal manipulation"),
           _fm(FrameworkName.OWASP_LLM_TOP10, "LLM10"),
       ]),

    _C("AI-029", "Agent Delegation Controls", ControlDomain.SECURITY,
       "An agent may not delegate to a sub-agent with higher privileges than itself. Delegation chains are logged and depth-limited.",
       Priority.P1, automated=True,
       evidence_required=[EvidenceType.POLICY_ATTESTATION, EvidenceType.AUDIT_LOG],
       pass_criteria="0 detected delegations to higher-privileged sub-agents AND delegation depth <= configured limit.",
       gate_expression="count(delegations[child.privilege > parent.privilege]) == 0",
       failure_impact="Confused-deputy attack via sub-agent; orchestration tools used to break least privilege.",
       recommended_owner=ApproverRole.APPSEC,
       applicable_when=Applicability(always=False, autonomy_levels=[
           AutonomyLevel.TOOL_USING_AUTONOMOUS, AutonomyLevel.FULLY_AUTONOMOUS,
       ]),
       framework_mappings=[
           _fm(FrameworkName.OWASP_AGENTIC_TOP10, "AAI-06", "Delegation abuse"),
           _fm(FrameworkName.OWASP_AGENTIC_TOP10, "AAI-05"),
           _fm(FrameworkName.OWASP_AGENTIC_TOP10, "AAI-07", "Agent identity spoofing"),
       ]),

    # =====================================================================
    # RUNTIME ASSURANCE
    # =====================================================================

    _C("AI-007", "Human Approval Required for High-Risk Actions", ControlDomain.RUNTIME_ASSURANCE,
       "Money movement > $10K, customer-impacting decisions, sanctions hits, and account modifications require a human reviewer recorded inline with the decision.",
       Priority.P0, automated=False,
       evidence_required=[EvidenceType.AUDIT_LOG, EvidenceType.POLICY_ATTESTATION],
       pass_criteria="100% of in-scope decisions have a human reviewer recorded with timestamp + principal.",
       gate_expression="hitl_coverage(high_risk_actions) >= 1.0",
       failure_impact="Unsupervised AI action at the point where consequence is highest.",
       recommended_owner=ApproverRole.CRO,
       applicable_when=Applicability(always=False, customer_impact_min=CustomerImpact.DIRECT),
       framework_mappings=[
           _fm(FrameworkName.NIST_AI_600_1, "Human-AI Interaction"),
           _fm(FrameworkName.NIST_AI_RMF, "MANAGE-2.1"),
           _fm(FrameworkName.OWASP_AGENTIC_TOP10, "AAI-05"),
           _fm(FrameworkName.OWASP_AGENTIC_TOP10, "AAI-10", "Human oversight failure"),
       ]),

    _C("AI-024", "Runtime Policy Monitoring Required", ControlDomain.RUNTIME_ASSURANCE,
       "A runtime monitor must continuously evaluate policy rules (DLP, tool allowlist, rate limits, PII, jailbreak signatures) and emit a structured RuntimeEvent on every detection.",
       Priority.P2, automated=True,
       evidence_required=[EvidenceType.RUNTIME_TELEMETRY],
       pass_criteria="Monitor heartbeat present within last 5 minutes AND >= 1 RuntimeEvent emitted per 1000 inferences expected.",
       gate_expression="monitor.last_heartbeat <= 5m AND runtime_event_rate > 0",
       failure_impact="No telemetry, no detection, no incident response trigger.",
       recommended_owner=ApproverRole.CISO,
       applicable_when=PROD_OR_PILOT,
       framework_mappings=[
           _fm(FrameworkName.NIST_AI_RMF, "MEASURE-3.1"),
           _fm(FrameworkName.AWS_CONTROLS, "CloudWatch"),
           _fm(FrameworkName.AWS_CONTROLS, "Security Hub"),
           _fm(FrameworkName.OWASP_AGENTIC_TOP10, "AAI-09", "Runtime control failure"),
       ]),

    _C("AI-025", "Runtime Kill Switch Required", ControlDomain.RUNTIME_ASSURANCE,
       "A documented, tested kill switch must be available to halt the AI system within 5 minutes of an incident declaration.",
       Priority.P0, automated=False,
       evidence_required=[EvidenceType.POLICY_ATTESTATION, EvidenceType.AUDIT_LOG],
       pass_criteria="Kill switch exists, tested in last 90 days, and time-to-halt verified <= 5 minutes.",
       gate_expression="kill_switch.tested_age <= 90d AND kill_switch.measured_halt_time <= 5m",
       failure_impact="Critical incident with no fast response path; prolonged customer or financial impact.",
       recommended_owner=ApproverRole.CISO,
       applicable_when=PROD_OR_PILOT,
       framework_mappings=[
           _fm(FrameworkName.NIST_AI_RMF, "MANAGE-2.4"),
           _fm(FrameworkName.OWASP_AGENTIC_TOP10, "AAI-08", "Autonomous persistence"),
           _fm(FrameworkName.OWASP_AGENTIC_TOP10, "AAI-09", "Runtime control failure"),
       ]),

    _C("AI-026", "Memory TTL Required", ControlDomain.RUNTIME_ASSURANCE,
       "Any non-ephemeral agent memory must carry an explicit TTL appropriate to its classification.",
       Priority.P2, automated=True,
       evidence_required=[EvidenceType.POLICY_ATTESTATION, EvidenceType.AUDIT_LOG],
       pass_criteria="100% of memory records have non-null TTL; max TTL <= classification policy.",
       gate_expression="all(memory_records.ttl is not null) AND max(memory_records.ttl) <= policy_max",
       failure_impact="Memory accumulates indefinitely; later breach has unbounded blast radius.",
       recommended_owner=ApproverRole.CISO,
       applicable_when=Applicability(always=False, autonomy_levels=[
           AutonomyLevel.TOOL_USING_HITL, AutonomyLevel.TOOL_USING_AUTONOMOUS,
           AutonomyLevel.FULLY_AUTONOMOUS,
       ]),
       framework_mappings=[
           _fm(FrameworkName.OWASP_AGENTIC_TOP10, "AAI-03", "Memory poisoning"),
           _fm(FrameworkName.NIST_AI_600_1, "Data Privacy"),
       ]),

    # =====================================================================
    # OPERATIONS
    # =====================================================================

    _C("AI-008", "Evals Required Before Release", ControlDomain.OPERATIONS,
       "A current evaluation pack (factuality, hallucination, bias, PII, prompt-injection, tool-authz where applicable) must pass thresholds before release.",
       Priority.P1, automated=True,
       evidence_required=[EvidenceType.EVAL_RUN],
       pass_criteria="All applicable eval types have a PASS result dated within 30 days of release.",
       gate_expression="all(applicable_evals.status == PASS) AND all(applicable_evals.age <= 30d)",
       failure_impact="Untested model in production; regressions and unsafe outputs go unnoticed.",
       recommended_owner=ApproverRole.MODEL_RISK,
       applicable_when=PROD_OR_PILOT,
       framework_mappings=[
           _fm(FrameworkName.NIST_AI_RMF, "MEASURE-2.1"),
           _fm(FrameworkName.NIST_AI_RMF, "MEASURE-2.7"),
       ]),

    _C("AI-021", "Groundedness Threshold Required", ControlDomain.OPERATIONS,
       "RAG-based systems must score >= 0.90 on groundedness evaluation before pilot/production release.",
       Priority.P1, automated=True,
       evidence_required=[EvidenceType.EVAL_RUN],
       pass_criteria="eval.RAG_GROUNDING.score >= 0.90 within last 30 days.",
       gate_expression="eval.RAG_GROUNDING.score >= 0.90 AND eval.RAG_GROUNDING.age <= 30d",
       failure_impact="Model fabricates citations and content not supported by retrieved context.",
       recommended_owner=ApproverRole.MODEL_RISK,
       applicable_when=RAG_SYSTEMS,
       framework_mappings=[
           _fm(FrameworkName.OWASP_LLM_TOP10, "LLM09", "Misinformation"),
           _fm(FrameworkName.NIST_AI_600_1, "Hallucination"),
           _fm(FrameworkName.NIST_AI_600_1, "RAG Risks"),
       ]),

    _C("AI-022", "Hallucination Threshold Required", ControlDomain.OPERATIONS,
       "Hallucination rate must remain below 5% (eval score >= 0.95) on the standard test suite.",
       Priority.P1, automated=True,
       evidence_required=[EvidenceType.EVAL_RUN],
       pass_criteria="eval.HALLUCINATION.score >= 0.95 within last 30 days.",
       gate_expression="eval.HALLUCINATION.score >= 0.95 AND eval.HALLUCINATION.age <= 30d",
       failure_impact="Inaccurate outputs lead to bad decisions in credit, AML, customer service, or KYC.",
       recommended_owner=ApproverRole.MODEL_RISK,
       applicable_when=PROD_OR_PILOT,
       framework_mappings=[
           _fm(FrameworkName.NIST_AI_600_1, "Hallucination"),
           _fm(FrameworkName.NIST_AI_RMF, "MEASURE-2.7"),
           _fm(FrameworkName.OWASP_LLM_TOP10, "LLM09", "Misinformation"),
       ]),

    _C("AI-032", "CloudTrail Enabled", ControlDomain.OPERATIONS,
       "CloudTrail must be enabled in all accounts hosting the AI workload, including data-events for S3 buckets backing RAG corpora and model artifacts.",
       Priority.P1, automated=True,
       evidence_required=[EvidenceType.AUDIT_LOG],
       pass_criteria="CloudTrail trail exists, multi-region, log-file validation enabled, S3 data-events enabled for in-scope buckets.",
       gate_expression="cloudtrail.enabled AND cloudtrail.log_file_validation AND s3_data_events(rag_buckets) == enabled",
       failure_impact="No audit trail for API actions; forensic investigation impossible.",
       recommended_owner=ApproverRole.CISO,
       applicable_when=AWS_PROD_OR_PILOT,
       framework_mappings=[
           _fm(FrameworkName.AWS_CONTROLS, "CloudTrail"),
           _fm(FrameworkName.NIST_AI_RMF, "GOVERN-4.2"),
       ]),

    _C("AI-033", "Security Hub Findings Ingested", ControlDomain.OPERATIONS,
       "AWS Security Hub findings affecting the AI workload's resources must be ingested into the assurance platform as Findings within 24 hours.",
       Priority.P2, automated=True,
       evidence_required=[EvidenceType.RUNTIME_TELEMETRY, EvidenceType.AUDIT_LOG],
       pass_criteria="0 Security Hub HIGH/CRITICAL findings older than 24h that are not represented as platform Findings.",
       gate_expression="ingest_lag(security_hub_findings) <= 24h",
       failure_impact="Infrastructure-level security findings (mis-IAM, exposed bucket) miss assurance review.",
       recommended_owner=ApproverRole.CISO,
       applicable_when=AWS_PROD_OR_PILOT,
       framework_mappings=[
           _fm(FrameworkName.AWS_CONTROLS, "Security Hub"),
       ]),

    _C("AI-034", "Macie Scan Required for S3 / RAG Sources", ControlDomain.OPERATIONS,
       "S3 buckets backing RAG corpora and model artifacts must be under continuous Macie scan; HIGH/CRITICAL Macie findings open Findings against the AI system.",
       Priority.P1, automated=True,
       evidence_required=[EvidenceType.DATA_LINEAGE, EvidenceType.RUNTIME_TELEMETRY],
       pass_criteria="macie.continuous_scan(in_scope_buckets) == enabled AND open Macie findings = 0 critical.",
       gate_expression="macie.coverage(in_scope_buckets) == 1.0 AND macie_critical_findings == 0",
       failure_impact="Customer PII silently lands in S3 corpus; downstream embedding inherits the leak.",
       recommended_owner=ApproverRole.CISO,
       applicable_when=Applicability(
           always=False,
           cloud_providers=[CloudProvider.AWS, CloudProvider.MULTI],
           data_classes_any=[
               DataClass.PII, DataClass.NPI, DataClass.PCI, DataClass.PHI,
               DataClass.ACCOUNT_NUMBERS, DataClass.KYC_DOCUMENTS, DataClass.FINANCIAL_STATEMENTS,
           ],
       ),
       framework_mappings=[
           _fm(FrameworkName.AWS_CONTROLS, "Macie"),
           _fm(FrameworkName.NIST_AI_600_1, "Data Privacy"),
       ]),

    _C("AI-035", "GuardDuty Findings Ingested", ControlDomain.OPERATIONS,
       "AWS GuardDuty findings touching the AI workload's accounts, IAM principals, or VPCs must be ingested into the assurance platform within 24 hours.",
       Priority.P2, automated=True,
       evidence_required=[EvidenceType.RUNTIME_TELEMETRY],
       pass_criteria="GuardDuty enabled in in-scope accounts; HIGH severity findings auto-ingested within 24h.",
       gate_expression="guardduty.enabled AND ingest_lag(guardduty_findings) <= 24h",
       failure_impact="Account-level compromise (credential exfil, anomalous API) missed by assurance lifecycle.",
       recommended_owner=ApproverRole.CISO,
       applicable_when=AWS_PROD_OR_PILOT,
       framework_mappings=[
           _fm(FrameworkName.AWS_CONTROLS, "GuardDuty"),
       ]),

    _C("AI-036", "IAM Least Privilege Validated", ControlDomain.OPERATIONS,
       "IAM roles used by the AI workload (inference, tool execution, RAG retrieval, evaluation) must be reviewed via Access Analyzer and IAM Access Advisor; unused permissions removed.",
       Priority.P1, automated=True,
       evidence_required=[EvidenceType.POLICY_ATTESTATION, EvidenceType.AUDIT_LOG],
       pass_criteria="Access Analyzer findings = 0 critical AND last IAM review within 90 days.",
       gate_expression="access_analyzer.critical_findings == 0 AND iam_review.age <= 90d",
       failure_impact="Over-privileged roles widen blast radius of any successful tool injection.",
       recommended_owner=ApproverRole.CISO,
       applicable_when=AWS_PROD_OR_PILOT,
       framework_mappings=[
           _fm(FrameworkName.AWS_CONTROLS, "IAM"),
           _fm(FrameworkName.NIST_AI_RMF, "MANAGE-2.2"),
       ]),

    # =====================================================================
    # AUDIT & EVIDENCE
    # =====================================================================

    _C("AI-009", "Full Audit Logging Required", ControlDomain.AUDIT_EVIDENCE,
       "Every AI decision affecting a customer or transaction must produce an immutable, hash-chained audit log entry with: principal, prompt fingerprint, model+version, tool calls, output fingerprint, evidence ids.",
       Priority.P1, automated=True,
       evidence_required=[EvidenceType.AUDIT_LOG],
       pass_criteria="Audit coverage >= 99.9% AND hash-chain integrity verified within last 24h.",
       gate_expression="audit.coverage >= 0.999 AND audit.hash_chain_verified_age <= 24h",
       failure_impact="No reconstruction of AI-influenced decisions; SOX, FFIEC, FinCEN exam exposure.",
       recommended_owner=ApproverRole.INTERNAL_AUDIT,
       framework_mappings=[
           _fm(FrameworkName.SOC2, "CC7.2"),
           _fm(FrameworkName.NIST_AI_600_1, "Accountability"),
           _fm(FrameworkName.AWS_CONTROLS, "CloudTrail"),
       ]),

    _C("AI-037", "Evidence Immutability Required", ControlDomain.AUDIT_EVIDENCE,
       "Evidence artifacts must be written to immutable storage with SHA-256 manifest and Object Lock (or equivalent) for the retention period.",
       Priority.P1, automated=True,
       evidence_required=[EvidenceType.AUDIT_LOG, EvidenceType.POLICY_ATTESTATION],
       pass_criteria="Object Lock = COMPLIANCE mode for evidence buckets; manifest hash verified daily.",
       gate_expression="object_lock.mode(evidence_bucket) == COMPLIANCE AND manifest_verify.age <= 24h",
       failure_impact="Evidence tampering or loss; cannot defend a release decision under audit.",
       recommended_owner=ApproverRole.INTERNAL_AUDIT,
       framework_mappings=[
           _fm(FrameworkName.SOC2, "CC7.2"),
           _fm(FrameworkName.AWS_CONTROLS, "S3 Object Lock"),
           _fm(FrameworkName.NIST_AI_600_1, "Accountability"),
       ]),

    _C("AI-038", "Approval Lineage Required", ControlDomain.AUDIT_EVIDENCE,
       "Each release decision must link to: the assessment it relied on, the eval results that supported it, the findings considered, the approver identities + roles, and any waivers in force.",
       Priority.P1, automated=True,
       evidence_required=[EvidenceType.APPROVAL_RECORD, EvidenceType.AUDIT_LOG],
       pass_criteria="Every PRODUCTION release has a complete approval lineage record stored in evidence.",
       gate_expression="approval_lineage(release).complete == True",
       failure_impact="Cannot explain or defend who approved what, when, on which evidence — audit failure.",
       recommended_owner=ApproverRole.AI_GOVERNANCE,
       applicable_when=PROD_OR_PILOT,
       framework_mappings=[
           _fm(FrameworkName.NIST_AI_RMF, "GOVERN-1.5"),
           _fm(FrameworkName.NIST_AI_600_1, "Accountability"),
           _fm(FrameworkName.NIST_AI_600_1, "Transparency"),
           _fm(FrameworkName.NIST_AI_600_1, "Content Provenance"),
       ]),
]


# Stable ID -> Control lookup
CONTROLS_BY_ID: dict[str, Control] = {c.control_id: c for c in CONTROLS}


# ---------------------------------------------------------------------------
# Applicability evaluation
# ---------------------------------------------------------------------------

def _ci_at_least(actual: CustomerImpact, minimum: CustomerImpact) -> bool:
    order = [CustomerImpact.NONE, CustomerImpact.INDIRECT,
             CustomerImpact.DIRECT, CustomerImpact.DIRECT_FINANCIAL]
    return order.index(actual) >= order.index(minimum)


def _risk_at_least(actual: RiskLevel, minimum: RiskLevel) -> bool:
    order = [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]
    return order.index(actual) >= order.index(minimum)


def is_applicable(control: Control, system: "AISystem") -> bool:
    """Evaluate `control.applicable_when` against an AISystem. Deterministic."""
    a = control.applicable_when
    if a.always:
        return True

    if a.autonomy_levels is not None and system.autonomy_level not in a.autonomy_levels:
        return False
    if a.data_classes_any is not None and not (set(system.data_classes) & set(a.data_classes_any)):
        return False
    if a.regulatory_exposures_any is not None and not (set(system.regulatory_exposure) & set(a.regulatory_exposures_any)):
        return False
    if a.customer_impact_min is not None and not _ci_at_least(system.customer_impact, a.customer_impact_min):
        return False
    if a.inherent_risk_min is not None and not _risk_at_least(system.inherent_risk, a.inherent_risk_min):
        return False
    if a.environments is not None and system.environment not in a.environments:
        return False
    if a.cloud_providers is not None and system.cloud_provider not in a.cloud_providers:
        return False
    if a.rag_required is not None and bool(system.rag_enabled) != a.rag_required:
        return False
    if a.tools_required is not None and bool(system.tools) != a.tools_required:
        return False
    if a.side_effect_tools_required is True and not any(t.side_effect for t in system.tools):
        return False
    if a.side_effect_tools_required is False and any(t.side_effect for t in system.tools):
        return False

    return True


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def get_controls_for_ai_system(system: "AISystem") -> list[Control]:
    """All controls applicable to this system, by Applicability evaluation."""
    return [c for c in CONTROLS if is_applicable(c, system)]


def get_required_controls(system: "AISystem") -> list[Control]:
    """Applicable P0/P1 controls — the set that must pass for release."""
    return [c for c in get_controls_for_ai_system(system)
            if c.priority in (Priority.P0, Priority.P1)]


def map_control_to_frameworks(control: Control) -> dict[str, list[str]]:
    """Return a {framework_name: [clauses...]} table for the control."""
    out: dict[str, list[str]] = {}
    for fm in control.framework_mappings:
        out.setdefault(fm.framework.value, []).append(fm.clause)
    return out


# ---------------------------------------------------------------------------
# Coverage calculation
# ---------------------------------------------------------------------------

@dataclass
class ControlCoverageRow:
    control_id: str
    title: str
    domain: ControlDomain
    priority: Priority
    applicable: bool
    status: str                            # PASS, FAIL, PARTIAL, NOT_APPLICABLE, NO_EVIDENCE
    open_findings: int
    open_critical_findings: int
    evidence_present: bool
    blocking_release: bool
    rationale: str


@dataclass
class ControlCoverageReport:
    ai_system_id: str
    applicable_total: int
    passing: int
    failing: int
    partial: int
    no_evidence: int
    blocking_failures: int
    coverage_pct: float                    # passing / applicable_total
    rows: list[ControlCoverageRow]

    @property
    def release_recommendation(self) -> str:
        if self.blocking_failures > 0:
            return "HOLD"
        if self.failing > 0 or self.partial > 0:
            return "CONDITIONAL_PILOT"
        return "APPROVED"


def calculate_control_coverage(
    system: "AISystem",
    findings: list["Finding"],
    evidence: list["Evidence"],
) -> ControlCoverageReport:
    """Deterministic per-control coverage. Inputs are the system being assessed
    and the corpus of findings + evidence to evaluate against.

    Semantics per applicable control:
      PASS   — no open finding mapped to this control AND required evidence types present
      FAIL   — at least one open finding mapped to this control with severity CRITICAL or HIGH
      PARTIAL — open MEDIUM/LOW finding only, or evidence present but stale (caller may decide)
      NO_EVIDENCE — no open finding, but at least one required evidence type missing
      NOT_APPLICABLE — Applicability returned False
    """
    sys_findings = [f for f in findings if f.ai_system_id == system.id]
    sys_evidence = [e for e in evidence if e.ai_system_id == system.id]
    evidence_types_present = {e.evidence_type for e in sys_evidence}

    rows: list[ControlCoverageRow] = []
    applicable_total = 0
    passing = 0
    failing = 0
    partial = 0
    no_evidence = 0
    blocking_failures = 0

    for control in CONTROLS:
        if not is_applicable(control, system):
            rows.append(ControlCoverageRow(
                control_id=control.control_id, title=control.title,
                domain=control.domain, priority=control.priority,
                applicable=False, status="NOT_APPLICABLE",
                open_findings=0, open_critical_findings=0,
                evidence_present=False, blocking_release=False,
                rationale="Applicability did not match this system's attributes.",
            ))
            continue

        applicable_total += 1
        open_findings = [
            f for f in sys_findings
            if f.control_id == control.control_id
            and f.status in (FindingStatus.OPEN, FindingStatus.IN_PROGRESS)
        ]
        open_critical = [f for f in open_findings if f.severity == Severity.CRITICAL]
        open_high_or_critical = [f for f in open_findings
                                  if f.severity in (Severity.CRITICAL, Severity.HIGH)]
        required_ev_present = all(et in evidence_types_present for et in control.evidence_required)

        if open_high_or_critical:
            status = "FAIL"
            failing += 1
            blocking = control.priority in (Priority.P0, Priority.P1) and any(
                f.severity == Severity.CRITICAL for f in open_high_or_critical
            )
            if blocking:
                blocking_failures += 1
            rationale = f"{len(open_high_or_critical)} open HIGH/CRITICAL finding(s) mapped to this control."
        elif open_findings:
            status = "PARTIAL"
            partial += 1
            blocking = False
            rationale = f"{len(open_findings)} open MEDIUM/LOW finding(s) mapped to this control."
        elif not required_ev_present:
            status = "NO_EVIDENCE"
            no_evidence += 1
            blocking = control.priority == Priority.P0
            if blocking:
                blocking_failures += 1
            missing = [et.value for et in control.evidence_required if et not in evidence_types_present]
            rationale = f"No open findings, but missing evidence: {', '.join(missing)}."
        else:
            status = "PASS"
            passing += 1
            blocking = False
            rationale = "No open findings; all required evidence types present."

        rows.append(ControlCoverageRow(
            control_id=control.control_id, title=control.title,
            domain=control.domain, priority=control.priority,
            applicable=True, status=status,
            open_findings=len(open_findings),
            open_critical_findings=len(open_critical),
            evidence_present=required_ev_present,
            blocking_release=blocking,
            rationale=rationale,
        ))

    coverage_pct = (passing / applicable_total * 100.0) if applicable_total else 0.0

    return ControlCoverageReport(
        ai_system_id=system.id,
        applicable_total=applicable_total,
        passing=passing,
        failing=failing,
        partial=partial,
        no_evidence=no_evidence,
        blocking_failures=blocking_failures,
        coverage_pct=coverage_pct,
        rows=rows,
    )


__all__ = [
    "CONTROLS", "CONTROLS_BY_ID",
    "is_applicable",
    "get_controls_for_ai_system", "get_required_controls",
    "map_control_to_frameworks", "calculate_control_coverage",
    "ControlCoverageRow", "ControlCoverageReport",
]
