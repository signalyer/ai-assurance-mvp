"""Session 10 performance smoke tests.

Runs a fast (<5s) micro-version of the three microbenches using 50 operations
each. Verifies:
  - Each bench module is importable and run_bench() returns the required keys.
  - The module-level threshold constants match the documented values
    (guards against accidental loosening).
  - Framework coverage bench exits code 2 (skipped) cleanly when seeded
    systems are absent.

These tests do NOT validate production thresholds — they validate that the
harness itself works correctly.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Path setup — ensure project root is importable
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _assert_bench_result(result: dict[str, Any], bench_name: str) -> None:
    """Assert that a bench result dict has the required shape.

    Args:
        result: Dict returned by run_bench().
        bench_name: Human-readable bench name for assertion messages.
    """
    assert isinstance(result, dict), f"{bench_name}: run_bench() must return a dict"
    assert "p95_ms" in result or "median_ms" in result, (
        f"{bench_name}: result must contain 'p95_ms' or 'median_ms'. Got keys: {list(result.keys())}"
    )
    assert "pass" in result, f"{bench_name}: result must contain 'pass' key"
    assert "n" in result, f"{bench_name}: result must contain 'n' key"


# ---------------------------------------------------------------------------
# Scrubber bench
# ---------------------------------------------------------------------------

class TestScrubberPerfModule:
    """Tests for loadtests.scrubber_perf."""

    def test_importable(self) -> None:
        """scrubber_perf module imports without error."""
        import loadtests.scrubber_perf  # noqa: F401

    def test_threshold_constant(self) -> None:
        """P95_MAX_MS is exactly 100 — guards against accidental loosening."""
        from loadtests.scrubber_perf import P95_MAX_MS
        assert P95_MAX_MS == 100, (
            f"P95_MAX_MS should be 100 ms per spec; got {P95_MAX_MS}. "
            "Do not loosen this threshold without a DECISIONS.md entry."
        )

    def test_run_bench_returns_expected_keys(self) -> None:
        """run_bench(n=50) returns a dict with the required shape."""
        try:
            from loadtests.scrubber_perf import run_bench
            result = run_bench(n=50)
        except ImportError as exc:
            pytest.skip(f"scrubber dependency unavailable: {exc}")

        _assert_bench_result(result, "scrubber_perf")
        assert "p50_ms" in result, "scrubber_perf result must contain 'p50_ms'"
        assert "p99_ms" in result, "scrubber_perf result must contain 'p99_ms'"
        assert result["n"] == 50, f"Expected n=50; got {result['n']}"

    def test_p95_ms_is_float(self) -> None:
        """p95_ms value is a non-negative float."""
        try:
            from loadtests.scrubber_perf import run_bench
            result = run_bench(n=50)
        except ImportError as exc:
            pytest.skip(f"scrubber dependency unavailable: {exc}")

        assert isinstance(result["p95_ms"], float), "p95_ms must be a float"
        assert result["p95_ms"] >= 0.0, "p95_ms must be non-negative"


# ---------------------------------------------------------------------------
# OPA bench
# ---------------------------------------------------------------------------

class TestOpaBenchModule:
    """Tests for loadtests.opa_p95."""

    def test_importable(self) -> None:
        """opa_p95 module imports without error."""
        import loadtests.opa_p95  # noqa: F401

    def test_threshold_constant(self) -> None:
        """P95_MAX_MS is exactly 50 — guards against accidental loosening."""
        from loadtests.opa_p95 import P95_MAX_MS
        assert P95_MAX_MS == 50, (
            f"P95_MAX_MS should be 50 ms per spec; got {P95_MAX_MS}. "
            "Do not loosen this threshold without a DECISIONS.md entry."
        )

    def test_run_bench_returns_expected_keys(self) -> None:
        """run_bench(n=50) returns a dict with the required shape."""
        try:
            from loadtests.opa_p95 import run_bench
            result = run_bench(n=50)
        except ImportError as exc:
            pytest.skip(f"domain.policy_engine unavailable: {exc}")

        _assert_bench_result(result, "opa_p95")
        assert "p50_ms" in result, "opa_p95 result must contain 'p50_ms'"
        assert "p99_ms" in result, "opa_p95 result must contain 'p99_ms'"
        assert result["n"] == 50, f"Expected n=50; got {result['n']}"

    def test_opa_not_required(self) -> None:
        """run_bench() must not fail if OPA_URL is not set."""
        import os
        os.environ.pop("OPA_URL", None)

        try:
            from loadtests.opa_p95 import run_bench
            result = run_bench(n=10)
        except ImportError as exc:
            pytest.skip(f"domain.policy_engine unavailable: {exc}")

        assert isinstance(result, dict), "run_bench must return a dict even without OPA"


# ---------------------------------------------------------------------------
# Framework coverage bench
# ---------------------------------------------------------------------------

class TestFrameworkCoverageModule:
    """Tests for loadtests.framework_coverage_perf."""

    def test_importable(self) -> None:
        """framework_coverage_perf module imports without error."""
        import loadtests.framework_coverage_perf  # noqa: F401

    def test_threshold_constant(self) -> None:
        """MEDIAN_MAX_MS is exactly 2000 — guards against accidental loosening."""
        from loadtests.framework_coverage_perf import MEDIAN_MAX_MS
        assert MEDIAN_MAX_MS == 2_000, (
            f"MEDIAN_MAX_MS should be 2000 ms per spec; got {MEDIAN_MAX_MS}. "
            "Do not loosen this threshold without a DECISIONS.md entry."
        )

    def test_run_bench_skips_gracefully_when_no_seeded_systems(self) -> None:
        """run_bench() raises RuntimeError (not a crash) when seeded systems absent.

        The bench is responsible for propagating RuntimeError so callers can
        exit code 2 (skipped).  This test asserts the contract.
        """
        try:
            from loadtests.framework_coverage_perf import run_bench
            from domain import repository
        except ImportError as exc:
            pytest.skip(f"domain.framework_coverage unavailable: {exc}")

        repo_systems = repository.list_ai_systems()
        seeded_ids = {
            "sys-payments-001", "sys-cx-001", "sys-risk-001",
            "sys-platform-001", "sys-finserv-001", "sys-internal-001",
        }
        has_seeded = bool({s.id for s in repo_systems} & seeded_ids)

        if not has_seeded:
            with pytest.raises(RuntimeError, match="No seeded systems"):
                run_bench(n=1)
        else:
            pytest.skip("Seeded systems present — skipped-path test not applicable")

    def test_run_bench_returns_expected_keys_when_seeded(self) -> None:
        """run_bench(n=5) returns a dict with required keys when systems exist."""
        try:
            from loadtests.framework_coverage_perf import run_bench
            from domain import repository
        except ImportError as exc:
            pytest.skip(f"domain.framework_coverage unavailable: {exc}")

        repo_systems = repository.list_ai_systems()
        seeded_ids = {
            "sys-payments-001", "sys-cx-001", "sys-risk-001",
            "sys-platform-001", "sys-finserv-001", "sys-internal-001",
        }
        if not ({s.id for s in repo_systems} & seeded_ids):
            pytest.skip("No seeded systems in repository — seed with python mock_data.py first")

        result = run_bench(n=5)

        assert isinstance(result, dict), "run_bench must return a dict"
        assert "median_ms" in result, "result must contain 'median_ms'"
        assert "pass" in result, "result must contain 'pass'"
        assert result["n"] == 5, f"Expected n=5; got {result['n']}"
