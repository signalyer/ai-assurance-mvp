"""End-to-end demo: LLM instrumentation with Langfuse + evaluation with DeepEval."""

import os
import json
from typing import Optional
from dotenv import load_dotenv
from anthropic import Anthropic

from langfuse_wrapper import LangfuseTracer
from eval_suite import EvaluationSuite


def load_config() -> dict[str, str]:
    """Load and validate required environment variables."""
    load_dotenv()

    required = ["ANTHROPIC_API_KEY", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "OPENAI_API_KEY"]
    config = {}
    missing = []

    for var in required:
        value = os.getenv(var)
        if not value:
            missing.append(var)
        else:
            config[var] = value

    if missing:
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}\n"
                        "Copy .env.example to .env and fill in your API keys.")

    return config


def generate_response(client: Anthropic, query: str) -> str:
    """
    Generate response from Claude using Anthropic API.

    Args:
        client: Anthropic client instance
        query: User query

    Returns:
        Response text from Claude
    """
    message = client.messages.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": query,
            }
        ],
    )

    return message.content[0].text


def run_demo() -> None:
    """Run end-to-end demo with tracing and evaluation."""
    print("=" * 70)
    print("AI ASSURANCE PLATFORM MVP - END-TO-END DEMO")
    print("=" * 70)

    # Load configuration
    print("\n[1/5] Loading configuration...")
    try:
        config = load_config()
        print("✓ Configuration loaded")
    except ValueError as e:
        print(f"✗ Configuration error: {e}")
        return

    # Initialize Langfuse tracer
    print("\n[2/5] Initializing Langfuse tracer...")
    try:
        tracer = LangfuseTracer()
        print("✓ Langfuse client initialized")
    except Exception as e:
        print(f"✗ Langfuse initialization failed: {e}")
        return

    # Initialize evaluation suite
    print("\n[3/5] Initializing DeepEval suite...")
    try:
        eval_suite = EvaluationSuite()
        print("✓ Evaluation suite initialized with 5 metrics")
    except Exception as e:
        print(f"✗ Evaluation suite initialization failed: {e}")
        return

    # Initialize Anthropic client
    print("\n[4/5] Generating response with Claude API...")
    anthropic_client = Anthropic(api_key=config["ANTHROPIC_API_KEY"])

    query = "Explain the concept of machine learning in 2-3 sentences for someone new to AI."
    retrieval_context = [
        "Machine learning is a subset of artificial intelligence that focuses on systems that can learn from and make decisions based on data.",
        "Supervised learning uses labeled data to train models, while unsupervised learning finds patterns in unlabeled data.",
    ]

    try:
        response_text = generate_response(anthropic_client, query)
        print(f"✓ Response generated successfully")
        print(f"\nQuery: {query}")
        print(f"\nResponse:\n{response_text}\n")
    except Exception as e:
        print(f"✗ Response generation failed: {e}")
        return

    # Trace the LLM call
    print("[5/5] Tracing and evaluating response...")
    try:
        trace_id = tracer.trace_llm_call(
            function_name="generate_response",
            model="claude-3-5-sonnet-20241022",
            input_data={"query": query},
            output_data={"response": response_text},
            metadata={"demo": True, "context_provided": True},
        )
        print(f"✓ Traced with ID: {trace_id}")
    except Exception as e:
        print(f"✗ Tracing failed: {e}")
        return

    # Run evaluation
    print("\nRunning evaluation suite (5 metrics)...")
    try:
        eval_results = eval_suite.evaluate_output(
            input_text=query,
            actual_output=response_text,
            retrieval_context=retrieval_context,
            expected_output="Machine learning is a subset of AI that learns from data.",
        )

        # Log metrics to Langfuse
        for metric_name, metric_result in eval_results.items():
            tracer.trace_evaluation(
                trace_id=trace_id,
                metric_name=metric_name,
                metric_value=float(metric_result["score"]),
                passed=bool(metric_result["passed"]),
                details={"reason": metric_result["reason"]},
            )

        # Display results
        print("\n" + "=" * 70)
        print("EVALUATION RESULTS")
        print("=" * 70)

        for metric_name, metric_result in eval_results.items():
            status = "✓ PASS" if metric_result["passed"] else "✗ FAIL"
            print(f"\n{metric_name.upper()}")
            print(f"  Score: {metric_result['score']:.2f}")
            print(f"  Status: {status}")
            print(f"  Reason: {metric_result['reason']}")

        summary = eval_suite.summarize_results(eval_results)
        print("\n" + "=" * 70)
        print("SUMMARY")
        print("=" * 70)
        print(f"Metrics Passed: {summary['passed_count']}/{summary['total_count']}")
        print(f"Average Score: {summary['avg_score']:.2f}/1.0")
        print(f"Overall Result: {'✓ PASS' if summary['all_passed'] else '✗ FAIL'}")

    except Exception as e:
        print(f"✗ Evaluation failed: {e}")
        return

    # Flush traces to Langfuse Cloud
    print("\nFlushing traces to Langfuse Cloud...")
    try:
        tracer.flush()
        print("✓ Traces flushed successfully")
        print(f"\nView traces at: https://cloud.langfuse.com/traces/{trace_id}")
    except Exception as e:
        print(f"✗ Flush failed: {e}")

    print("\n" + "=" * 70)
    print("DEMO COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    run_demo()
