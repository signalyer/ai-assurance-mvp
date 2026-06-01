"""Eval runner for the vendor_risk agent (Phase 4 — skeleton).

S82c scope: harness ONLY. The agent body (`_run_vendor_risk_inner`) does
not exist yet — that lands in S82d. This runner exists so we can prove
the eval scaffolding (datasets, metrics, thresholds, persistence) is
wired correctly before any agent code is written.

Modes:
    --null-baseline      Skip the inner call; emit metric_columns=null per
                         case. Proves the harness shape against zero agent
                         code. THIS is what S82c ships green.
    --outputs <path>     (S82d+) Score pre-computed candidate output rows
                         from a JSONL file (id + actual_output per row),
                         matching the azure-architect pattern.
    (default, S82d+)     Call `_run_vendor_risk_inner` per case. Will raise
                         ImportError until S82d wires the agent body.

Usage:
    python -m agents.vendor_risk.eval.run_eval --null-baseline
    python -m agents.vendor_risk.eval.run_eval --null-baseline --datasets ext
    python -m agents.vendor_risk.eval.run_eval --outputs path/to/outputs.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

EVAL_DIR = Path(__file__).resolve().parent
REPO_ROOT = EVAL_DIR.parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agents.vendor_risk.eval.metrics import (  # noqa: E402
    METRIC_NAMES,
    MetricResult,
    score_all,
)
from storage import STORAGE_DIR, _append_jsonl  # noqa: E402

DATASETS: dict[str, Path] = {
    "ext": EVAL_DIR / "dataset-external.jsonl",
    "int": EVAL_DIR / "dataset-internal.jsonl",
}
THRESHOLDS_PATH = EVAL_DIR / "thresholds.json"
VENDOR_RISK_EVAL_RUNS_FILE = STORAGE_DIR / "vendor_risk_eval_runs.jsonl"


class CaseResult(BaseModel):
    """Eval result for one dataset case."""

    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    system: str
    category: str
    passed: Optional[bool] = None
    overall_score: Optional[float] = None
    metrics: list[MetricResult] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)


class EvalRunSummary(BaseModel):
    """Persisted summary for one vendor_risk eval run."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    timestamp: str
    mode: str
    datasets: list[str]
    cases_total: int
    cases_passed: int
    cases_null: int
    status: str
    pass_rate: Optional[float] = None
    results: list[CaseResult]


def load_dataset(path: Path) -> list[dict]:
    """Load a dataset JSONL file as a list of case dicts in file order."""
    cases: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            cases.append(json.loads(line))
    return cases


