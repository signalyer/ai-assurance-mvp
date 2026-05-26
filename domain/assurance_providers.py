"""Assurance Model Providers — governance for AI that evaluates AI.

This module is the supply-chain governance layer for *assurance* model usage:
the models the platform calls to judge, summarize, explain, and recommend on
top of governed AI systems. It is **not** for production runtime inference.

Two distinct trust tiers:
  - Production Runtime Models: invoked by the customer's AI systems/agents.
  - Assurance Runtime Models: invoked by the platform to evaluate / summarize.

Both live here as `AssuranceProvider` records, but they carry different roles
and data-policy bindings. The policy engine refuses to route restricted-data
payloads to external SaaS providers; Bedrock or Local/VPC are required for
those workloads.

NO raw API keys live in this module. Keys exist only as `api_key_secret_ref`
URIs (e.g. `aws-secretsmanager://ai-assurance/openai/prod`). The frontend
sees masked previews + the secret ref, never the key.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional
from uuid import uuid4


# ===========================================================================
# Enums
# ===========================================================================

class ProviderType(str, Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    BEDROCK = "bedrock"
    LOCAL = "local"


class ProviderStatus(str, Enum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    WARNING = "warning"
    DISABLED = "disabled"
    NOT_CONFIGURED = "not_configured"


class ProviderRole(str, Enum):
    JUDGE_MODEL = "judge_model"
    ANALYSIS_MODEL = "analysis_model"
    RED_TEAM_MODEL = "red_team_model"
    PRODUCTION_RUNTIME = "production_runtime"
    LOCAL_SENSITIVE_WORKLOAD = "local_sensitive_workload"


class DataClass(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    SANITIZED_CONFIDENTIAL = "sanitized_confidential"
    PII = "pii"
    NPI = "npi"
    PCI = "pci"
    PAYMENT_DATA = "payment_data"
    AML_KYC_DATA = "aml_kyc_data"
    CREDIT_DATA = "credit_data"
    SYNTHETIC_DATA = "synthetic_data"
    SANITIZED_EVAL_TRACE = "sanitized_eval_trace"
    REDACTED_EVIDENCE = "redacted_evidence"


# Restricted classes that REQUIRE Bedrock or Local/VPC (not external SaaS).
RESTRICTED_DATA_CLASSES = {
    DataClass.PII, DataClass.NPI, DataClass.PCI,
    DataClass.PAYMENT_DATA, DataClass.AML_KYC_DATA, DataClass.CREDIT_DATA,
}

# Classes safe for any provider including external SaaS.
SAFE_DATA_CLASSES = {
    DataClass.PUBLIC, DataClass.INTERNAL,
    DataClass.SANITIZED_CONFIDENTIAL, DataClass.SANITIZED_EVAL_TRACE,
    DataClass.SYNTHETIC_DATA, DataClass.REDACTED_EVIDENCE,
}


class UseCase(str, Enum):
    MODEL_AS_JUDGE = "model_as_judge"
    HALLUCINATION_GRADING = "hallucination_grading"
    GROUNDEDNESS_SCORING = "groundedness_scoring"
    ANSWER_RELEVANCE_SCORING = "answer_relevance_scoring"
    PROMPT_INJECTION_ANALYSIS = "prompt_injection_analysis"
    RAG_EVALUATION = "rag_evaluation"
    RED_TEAM_GENERATION = "red_team_generation"
    FINDINGS_SUMMARIZATION = "findings_summarization"
    REMEDIATION_GENERATION = "remediation_generation"
    RELEASE_DECISION_NARRATIVE = "release_decision_narrative"
    EXECUTIVE_REPORT_GENERATION = "executive_report_generation"
    POLICY_CONTROL_QA = "policy_control_qa"
    EVIDENCE_SUMMARIZATION = "evidence_summarization"
    PRODUCTION_INFERENCE = "production_inference"
    TOOL_USING_AGENT_RUNTIME = "tool_using_agent_runtime"
    SYSTEM_QA = "system_qa"  # "Ask about this system"


class AuditDecision(str, Enum):
    ALLOWED = "allowed"
    BLOCKED = "blocked"
    WARNING = "warning"
    SIMULATED = "simulated"


# ===========================================================================
# Data models
# ===========================================================================

@dataclass
class AssuranceProvider:
    provider_id: str
    provider_name: str
    provider_type: str                  # ProviderType
    status: str                         # ProviderStatus
    roles: list[str]                    # list[ProviderRole]
    allowed_use_cases: list[str]        # list[UseCase]
    blocked_use_cases: list[str]
    allowed_data_classes: list[str]
    blocked_data_classes: list[str]
    default_model: str
    available_models: list[str]
    trust_boundary: str                 # human-readable, e.g. "External SaaS"
    data_residency: str
    api_key_secret_ref: str             # NEVER the raw key
    last_connection_test: Optional[str] = None
    monthly_cost_limit_usd: int = 1000
    rate_limit_per_min: int = 60
    enabled: bool = True
    requires_approval_for_confidential_data: bool = True
    requires_approval_for_restricted_data: bool = True
    audit_logging_enabled: bool = True
    created_at: str = ""
    updated_at: str = ""

    def masked_key_preview(self) -> str:
        """Return a fake masked preview — only used for UI display.

        The raw key is *never* available client-side. This is purely a visual
        affordance (`sk-...XXXX`) derived from the secret reference URI's last
        4 chars so the UI has something to render without ever needing the
        actual secret material.
        """
        ref = self.api_key_secret_ref or ""
        suffix = ref[-4:] if len(ref) >= 4 else "----"
        prefix = {
            "openai":    "sk-",
            "anthropic": "sk-ant-",
            "bedrock":   "AKIA",
            "local":     "vpc-",
        }.get(self.provider_type, "key-")
        return f"{prefix}••••••••••{suffix}"


@dataclass
class AssuranceModelUsageAudit:
    id: str
    timestamp: str
    provider_id: str
    provider_name: str
    model: Optional[str]
    use_case: str
    ai_system_id: Optional[str]
    data_classes: list[str]
    decision: str                       # AuditDecision
    reason: str
    token_estimate: int
    cost_estimate_usd: float
    user: str
    evidence_id: Optional[str] = None
    trace_id: Optional[str] = None
    response_snippet: Optional[str] = None


# ===========================================================================
# Seed providers
# ===========================================================================

_NOW = datetime.utcnow().isoformat() + "Z"


_OPENAI = AssuranceProvider(
    provider_id="openai-prod",
    provider_name="OpenAI",
    provider_type=ProviderType.OPENAI.value,
    status=ProviderStatus.CONNECTED.value,
    roles=[ProviderRole.JUDGE_MODEL.value, ProviderRole.ANALYSIS_MODEL.value],
    allowed_use_cases=[
        UseCase.HALLUCINATION_GRADING.value,
        UseCase.GROUNDEDNESS_SCORING.value,
        UseCase.ANSWER_RELEVANCE_SCORING.value,
        UseCase.MODEL_AS_JUDGE.value,
        UseCase.FINDINGS_SUMMARIZATION.value,
        UseCase.REMEDIATION_GENERATION.value,
        UseCase.POLICY_CONTROL_QA.value,
    ],
    blocked_use_cases=[
        UseCase.PRODUCTION_INFERENCE.value,
        UseCase.TOOL_USING_AGENT_RUNTIME.value,
    ],
    allowed_data_classes=[
        DataClass.PUBLIC.value,
        DataClass.INTERNAL.value,
        DataClass.SANITIZED_CONFIDENTIAL.value,
        DataClass.SANITIZED_EVAL_TRACE.value,
        DataClass.SYNTHETIC_DATA.value,
        DataClass.REDACTED_EVIDENCE.value,
    ],
    blocked_data_classes=[
        DataClass.PII.value, DataClass.NPI.value, DataClass.PCI.value,
        DataClass.PAYMENT_DATA.value, DataClass.AML_KYC_DATA.value,
        DataClass.CREDIT_DATA.value, DataClass.CONFIDENTIAL.value,
    ],
    default_model="gpt-4.1",
    available_models=["gpt-4.1", "gpt-4.1-mini", "gpt-4o", "o3-mini"],
    trust_boundary="External SaaS — outside enterprise VPC",
    data_residency="us-east (OpenAI managed)",
    api_key_secret_ref="aws-secretsmanager://ai-assurance/openai/prod",
    last_connection_test=_NOW,
    monthly_cost_limit_usd=500,
    rate_limit_per_min=120,
    enabled=True,
    created_at=_NOW, updated_at=_NOW,
)

_ANTHROPIC = AssuranceProvider(
    provider_id="anthropic-prod",
    provider_name="Anthropic",
    provider_type=ProviderType.ANTHROPIC.value,
    status=ProviderStatus.CONNECTED.value,
    roles=[ProviderRole.ANALYSIS_MODEL.value, ProviderRole.JUDGE_MODEL.value],
    allowed_use_cases=[
        UseCase.RELEASE_DECISION_NARRATIVE.value,
        UseCase.POLICY_CONTROL_QA.value,
        UseCase.EVIDENCE_SUMMARIZATION.value,
        UseCase.EXECUTIVE_REPORT_GENERATION.value,
        UseCase.FINDINGS_SUMMARIZATION.value,
        UseCase.REMEDIATION_GENERATION.value,
        UseCase.SYSTEM_QA.value,
        UseCase.MODEL_AS_JUDGE.value,
        UseCase.HALLUCINATION_GRADING.value,
    ],
    blocked_use_cases=[
        UseCase.PRODUCTION_INFERENCE.value,
        UseCase.TOOL_USING_AGENT_RUNTIME.value,
    ],
    allowed_data_classes=[
        DataClass.PUBLIC.value,
        DataClass.INTERNAL.value,
        DataClass.SANITIZED_CONFIDENTIAL.value,
        DataClass.SANITIZED_EVAL_TRACE.value,
        DataClass.SYNTHETIC_DATA.value,
        DataClass.REDACTED_EVIDENCE.value,
    ],
    blocked_data_classes=[
        DataClass.PII.value, DataClass.NPI.value, DataClass.PCI.value,
        DataClass.PAYMENT_DATA.value, DataClass.AML_KYC_DATA.value,
        DataClass.CREDIT_DATA.value, DataClass.CONFIDENTIAL.value,
    ],
    default_model="claude-sonnet-4-6",
    available_models=["claude-sonnet-4-6", "claude-opus-4-7", "claude-haiku-4-5-20251001"],
    trust_boundary="External SaaS — outside enterprise VPC",
    data_residency="us-east (Anthropic managed)",
    api_key_secret_ref="aws-secretsmanager://ai-assurance/anthropic/prod",
    last_connection_test=_NOW,
    monthly_cost_limit_usd=750,
    rate_limit_per_min=100,
    enabled=True,
    created_at=_NOW, updated_at=_NOW,
)

_BEDROCK = AssuranceProvider(
    provider_id="bedrock-prod",
    provider_name="AWS Bedrock",
    provider_type=ProviderType.BEDROCK.value,
    status=ProviderStatus.CONNECTED.value,
    roles=[ProviderRole.PRODUCTION_RUNTIME.value, ProviderRole.JUDGE_MODEL.value,
           ProviderRole.ANALYSIS_MODEL.value],
    allowed_use_cases=[
        # Bedrock is allowed for the full range — production AND assurance.
        UseCase.PRODUCTION_INFERENCE.value,
        UseCase.TOOL_USING_AGENT_RUNTIME.value,
        UseCase.MODEL_AS_JUDGE.value,
        UseCase.HALLUCINATION_GRADING.value,
        UseCase.GROUNDEDNESS_SCORING.value,
        UseCase.ANSWER_RELEVANCE_SCORING.value,
        UseCase.PROMPT_INJECTION_ANALYSIS.value,
        UseCase.RAG_EVALUATION.value,
        UseCase.FINDINGS_SUMMARIZATION.value,
        UseCase.REMEDIATION_GENERATION.value,
        UseCase.RELEASE_DECISION_NARRATIVE.value,
        UseCase.EXECUTIVE_REPORT_GENERATION.value,
        UseCase.POLICY_CONTROL_QA.value,
        UseCase.EVIDENCE_SUMMARIZATION.value,
        UseCase.SYSTEM_QA.value,
    ],
    blocked_use_cases=[],
    allowed_data_classes=[
        DataClass.PUBLIC.value, DataClass.INTERNAL.value,
        DataClass.CONFIDENTIAL.value, DataClass.SANITIZED_CONFIDENTIAL.value,
        DataClass.PII.value, DataClass.NPI.value, DataClass.PAYMENT_DATA.value,
        DataClass.AML_KYC_DATA.value, DataClass.CREDIT_DATA.value,
        DataClass.REDACTED_EVIDENCE.value, DataClass.SANITIZED_EVAL_TRACE.value,
        DataClass.SYNTHETIC_DATA.value,
    ],
    blocked_data_classes=[DataClass.PCI.value],   # PCI still restricted on Bedrock without dedicated tenancy
    default_model="anthropic.claude-3-5-sonnet-v2 (via Bedrock)",
    available_models=[
        "anthropic.claude-3-5-sonnet-v2 (via Bedrock)",
        "anthropic.claude-3-haiku (via Bedrock)",
        "amazon.titan-text-premier-v1",
        "meta.llama3-70b-instruct",
    ],
    trust_boundary="AWS / GovCloud / approved enterprise boundary",
    data_residency="us-east-1 (regulated tenant)",
    api_key_secret_ref="aws-iam://role/AI-Assurance-Bedrock-Runtime",
    last_connection_test=_NOW,
    monthly_cost_limit_usd=4000,
    rate_limit_per_min=240,
    enabled=True,
    requires_approval_for_restricted_data=False,
    created_at=_NOW, updated_at=_NOW,
)

_LOCAL_VPC = AssuranceProvider(
    provider_id="local-vpc",
    provider_name="Local / VPC Model",
    provider_type=ProviderType.LOCAL.value,
    status=ProviderStatus.NOT_CONFIGURED.value,
    roles=[ProviderRole.LOCAL_SENSITIVE_WORKLOAD.value],
    allowed_use_cases=[
        UseCase.HALLUCINATION_GRADING.value,
        UseCase.GROUNDEDNESS_SCORING.value,
        UseCase.EVIDENCE_SUMMARIZATION.value,
        UseCase.FINDINGS_SUMMARIZATION.value,
        UseCase.POLICY_CONTROL_QA.value,
        UseCase.SYSTEM_QA.value,
    ],
    blocked_use_cases=[],
    allowed_data_classes=[c.value for c in DataClass],   # everything when VPC-deployed
    blocked_data_classes=[],
    default_model="(not configured)",
    available_models=[],
    trust_boundary="Zero-egress VPC (customer-managed)",
    data_residency="customer VPC",
    api_key_secret_ref="customer-vpc://local/internal",
    last_connection_test=None,
    monthly_cost_limit_usd=0,
    rate_limit_per_min=0,
    enabled=False,
    requires_approval_for_restricted_data=False,
    created_at=_NOW, updated_at=_NOW,
)


PROVIDERS: list[AssuranceProvider] = [_OPENAI, _ANTHROPIC, _BEDROCK, _LOCAL_VPC]
PROVIDERS_BY_ID: dict[str, AssuranceProvider] = {p.provider_id: p for p in PROVIDERS}


# ===========================================================================
# Audit log — JSONL persistence
# ===========================================================================

_DATA_DIR = Path(__import__("os").environ.get("DATA_ROOT") or (Path(__file__).resolve().parents[1] / "data"))
_DATA_DIR.mkdir(exist_ok=True)
AUDIT_FILE = _DATA_DIR / "assurance_audit.jsonl"


def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _append_audit(rec: AssuranceModelUsageAudit) -> None:
    with AUDIT_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(rec)) + "\n")


def _read_audit() -> list[AssuranceModelUsageAudit]:
    if not AUDIT_FILE.exists():
        return []
    out: list[AssuranceModelUsageAudit] = []
    for line in AUDIT_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(AssuranceModelUsageAudit(**json.loads(line)))
        except (json.JSONDecodeError, TypeError):
            continue
    return out


# Seeded initial audit events so the UI shows realistic history on first load.
def _seed_audit_if_empty() -> None:
    if AUDIT_FILE.exists() and AUDIT_FILE.stat().st_size > 0:
        return
    seeds = [
        AssuranceModelUsageAudit(
            id=f"aud-{uuid4().hex[:8].upper()}", timestamp=_now_iso(),
            provider_id="bedrock-prod", provider_name="AWS Bedrock",
            model="anthropic.claude-3-5-sonnet-v2 (via Bedrock)",
            use_case=UseCase.HALLUCINATION_GRADING.value,
            ai_system_id="ai-sys-002",
            data_classes=[DataClass.SANITIZED_EVAL_TRACE.value],
            decision=AuditDecision.ALLOWED.value,
            reason="Bedrock — assurance trust boundary; sanitized eval trace.",
            token_estimate=2400, cost_estimate_usd=0.018,
            user="elena.vasquez", evidence_id="EV-2026-0312",
            response_snippet="Groundedness 0.88 across 250 SAR cases; 2 citations not retrievable.",
        ),
        AssuranceModelUsageAudit(
            id=f"aud-{uuid4().hex[:8].upper()}", timestamp=_now_iso(),
            provider_id="openai-prod", provider_name="OpenAI",
            model="gpt-4.1", use_case=UseCase.FINDINGS_SUMMARIZATION.value,
            ai_system_id="ai-sys-001",
            data_classes=[DataClass.SANITIZED_CONFIDENTIAL.value],
            decision=AuditDecision.ALLOWED.value,
            reason="OpenAI permitted for sanitized confidential payloads.",
            token_estimate=1100, cost_estimate_usd=0.011,
            user="david.kumar",
            response_snippet="3 CRITICAL P0 blockers; root cause is prompt-injection bypass in tool router.",
        ),
        AssuranceModelUsageAudit(
            id=f"aud-{uuid4().hex[:8].upper()}", timestamp=_now_iso(),
            provider_id="openai-prod", provider_name="OpenAI",
            model="gpt-4.1", use_case=UseCase.SYSTEM_QA.value,
            ai_system_id="ai-sys-003",
            data_classes=[DataClass.PII.value, DataClass.NPI.value],
            decision=AuditDecision.BLOCKED.value,
            reason="OpenAI blocked: raw PII / NPI in payload — external SaaS not permitted for restricted data.",
            token_estimate=0, cost_estimate_usd=0.0,
            user="james.wong",
        ),
    ]
    for s in seeds:
        _append_audit(s)


_seed_audit_if_empty()


# ===========================================================================
# Routing engine
# ===========================================================================

def get_allowed_providers_for_use_case(
    use_case: UseCase | str, data_classes: list[DataClass | str] | None = None,
) -> list[AssuranceProvider]:
    """Filter providers that allow this use case AND satisfy data-class rules."""
    uc = use_case.value if isinstance(use_case, UseCase) else use_case
    dcs = _normalize_data_classes(data_classes or [])
    out: list[AssuranceProvider] = []
    for p in PROVIDERS:
        if not p.enabled:
            continue
        if p.status not in (ProviderStatus.CONNECTED.value, ProviderStatus.WARNING.value):
            continue
        if uc not in p.allowed_use_cases:
            continue
        if uc in p.blocked_use_cases:
            continue
        if any(d in p.blocked_data_classes for d in dcs):
            continue
        # All payload classes must be in allowed list.
        if dcs and not all(d in p.allowed_data_classes for d in dcs):
            continue
        out.append(p)
    return out


def _normalize_data_classes(items) -> list[str]:
    out: list[str] = []
    for it in items:
        out.append(it.value if isinstance(it, DataClass) else str(it).lower())
    return out


def requires_approval(
    provider: AssuranceProvider, data_classes: list[DataClass | str],
) -> tuple[bool, str | None]:
    dcs = _normalize_data_classes(data_classes)
    has_restricted = any(d in {c.value for c in RESTRICTED_DATA_CLASSES} for d in dcs)
    has_confidential = DataClass.CONFIDENTIAL.value in dcs
    if has_restricted and provider.requires_approval_for_restricted_data:
        return True, "Restricted-data exception approval required (PII/NPI/PCI/AML/KYC/credit)."
    if has_confidential and provider.requires_approval_for_confidential_data:
        return True, "Confidential-data exception approval required."
    return False, None


@dataclass
class RoutingDecision:
    allowed: bool
    provider: Optional[AssuranceProvider]
    reason: str
    alternatives: list[dict] = field(default_factory=list)
    remediation: list[str] = field(default_factory=list)
    requires_approval: bool = False
    approval_reason: Optional[str] = None


def select_assurance_provider(
    use_case: UseCase | str,
    data_classes: list[DataClass | str] | None = None,
    risk_level: str | None = None,
    preferred_provider: str | None = None,
) -> RoutingDecision:
    """Pick a provider for the request. Bedrock preferred for restricted data."""
    dcs = _normalize_data_classes(data_classes or [])
    uc = use_case.value if isinstance(use_case, UseCase) else use_case

    candidates = get_allowed_providers_for_use_case(uc, dcs)
    if not candidates:
        return _block_decision(uc, dcs)

    # Preference order:
    #   1) explicit preferred_provider if in candidates
    #   2) Bedrock or Local if any restricted data
    #   3) preferred role match (judge_model > analysis_model > production_runtime)
    if preferred_provider:
        for c in candidates:
            if c.provider_id == preferred_provider:
                approval, why = requires_approval(c, dcs)
                return RoutingDecision(
                    allowed=True, provider=c,
                    reason=f"Honored preferred provider {c.provider_name} for {uc}.",
                    requires_approval=approval, approval_reason=why,
                )

    has_restricted = any(d in {c.value for c in RESTRICTED_DATA_CLASSES} for d in dcs)
    if has_restricted:
        for c in candidates:
            if c.provider_type in (ProviderType.BEDROCK.value, ProviderType.LOCAL.value):
                approval, why = requires_approval(c, dcs)
                return RoutingDecision(
                    allowed=True, provider=c,
                    reason=f"Restricted data ({', '.join(dcs)}) routed to {c.provider_name} inside {c.trust_boundary}.",
                    requires_approval=approval, approval_reason=why,
                )

    # Otherwise pick the first candidate with the best role for the use case.
    ranked = sorted(
        candidates,
        key=lambda p: (
            0 if ProviderRole.JUDGE_MODEL.value in p.roles else 1,
            0 if ProviderRole.ANALYSIS_MODEL.value in p.roles else 1,
            0 if p.provider_type == ProviderType.BEDROCK.value else 1,
        ),
    )
    chosen = ranked[0]
    approval, why = requires_approval(chosen, dcs)
    return RoutingDecision(
        allowed=True, provider=chosen,
        reason=f"Routed to {chosen.provider_name} for {uc} based on role + data policy.",
        requires_approval=approval, approval_reason=why,
    )


def _block_decision(use_case: str, data_classes: list[str]) -> RoutingDecision:
    alternatives = []
    remediation: list[str] = []

    # Suggest Bedrock if any restricted class present.
    if any(d in {c.value for c in RESTRICTED_DATA_CLASSES} for d in data_classes):
        alternatives.append({
            "provider_id": "bedrock-prod",
            "provider_name": "AWS Bedrock",
            "why": "Approved trust boundary for restricted-data assurance workflows.",
        })
        remediation.append("Route this call through AWS Bedrock (inside approved AWS boundary).")
        remediation.append("Or redact the payload to sanitized_confidential / redacted_evidence and retry with OpenAI / Anthropic.")
        alternatives.append({
            "provider_id": "local-vpc",
            "provider_name": "Local / VPC Model",
            "why": "Zero-egress option for restricted data — requires customer VPC deployment.",
        })
        remediation.append("Or deploy the Local/VPC model and re-route the use case there.")
    else:
        remediation.append("Request an exception approval via the Policies page (CRO + CISO sign-off).")

    return RoutingDecision(
        allowed=False, provider=None,
        reason=(
            f"No assurance provider permits use_case={use_case} with data classes "
            f"[{', '.join(data_classes) or '—'}]. External SaaS providers (OpenAI, "
            "Anthropic) are blocked for raw restricted data."
        ),
        alternatives=alternatives,
        remediation=remediation,
    )


def validate_provider_policy(
    provider: AssuranceProvider, payload_metadata: dict,
) -> tuple[bool, str]:
    """Re-validates that a payload's metadata is acceptable for a provider.

    Used by the API right before dispatch as a defense-in-depth check.
    """
    if not provider.enabled:
        return False, f"{provider.provider_name} is disabled."
    if provider.status == ProviderStatus.DISCONNECTED.value:
        return False, f"{provider.provider_name} is disconnected."

    uc = payload_metadata.get("use_case")
    if uc and uc in provider.blocked_use_cases:
        return False, f"Use case {uc} is in {provider.provider_name}'s blocked list."
    if uc and uc not in provider.allowed_use_cases:
        return False, f"Use case {uc} is not in {provider.provider_name}'s allowed list."

    dcs = payload_metadata.get("data_classes", [])
    for d in dcs:
        if d in provider.blocked_data_classes:
            return False, f"Data class {d} is blocked on {provider.provider_name}."
        if d not in provider.allowed_data_classes:
            return False, f"Data class {d} is not on {provider.provider_name}'s allow-list."
    return True, "ok"


def sanitize_payload_for_provider(
    provider: AssuranceProvider, payload: dict,
) -> dict:
    """Strip fields that aren't allowed off-platform.

    This is best-effort defense-in-depth. The real sanitization should happen
    at the application layer that knows the schema. Here we just nuke any
    obviously-sensitive keys when the provider is external SaaS.
    """
    if provider.provider_type in (ProviderType.BEDROCK.value, ProviderType.LOCAL.value):
        return dict(payload)
    OFF_LIMITS = {
        "ssn", "tax_id", "account_number", "card_number", "pan",
        "customer_full_name", "dob", "raw_pii", "pii_blob",
        "transaction_amount", "balance", "wire_details",
    }
    out: dict = {}
    redacted: list[str] = []
    for k, v in (payload or {}).items():
        if k.lower() in OFF_LIMITS:
            redacted.append(k)
            continue
        out[k] = v
    if redacted:
        out["_redacted_fields"] = redacted
    return out


def create_provider_audit_event(
    *,
    provider: AssuranceProvider | None,
    use_case: str,
    ai_system_id: str | None,
    data_classes: list[str],
    decision: AuditDecision | str,
    reason: str,
    user: str,
    model: str | None = None,
    token_estimate: int = 0,
    cost_estimate_usd: float = 0.0,
    evidence_id: str | None = None,
    trace_id: str | None = None,
    response_snippet: str | None = None,
) -> AssuranceModelUsageAudit:
    rec = AssuranceModelUsageAudit(
        id=f"aud-{uuid4().hex[:8].upper()}",
        timestamp=_now_iso(),
        provider_id=provider.provider_id if provider else "",
        provider_name=provider.provider_name if provider else "",
        model=model or (provider.default_model if provider else None),
        use_case=use_case,
        ai_system_id=ai_system_id,
        data_classes=list(data_classes or []),
        decision=decision.value if isinstance(decision, AuditDecision) else decision,
        reason=reason,
        token_estimate=token_estimate,
        cost_estimate_usd=cost_estimate_usd,
        user=user, evidence_id=evidence_id, trace_id=trace_id,
        response_snippet=response_snippet,
    )
    _append_audit(rec)
    return rec


def list_audit(limit: int = 200) -> list[AssuranceModelUsageAudit]:
    out = _read_audit()
    out.sort(key=lambda a: a.timestamp, reverse=True)
    return out[:limit]


def block_provider_use(reason: str) -> dict:
    """Helper used by API routes when policy forbids dispatch."""
    return {"blocked": True, "reason": reason}


def explain_provider_decision(decision: RoutingDecision) -> dict:
    """Produce a UI-friendly explanation of a routing decision."""
    return {
        "allowed": decision.allowed,
        "provider_id": decision.provider.provider_id if decision.provider else None,
        "provider_name": decision.provider.provider_name if decision.provider else None,
        "reason": decision.reason,
        "requires_approval": decision.requires_approval,
        "approval_reason": decision.approval_reason,
        "alternatives": decision.alternatives,
        "remediation": decision.remediation,
    }


# ===========================================================================
# Simulated responses — used when API keys are absent
# ===========================================================================

def have_real_credentials(provider: AssuranceProvider) -> bool:
    if provider.provider_type == ProviderType.OPENAI.value:
        return bool(os.getenv("OPENAI_API_KEY"))
    if provider.provider_type == ProviderType.ANTHROPIC.value:
        return bool(os.getenv("ANTHROPIC_API_KEY"))
    if provider.provider_type == ProviderType.BEDROCK.value:
        return bool(os.getenv("AWS_REGION")) and bool(os.getenv("AWS_ACCESS_KEY_ID"))
    # Local/VPC: we don't simulate real calls
    return False


def simulate_response(
    use_case: str, provider: AssuranceProvider, payload: dict,
) -> str:
    """Use-case-specific stub responses. Realistic FS framing."""
    ai_sys = payload.get("ai_system_id") or payload.get("system_id") or "the system"
    fid = payload.get("finding_id") or "—"
    question = (payload.get("question") or "").strip()

    if use_case == UseCase.FINDINGS_SUMMARIZATION.value:
        return (
            f"Finding {fid} — Plain-English summary:\n"
            f"  · Root cause: instruction-in-memo bypass on the tool router; the agent treated retrieved memo text as system instructions.\n"
            f"  · Mapped frameworks: OWASP LLM01, OWASP AAI-04, FS-Overlay AI-006.\n"
            f"  · Release impact: BLOCK_PRODUCTION until tool authz moves out of the model prompt + per-tool rate limit applied.\n"
            f"  · Remediation: (1) Move tool-authz to a separate service; (2) sanitize HTML/markdown from RAG chunks; (3) re-run Garak instruction-isolation suite.\n"
            f"\n[Simulated — no live model call. Provider: {provider.provider_name}.]"
        )

    if use_case == UseCase.RELEASE_DECISION_NARRATIVE.value:
        return (
            f"Release decision narrative for {ai_sys}:\n"
            f"  · Decision: HOLD — rule R-Hold-P0-Open fired.\n"
            f"  · Why: 1 open CRITICAL finding (prompt-injection bypass on tool router) and 3 HIGH findings related to authz + RAG quarantine.\n"
            f"  · Failed gates: RG-002 (prompt injection), RG-004 (tool authz), RG-007 (evidence completeness 38%).\n"
            f"  · Evidence gaps: RAG_CONFIG manifest missing; remediation-verification not attached.\n"
            f"  · Required remediation: close the CRITICAL, attach RAG_CONFIG + REMEDIATION_VERIFICATION, then re-evaluate.\n"
            f"\n[Simulated — no live model call. Provider: {provider.provider_name}.]"
        )

    if use_case == UseCase.EVIDENCE_SUMMARIZATION.value:
        return (
            f"Evidence summary (redacted metadata only):\n"
            f"  · 18 evidence records across 8 sections; completeness 38%.\n"
            f"  · Strongest: Architecture diagram (current), IAM policy snapshot, Bedrock config.\n"
            f"  · Gaps: RAG_CONFIG missing — required for AI-004 close; REMEDIATION_VERIFICATION absent on the prompt-injection finding.\n"
            f"  · Next steps: re-run Macie + Garak connectors, attach manifests.\n"
            f"\n[Simulated — no live model call. Provider: {provider.provider_name}.]"
        )

    if use_case == UseCase.EXECUTIVE_REPORT_GENERATION.value:
        return (
            f"Executive summary draft (board-ready, sanitized):\n"
            f"  · Portfolio: 6 governed AI systems · 1 production-approved · 2 on HOLD · 3 on Conditional Pilot.\n"
            f"  · Critical exposure: 6 open P0 findings concentrated in the Customer Service Copilot (3) and Payments / KYC agents.\n"
            f"  · Framework posture: NIST 600-1 at 48%, OWASP Agentic at 22% — both require remediation cycles.\n"
            f"  · Recommendation: defer Customer Service Copilot promotion until SSN-redaction + roleplay-jailbreak mitigations are verified.\n"
            f"\n[Simulated — no live model call. Provider: {provider.provider_name}.]"
        )

    if use_case == UseCase.SYSTEM_QA.value:
        prefix = f"Q: {question}\nA:" if question else "A:"
        return (
            f"{prefix} {ai_sys} is HIGH inherent risk because it touches GLBA/OFAC payment data with tool-using autonomy. "
            f"Release is blocked by the open CRITICAL prompt-injection bypass and missing RAG quarantine evidence. "
            f"Closing the CRITICAL + attaching RAG_CONFIG + REMEDIATION_VERIFICATION will move the decision to Conditional Pilot under HITL.\n"
            f"\n[Simulated — no live model call. Provider: {provider.provider_name}.]"
        )

    if use_case == UseCase.HALLUCINATION_GRADING.value:
        return f"Hallucination rate: 12% across 250 cases. 2 citations not in retrieved corpus.\n[Simulated · {provider.provider_name}]"
    if use_case == UseCase.GROUNDEDNESS_SCORING.value:
        return f"Groundedness: 0.88 vs 0.90 threshold (WARN).\n[Simulated · {provider.provider_name}]"

    return (
        f"Use case: {use_case}\nProvider: {provider.provider_name}\n"
        f"[Simulated assurance-model response — no live API call was made.]"
    )


# ===========================================================================
# Public-facing accessors (used by API)
# ===========================================================================

def list_providers() -> list[dict]:
    """Provider list with masked key preview — never returns raw secret."""
    out = []
    for p in PROVIDERS:
        d = asdict(p)
        d["masked_key_preview"] = p.masked_key_preview()
        d["has_real_credentials"] = have_real_credentials(p)
        out.append(d)
    return out


def get_provider(provider_id: str) -> dict | None:
    p = PROVIDERS_BY_ID.get(provider_id)
    if not p:
        return None
    d = asdict(p)
    d["masked_key_preview"] = p.masked_key_preview()
    d["has_real_credentials"] = have_real_credentials(p)
    return d


def policy_summary() -> dict:
    """Top-level data-policy summary for the UI hero card."""
    audit = _read_audit()
    allowed = sum(1 for a in audit if a.decision == AuditDecision.ALLOWED.value)
    blocked = sum(1 for a in audit if a.decision == AuditDecision.BLOCKED.value)
    simulated = sum(1 for a in audit if a.decision == AuditDecision.SIMULATED.value)
    return {
        "providers_total": len(PROVIDERS),
        "providers_connected": sum(1 for p in PROVIDERS if p.status == ProviderStatus.CONNECTED.value),
        "providers_not_configured": sum(1 for p in PROVIDERS if p.status == ProviderStatus.NOT_CONFIGURED.value),
        "audit_total": len(audit),
        "audit_allowed": allowed,
        "audit_blocked": blocked,
        "audit_simulated": simulated,
        "use_case_count": len(UseCase),
        "data_classes_count": len(DataClass),
    }


__all__ = [
    "ProviderType", "ProviderStatus", "ProviderRole", "DataClass", "UseCase",
    "AuditDecision",
    "AssuranceProvider", "AssuranceModelUsageAudit",
    "PROVIDERS", "PROVIDERS_BY_ID",
    "get_allowed_providers_for_use_case", "select_assurance_provider",
    "validate_provider_policy", "sanitize_payload_for_provider",
    "create_provider_audit_event", "block_provider_use",
    "requires_approval", "explain_provider_decision",
    "have_real_credentials", "simulate_response",
    "list_providers", "get_provider", "policy_summary", "list_audit",
    "RoutingDecision",
]
