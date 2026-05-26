"""File-based persistent storage for runs, evaluations, and historical data."""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Any
import threading

# Thread-safe lock for file writes
_storage_lock = threading.Lock()

# Storage directory
import os as _os
STORAGE_DIR = Path(_os.environ.get("DATA_ROOT") or (Path(__file__).parent / "data"))
STORAGE_DIR.mkdir(parents=True, exist_ok=True)

RUNS_FILE = STORAGE_DIR / "runs.jsonl"
BATCH_FILE = STORAGE_DIR / "batches.jsonl"
ADVERSARIAL_FILE = STORAGE_DIR / "adversarial.jsonl"


def _append_jsonl(file_path: Path, record: dict) -> None:
    """Thread-safe append to JSONL file."""
    with _storage_lock:
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")


def _read_jsonl(file_path: Path, limit: Optional[int] = None) -> list[dict]:
    """Read records from JSONL file. Most recent first."""
    if not file_path.exists():
        return []

    records = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    # Reverse for most-recent-first
    records.reverse()

    if limit:
        records = records[:limit]

    return records


def save_run(run_data: dict) -> None:
    """Persist a run to disk."""
    if "timestamp" not in run_data:
        run_data["timestamp"] = datetime.utcnow().isoformat() + "Z"
    _append_jsonl(RUNS_FILE, run_data)


def get_runs(
    limit: int = 100,
    domain: Optional[str] = None,
    model: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> list[dict]:
    """Get historical runs with optional filters."""
    runs = _read_jsonl(RUNS_FILE, limit=None)

    # Apply filters
    if domain:
        runs = [r for r in runs if r.get("domain", "").lower() == domain.lower()]

    if model:
        runs = [r for r in runs if r.get("model", "") == model]

    if start_date:
        runs = [
            r for r in runs
            if datetime.fromisoformat(r["timestamp"].replace("Z", "")) >= start_date
        ]

    if end_date:
        runs = [
            r for r in runs
            if datetime.fromisoformat(r["timestamp"].replace("Z", "")) <= end_date
        ]

    return runs[:limit]


def get_run_by_id(run_id: str) -> Optional[dict]:
    """Get a specific run by ID."""
    runs = _read_jsonl(RUNS_FILE, limit=None)
    for run in runs:
        if run.get("id") == run_id or run.get("trace_id") == run_id:
            return run
    return None


def calculate_analytics(days: int = 30) -> dict:
    """Calculate analytics over recent period."""
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days)

    runs = get_runs(limit=10000, start_date=start_date, end_date=end_date)

    if not runs:
        return {
            "total_runs": 0,
            "by_domain": {},
            "by_model": {},
            "by_risk": {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0},
            "trends": [],
            "failure_types": {},
            "average_latency_ms": 0,
            "total_tokens": 0,
        }

    # Aggregations
    by_domain = {}
    by_model = {}
    by_risk = {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0}
    failure_types = {}
    total_latency = 0
    total_tokens = 0

    for run in runs:
        # Domain stats
        domain = run.get("domain", "Unknown")
        if domain not in by_domain:
            by_domain[domain] = {"total": 0, "pass": 0, "fail": 0}
        by_domain[domain]["total"] += 1

        # Model stats
        model = run.get("model", "Unknown")
        if model not in by_model:
            by_model[model] = {"total": 0, "pass": 0, "fail": 0, "avg_latency": 0}
        by_model[model]["total"] += 1

        # Risk distribution
        eval_scores = run.get("eval_scores", {})
        fail_count = sum(
            1 for m in eval_scores.values()
            if m.get("passed") is False and not m.get("skipped", False)
        )

        if fail_count == 0:
            risk = "LOW"
            by_domain[domain]["pass"] += 1
            by_model[model]["pass"] += 1
        elif fail_count <= 2:
            risk = "MEDIUM"
            by_domain[domain]["fail"] += 1
            by_model[model]["fail"] += 1
        elif fail_count <= 4:
            risk = "HIGH"
            by_domain[domain]["fail"] += 1
            by_model[model]["fail"] += 1
        else:
            risk = "CRITICAL"
            by_domain[domain]["fail"] += 1
            by_model[model]["fail"] += 1
        by_risk[risk] += 1

        # Failure types
        for metric, result in eval_scores.items():
            if result.get("passed") is False and not result.get("skipped", False):
                failure_types[metric] = failure_types.get(metric, 0) + 1

        # Latency and tokens
        total_latency += run.get("latency_ms", 0)
        total_tokens += run.get("tokens_used", 0)

    # Calculate model average latency
    for model_name in by_model:
        model_runs = [r for r in runs if r.get("model") == model_name]
        if model_runs:
            avg = sum(r.get("latency_ms", 0) for r in model_runs) / len(model_runs)
            by_model[model_name]["avg_latency"] = int(avg)

    # Daily trend
    trends = _calculate_daily_trends(runs, days)

    return {
        "total_runs": len(runs),
        "period_days": days,
        "by_domain": by_domain,
        "by_model": by_model,
        "by_risk": by_risk,
        "trends": trends,
        "failure_types": dict(sorted(failure_types.items(), key=lambda x: -x[1])),
        "average_latency_ms": int(total_latency / len(runs)) if runs else 0,
        "total_tokens": total_tokens,
        "pass_rate": _calculate_pass_rate(runs),
    }


