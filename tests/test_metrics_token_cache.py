"""Tests for api/metrics.py METRICS_TOKEN module-load caching.

Task 5 — Session 11 debt fix.

3 tests:
  (a) cached token validates correct value
  (b) _METRICS_TOKEN = None (env missing at module load) → _token_valid returns False
  (c) env var change after module load does NOT affect validation (proves caching)
"""
from __future__ import annotations

import hmac
import importlib
import os
import sys
from unittest.mock import patch

import pytest

_MODULE_AVAILABLE = False
try:
    import api.metrics as _metrics_probe  # noqa: F401
    _MODULE_AVAILABLE = True
except ImportError:
    pass

pytestmark = pytest.mark.skipif(
    not _MODULE_AVAILABLE,
    reason="api.metrics not available",
)


def _reload_metrics_with_env(env: dict[str, str]) -> object:
    """Reload api.metrics with a specific environment, return the fresh module."""
    # Remove cached module to force a fresh import
    if "api.metrics" in sys.modules:
        del sys.modules["api.metrics"]
    with patch.dict(os.environ, env, clear=False):
        import api.metrics as fresh
        return fresh


class TestCachedTokenValidatesCorrectValue:
    """Test (a): _token_valid returns True for the correct cached token."""

    def test_correct_token_validates(self) -> None:
        """When METRICS_TOKEN is set at load time, _token_valid(correct) → True."""
        module = _reload_metrics_with_env({"METRICS_TOKEN": "secret-token-abc"})

        assert hasattr(module, "_METRICS_TOKEN"), (
            "api.metrics must expose _METRICS_TOKEN module-level attribute"
        )
        assert module._METRICS_TOKEN == "secret-token-abc", (
            "_METRICS_TOKEN must be cached from env at module load"
        )
        assert module._token_valid("secret-token-abc") is True, (
            "_token_valid must return True for the correct token"
        )
        assert module._token_valid("wrong-token") is False, (
            "_token_valid must return False for a wrong token"
        )


class TestMissingEnvReturnsFalse:
    """Test (b): _METRICS_TOKEN = None when env var absent → _token_valid always False."""

    def test_missing_env_means_deny_all(self) -> None:
        """If METRICS_TOKEN is not set at module load, _token_valid returns False for any input."""
        # Ensure the env var is absent during module load
        env_without_token = {k: v for k, v in os.environ.items() if k != "METRICS_TOKEN"}

        if "api.metrics" in sys.modules:
            del sys.modules["api.metrics"]

        with patch.dict(os.environ, {}, clear=True):
            # Re-set only non-METRICS_TOKEN vars
            os.environ.update(env_without_token)
            if "METRICS_TOKEN" in os.environ:
                del os.environ["METRICS_TOKEN"]
            import api.metrics as fresh

        assert fresh._METRICS_TOKEN is None, (
            "_METRICS_TOKEN must be None when env var absent at module load"
        )
        # Any input must return False
        assert fresh._token_valid("anything") is False
        assert fresh._token_valid("") is False
        assert fresh._token_valid("secret") is False


class TestEnvChangeAfterLoadNoEffect:
    """Test (c): changing env var after module load does NOT affect validation."""

    def test_env_change_after_load_ignored(self) -> None:
        """Cached token must not change when os.environ is mutated post-import."""
        # Load with a known token
        module = _reload_metrics_with_env({"METRICS_TOKEN": "initial-token"})

        assert module._token_valid("initial-token") is True

        # Now change the env var WITHOUT reloading the module
        os.environ["METRICS_TOKEN"] = "changed-token"
        try:
            # The module-level cache must still hold "initial-token"
            assert module._METRICS_TOKEN == "initial-token", (
                "Module-level cache must not change with os.environ mutation"
            )
            # _token_valid must still accept the original token
            assert module._token_valid("initial-token") is True, (
                "_token_valid must use the cached value, not re-read os.environ"
            )
            # And must reject the new env value (because it wasn't cached)
            assert module._token_valid("changed-token") is False, (
                "_token_valid must NOT accept a token set after module load"
            )
        finally:
            # Restore env to avoid polluting other tests
            if "METRICS_TOKEN" in os.environ:
                del os.environ["METRICS_TOKEN"]
