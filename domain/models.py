"""Pydantic v2 domain models for the Enterprise AI Assurance Platform.

These are the canonical typed entities for the platform. Existing `mock_data.py`
dicts remain as the legacy compatibility layer for the dashboard endpoints;
new code should import from here.

Frameworks supported:
  - NIST AI RMF (govern, map, measure, manage)
  - NIST AI 600-1 GenAI Profile
  - OWASP Top 10 for LLM Applications
  - OWASP Top 10 for Agentic AI
  - Financial Services overlay controls (AI-001..AI-010)
"""

from __future__ import annotations

from datetime import datetime, date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Environment(str, Enum):
    DEV = "DEV"
    STAGING = "STAGING"
    PILOT = "PILOT"
    PRODUCTION = "PRODUCTION"


class RuntimeStatus(str, Enum):
    DESIGN = "DESIGN"
    DEV = "DEV"
    STAGED = "STAGED"
    PILOT = "PILOT"
    PRODUCTION = "PRODUCTION"
    DECOMMISSIONED = "DECOMMISSIONED"


class CloudProvider(str, Enum):
    AWS = "AWS"
    AZURE = "AZURE"
    GCP = "GCP"
    ON_PREM = "ON_PREM"
    MULTI = "MULTI"


class AutonomyLevel(str, Enum):
    ADVISORY = "ADVISORY"                # Human reads/approves every output
    TRIAGE = "TRIAGE"                    # Routes/classifies, human acts
    DOCUMENT_GENERATION = "DOCUMENT_GENERATION"  # Drafts, human finalizes
    TOOL_USING_HITL = "TOOL_USING_HITL"  # Calls tools, human gates risky calls
    TOOL_USING_AUTONOMOUS = "TOOL_USING_AUTONOMOUS"  # Tools without HITL
    FULLY_AUTONOMOUS = "FULLY_AUTONOMOUS"


class CustomerImpact(str, Enum):
    NONE = "NONE"
    INDIRECT = "INDIRECT"
    DIRECT = "DIRECT"
    DIRECT_FINANCIAL = "DIRECT_FINANCIAL"


class RegulatoryExposure(str, Enum):
    NONE = "NONE"
    SOX = "SOX"
    GLBA = "GLBA"
    BSA_AML = "BSA_AML"
    OFAC = "OFAC"
    FFIEC = "FFIEC"
    CFPB = "CFPB"
    PCI_DSS = "PCI_DSS"
    GDPR = "GDPR"
    CCPA = "CCPA"
    MULTI = "MULTI"


class DataClass(str, Enum):
    PII = "PII"
    NPI = "NPI"                          # Non-public personal information (GLBA)
    PCI = "PCI"                          # Payment card data
    PHI = "PHI"
    ACCOUNT_NUMBERS = "ACCOUNT_NUMBERS"
    TRANSACTION_DATA = "TRANSACTION_DATA"
    AUTHENTICATION_DATA = "AUTHENTICATION_DATA"
    SAR_DATA = "SAR_DATA"                # Suspicious activity reports
    KYC_DOCUMENTS = "KYC_DOCUMENTS"
    BIOMETRIC = "BIOMETRIC"
    FINANCIAL_STATEMENTS = "FINANCIAL_STATEMENTS"
    SANCTIONS_LISTS = "SANCTIONS_LISTS"
    INTERNAL_CREDIT = "INTERNAL_CREDIT"
    MARKET_DATA = "MARKET_DATA"
    CUSTOMER_NAMES = "CUSTOMER_NAMES"
    PUBLIC = "PUBLIC"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ReleaseDecision(str, Enum):
    APPROVED = "APPROVED"
    CONDITIONAL_PILOT = "CONDITIONAL_PILOT"
    HOLD = "HOLD"
    REJECT = "REJECT"
    NOT_ASSESSED = "NOT_ASSESSED"


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    RISK_ACCEPTED = "RISK_ACCEPTED"
    REMEDIATED = "REMEDIATED"
    VERIFIED = "VERIFIED"
    CLOSED = "CLOSED"
    FALSE_POSITIVE = "FALSE_POSITIVE"


