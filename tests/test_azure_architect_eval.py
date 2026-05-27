"""Tests for the Azure Deployment Architect offline eval harness."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
RUNNER_PATH = REPO_ROOT / "agents" / "azure-architect" / "eval" / "run_eval.py"


def _load_runner() -> ModuleType:
    """Load the hyphen-path eval runner as a normal module for tests."""
    spec = importlib.util.spec_from_file_location("azure_architect_eval_runner", RUNNER_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write JSONL test fixtures."""
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )


def _dataset_row(case_id: str = "simple-1rg") -> dict[str, Any]:
    """Return a compact dataset row for tests."""
    return {
        "id": case_id,
        "label": "Simple web app",
        "input_subscription_manifest": {"subscription_id": "sub-1"},
        "expected_diagram_contains": ["graph TD", "[App]", "[Storage]"],
        "expected_manifest_min_entries": 2,
    }


def _passing_output(case_id: str = "simple-1rg") -> dict[str, Any]:
    """Return a candidate output that should pass all local checks."""
    envelope = {
        "mermaid_source": "graph TD\n  app[App] --> storage[Storage]",
        "manifest": [
            {
                "resource_id": "/sub/1/rg/rg/providers/Microsoft.Web/sites/app",
                "resource_type": "Microsoft.Web/sites",
                "tier": "application",
                "configuration_summary": "Azure App Service hosting the workload.",
                "private_endpoints": [],
                "rbac_assignments": [],
                "notes": "",
            },
            {
                "resource_id": "/sub/1/rg/rg/providers/Microsoft.Storage/storageAccounts/st",
                "resource_type": "Microsoft.Storage/storageAccounts",
                "tier": "data",
                "configuration_summary": "Storage account backing the workload.",
                "private_endpoints": [],
                "rbac_assignments": [],
                "notes": "",
            },
        ],
    }
    return {"id": case_id, "actual_output": json.dumps(envelope)}


def test_run_eval_suite_passes_valid_candidate(tmp_path: Path, monkeypatch: Any) -> None:
    """A valid output row passes and reports all architecture-specific metrics."""
    runner = _load_runner()
    monkeypatch.setattr(runner, "mermaid_compiles_metric", lambda _: (1.0, "compiled"))
    dataset = tmp_path / "dataset.jsonl"
    outputs = tmp_path / "outputs.jsonl"
    _write_jsonl(dataset, [_dataset_row()])
    _write_jsonl(outputs, [_passing_output()])

    summary = runner.run_eval_suite(
        dataset_path=dataset,
        outputs_path=outputs,
        min_pass_cases=1,
        persist=False,
    )

    assert summary.status == "PASS"
    assert summary.cases_passed == 1
    assert summary.results[0].passed is True
    assert {metric.name for metric in summary.results[0].metrics} == {
        "schema_valid",
        "no_pii_leakage",
        "diagram_expected_terms",
        "manifest_coverage",
        "expected_notes",
        "mermaid_compiles",
    }


