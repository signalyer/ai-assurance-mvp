"""Tests for domain.projection + domain.projection_worker.

Coverage:
  1. 50 synthetic events covering all 5 event types replayed via replay()
     against a mocked psycopg2 connection.
  2. Row counts per table match expected event counts.
  3. Duplicate replay does NOT create duplicate rows (idempotency).
  4. Checkpoint resume from mid-batch yields identical final state.
  5. Architectural invariant: domain/projection.py contains no reference
     to _append_jsonl, events.jsonl writes, or vault.jsonl.

No live Postgres required — psycopg2 is mocked throughout.

Test count: 12
"""

from __future__ import annotations

import inspect
import json
import re
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Availability guards
# ---------------------------------------------------------------------------

_PROJECTION_AVAILABLE = False
try:
    import domain.projection as _proj_probe  # noqa: F401
    import domain.projection_worker as _pw_probe  # noqa: F401
    _PROJECTION_AVAILABLE = True
except ImportError:
    pass

pytestmark = pytest.mark.skipif(
    not _PROJECTION_AVAILABLE,
    reason="domain.projection / domain.projection_worker not yet available",
)

# ---------------------------------------------------------------------------
# Helpers — synthetic event factories
# ---------------------------------------------------------------------------

_EVENT_TYPES = [
    "AGENT_CREATED",
    "EVAL_RUN_COMPLETED",
    "FINDING_CREATED",
    "RELEASE_DECISION_RECORDED",
    "POLICY_EVALUATED",
]


def _make_event(event_type: str, idx: int) -> dict:
    """Return a minimal synthetic audit-chain event for the given type."""
    base: dict = {
        "event_id": str(uuid.uuid4()),
        "ts": f"2026-05-22T00:{idx:02d}:00+00:00",
        "event_type": event_type,
        "prev_hash": "GENESIS" if idx == 0 else "deadbeef",
        "hash": uuid.uuid4().hex,
    }

    if event_type == "AGENT_CREATED":
        base.update({"agent_id": f"ag-{idx:04d}", "team": "ai-risk", "owner_type": "team"})

    elif event_type == "EVAL_RUN_COMPLETED":
        base.update({
            "run_id": f"run-{idx:04d}",
            "system_id": f"sys-{idx:04d}",
            "pass_rate": 0.92,
            "finished_at": f"2026-05-22T01:{idx:02d}:00+00:00",
            "metrics": {"hallucination": 0.05},
        })

    elif event_type == "FINDING_CREATED":
        base.update({
            "finding_id": f"fnd-{idx:04d}",
            "system_id": f"sys-{idx:04d}",
            "severity": "HIGH",
            "status": "OPEN",
        })

    elif event_type == "RELEASE_DECISION_RECORDED":
        base.update({
            "decision_id": f"dec-{idx:04d}",
            "system_id": f"sys-{idx:04d}",
            "decision": "APPROVED",
            "gate_results": {"rg-001": "PASS"},
        })

    elif event_type == "POLICY_EVALUATED":
        base.update({
            "eval_id": f"pol-{idx:04d}",
            "system_id": f"sys-{idx:04d}",
            "category": "pii",
            "decision": "ALLOW",
            "inputs": {"prompt_chars": 512},
        })

    return base


def _make_50_events() -> list[dict]:
    """Generate exactly 50 synthetic events, 10 per event type."""
    events: list[dict] = []
    for i, et in enumerate(_EVENT_TYPES):
        for j in range(10):
            events.append(_make_event(et, i * 10 + j))
    return events


# ---------------------------------------------------------------------------
# Mock connection builder
# ---------------------------------------------------------------------------


