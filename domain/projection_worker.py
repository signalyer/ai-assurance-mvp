"""Postgres event projection worker — JSONL tailer + LISTEN/NOTIFY projection loop.

ARCHITECTURAL INVARIANT:
  This module reads data/events.jsonl (never writes it).
  It NEVER calls _append_jsonl, repository._append_jsonl, or any write to
  events.jsonl or vault.jsonl.  JSONL is the source of truth; Postgres tables
  are a downstream read-side replica.

Two entry points, invocable via  ``python -m domain.projection_worker {tailer|worker}``:

  run_tailer()
    Tails data/events.jsonl from a file-offset checkpoint, parses each new
    line, and issues ``NOTIFY projection_events, '<json_payload>'`` to Postgres
    so the projection worker can pick it up.  Updates
    data/projection_tailer_checkpoint.json after each successful NOTIFY.

  run_projection_worker()
    LISTENs on ``projection_events``, deserialises each notification payload,
    and calls :func:`domain.projection.project_event` inside a transaction.
    Handles SIGTERM for graceful shutdown.

  replay(from_event_id, conn)
    Reads JSONL from *from_event_id* (or from the start) and applies
    projections directly (no NOTIFY).  Returns count of events processed.
    Used by POST /api/projection/replay.

Environment variables:
  DATABASE_URL   Full Postgres connection string (required for live use).
  EVENTS_JSONL   Override path for data/events.jsonl (testing).
"""

from __future__ import annotations

import base64
import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_DATA_DIR: Path = Path(__file__).resolve().parents[1] / "data"
_EVENTS_JSONL: Path = Path(os.getenv("EVENTS_JSONL", str(_DATA_DIR / "events.jsonl")))
_TAILER_CHECKPOINT: Path = _DATA_DIR / "projection_tailer_checkpoint.json"

_DATABASE_URL: str | None = os.getenv("DATABASE_URL")

# Poll interval in seconds between tail passes
_POLL_INTERVAL_SECONDS: float = 1.0


# ---------------------------------------------------------------------------
# Checkpoint helpers
# ---------------------------------------------------------------------------


