"""Tests for Session 10 observability layer.

Covers:
- Counter increment semantics via prometheus_client in-process registry.
- init_app_insights no-op and bogus-string paths.
- RequestContextMiddleware stamps X-Request-Id header.
- GET /api/metrics access control (disabled / wrong token / correct token).
- Idempotent counter registration across module reloads.
- Counter no-op behaviour when prometheus_client is absent (sys.modules patch).
"""
from __future__ import annotations

import importlib
import os
import sys
import types
from typing import Generator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_sample(metric_name: str, labels: dict | None = None) -> float | None:
    """Return the current value of a Prometheus counter sample or None.

    Searches by *sample* name (e.g. ``scrub_pii_detected_total``) because
    prometheus_client stores the metric under the base name
    (``scrub_pii_detected``) while the sample carries the ``_total`` suffix.
    """
    try:
        from prometheus_client import REGISTRY

        labels = labels or {}
        for metric in REGISTRY.collect():
            for sample in metric.samples:
                if sample.name == metric_name and sample.labels == labels:
                    return sample.value
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Counter increment tests
# ---------------------------------------------------------------------------

class TestCounterIncrements:
    """Verify that public counter functions actually move the registry value."""

    def test_record_scrub_increments(self) -> None:
        """record_scrub should add detected_count to scrub_pii_detected_total."""
        from observability import counters

        before = _get_sample("scrub_pii_detected_total") or 0.0
        counters.record_scrub(3)
        after = _get_sample("scrub_pii_detected_total") or 0.0
        assert after == before + 3

    def test_record_scrub_zero_is_safe(self) -> None:
        """record_scrub(0) must not raise and must not decrement."""
        from observability import counters

        before = _get_sample("scrub_pii_detected_total") or 0.0
        counters.record_scrub(0)
        after = _get_sample("scrub_pii_detected_total") or 0.0
        assert after == before

    def test_record_eval_failure_increments(self) -> None:
        from observability import counters

        before = _get_sample("eval_failure_total") or 0.0
        counters.record_eval_failure()
        after = _get_sample("eval_failure_total") or 0.0
        assert after == before + 1

    def test_record_policy_deny_increments(self) -> None:
        from observability import counters

        before = _get_sample("policy_deny_total") or 0.0
        counters.record_policy_deny()
        after = _get_sample("policy_deny_total") or 0.0
        assert after == before + 1

    def test_record_pii_leak_increments(self) -> None:
        from observability import counters

        before = _get_sample("pii_leak_attempt_total") or 0.0
        counters.record_pii_leak()
        after = _get_sample("pii_leak_attempt_total") or 0.0
        assert after == before + 1

    def test_record_opa_unreachable_increments(self) -> None:
        from observability import counters

        before = _get_sample("opa_unreachable_total") or 0.0
        counters.record_opa_unreachable()
        after = _get_sample("opa_unreachable_total") or 0.0
        assert after == before + 1

    def test_record_vault_error_increments(self) -> None:
        from observability import counters

        before = _get_sample("vault_error_total") or 0.0
        counters.record_vault_error()
        after = _get_sample("vault_error_total") or 0.0
        assert after == before + 1

    def test_record_audit_chain_break_increments(self) -> None:
        from observability import counters

        before = _get_sample("audit_chain_break_total") or 0.0
        counters.record_audit_chain_break()
        after = _get_sample("audit_chain_break_total") or 0.0
        assert after == before + 1

    def test_record_rtf_cascade_increments_with_label(self) -> None:
        from observability import counters

        before = _get_sample("rtf_cascade_total", {"status": "COMPLETED"}) or 0.0
        counters.record_rtf_cascade("COMPLETED")
        after = _get_sample("rtf_cascade_total", {"status": "COMPLETED"}) or 0.0
        assert after == before + 1

    def test_record_rtf_cascade_partial_failure_label(self) -> None:
        from observability import counters

        before = _get_sample("rtf_cascade_total", {"status": "PARTIAL_FAILURE"}) or 0.0
        counters.record_rtf_cascade("PARTIAL_FAILURE")
        after = _get_sample("rtf_cascade_total", {"status": "PARTIAL_FAILURE"}) or 0.0
        assert after == before + 1


# ---------------------------------------------------------------------------
# App Insights init tests
# ---------------------------------------------------------------------------

