"""Offline eval runner for the Azure Deployment Architect agent.

The live agent is allowed to spend tokens; this runner is not. It scores
candidate output JSON envelopes against the worked-example dataset in
``dataset.jsonl`` and persists a compact run record through the platform's
canonical JSONL storage helper.

Usage:
    python agents/azure-architect/eval/run_eval.py --outputs path/to/outputs.jsonl

Each output row must contain:
    {"id": "<dataset row id>", "actual_output": "{\"mermaid_source\": ...}"}
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

EVAL_DIR = Path(__file__).resolve().parent
REPO_ROOT = EVAL_DIR.parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))

from mermaid_compiles_metric import mermaid_compiles_metric  # noqa: E402
from storage import STORAGE_DIR, _append_jsonl, _read_jsonl  # noqa: E402


DEFAULT_DATASET = EVAL_DIR / "dataset.jsonl"
AZURE_ARCHITECT_EVAL_RUNS_FILE = STORAGE_DIR / "azure_architect_eval_runs.jsonl"
PII_PATTERNS: tuple[tuple[str, str], ...] = (
    ("email", r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    ("phone", r"\b(?:\(\d{3}\)\s?|\d{3}[-.]?)\d{3}[-.]?\d{4}\b"),
    ("ssn", r"\b\d{3}-\d{2}-\d{4}\b"),
    ("credit_card", r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b"),
)


def _strict() -> ConfigDict:
    """Return the strict model config used by eval wire models."""
    return ConfigDict(extra="forbid")


class DatasetCase(BaseModel):
    """One manifest fixture from ``dataset.jsonl``."""

    model_config = _strict()

    id: str
    input_subscription_manifest: dict[str, object]
    expected_diagram_contains: list[str] = Field(default_factory=list)
    expected_manifest_min_entries: int = 0
    expected_notes_contains: list[str] = Field(default_factory=list)
    label: str = ""


class CandidateOutput(BaseModel):
    """One candidate agent output keyed to a dataset row."""

    model_config = _strict()

    id: str
    actual_output: str | dict[str, object]


class RbacAssignmentOut(BaseModel):
    """One RBAC assignment entry in the generated resource manifest."""

    model_config = _strict()

    principal_type: str
    role: str
    scope: str


class ManifestEntryOut(BaseModel):
    """One generated per-resource manifest entry."""

    model_config = _strict()

    resource_id: str
    resource_type: str
    tier: Literal[
        "frontend",
        "application",
        "data",
        "shared",
        "observability",
        "unknown",
    ]
    configuration_summary: str
    private_endpoints: list[str] = Field(default_factory=list)
    rbac_assignments: list[RbacAssignmentOut] = Field(default_factory=list)
    notes: str = ""


class AgentOutputEnvelope(BaseModel):
    """The terminal output contract for Azure architect synthesis."""

    model_config = _strict()

    mermaid_source: str
    manifest: list[ManifestEntryOut]


class MetricResult(BaseModel):
    """One normalized metric result."""

    model_config = _strict()

    name: str
    score: float
    passed: bool
    details: str


class CaseResult(BaseModel):
    """Eval result for one dataset case."""

    model_config = _strict()

    id: str
    label: str
    passed: bool
    score: float
    metrics: list[MetricResult]
    failures: list[str] = Field(default_factory=list)


class EvalRunSummary(BaseModel):
    """Persisted summary for one Azure architect eval run."""

    model_config = _strict()

    run_id: str
    timestamp: str
    dataset_path: str
    outputs_path: str
    status: Literal["PASS", "FAIL"]
    cases_total: int
    cases_passed: int
    min_pass_cases: int
    pass_rate: float
    overall_score: float
    results: list[CaseResult]


for _model in (AgentOutputEnvelope, CaseResult, EvalRunSummary):
    _model.model_rebuild(_types_namespace=globals())


def _jsonl_records_in_file_order(path: Path) -> list[dict]:
    """Read a JSONL file via storage._read_jsonl and restore file order."""
    return list(reversed(_read_jsonl(path, limit=None)))


def load_dataset(path: Path = DEFAULT_DATASET) -> list[DatasetCase]:
    """Load and validate the Azure architect eval dataset.

    Args:
        path: Dataset JSONL path.

    Returns:
        Dataset cases in file order.
    """
    return [DatasetCase.model_validate(row) for row in _jsonl_records_in_file_order(path)]


def load_candidate_outputs(path: Path) -> dict[str, CandidateOutput]:
    """Load candidate outputs keyed by dataset case id.

    Args:
        path: JSONL file with one ``CandidateOutput`` row per case.

    Returns:
        Mapping of case id to candidate output. Later duplicate ids replace
        earlier ones, matching normal "latest candidate wins" eval semantics.
    """
    outputs: dict[str, CandidateOutput] = {}
    for row in _jsonl_records_in_file_order(path):
        candidate = CandidateOutput.model_validate(row)
        outputs[candidate.id] = candidate
    return outputs


def _normalise_actual_output(actual_output: str | dict[str, object]) -> str:
    """Return candidate output as a JSON string for schema and metric checks."""
    if isinstance(actual_output, str):
        return actual_output
    return json.dumps(actual_output, sort_keys=True)


def _parse_envelope(actual_output: str | dict[str, object]) -> tuple[AgentOutputEnvelope | None, MetricResult]:
    """Parse and strictly validate the agent output envelope."""
    text = _normalise_actual_output(actual_output)
    try:
        envelope = AgentOutputEnvelope.model_validate_json(text)
    except ValidationError as exc:
        return (
            None,
            MetricResult(
                name="schema_valid",
                score=0.0,
                passed=False,
                details=f"Output schema invalid: {exc.errors()[0]['msg']}",
            ),
        )
    except ValueError as exc:
        return (
            None,
            MetricResult(
                name="schema_valid",
                score=0.0,
                passed=False,
                details=f"Output JSON invalid: {exc}",
            ),
        )
    return (
        envelope,
        MetricResult(
            name="schema_valid",
            score=1.0,
            passed=True,
            details="Envelope matches mermaid_source + manifest contract",
        ),
    )


def _score_expected_diagram(case: DatasetCase, envelope: AgentOutputEnvelope) -> MetricResult:
    """Score whether required Mermaid substrings are present."""
    expected = case.expected_diagram_contains
    if not expected:
        return MetricResult(
            name="diagram_expected_terms",
            score=1.0,
            passed=True,
            details="No expected diagram terms configured",
        )
    missing = [term for term in expected if term not in envelope.mermaid_source]
    score = (len(expected) - len(missing)) / len(expected)
    return MetricResult(
        name="diagram_expected_terms",
        score=round(score, 4),
        passed=not missing,
        details="All expected diagram terms present"
        if not missing
        else f"Missing: {', '.join(missing)}",
    )


def _score_manifest_coverage(case: DatasetCase, envelope: AgentOutputEnvelope) -> MetricResult:
    """Score whether the manifest has enough resource entries."""
    minimum = case.expected_manifest_min_entries
    actual = len(envelope.manifest)
    if minimum <= 0:
        return MetricResult(
            name="manifest_coverage",
            score=1.0,
            passed=True,
            details=f"{actual} manifest entries; no minimum configured",
        )
    score = min(actual / minimum, 1.0)
    return MetricResult(
        name="manifest_coverage",
        score=round(score, 4),
        passed=actual >= minimum,
        details=f"{actual}/{minimum} required manifest entries",
    )


def _score_notes(case: DatasetCase, envelope: AgentOutputEnvelope) -> MetricResult:
    """Score whether expected operator notes are present."""
    expected = case.expected_notes_contains
    if not expected:
        return MetricResult(
            name="expected_notes",
            score=1.0,
            passed=True,
            details="No expected notes configured",
        )
    notes_text = " ".join(entry.notes for entry in envelope.manifest).lower()
    missing = [term for term in expected if term.lower() not in notes_text]
    score = (len(expected) - len(missing)) / len(expected)
    return MetricResult(
        name="expected_notes",
        score=round(score, 4),
        passed=not missing,
        details="All expected notes present" if not missing else f"Missing: {', '.join(missing)}",
    )


def _score_mermaid_compiles(envelope: AgentOutputEnvelope) -> MetricResult:
    """Run the custom Mermaid compile metric against the output envelope."""
    score, reason = mermaid_compiles_metric(envelope.model_dump_json())
    return MetricResult(
        name="mermaid_compiles",
        score=float(score),
        passed=score == 1.0,
        details=reason,
    )


def _score_no_pii(actual_output: str | dict[str, object]) -> MetricResult:
    """Score 1.0 when output contains no obvious PII."""
    text = _normalise_actual_output(actual_output)
    findings = [
        name
        for name, pattern in PII_PATTERNS
        if re.search(pattern, text)
    ]
    return MetricResult(
        name="no_pii_leakage",
        score=0.0 if findings else 1.0,
        passed=not findings,
        details="No PII detected" if not findings else f"Found: {', '.join(findings)}",
    )


def score_case(case: DatasetCase, candidate: CandidateOutput | None) -> CaseResult:
    """Score one dataset case against a candidate output.

    Args:
        case: Dataset case.
        candidate: Candidate output with matching id, or None if missing.

    Returns:
        Normalized case result.
    """
    if candidate is None:
        missing = MetricResult(
            name="candidate_present",
            score=0.0,
            passed=False,
            details="No candidate output row for dataset id",
        )
        return CaseResult(
            id=case.id,
            label=case.label,
            passed=False,
            score=0.0,
            metrics=[missing],
            failures=[missing.details],
        )

    envelope, schema_metric = _parse_envelope(candidate.actual_output)
    metrics = [schema_metric, _score_no_pii(candidate.actual_output)]
    if envelope is not None:
        metrics.extend(
            [
                _score_expected_diagram(case, envelope),
                _score_manifest_coverage(case, envelope),
                _score_notes(case, envelope),
                _score_mermaid_compiles(envelope),
            ]
        )

    failures = [metric.details for metric in metrics if not metric.passed]
    score = mean(metric.score for metric in metrics) if metrics else 0.0
    return CaseResult(
        id=case.id,
        label=case.label,
        passed=not failures,
        score=round(score, 4),
        metrics=metrics,
        failures=failures,
    )


def run_eval_suite(
    *,
    dataset_path: Path = DEFAULT_DATASET,
    outputs_path: Path,
    min_pass_cases: int = 4,
    persist: bool = True,
) -> EvalRunSummary:
    """Run the Azure architect offline eval suite.

    Args:
        dataset_path: JSONL fixture dataset.
        outputs_path: JSONL candidate output file.
        min_pass_cases: Minimum number of passing cases required for suite pass.
        persist: Whether to append the summary to
            ``data/azure_architect_eval_runs.jsonl``.

    Returns:
        Persistable eval run summary.
    """
    cases = load_dataset(dataset_path)
    candidates = load_candidate_outputs(outputs_path)
    results = [score_case(case, candidates.get(case.id)) for case in cases]
    cases_passed = sum(1 for result in results if result.passed)
    overall_score = mean(result.score for result in results) if results else 0.0
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    run_id = "azure-architect-eval-" + timestamp.replace(":", "").replace(".", "")
    summary = EvalRunSummary(
        run_id=run_id,
        timestamp=timestamp,
        dataset_path=str(dataset_path.resolve()),
        outputs_path=str(outputs_path.resolve()),
        status="PASS" if cases_passed >= min_pass_cases else "FAIL",
        cases_total=len(results),
        cases_passed=cases_passed,
        min_pass_cases=min_pass_cases,
        pass_rate=round(cases_passed / len(results), 4) if results else 0.0,
        overall_score=round(overall_score, 4),
        results=results,
    )
    if persist:
        _append_jsonl(AZURE_ARCHITECT_EVAL_RUNS_FILE, summary.model_dump(mode="json"))
    return summary


def recent_runs(limit: int = 10) -> list[EvalRunSummary]:
    """Return recent persisted Azure architect eval run summaries."""
    return [
        EvalRunSummary.model_validate(row)
        for row in _read_jsonl(AZURE_ARCHITECT_EVAL_RUNS_FILE, limit=limit)
    ]


def _print_summary(summary: EvalRunSummary) -> None:
    """Print a compact CLI summary."""
    print(
        f"{summary.status} {summary.cases_passed}/{summary.cases_total} cases "
        f"overall_score={summary.overall_score:.3f} run_id={summary.run_id}"
    )
    for result in summary.results:
        marker = "PASS" if result.passed else "FAIL"
        print(f"  {marker} {result.id:18s} score={result.score:.3f} {result.label}")
        for metric in result.metrics:
            metric_marker = "ok" if metric.passed else "bad"
            print(f"    {metric_marker:3s} {metric.name:24s} {metric.score:.3f} {metric.details}")


def _print_recent(limit: int) -> None:
    """Print recent persisted run summaries."""
    runs = recent_runs(limit=limit)
    if not runs:
        print("No persisted Azure architect eval runs.")
        return
    for run in runs:
        print(
            f"{run.timestamp} {run.status} {run.cases_passed}/{run.cases_total} "
            f"score={run.overall_score:.3f} {run.run_id}"
        )


def _parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="Run Azure architect offline evals.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--outputs", type=Path, help="Candidate outputs JSONL.")
    parser.add_argument("--min-pass-cases", type=int, default=4)
    parser.add_argument("--no-persist", action="store_true")
    parser.add_argument("--list-runs", action="store_true")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args(argv)
    if not args.list_runs and args.outputs is None:
        parser.error("--outputs is required unless --list-runs is set")
    return args


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for the eval runner."""
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    if args.list_runs:
        _print_recent(args.limit)
        return 0
    summary = run_eval_suite(
        dataset_path=args.dataset,
        outputs_path=args.outputs,
        min_pass_cases=args.min_pass_cases,
        persist=not args.no_persist,
    )
    _print_summary(summary)
    return 0 if summary.status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
