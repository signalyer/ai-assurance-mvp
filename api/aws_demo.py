"""AWS Analyzer Demo — endpoints serving the walkthrough payload.

Session 39 — Track A OpenAPI sweep, per-router #19.

Routes and their SDK contracts:

``aws_demo_get_full`` (GET /api/aws-demo)
    Returns the complete walkthrough payload as a permissive model.
    ``get_full_demo()`` returns a dict whose top-level keys each hold entirely
    different nested structures (intake, risk classification, mermaid diagram,
    final HTML, etc.) — no fixed uniform shape exists.  ``extra="allow"`` lets
    the heterogeneous payload flow through without schema rejection; mirrors the
    compound-27a treatment used for AnalyticsResponse (Session 27) and
    DemoRunResponse (Session 38).

``aws_demo_get_step`` (GET /api/aws-demo/step/{step_key})
    Returns a two-key dict (``step`` and ``data``) where ``data`` is one
    arbitrary slice of the full payload — value type varies completely by key.
    Permissive model for the same compound-27a reason as above.

``aws_demo_get_document`` (GET /api/aws-demo/document)
    Returns an ``HTMLResponse`` (non-JSON Response subclass).  Per compound-26a
    this route carries a stable SDK operation name only; no ``response_model``
    is possible on a ``response_class=HTMLResponse`` route.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict

from domain import aws_demo_flow as flow


router = APIRouter(prefix="/api/aws-demo", tags=["aws-demo"])


class AwsDemoFullResponse(BaseModel):
    """Full walkthrough payload.

    Permissive: top-level keys each hold entirely different nested structures
    (intake metadata, risk classification tables, mermaid diagrams, raw HTML,
    etc.).  A closed schema would reject valid payload — extra="allow" is the
    correct compound-27a choice for heterogeneous / asymmetric top-level dicts.
    """

    model_config = ConfigDict(extra="allow")


class AwsDemoStepResponse(BaseModel):
    """Single step slice of the walkthrough payload.

    ``data`` is typed ``Any`` because each step key returns a completely
    different structure (dict, list, str, int) — a union type would provide
    false precision on a truly open-ended shape.
    """

    step: str
    data: Any

    model_config = ConfigDict(extra="allow")


@router.get("", response_model=AwsDemoFullResponse, operation_id="aws_demo_get_full")
async def get_full() -> AwsDemoFullResponse:
    """Return the full deterministic AWS Analyzer demo payload."""
    return AwsDemoFullResponse(**flow.get_full_demo())


@router.get(
    "/step/{step_key}",
    response_model=AwsDemoStepResponse,
    operation_id="aws_demo_get_step",
)
async def get_step(step_key: str) -> AwsDemoStepResponse:
    """Return a single step slice of the demo payload by key."""
    full = flow.get_full_demo()
    return AwsDemoStepResponse(step=step_key, data=full.get(step_key))


@router.get("/document", response_class=HTMLResponse, operation_id="aws_demo_get_document")
async def get_final_document() -> HTMLResponse:
    """Return the final assembled document as rendered HTML."""
    full = flow.get_full_demo()
    return HTMLResponse(content=full["final_document_html"])
