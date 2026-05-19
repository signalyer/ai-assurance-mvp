"""API route for fetching recent traces."""

from fastapi import APIRouter, HTTPException
from typing import Optional
from tracer import get_recent_traces
from evaluator import evaluate_response
from api.evaluate import runs_cache, eval_cache

router = APIRouter(prefix="/api", tags=["traces"])


@router.get("/traces")
async def fetch_traces():
    """
    Fetch recent traces from cache with eval scores.

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
        # Return cached runs (populated by demo endpoint)
        traces = runs_cache[:20]  # Return up to 20 most recent

        return {"traces": traces, "error": None}

    except Exception as e:
        error_msg = str(e)
        return {
            "traces": [],
            "error": error_msg,
        }