class ReleaseImpact(str, Enum):
    # Spec'd values
    BLOCK_PRODUCTION = "BLOCK_PRODUCTION"
    BLOCK_PILOT = "BLOCK_PILOT"
    WARNING = "WARNING"
    NO_IMPACT = "NO_IMPACT"
    # Legacy aliases (kept so existing code paths work; UI normalizes)
    BLOCKS_RELEASE = "BLOCKS_RELEASE"
    CONDITIONAL = "CONDITIONAL"
    NONE = "NONE"


class AssessmentType(str, Enum):
    INITIAL = "INITIAL"
    QUARTERLY = "QUARTERLY"
    POST_INCIDENT = "POST_INCIDENT"
    PRE_RELEASE = "PRE_RELEASE"
    CONTINUOUS = "CONTINUOUS"
    THIRD_PARTY = "THIRD_PARTY"


class AssessmentStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    AWAITING_REVIEW = "AWAITING_REVIEW"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"


class FrameworkName(str, Enum):
    NIST_AI_RMF = "NIST_AI_RMF"
    NIST_AI_600_1 = "NIST_AI_600_1"
    OWASP_LLM_TOP10 = "OWASP_LLM_TOP10"
    OWASP_AGENTIC_TOP10 = "OWASP_AGENTIC_TOP10"
    FS_OVERLAY = "FS_OVERLAY"
    ISO_IEC_23894 = "ISO_IEC_23894"
    EU_AI_ACT = "EU_AI_ACT"
    ISO_42001 = "ISO_42001"
    SR_11_7 = "SR_11_7"
    FFIEC = "FFIEC"
    US_FINSERV_OVERLAY = "US_FINSERV_OVERLAY"
    SOC2 = "SOC2"
    AWS_CONTROLS = "AWS_CONTROLS"  # IAM, CloudTrail, Security Hub, Macie, GuardDuty, KMS, VPC Endpoints, Bedrock Guardrails


class ControlDomain(str, Enum):
    """Canonical 6-domain taxonomy for the platform control library."""
    GOVERNANCE = "GOVERNANCE"
    ARCHITECTURE = "ARCHITECTURE"
    SECURITY = "SECURITY"
    RUNTIME_ASSURANCE = "RUNTIME_ASSURANCE"
    OPERATIONS = "OPERATIONS"
    AUDIT_EVIDENCE = "AUDIT_EVIDENCE"


class Priority(str, Enum):
    """Control priority. Drives release-gate behavior:
      P0 — always blocking; one failure halts production release
      P1 — blocking by default; can be conditionally waived with compensating controls
      P2 — non-blocking; tracked, must be remediated before next review cycle
      P3 — informational / hygiene
    """
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class EvalType(str, Enum):
    FACTUALITY = "FACTUALITY"
    HALLUCINATION = "HALLUCINATION"
    GROUNDEDNESS = "GROUNDEDNESS"
    ANSWER_RELEVANCE = "ANSWER_RELEVANCE"
    TOXICITY = "TOXICITY"
    BIAS = "BIAS"
    PII_LEAKAGE = "PII_LEAKAGE"
    PROMPT_INJECTION = "PROMPT_INJECTION"
    JAILBREAK = "JAILBREAK"
    TOOL_AUTHORIZATION = "TOOL_AUTHORIZATION"
    REFUSAL = "REFUSAL"
    RAG_GROUNDING = "RAG_GROUNDING"
    RAG_POISONING = "RAG_POISONING"
    AUDIT_COMPLETENESS = "AUDIT_COMPLETENESS"
    HUMAN_APPROVAL = "HUMAN_APPROVAL"
    RUNTIME_POLICY = "RUNTIME_POLICY"
    LATENCY = "LATENCY"
    COST = "COST"
    REGULATORY_KNOWLEDGE = "REGULATORY_KNOWLEDGE"
    SANCTIONS_SCREENING = "SANCTIONS_SCREENING"


