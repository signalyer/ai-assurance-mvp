"""OPA / policy-engine microbenchmark — acceptance criterion A5.

Runs 1 000 calls to domain.policy_engine.evaluate() against the local
Python fallback (no OPA sidecar required). Asserts p95 latency < 50 ms.

Usage:
    python -m loadtests.opa_p95

Exit codes:
    0 — p95 < P95_MAX_MS (pass)
    1 — p95 >= P95_MAX_MS (fail)
    2 — policy_engine unavailable (skipped)

Output:
    Single JSON line: {"n": int, "p50_ms": float, "p95_ms": float, "p99_ms": float, "pass": bool}
"""
from __future__ import annotations

import json
import sys
import time
from typing import Any

P95_MAX_MS: int = 50
"""Acceptance threshold: policy-engine p95 latency must be below this value (ms)."""

_SYNTHETIC_INPUTS: list[dict[str, Any]] = [
    {"prompt": "What is the weather today?", "domain": "general"},
    {"prompt": "Show me account balance for [EMAIL_001]", "risk_tier": "MEDIUM"},
    {"prompt": "Trade recommendation for [PERSON_001]", "domain": "finance", "posture": "us-finserv"},
    {"prompt": "Memory write for agent [UUID_001]", "team": "payments", "preauthorized": True},
    {"prompt": "Tool invoke for data export", "risk_tier": "HIGH"},
]


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Compute the p-th percentile of a sorted list.

    Args:
        sorted_values: Pre-sorted list of float values.
        pct: Percentile fraction between 0.0 and 1.0.

    Returns:
        Interpolated percentile value.
    """
    if not sorted_values:
        return 0.0
    idx = min(int(len(sorted_values) * pct), len(sorted_values) - 1)
    return sorted_values[idx]


def run_bench(n: int = 1_000) -> dict[str, Any]:
    """Run the OPA / policy-engine benchmark and return a results dict.

    OPA_URL is intentionally unset during the bench so the local Python
    fallback path is exercised. No network calls are made.

    Args:
        n: Number of evaluate() calls to make.

    Returns:
        Dict with keys: n, p50_ms, p95_ms, p99_ms, pass.

    Raises:
        ImportError: If domain.policy_engine is unavailable (caller handles).
    """
    import os

    # Force local fallback — do not depend on OPA sidecar
    original_opa_url = os.environ.pop("OPA_URL", None)

    try:
        from domain.policy_engine import evaluate  # noqa: PLC0415

        latencies_ns: list[int] = []

        for i in range(n):
            input_data = _SYNTHETIC_INPUTS[i % len(_SYNTHETIC_INPUTS)]
            t0 = time.perf_counter_ns()
            evaluate(
                workload_id=f"bench-workload-{i:04d}",
                action="llm_call",
                input_data=input_data,
            )
            t1 = time.perf_counter_ns()
            latencies_ns.append(t1 - t0)

    finally:
        if original_opa_url is not None:
            os.environ["OPA_URL"] = original_opa_url

    latencies_ms = sorted(ns / 1_000_000.0 for ns in latencies_ns)

    p50 = _percentile(latencies_ms, 0.50)
    p95 = _percentile(latencies_ms, 0.95)
    p99 = _percentile(latencies_ms, 0.99)

    return {
        "n": n,
        "p50_ms": round(p50, 3),
        "p95_ms": round(p95, 3),
        "p99_ms": round(p99, 3),
        "pass": p95 < P95_MAX_MS,
    }


def main() -> None:
    """Entry point: run bench, print JSON result, exit with appropriate code."""
    try:
        result = run_bench(1_000)
    except ImportError as exc:
        print(json.dumps({"skipped": True, "reason": str(exc)}))
        sys.exit(2)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)

    print(json.dumps(result))
    sys.exit(0 if result["pass"] else 1)


if __name__ == "__main__":
    main()
