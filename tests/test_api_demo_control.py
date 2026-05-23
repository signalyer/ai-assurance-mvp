"""Tests for api/demo_control.py — Demo Control Panel.

Test-first contract: this file is written before the implementation.
Five tests as specified:
1. test_unauthenticated_returns_401_or_403
2. test_authenticated_non_demo_operator_role_returns_403
3. test_list_scenarios_returns_six_entries
4. test_run_valid_scenario_emits_event_to_jsonl
5. test_run_invalid_scenario_returns_404

Auth model: AUTH_ENABLED=false (dev mode). require_role() reads X-Role header
and raises 403 when the header is present but not in allowed_roles.
No X-Role header → no check → passes in dev mode.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixture: isolated app with only the demo_control router
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client() -> TestClient:
    """Build a minimal FastAPI app mounting api.demo_control router.

    We mount it in isolation (not the full dashboard) so we do not need
    Postgres, Langfuse, or any other external service to run the RBAC and
    scenario-list tests. The run-scenario test calls real backends that
    are available in the dev environment.
    """
    from api.demo_control import router as dc_router

    app = FastAPI()
    app.include_router(dc_router)
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Test 1 — unauthenticated → 401 or 403
# ---------------------------------------------------------------------------

class TestUnauthenticated:
    """Verify that a caller with an explicit non-permitted role is rejected."""

    def test_unauthenticated_returns_403_or_401(self, client: TestClient) -> None:
        """X-Role header set to a role that is not demo-operator or ciso → 403.

        When AUTH_ENABLED=false, require_role() uses the X-Role header.
        Supplying a disallowed role must yield 403.
        """
        response = client.get(
            "/api/demo-control/scenarios",
            headers={"X-Role": "readonly"},
        )
        assert response.status_code in (401, 403), (
            f"Expected 401 or 403 for disallowed role, got {response.status_code}"
        )


# ---------------------------------------------------------------------------
# Test 2 — wrong role → 403
# ---------------------------------------------------------------------------

class TestWrongRole:
    def test_authenticated_non_demo_operator_role_returns_403(
        self, client: TestClient
    ) -> None:
        """A role that exists but is not demo-operator or ciso must be rejected."""
        response = client.get(
            "/api/demo-control/scenarios",
            headers={"X-Role": "engineer"},
        )
        assert response.status_code == 403, (
            f"Expected 403 for 'engineer' role, got {response.status_code}"
        )


# ---------------------------------------------------------------------------
# Test 3 — valid role → 6 scenarios
# ---------------------------------------------------------------------------

class TestListScenarios:
    def test_list_scenarios_returns_six_entries(
        self, client: TestClient
    ) -> None:
        """GET /api/demo-control/scenarios with demo-operator role → list of 6."""
        response = client.get(
            "/api/demo-control/scenarios",
            headers={"X-Role": "demo-operator"},
        )
        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}: {response.text}"
        )
        body = response.json()
        assert "scenarios" in body, f"Missing 'scenarios' key: {body}"
        scenarios = body["scenarios"]
        assert len(scenarios) == 6, (
            f"Expected 6 scenarios, got {len(scenarios)}: {scenarios}"
        )
        # Verify each entry has required keys
        required_keys = {"id", "title", "narration_url", "expected_duration_sec", "brief"}
        for sc in scenarios:
            missing = required_keys - sc.keys()
            assert not missing, f"Scenario {sc.get('id')} missing keys: {missing}"

    def test_known_scenario_ids_present(self, client: TestClient) -> None:
        """All 6 canonical scenario IDs must be present."""
        response = client.get(
            "/api/demo-control/scenarios",
            headers={"X-Role": "ciso"},
        )
        assert response.status_code == 200
        ids = {sc["id"] for sc in response.json()["scenarios"]}
        expected = {
            "pii-pipeline-live",
            "gate-failure-recovery",
            "reusable-agent-upgrade",
            "rtf-cascade",
            "evals-degradation",
            "framework-coverage-export",
        }
        assert ids == expected, f"ID mismatch. Got: {ids}"


# ---------------------------------------------------------------------------
# Test 4 — run valid scenario → 202 + events.jsonl entry
# ---------------------------------------------------------------------------

class TestRunScenario:
    def test_run_valid_scenario_emits_event_to_jsonl(
        self, client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """POST /api/demo-control/run/pii-pipeline-live → 202.

        Verify a demo_scenario_run event is appended to events.jsonl with the
        correct structure.
        """
        # Point the demo_control module's EVENTS_FILE at a temp file
        import api.demo_control as dc_mod
        import storage

        events_file = tmp_path / "events.jsonl"
        monkeypatch.setattr(dc_mod, "DEMO_EVENTS_FILE", events_file)

        response = client.post(
            "/api/demo-control/run/pii-pipeline-live",
            headers={"X-Role": "demo-operator"},
        )
        assert response.status_code == 202, (
            f"Expected 202, got {response.status_code}: {response.text}"
        )
        body = response.json()
        assert "run_id" in body, f"Missing run_id in response: {body}"
        assert "status_url" in body, f"Missing status_url in response: {body}"

        run_id = body["run_id"]

        # Verify the event was written to JSONL
        assert events_file.exists(), "events.jsonl was not created"
        lines = [
            json.loads(ln)
            for ln in events_file.read_text(encoding="utf-8").splitlines()
            if ln.strip()
        ]
        matching = [
            ev for ev in lines
            if ev.get("event_type") == "demo_scenario_run"
            and ev.get("run_id") == run_id
        ]
        assert matching, (
            f"No demo_scenario_run event with run_id={run_id} found in JSONL. "
            f"Events: {lines}"
        )
        event = matching[0]
        assert event.get("scenario_id") == "pii-pipeline-live"
        assert "started_at" in event


# ---------------------------------------------------------------------------
# Test 5 — invalid scenario → 404
# ---------------------------------------------------------------------------

class TestInvalidScenario:
    def test_run_invalid_scenario_returns_404(
        self, client: TestClient
    ) -> None:
        """POST /api/demo-control/run/does-not-exist → 404."""
        response = client.post(
            "/api/demo-control/run/does-not-exist",
            headers={"X-Role": "demo-operator"},
        )
        assert response.status_code == 404, (
            f"Expected 404 for unknown scenario, got {response.status_code}: {response.text}"
        )