def _read_tailer_checkpoint() -> dict:
    """Read the tailer checkpoint file.

    Returns:
        Dict with keys ``byte_offset`` (int) and ``last_event_id`` (str | None).
        Returns defaults when file is absent.
    """
    if not _TAILER_CHECKPOINT.exists():
        return {"byte_offset": 0, "last_event_id": None}
    try:
        return json.loads(_TAILER_CHECKPOINT.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("projection_worker: could not read tailer checkpoint: %s", exc)
        return {"byte_offset": 0, "last_event_id": None}


def _write_tailer_checkpoint(byte_offset: int, last_event_id: str | None) -> None:
    """Write the tailer checkpoint to disk.

    Args:
        byte_offset:   Current byte position in events.jsonl after processing.
        last_event_id: event_id of the last successfully processed event.
    """
    _TAILER_CHECKPOINT.parent.mkdir(parents=True, exist_ok=True)
    _TAILER_CHECKPOINT.write_text(
        json.dumps({"byte_offset": byte_offset, "last_event_id": last_event_id}),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# JSONL line reader — pure read, never writes
# ---------------------------------------------------------------------------


def _read_jsonl_from_offset(path: Path, byte_offset: int) -> list[tuple[dict, int]]:
    """Read all complete JSONL lines from *path* starting at *byte_offset*.

    Returns:
        List of (parsed_dict, new_byte_offset) tuples.  The new_byte_offset
        is the file position after the last successfully parsed line.
    """
    if not path.exists():
        return []

    results: list[tuple[dict, int]] = []
    with path.open("rb") as fh:
        fh.seek(byte_offset)
        while True:
            line_bytes = fh.readline()
            if not line_bytes:
                break
            line = line_bytes.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                new_offset = fh.tell()
                results.append((record, new_offset))
            except json.JSONDecodeError as exc:
                logger.warning(
                    "projection_worker: malformed JSONL line at offset=%d: %s",
                    byte_offset, exc,
                )
    return results


# ---------------------------------------------------------------------------
# Postgres connection helper
# ---------------------------------------------------------------------------


def _open_pg_conn(autocommit: bool = False) -> Any:
    """Open and return a psycopg2 connection using DATABASE_URL.

    Args:
        autocommit: If True sets connection.autocommit = True.

    Returns:
        An open psycopg2 connection.

    Raises:
        RuntimeError: If DATABASE_URL is not set.
        ImportError:  If psycopg2 is not installed.
    """
    if not _DATABASE_URL:
        raise RuntimeError(
            "projection_worker: DATABASE_URL is not set. "
            "Configure it before running the projection worker."
        )
    import psycopg2  # type: ignore[import]  # noqa: PLC0415

    conn = psycopg2.connect(_DATABASE_URL)
    conn.autocommit = autocommit
    return conn


# ---------------------------------------------------------------------------
# Bootstrap the projection schema
# ---------------------------------------------------------------------------


def _bootstrap_schema(conn: Any) -> None:
    """Run migrations/009_projection_views.sql if tables do not yet exist.

    Idempotent — uses CREATE TABLE IF NOT EXISTS throughout.

    Args:
        conn: Open psycopg2 connection with autocommit=True.
    """
    sql_path = Path(__file__).resolve().parents[1] / "migrations" / "009_projection_views.sql"
    if not sql_path.exists():
        logger.warning("projection_worker: migration file not found: %s", sql_path)
        return
    sql = sql_path.read_text(encoding="utf-8")
    cur = conn.cursor()
    try:
        cur.execute(sql)
        logger.info("projection_worker: schema bootstrapped from %s", sql_path.name)
    except Exception as exc:
        logger.error("projection_worker: schema bootstrap failed: %s", exc, exc_info=True)
        raise
    finally:
        cur.close()


# ---------------------------------------------------------------------------
# Tailer entry point
# ---------------------------------------------------------------------------


def run_tailer() -> None:
    """Tail data/events.jsonl and NOTIFY Postgres for each new line.

    Runs until interrupted (SIGTERM / KeyboardInterrupt).  Maintains a byte-
    offset checkpoint at data/projection_tailer_checkpoint.json so restarts
    resume from the last processed position.

    Never writes to events.jsonl or any other JSONL file.
    """
    logger.info("projection_worker.run_tailer: starting up")

    conn = _open_pg_conn(autocommit=True)
    _bootstrap_schema(conn)

    checkpoint = _read_tailer_checkpoint()
    byte_offset: int = checkpoint.get("byte_offset", 0)
    last_event_id: str | None = checkpoint.get("last_event_id")

    logger.info(
        "projection_worker.run_tailer: resuming from byte_offset=%d last_event_id=%s",
        byte_offset, last_event_id,
    )

    _shutdown_requested = False

    def _handle_sigterm(signum: int, frame: Any) -> None:  # noqa: ARG001
        nonlocal _shutdown_requested
        logger.info("projection_worker.run_tailer: SIGTERM received — shutting down")
        _shutdown_requested = True

    signal.signal(signal.SIGTERM, _handle_sigterm)

    try:
        while not _shutdown_requested:
            lines = _read_jsonl_from_offset(_EVENTS_JSONL, byte_offset)

            for record, new_offset in lines:
                event_id: str = record.get("event_id", "")
                if not event_id:
                    byte_offset = new_offset
                    continue

                # Encode full event JSON as base64 so it survives NOTIFY payload escaping
                payload_json = json.dumps(record, default=str)
                payload_b64 = base64.b64encode(payload_json.encode("utf-8")).decode("ascii")

                # NOTIFY carries: {"event_id": "...", "data": "<base64>"}
                notify_payload = json.dumps({"event_id": event_id, "data": payload_b64})

                cur = conn.cursor()
                try:
                    # Use pg_notify() function with parameterized args — no SQL injection risk
                    # via manual quote escaping. event_id and payload flow as bound params.
                    cur.execute(
                        "SELECT pg_notify(%s, %s)",
                        ("projection_events", notify_payload),
                    )
                    logger.debug(
                        "run_tailer: NOTIFY sent event_id=%s", event_id
                    )
                except Exception as exc:
                    logger.error("run_tailer: NOTIFY failed event_id=%s: %s", event_id, exc)
                finally:
                    cur.close()

                byte_offset = new_offset
                last_event_id = event_id
                _write_tailer_checkpoint(byte_offset, last_event_id)

            if not lines:
                time.sleep(_POLL_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        logger.info("projection_worker.run_tailer: KeyboardInterrupt — shutting down")
    finally:
        try:
            conn.close()
        except Exception:
            pass
        logger.info("projection_worker.run_tailer: stopped")


# ---------------------------------------------------------------------------
# Projection worker entry point
# ---------------------------------------------------------------------------


def run_projection_worker() -> None:
    """LISTEN on projection_events and apply projections to Postgres tables.

    Runs until interrupted (SIGTERM / KeyboardInterrupt).  Each notification
    payload is base64-decoded, deserialized, and passed to
    :func:`domain.projection.project_event` inside a transaction.

    Never writes to events.jsonl or any other JSONL file.
    """
    logger.info("projection_worker.run_projection_worker: starting up")

    # Import here so module-level import of projection_worker never fails
    # if psycopg2 is absent (e.g. in test environments with mocks).
    import psycopg2.extensions  # type: ignore[import]  # noqa: PLC0415
    from domain.projection import project_event  # noqa: PLC0415

    listen_conn = _open_pg_conn(autocommit=True)
    _bootstrap_schema(listen_conn)

    cur = listen_conn.cursor()
    cur.execute("LISTEN projection_events")
    cur.close()
    logger.info("projection_worker.run_projection_worker: LISTEN projection_events")

    _shutdown_requested = False

    def _handle_sigterm(signum: int, frame: Any) -> None:  # noqa: ARG001
        nonlocal _shutdown_requested
        logger.info("run_projection_worker: SIGTERM received — shutting down")
        _shutdown_requested = True

    signal.signal(signal.SIGTERM, _handle_sigterm)

    try:
        while not _shutdown_requested:
            import select  # noqa: PLC0415

            # poll with 2s timeout so SIGTERM check fires regularly
            r, _, _ = select.select([listen_conn], [], [], 2.0)
            if not r:
                continue

            listen_conn.poll()

            while listen_conn.notifies:
                notify = listen_conn.notifies.pop(0)
                payload_str: str = notify.payload

                try:
                    envelope = json.loads(payload_str)
                    event_json = base64.b64decode(envelope["data"]).decode("utf-8")
                    event = json.loads(event_json)
                except (KeyError, ValueError, Exception) as exc:
                    logger.error(
                        "run_projection_worker: failed to decode notification: %s", exc
                    )
                    continue

                # Open a fresh connection for each projection transaction
                proj_conn = _open_pg_conn(autocommit=False)
                try:
                    project_event(event, proj_conn)
                except Exception as exc:
                    logger.error(
                        "run_projection_worker: project_event failed event_id=%s: %s",
                        event.get("event_id"), exc,
                    )
                finally:
                    try:
                        proj_conn.close()
                    except Exception:
                        pass

    except KeyboardInterrupt:
        logger.info("run_projection_worker: KeyboardInterrupt — shutting down")
    finally:
        try:
            listen_conn.close()
        except Exception:
            pass
        logger.info("projection_worker.run_projection_worker: stopped")


# ---------------------------------------------------------------------------
# Replay helper
# ---------------------------------------------------------------------------


def replay(from_event_id: str | None = None, conn: Any = None) -> int:
    """Replay events from events.jsonl directly into Postgres (no NOTIFY).

    Reads all events from data/events.jsonl.  If *from_event_id* is given,
    skips events until that event_id is seen, then projects from there.
    If *from_event_id* is None, projects all events.

    Safe to call multiple times — every projection upsert is idempotent.

    Args:
        from_event_id: event_id to start from (inclusive), or None for all.
        conn:          Open psycopg2 connection.  If None, a new connection is
                       opened using DATABASE_URL.

    Returns:
        Count of events processed (including already-projected events that
        were skipped by idempotency check inside project_event).
    """
    logger.info("replay: entry from_event_id=%s", from_event_id)

    from domain.projection import project_event  # noqa: PLC0415

    _owns_conn = conn is None
    if _owns_conn:
        conn = _open_pg_conn(autocommit=False)

    try:
        _bootstrap_schema_autocommit(conn)

        events = _read_jsonl_from_offset(_EVENTS_JSONL, 0)

        # If from_event_id given, seek to it
        if from_event_id is not None:
            found = False
            start_idx = 0
            for i, (record, _) in enumerate(events):
                if record.get("event_id") == from_event_id:
                    found = True
                    start_idx = i
                    break
            if not found:
                logger.warning("replay: from_event_id=%s not found — replaying all", from_event_id)
            else:
                events = events[start_idx:]

        count = 0
        for record, _ in events:
            # Each project_event opens its own transaction internally
            project_event(record, conn)
            count += 1

        logger.info("replay: exit count=%d", count)
        return count

    finally:
        if _owns_conn:
            try:
                conn.close()
            except Exception:
                pass


def _bootstrap_schema_autocommit(conn: Any) -> None:
    """Run schema bootstrap on a non-autocommit connection.

    Temporarily sets autocommit, runs DDL, then restores the prior setting.

    Args:
        conn: Open psycopg2 connection.
    """
    prior_autocommit = conn.autocommit
    try:
        conn.autocommit = True
        _bootstrap_schema(conn)
    finally:
        conn.autocommit = prior_autocommit


# ---------------------------------------------------------------------------
# JSONL line count helper (used by api/projection.py for lag computation)
# ---------------------------------------------------------------------------


def events_line_count() -> int:
    """Return the total number of non-empty lines in events.jsonl.

    Returns:
        Integer line count.  0 if file does not exist.
    """
    if not _EVENTS_JSONL.exists():
        return 0
    count = 0
    with _EVENTS_JSONL.open("r", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                count += 1
    return count


# ---------------------------------------------------------------------------
# __main__ entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if len(sys.argv) < 2 or sys.argv[1] not in ("tailer", "worker"):
        print("Usage: python -m domain.projection_worker {tailer|worker}", file=sys.stderr)
        sys.exit(1)

    mode = sys.argv[1]
    if mode == "tailer":
        run_tailer()
    else:
        run_projection_worker()


__all__ = [
    "run_tailer",
    "run_projection_worker",
    "replay",
    "events_line_count",
]
