"""Analytics API — trends, charts, aggregated metrics."""

from datetime import datetime, timedelta
from fastapi import APIRouter, Query
from storage import calculate_analytics, get_runs, export_runs_csv, export_runs_json
from fastapi.responses import Response, PlainTextResponse

router = APIRouter(prefix="/api", tags=["analytics"])


@router.get("/analytics")
async def get_analytics(days: int = Query(30, ge=1, le=365)) -> dict:
    """Get analytics for recent period."""
    return calculate_analytics(days=days)


@router.get("/analytics/by-domain")
async def analytics_by_domain(days: int = Query(30, ge=1, le=365)) -> dict:
    """Get analytics grouped by domain."""
    analytics = calculate_analytics(days=days)
    return {
        "period_days": days,
        "by_domain": analytics["by_domain"],
        "total_runs": analytics["total_runs"],
    }


@router.get("/analytics/trends")
async def get_trends(days: int = Query(30, ge=1, le=365)) -> dict:
    """Get daily trends for the period."""
    analytics = calculate_analytics(days=days)
    return {
        "period_days": days,
        "trends": analytics["trends"],
        "pass_rate": analytics["pass_rate"],
    }


@router.get("/export/csv")
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


@router.get("/export/json")
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
