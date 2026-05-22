"""Scrubber microbenchmark — acceptance criterion A4.

Generates 10 000 synthetic payloads containing PII (emails, SSNs, names),
runs each through scrubber.tokenise_payload(), and asserts p95 < 100 ms.

Usage:
    python -m loadtests.scrubber_perf

Exit codes:
    0 — p95 < P95_MAX_MS (pass)
    1 — p95 >= P95_MAX_MS (fail)
    2 — scrubber dependency unavailable (skipped)

Output:
    Single JSON line: {"n": int, "p50_ms": float, "p95_ms": float, "p99_ms": float, "pass": bool}
"""
from __future__ import annotations

import json
import sys
import time
from typing import Any

P95_MAX_MS: int = 100
"""Acceptance threshold: scrubber p95 latency must be below this value (ms)."""

_PAYLOAD_TEMPLATE = (
    "Customer {name} has SSN {ssn} and email {email}. "
    "Account {acct}. Phone {phone}."
)

_NAMES = [
    "Alice Johnson", "Bob Martinez", "Carol Lee", "David Chen",
    "Eve Williams", "Frank Brown", "Grace Taylor", "Henry Davis",
]
_SSNS = [
    "123-45-6789", "234-56-7890", "345-67-8901", "456-78-9012",
    "567-89-0123", "678-90-1234", "789-01-2345", "890-12-3456",
]
_EMAILS = [
    "alice@example.com", "bob@corp.org", "carol@domain.net",
    "david@sample.io", "eve@test.co", "frank@demo.ai",
    "grace@company.com", "henry@enterprise.biz",
]
_PHONES = [
    "+1-555-867-5309", "+1-555-234-5678", "+1-555-345-6789",
    "+1-555-456-7890", "+1-555-567-8901", "+1-555-678-9012",
]


def _generate_payload(index: int) -> str:
    """Generate one synthetic PII payload at the given index.

    Args:
        index: Sequence number used to cycle through PII variants.

    Returns:
        A text string containing name, SSN, email, phone, and account number.
    """
    return _PAYLOAD_TEMPLATE.format(
        name=_NAMES[index % len(_NAMES)],
        ssn=_SSNS[index % len(_SSNS)],
        email=_EMAILS[index % len(_EMAILS)],
        acct=f"ACC{index:08d}",
        phone=_PHONES[index % len(_PHONES)],
    )


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
    idx = int(len(sorted_values) * pct)
    idx = min(idx, len(sorted_values) - 1)
    return sorted_values[idx]


def run_bench(n: int = 10_000) -> dict[str, Any]:
    """Run the scrubber benchmark and return a results dict.

    Args:
        n: Number of payloads to process.

    Returns:
        Dict with keys: n, p50_ms, p95_ms, p99_ms, pass.

    Raises:
        ImportError: If scrubber or its dependencies are unavailable (caller handles).
    """
    from scrubber import tokenise_payload  # noqa: PLC0415 — deferred to allow ImportError propagation

    latencies_ns: list[int] = []

    for i in range(n):
        payload = _generate_payload(i)
        scope = f"bench_{i}"
        t0 = time.perf_counter_ns()
        tokenise_payload(payload, scope)
        t1 = time.perf_counter_ns()
        latencies_ns.append(t1 - t0)

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
        result = run_bench(10_000)
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