class ToolSource(str, Enum):
    DEEPEVAL = "DeepEval"
    RAGAS = "Ragas"
    GARAK = "Garak"
    PYRIT = "PyRIT"
    LANGFUSE = "Langfuse"
    AWS = "AWS"
    CUSTOM = "Custom"


class EvalStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"
    NOT_RUN = "NOT_RUN"


class EvidenceType(str, Enum):
    # General types — what controls require by name
    EVAL_RUN = "EVAL_RUN"
    RED_TEAM_REPORT = "RED_TEAM_REPORT"
    POLICY_ATTESTATION = "POLICY_ATTESTATION"
    AUDIT_LOG = "AUDIT_LOG"
    MODEL_CARD = "MODEL_CARD"
    DATA_LINEAGE = "DATA_LINEAGE"
    APPROVAL_RECORD = "APPROVAL_RECORD"
    PEN_TEST = "PEN_TEST"
    THIRD_PARTY_REPORT = "THIRD_PARTY_REPORT"
    RUNTIME_TELEMETRY = "RUNTIME_TELEMETRY"
    # Specific subtypes — what auditors and engineers actually upload
    ARCHITECTURE_DIAGRAM = "ARCHITECTURE_DIAGRAM"
    TERRAFORM_SNAPSHOT = "TERRAFORM_SNAPSHOT"
    IAM_POLICY_SNAPSHOT = "IAM_POLICY_SNAPSHOT"
    BEDROCK_CONFIG = "BEDROCK_CONFIG"
    RAG_CONFIG = "RAG_CONFIG"
    LANGFUSE_TRACE = "LANGFUSE_TRACE"
    GARAK_REPORT = "GARAK_REPORT"
    PYRIT_REPORT = "PYRIT_REPORT"
    MACIE_FINDING = "MACIE_FINDING"
    SECURITY_HUB_FINDING = "SECURITY_HUB_FINDING"
    CLOUDTRAIL_EVENT = "CLOUDTRAIL_EVENT"
    EXCEPTION_WAIVER = "EXCEPTION_WAIVER"
    REMEDIATION_VERIFICATION = "REMEDIATION_VERIFICATION"
    PROMPT_VERSION_RECORD = "PROMPT_VERSION_RECORD"
    TOOL_VERSION_RECORD = "TOOL_VERSION_RECORD"
    POLICY_VERSION_RECORD = "POLICY_VERSION_RECORD"


class RuntimeEventType(str, Enum):
    PROMPT_INJECTION_BLOCKED = "PROMPT_INJECTION_BLOCKED"
    PII_LEAK_BLOCKED = "PII_LEAK_BLOCKED"
    UNAUTHORIZED_TOOL_CALL = "UNAUTHORIZED_TOOL_CALL"
    RATE_LIMIT_TRIPPED = "RATE_LIMIT_TRIPPED"
    GUARDRAIL_REFUSAL = "GUARDRAIL_REFUSAL"
    HALLUCINATION_DETECTED = "HALLUCINATION_DETECTED"
    POLICY_VIOLATION = "POLICY_VIOLATION"
    HITL_ESCALATION = "HITL_ESCALATION"
    SANCTIONS_HIT = "SANCTIONS_HIT"
    JAILBREAK_ATTEMPT = "JAILBREAK_ATTEMPT"
    ANOMALOUS_USAGE = "ANOMALOUS_USAGE"
    AGENT_RECURSION_EXCEEDED = "AGENT_RECURSION_EXCEEDED"
    BEDROCK_INVOCATION = "BEDROCK_INVOCATION"
    MACIE_FINDING_INGESTED = "MACIE_FINDING_INGESTED"


