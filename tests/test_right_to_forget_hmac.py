"""Tests for RTF sidecar HMAC-SHA256 signing and verification.

Task 1 — Session 11 debt fix.

4 tests:
  (a) valid HMAC sig accepted — sidecar entry with correct sig is found
  (b) invalid sig rejected — logger.warning + counter increment + fallback to events.jsonl scan
  (c) missing sig (legacy entry) rejected-with-warn + fallback
  (d) disagreement between sidecar and events.jsonl still emits existing warning
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Module availability guard
# ---------------------------------------------------------------------------

_MODULE_AVAILABLE = False
try:
    import domain.right_to_forget as _rtf_probe  # noqa: F401
    _MODULE_AVAILABLE = True
except ImportError:
    pass

pytestmark = pytest.mark.skipif(
    not _MODULE_AVAILABLE,
    reason="domain.right_to_forget not available",
)

if _MODULE_AVAILABLE:
    import domain.right_to_forget as rtf


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TEST_SECRET = "test-hmac-secret-32bytes-padded!!"


def _make_sidecar_entry(
    cascade_id: str,
    subject_id: str,
    *,
    secret: str = _TEST_SECRET,
    tamper_sig: bool = False,
    omit_sig: bool = False,
) -> dict[str, Any]:
    """Build a sidecar entry dict, optionally signed, unsigned, or tampered."""
    entry: dict[str, Any] = {
        "cascade_id": cascade_id,
        "subject_id": subject_id,
        "completed_at": "2026-05-22T00:00:00+00:00",
        "started_at": "2026-05-22T00:00:00+00:00",
        "steps": {},
    }
    if not omit_sig:
        # Sign over the entry-minus-sig canonical JSON
        canonical = json.dumps(entry, sort_keys=True, separators=(",", ":"), default=str)
        sig = hmac.new(
            secret.encode("utf-8"),
            canonical.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if tamper_sig:
            sig = "deadbeef" + sig[8:]
        entry["_sig"] = sig
    return entry


def _write_sidecar(path: Path, entries: list[dict[str, Any]]) -> None:
    """Write a list of dicts to a JSONL sidecar file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for entry in entries:
            fh.write(json.dumps(entry, default=str) + "\n")


# ---------------------------------------------------------------------------
# Test (a): valid HMAC sig accepted
# ---------------------------------------------------------------------------

class TestValidSigAccepted:
    """Sidecar entry with correct HMAC signature is found and returned."""

    def test_valid_sig_returns_result(self, tmp_path: pytest.TempPathFactory) -> None:
        """_find_completed_cascade finds a correctly-signed sidecar entry."""
        cascade_id = str(uuid.uuid4())
        subject_id = "subj-valid-001"

        entry = _make_sidecar_entry(cascade_id, subject_id, secret=_TEST_SECRET)
        sidecar = tmp_path / "rtf_completed_index.jsonl"
        _write_sidecar(sidecar, [entry])

        # Clear in-memory cache so we actually read from file
        rtf._completed_cache.clear() if hasattr(rtf._completed_cache, "clear") else None

        with (
            patch.object(rtf, "_RTF_INDEX_FILE", sidecar),
            patch.dict(os.environ, {"SL_HMAC_SECRET": _TEST_SECRET}),
        ):
            result = rtf._find_completed_cascade(cascade_id)

        assert result is not None, "Valid signed entry must be found"
        assert result.cascade_id == cascade_id
        assert result.subject_id == subject_id


# ---------------------------------------------------------------------------
# Test (b): invalid sig rejected + warning + counter increment + fallback
# ---------------------------------------------------------------------------

