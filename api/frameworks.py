"""Framework Coverage Matrix API — Session 06.

Endpoints:
    GET  /api/frameworks/matrix
    GET  /api/frameworks/{framework_slug}
    GET  /api/frameworks/{framework_slug}/system/{system_id}
    POST /api/frameworks/{framework_slug}/export
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

from domain.framework_coverage import (
    FrameworkItem,
    ItemCoverage,
    framework_matrix,
    framework_overview,
    framework_catalog,
    item_coverage,
    framework_display_name,
    _FRAMEWORK_SLUG_TO_CATALOG_KEY,
)
from domain import repository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/frameworks", tags=["frameworks"])

# ---------------------------------------------------------------------------
# Slug → catalog key normalisation
# Finding #12: removed duplicate _SLUG_TO_CATALOG; use _FRAMEWORK_SLUG_TO_CATALOG_KEY
# from domain directly.  _PDF_NOT_YET and _LIVE_CATALOG_SLUGS derived from it.
# ---------------------------------------------------------------------------

# Frameworks planned for Session 11 — return 501 for PDF export only
_PDF_NOT_YET: set[str] = {"iso-42001", "sr-11-7", "ffiec"}

# Frameworks that have a live catalog (all keys in the domain mapping)
_LIVE_CATALOG_SLUGS: set[str] = set(_FRAMEWORK_SLUG_TO_CATALOG_KEY.keys())


def _resolve_catalog_key(slug: str) -> str:
    """Map a URL slug to a catalog key, raising 404 if unknown."""
    key = _FRAMEWORK_SLUG_TO_CATALOG_KEY.get(slug)
    if key is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown framework slug '{slug}'. "
                   f"Supported: {sorted(_FRAMEWORK_SLUG_TO_CATALOG_KEY.keys())}.",
        )
    return key


def _evidence_hash(evidence_id: str, summary: str, collected_at: str) -> str:
    """Compute a deterministic SHA-256 hash from evidence content fields."""
    raw = f"{evidence_id}|{summary}|{collected_at}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class MatrixCellOut(BaseModel):
    """Coverage cell for one system × one framework."""
    framework_slug: str
    coverage_pct: float


class MatrixRowOut(BaseModel):
    """One row in the coverage matrix."""
    system_id: str
    system_name: str
    cells: dict[str, float]


class MatrixOut(BaseModel):
    """Full portfolio matrix response."""
    frameworks: list[dict[str, str]]
    rows: list[MatrixRowOut]


class ControlRollupOut(BaseModel):
    control_id: str
    title: str
    priority: str
    domain: str
    status: str
    open_findings: int


class FindingSummaryOut(BaseModel):
    id: str
    system_id: str
    title: str
    severity: str
    status: str
    control_id: str | None


class ItemCoverageOut(BaseModel):
    item_id: str
    framework: str
    display_name: str
    description: str
    recommended_owner: str
    coverage_pct: float
    evidence_completeness: float
    controls: list[ControlRollupOut]
    findings: list[FindingSummaryOut]
    release_gates_affected: list[str]
    recommended_remediation: list[str]


class FrameworkOverviewOut(BaseModel):
    framework_slug: str
    display_name: str
    items: list[ItemCoverageOut]


class EvidenceOut(BaseModel):
    id: str
    summary: str
    evidence_hash: str
    collected_at: str
    source: str
    evidence_type: str


class DrillDownItemOut(BaseModel):
    id: str
    display_name: str
    coverage_pct: float
    controls: list[ControlRollupOut]
    findings: list[FindingSummaryOut]
    evidence: list[EvidenceOut]


class DrillDownOut(BaseModel):
    framework: str
    display_name: str
    system_id: str
    items: list[DrillDownItemOut]


class ExportRequest(BaseModel):
    system_id: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Finding #9: replace Any with concrete domain types
def _item_coverage_to_out(ic: ItemCoverage) -> ItemCoverageOut:
    """Convert an ItemCoverage domain object to the API response model."""
    return ItemCoverageOut(
        item_id=ic.item_id,
        framework=ic.framework,
        display_name=ic.display_name,
        description=ic.description,
        recommended_owner=ic.recommended_owner,
        coverage_pct=ic.coverage_pct,
        evidence_completeness=ic.evidence_completeness,
        controls=[
            ControlRollupOut(
                control_id=c.control_id, title=c.title,
                priority=c.priority, domain=c.domain,
                status=c.status, open_findings=c.open_findings,
            )
            for c in ic.mapped_controls
        ],
        findings=[
            FindingSummaryOut(
                id=f.id, system_id=f.system_id, title=f.title,
                severity=f.severity, status=f.status, control_id=f.control_id,
            )
            for f in ic.related_findings
        ],
        release_gates_affected=ic.release_gates_affected,
        recommended_remediation=ic.recommended_remediation,
    )


def _build_evidence_out(ev: object) -> EvidenceOut:
    """Convert a repository Evidence object to the API response model."""
    collected_str = ev.collected_at.isoformat() if hasattr(ev.collected_at, "isoformat") else str(ev.collected_at)  # type: ignore[attr-defined]
    return EvidenceOut(
        id=ev.id,  # type: ignore[attr-defined]
        summary=ev.summary,  # type: ignore[attr-defined]
        evidence_hash=_evidence_hash(ev.id, ev.summary, collected_str),  # type: ignore[attr-defined]
        collected_at=collected_str,
        source=ev.source,  # type: ignore[attr-defined]
        evidence_type=ev.evidence_type.value,  # type: ignore[attr-defined]
    )


def _evidence_for_controls(
    system_id: str,
    control_ids: set[str],
) -> list[EvidenceOut]:
    """Return evidence items linked to any of the given control IDs."""
    evidence = repository.evidence_for(system_id)
    out: list[EvidenceOut] = []
    for ev in evidence:
        if any(cid in control_ids for cid in (ev.linked_control_ids or [])):
            out.append(_build_evidence_out(ev))
    return out


# ---------------------------------------------------------------------------
# GET /api/frameworks/matrix
# ---------------------------------------------------------------------------

@router.get("/matrix", response_model=MatrixOut)
async def get_matrix(request: Request) -> MatrixOut:
    """Return portfolio-wide coverage matrix (all systems × 6 frameworks).

    Response shape: {frameworks: [{slug, display_name}], rows: [{system_id, system_name, cells}]}
    """
    start = datetime.now(tz=timezone.utc)
    logger.info("frameworks.matrix.enter")

    result = await asyncio.to_thread(framework_matrix)

    rows = [
        MatrixRowOut(
            system_id=row.system_id,
            system_name=row.system_name,
            cells=row.cells,
        )
        for row in result.rows
    ]

    elapsed_ms = (datetime.now(tz=timezone.utc) - start).total_seconds() * 1000
    logger.info(
        "frameworks.matrix.exit",
        extra={"rows": len(rows), "elapsed_ms": round(elapsed_ms, 1)},
    )
    return MatrixOut(frameworks=result.frameworks, rows=rows)


# ---------------------------------------------------------------------------
# GET /api/frameworks/{framework_slug}
# ---------------------------------------------------------------------------

@router.get("/{framework_slug}", response_model=FrameworkOverviewOut)
async def get_framework_overview(framework_slug: str) -> FrameworkOverviewOut:
    """Return framework catalog + portfolio-wide coverage for every item.

    Returns 404 for unknown framework_slug.
    """
    start = datetime.now(tz=timezone.utc)
    logger.info("frameworks.overview.enter", extra={"slug": framework_slug})

    catalog_key = _resolve_catalog_key(framework_slug)

    items_raw = await asyncio.to_thread(framework_overview, catalog_key)

    # Finding #16: use framework_display_name() instead of raw enum value
    display = framework_display_name(framework_slug)

    items_out = [_item_coverage_to_out(ic) for ic in items_raw]

    elapsed_ms = (datetime.now(tz=timezone.utc) - start).total_seconds() * 1000
    logger.info(
        "frameworks.overview.exit",
        extra={"slug": framework_slug, "items": len(items_out), "elapsed_ms": round(elapsed_ms, 1)},
    )
    return FrameworkOverviewOut(
        framework_slug=framework_slug,
        display_name=display,
        items=items_out,
    )


# ---------------------------------------------------------------------------
# GET /api/frameworks/{framework_slug}/system/{system_id}
# ---------------------------------------------------------------------------

@router.get("/{framework_slug}/system/{system_id}", response_model=DrillDownOut)
async def get_system_drill_down(framework_slug: str, system_id: str) -> DrillDownOut:
    """Per-item coverage for a single AI system within a framework.

    Each evidence item includes `evidence_hash` (SHA-256 computed from content).
    Returns 404 for unknown framework_slug or system_id.

    Finding #13: item_coverage and evidence calls are now gathered concurrently
    via asyncio.gather instead of sequential awaits in the loop.
    """
    start = datetime.now(tz=timezone.utc)
    logger.info(
        "frameworks.drilldown.enter",
        extra={"slug": framework_slug, "system_id": system_id},
    )

    catalog_key = _resolve_catalog_key(framework_slug)

    system, catalog = await asyncio.gather(
        asyncio.to_thread(repository.get_ai_system, system_id),
        asyncio.to_thread(framework_catalog, catalog_key),
    )
    if system is None:
        raise HTTPException(status_code=404, detail=f"AI system '{system_id}' not found.")

    # Finding #13: gather all item_coverage calls concurrently
    coverages: list[ItemCoverage] = list(
        await asyncio.gather(
            *[asyncio.to_thread(item_coverage, catalog_key, fw_item.id, system_id)
              for fw_item in catalog]
        )
    )

    # Gather all evidence lookups concurrently as well
    control_id_sets = [
        {c.control_id for c in ic.mapped_controls} for ic in coverages
    ]
    evidence_lists: list[list[EvidenceOut]] = list(
        await asyncio.gather(
            *[asyncio.to_thread(_evidence_for_controls, system_id, cids)
              for cids in control_id_sets]
        )
    )

    drill_items: list[DrillDownItemOut] = []
    for fw_item, ic, evidence in zip(catalog, coverages, evidence_lists):
        drill_items.append(DrillDownItemOut(
            id=fw_item.id,
            display_name=fw_item.display_name,
            coverage_pct=ic.coverage_pct,
            controls=[
                ControlRollupOut(
                    control_id=c.control_id, title=c.title,
                    priority=c.priority, domain=c.domain,
                    status=c.status, open_findings=c.open_findings,
                )
                for c in ic.mapped_controls
            ],
            findings=[
                FindingSummaryOut(
                    id=f.id, system_id=f.system_id, title=f.title,
                    severity=f.severity, status=f.status, control_id=f.control_id,
                )
                for f in ic.related_findings
            ],
            evidence=evidence,
        ))

    elapsed_ms = (datetime.now(tz=timezone.utc) - start).total_seconds() * 1000
    logger.info(
        "frameworks.drilldown.exit",
        extra={
            "slug": framework_slug, "system_id": system_id,
            "items": len(drill_items), "elapsed_ms": round(elapsed_ms, 1),
        },
    )
    return DrillDownOut(
        framework=catalog_key,
        display_name=framework_display_name(framework_slug),
        system_id=system_id,
        items=drill_items,
    )


# ---------------------------------------------------------------------------
# POST /api/frameworks/{framework_slug}/export
# ---------------------------------------------------------------------------

@router.post("/{framework_slug}/export")
async def export_framework_pdf(framework_slug: str, body: ExportRequest, request: Request) -> Response:
    """Generate a PDF Pack for the given framework and AI system.

    Returns 501 for frameworks planned for Session 11 (iso-42001, sr-11-7, ffiec).
    Returns 404 for unknown framework_slug or system_id.
    Returns application/pdf with the generated PDF bytes.

    Finding #2: Content-Disposition filename is sanitised to strip non-safe chars.
    """
    start = datetime.now(tz=timezone.utc)
    logger.info(
        "frameworks.export.enter",
        extra={"slug": framework_slug, "system_id": body.system_id},
    )

    # Check planned-but-not-yet frameworks first
    if framework_slug in _PDF_NOT_YET:
        raise HTTPException(
            status_code=501,
            detail=f"PDF Pack for {framework_slug} planned for Session 11.",
        )

    # Validate it's a known slug even if not PDF-not-yet
    if framework_slug not in _LIVE_CATALOG_SLUGS:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown framework slug '{framework_slug}'.",
        )

    # Validate system exists
    system = await asyncio.to_thread(repository.get_ai_system, body.system_id)
    if system is None:
        raise HTTPException(status_code=404, detail=f"AI system '{body.system_id}' not found.")

    # Resolve which PDF generator to call
    from pdf_report import generate_nist_pack, generate_owasp_pack, generate_eu_ai_act_pack

    _PACK_MAP: dict[str, Any] = {
        "nist-ai-rmf":   generate_nist_pack,
        "nist-ai-600-1": generate_nist_pack,
        "owasp-llm":     generate_owasp_pack,
        "owasp-agentic": generate_owasp_pack,
    }
    generator = _PACK_MAP.get(framework_slug)
    if generator is None:
        raise HTTPException(
            status_code=501,
            detail=f"PDF Pack for {framework_slug} planned for Session 11.",
        )

    pdf_bytes: bytes = await asyncio.to_thread(generator, body.system_id)

    elapsed_ms = (datetime.now(tz=timezone.utc) - start).total_seconds() * 1000
    logger.info(
        "frameworks.export.exit",
        extra={
            "slug": framework_slug, "system_id": body.system_id,
            "pdf_bytes": len(pdf_bytes), "elapsed_ms": round(elapsed_ms, 1),
        },
    )

    # Finding #2: sanitise system_id before interpolating into Content-Disposition header
    safe_sid = re.sub(r"[^a-zA-Z0-9_\-]", "_", body.system_id)
    filename = f"{framework_slug}-pack-{safe_sid}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