class RuntimeEventSource(str, Enum):
    LANGFUSE = "Langfuse"
    AWS_CLOUDTRAIL = "AWS CloudTrail"
    AWS_SECURITY_HUB = "AWS Security Hub"
    AWS_GUARDDUTY = "AWS GuardDuty"
    AWS_MACIE = "AWS Macie"
    AWS_BEDROCK_GUARDRAIL = "AWS Bedrock Guardrails"
    NEMO_GUARDRAILS = "NeMo Guardrails"
    LAKERA = "Lakera (placeholder)"
    CUSTOM_TOOL_GATEWAY = "Custom Tool Gateway"
    CUSTOM_AI_GATEWAY = "Custom AI Gateway"
    INTERNAL = "Internal"


class PolicyStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"


class ApprovalDecision(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CONDITIONAL = "CONDITIONAL"
    DEFERRED = "DEFERRED"


class ApproverRole(str, Enum):
    AI_GOVERNANCE = "AI_GOVERNANCE"
    CRO = "CRO"
    CISO = "CISO"
    MODEL_RISK = "MODEL_RISK"
    APPSEC = "APPSEC"
    INTERNAL_AUDIT = "INTERNAL_AUDIT"
    BUSINESS_OWNER = "BUSINESS_OWNER"
    COMPLIANCE = "COMPLIANCE"


class WaiverStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


# ---------------------------------------------------------------------------
# Helper sub-models
# ---------------------------------------------------------------------------

class FrameworkMapping(BaseModel):
    """Maps a control to a specific clause/category in a named framework."""
    framework: FrameworkName
    clause: str = Field(..., description="e.g. 'GOVERN-1.1', 'LLM01', 'AAI-04', 'AI-005'")
    rationale: Optional[str] = None


class RAGSource(BaseModel):
    name: str
    type: str = Field(..., description="e.g. 'vector_store', 's3_corpus', 'document_db'")
    uri: Optional[str] = None
    classification: list[DataClass] = []
    version_controlled: bool = False
    last_refreshed: Optional[datetime] = None


class AgentTool(BaseModel):
    name: str
    description: str
    side_effect: bool = Field(..., description="True if the tool mutates state or moves money")
    authorization_required: bool = True
    rate_limit_per_min: Optional[int] = None


class Applicability(BaseModel):
    """Predicate that determines whether a Control applies to a given AISystem.

    All non-None fields are ANDed. Within a list field the match is OR (any-of).
    `always=True` short-circuits to applicable. An empty Applicability means
    'applies to all systems'.
    """
    always: bool = True
    autonomy_levels: Optional[list["AutonomyLevel"]] = None
    data_classes_any: Optional[list["DataClass"]] = None
    regulatory_exposures_any: Optional[list["RegulatoryExposure"]] = None
    customer_impact_min: Optional["CustomerImpact"] = None
    inherent_risk_min: Optional["RiskLevel"] = None
    environments: Optional[list["Environment"]] = None
    cloud_providers: Optional[list["CloudProvider"]] = None
    rag_required: Optional[bool] = Field(None, description="True=requires RAG; False=requires no RAG; None=either")
    tools_required: Optional[bool] = Field(None, description="True=requires at least one tool; False=requires none; None=either")
    side_effect_tools_required: Optional[bool] = None


# ---------------------------------------------------------------------------
# Core entities
# ---------------------------------------------------------------------------

class AISystem(BaseModel):
    """The unit of governance. One AI system = one assurance lifecycle."""
    model_config = ConfigDict(use_enum_values=False)

    id: str
    name: str
    description: str
    business_owner: str
    technical_owner: str
    domain: str = Field(..., description="Business domain, e.g. 'Payments Operations'")
    cloud_provider: CloudProvider = CloudProvider.AWS
    environment: Environment
    model_provider: str = Field(..., description="e.g. 'Anthropic', 'OpenAI', 'AWS Bedrock'")
    models_used: list[str]
    data_classes: list[DataClass]
    autonomy_level: AutonomyLevel
    user_population: str = Field(..., description="Who uses this — internal users, customers, etc.")
    customer_impact: CustomerImpact
    regulatory_exposure: list[RegulatoryExposure]
    rag_enabled: bool = False
    rag_sources: list[RAGSource] = []
    tools: list[AgentTool] = []
    aws_services: list[str] = Field(default_factory=list, description="e.g. 'Bedrock', 'Textract', 'S3', 'KMS'")
    runtime_status: RuntimeStatus
    release_decision: ReleaseDecision
    inherent_risk: RiskLevel
    residual_risk: RiskLevel
    use_case: Optional[str] = None
    human_oversight: Optional[str] = None
    data_residency: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class Framework(BaseModel):
    id: str
    name: FrameworkName
    version: str
    description: str
    source_url: Optional[str] = None


class Control(BaseModel):
    id: str
    control_id: str = Field(..., description="Stable code e.g. 'AI-001', 'LLM01', 'GOVERN-1.1'")
    title: str
    domain: ControlDomain
    requirement: str
    priority: Priority
    automated: bool = Field(..., description="Whether a tool can evaluate this control automatically")
    applicable_when: Applicability = Field(default_factory=lambda: Applicability(always=True))
    evidence_required: list[EvidenceType]
    pass_criteria: str
    gate_expression: Optional[str] = Field(
        None,
        description="Machine-evaluable expression for release gates, e.g. "
                    "'eval.PROMPT_INJECTION.score >= 0.98 AND count(findings[control_id=this, status in (OPEN, IN_PROGRESS), severity=CRITICAL]) == 0'",
    )
    failure_impact: str = Field(..., description="What happens / what's at risk if this control fails")
    recommended_owner: ApproverRole
    framework_mappings: list[FrameworkMapping]

    @property
    def severity(self) -> Severity:
        """Back-compat: map priority -> Severity for legacy callers."""
        return {
            Priority.P0: Severity.CRITICAL,
            Priority.P1: Severity.HIGH,
            Priority.P2: Severity.MEDIUM,
            Priority.P3: Severity.LOW,
        }[self.priority]


class Assessment(BaseModel):
    id: str
    ai_system_id: str
    assessment_type: AssessmentType
    status: AssessmentStatus
    started_at: datetime
    completed_at: Optional[datetime] = None
    assessor: str
    framework_versions: dict[str, str] = Field(
        default_factory=dict,
        description="Map of FrameworkName.value -> version pinned for this assessment",
    )
    overall_score: Optional[float] = Field(None, ge=0, le=100)
    release_recommendation: ReleaseDecision = ReleaseDecision.NOT_ASSESSED
    notes: Optional[str] = None


class EvalResult(BaseModel):
    id: str
    ai_system_id: str
    assessment_id: Optional[str] = None
    eval_type: EvalType
    score: float                                     # 0..1 normalized
    threshold: float                                 # 0..1
    status: EvalStatus
    release_impact: ReleaseImpact
    tool_source: ToolSource
    framework_mappings: list[FrameworkMapping] = []  # NIST / OWASP / etc.
    control_mappings: list[str] = []                 # control_ids like "AI-001"
    evidence_id: Optional[str] = None
    test_count: int = 0
    failed_count: int = 0
    sample_failures: list[str] = Field(default_factory=list, description="Short, redacted excerpts illustrating failures")
    sample_size: Optional[int] = None                # legacy alias for test_count
    notes: Optional[str] = None
    run_at: datetime


class Finding(BaseModel):
    id: str
    ai_system_id: str
    assessment_id: Optional[str] = None
    title: str
    description: str
    severity: Severity
    framework_mappings: list[FrameworkMapping]
    control_id: Optional[str] = None
    asset: Optional[str] = Field(None, description="The specific asset/component affected")
    evidence_summary: Optional[str] = None
    release_impact: ReleaseImpact
    owner: str
    owner_email: Optional[str] = None
    sla_due_date: date
    status: FindingStatus
    remediation: Optional[str] = None
    evidence_ids: list[str] = []
    discovered: date


class ReleaseGate(BaseModel):
    id: str
    ai_system_id: str
    gate_name: str
    rule: str = Field(..., description="Human-readable rule, e.g. 'No CRITICAL findings open'")
    rule_expression: Optional[str] = Field(None, description="Machine-evaluable expression")
    status: EvalStatus
    failed_reason: Optional[str] = None
    blocking: bool = True
    evidence_id: Optional[str] = None
    last_evaluated: datetime


class Evidence(BaseModel):
    id: str
    ai_system_id: str
    assessment_id: Optional[str] = None
    evidence_type: EvidenceType
    source: str = Field(..., description="System or tool that produced the evidence")
    uri: Optional[str] = Field(None, description="s3://, https://, or internal URI")
    hash: Optional[str] = Field(None, description="SHA-256 of the artifact for immutability")
    collected_at: datetime
    summary: str
    immutable: bool = True
    linked_control_ids: list[str] = Field(default_factory=list, description="Control ids this evidence supports")
    linked_finding_ids: list[str] = Field(default_factory=list, description="Finding ids this evidence pertains to")
    linked_frameworks: list[str] = Field(default_factory=list, description="Framework names this evidence informs")


class RemediationItem(BaseModel):
    id: str
    finding_id: str
    ai_system_id: str
    description: str
    owner: str
    due_date: date
    status: FindingStatus
    blocking_release: bool
    created_at: datetime
    updated_at: datetime


class RuntimeEvent(BaseModel):
    id: str
    ai_system_id: str
    timestamp: datetime
    event_type: RuntimeEventType
    severity: Severity
    source: RuntimeEventSource = RuntimeEventSource.INTERNAL
    action_taken: str = Field(..., description="e.g. 'blocked', 'escalated', 'logged'")
    policy_triggered: Optional[str] = Field(None, description="Policy id that fired, e.g. AI-001")
    linked_control: Optional[str] = Field(None, description="Control id linked to the event, e.g. AI-006")
    linked_framework: Optional[str] = Field(None, description="Framework clause, e.g. OWASP LLM01")
    evidence_id: Optional[str] = None
    details: str
    user_id: Optional[str] = Field(None, description="Pseudonymized user id where applicable")
    session_id: Optional[str] = None


class Policy(BaseModel):
    id: str
    policy_id: str = Field(..., description="e.g. 'AI-001'")
    name: str
    description: str
    applies_to: list[str] = Field(default_factory=list, description="AI system ids or '*' for all")
    severity: Severity
    rule_logic: str = Field(..., description="Human-readable enforcement rule")
    status: PolicyStatus
    framework_mappings: list[FrameworkMapping] = []
    owner_role: ApproverRole
    last_updated: datetime


class Approval(BaseModel):
    id: str
    ai_system_id: str
    assessment_id: Optional[str] = None
    approver: str
    role: ApproverRole
    decision: ApprovalDecision
    comments: Optional[str] = None
    conditions: list[str] = []
    timestamp: datetime


class ExceptionWaiver(BaseModel):
    id: str
    ai_system_id: str
    control_id: str
    reason: str
    risk_acceptor: str
    risk_acceptor_role: ApproverRole
    expiration_date: date
    status: WaiverStatus
    compensating_controls: list[str] = []
    created_at: datetime


# ---------------------------------------------------------------------------
# Module __all__ (for `from domain.models import *`)
# ---------------------------------------------------------------------------

__all__ = [
    # Enums
    "Environment", "RuntimeStatus", "CloudProvider", "AutonomyLevel",
    "CustomerImpact", "RegulatoryExposure", "DataClass", "RiskLevel",
    "ReleaseDecision", "Severity", "FindingStatus", "ReleaseImpact",
    "AssessmentType", "AssessmentStatus", "FrameworkName", "ControlDomain",
    "Priority",
    "EvalType", "EvalStatus", "ToolSource", "EvidenceType", "RuntimeEventType",
    "PolicyStatus", "ApprovalDecision", "ApproverRole", "WaiverStatus",
    "RuntimeEventSource",
    # Agent enums
    "AgentOwnerType", "AgentStatus",
    # Sub-models
    "FrameworkMapping", "RAGSource", "AgentTool", "Applicability",
    # Entities
    "AISystem", "Framework", "Control", "Assessment", "EvalResult",
    "Finding", "ReleaseGate", "Evidence", "RemediationItem", "RuntimeEvent",
    "Policy", "Approval", "ExceptionWaiver",
    # Agent entities
    "Agent", "AgentVersion", "AgentBinding", "AgentSubscriber",
]


# ---------------------------------------------------------------------------
# Agent registry enums
# ---------------------------------------------------------------------------

import re as _re  # noqa: E402 — placed after __all__ to keep enum section clean


class AgentOwnerType(str, Enum):
    """Whether an agent belongs to a single team or is org-wide reusable."""
    CUSTOM = "CUSTOM"      # Team-owned, not subscribable by other teams
    REUSABLE = "REUSABLE"  # Org-wide, subscribable by any system


class AgentStatus(str, Enum):
    """Lifecycle status of an agent version."""
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    DEPRECATED = "DEPRECATED"


# ---------------------------------------------------------------------------
# Agent registry entities
# ---------------------------------------------------------------------------

_SEMVER_PATTERN = _re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    r"(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
)