class TestAppInsightsInit:
    """init_app_insights must never raise regardless of input quality."""

    def setup_method(self) -> None:
        """Reset the module-level _initialised flag before each test."""
        import observability.app_insights as ai_mod

        ai_mod._initialised = False

    def test_none_connection_string_is_noop(self) -> None:
        """init_app_insights(None) must not raise and must not set _initialised."""
        from observability import app_insights

        app_insights.init_app_insights(None)
        # Still False — we did not initialise
        assert app_insights._initialised is False

    def test_empty_string_is_noop(self) -> None:
        """init_app_insights("") must not raise."""
        from observability import app_insights

        app_insights.init_app_insights("")
        assert app_insights._initialised is False

    def test_whitespace_string_is_noop(self) -> None:
        """init_app_insights("   ") must not raise."""
        from observability import app_insights

        app_insights.init_app_insights("   ")
        assert app_insights._initialised is False

    def test_bogus_string_logs_error_but_does_not_raise(self) -> None:
        """init_app_insights with a bogus connection string must log error, not raise."""
        from observability import app_insights

        # Should not raise — even with a completely invalid connection string.
        try:
            app_insights.init_app_insights("bogus-not-a-real-connection-string")
        except Exception as exc:
            pytest.fail(f"init_app_insights raised unexpectedly: {exc}")

    def test_idempotent_second_call_is_noop(self) -> None:
        """Calling init_app_insights twice must not raise even if first call set _initialised."""
        from observability import app_insights

        app_insights._initialised = True
        # Second call with any value must be a silent no-op.
        app_insights.init_app_insights("InstrumentationKey=00000000-0000-0000-0000-000000000000")
        # _initialised remains True and no exception was raised.
        assert app_insights._initialised is True


# ---------------------------------------------------------------------------
# RequestContextMiddleware tests
# ---------------------------------------------------------------------------

def _build_middleware_app() -> FastAPI:
    """Build a minimal FastAPI app with RequestContextMiddleware installed."""
    from observability.middleware import RequestContextMiddleware

    test_app = FastAPI()
    test_app.add_middleware(RequestContextMiddleware)

    @test_app.get("/ping")
    async def ping():
        return {"ok": True}

    return test_app


class TestRequestContextMiddleware:
    """Verify X-Request-Id header generation and preservation."""

    def test_generates_request_id_when_absent(self) -> None:
        """Middleware must add X-Request-Id when the client did not provide one."""
        client = TestClient(_build_middleware_app(), raise_server_exceptions=True)
        response = client.get("/ping")
        assert response.status_code == 200
        assert "x-request-id" in response.headers
        assert len(response.headers["x-request-id"]) == 32  # uuid4().hex

    def test_preserves_existing_request_id(self) -> None:
        """Middleware must echo back a client-supplied X-Request-Id unchanged."""
        supplied_id = "my-trace-id-abc123"
        client = TestClient(_build_middleware_app(), raise_server_exceptions=True)
        response = client.get("/ping", headers={"X-Request-Id": supplied_id})
        assert response.headers["x-request-id"] == supplied_id

    def test_different_requests_get_different_ids(self) -> None:
        """Two sequential requests without a client ID must get distinct IDs."""
        client = TestClient(_build_middleware_app(), raise_server_exceptions=True)
        r1 = client.get("/ping")
        r2 = client.get("/ping")
        assert r1.headers["x-request-id"] != r2.headers["x-request-id"]


# ---------------------------------------------------------------------------
# GET /api/metrics access control tests
# ---------------------------------------------------------------------------

def _build_metrics_app(metrics_enabled: str = "true", metrics_token: str = "test-token") -> FastAPI:
    """Build a minimal FastAPI app with the metrics router mounted."""
    os.environ["METRICS_ENABLED"] = metrics_enabled
    os.environ["METRICS_TOKEN"] = metrics_token

    # Re-import metrics router to pick up env changes
    import importlib
    import api.metrics as metrics_mod
    importlib.reload(metrics_mod)

    test_app = FastAPI()
    test_app.include_router(metrics_mod.router)
    return test_app


