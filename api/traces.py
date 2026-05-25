"""API route for fetching recent traces.

Session 38 — Track A OpenAPI sweep, per-router #16.
One JSON-returning endpoint gets a strict outer envelope (TracesResponse)
with a per-item model (TraceItemOut) that carries ConfigDict(extra="allow")
on its eval_scores sub-model. The eval_scores dict is keyed on live metric
names (e.g. "coherence", "groundedness") whose set is not fixed at
import time — this is the asymmetric/polymorphic exception carved out by
compound 27a. The outer envelope and every non-eval_scores field are strict.
The route earns a stable SDK method name via the operation_id convention
traces_<verb>[_<noun>] without re-exporting response_model or operation_id
prose from this docstring.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from api.evaluate import runs_cache, eval_cache
from evaluator import evaluate_response
from tracer import get_recent_traces

router = APIRouter(prefix="/api", tags=["traces"])


# ===========================================================================
# Response models (Session 38 — Track A OpenAPI sweep, per-router #16)
# ===========================================================================


class EvalScoreEntry(BaseModel):
    """One metric result inside eval_scores.

    Keys beyond score/passed/details are permitted via extra="allow" because
    some evaluators attach supplemental fields (e.g. "details", "rationale").
    """

    score: Optional[float] = None
    passed: Optional[bool] = None
    details: str = ""

    model_config = ConfigDict(extra="allow")


class TraceItemOut(BaseModel):
    """Single trace record as returned in the recent-traces list.

    eval_scores is typed as a dict keyed on metric name (e.g. "coherence")
    because the set of active metrics is runtime-configured and not fixed at
    schema definition time — per compound 27a asymmetric/polymorphic carve-out.
    When a trace has not been evaluated the field is None.
    """

    id: str
    model: str
    prompt_preview: str
    response_preview: str
    latency_ms: int
    tokens_used: int
    timestamp: str
    eval_scores: Optional[dict[str, EvalScoreEntry]] = None

    model_config = ConfigDict(extra="allow")


class TracesResponse(BaseModel):
    """Envelope for GET /traces."""

    traces: list[TraceItemOut]
    error: Optional[str] = None


# ===========================================================================
# Routes
# ===========================================================================


@router.get(
    "/traces",
    response_model=TracesResponse,
    operation_id="traces_list_get",
)
async def fetch_traces() -> dict:
    """Fetch recent traces from cache with eval scores.

    Returns up to 20 of the most recently recorded runs. Each item carries
    a prompt/response preview (first 100 chars), timing and token metadata,
    and the eval_scores dict when the trace has been evaluated.
    """
    try:
        traces = runs_cache[:20]
        return {"traces": traces, "error": None}

    except Exception as e:
        return {
            "traces": [],
            "error": str(e),
        }
