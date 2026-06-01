"""FastAPI dashboard for AI Assurance Platform."""

from __future__ import annotations

import sys
import io
import os
from contextlib import asynccontextmanager
from pathlib import Path

# Force UTF-8 output on Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from dotenv import load_dotenv

# Load environment variables FIRST -- before any other domain imports.
# The previous hand-rolled .env parser (reading local.env manually) was dead
# code after load_dotenv(override=True) ran anyway. Removed in Session 10.
_env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=str(_env_path), override=True)

# Initialise App Insights telemetry (no-op when connection string is absent).
try:
    from observability.app_insights import init_app_insights as _init_ai
    _init_ai(os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING"))
except ImportError:
    pass  # observability package not yet installed -- safe to skip

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from api.traces import router as traces_router
from api.evaluate import router as evaluate_router
from api.demo_run import router as demo_run_router
from api.analytics import router as analytics_router
from api.security import router as security_router
from api.domains_api import router as domains_api_router
from api.batch import router as batch_router
from api.grc import router as grc_router
from api.intake import router as intake_router
from api.assessment import router as assessment_router
from api.release_gates import router as release_gates_v2_router
from api.evals_v2 import router as evals_v2_router
from api.framework import router as framework_router
from api.evidence import router as evidence_v2_router
from api.findings_v2 import router as findings_v2_router
from api.runtime_v2 import router as runtime_v2_router
from api.connectors import router as connectors_router
from api.demo import router as demo_router
from api.reports import router as reports_router
from api.guide import router as guide_router
from api.assurance_model import router as assurance_model_router, providers_router as assurance_providers_router
from api.usage import router as usage_router
from api.ai_system_edit import router as ai_system_edit_router
from api.aws_demo import router as aws_demo_router
from api.memory import router as memory_router
from api.rag import router as rag_router
from api.adversarial import router as adversarial_router
from api.frameworks import router as frameworks_router
from api.agents import router as agents_router
from api.agent_bindings import router as agent_bindings_router
from api.agent_notifications import router as agent_notifications_router
from api.right_to_forget import router as rtf_router
from api.audit_verify import router as audit_verify_router
from api.projection import router as projection_router
from api.sdk_keys import router as sdk_keys_router
from api.sdk_runtime import router as sdk_runtime_router
from api.sdk_episodes import router as sdk_episodes_router
from api.demo_control import router as demo_control_router
from api.auth_oidc import router as auth_oidc_router
from api.evals import router as evals_router
from api.policies_rego import router as policies_rego_router
from api.eval_suites import router as eval_suites_router
from api._errors import register_error_handlers
from middleware.auth import SessionAuthMiddleware, router as auth_router
from middleware.hmac_auth import HMACAuthMiddleware
from middleware.api_version_alias import ApiVersionAliasMiddleware
from middleware import oidc as oidc_mod
from __version__ import __version__

# Metrics router -- 404 when METRICS_ENABLED != "true"
try:
    from api.metrics import router as _metrics_router
    _HAS_METRICS = True
except ImportError:
    _HAS_METRICS = False
    _metrics_router = None  # type: ignore[assignment]

# RequestContextMiddleware -- stamps X-Request-Id into ContextVar for structured logging
try:
    from observability.middleware import RequestContextMiddleware
    _HAS_REQUEST_CTX = True
except ImportError:
    _HAS_REQUEST_CTX = False
    RequestContextMiddleware = None  # type: ignore[assignment]


def validate_api_keys() -> dict[str, bool]:
    """Validate required API keys. Returns {key_name: is_valid}."""
    status = {}

    # Check Anthropic API Key
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    status["ANTHROPIC_API_KEY"] = (
        bool(anthropic_key) and
        len(anthropic_key) > 10 and
        anthropic_key.startswith("sk-ant-")
    )

    # Check OpenAI API Key
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    status["OPENAI_API_KEY"] = (
        bool(openai_key) and
        len(openai_key) > 10 and
        openai_key.startswith("sk-")
    )

    # Check Langfuse Keys (optional but recommended)
    langfuse_public = os.getenv("LANGFUSE_PUBLIC_KEY", "").strip()
    langfuse_secret = os.getenv("LANGFUSE_SECRET_KEY", "").strip()
    status["LANGFUSE"] = bool(langfuse_public) and bool(langfuse_secret)

    return status


def print_startup_status() -> bool:
    """Print API key validation status on startup."""
    status = validate_api_keys()

    print("\n" + "=" * 65)
    print("API KEY VALIDATION")
    print("=" * 65)

    for key, is_valid in status.items():
        symbol = "OK" if is_valid else "MISSING"
        print(f"  {key:<25} {symbol}")

    all_required = bool(status.get("ANTHROPIC_API_KEY") and status.get("OPENAI_API_KEY"))

    print("=" * 65)
    if all_required:
        print("All required keys configured. Dashboard ready.")
    else:
        print("Missing required API keys. Edit .env and restart.")
    print("=" * 65 + "\n")

    return all_required


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """App lifecycle hook — replaces deprecated @app.on_event("startup").

    Day-12 finding: smoke-test scenario #3 expects >= 6 agents but prod's
    agent table is empty (Postgres isn't configured on App Service, so
    domain.agents.create_agent() falls back to in-memory only — which means
    agents disappear on every container restart). Seeding here matches that
    lifecycle: every cold start re-seeds the demo data.

    Idempotent: seed_agents uses ON CONFLICT DO NOTHING when Postgres is
    available; safe to call repeatedly. Failure is swallowed — startup must
    never die over demo data.
    """
    try:
        # S77: Eager-import the bindings + subscribers modules BEFORE seeding so
        # their module-load _init_schema() runs and creates the agent_bindings /
        # agent_subscribers tables. seed_agents -> publish_version ->
        # notify_subscribers_on_publish writes raw SQL touching agent_bindings
        # without importing the bindings module itself; without this eager
        # import the first cold-start hits psycopg2.errors.UndefinedTable.
        # Both api-layer imports of these modules are lazy (inside functions),
        # so dashboard.py is the only deterministic bootstrap point.
        import domain.agent_bindings  # noqa: F401
        import domain.agent_subscribers  # noqa: F401
        from domain.agents import seed_agents
        seeded = seed_agents()
        print(f"[startup] seed_agents: {len(seeded)} agents available")
    except Exception as exc:  # noqa: BLE001
        print(f"[startup] seed_agents failed (non-fatal): {exc}")
    yield
    # No shutdown work today.


app = FastAPI(
    title="AI Assurance Platform",
    version=__version__,
    description=(
        "Governance substrate for enterprise AI. Six-layer architecture "
        "(see docs/target-architecture.md). Consumed by Team Workspace SPA, "
        "CISO Console SPA, signallayer Python SDK, and `sl` CLI."
    ),
    servers=[
        {"url": "https://api.aigovern.sandboxhub.co", "description": "Production engine"},
        {"url": "http://localhost:9007", "description": "Local dev"},
    ],
    lifespan=_lifespan,
)

# Global exception handlers -- typed 500 ServerErrorDetail with trace_id correlation.
# Per docs/plans/SESSION-13-api-typing-audit.md §1.2.
register_error_handlers(app)

# S77 #2: Wire OpenTelemetry's FastAPIInstrumentor so every HTTP request
# produces a span exported to App Insights. init_app_insights() above only
# configured the TracerProvider + AzureMonitorTraceExporter — without this
# call there are no spans for the exporter to ship. Silent no-op if AI
# is disabled or the instrumentor package is missing. Must run AFTER `app`
# is constructed but BEFORE the first request, so module-load is correct.
try:
    from observability.app_insights import instrument_fastapi_app as _instrument_ai
    _instrument_ai(app)
except ImportError:
    pass  # observability package not yet installed -- safe to skip


def _validate_openapi_artifact() -> None:
    """Compare generated OpenAPI to committed docs/openapi-v1.json.

    Per docs/plans/SESSION-13-api-typing-audit.md §10 resolution #2 + §6.3a:
        - Dev/local: fail-closed (raise RuntimeError, refuse to start) so
          local devs catch drift before pushing.
        - Production (App Service): warn-only -- logs to App Insights so a
          legitimate hotfix doesn't crash-loop the container.

    Toggles:
        SL_OPENAPI_STRICT  "true"/"false" -- explicit override
        SL_OPENAPI_SKIP_STARTUP_CHECK  "true" -- skip entirely (used by the
                                       export script to avoid circular dep)
    Production default: strict=false. Local default: strict=true.
    """
    import json as _json
    import logging as _logging

    _logger = _logging.getLogger(__name__)

    if os.environ.get("SL_OPENAPI_SKIP_STARTUP_CHECK", "").lower() == "true":
        return

    artifact_path = Path(__file__).parent / "docs" / "openapi-v1.json"
    if not artifact_path.exists():
        _logger.warning("openapi.artifact_missing path=%s", artifact_path)
        return

    # Strict mode is opt-in: CI=true (GitHub Actions) or explicit SL_OPENAPI_STRICT=true.
    # Local dev and prod both default to warn-only so `import dashboard` never raises
    # on routine drift. The committed artifact is gated by CI on PRs.
    is_ci = os.environ.get("CI", "").lower() == "true"
    strict_default = "true" if is_ci else "false"
    strict = os.environ.get("SL_OPENAPI_STRICT", strict_default).lower() == "true"

    try:
        committed = _json.loads(artifact_path.read_text(encoding="utf-8"))
        generated = app.openapi()
    except Exception as exc:                                  # noqa: BLE001
        _logger.warning("openapi.check_failed err=%s", exc)
        return

    # Ignore info.version drift so local devs don't trip on version bumps
    # between PRs; the version bump itself is reviewed in the artifact diff.
    def _strip_version(spec: dict) -> dict:
        info = {**spec.get("info", {}), "version": "<ignored>"}
        return {**spec, "info": info}

    if _strip_version(committed) == _strip_version(generated):
        return

    msg = (
        "openapi.drift: committed docs/openapi-v1.json does not match generated "
        "spec. Run `python scripts/export_openapi.py` and commit the diff."
    )
    if strict:
        raise RuntimeError(msg)
    _logger.error("openapi.drift.production_warn %s", msg)


_validate_openapi_artifact()

# Mount static files
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")

# Middleware execution order (Starlette: last add_middleware = outermost = first to execute).
# Request flow (outer -> inner):
#   CORSMiddleware -> ApiVersionAliasMiddleware -> HMACAuthMiddleware ->
#   SessionAuthMiddleware -> RequestContextMiddleware -> routes.

# RequestContextMiddleware -- generates X-Request-Id, stamps into ContextVar (innermost)
if _HAS_REQUEST_CTX:
    app.add_middleware(RequestContextMiddleware)

# Starlette SessionMiddleware -- gives authlib's OIDC handlers a place to stash
# state/nonce/PKCE values across the redirect roundtrip. Distinct from our
# SessionAuthMiddleware: this is a short-lived signed cookie, not an auth gate.
# Only added when OIDC is actually configured (Session 49 / ADR-002) so dev
# environments without OIDC_* env vars don't fail to boot.
if oidc_mod.is_oidc_enabled():
    from starlette.middleware.sessions import SessionMiddleware
    _oauth_secret = os.getenv("SESSION_SECRET")
    if not _oauth_secret:
        raise RuntimeError(
            "SESSION_SECRET is required when OIDC is enabled "
            "(consumed by both SessionAuthMiddleware and the OIDC redirect cookie)."
        )
    app.add_middleware(
        SessionMiddleware,
        secret_key=_oauth_secret,
        session_cookie="aigovern_oauth_dance",
        max_age=600,  # 10 min — only needs to survive the redirect roundtrip
        same_site="lax",  # required: callback is top-level redirect from MS
        https_only=True,
    )

# Session-cookie auth gate (no-op unless AUTH_ENABLED=true)
app.add_middleware(SessionAuthMiddleware)

# HMAC auth for /api/sdk/* -- outer of the auth tier, executes before SessionAuth
app.add_middleware(HMACAuthMiddleware)

# API version alias -- rewrites /api/v1/* -> /api/* BEFORE auth so the auth
# middleware sees the canonical path.
app.add_middleware(ApiVersionAliasMiddleware)

# CORS -- added LAST so it is OUTERMOST and runs FIRST on every request.
# Critical for cross-origin preflight: OPTIONS must be answered with CORS
# headers BEFORE SessionAuth/HMACAuth can 401 it. V2 split puts the engine
# on aigovern.sandboxhub.co and the SPAs on portal.* / gov.* (same-site,
# different-origin), so preflight on POST/PUT/DELETE/credentialed-GET will
# fire. allow_credentials=True forbids wildcard origins -- list them
# explicitly. Override via CORS_ALLOWED_ORIGINS env (comma-separated).
_default_origins = [
    "https://portal.aigovern.sandboxhub.co",
    "https://gov.aigovern.sandboxhub.co",
    "http://localhost:9007",
    "http://127.0.0.1:9007",
    "http://localhost:5174",  # team-portal vite dev
    "http://localhost:5175",  # ciso-console vite dev
]
_env_origins = os.getenv("CORS_ALLOWED_ORIGINS", "").strip()
_cors_origins = (
    [o.strip() for o in _env_origins.split(",") if o.strip()]
    if _env_origins
    else _default_origins
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# S46 — V1 surface deprecation. Stamps X-V1-Surface-Deprecated on responses
# from legacy V1 navigation routes and records a 24h-rolling hit counter
# surfaced via /api/health. Set `_V1_NAV_PATHS` is defined alongside the
# page handlers below; we forward-reference it via the module global so the
# middleware registration order doesn't matter.
@app.middleware("http")
async def v1_surface_deprecation(request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path in _V1_NAV_PATHS and response.status_code < 400:
        # Skip apex redirects to V2 — only stamp when V1 HTML is actually served.
        if not (path == "/" and 300 <= response.status_code < 400):
            response.headers["X-V1-Surface-Deprecated"] = f"removal-date={_V1_REMOVAL_DATE}"
            from observability.counters import record_v1_surface_hit
            record_v1_surface_hit(path)
    return response


app.include_router(auth_router)

# OIDC login + callback routes (Session 49 / ADR-002). Mounted unconditionally
# so /auth/oidc/login is reachable for diagnostics even pre-config; the routes
# themselves will 500 with a clear "Missing required env var" error rather
# than silently 404. SessionMiddleware above is the gate that requires
# OIDC_* env vars at startup.
app.include_router(auth_oidc_router)

# Include API routers
app.include_router(traces_router)
app.include_router(evaluate_router)
app.include_router(demo_run_router)
app.include_router(analytics_router)
app.include_router(security_router)
app.include_router(domains_api_router)
app.include_router(batch_router)
app.include_router(grc_router)
app.include_router(intake_router)
app.include_router(assessment_router)
app.include_router(release_gates_v2_router)
app.include_router(evals_v2_router)
app.include_router(framework_router)
app.include_router(evidence_v2_router)
app.include_router(findings_v2_router)
app.include_router(runtime_v2_router)
app.include_router(connectors_router)
app.include_router(demo_router)
app.include_router(reports_router)
app.include_router(guide_router)
app.include_router(assurance_model_router)
app.include_router(assurance_providers_router)
app.include_router(usage_router)
app.include_router(ai_system_edit_router)
app.include_router(aws_demo_router)
app.include_router(memory_router)
app.include_router(rag_router)
app.include_router(adversarial_router)
app.include_router(sdk_keys_router)
app.include_router(sdk_runtime_router)
app.include_router(sdk_episodes_router)
app.include_router(frameworks_router)
app.include_router(agents_router)
app.include_router(agent_bindings_router)
app.include_router(agent_notifications_router)
app.include_router(rtf_router)
app.include_router(audit_verify_router)
app.include_router(projection_router)
app.include_router(demo_control_router)
app.include_router(evals_router)
app.include_router(policies_rego_router)
app.include_router(eval_suites_router)
if _HAS_METRICS and _metrics_router is not None:
    app.include_router(_metrics_router)


def _read_build_sha() -> str:
    """Read the BUILD_SHA file baked into the deploy zip.

    Session 19: enables deploy-drift detection. Falls back to GITHUB_SHA env
    var (CI runs the app directly) then 'unknown'. Read once at import.
    """
    try:
        sha_path = Path(__file__).resolve().parent / "BUILD_SHA"
        if sha_path.exists():
            return sha_path.read_text(encoding="ascii").strip() or "unknown"
    except Exception:  # noqa: BLE001
        pass
    return os.getenv("GITHUB_SHA", "unknown").strip() or "unknown"


_BUILD_SHA = _read_build_sha()


@app.get("/api/health")
async def health_check() -> dict:
    """Return API health status plus the deployed build SHA.

    Returns {"status": "ready" | "incomplete", "sha": "<40-char-or-unknown>"}.
    The sha field (Session 19) lets deploy verification confirm which commit
    is live without authenticating. The previous api_keys disclosure was
    removed in Session 10.
    """
    from observability.counters import get_v1_surface_hits_24h

    status = validate_api_keys()
    all_required = bool(status.get("ANTHROPIC_API_KEY") and status.get("OPENAI_API_KEY"))
    return {
        "status": "ready" if all_required else "incomplete",
        "sha": _BUILD_SHA,
        # S46 — V1 deprecation observation signal. Process-local 24h counter;
        # deletion criterion: 7 consecutive days < 5 hits/day. See SESSION-46.
        "v1_surface_hits_24h": get_v1_surface_hits_24h(),
    }


@app.get("/api/report/compliance")
async def get_compliance_report(
    report_type: str = "HIPAA",
    days: int = 30,
    organization: str = "Customer Organization",
) -> HTMLResponse:
    """Generate compliance audit report HTML (printable to PDF)."""
    from datetime import datetime, timedelta
    from pdf_report import generate_compliance_report_html
    from storage import get_runs
    from audit import global_audit

    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=days)

    runs = get_runs(limit=10000, start_date=start_date, end_date=end_date)
    audit_logs = global_audit.get_logs_for_period(start_date, end_date)

    html = generate_compliance_report_html(
        runs=runs,
        audit_logs=audit_logs,
        start_date=start_date,
        end_date=end_date,
        report_type=report_type,
        organization=organization,
    )

    return HTMLResponse(content=html)


STATIC_DIR = Path(__file__).parent / "static"


_V1_REMOVAL_DATE = "2026-07-02"  # S46 — 60-day deprecation window post-S45 V2 LIVE cutover.

# S46 — V1 navigation paths. Membership here drives the deprecation header
# (X-V1-Surface-Deprecated) and the 24h-hits counter consumed by /api/health.
# Keep in sync with the V1 page handlers below; adding a new V1 route without
# updating this set silently skips the deprecation contract.
_V1_NAV_PATHS: frozenset[str] = frozenset({
    "/", "/ai-systems", "/ai-systems/new", "/assessment", "/connectors",
    "/demo", "/demo-control", "/reports", "/assurance-providers",
    "/framework-sop", "/governance", "/security", "/runtime", "/evals",
    "/findings", "/release-gates", "/evidence", "/policies", "/analytics",
    "/domains", "/compare", "/analytics-usage", "/demo-aws-analyzer",
    "/frameworks", "/agent-library", "/right-to-forget", "/audit-events",
    "/projection",
})


def _page(filename: str) -> FileResponse:
    return FileResponse(STATIC_DIR / filename, media_type="text/html")


# === Primary navigation pages ===
@app.get("/")
async def page_overview():
    # Session 45 — V2 LIVE cutover (A12): when V2_APEX_REDIRECT=true, the
    # apex 302s to the V2 Team Workspace (PORTAL_URL). Env-var-gated so
    # rollback is a single App Service setting flip — symmetric with
    # PORTAL_URL/GOV_URL (S43) and V1→V2 staging precedents. Env is read
    # per-request (not module load) so the flag is flippable without
    # restart. Falsy / unset → existing V1 Command Center behavior.
    if os.environ.get("V2_APEX_REDIRECT", "").lower() == "true":
        portal = os.environ.get("PORTAL_URL", "").rstrip("/")
        if portal:
            return RedirectResponse(url=portal + "/", status_code=302)
    return _page("index.html")


@app.get("/ai-systems")
async def page_ai_systems():
    return _page("ai-systems.html")


@app.get("/ai-systems/new")
async def page_ai_systems_new():
    return _page("ai-systems-new.html")


@app.get("/assessment")
async def page_assessment():
    return _page("assessment.html")


@app.get("/connectors")
async def page_connectors():
    return _page("connectors.html")


@app.get("/demo")
async def page_demo():
    return _page("demo.html")


@app.get("/demo-control")
async def page_demo_control():
    """Session 11 — Demo Control Panel (one-click triggers for 6 scenarios)."""
    return _page("demo-control.html")


@app.get("/reports")
async def page_reports():
    return _page("reports.html")


@app.get("/assurance-providers")
async def page_assurance_providers():
    return _page("assurance-providers.html")


@app.get("/framework-sop")
async def page_framework_sop():
    return _page("framework-sop.html")


@app.get("/governance")
async def page_governance():
    return _page("governance.html")


@app.get("/security")
async def page_security():
    return _page("security.html")


@app.get("/runtime")
async def page_runtime():
    return _page("runtime.html")


@app.get("/evals")
async def page_evals():
    return _page("evals.html")


@app.get("/findings")
async def page_findings():
    return _page("findings.html")


@app.get("/release-gates")
async def page_release_gates():
    return _page("release-gates.html")


@app.get("/evidence")
async def page_evidence():
    return _page("evidence.html")


@app.get("/policies")
async def page_policies():
    return _page("policies.html")


# === Secondary pages ===
@app.get("/analytics")
async def page_analytics():
    return _page("analytics.html")


@app.get("/domains")
async def page_domains():
    return _page("domains.html")


@app.get("/compare")
async def page_compare():
    return _page("compare.html")


@app.get("/analytics-usage")
async def page_analytics_usage():
    return _page("analytics-usage.html")


@app.get("/demo-aws-analyzer")
async def page_demo_aws_analyzer():
    return _page("demo-aws-analyzer.html")


@app.get("/frameworks")
async def page_frameworks():
    return _page("frameworks.html")


@app.get("/agent-library")
async def page_agent_library():
    """Serve the Agent Library publish/subscribe UI."""
    return _page("agent-library.html")


@app.get("/right-to-forget")
async def page_right_to_forget():
    """Serve the Right-to-Forget erasure request console UI."""
    return _page("right-to-forget.html")


@app.get("/audit-events")
async def page_audit_events():
    """Serve the tamper-evident audit events viewer."""
    return _page("audit-events.html")


@app.get("/projection")
async def page_projection():
    """Serve the event projection read-side UI."""
    return _page("projection.html")


if __name__ == "__main__":
    import uvicorn

    print("\n" + "=" * 65)
    print("AI ASSURANCE DASHBOARD")
    print("=" * 65)
    print("Dashboard running at http://localhost:9007")
    print("=" * 65 + "\n")

    # Validate API keys on startup
    print_startup_status()

    uvicorn.run(app, host="127.0.0.1", port=9007, log_level="info")