def load_thresholds(path: Path = THRESHOLDS_PATH) -> dict:
    """Load and shape-validate the thresholds file."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    metrics = payload.get("metrics", {})
    missing = [name for name in METRIC_NAMES if name not in metrics]
    if missing:
        raise ValueError(f"thresholds.json missing metrics: {missing}")
    return payload


def score_case(case: dict, output: Optional[dict]) -> CaseResult:
    """Score one dataset case. When output is None, every metric is null."""
    metrics = score_all(case, output)
    if output is None:
        return CaseResult(
            id=case["id"],
            label=case.get("label", ""),
            system=case.get("system", ""),
            category=case.get("category", ""),
            passed=None,
            overall_score=None,
            metrics=metrics,
            failures=[],
        )
    scored = [m for m in metrics if m.score is not None]
    overall = mean(m.score for m in scored) if scored else 0.0
    failures = [m.details for m in metrics if m.passed is False]
    return CaseResult(
        id=case["id"],
        label=case.get("label", ""),
        system=case.get("system", ""),
        category=case.get("category", ""),
        passed=not failures,
        overall_score=round(overall, 4),
        metrics=metrics,
        failures=failures,
    )


def run_eval_suite(
    *,
    datasets: Optional[list[str]] = None,
    null_baseline: bool = False,
    outputs_path: Optional[Path] = None,
    persist: bool = True,
) -> EvalRunSummary:
    """Run the vendor_risk eval suite.

    Args:
        datasets: Subset of {"ext", "int"} to run. None = both.
        null_baseline: If True, skip the agent body and emit null metrics.
        outputs_path: Optional candidate outputs JSONL (S82d+). One row per
            case: ``{"id": "<case id>", "actual_output": {...}}``.
        persist: Whether to append the summary to
            ``data/vendor_risk_eval_runs.jsonl``.

    Returns:
        Persistable eval run summary.
    """
    selected = datasets or list(DATASETS.keys())
    cases: list[dict] = []
    for key in selected:
        cases.extend(load_dataset(DATASETS[key]))

    candidate_outputs: dict[str, dict] = {}
    if outputs_path is not None:
        with outputs_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                candidate_outputs[row["id"]] = row.get("actual_output") or row

    results: list[CaseResult] = []
    for case in cases:
        output: Optional[dict]
        if null_baseline:
            output = None
        elif candidate_outputs:
            output = candidate_outputs.get(case["id"])
        else:
            output = _invoke_agent_or_none(case)
        results.append(score_case(case, output))

    cases_null = sum(1 for r in results if r.passed is None)
    cases_passed = sum(1 for r in results if r.passed is True)
    if null_baseline:
        status = "NULL_BASELINE"
        pass_rate: Optional[float] = None
    else:
        status = "PASS" if cases_passed == len(results) and results else "FAIL"
        pass_rate = round(cases_passed / len(results), 4) if results else 0.0

    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    run_id = "vendor-risk-eval-" + timestamp.replace(":", "").replace(".", "")
    summary = EvalRunSummary(
        run_id=run_id,
        timestamp=timestamp,
        mode="null-baseline" if null_baseline
              else ("outputs-file" if candidate_outputs else "live"),
        datasets=selected,
        cases_total=len(results),
        cases_passed=cases_passed,
        cases_null=cases_null,
        status=status,
        pass_rate=pass_rate,
        results=results,
    )
    if persist:
        _append_jsonl(VENDOR_RISK_EVAL_RUNS_FILE, summary.model_dump(mode="json"))
    return summary


def _invoke_agent_or_none(case: dict) -> Optional[dict]:
    """Call the inner agent body if it exists; else return None.

    The body lands in S82d. Until then, this function returns None and
    the runner falls back to null-baseline rows for that case.
    """
    try:
        from agents.vendor_risk.agent import _run_vendor_risk_inner  # type: ignore
    except ImportError:
        return None
    return _run_vendor_risk_inner(case)  # pragma: no cover — S82d wires this


def _print_summary(summary: EvalRunSummary) -> None:
    """Compact CLI summary."""
    print(
        f"{summary.status} mode={summary.mode} cases={summary.cases_total} "
        f"passed={summary.cases_passed} null={summary.cases_null} "
        f"run_id={summary.run_id}"
    )
    for result in summary.results:
        marker = (
            "NULL" if result.passed is None
            else ("PASS" if result.passed else "FAIL")
        )
        score = "—" if result.overall_score is None else f"{result.overall_score:.3f}"
        print(f"  {marker} {result.id:32s} score={score} {result.label}")
        for metric in result.metrics:
            score_s = "—" if metric.score is None else f"{metric.score:.3f}"
            print(f"      {metric.name:36s} {score_s}  {metric.details}")


def _parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="Run vendor_risk offline evals.")
    parser.add_argument(
        "--null-baseline",
        action="store_true",
        help="Skip agent invocation; emit null metrics for every case. "
             "Proves the harness scaffolding works before the agent body exists.",
    )
    parser.add_argument(
        "--datasets",
        nargs="+",
        choices=list(DATASETS.keys()),
        help="Datasets to run (ext|int). Default: both.",
    )
    parser.add_argument(
        "--outputs",
        type=Path,
        help="Pre-computed candidate outputs JSONL (S82d+).",
    )
    parser.add_argument("--no-persist", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for the eval runner."""
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    load_thresholds()  # Shape-validate; raises if drift.
    summary = run_eval_suite(
        datasets=args.datasets,
        null_baseline=args.null_baseline,
        outputs_path=args.outputs,
        persist=not args.no_persist,
    )
    _print_summary(summary)
    if summary.status == "NULL_BASELINE":
        return 0
    return 0 if summary.status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
