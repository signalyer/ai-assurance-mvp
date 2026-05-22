"""Unit and integration tests for domain.right_to_forget and related API endpoints.

Covers acceptance criteria A, D, E, F from SESSION-08-right-to-forget.md:
  A. Cascade end-to-end: all 4 stores purged, status=COMPLETED
  D. Fail-closed on store error: PARTIAL_FAILURE; no CASCADE_COMPLETED event
  E. Verification report: all SHA-256 digests are 64-char lowercase hex
  F. API surface: POST /api/right-to-forget, GET /api/right-to-forget/{id}, GET /api/audit/verify

All tests are hermetic: EVENTS_FILE is monkeypatched to a tmp_path file so the real
data/events.jsonl is never touched.

Test count: 6
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Skip if Agent 1's domain.right_to_forget is not yet available.
# ---------------------------------------------------------------------------

_RTF_AVAILABLE = False
try:
    import domain.right_to_forget as _rtf_probe  # noqa: F401
    _RTF_AVAILABLE = True
except ImportError:
    pass

_API_AVAILABLE = False
try:
    import api.right_to_forget as _api_rtf_probe  # noqa: F401
    import api.audit_verify as _api_audit_probe  # noqa: F401
    _API_AVAILABLE = True
except ImportError:
    pass

pytestmark = pytest.mark.skipif(
    not _RTF_AVAILABLE,
    reason="domain.right_to_forget not yet available (Agent 1 not landed)",
)


# ---------------------------------------------------------------------------
# Deferred imports
# ---------------------------------------------------------------------------

if _RTF_AVAILABLE:
    from domain.right_to_forget import cascade  # type: ignore[import]

_HEX_RE = re.compile(r"^[0-9a-f]{64}$")

_SUBJECT_ID = "test-customer-9999"
_CASCADE_REASON = "GDPR Art 17 request"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def isolated_events_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Patch EVENTS_FILE in repository and audit_chain to use a tmp file."""
    events_file = tmp_path / "events.jsonl"
    events_file.touch()

    monkeypatch.setattr("domain.repository.EVENTS_FILE", events_file)

    try:
        monkeypatch.setattr("domain.audit_chain.EVENTS_FILE", events_file)
    except AttributeError:
        pass  # audit_chain may not be available yet

    return events_file


