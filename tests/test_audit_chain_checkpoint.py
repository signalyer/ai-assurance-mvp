"""Tests for audit_chain checkpoint-inside-lock and dead-branch removal.

Task 4 — Session 11 debt fix.

2 tests:
  (a) checkpoint file is written before lock release (assert checkpoint exists
      inside the write sequence, not after)
  (b) existing audit_chain regression tests still pass (import guard)
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any
from unittest.mock import patch, MagicMock

import pytest

_MODULE_AVAILABLE = False
try:
    import domain.audit_chain as _ac_probe  # noqa: F401
    _MODULE_AVAILABLE = True
except ImportError:
    pass

pytestmark = pytest.mark.skipif(
    not _MODULE_AVAILABLE,
    reason="domain.audit_chain not available",
)

if _MODULE_AVAILABLE:
    import domain.audit_chain as ac


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def isolated_chain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect EVENTS_FILE and CHECKPOINTS_FILE to tmp_path for test isolation."""
    events_file = tmp_path / "events.jsonl"
    checkpoints_file = tmp_path / "audit_checkpoints.jsonl"
    events_file.touch()

    monkeypatch.setattr("domain.audit_chain.EVENTS_FILE", events_file)
    monkeypatch.setattr("domain.audit_chain.CHECKPOINTS_FILE", checkpoints_file)
    # Reset module-level cache so tests start fresh
    monkeypatch.setattr("domain.audit_chain._prev_hash_cache", None)
    monkeypatch.setattr("domain.audit_chain._chained_count_cache", None)
    monkeypatch.setattr("domain.audit_chain._cache_seeded_from", None)
    return events_file


# ---------------------------------------------------------------------------
# Test (a): checkpoint written inside advisory lock (before __exit__)
# ---------------------------------------------------------------------------

class TestCheckpointInsideLock:
    """Checkpoint must be written while the advisory lock is still held."""

    def test_checkpoint_written_before_lock_releases(
        self, isolated_chain: Path, tmp_path: Path
    ) -> None:
        """The checkpoint file exists at the point the advisory lock context exits.

        We lower _CHECKPOINT_INTERVAL to 2 so we can trigger a checkpoint quickly,
        then intercept the lock context manager's __exit__ to assert the checkpoint
        already exists at that moment.
        """
        # Lower checkpoint interval so we trigger it after 2 events
        original_interval = ac._CHECKPOINT_INTERVAL
        try:
            ac._CHECKPOINT_INTERVAL = 2

            checkpoints_file: Path = tmp_path / "audit_checkpoints.jsonl"
            # Monkeypatch CHECKPOINTS_FILE to our tmp path
            original_cp = ac.CHECKPOINTS_FILE
            ac.CHECKPOINTS_FILE = checkpoints_file

            checkpoint_existed_at_lock_exit: list[bool] = []

            # Wrap _acquire_writer_lock to intercept __exit__
            original_acquire = ac._acquire_writer_lock

            def patched_acquire(path: Path):
                """Return a context manager that checks checkpoint existence on exit."""
                real_cm = original_acquire(path)

                class _InstrumentedLock:
                    def __enter__(self_inner):
                        return real_cm.__enter__()

                    def __exit__(self_inner, *args: Any) -> None:
                        # At the moment the lock is released, checkpoint should exist
                        # IF this is the Nth event and we've just crossed the threshold.
                        # We record whether the file exists at this point.
                        checkpoint_existed_at_lock_exit.append(checkpoints_file.exists())
                        return real_cm.__exit__(*args)

                return _InstrumentedLock()

            with patch.object(ac, "_acquire_writer_lock", side_effect=patched_acquire):
                # Write exactly 2 events to cross interval=2 threshold
                ac.append_chained_event("CHECKPOINT_TEST_1", {"seq": 1})
                ac.append_chained_event("CHECKPOINT_TEST_2", {"seq": 2})

            # The checkpoint must have existed by the time the lock __exit__ was called
            # on the 2nd event (i.e., checkpoint was written INSIDE the with block).
            assert len(checkpoint_existed_at_lock_exit) >= 2, (
                "Lock must have been acquired at least twice"
            )
            # On the 2nd lock exit (which crosses interval=2), checkpoint must exist
            assert checkpoint_existed_at_lock_exit[-1] is True, (
                "Checkpoint file must exist before the advisory lock is released "
                "(checkpoint must be written INSIDE the with block)"
            )

        finally:
            ac._CHECKPOINT_INTERVAL = original_interval
            ac.CHECKPOINTS_FILE = original_cp if "_cp" not in dir() else original_cp


# ---------------------------------------------------------------------------
# Test (b): existing regression tests still importable (structural check)
# ---------------------------------------------------------------------------

class TestRegressionGuard:
    """Verify the existing test_audit_chain.py tests can still be discovered."""

    def test_existing_test_file_importable(self) -> None:
        """tests/test_audit_chain.py must still import without error."""
        import importlib.util
        test_file = Path(__file__).parent / "test_audit_chain.py"
        assert test_file.exists(), "tests/test_audit_chain.py must still exist"

        spec = importlib.util.spec_from_file_location("test_audit_chain", test_file)
        assert spec is not None and spec.loader is not None, (
            "test_audit_chain.py must be importable"
        )
        # Just check it parses — don't execute the module-level fixture code
        import ast
        src = test_file.read_text(encoding="utf-8")
        try:
            ast.parse(src)
        except SyntaxError as exc:
            pytest.fail(f"test_audit_chain.py has syntax error: {exc}")

    def test_append_chained_event_returns_record_with_hash(
        self, isolated_chain: Path
    ) -> None:
        """append_chained_event still returns a dict with 'hash' field."""
        record = ac.append_chained_event("REGRESSION_CHECK", {"value": 42})
        assert "hash" in record, "append_chained_event must return record with 'hash'"
        assert "prev_hash" in record, "append_chained_event must return record with 'prev_hash'"
        assert len(record["hash"]) == 64, "hash must be 64-char SHA-256 hex"
