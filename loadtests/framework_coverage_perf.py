"""Framework coverage matrix microbenchmark — acceptance criterion A6.

Calls domain.framework_coverage.framework_matrix() 50 times against the 6
seeded demo AI system IDs. Asserts median total wall time < 2 000 ms.

If none of the seeded systems exist in the repository (fresh start / empty
data directory), the bench exits with code 2 (skipped) rather than failing.

Usage:
    python -m loadtests.framework_coverage_perf

Exit codes:
    0 — median wall time < MEDIAN_MAX_MS (pass)
    1 — median wall time >= MEDIAN_MAX_MS (fail)
    2 — seeded systems not found or dependency unavailable (skipped)

Output:
    Single JSON line:
        {"n": int, "median_ms": float, "max_ms": float, "min_ms": float, "pass": bool}
    or on skip:
        {"skipped": true, "reason": str}
"""
from __future__ import annotations

import json
import sys
import time
from typing import Any

MEDIAN_MAX_MS: int = 2_000
"""Acceptance threshold: median framework_matrix wall time must be below this (ms)."""

_SEEDED_SYSTEM_IDS: list[str] = [
    "sys-payments-001",
    "sys-cx-001",
    "sys-risk-001",
    "sys-platform-001",
    "sys-finserv-001",
    "sys-internal-001",
]


def _median(values: list[float]) -> float:
    """Compute median of a list of floats.

    Args:
        values: Non-empty list of floats.

    Returns:
        Median value.
    """
    if not values:
        return 0.0
    sv = sorted(values)
    mid = len(sv) // 2
    if len(sv) % 2 == 0:
        return (sv[mid - 1] + sv[mid]) / 2.0
    return sv[mid]


def run_bench(n: int = 50) -> dict[str, Any]:
    """Run the framework_matrix benchmark and return a results dict.

    Args:
        n: Number of framework_matrix() calls to make.

    Returns:
        Dict with keys: n, median_ms, max_ms, min_ms, pass.

    Raises:
        ImportError: If domain.framework_coverage is unavailable (caller handles).
        RuntimeError: If no seeded systems are found (caller should exit 2).
    """
    from domain.framework_coverage import framework_matrix  # noqa: PLC0415
    from domain import repository  # noqa: PLC0415

    # Check if any seeded systems are present in the repository
    repo_systems = repository.list_ai_systems()
    repo_ids = {s.id for s in repo_systems}
    found_ids = [sid for sid in _SEEDED_SYSTEM_IDS if sid in repo_ids]

    if not found_ids:
        raise RuntimeError(
            f"No seeded systems found in repository. Expected one of: {_SEEDED_SYSTEM_IDS}. "
            "Seed the demo data before running this benchmark."
        )

    wall_times_ms: list[float] = []

    for _ in range(n):
        t0 = time.perf_counter_ns()
        framework_matrix(_SEEDED_SYSTEM_IDS)
        t1 = time.perf_counter_ns()
        wall_times_ms.append((t1 - t0) / 1_000_000.0)

    med = _median(wall_times_ms)

    return {
        "n": n,
        "median_ms": round(med, 3),
        "max_ms": round(max(wall_times_ms), 3),
        "min_ms": round(min(wall_times_ms), 3),
        "pass": med < MEDIAN_MAX_MS,
    }


def main() -> None:
    """Entry point: run bench, print JSON result, exit with appropriate code."""
    try:
        result = run_bench(50)
    except ImportError as exc:
        print(json.dumps({"skipped": True, "reason": str(exc)}))
        sys.exit(2)
    except RuntimeError as exc:
        print(json.dumps({"skipped": True, "reason": str(exc)}))
        sys.exit(2)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)

    print(json.dumps(result))
    sys.exit(0 if result["pass"] else 1)


if __name__ == "__main__":
    main()
