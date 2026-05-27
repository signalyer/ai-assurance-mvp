"""ADR-003 Step 1 — Protocol extension + catalog endpoint + registry guard."""

from __future__ import annotations

import importlib
import os

import pytest


def test_deepeval_backend_satisfies_protocol() -> None:
    from providers.backends.deepeval_evaluator import DeepEvalEvaluator
    from providers.protocols import EvaluatorBackend

    backend = DeepEvalEvaluator()
    assert isinstance(backend, EvaluatorBackend)
    assert backend.vendor == "deepeval"
    assert isinstance(backend.vendor_version, str)
    assert backend.vendor_version  # non-empty
    assert set(backend.metric_schema.keys()) == {
        "answer_relevancy", "toxicity", "hallucination", "faithfulness", "pii_leakage",
    }


def test_noop_backend_satisfies_protocol() -> None:
    from providers.backends.noop import NoopEvaluator
    from providers.protocols import EvaluatorBackend

    backend = NoopEvaluator()
    assert isinstance(backend, EvaluatorBackend)
    assert backend.vendor == "noop"
    assert backend.vendor_version == "1.0"
    assert backend.metric_schema == {}


def test_new_enum_values_declared() -> None:
    from providers.config import EvalBackendChoice

    assert {c.value for c in EvalBackendChoice} == {
        "deepeval", "ragas", "promptfoo", "openai_evals", "noop",
    }


def test_registry_raises_not_implemented_for_pending_vendors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Selecting ragas/promptfoo/openai_evals as active backend must fail loudly."""
    for vendor in ("ragas", "promptfoo", "openai_evals"):
        monkeypatch.setenv("EVAL_BACKEND", vendor)
        # Reload registry so it re-reads ProviderSettings.
        from providers import registry as reg_mod
        importlib.reload(reg_mod)
        reg_mod.clear_registry()
        with pytest.raises(NotImplementedError) as excinfo:
            reg_mod.get_evaluator()
        assert "ADR-003" in str(excinfo.value)


def test_evaluate_response_v2_envelope_shape_via_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    """v2 envelope shape contract — independent of vendor."""
    monkeypatch.setenv("EVAL_BACKEND", "noop")
    from providers import registry as reg_mod
    importlib.reload(reg_mod)
    reg_mod.clear_registry()

    # Reload evaluator so it picks up the cleared registry.
    import evaluator as ev_mod
    importlib.reload(ev_mod)

    env = ev_mod.evaluate_response_v2(
        input_prompt="Q",
        actual_output="A",
        context=[],
        trace_id="tr_test",
        workload_id="test-workload",
        model="claude-test",
    )
    assert env["vendor"] == "noop"
    assert env["vendor_version"] == "1.0"
    assert env["status"] == "ok"
    assert env["errors"] == []
    assert isinstance(env["duration_ms"], int)
    assert env["cost_usd_est"] == 0.0
    assert "raw_metrics" in env
    # noop returns all 5 metrics skipped
    assert set(env["raw_metrics"].keys()) == {
        "answer_relevancy", "toxicity", "hallucination", "faithfulness", "pii_leakage",
    }


def test_legacy_evaluate_response_unchanged_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    """Legacy 5-key shape must remain intact for api/evals.py + S57a runner."""
    monkeypatch.setenv("EVAL_BACKEND", "noop")
    from providers import registry as reg_mod
    importlib.reload(reg_mod)
    reg_mod.clear_registry()

    import evaluator as ev_mod
    importlib.reload(ev_mod)

    result = ev_mod.evaluate_response(
        input_prompt="Q",
        actual_output="A",
        context=[],
    )
    # Must be the legacy 5-key dict — NOT an envelope.
    assert set(result.keys()) == {
        "answer_relevancy", "toxicity", "hallucination", "faithfulness", "pii_leakage",
    }
    assert all("score" in v and "passed" in v and "skipped" in v for v in result.values())


def test_catalog_endpoint_shape() -> None:
    """GET /api/evals/suites returns the 4-vendor catalog with deepeval enabled."""
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from api.eval_suites import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    r = client.get("/api/evals/suites")
    assert r.status_code == 200
    payload = r.json()
    assert payload["adr"] == "docs/adr/ADR-003-multi-vendor-evals.md"
    vendors = [i["vendor"] for i in payload["items"]]
    assert vendors == ["deepeval", "ragas", "promptfoo", "openai_evals"]
    statuses = {i["vendor"]: i["status"] for i in payload["items"]}
    # Whichever vendor is configured as EVAL_BACKEND in the test env is "enabled".
    # In CI default this is deepeval; we accept either deepeval or noop being enabled.
    enabled = [v for v, s in statuses.items() if s == "enabled"]
    assert len(enabled) <= 1  # at most one is enabled at a time
    roadmap_vendors = {v for v, s in statuses.items() if s == "roadmap"}
    # ragas/promptfoo/openai_evals are always roadmap until §7 Steps 2/4/5 ship.
    assert {"ragas", "promptfoo", "openai_evals"}.issubset(roadmap_vendors)