def test_run_eval_suite_fails_missing_terms_and_manifest_entries(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Coverage checks fail when diagram terms and manifest entries are absent."""
    runner = _load_runner()
    monkeypatch.setattr(runner, "mermaid_compiles_metric", lambda _: (1.0, "compiled"))
    dataset = tmp_path / "dataset.jsonl"
    outputs = tmp_path / "outputs.jsonl"
    _write_jsonl(dataset, [_dataset_row()])
    envelope = {
        "mermaid_source": "graph TD\n  app[App]",
        "manifest": [
            {
                "resource_id": "/sub/1/rg/rg/providers/Microsoft.Web/sites/app",
                "resource_type": "Microsoft.Web/sites",
                "tier": "application",
                "configuration_summary": "Azure App Service hosting the workload.",
                "private_endpoints": [],
                "rbac_assignments": [],
                "notes": "",
            }
        ],
    }
    _write_jsonl(outputs, [{"id": "simple-1rg", "actual_output": json.dumps(envelope)}])

    summary = runner.run_eval_suite(
        dataset_path=dataset,
        outputs_path=outputs,
        min_pass_cases=1,
        persist=False,
    )

    assert summary.status == "FAIL"
    metrics = {metric.name: metric for metric in summary.results[0].metrics}
    assert metrics["diagram_expected_terms"].passed is False
    assert metrics["manifest_coverage"].passed is False


def test_missing_candidate_is_explicit_failure(tmp_path: Path) -> None:
    """A dataset row without a matching candidate output fails clearly."""
    runner = _load_runner()
    dataset = tmp_path / "dataset.jsonl"
    outputs = tmp_path / "outputs.jsonl"
    _write_jsonl(dataset, [_dataset_row()])
    _write_jsonl(outputs, [])

    summary = runner.run_eval_suite(
        dataset_path=dataset,
        outputs_path=outputs,
        min_pass_cases=1,
        persist=False,
    )

    assert summary.status == "FAIL"
    assert summary.results[0].metrics[0].name == "candidate_present"
    assert "No candidate output row" in summary.results[0].failures[0]


def test_run_eval_suite_persists_with_storage_helper(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Persisted summaries are appended to the configured JSONL run file."""
    runner = _load_runner()
    monkeypatch.setattr(runner, "mermaid_compiles_metric", lambda _: (1.0, "compiled"))
    run_file = tmp_path / "azure_architect_eval_runs.jsonl"
    monkeypatch.setattr(runner, "AZURE_ARCHITECT_EVAL_RUNS_FILE", run_file)
    dataset = tmp_path / "dataset.jsonl"
    outputs = tmp_path / "outputs.jsonl"
    _write_jsonl(dataset, [_dataset_row()])
    _write_jsonl(outputs, [_passing_output()])

    summary = runner.run_eval_suite(
        dataset_path=dataset,
        outputs_path=outputs,
        min_pass_cases=1,
        persist=True,
    )

    rows = runner._read_jsonl(run_file, limit=10)
    assert len(rows) == 1
    assert rows[0]["run_id"] == summary.run_id
    assert rows[0]["status"] == "PASS"


def test_schema_extra_key_fails_closed(tmp_path: Path, monkeypatch: Any) -> None:
    """Unexpected output keys fail schema validation instead of being ignored."""
    runner = _load_runner()
    monkeypatch.setattr(runner, "mermaid_compiles_metric", lambda _: (1.0, "compiled"))
    dataset = tmp_path / "dataset.jsonl"
    outputs = tmp_path / "outputs.jsonl"
    _write_jsonl(dataset, [_dataset_row()])
    envelope = json.loads(_passing_output()["actual_output"])
    envelope["extra_summary"] = "This field is not in the output contract."
    _write_jsonl(outputs, [{"id": "simple-1rg", "actual_output": json.dumps(envelope)}])

    summary = runner.run_eval_suite(
        dataset_path=dataset,
        outputs_path=outputs,
        min_pass_cases=1,
        persist=False,
    )

    assert summary.status == "FAIL"
    assert summary.results[0].metrics[0].name == "schema_valid"
    assert summary.results[0].metrics[0].passed is False


def test_pii_leakage_fails_even_when_shape_is_valid(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """PII in otherwise-valid output fails the no_pii_leakage metric."""
    runner = _load_runner()
    monkeypatch.setattr(runner, "mermaid_compiles_metric", lambda _: (1.0, "compiled"))
    dataset = tmp_path / "dataset.jsonl"
    outputs = tmp_path / "outputs.jsonl"
    _write_jsonl(dataset, [_dataset_row()])
    envelope = json.loads(_passing_output()["actual_output"])
    envelope["manifest"][0]["notes"] = "Owner is engineer@example.com."
    _write_jsonl(outputs, [{"id": "simple-1rg", "actual_output": json.dumps(envelope)}])

    summary = runner.run_eval_suite(
        dataset_path=dataset,
        outputs_path=outputs,
        min_pass_cases=1,
        persist=False,
    )

    metrics = {metric.name: metric for metric in summary.results[0].metrics}
    assert summary.status == "FAIL"
    assert metrics["schema_valid"].passed is True
    assert metrics["no_pii_leakage"].passed is False
    assert "email" in metrics["no_pii_leakage"].details


def test_expected_notes_required_for_broken_topology(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Broken topology rows can require notes such as circular-reference flags."""
    runner = _load_runner()
    monkeypatch.setattr(runner, "mermaid_compiles_metric", lambda _: (1.0, "compiled"))
    dataset = tmp_path / "dataset.jsonl"
    outputs = tmp_path / "outputs.jsonl"
    row = _dataset_row("broken-circular")
    row["expected_notes_contains"] = ["circular"]
    _write_jsonl(dataset, [row])
    output = _passing_output("broken-circular")
    envelope = json.loads(output["actual_output"])
    envelope["manifest"][0]["notes"] = "linkedResource cycle detected; circular pair needs operator review."
    output["actual_output"] = json.dumps(envelope)
    _write_jsonl(outputs, [output])

    summary = runner.run_eval_suite(
        dataset_path=dataset,
        outputs_path=outputs,
        min_pass_cases=1,
        persist=False,
    )

    assert summary.status == "PASS"
    metrics = {metric.name: metric for metric in summary.results[0].metrics}
    assert metrics["expected_notes"].passed is True


def test_latest_duplicate_candidate_wins(tmp_path: Path, monkeypatch: Any) -> None:
    """Duplicate candidate rows use the last row, matching rerun semantics."""
    runner = _load_runner()
    monkeypatch.setattr(runner, "mermaid_compiles_metric", lambda _: (1.0, "compiled"))
    dataset = tmp_path / "dataset.jsonl"
    outputs = tmp_path / "outputs.jsonl"
    _write_jsonl(dataset, [_dataset_row()])
    failing = _passing_output()
    failing["actual_output"] = '{"not_the_contract": true}'
    passing = _passing_output()
    _write_jsonl(outputs, [failing, passing])

    summary = runner.run_eval_suite(
        dataset_path=dataset,
        outputs_path=outputs,
        min_pass_cases=1,
        persist=False,
    )

    assert summary.status == "PASS"
    assert summary.results[0].passed is True


def test_mermaid_compile_failure_fails_case(tmp_path: Path, monkeypatch: Any) -> None:
    """A valid envelope still fails when the Mermaid compiler rejects the diagram."""
    runner = _load_runner()
    monkeypatch.setattr(runner, "mermaid_compiles_metric", lambda _: (0.0, "parse error"))
    dataset = tmp_path / "dataset.jsonl"
    outputs = tmp_path / "outputs.jsonl"
    _write_jsonl(dataset, [_dataset_row()])
    _write_jsonl(outputs, [_passing_output()])

    summary = runner.run_eval_suite(
        dataset_path=dataset,
        outputs_path=outputs,
        min_pass_cases=1,
        persist=False,
    )

    metrics = {metric.name: metric for metric in summary.results[0].metrics}
    assert summary.status == "FAIL"
    assert metrics["mermaid_compiles"].passed is False
    assert metrics["mermaid_compiles"].details == "parse error"
