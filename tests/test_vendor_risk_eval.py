"""Contract tests for the vendor_risk eval harness (S82c Phase 4).

These tests lock the SHAPE of the harness — dataset row schema, metric
column registry, thresholds file shape, runner output schema. They do
NOT assert metric values; thresholds-met assertions land in S82e
(regression test) once real scores exist.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.vendor_risk.eval import metrics as vr_metrics
from agents.vendor_risk.eval import run_eval as vr_runner

REPO_ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = REPO_ROOT / "agents" / "vendor_risk" / "eval"

REQUIRED_CASE_FIELDS = {
    "id",
    "label",
    "system",
    "category",
    "input_vendor_package_ref",
    "expected_risk_tier",
    "expected_routing",
    "expected_hitl",
    "expected_citations_count_min",
    "expected_carve_out_detected",
    "expected_conflicts_count",
    "expected_injection_resistance",
    "expected_no_pii_leakage",
    "adversarial_injection_phrase",
}

VALID_RISK_TIERS = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
VALID_SYSTEMS = {"sys-vendor-risk-ext-001", "sys-vendor-risk-int-001"}


def _load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def test_dataset_external_has_ten_rows():
    rows = _load_jsonl(EVAL_DIR / "dataset-external.jsonl")
    assert len(rows) == 10, f"expected 10 external cases, got {len(rows)}"


def test_dataset_internal_has_eight_rows():
    rows = _load_jsonl(EVAL_DIR / "dataset-internal.jsonl")
    assert len(rows) == 8, f"expected 8 internal cases, got {len(rows)}"


@pytest.mark.parametrize(
    "dataset_file",
    ["dataset-external.jsonl", "dataset-internal.jsonl"],
)
def test_dataset_rows_have_required_fields(dataset_file: str):
    rows = _load_jsonl(EVAL_DIR / dataset_file)
    for row in rows:
        missing = REQUIRED_CASE_FIELDS - set(row.keys())
        assert not missing, f"{row.get('id')}: missing fields {missing}"
        assert row["expected_risk_tier"] in VALID_RISK_TIERS
        assert row["expected_routing"] in VALID_SYSTEMS
        assert isinstance(row["expected_hitl"], bool)


def test_external_dataset_routes_to_ext_system():
    rows = _load_jsonl(EVAL_DIR / "dataset-external.jsonl")
    for row in rows:
        assert row["expected_routing"] == "sys-vendor-risk-ext-001", (
            f"{row['id']}: external dataset row routes to {row['expected_routing']}"
        )


def test_internal_dataset_routes_to_int_system():
    rows = _load_jsonl(EVAL_DIR / "dataset-internal.jsonl")
    for row in rows:
        assert row["expected_routing"] == "sys-vendor-risk-int-001", (
            f"{row['id']}: internal dataset row routes to {row['expected_routing']}"
        )


def test_thresholds_file_shape():
    payload = vr_runner.load_thresholds()
    assert payload["version"] == "v0-spec"
    metrics = payload["metrics"]
    for name in vr_metrics.METRIC_NAMES:
        spec = metrics[name]
        assert "threshold" in spec
        assert "tier" in spec
        assert spec["tier"] in {"P0", "P1", "P2"}
        assert 0.0 <= spec["threshold"] <= 1.0


def test_p0_metrics_have_exact_threshold():
    payload = vr_runner.load_thresholds()
    metrics = payload["metrics"]
    p0_names = {
        name for name, spec in metrics.items()
        if spec["tier"] == "P0"
    }
    expected_p0 = {
        "pii_leakage",
        "prompt_injection_resisted",
        "escalation_triggered_when_required",
        "routing_correct",
        "carve_out_detected",
    }
    assert p0_names == expected_p0
    for name in p0_names:
        assert metrics[name]["threshold"] == 1.0
        assert metrics[name]["direction"] == "exact"


def test_null_baseline_run_emits_complete_row_per_case():
    summary = vr_runner.run_eval_suite(null_baseline=True, persist=False)
    assert summary.status == "NULL_BASELINE"
    assert summary.cases_total == 18
    assert summary.cases_null == 18
    assert summary.cases_passed == 0
    for result in summary.results:
        assert result.passed is None
        assert result.overall_score is None
        assert len(result.metrics) == len(vr_metrics.METRIC_NAMES)
        metric_names = {m.name for m in result.metrics}
        assert metric_names == set(vr_metrics.METRIC_NAMES)
        for metric in result.metrics:
            assert metric.score is None
            assert metric.passed is None


def test_metrics_registry_matches_thresholds():
    payload = vr_runner.load_thresholds()
    metric_keys = set(payload["metrics"].keys())
    assert metric_keys == set(vr_metrics.METRIC_NAMES)


def test_scorers_handle_a_synthetic_passing_output():
    """End-to-end smoke: hand-rolled "good" output scores cleanly."""
    case = {
        "id": "synthetic-1",
        "label": "synthetic",
        "system": "ext",
        "category": "clean",
        "expected_risk_tier": "LOW",
        "expected_routing": "sys-vendor-risk-ext-001",
        "expected_hitl": False,
        "expected_citations_count_min": 2,
        "expected_carve_out_detected": False,
        "expected_conflicts_count": 0,
        "adversarial_injection_phrase": None,
    }
    output = {
        "system_id": "sys-vendor-risk-ext-001",
        "risk_tier": "LOW",
        "concerns": [],
        "conflicts": [],
        "citations": ["doc-a", "doc-b"],
        "retrieved_doc_ids": ["doc-a", "doc-b", "doc-c"],
        "escalation_triggered": False,
        "summary": "Clean vendor",
    }
    results = vr_metrics.score_all(case, output)
    by_name = {m.name: m for m in results}
    for p0 in (
        "routing_correct",
        "pii_leakage",
        "prompt_injection_resisted",
        "escalation_triggered_when_required",
        "carve_out_detected",
    ):
        assert by_name[p0].passed is True, f"{p0} should pass on clean synthetic"
    assert by_name["risk_tier_correct"].passed is True
