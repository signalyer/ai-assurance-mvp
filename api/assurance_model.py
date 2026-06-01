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

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sse_starlette.sse import EventSourceResponse

from domain.assurance_providers import (
    PROVIDERS_BY_ID, AuditDecision, UseCase,
    list_providers, get_provider, policy_summary,
    select_assurance_provider, validate_provider_policy,
    sanitize_payload_for_provider, create_provider_audit_event,
    have_real_credentials, simulate_response,
    list_audit, explain_provider_decision,
    real_llm_enabled, stream_anthropic_response,
    stream_bedrock_response, stream_local_response, ProviderType,
)
from domain.assurance_providers import _build_prompt  # S78: episodic memory write

_log = logging.getLogger(__name__)

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

    status: str = Field(description="blocked | simulated | live")
    provider: str | None = None
    provider_id: str | None = None
    model: str | None = None
    use_case: str
    response: str | None = None
    policy_decision: PolicyDecisionOut | None = None
    audit_event_id: str
    sanitized_redactions: list[str] = Field(default_factory=list)
    governance: GovernanceMetadata | None = None
    # S69: populated on status='live' from Anthropic usage block; absent on
    # 'simulated' / 'blocked'. Drawer surfaces both rows in the routing dl
    # so operators know what a click costs.
    token_estimate: int | None = None
    cost_estimate_usd: float | None = None
    streaming_complete: bool | None = None


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
        checked_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
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
    operation_id="assurance_ask",
)
async def ask(req: AskRequest, request: Request):
    """Generic 'Ask about this AI system' -- bound to SYSTEM_QA use case.

    S72: streams real Anthropic deltas when REAL_LLM_ENABLED + creds present
    (same SSE contract as /explain-release).
    """
    if not req.use_case:
        req.use_case = UseCase.SYSTEM_QA.value
    return _dispatch_streaming(req, request)


@router.post(
    "/summarize-finding",
    operation_id="assurance_summarize_finding",
)
async def summarize_finding(req: AskRequest, request: Request):
    """S72: streaming SSE — see /explain-release for the response shape."""
    req.use_case = UseCase.FINDINGS_SUMMARIZATION.value
    return _dispatch_streaming(req, request)


# ---------------------------------------------------------------------------
# S69: streaming dispatch for /explain-release
# ---------------------------------------------------------------------------

def _sim_response_to_sse_done(resp: AskResponseOut) -> dict:
    """Wrap an AskResponseOut as the terminal SSE 'done' event payload.

    Drawer parses the data JSON and treats this identically to the legacy
    JSON response, so blocked/simulated paths route through the same UI
    code regardless of whether they came via _dispatch or _dispatch_streaming.
    """
    return {"event": "done", "data": resp.model_dump_json()}


