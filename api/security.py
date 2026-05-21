"""Security testing API — adversarial probes and guardrails.

Session 05: guardrail integration updated. apply_guardrails and filter_output now delegate
to middleware.injection (detect_injection) and guardrails.llama_guard_adapter
(evaluate_content). Public function signatures preserved for backward compatibility.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel
from dotenv import load_dotenv

from adversarial import (
    run_adversarial_suite,
    get_available_categories,
    get_probes_for_category,
    ADVERSARIAL_PROBES,
)
from middleware.injection import detect_injection
from guardrails.llama_guard_adapter import evaluate_content
from storage import save_adversarial_result, get_adversarial_results

logger = logging.getLogger(__name__)

# Load env vars
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=str(env_path))

router = APIRouter(prefix="/api/security", tags=["security"])


class GuardrailCheckRequest(BaseModel):
    """Request to check input/output via guardrails."""

    text: str
    domain: Optional[str] = None
    direction: str = "input"  # input or output


def apply_guardrails(prompt: str, domain: Optional[str] = None) -> dict:
    """Apply input guardrails. Use BEFORE sending to model.

    Delegates to middleware.injection.detect_injection. Signature preserved for
    backward compatibility with all call sites.

    Args:
        prompt: The user prompt to check.
        domain: Optional domain context (retained for interface compat; not used by
                the new injection detector which is domain-agnostic at this layer).

    Returns:
        {"allowed": bool, "reason": str, "violation": dict | None, "prompt": str}
    """
    start = time.monotonic()
    logger.info(
        "apply_guardrails entry",
        extra={"prompt_length": len(prompt), "domain": domain},
    )

    result = detect_injection(prompt)

    duration_ms = int((time.monotonic() - start) * 1000)

    if result.is_injection:
        violation = {
            "category": result.attack_type.value,
            "pattern": result.metadata.get("pattern_matched", ""),
            "severity": "CRITICAL" if result.confidence >= 0.8 else "HIGH",
            "message": result.reason,
            "blocked": True,
        }
        logger.warning(
            "apply_guardrails blocked injection",
            extra={
                "attack_type": result.attack_type.value,
                "confidence": result.confidence,
                "duration_ms": duration_ms,
            },
        )
        return {
            "allowed": False,
            "reason": result.reason,
            "violation": violation,
            "prompt": prompt,
        }

    logger.info(
        "apply_guardrails allowed",
        extra={"duration_ms": duration_ms},
    )
    return {
        "allowed": True,
        "reason": "Prompt passed all input rails",
        "violation": None,
        "prompt": prompt,
    }


def filter_output(
    response: str,
    domain: Optional[str] = None,
    auto_redact: bool = True,
) -> dict:
    """Filter model output. Use AFTER receiving response from model.

    Delegates to guardrails.llama_guard_adapter.evaluate_content. Signature and
    return shape preserved for backward compatibility with all call sites.

    Args:
        response: Model response text.
        domain: Optional domain context (retained for interface compat).
        auto_redact: Retained for interface compat; the new safety evaluator does
                     not perform regex redaction — PII redaction is handled upstream
                     by the scrubber (scrubber.tokenise_payload).

    Returns:
        {
            "safe": bool,
            "response": str,
            "original": str,
            "violations": list[str],
            "redacted": bool,
            "violation_count": int,
            "score": float,
        }
    """
    start = time.monotonic()
    logger.info(
        "filter_output entry",
        extra={"response_length": len(response), "domain": domain},
    )

    llama_result = evaluate_content(response)

    violations_str: list[str] = [v.value for v in llama_result.violations]
    duration_ms = int((time.monotonic() - start) * 1000)

    logger.info(
        "filter_output exit",
        extra={
            "safe": llama_result.safe,
            "violation_count": len(violations_str),
            "score": llama_result.score,
            "duration_ms": duration_ms,
        },
    )

    return {
        "safe": llama_result.safe,
        "response": response,
        "original": response,
        "violations": violations_str,
        "redacted": False,          # Redaction is scrubber's responsibility, not guardrails
        "violation_count": len(violations_str),
        "score": llama_result.score,
    }


def get_rail_summary() -> dict:
    """Get summary of active guardrail capabilities.

    Returns a summary aligned with the new Session 03 guardrail stack rather than
    the legacy regex pattern counts.
    """
    from guardrails.llama_guard_adapter import LlamaGuardEvaluator, UnsafeCategory

    unsafe_categories = [c.value for c in UnsafeCategory]

    return {
        "guardrail_version": "session-03",
        "input_rails": {
            "injection_detection": "active",
            "attack_types": [
                "jailbreak",
                "prompt_override",
                "context_escape",
                "preamble_injection",
            ],
        },
        "output_rails": {
            "content_safety": "active",
            "unsafe_categories": unsafe_categories,
        },
        "total_input_patterns": 4,          # Four attack type categories
        "total_output_categories": len(unsafe_categories),
        "domain_rules": "topic-enforcement-via-nemo",
    }


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
    """Run adversarial test suite against a model.

    Args:
        model: Model name (e.g., 'claude-sonnet-4-6', 'gpt-4o-mini')
        provider: 'anthropic' or 'openai'
        categories: Comma-separated list (None = all)
    """
    start = time.monotonic()
    logger.info(
        "run_adversarial entry",
        extra={"model": model, "provider": provider, "categories": categories},
    )

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

    duration_ms = int((time.monotonic() - start) * 1000)
    logger.info("run_adversarial exit", extra={"duration_ms": duration_ms})

    return results


@router.get("/adversarial/history")
async def adversarial_history(limit: int = Query(50, ge=1, le=200)) -> dict:
    """Get historical adversarial test results."""
    return {"results": get_adversarial_results(limit=limit)}


@router.get("/guardrails/summary")
async def guardrails_summary() -> dict:
    """Get summary of active guardrail capabilities."""
    return get_rail_summary()


@router.post("/guardrails/check")
async def check_guardrails(request: GuardrailCheckRequest) -> dict:
    """Check text against guardrails."""
    if request.direction == "input":
        result = apply_guardrails(request.text, domain=request.domain)
    else:
        result = filter_output(request.text, domain=request.domain)

    return result