def _calculate_pass_rate(runs: list[dict]) -> float:
    """Calculate overall pass rate."""
    if not runs:
        return 0.0
    passes = 0
    for run in runs:
        eval_scores = run.get("eval_scores", {})
        fail_count = sum(
            1 for m in eval_scores.values()
            if m.get("passed") is False and not m.get("skipped", False)
        )
        if fail_count == 0:
            passes += 1
    return round(passes / len(runs) * 100, 1)


def _calculate_daily_trends(runs: list[dict], days: int) -> list[dict]:
    """Calculate daily pass/fail trends."""
    trends_by_day = {}

    for run in runs:
        try:
            ts = run["timestamp"].replace("Z", "")
            day = ts.split("T")[0]  # YYYY-MM-DD
        except (KeyError, AttributeError):
            continue

        if day not in trends_by_day:
            trends_by_day[day] = {"date": day, "total": 0, "pass": 0, "fail": 0}

        trends_by_day[day]["total"] += 1

        eval_scores = run.get("eval_scores", {})
        fail_count = sum(
            1 for m in eval_scores.values()
            if m.get("passed") is False and not m.get("skipped", False)
        )
        if fail_count == 0:
            trends_by_day[day]["pass"] += 1
        else:
            trends_by_day[day]["fail"] += 1

    # Sort by date
    sorted_trends = sorted(trends_by_day.values(), key=lambda x: x["date"])
    return sorted_trends


def save_batch(batch_data: dict) -> None:
    """Save a batch evaluation record."""
    if "timestamp" not in batch_data:
        batch_data["timestamp"] = datetime.utcnow().isoformat() + "Z"
    _append_jsonl(BATCH_FILE, batch_data)


def get_batches(limit: int = 50) -> list[dict]:
    """Get recent batch runs."""
    return _read_jsonl(BATCH_FILE, limit=limit)


def save_adversarial_result(result: dict) -> None:
    """Save adversarial test result."""
    if "timestamp" not in result:
        result["timestamp"] = datetime.utcnow().isoformat() + "Z"
    _append_jsonl(ADVERSARIAL_FILE, result)


def get_adversarial_results(limit: int = 50) -> list[dict]:
    """Get recent adversarial test results."""
    return _read_jsonl(ADVERSARIAL_FILE, limit=limit)


def export_runs_csv(
    domain: Optional[str] = None,
    model: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> str:
    """Export runs as CSV string."""
    runs = get_runs(limit=100000, domain=domain, model=model, start_date=start_date, end_date=end_date)

    if not runs:
        return "timestamp,model,domain,trace_id,latency_ms,tokens_used,risk_level\n"

    lines = ["timestamp,model,domain,trace_id,latency_ms,tokens_used,risk_level,pass_count,fail_count"]
    for run in runs:
        eval_scores = run.get("eval_scores", {})
        fail_count = sum(
            1 for m in eval_scores.values()
            if m.get("passed") is False and not m.get("skipped", False)
        )
        pass_count = sum(
            1 for m in eval_scores.values()
            if m.get("passed") is True
        )

        if fail_count == 0:
            risk = "LOW"
        elif fail_count <= 2:
            risk = "MEDIUM"
        elif fail_count <= 4:
            risk = "HIGH"
        else:
            risk = "CRITICAL"

        lines.append(
            f'{run.get("timestamp", "")},{run.get("model", "")},{run.get("domain", "")},'
            f'{run.get("trace_id", "")},{run.get("latency_ms", 0)},{run.get("tokens_used", 0)},'
            f'{risk},{pass_count},{fail_count}'
        )

    return "\n".join(lines)


def export_runs_json(
    domain: Optional[str] = None,
    model: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> str:
    """Export runs as JSON string."""
    runs = get_runs(limit=100000, domain=domain, model=model, start_date=start_date, end_date=end_date)
    return json.dumps({"runs": runs, "count": len(runs)}, indent=2, default=str)


if __name__ == "__main__":
    # Test
    test_run = {
        "id": "test-1",
        "model": "claude-sonnet-4-6",
        "domain": "Healthcare",
        "trace_id": "trace-123",
        "latency_ms": 2500,
        "tokens_used": 450,
        "eval_scores": {
            "faithfulness": {"score": 0.92, "passed": True, "skipped": False},
            "pii_leakage": {"score": 0.0, "passed": True, "skipped": False},
        }
    }
    save_run(test_run)

    runs = get_runs(limit=10)
    print(f"✓ Stored runs: {len(runs)}")

    analytics = calculate_analytics(days=30)
    print(f"✓ Analytics: {analytics['total_runs']} runs, {analytics['pass_rate']}% pass rate")

    csv = export_runs_csv()
    print(f"✓ CSV export: {len(csv.splitlines())} lines")
