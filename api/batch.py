"""Batch evaluation — run multiple test cases at once.

PERFORMANCE: All LLM calls are dispatched in parallel via asyncio.gather.
For N prompts × M models, total time ≈ max(call_latency) instead of N×M×latency.

Session 05: guardrail integration updated. filter_output now delegates to
guardrails.llama_guard_adapter.evaluate_content. Signature preserved for
backward compatibility.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
import uuid
import json
from pathlib import Path
from typing import Optional

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from dotenv import load_dotenv
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from api._models import GovernanceMetadata

from tracer import trace_call
from evaluator import evaluate_response
from api.evaluate import _normalize_eval_scores, eval_cache, runs_cache
from storage import save_run, save_batch, get_batches
from audit import log_evaluation
from guardrails.llama_guard_adapter import evaluate_content
from scrubber import tokenise_payload

logger = logging.getLogger(__name__)

env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=str(env_path))

router = APIRouter(prefix="/api/batch", tags=["batch"])

DOMAINS_DIR = Path(__file__).parent.parent / "domains"

# Reuse async clients across calls (warm connection pool)
_anthropic_client: Optional[AsyncAnthropic] = None
_openai_client: Optional[AsyncOpenAI] = None


def _get_anthropic_client() -> AsyncAnthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return _anthropic_client


def _get_openai_client() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _openai_client


class BatchPrompt(BaseModel):
    """A single prompt in a batch."""

    name: str
    prompt: str
    context: list[str] | None = None
    expected_behavior: str | None = None


class BatchRequest(BaseModel):
    """Batch evaluation request."""

    name: str | None = None
    prompts: list[BatchPrompt]
    models: list[str] = ["claude-sonnet-4-6", "gpt-4o-mini"]


def _provider_for_model(model: str) -> str:
    """Determine provider from model name."""
    if model.startswith("claude"):
        return "anthropic"
    elif model.startswith("gpt") or model.startswith("o1") or model.startswith("o3"):
        return "openai"
    return "anthropic"


def filter_output(
    response: str,
    domain: Optional[str] = None,
    auto_redact: bool = True,
) -> dict:
    """Filter model output via Llama Guard 3 content safety evaluation.

    Backward-compatible wrapper around guardrails.llama_guard_adapter.evaluate_content.
    The return shape is a superset of the legacy filter_output shape so all existing
    callers continue to work without modification.

    Args:
        response: Model response text.
        domain: Optional domain context (retained for interface compat).
        auto_redact: Retained for interface compat; PII redaction is the scrubber's
                     responsibility, not the guardrails layer.

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
    logger.info("filter_output entry", extra={"response_length": len(response)})

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
        "redacted": False,
        "violation_count": len(violations_str),
        "score": llama_result.score,
    }


async def _call_model_async(
    provider: str, model: str, prompt: str, max_tokens: int = 500
) -> tuple[str, int, int]:
    """Async model invocation — all calls are parallelizable."""
    start = time.time()
    if provider == "anthropic":
        client = _get_anthropic_client()
        message = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        response = message.content[0].text
        tokens = message.usage.input_tokens + message.usage.output_tokens
    else:
        client = _get_openai_client()
        completion = await client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        response = completion.choices[0].message.content
        tokens = completion.usage.prompt_tokens + completion.usage.completion_tokens

    latency = int((time.time() - start) * 1000)
    return response, latency, tokens


