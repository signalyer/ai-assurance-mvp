"""Batch evaluation — run multiple test cases at once."""

import os
import time
import uuid
import json
from pathlib import Path
from fastapi import APIRouter, Query
from pydantic import BaseModel
from dotenv import load_dotenv
from anthropic import Anthropic
from openai import OpenAI

from tracer import trace_call
from evaluator import evaluate_response
from api.evaluate import _normalize_eval_scores, eval_cache, runs_cache
from storage import save_run, save_batch, get_batches
from audit import log_evaluation
from guardrails import filter_output

env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=str(env_path))

router = APIRouter(prefix="/api/batch", tags=["batch"])

DOMAINS_DIR = Path(__file__).parent.parent / "domains"


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


def _call_model(provider: str, model: str, prompt: str, max_tokens: int = 500) -> tuple[str, int, int]:
    """Generic model invocation."""
    start = time.time()
    if provider == "anthropic":
        client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        message = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        response = message.content[0].text
        tokens = message.usage.input_tokens + message.usage.output_tokens
    else:
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        completion = client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        response = completion.choices[0].message.content
        tokens = completion.usage.prompt_tokens + completion.usage.completion_tokens

    latency = int((time.time() - start) * 1000)
    return response, latency, tokens


def _provider_for_model(model: str) -> str:
    """Determine provider from model name."""
    if model.startswith("claude"):
        return "anthropic"
    elif model.startswith("gpt") or model.startswith("o1") or model.startswith("o3"):
        return "openai"
    return "anthropic"


@router.post("/run")
async def run_batch(request: BatchRequest) -> dict:
    """Run a batch evaluation across multiple prompts and models."""
    if not request.prompts:
        return {"error": "No prompts provided"}

    batch_id = str(uuid.uuid4())[:8]
    batch_name = request.name or f"Batch {batch_id}"
    results = []
    start_time = time.time()

    for test_case in request.prompts:
        for model in request.models:
            provider = _provider_for_model(model)
            try:
                response, latency, tokens = _call_model(provider, model, test_case.prompt)

                # Trace
                trace_id = trace_call(
                    model=model,
                    prompt=test_case.prompt,
                    response=response,
                    latency_ms=latency,
                    tokens_used=tokens,
                    metadata={"batch_id": batch_id, "test_case": test_case.name},
                )

                # Evaluate
                raw_evals = evaluate_response(
                    input_prompt=test_case.prompt,
                    actual_output=response,
                    context=test_case.context or [],
                )
                eval_scores = _normalize_eval_scores(raw_evals)
                eval_cache[trace_id] = eval_scores

                # Guardrails
                guardrail_result = filter_output(response)

                run_data = {
                    "id": trace_id,
                    "batch_id": batch_id,
                    "test_case": test_case.name,
                    "model": model,
                    "trace_id": trace_id,
                    "domain": batch_name,
                    "prompt": test_case.prompt,
                    "prompt_preview": test_case.prompt[:100],
                    "response": response,
                    "response_preview": response[:100],
                    "latency_ms": latency,
                    "tokens_used": tokens,
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "eval_scores": eval_scores,
                    "guardrails": guardrail_result,
                }
                results.append(run_data)
                runs_cache.insert(0, run_data)
                save_run(run_data)
                log_evaluation(
                    model=model,
                    domain=batch_name,
                    trace_id=trace_id,
                    eval_scores=eval_scores,
                )

            except Exception as e:
                results.append({
                    "test_case": test_case.name,
                    "model": model,
                    "error": str(e)[:200],
                })

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

    batch_summary = {
        "batch_id": batch_id,
        "name": batch_name,
        "total_runs": len(results),
        "success_count": success_count,
        "error_count": fail_count,
        "pass_count": pass_count,
        "duration_ms": total_time,
        "results": results,
    }

    save_batch({
        "batch_id": batch_id,
        "name": batch_name,
        "total_runs": len(results),
        "pass_count": pass_count,
        "fail_count": fail_count,
        "duration_ms": total_time,
    })

    return batch_summary


@router.post("/run-domain/{domain_id}")
async def run_domain_test_suite(domain_id: str) -> dict:
    """Run all test cases for a specific domain."""
    file_path = DOMAINS_DIR / f"{domain_id}.json"
    if not file_path.exists():
        return {"error": f"Domain '{domain_id}' not found"}

    with open(file_path) as f:
        domain = json.load(f)

    test_cases = domain.get("test_cases", [])
    if not test_cases:
        # Fall back to single prompt
        if domain.get("prompt"):
            test_cases = [{"name": "default", "prompt": domain["prompt"]}]
        else:
            return {"error": "No test cases or prompt defined in domain"}

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


@router.get("/history")
async def batch_history(limit: int = Query(50, ge=1, le=200)) -> dict:
    """Get batch run history."""
    return {"batches": get_batches(limit=limit)}
