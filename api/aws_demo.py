"""AWS Analyzer Demo — endpoints serving the walkthrough payload."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from domain import aws_demo_flow as flow


router = APIRouter(prefix="/api/aws-demo", tags=["aws-demo"])


@router.get("")
async def get_full() -> dict:
    return flow.get_full_demo()


@router.get("/step/{step_key}")
async def get_step(step_key: str) -> dict:
    full = flow.get_full_demo()
    return {"step": step_key, "data": full.get(step_key)}


@router.get("/document", response_class=HTMLResponse)
async def get_final_document() -> HTMLResponse:
    full = flow.get_full_demo()
    return HTMLResponse(content=full["final_document_html"])