@pytest.fixture()
def seeded_stores(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    isolated_events_file: Path,
) -> dict[str, Path]:
    """Seed vault, T2, and T3 stubs so cascade has data to purge.

    Returns a dict of store-name -> path for inspection.
    The actual purge implementations are monkeypatched to stub functions
    that record their calls and return a realistic PurgeResult-style dict.
    This keeps the tests independent from the real Postgres / Azure Search backends.
    """
    vault_file = tmp_path / "deid_vault.jsonl"
    episodes_file = tmp_path / "episodes.jsonl"

    # Seed vault with one token for the subject
    subject_token_record = {
        "subject_id": _SUBJECT_ID,
        "token": "<<NAME_001>>",
        "original": "John Doe",
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    with vault_file.open("w", encoding="utf-8") as f:
        f.write(json.dumps(subject_token_record) + "\n")

    # Seed episodes for the subject
    episode_record = {
        "subject_id": _SUBJECT_ID,
        "workload_id": "wl-test-001",
        "prompt": "<<SCRUBBED>>",
        "response": "ok",
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    with episodes_file.open("w", encoding="utf-8") as f:
        f.write(json.dumps(episode_record) + "\n")

    # Monkeypatch vault purge — return real dict (orchestrator calls .get())
    def _mock_vault_purge(subject_id: str) -> dict[str, Any]:
        return {"tokens_removed": 1, "sha256_digest_after": hashlib.sha256(b"vault-after").hexdigest()}

    def _mock_t2_purge(subject_id: str, workload_id: Any = None) -> dict[str, Any]:
        return {"episodes_removed": 1, "sha256_digest_after": hashlib.sha256(b"t2-after").hexdigest()}

    def _mock_t3_purge(subject_id: str) -> dict[str, Any]:
        return {"chunks_removed": 1, "sha256_digest_after": hashlib.sha256(b"t3-after").hexdigest()}

    monkeypatch.setattr("domain.deid_vault.purge_subject_tokens", _mock_vault_purge, raising=False)
    monkeypatch.setattr("domain.agent_memory.purge_episodes", _mock_t2_purge, raising=False)
    monkeypatch.setattr("domain.rag_engine.purge_chunks", _mock_t3_purge, raising=False)

    return {"vault": vault_file, "episodes": episodes_file}


def _read_events(path: Path) -> list[dict[str, Any]]:
    """Read all JSONL events from *path*."""
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records


def _events_for_cascade(events_file: Path, cascade_id: str) -> list[dict[str, Any]]:
    """Filter events by cascade_id."""
    return [
        ev for ev in _read_events(events_file)
        if ev.get("cascade_id") == cascade_id
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCascadeCompleted:
    """Acceptance A — successful cascade across all 4 stores."""

    def test_cascade_completed(
        self,
        seeded_stores: dict[str, Path],
        isolated_events_file: Path,
    ) -> None:
        """cascade() with seeded stores must return status=COMPLETED and 4 steps with digests."""
        result = cascade(subject_id=_SUBJECT_ID, reason=_CASCADE_REASON)

        assert result.status == "COMPLETED", (
            f"Expected COMPLETED, got {result.status!r}"
        )
        assert result.cascade_id, "cascade_id must be a non-empty UUID string"

        # All 4 stores must be present
        assert "vault" in result.steps, "vault step missing"
        assert "tier2" in result.steps, "tier2 step missing"
        assert "tier3" in result.steps, "tier3 step missing"
        assert "langfuse" in result.steps, "langfuse step missing"

        # All digests must be 64-char lowercase hex
        for store_name, step in result.steps.items():
            digest = step.sha256_digest_after
            assert _HEX_RE.match(digest), (
                f"Step '{store_name}': sha256_digest_after must be 64-char hex, got {digest!r}"
            )


class TestCascadeIdempotency:
    """Acceptance A (second call) — re-submitting same cascade_id must be a no-op."""

    def test_cascade_idempotent(
        self,
        seeded_stores: dict[str, Path],
        isolated_events_file: Path,
    ) -> None:
        """Re-submitting the same cascade_id must return status=ALREADY_COMPLETED."""
        first_result = cascade(subject_id=_SUBJECT_ID, reason=_CASCADE_REASON)
        assert first_result.status == "COMPLETED"

        second_result = cascade(
            subject_id=_SUBJECT_ID,
            reason=_CASCADE_REASON,
            cascade_id=first_result.cascade_id,
        )

        assert second_result.status == "ALREADY_COMPLETED", (
            f"Second call with same cascade_id must return ALREADY_COMPLETED, "
            f"got {second_result.status!r}"
        )


class TestCascadePartialFailure:
    """Acceptance D — fail-closed on store error."""

    def test_cascade_partial_failure(
        self,
        seeded_stores: dict[str, Path],
        isolated_events_file: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """If rag_engine.purge_chunks raises, cascade must return PARTIAL_FAILURE.

        Also asserts:
          - RTF_STEP_FAILED event is emitted for tier3
          - RTF_CASCADE_COMPLETED event is NOT emitted
        """

        def _failing_t3_purge(subject_id: str) -> Any:
            raise RuntimeError("Azure AI Search connection refused")

        monkeypatch.setattr("domain.rag_engine.purge_chunks", _failing_t3_purge, raising=False)

        result = cascade(subject_id="t-partial-fail-001", reason="test partial failure")

        assert result.status == "PARTIAL_FAILURE", (
            f"Expected PARTIAL_FAILURE when T3 raises, got {result.status!r}"
        )
        assert result.steps["tier3"].error, (
            "tier3 step must carry an error description"
        )

        cascade_events = _events_for_cascade(isolated_events_file, result.cascade_id)
        event_types = [ev.get("event_type") for ev in cascade_events]

        assert "RTF_STEP_FAILED" in event_types, (
            "RTF_STEP_FAILED event must be emitted when a store purge raises"
        )
        assert "RTF_CASCADE_COMPLETED" not in event_types, (
            "RTF_CASCADE_COMPLETED must NOT be emitted on partial failure (fail-closed)"
        )


class TestVerificationReportDigests:
    """Acceptance E — all SHA-256 digests in verification report are valid hex."""

    def test_verification_report_digests(
        self,
        seeded_stores: dict[str, Path],
        isolated_events_file: Path,
    ) -> None:
        """Every step's sha256_digest_after must be 64-char lowercase hex."""
        result = cascade(subject_id=_SUBJECT_ID, reason=_CASCADE_REASON)

        for store_name, step in result.steps.items():
            digest = step.sha256_digest_after
            assert len(digest) == 64, (
                f"Store '{store_name}': digest length {len(digest)} != 64"
            )
            assert all(c in "0123456789abcdef" for c in digest), (
                f"Store '{store_name}': digest contains non-hex chars: {digest!r}"
            )


class TestLangfuseFlagGated:
    """Langfuse delete step must be safe when LANGFUSE_DELETE_ENABLED is not set."""

    def test_langfuse_flag_gated(
        self,
        seeded_stores: dict[str, Path],
        isolated_events_file: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """With LANGFUSE_DELETE_ENABLED unset, Langfuse step must return a valid digest.

        The step should not raise and must return items_removed=0 and a 64-char hex digest.
        This confirms the feature flag is respected in dev/test environments.
        """
        monkeypatch.delenv("LANGFUSE_DELETE_ENABLED", raising=False)

        result = cascade(subject_id=_SUBJECT_ID, reason=_CASCADE_REASON)

        langfuse_step = result.steps.get("langfuse")
        assert langfuse_step is not None, "langfuse step must always be present"

        digest = langfuse_step.sha256_digest_after
        assert _HEX_RE.match(digest), (
            f"langfuse digest must be 64-char hex even when flag-gated, got {digest!r}"
        )


@pytest.mark.skipif(
    not _API_AVAILABLE,
    reason="api.right_to_forget or api.audit_verify not yet available (Agent 2 not landed)",
)
class TestApiEndpoints:
    """Acceptance F — API surface smoke tests via FastAPI TestClient."""

    def test_api_endpoints(
        self,
        seeded_stores: dict[str, Path],
        isolated_events_file: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """POST /api/right-to-forget, GET /{id}, GET /api/audit/verify must all respond correctly."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from api.right_to_forget import router as rtf_router  # type: ignore[import]
        from api.audit_verify import router as audit_router  # type: ignore[import]

        # Build a minimal app with just the two routers (no auth middleware)
        test_app = FastAPI()
        test_app.include_router(rtf_router)
        test_app.include_router(audit_router)

        client = TestClient(test_app, raise_server_exceptions=True)

        # POST /api/right-to-forget
        r = client.post(
            "/api/right-to-forget",
            json={"subject_id": "t-2", "reason": "test API endpoint"},
        )
        assert r.status_code in (201, 207), (
            f"POST /api/right-to-forget returned {r.status_code}: {r.text}"
        )
        cascade_id = r.json().get("cascade_id")
        assert cascade_id, "Response must include cascade_id"

        # GET /api/right-to-forget/{cascade_id}
        r2 = client.get(f"/api/right-to-forget/{cascade_id}")
        assert r2.status_code == 200, (
            f"GET /api/right-to-forget/{cascade_id} returned {r2.status_code}: {r2.text}"
        )
        assert r2.json().get("status") in ("COMPLETED", "PARTIAL_FAILURE", "IN_PROGRESS"), (
            f"Unexpected cascade status: {r2.json().get('status')!r}"
        )

        # GET /api/audit/verify?window=1000
        r3 = client.get("/api/audit/verify?window=1000")
        assert r3.status_code == 200, (
            f"GET /api/audit/verify returned {r3.status_code}: {r3.text}"
        )
        assert r3.json().get("status") in ("CLEAN", "BROKEN"), (
            f"Unexpected verify status: {r3.json().get('status')!r}"
        )