class Agent(BaseModel):
    """An AI agent that can be registered in the platform library.

    team-owned (CUSTOM) agents belong to one team; REUSABLE agents are
    subscribable org-wide.  latest_version_id is updated atomically on publish.
    """
    model_config = ConfigDict(use_enum_values=False)

    id: str = Field(..., description="Stable slug e.g. 'ai-agent-pay-fraud'")
    name: str
    description: str
    team: str = Field(..., description="e.g. 'payments', 'cx', 'risk', 'platform'")
    owner_type: AgentOwnerType
    latest_version_id: Optional[str] = None
    inherent_risk: RiskLevel
    framework_refs: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class AgentVersion(BaseModel):
    """An immutable snapshot of an agent at a specific semver.

    Once status=PUBLISHED the version is frozen; config changes require a new
    version.  The semver field is validated against the full semver 2.0.0 regex.
    """
    model_config = ConfigDict(use_enum_values=False)

    id: str = Field(..., description="Stable id e.g. 'ai-agent-ver-{uuid}'")
    agent_id: str
    semver: str = Field(..., description="Semver 2.0.0 string e.g. '1.0.0', '2.3.4-rc.1'")
    changelog: str
    status: AgentStatus = AgentStatus.DRAFT
    config: dict = Field(default_factory=dict, description="Prompt, tools, model settings")
    published_at: Optional[datetime] = None
    published_by: Optional[str] = None

    from pydantic import field_validator  # noqa: PLC0415

    @field_validator("semver")
    @classmethod
    def _validate_semver(cls, v: str) -> str:
        """Enforce semver 2.0.0 format; reject 'v' prefix and partial forms."""
        if not _SEMVER_PATTERN.match(v):
            raise ValueError(
                f"'{v}' is not a valid semver 2.0.0 string. "
                "Expected format: MAJOR.MINOR.PATCH[-pre][+build] e.g. '1.0.0', '2.3.4-rc.1'."
            )
        return v


class AgentBinding(BaseModel):
    """Links an agent version to an AI system at a specific semver.

    pinned=True means the binding will NOT auto-accept future publishes.
    upgrade_available_version_id is set when a new version is published and
    the binding is not pinned; cleared once accept_upgrade is called.
    """
    model_config = ConfigDict(use_enum_values=False)

    id: str = Field(..., description="Stable id e.g. 'ai-bind-{uuid}'")
    agent_id: str
    system_id: str
    version_id: str = Field(..., description="FK to AgentVersion.id (currently pinned)")
    pinned: bool = False
    upgrade_available_version_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class AgentSubscriber(BaseModel):
    """Tracks which AI systems subscribe to upgrade notifications for a REUSABLE agent."""
    model_config = ConfigDict(use_enum_values=False)

    id: str
    agent_id: str
    system_id: str = Field(..., description="The subscribing system")
    subscribed_at: datetime
    last_notified_version_id: Optional[str] = None
