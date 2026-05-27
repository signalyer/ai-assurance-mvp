"""F-017: read endpoint for persisted eval scores.

Reads data/evals.jsonl (written by evaluator.evaluate_response) and exposes
it via GET /api/v1/evals. Optional `trace_id` filter joins eval records to
trace records (data/traces.jsonl) produced by tracer.trace_call.

This is intentionally a thin reader — no auth, no pagination beyond limit,
no aggregation. The persistence story is the point of S56; the rich UI
panels can come later.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict

router = APIRouter(prefix="/api/v1", tags=["evals"])


_EVALS_JSONL = Path(
    os.environ.get("DATA_ROOT") or (Path(__file__).resolve().parent.parent / "data")
) / "evals.jsonl"


class EvalRecordOut(BaseModel):
    model_config = ConfigDict(extra="allow")
    trace_id: str = ""
    timestamp: str = ""
    workload_id: str = ""
    model: str = ""
    results: dict = {}


class EvalsListOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[EvalRecordOut]
    count: int
    source: str  # absolute path of evals.jsonl (operator transparency)


def _read_evals() -> list[dict]:
    if not _EVALS_JSONL.exists():
        return []
    out: list[dict] = []
    with open(_EVALS_JSONL, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    out.reverse()  # most recent first
    return out


@router.get("/evals", response_model=EvalsListOut, operation_id="evals_list")
def list_evals(
    trace_id: Optional[str] = Query(default=None),
    workload_id: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
) -> EvalsListOut:
    """List persisted eval records, most recent first.

    Filters apply in this order: trace_id (exact), workload_id (exact), then limit.
    """
    records = _read_evals()
    if trace_id:
        records = [r for r in records if r.get("trace_id") == trace_id]
    if workload_id:
        records = [r for r in records if r.get("workload_id") == workload_id]
    records = records[:limit]
    return EvalsListOut(
        items=[EvalRecordOut(**r) for r in records],
        count=len(records),
        source=str(_EVALS_JSONL),
    )
