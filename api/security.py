"""Security testing API — adversarial probes and guardrails."""

import os
import time
from pathlib import Path
from fastapi import APIRouter, Query
from pydantic import BaseModel
from dotenv import load_dotenv

from adversarial import (
    run_adversarial_suite,
    get_available_categories,
    get_probes_for_category,
    ADVERSARIAL_PROBES,
)
from guardrails import (
    apply_guardrails,
    filter_output,
    get_rail_summary,
)
from storage import save_adversarial_result, get_adversarial_results

# Load env vars
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=str(env_path))

router = APIRouter(prefix="/api/security", tags=["security"])


class GuardrailCheckRequest(BaseModel):
    """Request to check input/output via guardrails."""
    text: str
    domain: str | None = None
    direction: str = "input"  # input or output


@router.get("/adversarial/categories")
async def get_categories() -> dict:
    """Get available adversarial test categories."""
    categories = get_available_categories()
    return {
        "categories": [
            {
                "name": cat,
                "probe_count": len(get_probes_for_category(cat)),
                "probes": [p["name"] for p in get_probes_for_category(cat)],
            }
            for cat in categories
        ],
        "total_probes": sum(len(ADVERSARIAL_PROBES[c]) for c in categories),
    }


@router.post("/adversarial/run")
async def run_adversarial(
    model: str = Query("claude-sonnet-4-6"),
    provider: str = Query("anthropic"),
    categories: str = Query(None),
) -> dict:
    """
    Run adversarial test suite against a model.

    Args:
        model: Model name (e.g., 'claude-sonnet-4-6', 'gpt-4o-mini')
        provider: 'anthropic' or 'openai'
        categories: Comma-separated list (None = all)
    """
    # Validate keys
    if provider == "anthropic" and not os.getenv("ANTHROPIC_API_KEY"):
        return {"error": "ANTHROPIC_API_KEY not configured"}
    if provider == "openai" and not os.getenv("OPENAI_API_KEY"):
        return {"error": "OPENAI_API_KEY not configured"}

    cat_list = categories.split(",") if categories else None

    results = run_adversarial_suite(
        model_provider=provider,
        model_name=model,
        categories=cat_list,
    )

    # Persist
    save_adversarial_result(results)

    return results


@router.get("/adversarial/history")
async def adversarial_history(limit: int = Query(50, ge=1, le=200)) -> dict:
    """Get historical adversarial test results."""
    return {"results": get_adversarial_results(limit=limit)}


@router.get("/guardrails/summary")
async def guardrails_summary() -> dict:
    """Get summary of available guardrail rules."""
    return get_rail_summary()


@router.post("/guardrails/check")
async def check_guardrails(request: GuardrailCheckRequest) -> dict:
    """Check text against guardrails."""
    if request.direction == "input":
        result = apply_guardrails(request.text, domain=request.domain)
    else:
        result = filter_output(request.text, domain=request.domain)

    return result
