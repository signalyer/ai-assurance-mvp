"""Tests for middleware.api_version_alias.

Asserts that /api/v1/<rest> returns identical body+status to /api/<rest> for
a representative set of read endpoints across multiple routers.

Per docs/plans/SESSION-13-api-typing-audit.md §1.5 + §8 risk row 7.
"""
from __future__ import annotations

import os

# Ensure backends noop'd BEFORE importing dashboard
for _k, _v in {
    "EVAL_BACKEND": "noop",
    "SCRUBBER_BACKEND": "regex",
    "TRACER_BACKEND": "noop",
    "MEMORY_BACKEND": "noop",
    "RAG_BACKEND": "noop",
    "POLICY_BACKEND": "noop",
    "SL_OPENAPI_STRICT": "false",   # don't fail test on artifact drift
}.items():
    os.environ.setdefault(_k, _v)

import pytest
from fastapi.testclient import TestClient

from dashboard import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


# (path-without-prefix, fields-to-ignore-in-comparison-because-timestamp-sensitive)
PARITY_ENDPOINTS = [
    ("/api/grc/kpis", {"generated_at"}),
    ("/api/grc/next-actions", set()),
    ("/api/grc/release-gates/rules", set()),
    ("/api/grc/governance/nist-ai-rmf", set()),
    ("/api/grc/security/owasp-llm", set()),
    ("/api/grc/policies", set()),
    ("/api/grc/runtime/v2/_meta", set()),
    ("/api/grc/runtime/v2/connectors", {"latest_ts"}),
    ("/api/audit/verify", set()),
    ("/api/right-to-forget", set()),
    ("/api/frameworks/matrix", set()),
]


@pytest.mark.parametrize("path,ignore_fields", PARITY_ENDPOINTS)
def test_v1_alias_returns_identical_body(client, path: str, ignore_fields: set[str]) -> None:
    """/api/v1/foo and /api/foo must return identical body + status.

    Timestamp-sensitive fields (generated_at, latest_ts) are stripped before
    comparison since two calls a few ms apart will produce different values.
    """
    v1_path = "/api/v1/" + path[len("/api/"):]

    r_orig = client.get(path)
    r_alias = client.get(v1_path)

    assert r_orig.status_code == r_alias.status_code, (
        f"status_code differs: {path}={r_orig.status_code} {v1_path}={r_alias.status_code}"
    )

    if r_orig.headers.get("content-type", "").startswith("application/json"):
        b_orig = _strip(r_orig.json(), ignore_fields)
        b_alias = _strip(r_alias.json(), ignore_fields)
        assert b_orig == b_alias, f"body differs at {path} vs {v1_path}"


def _strip(value: object, fields: set[str]) -> object:
    """Recursively remove fields from a JSON value."""
    if not fields:
        return value
    if isinstance(value, dict):
        return {k: _strip(v, fields) for k, v in value.items() if k not in fields}
    if isinstance(value, list):
        return [_strip(v, fields) for v in value]
    return value


def test_openapi_does_not_advertise_v1_paths(client) -> None:
    """The alias is incoming-only -- /api/v1/* must not appear in /openapi.json.

    Per audit §1.5: duplicating routes in OpenAPI would double Schemathesis
    runtime and confuse codegen. The middleware rewrites at request time;
    the spec stays single-sourced on /api/*.
    """
    spec = app.openapi()
    v1_paths = [p for p in spec["paths"] if p.startswith("/api/v1/")]
    assert v1_paths == [], (
        f"OpenAPI advertises {len(v1_paths)} /api/v1/* paths; alias should be "
        f"middleware-only, not duplicated in routes. First few: {v1_paths[:3]}"
    )
