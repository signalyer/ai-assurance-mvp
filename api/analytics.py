"""Analytics API — trends, charts, aggregated metrics.

Session 27 — Track A OpenAPI sweep, per-router #3.
Three rollup endpoints get permissive Pydantic v2 response models
(ConfigDict(extra="allow")) so dynamic key/value aggregations
(by_domain, by_model, failure_types) flow through unchanged.
Two raw-export endpoints (CSV/JSON download) get operation_id only,
per compound rule 26a — Response subclass handlers skip response_model
but still earn a stable SDK method name in the OpenAPI document.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import Response, PlainTextResponse
from pydantic import BaseModel, ConfigDict

from storage import calculate_analytics, export_runs_csv, export_runs_json

router = APIRouter(prefix="/api", tags=["analytics"])


# ===========================================================================
# Response models (Session 27 — Track A OpenAPI sweep, per-router #3)
# ===========================================================================

class AnalyticsResponse(BaseModel):
    """Full analytics rollup.

    Permissive: empty-history path returns 8 keys, populated path returns 10.
    by_domain/by_model/failure_types are dynamic dicts keyed on real-world
    names (domain, model id, metric name) so they're typed as plain dicts.
    """
    total_runs: int
    by_domain: dict = {}
    by_model: dict = {}
    by_risk: dict = {}
    trends: list = []
    failure_types: dict = {}
    average_latency_ms: int = 0
    total_tokens: int = 0
    period_days: Optional[int] = None
    pass_rate: Optional[float] = None

    model_config = ConfigDict(extra="allow")


class AnalyticsByDomainResponse(BaseModel):
    """Domain-scoped subset of the analytics rollup."""
    period_days: int
    by_domain: dict
    total_runs: int

    model_config = ConfigDict(extra="allow")


class AnalyticsTrendsResponse(BaseModel):
    """Time-series subset of the analytics rollup."""
    period_days: int
    trends: list
    pass_rate: float

    model_config = ConfigDict(extra="allow")


# ===========================================================================
# Routes
# ===========================================================================

@router.get(
    "/analytics",
    response_model=AnalyticsResponse,
    operation_id="analytics_rollup_get",
)
async def get_analytics(days: int = Query(30, ge=1, le=365)) -> dict:
    """Get analytics for recent period."""
    return calculate_analytics(days=days)


@router.get(
    "/analytics/by-domain",
    response_model=AnalyticsByDomainResponse,
    operation_id="analytics_by_domain_get",
)
async def analytics_by_domain(days: int = Query(30, ge=1, le=365)) -> dict:
    """Get analytics grouped by domain."""
    analytics = calculate_analytics(days=days)
    return {
        "period_days": days,
        "by_domain": analytics["by_domain"],
        "total_runs": analytics["total_runs"],
    }


@router.get(
    "/analytics/trends",
    response_model=AnalyticsTrendsResponse,
    operation_id="analytics_trends_get",
)
async def get_trends(days: int = Query(30, ge=1, le=365)) -> dict:
    """Get daily trends for the period."""
    analytics = calculate_analytics(days=days)
    return {
        "period_days": days,
        "trends": analytics["trends"],
        "pass_rate": analytics["pass_rate"],
    }


@router.get(
    "/export/csv",
    operation_id="analytics_export_csv",
)
async def export_csv(
    domain: str = None,
    model: str = None,
    days: int = Query(30, ge=1, le=365),
) -> PlainTextResponse:
    """Export runs as CSV."""
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days)
    csv_data = export_runs_csv(
        domain=domain,
        model=model,
        start_date=start_date,
        end_date=end_date,
    )
    return PlainTextResponse(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=runs-{datetime.utcnow().strftime('%Y%m%d')}.csv"},
    )


@router.get(
    "/export/json",
    operation_id="analytics_export_json",
)
async def export_json(
    domain: str = None,
    model: str = None,
    days: int = Query(30, ge=1, le=365),
) -> Response:
    """Export runs as JSON."""
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days)
    json_data = export_runs_json(
        domain=domain,
        model=model,
        start_date=start_date,
        end_date=end_date,
    )
    return Response(
        content=json_data,
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename=runs-{datetime.utcnow().strftime('%Y%m%d')}.json"},
    )