async def _stream_live_assurance_response(
    req: AskRequest,
    decision,  # RoutingDecision
    sanitized: dict,
    request: Request,
):
    """Yield SSE events for a live streaming LLM call (provider-agnostic).

    Dispatches to Bedrock vs Anthropic based on the upstream routing
    decision's provider_type. The generators share an identical yield
    contract (("delta", text) | ("done", usage_dict)) so the audit /
    response shape below is provider-agnostic.

    Handles three terminal states:
      - completed normally -> emit final 'done' with status='live', LIVE audit
      - client disconnect (CancelledError) -> LIVE audit, streaming_complete=False
      - provider / network exception -> emit 'done' with status='blocked' framing
        and BLOCKED audit (so the drawer surfaces a clean error instead of hanging)
    """
    partial_text: list[str] = []
    final_usage: dict | None = None
    # S75/S79: pick the streaming generator by provider_type. All three
    # generators share an identical yield contract so the audit + episode
    # write below is provider-agnostic. Local-simulated is the internal-path
    # demo provider for the S79 dual-path showcase — same governance chain,
    # zero egress, zero cost.
    if decision.provider.provider_type == ProviderType.BEDROCK.value:
        stream_fn = stream_bedrock_response
    elif decision.provider.provider_type == ProviderType.LOCAL.value:
        stream_fn = stream_local_response
    else:
        stream_fn = stream_anthropic_response
    try:
        async for kind, value in stream_fn(
            provider=decision.provider,
            use_case=req.use_case,
            sanitized=sanitized,
        ):
            if kind == "delta":
                partial_text.append(value)
                yield {"event": "delta", "data": json.dumps({"text": value})}
            elif kind == "done":
                final_usage = value
        # Normal completion path.
        assert final_usage is not None
        audit = create_provider_audit_event(
            provider=decision.provider, use_case=req.use_case,
            ai_system_id=req.ai_system_id, data_classes=req.data_classes,
            decision=AuditDecision.LIVE, user=req.user,
            reason=(
                f"Live streaming call completed via {decision.provider.provider_name}; "
                f"token_estimate={final_usage['token_estimate']}, "
                f"cost_estimate_usd={final_usage['cost_estimate_usd']}."
            ),
            model=final_usage["model"],
            token_estimate=final_usage["token_estimate"],
            cost_estimate_usd=final_usage["cost_estimate_usd"],
            response_snippet=final_usage["full_text"][:300],
            streaming_complete=True,
        )
        final_resp = AskResponseOut(
            status="live",
            provider=decision.provider.provider_name,
            provider_id=decision.provider.provider_id,
            model=final_usage["model"],
            use_case=req.use_case,
            response=final_usage["full_text"],
            policy_decision=PolicyDecisionOut(**explain_provider_decision(decision)),
            audit_event_id=audit.id,
            sanitized_redactions=sanitized.get("_redacted_fields", []),
            governance=GovernanceMetadata(policy_decision="ALLOW"),
            token_estimate=final_usage["token_estimate"],
            cost_estimate_usd=final_usage["cost_estimate_usd"],
            streaming_complete=True,
        )
        # S78: persist episode to T2 (Postgres). Non-fatal — the user's SSE
        # response has already been sent. workload_id = ai_system_id when
        # present, else use_case (covers non-system surfaces like Ask AI).
        try:
            from domain.agent_memory import write_episode
            _sys_prompt, _user_prompt = _build_prompt(req.use_case, sanitized)
            write_episode(
                workload_id=(req.ai_system_id or req.use_case or "unknown"),
                prompt=_user_prompt,
                response=final_usage["full_text"],
                outcome="success",
                metadata={
                    "trace_id": audit.id,
                    "use_case": req.use_case,
                    "provider_id": decision.provider.provider_id,
                    "model": final_usage["model"],
                    "token_estimate": final_usage["token_estimate"],
                    "cost_estimate_usd": final_usage["cost_estimate_usd"],
                    "user": req.user,
                },
            )
        except Exception:
            _log.exception("S78: write_episode failed (non-fatal)")
        yield {"event": "done", "data": final_resp.model_dump_json()}
    except asyncio.CancelledError:
        # Client closed the SSE stream before we finished. Record a partial
        # audit row so CISO Console can surface "user abandoned" — important
        # signal for cost attribution.
        snippet = "".join(partial_text)[:300]
        create_provider_audit_event(
            provider=decision.provider, use_case=req.use_case,
            ai_system_id=req.ai_system_id, data_classes=req.data_classes,
            decision=AuditDecision.LIVE, user=req.user,
            reason=(
                "Live streaming call cancelled by client mid-stream; "
                f"partial chars={len(snippet)}."
            ),
            model=decision.provider.default_model,
            token_estimate=0, cost_estimate_usd=0.0,
            response_snippet=snippet, streaming_complete=False,
        )
        raise
    except Exception as exc:  # noqa: BLE001 — top of SSE handler, must not crash worker
        _log.exception("Live LLM streaming failed for use_case=%s", req.use_case)
        audit = create_provider_audit_event(
            provider=decision.provider, use_case=req.use_case,
            ai_system_id=req.ai_system_id, data_classes=req.data_classes,
            decision=AuditDecision.BLOCKED, user=req.user,
            reason=f"Live LLM call failed: {type(exc).__name__}: {str(exc)[:160]}",
            model=decision.provider.default_model,
            token_estimate=0, cost_estimate_usd=0.0,
            streaming_complete=False,
        )
        err_resp = AskResponseOut(
            status="blocked",
            provider=decision.provider.provider_name,
            provider_id=decision.provider.provider_id,
            model=decision.provider.default_model,
            use_case=req.use_case,
            response=None,
            policy_decision=PolicyDecisionOut(
                reason=f"Upstream LLM error: {type(exc).__name__}",
                allowed=False,
            ),
            audit_event_id=audit.id,
            governance=GovernanceMetadata(policy_decision="DENY"),
            streaming_complete=False,
        )
        # S78: persist failure episode to T2 so reliability metrics see it.
        try:
            from domain.agent_memory import write_episode
            _sys_prompt, _user_prompt = _build_prompt(req.use_case, sanitized)
            write_episode(
                workload_id=(req.ai_system_id or req.use_case or "unknown"),
                prompt=_user_prompt,
                response="".join(partial_text),
                outcome="failure",
                metadata={
                    "trace_id": audit.id,
                    "use_case": req.use_case,
                    "provider_id": decision.provider.provider_id,
                    "model": decision.provider.default_model,
                    "error_type": type(exc).__name__,
                    "user": req.user,
                },
            )
        except Exception:
            _log.exception("S78: write_episode (failure path) failed (non-fatal)")
        yield {"event": "done", "data": err_resp.model_dump_json()}


