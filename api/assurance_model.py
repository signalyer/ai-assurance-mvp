"""Assurance Model API -- server-side only.

All endpoints sit behind the routing-policy engine in
`domain/assurance_providers.py`. No real OpenAI / Anthropic API calls are
made unless the corresponding env var is set; otherwise responses are
deterministic simulations and recorded as decision=SIMULATED.

API key material is NEVER returned to the client -- only the masked preview
and the secret reference URI.

Session 13: typed per audit doc §3.2. The 5 /ask|/summarize|/explain|/draft
endpoints are LLM-triggering (governance-emitting); their response model
carries GovernanceMetadata for trace_id / policy_decision surfacing.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from domain.assurance_providers import (
    PROVIDERS_BY_ID, AuditDecision, UseCase,
    list_providers, get_provider, policy_summary,
    select_assurance_provider, validate_provider_policy,
    sanitize_payload_for_provider, create_provider_audit_event,
    have_real_credentials, simulate_response,
    list_audit, explain_provider_decision,
)

from api._models import GovernanceMetadata, OkResponse


router = APIRouter(prefix="/api/assurance-model", tags=["assurance-model"])
providers_router = APIRouter(prefix="/api/assurance-providers", tags=["assurance-providers"])


def _strict() -> ConfigDict:
    return ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Provider models
# ---------------------------------------------------------------------------

class ProviderOut(BaseModel):
    """Full provider record (catalog entry).

    Note: api_key_secret_ref is the SECRET REFERENCE URI, not the secret value.
    masked_key_preview is the only key-related field clients ever see.
    """
    model_config = _strict()

    provider_id: str
    provider_name: str
    provider_type: str
    status: str
    roles: list[str]
    allowed_use_cases: list[str]
    blocked_use_cases: list[str]
    allowed_data_classes: list[str]
    blocked_data_classes: list[str]
    default_model: str
    available_models: list[str]
    trust_boundary: str
    data_residency: str
    api_key_secret_ref: str
    last_connection_test: str | None = None
    monthly_cost_limit_usd: int | float | None = None
    rate_limit_per_min: int | None = None
    enabled: bool
    requires_approval_for_confidential_data: bool
    requires_approval_for_restricted_data: bool
    audit_logging_enabled: bool
    created_at: str
    updated_at: str
    masked_key_preview: str
    has_real_credentials: bool


class PolicySummaryOut(BaseModel):
    """Aggregate stats across all providers + audit log."""
    model_config = _strict()

    providers_total: int
    providers_connected: int
    providers_not_configured: int
    audit_total: int
    audit_allowed: int
    audit_blocked: int
    audit_simulated: int
    use_case_count: int
    data_classes_count: int


class ProvidersListOut(BaseModel):
    model_config = _strict()
    providers: list[ProviderOut]
    policy_summary: PolicySummaryOut


class TestConnectionOut(BaseModel):
    """Result of POST /api/assurance-providers/{id}/test."""
    model_config = _strict()

    provider_id: str
    status: str
    trust_boundary: str
    data_residency: str
    has_real_credentials: bool
    checked_at: str
    audit_event_id: str
    note: str


class ToggleProviderOut(BaseModel):
    """Result of enable/disable mutations."""
    model_config = _strict()

    ok: bool = True
    provider_id: str
    enabled: bool


class RotateKeyOut(BaseModel):
    """Result of POST /api/assurance-providers/{id}/rotate-key."""
    model_config = _strict()

    ok: bool = True
    provider_id: str
    secret_ref: str
    note: str


class AuditRowOut(BaseModel):
    """One row in the provider audit log."""
    model_config = _strict()

    id: str
    timestamp: str
    provider_id: str | None = None
    provider_name: str | None = None
    model: str | None = None
    use_case: str
    ai_system_id: str | None = None
    data_classes: list[str]
    decision: str
    reason: str
    token_estimate: int | None = None
    cost_estimate_usd: float | None = None
    user: str
    evidence_id: str | None = None
    trace_id: str | None = None
    response_snippet: str | None = None


class AuditListOut(BaseModel):
    model_config = _strict()
    audit: list[AuditRowOut]


# ---------------------------------------------------------------------------
# Ask request / response models
# ---------------------------------------------------------------------------

class AskRequest(BaseModel):
    use_case: str = Field(default="", description="UseCase enum value -- set by endpoint if omitted")
    ai_system_id: str | None = None
    data_classes: list[str] = Field(default_factory=list)
    question: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    preferred_provider: str | None = None
    user: str = "anonymous"


class PolicyDecisionOut(BaseModel):
    """Loose typed wrapper for explain_provider_decision() output.

    The underlying dispatch returns different shapes depending on which branch
    fires (blocked / re-check blocked / allowed). Keep extra='allow' for now;
    tighten when downstream Phase 1.5 plumbs the values cleanly.
    """
    model_config = ConfigDict(extra="allow")


class AskResponseOut(BaseModel):
    """Response from any /ask|/summarize-*|/explain-*|/draft-* endpoint.

    These endpoints are LLM-triggering -- response carries GovernanceMetadata
    for downstream CISO Console correlation (trace_id linkage to App Insights).
    """
    model_config = _strict()

    status: str = Field(description="blocked | simulated | (real when wired)")
    provider: str | None = None
    provider_id: str | None = None
    model: str | None = None
    use_case: str
    response: str | None = None
    policy_decision: PolicyDecisionOut | None = None
    audit_event_id: str
    sanitized_redactions: list[str] = Field(default_factory=list)
    governance: GovernanceMetadata | None = None


# ===========================================================================
# Provider catalog endpoints
# ===========================================================================

@providers_router.get(
    "/list",
    response_model=ProvidersListOut,
    operation_id="assurance_providers_list",
)
async def list_all_providers() -> ProvidersListOut:
    return ProvidersListOut(
        providers=[ProviderOut(**p) for p in list_providers()],
        policy_summary=PolicySummaryOut(**policy_summary()),
    )


@providers_router.get(
    "/{provider_id}",
    response_model=ProviderOut,
    operation_id="assurance_providers_get",
)
async def provider_detail(provider_id: str) -> ProviderOut:
    p = get_provider(provider_id)
    if not p:
        raise HTTPException(404, f"Unknown provider: {provider_id}")
    return ProviderOut(**p)


@providers_router.post(
    "/{provider_id}/test",
    response_model=TestConnectionOut,
    operation_id="assurance_providers_test_connection",
)
async def test_connection(provider_id: str) -> TestConnectionOut:
    """Simulated test-connection. Returns has_real_credentials so the UI can
    distinguish 'simulated test' from a real round-trip."""
    p = PROVIDERS_BY_ID.get(provider_id)
    if not p:
        raise HTTPException(404, f"Unknown provider: {provider_id}")
    real = have_real_credentials(p)
    rec = create_provider_audit_event(
        provider=p, use_case="provider_test", ai_system_id=None,
        data_classes=[], decision=AuditDecision.SIMULATED, user="system",
        reason=(f"Test connection -- credentials present: {real}. "
                "No raw API key is read by the frontend."),
    )
    return TestConnectionOut(
        provider_id=provider_id,
        status=p.status,
        trust_boundary=p.trust_boundary,
        data_residency=p.data_residency,
        has_real_credentials=real,
        checked_at=datetime.utcnow().isoformat() + "Z",
        audit_event_id=rec.id,
        note="Test routed through policy engine; no real API call was made.",
    )


@providers_router.post(
    "/{provider_id}/disable",
    response_model=ToggleProviderOut,
    operation_id="assurance_providers_disable",
)
async def disable_provider(provider_id: str) -> ToggleProviderOut:
    p = PROVIDERS_BY_ID.get(provider_id)
    if not p:
        raise HTTPException(404, f"Unknown provider: {provider_id}")
    p.enabled = False
    p.status = "disabled"
    create_provider_audit_event(
        provider=p, use_case="provider_disable", ai_system_id=None,
        data_classes=[], decision=AuditDecision.WARNING, user="user",
        reason="Provider manually disabled by operator.",
    )
    return ToggleProviderOut(provider_id=provider_id, enabled=False)


@providers_router.post(
    "/{provider_id}/enable",
    response_model=ToggleProviderOut,
    operation_id="assurance_providers_enable",
)
async def enable_provider(provider_id: str) -> ToggleProviderOut:
    p = PROVIDERS_BY_ID.get(provider_id)
    if not p:
        raise HTTPException(404, f"Unknown provider: {provider_id}")
    p.enabled = True
    p.status = "connected" if p.provider_type != "local" else "not_configured"
    create_provider_audit_event(
        provider=p, use_case="provider_enable", ai_system_id=None,
        data_classes=[], decision=AuditDecision.ALLOWED, user="user",
        reason="Provider re-enabled by operator.",
    )
    return ToggleProviderOut(provider_id=provider_id, enabled=True)


@providers_router.post(
    "/{provider_id}/rotate-key",
    response_model=RotateKeyOut,
    operation_id="assurance_providers_rotate_key",
)
async def rotate_key(provider_id: str) -> RotateKeyOut:
    """Rotation is a stub here -- surfaces what the production flow would do."""
    p = PROVIDERS_BY_ID.get(provider_id)
    if not p:
        raise HTTPException(404, f"Unknown provider: {provider_id}")
    create_provider_audit_event(
        provider=p, use_case="key_rotation", ai_system_id=None,
        data_classes=[], decision=AuditDecision.SIMULATED, user="user",
        reason=("Key rotation requested. Production flow: invoke "
                "Secrets Manager / Vault rotation policy; never exposes raw key to UI."),
    )
    return RotateKeyOut(
        provider_id=provider_id,
        secret_ref=p.api_key_secret_ref,
        note=("Rotation must be performed by the secrets-management backend. "
              "This endpoint records the request only."),
    )


@providers_router.get(
    "/audit/list",
    response_model=AuditListOut,
    operation_id="assurance_providers_audit_list",
)
async def audit_list(limit: int = 200) -> AuditListOut:
    rows = [r.__dict__ for r in list_audit(limit=limit)]
    return AuditListOut(audit=[AuditRowOut(**r) for r in rows])


# ===========================================================================
# Assurance-model invocations (policy-gated, LLM-triggering)
# ===========================================================================

def _dispatch(req: AskRequest) -> AskResponseOut:
    """Route the request through the policy engine and return a typed response.

    Returns the typed AskResponseOut directly -- callers don't see the
    untyped dict that used to leak.
    """
    payload = dict(req.payload or {})
    if req.question:
        payload["question"] = req.question
    if req.ai_system_id:
        payload["ai_system_id"] = req.ai_system_id

    decision = select_assurance_provider(
        use_case=req.use_case,
        data_classes=req.data_classes,
        preferred_provider=req.preferred_provider,
    )

    if not decision.allowed or decision.provider is None:
        audit = create_provider_audit_event(
            provider=None, use_case=req.use_case,
            ai_system_id=req.ai_system_id,
            data_classes=req.data_classes,
            decision=AuditDecision.BLOCKED, user=req.user,
            reason=decision.reason,
        )
        return AskResponseOut(
            status="blocked",
            provider=None, provider_id=None, model=None,
            use_case=req.use_case,
            response=None,
            policy_decision=PolicyDecisionOut(**explain_provider_decision(decision)),
            audit_event_id=audit.id,
            governance=GovernanceMetadata(policy_decision="DENY"),
        )

    # Defense-in-depth re-check
    ok, why = validate_provider_policy(
        decision.provider, {"use_case": req.use_case, "data_classes": req.data_classes},
    )
    if not ok:
        audit = create_provider_audit_event(
            provider=decision.provider, use_case=req.use_case,
            ai_system_id=req.ai_system_id, data_classes=req.data_classes,
            decision=AuditDecision.BLOCKED, user=req.user, reason=why,
        )
        return AskResponseOut(
            status="blocked",
            provider=decision.provider.provider_name,
            provider_id=decision.provider.provider_id,
            model=decision.provider.default_model,
            use_case=req.use_case,
            response=None,
            policy_decision=PolicyDecisionOut(reason=why, allowed=False),
            audit_event_id=audit.id,
            governance=GovernanceMetadata(policy_decision="DENY"),
        )

    # Sanitize payload before any dispatch
    sanitized = sanitize_payload_for_provider(decision.provider, payload)

    # No real API calls in this build -- record SIMULATED.
    response_text = simulate_response(req.use_case, decision.provider, sanitized)
    tok = max(120, len(response_text) // 4)
    cost = round(tok * 0.000005, 5)
    audit = create_provider_audit_event(
        provider=decision.provider, use_case=req.use_case,
        ai_system_id=req.ai_system_id, data_classes=req.data_classes,
        decision=AuditDecision.SIMULATED, user=req.user,
        reason=("Routed via policy engine; "
                + ("real credentials present but simulation enforced in this build."
                   if have_real_credentials(decision.provider)
                   else "no live credentials -- simulated response.")),
        model=decision.provider.default_model,
        token_estimate=tok, cost_estimate_usd=cost,
        response_snippet=response_text[:300],
    )

    return AskResponseOut(
        status="simulated",
        provider=decision.provider.provider_name,
        provider_id=decision.provider.provider_id,
        model=decision.provider.default_model,
        use_case=req.use_case,
        response=response_text,
        policy_decision=PolicyDecisionOut(**explain_provider_decision(decision)),
        audit_event_id=audit.id,
        sanitized_redactions=sanitized.get("_redacted_fields", []),
        governance=GovernanceMetadata(
            policy_decision="ALLOW",
            # trace_id / chain_hash plumbing: Phase 1.5
        ),
    )


@router.post(
    "/ask",
    response_model=AskResponseOut,
    operation_id="assurance_ask",
)
async def ask(req: AskRequest) -> AskResponseOut:
    """Generic 'Ask about this AI system' -- bound to SYSTEM_QA use case."""
    if not req.use_case:
        req.use_case = UseCase.SYSTEM_QA.value
    return _dispatch(req)


@router.post(
    "/summarize-finding",
    response_model=AskResponseOut,
    operation_id="assurance_summarize_finding",
)
async def summarize_finding(req: AskRequest) -> AskResponseOut:
    req.use_case = UseCase.FINDINGS_SUMMARIZATION.value
    return _dispatch(req)


@router.post(
    "/explain-release",
    response_model=AskResponseOut,
    operation_id="assurance_explain_release",
)
async def explain_release(req: AskRequest) -> AskResponseOut:
    req.use_case = UseCase.RELEASE_DECISION_NARRATIVE.value
    return _dispatch(req)


@router.post(
    "/summarize-evidence",
    response_model=AskResponseOut,
    operation_id="assurance_summarize_evidence",
)
async def summarize_evidence(req: AskRequest) -> AskResponseOut:
    req.use_case = UseCase.EVIDENCE_SUMMARIZATION.value
    return _dispatch(req)


@router.post(
    "/draft-report",
    response_model=AskResponseOut,
    operation_id="assurance_draft_report",
)
async def draft_report(req: AskRequest) -> AskResponseOut:
    req.use_case = UseCase.EXECUTIVE_REPORT_GENERATION.value
    return _dispatch(req)
