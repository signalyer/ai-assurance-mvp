"""S82e regression test — vendor_risk eval thresholds against locked baseline.

Loads the locked baseline written by S82e (`agents/vendor_risk/eval/
baseline.json`) and asserts that every per-metric pass rate meets the
threshold declared in `thresholds.json`. This is a STATIC test: it does
NOT re-run the LLM eval (which costs API credits and takes ~15 min);
instead it gates against the frozen baseline written at lock time.

To refresh the baseline after an intentional prompt change:
  1. PYTHONIOENCODING=utf-8 python -m agents.vendor_risk.eval.run_eval
  2. Copy the latest run from data/vendor_risk_eval_runs.jsonl into
     agents/vendor_risk/eval/baseline.json.
  3. Update agents/vendor_risk/eval/iteration-log.md with cycle notes.
  4. Re-sign 06-lock-signoff.md.

This test guards against accidental prompt regressions: if someone
weakens the system prompt or breaks the JSON extractor, the baseline
file they regenerate will show degraded scores and this test catches
the drop at commit time (assuming the dev runs the eval and updates
the baseline — see CI gate note below).

CI gate caveat: the baseline is a checked-in artifact, so this test
only enforces that whatever baseline IS committed meets the thresholds.
A more aggressive gate would re-run the live eval on every PR; that
costs API credits per PR and was rejected in favor of this static
guard plus the lock signoff doc.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import pytest

EVAL_DIR = Path(__file__).resolve().parents[1] / "agents" / "vendor_risk" / "eval"
BASELINE_PATH = EVAL_DIR / "baseline.json"
THRESHOLDS_PATH = EVAL_DIR / "thresholds.json"


def _load_baseline() -> dict:
    if not BASELINE_PATH.exists():
        pytest.skip(f"locked baseline not found: {BASELINE_PATH}")
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def _load_thresholds() -> dict:
    return json.loads(THRESHOLDS_PATH.read_text(encoding="utf-8"))


def _pass_rates(baseline: dict) -> dict[str, float]:
    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for case in baseline["results"]:
        for m in case["metrics"]:
            totals[m["name"]][0] += 1 if m["passed"] else 0
            totals[m["name"]][1] += 1
    return {k: (p / t if t else 0.0) for k, (p, t) in totals.items()}


def test_locked_baseline_meets_every_metric_threshold() -> None:
    """Every per-metric pass rate ≥ its threshold in thresholds.json."""
    baseline = _load_baseline()
    thresholds = _load_thresholds()["metrics"]
    rates = _pass_rates(baseline)
    failures: list[str] = []
    for name, spec in thresholds.items():
        actual = rates.get(name, 0.0)
        if actual + 1e-9 < spec["threshold"]:
            failures.append(
                f"{name}: {actual:.3f} < threshold {spec['threshold']} ({spec['tier']})"
            )
    assert not failures, "Locked baseline regressed:\n  " + "\n  ".join(failures)


def test_locked_baseline_p0_metrics_at_perfect() -> None:
    """All P0 metrics MUST be 100% on the locked baseline."""
    baseline = _load_baseline()
    thresholds = _load_thresholds()["metrics"]
    rates = _pass_rates(baseline)
    p0_failures = [
        f"{name}: {rates.get(name, 0.0):.3f}"
        for name, spec in thresholds.items()
        if spec["tier"] == "P0" and rates.get(name, 0.0) < 1.0
    ]
    assert not p0_failures, "P0 metrics not at 1.0:\n  " + "\n  ".join(p0_failures)


def test_locked_baseline_has_expected_case_count() -> None:
    """Locked dataset is 18 cases — guards against silent dataset truncation."""
    baseline = _load_baseline()
    assert baseline["cases_total"] == 18, (
        f"locked baseline has {baseline['cases_total']} cases; expected 18"
    )


def test_locked_baseline_pass_rate_above_minimum() -> None:
    """≥80% of cases pass all-metrics — the S82e plan exit criterion."""
    baseline = _load_baseline()
    rate = baseline["cases_passed"] / baseline["cases_total"]
    assert rate >= 0.80, (
        f"locked baseline pass rate {rate:.3f} below S82e exit criterion 0.80"
    )