async def _run_single(
    test_case: BatchPrompt,
    model: str,
    batch_id: str,
    batch_name: str,
) -> dict:
    """Run one (test_case, model) pair end-to-end.

    Multiple of these can run concurrently via asyncio.gather.
    """
    provider = _provider_for_model(model)
    try:
        # Model call (async)
        response, latency, tokens = await _call_model_async(provider, model, test_case.prompt)

        # Scrub prompt and response BEFORE tracing — raw PII must never reach Langfuse.
        scrubbed_prompt, vault_id = tokenise_payload(
            test_case.prompt, scope=f"batch-prompt-{model}-{batch_id}"
        )
        if not vault_id:
            import hashlib
            scrubbed_prompt = test_case.prompt
            vault_id = f"batch-nopii_{hashlib.sha256(test_case.prompt.encode()).hexdigest()[:12]}"

        scrubbed_response, response_vault_id = tokenise_payload(
            response, scope=f"batch-resp-{model}-{batch_id}"
        )
        if not response_vault_id:
            scrubbed_response = response
            response_vault_id = ""

        # Tracing and evaluation are CPU/blocking — run in thread pool to not block event loop
        loop = asyncio.get_event_loop()

        trace_id = await loop.run_in_executor(
            None,
            lambda: trace_call(
                model=model,
                prompt=scrubbed_prompt,
                response=scrubbed_response,
                latency_ms=latency,
                tokens_used=tokens,
                metadata={
                    "batch_id": batch_id,
                    "test_case": test_case.name,
                    "vault_id": vault_id,
                    "response_vault_id": response_vault_id,
                },
            ),
        )

        raw_evals = await loop.run_in_executor(
            None,
            lambda: evaluate_response(
                input_prompt=scrubbed_prompt,
                actual_output=scrubbed_response,
                context=test_case.context or [],
            ),
        )
        eval_scores = _normalize_eval_scores(raw_evals)
        eval_cache[trace_id] = eval_scores

        guardrail_result = filter_output(response)

        run_data = {
            "id": trace_id,
            "batch_id": batch_id,
            "test_case": test_case.name,
            "model": model,
            "trace_id": trace_id,
            "domain": batch_name,
            "prompt": scrubbed_prompt,
            "prompt_preview": scrubbed_prompt[:100],
            "response": scrubbed_response,
            "response_preview": scrubbed_response[:100],
            "vault_id": vault_id,
            "response_vault_id": response_vault_id,
            "latency_ms": latency,
            "tokens_used": tokens,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "eval_scores": eval_scores,
            "guardrails": guardrail_result,
        }
        runs_cache.insert(0, run_data)
        save_run(run_data)
        log_evaluation(
            model=model,
            domain=batch_name,
            trace_id=trace_id,
            eval_scores=eval_scores,
        )
        return run_data

    except Exception as e:
        return {
            "test_case": test_case.name,
            "model": model,
            "error": str(e)[:200],
        }


# ---------------------------------------------------------------------------
# Response models (Session 13 typing pass)
#
# NOTE: run_batch was tagged JobResponse in audit doc §3.2; on review it's
# fully synchronous (asyncio.gather completes inline before return). Typed
# as BatchResultOut (synchronous result envelope) -- audit doc correction.
# ---------------------------------------------------------------------------


class BatchRunResultOut(BaseModel):
    """One (test_case, model) run result.

    Loosely typed -- the original V1 UI introspects many sub-fields
    (eval_scores per-metric, guardrails sub-dict) that vary by config.
    Phase 1.5 can tighten if V2 SPA needs strict types.
    """
    model_config = ConfigDict(extra="allow")


class BatchResultOut(BaseModel):
    """Synchronous result of /api/batch/run or /api/batch/run-domain/{id}.

    Returned 200 even on partial errors -- individual runs surface their
    error in the per-run dict (BatchRunResultOut). The top-level `error`
    field is set ONLY when the entire batch couldn't start (e.g. no prompts).
    Preserves V1 batch.html contract.
    """
    model_config = ConfigDict(extra="forbid")

    batch_id: str | None = None
    name: str | None = None
    total_runs: int | None = None
    success_count: int | None = None
    error_count: int | None = None
    pass_count: int | None = None
    duration_ms: int | None = None
    results: list[BatchRunResultOut] | None = None
    error: str | None = Field(
        default=None,
        description="Top-level error -- batch did not run. None on success.",
    )
    governance: GovernanceMetadata | None = None