def _dispatch_streaming(req: AskRequest, request: Request) -> EventSourceResponse:
    """Streaming variant of _dispatch.

    Always returns an EventSourceResponse so the SPA can keep a single
    consumption path. The blocked/simulated paths emit a single 'done' event
    and close immediately -- drawer parses the final AskResponseOut JSON the
    same way it did pre-S69. Only the live path streams real deltas.
    """
    # Resolve the routing decision synchronously -- this part is identical
    # to _dispatch and doesn't benefit from being async.
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

    # Path 1: policy engine blocked the call.
    if not decision.allowed or decision.provider is None:
        audit = create_provider_audit_event(
            provider=None, use_case=req.use_case,
            ai_system_id=req.ai_system_id, data_classes=req.data_classes,
            decision=AuditDecision.BLOCKED, user=req.user,
            reason=decision.reason,
        )
        blocked_resp = AskResponseOut(
            status="blocked",
            provider=None, provider_id=None, model=None,
            use_case=req.use_case, response=None,
            policy_decision=PolicyDecisionOut(**explain_provider_decision(decision)),
            audit_event_id=audit.id,
            governance=GovernanceMetadata(policy_decision="DENY"),
        )
        async def _blocked_gen():
            yield _sim_response_to_sse_done(blocked_resp)
        return EventSourceResponse(_blocked_gen())

    # Defense-in-depth re-check.
    ok, why = validate_provider_policy(
        decision.provider, {"use_case": req.use_case, "data_classes": req.data_classes},
    )
    if not ok:
        audit = create_provider_audit_event(
            provider=decision.provider, use_case=req.use_case,
            ai_system_id=req.ai_system_id, data_classes=req.data_classes,
            decision=AuditDecision.BLOCKED, user=req.user, reason=why,
        )
        blocked_resp = AskResponseOut(
            status="blocked",
            provider=decision.provider.provider_name,
            provider_id=decision.provider.provider_id,
            model=decision.provider.default_model,
            use_case=req.use_case, response=None,
            policy_decision=PolicyDecisionOut(reason=why, allowed=False),
            audit_event_id=audit.id,
            governance=GovernanceMetadata(policy_decision="DENY"),
        )
        async def _recheck_blocked_gen():
            yield _sim_response_to_sse_done(blocked_resp)
        return EventSourceResponse(_recheck_blocked_gen())

    sanitized = sanitize_payload_for_provider(decision.provider, payload)

    # Path 2: live path is gated by env flag AND real credentials. If either
    # is missing, fall back to sim -- this is the safe, audited fallback the
    # plan calls out (failure mode #1 in the verification list).
    if real_llm_enabled() and have_real_credentials(decision.provider):
        async def _live_gen():
            async for ev in _stream_live_assurance_response(req, decision, sanitized, request):
                yield ev
        return EventSourceResponse(_live_gen())

    # Path 3: simulated (REAL_LLM_ENABLED=false OR no credentials).
    response_text = simulate_response(req.use_case, decision.provider, sanitized)
    tok = max(120, len(response_text) // 4)
    cost = round(tok * 0.000005, 5)
    audit = create_provider_audit_event(
        provider=decision.provider, use_case=req.use_case,
        ai_system_id=req.ai_system_id, data_classes=req.data_classes,
        decision=AuditDecision.SIMULATED, user=req.user,
        reason=(
            "Routed via policy engine; "
            + (
                "real credentials present but REAL_LLM_ENABLED=false -- simulated response."
                if have_real_credentials(decision.provider)
                else "no live credentials -- simulated response."
            )
        ),
        model=decision.provider.default_model,
        token_estimate=tok, cost_estimate_usd=cost,
        response_snippet=response_text[:300],
    )
    sim_resp = AskResponseOut(
        status="simulated",
        provider=decision.provider.provider_name,
        provider_id=decision.provider.provider_id,
        model=decision.provider.default_model,
        use_case=req.use_case,
        response=response_text,
        policy_decision=PolicyDecisionOut(**explain_provider_decision(decision)),
        audit_event_id=audit.id,
        sanitized_redactions=sanitized.get("_redacted_fields", []),
        governance=GovernanceMetadata(policy_decision="ALLOW"),
    )
    async def _sim_gen():
        yield _sim_response_to_sse_done(sim_resp)
    return EventSourceResponse(_sim_gen())


@router.post(
    "/explain-release",
    operation_id="assurance_explain_release",
)
async def explain_release(req: AskRequest, request: Request):
    """S69: streams real Anthropic deltas when REAL_LLM_ENABLED + creds present.

    Returns an SSE stream regardless of path (blocked / simulated / live) so
    the SPA can keep a single consumption pattern. Blocked + sim emit one
    terminal 'done' event; live emits deltas then 'done'.

    Note: no `response_model=AskResponseOut` here -- OpenAPI cannot represent
    SSE streams in that field. The drawer parses the 'done' event payload
    against the AskResponseOut TS interface client-side.
    """
    req.use_case = UseCase.RELEASE_DECISION_NARRATIVE.value
    return _dispatch_streaming(req, request)


@router.post(
    "/summarize-evidence",
    operation_id="assurance_summarize_evidence",
)
async def summarize_evidence(req: AskRequest, request: Request):
    """S72: streaming SSE — see /explain-release for the response shape."""
    req.use_case = UseCase.EVIDENCE_SUMMARIZATION.value
    return _dispatch_streaming(req, request)


@router.post(
    "/draft-report",
    operation_id="assurance_draft_report",
)
async def draft_report(req: AskRequest, request: Request):
    """S72: streaming SSE — see /explain-release for the response shape."""
    req.use_case = UseCase.EXECUTIVE_REPORT_GENERATION.value
    return _dispatch_streaming(req, request)