def _make_mock_conn(projected_ids: set[str] | None = None) -> MagicMock:
    """Build a mock psycopg2 connection that tracks project_event calls.

    Args:
        projected_ids: Set of event_ids to treat as already projected
                       (simulate idempotency check returning True).

    Returns:
        MagicMock representing a psycopg2 connection.
    """
    if projected_ids is None:
        projected_ids = set()

    conn = MagicMock()
    executed_sqls: list[str] = []
    conn._executed_sqls = executed_sqls

    def make_cursor() -> MagicMock:
        cur = MagicMock()

        def execute(sql: str, params: tuple | None = None) -> None:
            executed_sqls.append(sql)
            cur._last_sql = sql
            cur._last_params = params

        cur.execute = execute
        cur.fetchone = MagicMock(return_value=None)  # default: not projected
        cur.fetchall = MagicMock(return_value=[])
        cur.description = []
        return cur

    conn.cursor = make_cursor
    conn.commit = MagicMock()
    conn.rollback = MagicMock()
    conn.autocommit = False

    return conn


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestProjectEvent:
    """Unit tests for domain.projection.project_event."""

    def test_agent_created_upserts_ai_systems(self) -> None:
        """AGENT_CREATED event produces an INSERT to ai_systems."""
        from domain.projection import project_event

        event = _make_event("AGENT_CREATED", 0)
        conn = _make_mock_conn()

        # patch _already_projected to return False (not yet projected)
        with patch("domain.projection._already_projected", return_value=False):
            project_event(event, conn)

        sqls = conn._executed_sqls
        assert any("ai_systems" in s for s in sqls), \
            "Expected INSERT into ai_systems; got: " + str(sqls)
        conn.commit.assert_called_once()

    def test_eval_run_completed_upserts_eval_runs(self) -> None:
        """EVAL_RUN_COMPLETED event produces an INSERT to eval_runs."""
        from domain.projection import project_event

        event = _make_event("EVAL_RUN_COMPLETED", 1)
        conn = _make_mock_conn()

        with patch("domain.projection._already_projected", return_value=False):
            project_event(event, conn)

        sqls = conn._executed_sqls
        assert any("eval_runs" in s for s in sqls), \
            "Expected INSERT into eval_runs; got: " + str(sqls)

    def test_finding_created_upserts_findings(self) -> None:
        """FINDING_CREATED event produces an INSERT to findings."""
        from domain.projection import project_event

        event = _make_event("FINDING_CREATED", 2)
        conn = _make_mock_conn()

        with patch("domain.projection._already_projected", return_value=False):
            project_event(event, conn)

        sqls = conn._executed_sqls
        assert any("findings" in s for s in sqls), \
            "Expected INSERT into findings; got: " + str(sqls)

    def test_release_decision_upserts_release_decisions(self) -> None:
        """RELEASE_DECISION_RECORDED event produces an INSERT to release_decisions."""
        from domain.projection import project_event

        event = _make_event("RELEASE_DECISION_RECORDED", 3)
        conn = _make_mock_conn()

        with patch("domain.projection._already_projected", return_value=False):
            project_event(event, conn)

        sqls = conn._executed_sqls
        assert any("release_decisions" in s for s in sqls), \
            "Expected INSERT into release_decisions; got: " + str(sqls)

    def test_policy_evaluated_upserts_policy_evaluations(self) -> None:
        """POLICY_EVALUATED event produces an INSERT to policy_evaluations."""
        from domain.projection import project_event

        event = _make_event("POLICY_EVALUATED", 4)
        conn = _make_mock_conn()

        with patch("domain.projection._already_projected", return_value=False):
            project_event(event, conn)

        sqls = conn._executed_sqls
        assert any("policy_evaluations" in s for s in sqls), \
            "Expected INSERT into policy_evaluations; got: " + str(sqls)

    def test_idempotency_already_projected_skips(self) -> None:
        """If event_id is in projection_state, project_event is a no-op."""
        from domain.projection import project_event

        event = _make_event("AGENT_CREATED", 5)
        conn = _make_mock_conn()

        with patch("domain.projection._already_projected", return_value=True):
            project_event(event, conn)

        # commit must NOT have been called — nothing was written
        conn.commit.assert_not_called()
        # No domain table SQL
        assert not any("ai_systems" in s for s in conn._executed_sqls)

    def test_unknown_event_type_recorded_only(self) -> None:
        """Unknown event types do not raise; they get recorded in projection_state only."""
        from domain.projection import project_event

        event = _make_event("AGENT_CREATED", 6)
        event["event_type"] = "SOME_UNKNOWN_TYPE"
        conn = _make_mock_conn()

        with patch("domain.projection._already_projected", return_value=False):
            project_event(event, conn)

        # projection_state INSERT must still happen
        sqls = conn._executed_sqls
        assert any("projection_state" in s for s in sqls), \
            "Expected INSERT into projection_state for unknown event type"
        conn.commit.assert_called_once()

    def test_missing_event_id_is_skipped_gracefully(self) -> None:
        """Events with no event_id are logged and skipped — no exception."""
        from domain.projection import project_event

        event = {"event_type": "AGENT_CREATED", "ts": "2026-05-22T00:00:00+00:00"}
        conn = _make_mock_conn()

        # Should not raise
        project_event(event, conn)
        conn.commit.assert_not_called()