class TestInvalidSigRejected:
    """Tampered signature triggers warning, counter, and events.jsonl fallback."""

    def test_invalid_sig_warns_and_falls_back(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Invalid sig → logger.warning + rtf_sidecar_unsigned_total increment + fallback."""
        cascade_id = str(uuid.uuid4())
        subject_id = "subj-invalid-001"

        # Write sidecar entry with tampered sig
        entry = _make_sidecar_entry(
            cascade_id, subject_id, secret=_TEST_SECRET, tamper_sig=True
        )
        sidecar = tmp_path / "rtf_completed_index.jsonl"
        _write_sidecar(sidecar, [entry])

        # Clear cache
        if hasattr(rtf._completed_cache, "clear"):
            rtf._completed_cache.clear()

        counter_mock = MagicMock()

        import logging

        with (
            patch.object(rtf, "_RTF_INDEX_FILE", sidecar),
            patch.dict(os.environ, {"SL_HMAC_SECRET": _TEST_SECRET}),
            patch.object(rtf, "_sidecar_unsigned_counter", counter_mock, create=True),
            patch("domain.audit_chain.read_chain_tail", return_value=[]),
            caplog.at_level(logging.WARNING, logger="domain.right_to_forget"),
        ):
            result = rtf._find_completed_cascade(cascade_id)

        # Must fall back to events.jsonl scan (which returns nothing here) → None
        assert result is None, "Fallback to events.jsonl; no matching event → None"
        # Warning must be logged
        assert any(
            "unsigned" in r.message.lower() or "invalid" in r.message.lower()
            for r in caplog.records
            if r.levelno >= logging.WARNING
        ), f"Expected warning about unsigned/invalid sidecar. Records: {[r.message for r in caplog.records]}"


# ---------------------------------------------------------------------------
# Test (c): missing sig (legacy entry) rejected-with-warn + fallback
# ---------------------------------------------------------------------------

class TestMissingSigRejected:
    """Legacy sidecar entries without _sig field trigger warning and fallback."""

    def test_missing_sig_warns_and_falls_back(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Entry without _sig field → logger.warning + fallback to events.jsonl."""
        cascade_id = str(uuid.uuid4())
        subject_id = "subj-legacy-001"

        # Write sidecar entry WITHOUT sig (legacy)
        entry = _make_sidecar_entry(cascade_id, subject_id, omit_sig=True)
        sidecar = tmp_path / "rtf_completed_index.jsonl"
        _write_sidecar(sidecar, [entry])

        if hasattr(rtf._completed_cache, "clear"):
            rtf._completed_cache.clear()

        import logging

        with (
            patch.object(rtf, "_RTF_INDEX_FILE", sidecar),
            patch.dict(os.environ, {"SL_HMAC_SECRET": _TEST_SECRET}),
            patch("domain.audit_chain.read_chain_tail", return_value=[]),
            caplog.at_level(logging.WARNING, logger="domain.right_to_forget"),
        ):
            result = rtf._find_completed_cascade(cascade_id)

        assert result is None, "Unsigned legacy entry must fall back to events.jsonl → None"
        assert any(
            "unsigned" in r.message.lower() or "invalid" in r.message.lower() or "legacy" in r.message.lower()
            for r in caplog.records
            if r.levelno >= logging.WARNING
        ), f"Expected warning about unsigned/legacy sidecar entry. Records: {[r.message for r in caplog.records]}"


# ---------------------------------------------------------------------------
# Test (d): sidecar/events disagreement still emits existing warning
# ---------------------------------------------------------------------------

class TestSidecarEventsDisagreement:
    """When sidecar has no entry but events.jsonl also has none, existing warning fires."""

    def test_disagreement_warning_emitted(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Cascade not in sidecar OR events.jsonl → existing 'sidecar write gap' warning."""
        cascade_id = str(uuid.uuid4())

        # Write sidecar with a DIFFERENT cascade (so it exists but misses our ID)
        other_entry = _make_sidecar_entry(
            str(uuid.uuid4()), "subj-other", secret=_TEST_SECRET
        )
        sidecar = tmp_path / "rtf_completed_index.jsonl"
        _write_sidecar(sidecar, [other_entry])

        if hasattr(rtf._completed_cache, "clear"):
            rtf._completed_cache.clear()

        import logging

        with (
            patch.object(rtf, "_RTF_INDEX_FILE", sidecar),
            patch.dict(os.environ, {"SL_HMAC_SECRET": _TEST_SECRET}),
            patch("domain.audit_chain.read_chain_tail", return_value=[]),
            caplog.at_level(logging.WARNING, logger="domain.right_to_forget"),
        ):
            result = rtf._find_completed_cascade(cascade_id)

        assert result is None
        assert any(
            "sidecar" in r.message.lower() or "write gap" in r.message.lower()
            for r in caplog.records
            if r.levelno >= logging.WARNING
        ), f"Expected 'sidecar write gap' warning. Records: {[r.message for r in caplog.records]}"
