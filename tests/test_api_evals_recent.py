"""Tests for GET /api/evals/recent (S70b — wire team-portal Evals to real data).

Three assertions against a tmp_path-isolated JSONL:
  1. Empty file -> 200 + rows=[] + total=0 (honest empty state, no seed fallback).
  2. Three rows -> most-recent-first, skipped metric carries skipped=true and
     score=None, normal metrics carry expected score+passed.
  3. workload_id query filter narrows the result set; limit clamps.

Critically: we override the module-level _EVALS_JSONL_PATH on api.evaluate so
no test ever reads or writes the real data/evals.jsonl. That file is owned by
the running engine; touching it from a test would corrupt live observability.

Pytest gotcha: run with `-p no:deepeval` to dodge the deepeval plugin
teardown crash under py3.14 (project standing rule).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def evals_jsonl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A tmp evals.jsonl wired into api.evaluate via monkeypatch.

    Returns the path so individual tests can write fixture rows into it
    before hitting the endpoint.
    """
    p = tmp_path / "evals.jsonl"
    p.touch()
    # api.evaluate resolves the path at module load; override the constant
    # directly. This is safer than env-var twiddling because evaluator.py
    # captures DATA_ROOT into a different constant.
    import api.evaluate as evaluate_module
    monkeypatch.setattr(evaluate_module, "_EVALS_JSONL_PATH", p)
    return p


@pytest.fixture
def client(evals_jsonl: Path) -> TestClient:
    # evals_jsonl is requested before app construction so the monkeypatch is
    # in place when the router is imported.
    from api.evaluate import router as eval_router
    app = FastAPI()
    app.include_router(eval_router)
    return TestClient(app)


def _write_rows(path: Path, rows: list[dict]) -> None:
    """Append rows to the fixture JSONL in the given order."""
    with path.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def _row(
    trace_id: str,
    *,
    timestamp: str = "2026-05-30T12:00:00Z",
    workload_id: str = "azure-architect",
    model: str = "claude-sonnet-4-6",
) -> dict:
    """Build one realistic eval row matching evaluator._append_eval_jsonl output."""
    return {
        "trace_id": trace_id,
        "timestamp": timestamp,
        "workload_id": workload_id,
        "model": model,
        "results": {
            "answer_relevancy": {
                "score": 0.85,
                "passed": True,
                "skipped": False,
                "details": "Relevant.",
            },
            "hallucination": {
                "score": None,
                "passed": False,
                "skipped": True,
                "details": "Skipped (no context provided)",
            },
        },
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_empty_jsonl_returns_no_rows(client: TestClient) -> None:
    """Honest empty state. No seed/overlay fallback — the panel must NOT
    pretend there are evals when no agent has run yet."""
    r = client.get("/api/evals/recent")
    assert r.status_code == 200
    body = r.json()
    assert body["rows"] == []
    assert body["total"] == 0
    assert body["source"] == "data/evals.jsonl"


def test_returns_rows_most_recent_first_with_skipped_metric(
    client: TestClient, evals_jsonl: Path,
) -> None:
    """Three rows -> ordered newest first (storage._read_jsonl contract),
    skipped metric round-trips as skipped=True with score=None."""
    _write_rows(
        evals_jsonl,
        [
            _row("trace_a", timestamp="2026-05-30T10:00:00Z"),
            _row("trace_b", timestamp="2026-05-30T11:00:00Z"),
            _row("trace_c", timestamp="2026-05-30T12:00:00Z"),
        ],
    )

    r = client.get("/api/evals/recent", params={"limit": 10})
    assert r.status_code == 200
    body = r.json()

    assert body["total"] == 3
    ids = [row["trace_id"] for row in body["rows"]]
    assert ids == ["trace_c", "trace_b", "trace_a"]

    # Spot-check the metric shape on the newest row.
    metrics = body["rows"][0]["results"]
    assert metrics["answer_relevancy"]["score"] == 0.85
    assert metrics["answer_relevancy"]["passed"] is True
    assert metrics["answer_relevancy"]["skipped"] is False

    # skipped metric: canonical signal is `skipped=true`; legacy V1 mark
    # surfaces `passed=false` but the panel logic must NOT treat it as fail.
    assert metrics["hallucination"]["score"] is None
    assert metrics["hallucination"]["passed"] is False
    assert metrics["hallucination"]["skipped"] is True


def test_workload_filter_and_limit_clamp(
    client: TestClient, evals_jsonl: Path,
) -> None:
    """Query filter narrows; limit clamps post-filter."""
    _write_rows(
        evals_jsonl,
        [
            _row("trace_arch_1", workload_id="azure-architect", timestamp="2026-05-30T10:00:00Z"),
            _row("trace_other_1", workload_id="other-agent", timestamp="2026-05-30T10:30:00Z"),
            _row("trace_arch_2", workload_id="azure-architect", timestamp="2026-05-30T11:00:00Z"),
            _row("trace_arch_3", workload_id="azure-architect", timestamp="2026-05-30T12:00:00Z"),
        ],
    )

    # Filter to azure-architect, limit 2 -> two newest matching rows.
    r = client.get(
        "/api/evals/recent",
        params={"workload_id": "azure-architect", "limit": 2},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    ids = [row["trace_id"] for row in body["rows"]]
    assert ids == ["trace_arch_3", "trace_arch_2"]
    # The 'other-agent' row must NOT leak into the filtered result.
    assert all(row["workload_id"] == "azure-architect" for row in body["rows"])
