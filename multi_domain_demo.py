"""Multi-domain demo runner — executes demo across all 5 domains."""

import os
import time
from pathlib import Path
from dotenv import load_dotenv
from anthropic import Anthropic
from openai import OpenAI

from tracer import trace_call
from evaluator import evaluate_response
from report import print_report
from domains import list_domains, load_domain

# Load env vars
env_path = Path(".env")
if env_path.exists():
    load_dotenv(dotenv_path=str(env_path))


def run_domain_demo(domain_name: str) -> dict:
    """
    Run demo for a single domain.

    Returns: {domain, models: [{model, trace_id, evals, latency, tokens, error}]}
    """
    try:
        domain = load_domain(domain_name)
    except Exception as e:
        return {
            "domain": domain_name,
            "error": f"Failed to load domain: {str(e)[:100]}",
            "models": [],
        }

    prompt = domain.prompt
    context = domain.context
    models = []

    # Call Claude
    try:
        start = time.time()
        client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        latency = int((time.time() - start) * 1000)
        response_text = message.content[0].text
        tokens = message.usage.input_tokens + message.usage.output_tokens

        # Trace and evaluate
        trace_id = trace_call(
            model="claude-sonnet-4-6",
            prompt=prompt,
            response=response_text,
            latency_ms=latency,
            tokens_used=tokens,
            metadata={"demo": True, "domain": domain.name},
        )

        evals = evaluate_response(
            input_prompt=prompt,
            actual_output=response_text,
            context=context,
        )

        models.append({
            "model": "claude-sonnet-4-6",
            "trace_id": trace_id,
            "evals": evals,
            "latency": latency,
            "tokens": tokens,
            "error": None,
        })

    except Exception as e:
        models.append({
            "model": "claude-sonnet-4-6",
            "trace_id": None,
            "evals": {},
            "latency": 0,
            "tokens": 0,
            "error": str(e)[:100],
        })

    # Call OpenAI
    try:
        start = time.time()
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        latency = int((time.time() - start) * 1000)
        response_text = response.choices[0].message.content
        tokens = response.usage.prompt_tokens + response.usage.completion_tokens

        # Trace and evaluate
        trace_id = trace_call(
            model="gpt-4o-mini",
            prompt=prompt,
            response=response_text,
            latency_ms=latency,
            tokens_used=tokens,
            metadata={"demo": True, "domain": domain.name},
        )

        evals = evaluate_response(
            input_prompt=prompt,
            actual_output=response_text,
            context=context,
        )

        models.append({
            "model": "gpt-4o-mini",
            "trace_id": trace_id,
            "evals": evals,
            "latency": latency,
            "tokens": tokens,
            "error": None,
        })

    except Exception as e:
        models.append({
            "model": "gpt-4o-mini",
            "trace_id": None,
            "evals": {},
            "latency": 0,
            "tokens": 0,
            "error": str(e)[:100],
        })

    return {
        "domain": domain.name,
        "error": None,
        "models": models,
    }


def run_all_domains() -> None:
    """Run demo across all domains."""
    print("\n" + "=" * 65)
    print("AI ASSURANCE PLATFORM — MULTI-DOMAIN DEMO")
    print("=" * 65)

    # Validate keys
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("\nERROR: ANTHROPIC_API_KEY not set")
        return
    if not os.getenv("OPENAI_API_KEY"):
        print("\nERROR: OPENAI_API_KEY not set")
        return

    domains = list_domains()
    if not domains:
        print("\nERROR: No domains found in domains/ directory")
        return

    print(f"\nFound {len(domains)} domains: {', '.join(domains)}")
    print("\n" + "=" * 65)

    results = []

    for i, domain_name in enumerate(domains, 1):
        print(f"\n[{i}/{len(domains)}] Running demo for {domain_name}...")
        result = run_domain_demo(domain_name)
        results.append(result)

        if result["error"]:
            print(f"✗ Error: {result['error']}")
        else:
            for model_result in result["models"]:
                if model_result["error"]:
                    print(f"  ✗ {model_result['model']}: {model_result['error']}")
                else:
                    print(f"  ✓ {model_result['model']}: {model_result['latency']}ms, {model_result['tokens']} tokens")

    # Print reports
    print("\n" + "=" * 65)
    print("RESULTS")
    print("=" * 65)

    for result in results:
        if result["error"]:
            print(f"\n{result['domain']}: ERROR")
            continue

        for model_result in result["models"]:
            if not model_result["error"] and model_result["evals"]:
                print_report(
                    model=model_result["model"],
                    trace_id=model_result["trace_id"],
                    eval_results=model_result["evals"],
                    latency_ms=model_result["latency"],
                    tokens_used=model_result["tokens"],
                )

    print("=" * 65)
    print("Demo complete. Traces available in Langfuse Cloud.")
    print("=" * 65)


if __name__ == "__main__":
    try:
        run_all_domains()
    except KeyboardInterrupt:
        print("\n\nDemo cancelled")
    except Exception as e:
        print(f"\nERROR: {e}")