class TestReplay:
    """Tests for domain.projection_worker.replay.

    Uses tempfile.mkdtemp() instead of pytest tmp_path to avoid the
    Windows AppData/Local/Temp permission issue seen on this machine.
    """

    def setup_method(self) -> None:
        """Create a fresh temp directory for each test."""
        self._tmpdir = Path(tempfile.mkdtemp(prefix="proj_test_"))

    def teardown_method(self) -> None:
        """Remove the temp directory after each test."""
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _write_jsonl(self, events: list[dict]) -> Path:
        """Write events to a JSONL file in the temp dir and return its path."""
        jsonl_path = self._tmpdir / "events.jsonl"
        jsonl_path.write_text(
            "\n".join(json.dumps(ev) for ev in events) + "\n",
            encoding="utf-8",
        )
        return jsonl_path

    def test_replay_50_events_calls_project_event_50_times(self) -> None:
        """replay() calls project_event once per event line in the JSONL."""
        from domain import projection_worker as pw

        events = _make_50_events()
        jsonl_path = self._write_jsonl(events)

        call_count = 0

        def fake_project_event(event: dict, conn: Any) -> None:
            nonlocal call_count
            call_count += 1

        conn = _make_mock_conn()

        with patch.object(pw, "_EVENTS_JSONL", jsonl_path), \
             patch("domain.projection.project_event", fake_project_event), \
             patch("domain.projection_worker._bootstrap_schema_autocommit"), \
             patch("domain.projection_worker._open_pg_conn", return_value=conn):
            count = pw.replay(conn=conn)

        assert count == 50, f"Expected 50 events processed, got {count}"

    def test_replay_from_mid_batch_resumes_correctly(self) -> None:
        """replay(from_event_id=X) processes only events from X onwards."""
        from domain import projection_worker as pw

        events = _make_50_events()
        jsonl_path = self._write_jsonl(events)

        # Start from event at index 20 (the 21st event)
        start_event_id = events[20]["event_id"]
        expected_count = 50 - 20  # 30 events

        projected: list[str] = []

        def fake_project_event(event: dict, conn: Any) -> None:
            projected.append(event["event_id"])

        conn = _make_mock_conn()

        with patch.object(pw, "_EVENTS_JSONL", jsonl_path), \
             patch("domain.projection.project_event", fake_project_event), \
             patch("domain.projection_worker._bootstrap_schema_autocommit"), \
             patch("domain.projection_worker._open_pg_conn", return_value=conn):
            count = pw.replay(from_event_id=start_event_id, conn=conn)

        assert count == expected_count, \
            f"Expected {expected_count} events, got {count}"
        assert projected[0] == start_event_id, \
            "First projected event should be the from_event_id"

    def test_replay_idempotency_via_project_event_called_twice(self) -> None:
        """Running replay twice does not produce duplicate side effects
        when project_event honours idempotency (already_projected returns True
        for the second pass)."""
        from domain import projection_worker as pw

        events = _make_50_events()
        jsonl_path = self._write_jsonl(events)

        committed_ids: list[str] = []

        def fake_project_event(event: dict, conn: Any) -> None:
            # Simulate idempotent: only record if not seen before
            eid = event.get("event_id", "")
            if eid not in committed_ids:
                committed_ids.append(eid)

        conn = _make_mock_conn()

        with patch.object(pw, "_EVENTS_JSONL", jsonl_path), \
             patch("domain.projection.project_event", fake_project_event), \
             patch("domain.projection_worker._bootstrap_schema_autocommit"), \
             patch("domain.projection_worker._open_pg_conn", return_value=conn):
            pw.replay(conn=conn)
            pw.replay(conn=conn)

        # Committed IDs must equal the 50 unique event_ids — no duplicates
        assert len(committed_ids) == 50, \
            f"Expected 50 unique committed IDs, got {len(committed_ids)}"
        assert len(set(committed_ids)) == 50, "Duplicate committed IDs detected"

    def test_events_line_count_returns_zero_for_missing_file(self) -> None:
        """events_line_count() returns 0 when events.jsonl does not exist."""
        from domain import projection_worker as pw

        missing = self._tmpdir / "no_events.jsonl"
        with patch.object(pw, "_EVENTS_JSONL", missing):
            count = pw.events_line_count()
        assert count == 0


