"""V2 data-mode filter on release-gates /systems endpoint.

S54 STEP 1 — verifies that X-Data-Mode: v2 hides seed systems from the
release-gates index, so the SPA's V2 empty-state copy renders until a
real-mode system is registered. V1 (default) keeps the legacy behavior.
"""
from __future__ import annotations

import os

for _k, _v in {
    "EVAL_BACKEND": "noop",
    "SCRUBBER_BACKEND": "regex",
    "TRACER_BACKEND": "noop",
    "MEMORY_BACKEND": "noop",
    "RAG_BACKEND": "noop",
    "POLICY_BACKEND": "noop",
    "SL_OPENAPI_STRICT": "false",
}.items():
    os.environ.setdefault(_k, _v)

import pytest
from fastapi.testclient import TestClient

from dashboard import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def test_release_gates_v1_returns_seed_systems(client: TestClient) -> None:
    """V1 (default) — seed systems remain visible."""
    r = client.get("/api/grc/release-gates/v2/systems")
    assert r.status_code == 200
    body = r.json()
    assert "systems" in body
    assert len(body["systems"]) > 0, "V1 mode must expose seed systems"


def test_release_gates_v2_hides_seed_systems(client: TestClient) -> None:
    """V2 — seed-sourced systems are filtered out; empty until a real system is registered."""
    r = client.get(
        "/api/grc/release-gates/v2/systems",
        headers={"X-Data-Mode": "v2"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body == {"systems": []}, (
        "V2 mode must return an empty systems list when only seed systems exist"
    )