class BatchHistoryRowOut(BaseModel):
    """One row in the batch history list."""
    model_config = ConfigDict(extra="forbid")

    batch_id: str
    name: str
    total_runs: int
    pass_count: int
    fail_count: int
    duration_ms: int
    timestamp: str


class BatchHistoryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    batches: list[BatchHistoryRowOut]


@router.post(
    "/run",
    response_model=BatchResultOut,
    operation_id="batch_run",
)
async def run_batch(request: BatchRequest) -> BatchResultOut:
    """Run a batch evaluation — all model calls dispatched in parallel."""
    if not request.prompts:
        return BatchResultOut(error="No prompts provided")

    batch_id = str(uuid.uuid4())[:8]
    batch_name = request.name or f"Batch {batch_id}"
    start_time = time.time()

    # Build all (test_case, model) tasks upfront
    tasks = [
        _run_single(test_case, model, batch_id, batch_name)
        for test_case in request.prompts
        for model in request.models
    ]

    # Dispatch ALL in parallel — wall time becomes max(call_latency) instead of sum
    results = await asyncio.gather(*tasks, return_exceptions=False)

    total_time = int((time.time() - start_time) * 1000)

    # Aggregate stats
    success_count = sum(1 for r in results if "error" not in r)
    fail_count = len(results) - success_count

    pass_count = 0
    for r in results:
        if "error" not in r:
            scores = r.get("eval_scores", {})
            if all(m.get("passed") is True or m.get("skipped", False) for m in scores.values()):
                pass_count += 1

    save_batch({
        "batch_id": batch_id,
        "name": batch_name,
        "total_runs": len(results),
        "pass_count": pass_count,
        "fail_count": fail_count,
        "duration_ms": total_time,
    })

    return BatchResultOut(
        batch_id=batch_id,
        name=batch_name,
        total_runs=len(results),
        success_count=success_count,
        error_count=fail_count,
        pass_count=pass_count,
        duration_ms=total_time,
        results=[BatchRunResultOut(**r) for r in results],
    )


_DOMAIN_ID_RE = re.compile(r"^[a-zA-Z0-9_\-]{1,64}$")


@router.post(
    "/run-domain/{domain_id}",
    response_model=BatchResultOut,
    operation_id="batch_run_domain",
)
async def run_domain_test_suite(domain_id: str) -> BatchResultOut:
    """Run all test cases for a specific domain."""
    if not _DOMAIN_ID_RE.match(domain_id):
        raise HTTPException(status_code=400, detail="Invalid domain_id — must be 1-64 alphanumeric/underscore/hyphen characters")
    file_path = DOMAINS_DIR / f"{domain_id}.json"
    if not file_path.exists():
        return BatchResultOut(error=f"Domain '{domain_id}' not found")

    with open(file_path) as f:
        domain = json.load(f)

    test_cases = domain.get("test_cases", [])
    if not test_cases:
        # Fall back to single prompt
        if domain.get("prompt"):
            test_cases = [{"name": "default", "prompt": domain["prompt"]}]
        else:
            return BatchResultOut(error="No test cases or prompt defined in domain")

    context = domain.get("regulatory_context") or domain.get("context") or []

    prompts = [
        BatchPrompt(
            name=tc.get("name", f"Test {i+1}"),
            prompt=tc["prompt"],
            context=context,
        )
        for i, tc in enumerate(test_cases)
    ]

    request = BatchRequest(
        name=f"{domain['name']} — Full Suite",
        prompts=prompts,
    )

    return await run_batch(request)


@router.get(
    "/history",
    response_model=BatchHistoryOut,
    operation_id="batch_history",
)
async def batch_history(limit: int = Query(50, ge=1, le=200)) -> BatchHistoryOut:
    """Get batch run history."""
    return BatchHistoryOut(
        batches=[BatchHistoryRowOut(**b) for b in get_batches(limit=limit)],
    )
