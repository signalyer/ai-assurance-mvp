"""Assurance Model API — server-side only.

All endpoints sit behind the routing-policy engine in
`domain/assurance_providers.py`. No real OpenAI / Anthropic API calls are
made unless the corresponding env var is set; otherwise responses are
deterministic simulations and recorded as decision=SIMULATED.

API key material is NEVER returned to the client — only the masked preview
and the secret reference URI.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from domain.assurance_providers import (
    PROVIDERS_BY_ID, AuditDecision, UseCase,
    list_providers, get_provider, policy_summary,
    select_assurance_provider, validate_provider_policy,
    sanitize_payload_for_provider, create_provider_audit_event,
    have_real_credentials, simulate_response,
    list_audit, explain_provider_decision,
)


router = APIRouter(prefix="/api/assurance-model", tags=["assurance-model"])
providers_router = APIRouter(prefix="/api/assurance-providers", tags=["assurance-providers"])


# ===========================================================================
# Provider catalog
# ===========================================================================

@providers_router.get("/list")
async def list_all_providers() -> dict:
    return {"providers": list_providers(), "policy_summary": policy_summary()}


@providers_router.get("/{provider_id}")
async def provider_detail(provider_id: str) -> dict:
    p = get_provider(provider_id)
    if not p:
        raise HTTPException(404, f"Unknown provider: {provider_id}")
    return p


@providers_router.post("/{provider_id}/test")
async def test_connection(provider_id: str) -> dict:
    """Simulated test-connection. Returns has_real_credentials so the UI can
    distinguish 'simulated test' from a real round-trip."""
    p = PROVIDERS_BY_ID.get(provider_id)
    if not p:
        raise HTTPException(404, f"Unknown provider: {provider_id}")
    real = have_real_credentials(p)
    rec = create_provider_audit_event(
        provider=p, use_case="provider_test", ai_system_id=None,
        data_classes=[], decision=AuditDecision.SIMULATED, user="system",
        reason=(f"Test connection — credentials present: {real}. "
                "No raw API key is read by the frontend."),
    )
    return {
        "provider_id": provider_id,
        "status": p.status,
        "trust_boundary": p.trust_boundary,
        "data_residency": p.data_residency,
        "has_real_credentials": real,
        "checked_at": datetime.utcnow().isoformat() + "Z",
        "audit_event_id": rec.id,
        "note": "Test routed through policy engine; no real API call was made.",
    }


@providers_router.post("/{provider_id}/disable")
async def disable_provider(provider_id: str) -> dict:
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
    return {"ok": True, "provider_id": provider_id, "enabled": False}


@providers_router.post("/{provider_id}/enable")
async def enable_provider(provider_id: str) -> dict:
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
    return {"ok": True, "provider_id": provider_id, "enabled": True}


@providers_router.post("/{provider_id}/rotate-key")
async def rotate_key(provider_id: str) -> dict:
    """Rotation is a stub here — surfaces what the production flow would do."""
    p = PROVIDERS_BY_ID.get(provider_id)
    if not p:
        raise HTTPException(404, f"Unknown provider: {provider_id}")
    create_provider_audit_event(
        provider=p, use_case="key_rotation", ai_system_id=None,
        data_classes=[], decision=AuditDecision.SIMULATED, user="user",
        reason=("Key rotation requested. Production flow: invoke "
                "Secrets Manager / Vault rotation policy; never exposes raw key to UI."),
    )
    return {
        "ok": True, "provider_id": provider_id,
        "secret_ref": p.api_key_secret_ref,
        "note": ("Rotation must be performed by the secrets-management backend. "
                  "This endpoint records the request only."),
    }


@providers_router.get("/audit/list")
async def audit_list(limit: int = 200) -> dict:
    rows = [r.__dict__ for r in list_audit(limit=limit)]
    return {"audit": rows}


# ===========================================================================
# Assurance-model invocations (policy-gated)
# ===========================================================================

class AskRequest(BaseModel):
    use_case: str = Field(default="", description="UseCase enum value — set by endpoint if omitted")
    ai_system_id: str | None = None
    data_classes: list[str] = Field(default_factory=list)
    question: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    preferred_provider: str | None = None
    user: str = "anonymous"


def _dispatch(req: AskRequest) -> dict:
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
        return {
            "status": "blocked",
            "provider": None, "model": None,
            "use_case": req.use_case,
            "response": None,
            "policy_decision": explain_provider_decision(decision),
            "audit_event_id": audit.id,
        }

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
        return {
            "status": "blocked",
            "provider": decision.provider.provider_name,
            "model": decision.provider.default_model,
            "use_case": req.use_case,
            "response": None,
            "policy_decision": {"reason": why, "allowed": False},
            "audit_event_id": audit.id,
        }

    # Sanitize payload before any dispatch
    sanitized = sanitize_payload_for_provider(decision.provider, payload)

    # No real API calls in this build — record SIMULATED.
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
                   else "no live credentials — simulated response.")),
        model=decision.provider.default_model,
        token_estimate=tok, cost_estimate_usd=cost,
        response_snippet=response_text[:300],
    )

    return {
        "status": "simulated",
        "provider": decision.provider.provider_name,
        "provider_id": decision.provider.provider_id,
        "model": decision.provider.default_model,
        "use_case": req.use_case,
        "response": response_text,
        "policy_decision": explain_provider_decision(decision),
        "audit_event_id": audit.id,
        "sanitized_redactions": sanitized.get("_redacted_fields", []),
    }


@router.post("/ask")
async def ask(req: AskRequest) -> dict:
    """Generic 'Ask about this AI system' — bound to SYSTEM_QA use case."""
    if not req.use_case:
        req.use_case = UseCase.SYSTEM_QA.value
    return _dispatch(req)


@router.post("/summarize-finding")
async def summarize_finding(req: AskRequest) -> dict:
    req.use_case = UseCase.FINDINGS_SUMMARIZATION.value
    return _dispatch(req)


@router.post("/explain-release")
async def explain_release(req: AskRequest) -> dict:
    req.use_case = UseCase.RELEASE_DECISION_NARRATIVE.value
    return _dispatch(req)


@router.post("/summarize-evidence")
async def summarize_evidence(req: AskRequest) -> dict:
    req.use_case = UseCase.EVIDENCE_SUMMARIZATION.value
    return _dispatch(req)


@router.post("/draft-report")
async def draft_report(req: AskRequest) -> dict:
    req.use_case = UseCase.EXECUTIVE_REPORT_GENERATION.value
    return _dispatch(req)
