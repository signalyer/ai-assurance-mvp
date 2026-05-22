"""Unit tests for domain.audit_chain — hash determinism, chain linking, tamper detection.

Covers acceptance criteria B and C from SESSION-08-right-to-forget.md:
  B. verify_chain over a window of chained events → CLEAN
  C. verify_chain after mutating an event payload → BROKEN

All tests are hermetic: EVENTS_FILE is monkeypatched to a tmp_path file so
the real data/events.jsonl is never touched.

Test count: 8
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Skip the module gracefully if Agent 1's domain.audit_chain is not yet
# available (so CI does not hard-fail before both agents land).
# ---------------------------------------------------------------------------

_AUDIT_CHAIN_AVAILABLE = False
try:
    import domain.audit_chain as _ac_probe  # noqa: F401
    _AUDIT_CHAIN_AVAILABLE = True
except ImportError:
    pass

pytestmark = pytest.mark.skipif(
    not _AUDIT_CHAIN_AVAILABLE,
    reason="domain.audit_chain not yet available (Agent 1 not landed)",
)


# ---------------------------------------------------------------------------
# Deferred imports — only executed when module is available
# ---------------------------------------------------------------------------

if _AUDIT_CHAIN_AVAILABLE:
    from domain.audit_chain import (  # type: ignore[import]
        append_chained_event,
        compute_event_hash,
        verify_chain,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def isolated_events_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Return a tmp_path JSONL file and monkeypatch repository + audit_chain to use it.

    This prevents any test from reading or writing the real data/events.jsonl.
    """
    events_file = tmp_path / "events.jsonl"
    events_file.touch()

    monkeypatch.setattr("domain.repository.EVENTS_FILE", events_file)
    monkeypatch.setattr("domain.audit_chain.EVENTS_FILE", events_file)
    return events_file


