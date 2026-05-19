"""API route for evaluating traces."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from tracer import get_recent_traces
from evaluator import evaluate_response

router = APIRouter(prefix="/api", tags=["evaluate"])

# In-memory cache for eval results (key: trace_id)
eval_cache: dict[str, dict] = {}

# In-memory cache for recent runs (populated by demo endpoint)
runs_cache: list[dict] = []


class EvaluateRequest(BaseModel):
    """Request to evaluate a trace."""
    trace_id: str


def _normalize_eval_scores(raw_results: dict) -> dict:
    """Convert evaluator results to API format."""
    normalized = {}
    for metric_name, result in raw_results.items():
        score = result.get("score")
        passed = result.get("passed")

        normalized[metric_name] = {
            "score": float(score) if score is not None else None,
            "passed": passed if isinstance(passed, bool) else None,
            "details": result.get("details", ""),
        }

    return normalized


@router.post("/evaluate")
async def evaluate_trace(request: EvaluateRequest):
    """
    Evaluate a trace by ID (or fetch and evaluate if not cached).

    Returns cached result if available.
    Returns eval_scores dict: metric_name -> {score, passed, details}
    """
    trace_id = request.trace_id

    # Check cache first
    if trace_id in eval_cache:
        return {
            "trace_id": trace_id,
            "eval_scores": eval_cache[trace_id],
            "cached": True,
            "error": None,
        }

    try:
        # Fetch trace details
        traces = get_recent_traces(limit=100)
        trace = None
        for t in traces:
            if t["id"] == trace_id:
                trace = t
                break

        if not trace:
            raise HTTPException(status_code=404, detail=f"Trace {trace_id} not found")

        # Extract prompt and response from trace metadata
        prompt = trace.get("prompt", "")
        response = trace.get("response", "")

        if not prompt or not response:
            raise HTTPException(
                status_code=400,
                detail="Trace missing prompt or response",
            )

        # Evaluate with context
        context = [
            "Financial advisors are prohibited from guaranteeing returns.",
            "Specific stock picks without disclaimer violate FINRA Rule 2210.",
            "Responsible advice includes risk disclosure.",
        ]

        raw_results = evaluate_response(
            input_prompt=prompt,
            actual_output=response,
            context=context,
        )

        # Normalize results
        eval_scores = _normalize_eval_scores(raw_results)

        # Cache the results
        eval_cache[trace_id] = eval_scores

        return {
            "trace_id": trace_id,
            "eval_scores": eval_scores,
            "cached": False,
            "error": None,
        }

    except HTTPException:
        raise
    except Exception as e:
        return {
            "trace_id": trace_id,
            "eval_scores": None,
            "cached": False,
            "error": str(e)[:200],
        }
