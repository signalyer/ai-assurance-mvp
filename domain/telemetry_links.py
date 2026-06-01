"""Telemetry deep-link builders for chain.done / audit events.

Two destinations:
    - Langfuse trace viewer (per-trace URL into the Langfuse dashboard)
    - Azure Application Insights transaction search (operation_id deep link)

Both builders return `None` when the inputs needed to construct a URL are
missing — never raise, never fabricate a URL that 404s. The Agent Runner
SPA renders the link only when the URL is present.

Env contract (read once per call; cheap):
    LANGFUSE_HOST                    e.g. "https://cloud.langfuse.com"
    LANGFUSE_PROJECT_ID              "p_xxxx" (optional; some Langfuse
                                     deployments don't require it in the URL)
    APPINSIGHTS_APPLICATION_ID       Azure portal GUID for the App Insights
                                     resource (NOT the connection string).
                                     Found via:
                                       az monitor app-insights component show
                                         --app <name> --resource-group <rg>
                                         --query appId -o tsv

S82f-1: Langfuse URL stays None until S83 wires the real Langfuse trace_id
through the chain (the placeholder "" gets us no further than this).
App Insights URL works today — operation_id is the current OTel trace_id.
"""
from __future__ import annotations

import os
from typing import Optional


def appinsights_operation_id_from_context() -> Optional[str]:
    """Read the current OpenTelemetry span's trace_id as a 32-char hex string.

    App Insights stores OTel trace_id as `operation_Id`. Returns None when
    no span is active or the OTel SDK isn't imported (e.g. local dev).
    """
    try:
        from opentelemetry import trace
    except ImportError:
        return None
    span = trace.get_current_span()
    ctx = span.get_span_context()
    if not ctx or not ctx.is_valid:
        return None
    # OTel trace_id is a 128-bit int; App Insights wants lowercase 32-char hex.
    return f"{ctx.trace_id:032x}"


def build_appinsights_url(operation_id: Optional[str]) -> Optional[str]:
    """Construct an Azure portal deep link to the AI transaction search view.

    Returns None if either:
        - operation_id is falsy
        - APPINSIGHTS_APPLICATION_ID env var is unset

    The URL targets the portal's Transaction Search blade scoped to a single
    operation_id, which is the most useful landing view for an operator
    investigating a chain run (one row per dependency / request).
    """
    if not operation_id:
        return None
    app_id = os.getenv("APPINSIGHTS_APPLICATION_ID")
    if not app_id:
        return None
    # Standard portal deep-link to the Transaction Search blade. Anchored
    # by operation_Id eq <id>.
    return (
        "https://portal.azure.com/#blade/AppInsightsExtension/"
        f"BladeRedirect/BladeName/searchV1/ResourceId/"
        f"%2Fsubscriptions%2F-%2FresourceGroups%2F-%2Fproviders%2F"
        f"microsoft.insights%2Fcomponents%2F{app_id}"
        f"/Query/operation_Id%20%3D%3D%20%22{operation_id}%22"
    )


def build_langfuse_url(trace_id: Optional[str]) -> Optional[str]:
    """Construct a Langfuse trace viewer URL.

    Returns None until trace_id is real (S83). Today the audit event passes
    "" so callers always see None — builder still lives here so S83 only
    needs to fix the call site, not introduce a new module.
    """
    if not trace_id:
        return None
    host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com").rstrip("/")
    project_id = os.getenv("LANGFUSE_PROJECT_ID")
    if project_id:
        return f"{host}/project/{project_id}/traces/{trace_id}"
    return f"{host}/trace/{trace_id}"