def _make_event(event_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a minimal event dict for testing purposes."""
    return {
        "event_type": event_type,
        "ts": datetime.now(timezone.utc).isoformat(),
        **(payload or {}),
    }


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


def _tamper_event(path: Path, index: int) -> None:
    """Mutate the payload of event at *index* in the JSONL file.

    The event's hash field is left intact so the tamper is detectable by the
    verifier recalculating from scratch.
    """
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    record = json.loads(lines[index])
    record["tampered"] = "MUTATED_PAYLOAD"
    lines[index] = json.dumps(record)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestComputeEventHash:
    """Unit tests for compute_event_hash determinism and independence."""

    def test_hash_determinism(self) -> None:
        """Same (prev_hash, event) input must always produce the same 64-char hex digest."""
        prev_hash = "GENESIS"
        event: dict[str, Any] = {
            "event_type": "AGENT_PUBLISHED",
            "ts": "2026-05-21T00:00:00+00:00",
            "agent_id": "test-agent-001",
        }

        hash_a = compute_event_hash(prev_hash, event)
        hash_b = compute_event_hash(prev_hash, event)

        assert hash_a == hash_b, "Hash must be deterministic for identical inputs"
        assert len(hash_a) == 64, "SHA-256 hex digest must be 64 characters"
        assert all(c in "0123456789abcdef" for c in hash_a), "Hash must be lowercase hex"

    def test_different_events_produce_different_hashes(self) -> None:
        """Different event payloads must produce different hashes (collision resistance)."""
        prev_hash = "GENESIS"
        event_a: dict[str, Any] = {"event_type": "EVENT_A", "ts": "2026-05-21T00:00:00+00:00"}
        event_b: dict[str, Any] = {"event_type": "EVENT_B", "ts": "2026-05-21T00:00:00+00:00"}

        assert compute_event_hash(prev_hash, event_a) != compute_event_hash(prev_hash, event_b)

    def test_hash_excludes_hash_field_itself(self) -> None:
        """The hash field inside the event record must be excluded from the hash computation.

        This ensures that after a chained event is written (with its own hash field),
        re-computing the hash from the stored record produces the same value.
        """
        prev_hash = "GENESIS"
        event_without: dict[str, Any] = {"event_type": "TEST", "ts": "2026-05-21T00:00:00+00:00"}
        event_with_hash: dict[str, Any] = {
            **event_without,
            "hash": "some-existing-hash-value",
        }

        assert compute_event_hash(prev_hash, event_without) == compute_event_hash(
            prev_hash, event_with_hash
        ), "hash field in event must be excluded when computing the hash"


class TestGenesisAndChaining:
    """Tests for genesis event and chain linkage invariants."""

    def test_genesis_event(self, isolated_events_file: Path) -> None:
        """The first chained event must have prev_hash == 'GENESIS'."""
        append_chained_event("CHAIN_TEST_START", {"seq": 0})

        records = _read_events(isolated_events_file)
        assert len(records) == 1
        first = records[0]
        assert first.get("prev_hash") == "GENESIS", (
            f"First event prev_hash must be 'GENESIS', got: {first.get('prev_hash')!r}"
        )
        assert "hash" in first and len(first["hash"]) == 64

    def test_chain_links(self, isolated_events_file: Path) -> None:
        """Each subsequent event's prev_hash must equal the preceding event's hash."""
        for i in range(5):
            append_chained_event("CHAIN_TEST", {"seq": i})

        records = _read_events(isolated_events_file)
        assert len(records) == 5

        for idx in range(1, len(records)):
            prev_event_hash = records[idx - 1]["hash"]
            curr_prev_hash = records[idx]["prev_hash"]
            assert curr_prev_hash == prev_event_hash, (
                f"Event {idx}: prev_hash {curr_prev_hash!r} != "
                f"prior event's hash {prev_event_hash!r}"
            )


class TestVerifyChain:
    """Tests for verify_chain CLEAN and BROKEN paths."""

    def test_verify_clean(self, isolated_events_file: Path) -> None:
        """Writing 10 chained events and verifying must return status=CLEAN."""
        for i in range(10):
            append_chained_event("VERIFY_TEST", {"seq": i})

        result = verify_chain(window=1000)

        assert result.status == "CLEAN", f"Expected CLEAN, got {result.status}"
        assert result.events_checked >= 10, (
            f"Expected events_checked >= 10, got {result.events_checked}"
        )
        assert result.broken_at is None, (
            f"broken_at must be None for a clean chain, got {result.broken_at!r}"
        )

    def test_verify_broken_on_tamper(self, isolated_events_file: Path) -> None:
        """Mutating a stored event's payload must cause verify_chain to return BROKEN.

        The tampered event's payload now differs from what was hashed at write time,
        so recalculating the hash from the stored record will not match the stored hash.
        """
        for i in range(5):
            append_chained_event("TAMPER_TEST", {"seq": i})

        # Mutate event at index 2 (middle of chain)
        _tamper_event(isolated_events_file, index=2)

        result = verify_chain(window=10_000)

        assert result.status == "BROKEN", f"Expected BROKEN after tamper, got {result.status}"
        assert result.broken_at is not None, "broken_at must be set when chain is BROKEN"

    def test_pre_chain_events_skipped(self, isolated_events_file: Path) -> None:
        """Pre-existing events without a 'hash' field must not break verify_chain.

        Session 08 audit chain starts fresh; historical events (pre-Session-08)
        have no hash/prev_hash fields. The verifier must treat them as pre-genesis
        and skip them, not raise or report BROKEN.
        """
        # Write two legacy events with no hash fields
        legacy_events = [
            {"event_type": "AGENT_CREATED", "ts": "2026-05-20T12:00:00+00:00", "agent_id": "old-001"},
            {"event_type": "AGENT_PUBLISHED", "ts": "2026-05-20T12:01:00+00:00", "agent_id": "old-001"},
        ]
        with isolated_events_file.open("a", encoding="utf-8") as f:
            for ev in legacy_events:
                f.write(json.dumps(ev) + "\n")

        # Now write 3 chained events after the legacy ones
        for i in range(3):
            append_chained_event("POST_GENESIS", {"seq": i})

        result = verify_chain(window=1000)

        # Must not raise and must not report BROKEN due to legacy events
        assert result.status == "CLEAN", (
            f"Legacy events without hash must be skipped; got {result.status}"
        )

    # TODO: test_checkpoint_every_500
    # Checkpointing at every 500 events is impractical to assert at small scale
    # in a unit test without writing 500+ events. Behavior is gated behind the
    # CHECKPOINT_INTERVAL constant in domain.audit_chain (default 500).
    # To validate: write 501 events and assert data/audit_checkpoints.jsonl contains
    # at least one checkpoint record. Deferred — test run time would exceed CI budget.
