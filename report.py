"""Report formatter — prints formatted eval reports."""

import sys


def print_report(
    model: str,
    trace_id: str,
    eval_results: dict,
    latency_ms: int,
    tokens_used: int,
) -> None:
    """
    Print a formatted eval report to stdout.

    Args:
        model: Model name
        trace_id: Langfuse trace ID
        eval_results: Dict from evaluator.evaluate_response()
        latency_ms: Latency in milliseconds
        tokens_used: Tokens consumed
    """
    print()
    print("=" * 65)
    print(f"MODEL EVALUATION REPORT".center(65))
    print("=" * 65)
    print(f"Model:      {model:<48}")
    print(f"Trace ID:   {trace_id:<48}")
    print(f"Latency:    {latency_ms} ms")
    print(f"Tokens:     {tokens_used}")
    print("-" * 65)
    print("METRICS".center(65))
    print("-" * 65)
    print(f"{'Metric':<20} {'Score':<12} {'Status':<8} {'Details':<25}")
    print("-" * 65)

    for metric_name, result in eval_results.items():
        score = result.get("score")
        passed = result.get("passed")
        details = result.get("details", "")

        # Format score
        if score is None:
            score_str = "SKIP"
            status_str = "~"
        elif passed:
            score_str = f"{score:.2f}"
            status_str = "PASS"
        else:
            score_str = f"{score:.2f}"
            status_str = "FAIL"

        # Truncate details to fit
        details_short = (details[:23] + "..") if len(details) > 25 else details

        # Pad metric name
        metric_display = metric_name.replace("_", " ").title()[:20]

        print(f"{metric_display:<20} {score_str:<12} {status_str:<8} {details_short:<25}")

    print("=" * 65)
    print()


if __name__ == "__main__":
    # Test
    test_results = {
        "hallucination": {"score": 0.92, "passed": True, "details": "Low hallucination"},
        "answer_relevancy": {"score": 0.88, "passed": True, "details": "Relevant"},
        "toxicity": {"score": 0.05, "passed": True, "details": "Non-toxic"},
        "pii_leakage": {"score": 1.0, "passed": True, "details": "No PII"},
        "faithfulness": {"score": 0.85, "passed": True, "details": "Faithful"},
    }

    print_report(
        model="gpt-4o-mini",
        trace_id="trace_abc123def456",
        eval_results=test_results,
        latency_ms=1250,
        tokens_used=145,
    )