class TestMetricsEndpoint:
    """Verify /api/metrics access gates."""

    def teardown_method(self) -> None:
        """Clean up env vars after each test."""
        os.environ.pop("METRICS_ENABLED", None)
        os.environ.pop("METRICS_TOKEN", None)

    def test_returns_404_when_disabled(self) -> None:
        """Should return 404 when METRICS_ENABLED != 'true'."""
        os.environ["METRICS_ENABLED"] = "false"
        os.environ["METRICS_TOKEN"] = "some-token"
        import importlib
        import api.metrics as m
        importlib.reload(m)
        app = FastAPI()
        app.include_router(m.router)
        client = TestClient(app, raise_server_exceptions=True)
        resp = client.get("/api/metrics", headers={"X-Metrics-Token": "some-token"})
        assert resp.status_code == 404

    def test_returns_401_with_wrong_token(self) -> None:
        """Should return 401 when token does not match."""
        os.environ["METRICS_ENABLED"] = "true"
        os.environ["METRICS_TOKEN"] = "correct-token"
        import importlib
        import api.metrics as m
        importlib.reload(m)
        app = FastAPI()
        app.include_router(m.router)
        client = TestClient(app, raise_server_exceptions=True)
        resp = client.get("/api/metrics", headers={"X-Metrics-Token": "wrong-token"})
        assert resp.status_code == 401

    def test_returns_401_with_no_token(self) -> None:
        """Should return 401 when X-Metrics-Token header is absent."""
        os.environ["METRICS_ENABLED"] = "true"
        os.environ["METRICS_TOKEN"] = "correct-token"
        import importlib
        import api.metrics as m
        importlib.reload(m)
        app = FastAPI()
        app.include_router(m.router)
        client = TestClient(app, raise_server_exceptions=True)
        resp = client.get("/api/metrics")
        assert resp.status_code == 401

    def test_returns_200_with_correct_token(self) -> None:
        """Should return 200 with Prometheus text when enabled and token matches."""
        os.environ["METRICS_ENABLED"] = "true"
        os.environ["METRICS_TOKEN"] = "correct-token"
        import importlib
        import api.metrics as m
        importlib.reload(m)
        app = FastAPI()
        app.include_router(m.router)
        client = TestClient(app, raise_server_exceptions=True)
        resp = client.get("/api/metrics", headers={"X-Metrics-Token": "correct-token"})
        # Either 200 (prometheus installed) or 503 (not installed) — both are acceptable.
        assert resp.status_code in (200, 503)
        if resp.status_code == 200:
            assert "text/plain" in resp.headers["content-type"]
            # Prometheus exposition format always starts with # HELP or # TYPE or a metric name.
            # Check the body is non-empty.
            assert len(resp.text) > 0


# ---------------------------------------------------------------------------
# Idempotent registration tests
# ---------------------------------------------------------------------------

class TestIdempotentRegistration:
    """Importing counters multiple times must never raise ValueError."""

    def test_reload_does_not_raise(self) -> None:
        """importlib.reload on observability.counters must not raise."""
        import observability.counters as counters_mod

        try:
            importlib.reload(counters_mod)
        except Exception as exc:
            pytest.fail(f"reload raised unexpectedly: {exc}")

    def test_double_import_does_not_raise(self) -> None:
        """Importing observability.counters twice is safe."""
        try:
            import observability.counters  # noqa: F401
            import observability.counters  # noqa: F401, F811
        except Exception as exc:
            pytest.fail(f"double import raised: {exc}")


# ---------------------------------------------------------------------------
# No-op when prometheus_client is absent (sys.modules patching)
# ---------------------------------------------------------------------------

class TestCountersNoopWithoutPrometheus:
    """Counter functions must be safe no-ops when prometheus_client is missing."""

    def test_all_counter_functions_are_noop_when_prometheus_absent(self) -> None:
        """Patch prometheus_client out of sys.modules and reload; verify no exceptions."""
        # Save originals
        saved: dict[str, object] = {}
        prometheus_keys = [k for k in sys.modules if k.startswith("prometheus_client")]
        for key in prometheus_keys:
            saved[key] = sys.modules.pop(key)

        # Also remove the already-imported counters module so it re-imports without prom
        counters_key = "observability.counters"
        saved_counters = sys.modules.pop(counters_key, None)

        # Inject a sentinel that makes the import raise ImportError
        sys.modules["prometheus_client"] = None  # type: ignore[assignment]

        try:
            import observability.counters as reloaded_counters

            # All functions must complete without raising.
            reloaded_counters.record_scrub(5)
            reloaded_counters.record_eval_failure()
            reloaded_counters.record_policy_deny()
            reloaded_counters.record_pii_leak()
            reloaded_counters.record_opa_unreachable()
            reloaded_counters.record_vault_error()
            reloaded_counters.record_audit_chain_break()
            reloaded_counters.record_rtf_cascade("COMPLETED")
        except Exception as exc:
            pytest.fail(f"counter function raised when prometheus_client absent: {exc}")
        finally:
            # Restore original modules
            del sys.modules["prometheus_client"]
            for key, mod in saved.items():
                sys.modules[key] = mod  # type: ignore[assignment]
            if saved_counters is not None:
                sys.modules[counters_key] = saved_counters  # type: ignore[assignment]
            elif counters_key in sys.modules:
                del sys.modules[counters_key]
