"""API route for fetching recent traces."""

from fastapi import APIRouter, HTTPException
from typing import Optional
from tracer import get_recent_traces
from evaluator import evaluate_response

router = APIRouter(prefix="/api", tags=["traces"])

# In-memory cache for eval results
eval_cache: dict[str, dict] = {}


@router.get("/traces")
async def fetch_traces():
    """
    Fetch recent traces from Langfuse with cached eval scores.

    Returns:
        {
          "traces": [
            {
              "id": str,
              "model": str,
              "prompt_preview": str (first 100 chars),
              "response_preview": str (first 100 chars),
              "latency_ms": int,
              "tokens_used": int,
              "timestamp": str (ISO8601),
              "eval_scores": { metric_name: {score, passed} } or null if not evaluated
            }
          ],
          "error": str (if any)
        }
    """
    try:
        traces = get_recent_traces(limit=20)

        # Add eval scores from cache if available
        for trace in traces:
            trace_id = trace["id"]
            if trace_id in eval_cache:
                trace["eval_scores"] = eval_cache[trace_id]
            else:
                trace["eval_scores"] = None

        return {"traces": traces, "error": None}

    except Exception as e:
        error_msg = str(e)
        if "LANGFUSE" in error_msg or "api" in error_msg.lower():
            error_msg = "Unable to connect to Langfuse — check your API keys"

        return {
            "traces": [],
            "error": error_msg,
        }
