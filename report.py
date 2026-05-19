"""Report formatter — prints formatted eval reports with box-drawing characters."""

import sys
import io

# Force UTF-8 output on Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def print_report(
    model: str,
    trace_id: str,
    eval_results: dict,
    latency_ms: int,
    tokens_used: int,
) -> None:
    """
    Print a formatted eval report to stdout using box-drawing characters.

    Args:
        model: Model name
        trace_id: Langfuse trace ID
        eval_results: Dict from evaluator.evaluate_response()
        latency_ms: Latency in milliseconds
        tokens_used: Tokens consumed
    """
    # Calculate fail count and risk level (skipped doesn't count as fail)
    fail_count = sum(1 for r in eval_results.values() if r.get("passed") is False and not r.get("skipped", False))

    if fail_count == 0:
        risk_level = "LOW"
        risk_symbol = "✓"
    elif fail_count <= 2:
        risk_level = "MEDIUM"
        risk_symbol = "⚠"
    else:
        risk_level = "HIGH"
        risk_symbol = "✗"

    # Box-drawing characters
    top_left = "┌"
    top_right = "┐"
    bottom_left = "└"
    bottom_right = "┘"
    h_line = "─"
    v_line = "│"
    cross = "┼"
    t_down = "┬"
    t_up = "┴"
    t_right = "├"
    t_left = "┤"

    width = 73
    h_fill = h_line * (width - 2)

    print()
    print(f"{top_left}{h_fill}{top_right}")
    print(f"{v_line} {'MODEL EVALUATION REPORT'.center(width - 2)} {v_line}")
    print(f"{t_right}{h_line * (width - 2)}{t_left}")
    print(f"{v_line} Model:      {model:<54} {v_line}")
    print(f"{v_line} Trace ID:   {trace_id:<54} {v_line}")
    print(f"{v_line} Latency:    {latency_ms} ms{' ' * (50 - len(str(latency_ms)))} {v_line}")
    print(f"{v_line} Tokens:     {tokens_used}{' ' * (55 - len(str(tokens_used)))} {v_line}")
    print(f"{v_line} Risk Level: {risk_level} {risk_symbol:<48} {v_line}")
    print(f"{t_right}{h_line * (width - 2)}{t_left}")
    print(f"{v_line} {'Metric':<22} {'Score':<12} {'Status':<18} {v_line}")
    print(f"{t_right}{h_line * (width - 2)}{t_left}")

    for metric_name, result in eval_results.items():
        score = result.get("score")
        passed = result.get("passed")
        skipped = result.get("skipped", False)

        # Format score and status
        if skipped:
            score_str = "N/A"
            status_str = "SKIPPED"
        elif score is None:
            score_str = "N/A"
            status_str = "ERROR"
        elif passed:
            score_str = f"{score:.2f}"
            status_str = "PASS ✓"
        else:
            score_str = f"{score:.2f}"
            status_str = "FAIL ✗"

        metric_display = metric_name.replace("_", " ").title()

        print(f"{v_line} {metric_display:<22} {score_str:<12} {status_str:<18} {v_line}")

    print(f"{bottom_left}{h_fill}{bottom_right}")
    print()


if __name__ == "__main__":
    # Test
    test_results = {
        "hallucination": {"score": 0.92, "passed": True, "skipped": False},
        "answer_relevancy": {"score": 0.88, "passed": True, "skipped": False},
        "toxicity": {"score": 0.05, "passed": True, "skipped": False},
        "pii_leakage": {"score": 0.0, "passed": True, "skipped": False},
        "faithfulness": {"score": 0.85, "passed": True, "skipped": False},
    }

    print_report(
        model="gpt-4o-mini",
        trace_id="trace_abc123def456",
        eval_results=test_results,
        latency_ms=1250,
        tokens_used=145,
    )