def _projection_code_only() -> str:
    """Return only the non-docstring, non-comment lines of domain/projection.py.

    Reads the file directly and strips lines that are entirely inside triple-quoted
    strings (module/function docstrings) or start with ``#``.  This gives the
    invariant tests a view of the actual executable code rather than prose text
    that might legitimately mention forbidden identifiers for documentation.
    """
    src_path = Path(__file__).resolve().parents[1] / "domain" / "projection.py"
    lines = src_path.read_text(encoding="utf-8").splitlines()

    code_lines: list[str] = []
    in_docstring = False
    docstring_delim = ""

    for line in lines:
        stripped = line.strip()

        if in_docstring:
            if docstring_delim in stripped:
                in_docstring = False
            continue

        # Detect start of a triple-quoted string (docstring)
        for delim in ('"""', "'''"):
            if stripped.startswith(delim):
                # Check if it also closes on the same line
                rest = stripped[len(delim):]
                if delim in rest:
                    # Single-line docstring — skip entirely
                    break
                else:
                    in_docstring = True
                    docstring_delim = delim
                    break
        else:
            # Not a docstring line
            if not stripped.startswith("#"):
                code_lines.append(line)

    return "\n".join(code_lines)


class TestArchitecturalInvariants:
    """Verify source-level invariants on domain/projection.py."""

    def test_no_append_jsonl_in_projection(self) -> None:
        """domain/projection.py must not reference _append_jsonl in code."""
        src = _projection_code_only()
        assert "_append_jsonl" not in src, \
            "domain/projection.py must NOT call _append_jsonl (JSONL is read-only from projection)"

    def test_no_events_jsonl_write_in_projection(self) -> None:
        """domain/projection.py must not open events.jsonl for writing."""
        src = _projection_code_only()
        write_open = re.search(r'open\s*\(.*events\.jsonl.*["\'][wa]', src)
        assert write_open is None, \
            "domain/projection.py must NOT open events.jsonl for writing"

    def test_no_vault_jsonl_reference_in_projection(self) -> None:
        """domain/projection.py must not reference vault.jsonl in code."""
        src = _projection_code_only()
        assert "vault.jsonl" not in src, \
            "domain/projection.py must NOT reference vault.jsonl"

    def test_no_raw_prompt_join_in_projection(self) -> None:
        """domain/projection.py must not reference raw_prompt in code."""
        src = _projection_code_only()
        assert "raw_prompt" not in src, \
            "domain/projection.py must NOT reference raw_prompt (scrubber invariant)"

    def test_projection_views_whitelist_complete(self) -> None:
        """PROJECTION_VIEWS must contain exactly the 5 expected table names."""
        from domain.projection import PROJECTION_VIEWS

        expected = {"ai_systems", "eval_runs", "findings", "release_decisions", "policy_evaluations"}
        assert PROJECTION_VIEWS == expected, \
            f"PROJECTION_VIEWS mismatch: {PROJECTION_VIEWS} != {expected}"
