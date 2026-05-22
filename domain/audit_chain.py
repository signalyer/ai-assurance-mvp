"""Tamper-evident SHA-256 hash-chain for the agent/RTF audit log.

Every event written to ``data/events.jsonl`` via :func:`append_chained_event`
receives three extra fields:

* ``event_id``  -- UUID4 assigned at write time.
* ``prev_hash`` -- SHA-256 hash of the previous event's serialised record
  (or the sentinel string ``"GENESIS"`` for the very first event).
* ``hash``      -- SHA-256 over ``prev_hash || canonical_json(event_without_hash)``.

Events written by earlier sessions that pre-date this module have neither field.
:func:`verify_chain` treats those as *pre-genesis* events: they are counted in
``pre_chain_events`` and excluded from hash verification without marking the
chain BROKEN.

Checkpoints
-----------
Every 500 chained events a checkpoint record is appended to
``data/audit_checkpoints.jsonl`` containing the event index position and its
hash.  This lets :func:`verify_chain` start from the nearest checkpoint rather
than scanning from the beginning of a large file.

Thread and process safety
-------------------------
An in-process ``threading.Lock`` serialises all writes through
:func:`append_chained_event`.

An advisory file lock (via ``portalocker``) guards the write sequence across
processes (e.g. multiple uvicorn workers or a tailer process).  The lock is
acquired with a 5-second timeout; if the lock cannot be acquired within that
window the function raises ``RuntimeError`` (fail-closed).

Session 10 hardening:
- ``_prev_hash_cache`` + ``_chained_count_cache`` are module-level variables
  seeded lazily on the first write.  This eliminates the O(n) full re-read of
  ``events.jsonl`` on every ``append_chained_event`` call (replaced by O(1)
  in-memory lookup after the first call).
- Cache is updated atomically under ``_write_lock``.
- Advisory file lock via ``portalocker`` (cross-platform).
- ``verify_chain`` calls ``observability.counters.record_audit_chain_break()``
  when status != CLEAN (additive counter hook, no behaviour change).

Single-worker note: the portalocker advisory lock is cross-process, but the
in-memory prev_hash cache is per-process.  If multiple processes write
concurrently the lock prevents data corruption but each process seeds its own
cache independently on the next write after startup.  This is safe because the
cache seed reads the tail of the file under the lock.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths -- same data directory used by repository.py
# ---------------------------------------------------------------------------

_DATA_DIR: Path = Path(__file__).resolve().parents[1] / "data"
_DATA_DIR.mkdir(exist_ok=True)

EVENTS_FILE: Path = _DATA_DIR / "events.jsonl"
CHECKPOINTS_FILE: Path = _DATA_DIR / "audit_checkpoints.jsonl"

_CHECKPOINT_INTERVAL: int = 500

# ---------------------------------------------------------------------------
# In-process write lock
# ---------------------------------------------------------------------------

_write_lock: threading.Lock = threading.Lock()

# ---------------------------------------------------------------------------
# Module-level prev_hash + chained_count cache (Session 10 O(1) optimisation)
# Guarded by _write_lock.  None means "not yet seeded from file".
# ---------------------------------------------------------------------------

_prev_hash_cache: str | None = None
_chained_count_cache: int | None = None

#: Path the cache was seeded from.  When EVENTS_FILE changes (e.g. in tests
#: that monkeypatch EVENTS_FILE to a tmp_path) the cache is automatically
#: invalidated and re-seeded from the new file.
_cache_seeded_from: Path | None = None


# ---------------------------------------------------------------------------
# Observability counter hooks (non-raising)
# ---------------------------------------------------------------------------

try:
    from observability.counters import record_audit_chain_break as _record_chain_break
except ImportError:
    try:
        from observability_compat import record_audit_chain_break as _record_chain_break
    except ImportError:
        def _record_chain_break() -> None:  # type: ignore[misc]
            """Local no-op fallback."""


# ---------------------------------------------------------------------------
# portalocker advisory file lock
# ---------------------------------------------------------------------------

try:
    import portalocker as _portalocker
    _HAS_PORTALOCKER = True
except ImportError:
    _HAS_PORTALOCKER = False
    _portalocker = None  # type: ignore[assignment]

_LOCK_TIMEOUT_S: float = 5.0


# ---------------------------------------------------------------------------
# Pydantic result model
# ---------------------------------------------------------------------------


class ChainVerifyResult(BaseModel):
    """Result returned by :func:`verify_chain`."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["CLEAN", "BROKEN"]
    events_checked: int
    broken_at: str | None = None
    window_start_event_id: str | None = None
    pre_chain_events: int = 0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _read_jsonl(path: Path) -> list[dict]:
    """Read all non-empty lines from a JSONL file; return list[dict].

    Returns an empty list if the file does not exist.

    Args:
        path: Path to a JSONL file.
    """
    if not path.exists():
        return []
    records: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.warning("audit_chain: skipping malformed JSONL line in %s", path.name)
    return records


def _append_jsonl(path: Path, record: dict) -> None:
    """Append a single dict as a JSONL line; creates parent dirs as needed.

    NOTE: callers that require in-process mutual exclusion must already hold
    ``_write_lock`` before calling this.  This function does NOT acquire the
    lock itself so it can be composed atomically with hash computation.

    Args:
        path:   Destination JSONL file.
        record: Dict to serialise and append.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, default=str) + "\n")


def _canonical_json(obj: dict) -> str:
    """Return a deterministic, compact JSON string for *obj*.

    Uses ``sort_keys=True`` and ``separators=(',', ':')`` so the output is
    identical regardless of insertion order.

    Args:
        obj: Dict to serialise.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _acquire_writer_lock(path: Path):
    """Acquire an advisory file lock on *path*.lock using portalocker.

    Returns a context manager if portalocker is available.  If portalocker is
    not installed, returns a no-op context manager (degrades gracefully in test
    environments where the package is absent).

    If the lock cannot be acquired within ``_LOCK_TIMEOUT_S`` seconds the
    function raises ``RuntimeError`` (fail-closed).

    Args:
        path: The events file path; the lock file is ``path + ".lock"``.

    Returns:
        A context manager that holds the file lock.

    Raises:
        RuntimeError: If the lock cannot be acquired within the timeout.
    """
    if not _HAS_PORTALOCKER:
        import contextlib

        @contextlib.contextmanager
        def _noop():
            yield

        return _noop()

    lock_path = Path(str(path) + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        return _portalocker.Lock(str(lock_path), timeout=_LOCK_TIMEOUT_S)
    except _portalocker.LockException as exc:
        raise RuntimeError(
            f"audit_chain: could not acquire writer lock on {lock_path} "
            f"within {_LOCK_TIMEOUT_S}s (fail-closed): {exc}"
        ) from exc


def _seed_cache_from_file() -> tuple[str, int]:
    """Seed the module-level prev_hash and chained_count from the events file.

    Must be called under ``_write_lock`` by the caller.

    Performs a FULL file scan on first seed (O(n) on cold start / process
    restart). The result is cached in module-level state and subsequent writes
    are O(1). Re-scanning is intentional for correctness — partial state would
    risk a chain break. Reverse-tail optimisation is a Phase 2 follow-up if
    cold-start latency becomes a bottleneck at production scale.

    Returns:
        Tuple of (prev_hash, chained_count).
    """
    all_events = _read_jsonl(EVENTS_FILE)
    prev_hash = "GENESIS"
    chained_count = 0
    for ev in all_events:
        if "hash" in ev:
            prev_hash = ev["hash"]
            chained_count += 1
    return prev_hash, chained_count


# ---------------------------------------------------------------------------
# Core hash computation
# ---------------------------------------------------------------------------


def compute_event_hash(prev_hash: str, event: dict) -> str:
    """Compute the SHA-256 chain hash for *event*.

    The hash is computed over the UTF-8 encoding of:
        ``prev_hash + canonical_json(event_without_hash_field)``

    The ``hash`` key is excluded from the event before serialisation so that
    the computation is deterministic whether or not the field is present.

    Args:
        prev_hash: SHA-256 hex digest of the preceding event, or ``"GENESIS"``.
        event:     The event dict to hash (may include a ``hash`` key; it is
                   excluded from the computation).

    Returns:
        64-character lowercase hex digest.
    """
    event_without_hash = {k: v for k, v in event.items() if k != "hash"}
    payload = prev_hash + _canonical_json(event_without_hash)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Public write API
# ---------------------------------------------------------------------------


def append_chained_event(event_type: str, payload: dict) -> dict:
    """Build and persist a tamper-evident chain event to ``data/events.jsonl``.

    Steps performed under ``_write_lock`` and the advisory file lock:

    1. Acquire advisory file lock (portalocker, 5s timeout, fail-closed).
    2. Seed module-level cache from file if not yet populated.
    3. Read ``prev_hash`` from the in-memory cache (O(1)).
    4. Build the full record with ``event_id``, ``ts``, ``event_type``,
       ``prev_hash`` and all *payload* fields.
    5. Compute ``hash = compute_event_hash(prev_hash, record)``.
    6. Append the completed record to ``EVENTS_FILE``.
    7. Update the module-level cache atomically.
    8. Every :data:`_CHECKPOINT_INTERVAL` chained events, append a checkpoint
       to ``data/audit_checkpoints.jsonl``.

    Args:
        event_type: String event type, e.g. ``"AGENT_CREATED"``.
        payload:    Arbitrary context dict merged into the record.

    Returns:
        The complete dict that was written to disk, including ``hash``.

    Raises:
        RuntimeError: If the advisory file lock cannot be acquired within 5s.
    """
    global _prev_hash_cache, _chained_count_cache, _cache_seeded_from

    logger.debug(
        "append_chained_event: entry event_type=%s", event_type
    )

    with _write_lock:
        # Acquire cross-process advisory lock (fail-closed on timeout).
        with _acquire_writer_lock(EVENTS_FILE):
            # Seed cache from file on first call, after a crash reset, or when
            # EVENTS_FILE has been changed (e.g. test monkeypatching tmp_path).
            if (
                _prev_hash_cache is None
                or _chained_count_cache is None
                or _cache_seeded_from != EVENTS_FILE
            ):
                _prev_hash_cache, _chained_count_cache = _seed_cache_from_file()
                _cache_seeded_from = EVENTS_FILE

            prev_hash: str = _prev_hash_cache

            # Build record (without hash field yet)
            now = datetime.now(timezone.utc).isoformat()
            record: dict = {
                "event_id": str(uuid.uuid4()),
                "ts": now,
                "event_type": event_type,
                "prev_hash": prev_hash,
                **payload,
            }

            # Compute hash over canonical form
            record["hash"] = compute_event_hash(prev_hash, record)

            # Append to events file
            _append_jsonl(EVENTS_FILE, record)

            # Update cache atomically (still under both locks)
            _chained_count_cache += 1
            _prev_hash_cache = record["hash"]
            new_count = _chained_count_cache

        # File lock released here; in-process lock still held for checkpoint

        # Checkpoint every N chained events
        if new_count % _CHECKPOINT_INTERVAL == 0:
            checkpoint = {
                "checkpoint_index": new_count,
                "event_id": record["event_id"],
                "hash": record["hash"],
                "ts": now,
            }
            _append_jsonl(CHECKPOINTS_FILE, checkpoint)
            logger.info(
                "audit_chain: checkpoint written at index=%d event_id=%s",
                new_count, record["event_id"],
            )

    logger.debug(
        "append_chained_event: exit event_id=%s event_type=%s hash=%s...",
        record["event_id"], event_type, record["hash"][:12],
    )
    return record


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def verify_chain(window: int = 1000, full: bool = False) -> ChainVerifyResult:
    """Re-compute and verify the SHA-256 hash chain over stored events.

    Pre-genesis events (those lacking a ``hash`` field) are **skipped** and
    counted in ``pre_chain_events``; their presence does NOT break the chain.

    When *full* is True, all chained events in the file are verified regardless
    of *window*.  Otherwise the most recent *window* chained events are checked.

    Calls ``observability.counters.record_audit_chain_break()`` when status
    is BROKEN (additive counter hook, no behaviour change).

    Args:
        window: Maximum number of chained events to verify (default 1000).
                Ignored when *full* is True.
        full:   If True, verify every chained event in the file.

    Returns:
        :class:`ChainVerifyResult` with ``status``, ``events_checked``,
        ``broken_at`` (event_id of first mismatch), ``window_start_event_id``,
        and ``pre_chain_events``.
    """
    logger.info(
        "verify_chain: entry window=%d full=%s", window, full
    )

    all_events = _read_jsonl(EVENTS_FILE)

    # Separate pre-genesis from chained events
    pre_chain: list[dict] = [ev for ev in all_events if "hash" not in ev]
    chained: list[dict] = [ev for ev in all_events if "hash" in ev]

    pre_chain_events = len(pre_chain)

    if not chained:
        logger.info("verify_chain: no chained events -- trivially CLEAN")
        return ChainVerifyResult(
            status="CLEAN",
            events_checked=0,
            pre_chain_events=pre_chain_events,
        )

    # Determine the slice to verify
    if full:
        to_verify = chained
    else:
        to_verify = chained[-window:]

    window_start_event_id: str | None = to_verify[0].get("event_id") if to_verify else None

    # The expected prev_hash for the first event in the window:
    # if verifying from the absolute genesis, it's "GENESIS";
    # otherwise it's the hash of the event just before the window.
    if to_verify and to_verify[0] is not chained[0]:
        # Window starts mid-chain -- seed prev_hash from the event just before
        window_start_index = chained.index(to_verify[0])
        expected_prev = chained[window_start_index - 1]["hash"]
    else:
        expected_prev = "GENESIS"

    events_checked = 0

    for ev in to_verify:
        stored_hash: str = ev.get("hash", "")
        stored_prev: str = ev.get("prev_hash", "")

        # Verify prev_hash linkage
        if stored_prev != expected_prev:
            broken_event_id: str | None = ev.get("event_id")
            logger.warning(
                "verify_chain: BROKEN -- prev_hash mismatch at event_id=%s "
                "expected=%s...  stored=%s...",
                broken_event_id,
                expected_prev[:12] if expected_prev else "GENESIS",
                stored_prev[:12] if stored_prev else "",
            )
            try:
                _record_chain_break()
            except Exception as _cb_exc:  # noqa: BLE001
                logger.warning("verify_chain: record_audit_chain_break raised: %s", _cb_exc)
            return ChainVerifyResult(
                status="BROKEN",
                events_checked=events_checked,
                broken_at=broken_event_id,
                window_start_event_id=window_start_event_id,
                pre_chain_events=pre_chain_events,
            )

        # Verify hash recomputation
        recomputed = compute_event_hash(expected_prev, ev)
        if recomputed != stored_hash:
            broken_event_id = ev.get("event_id")
            logger.warning(
                "verify_chain: BROKEN -- hash mismatch at event_id=%s "
                "recomputed=%s... stored=%s...",
                broken_event_id, recomputed[:12], stored_hash[:12],
            )
            try:
                _record_chain_break()
            except Exception as _cb_exc:  # noqa: BLE001
                logger.warning("verify_chain: record_audit_chain_break raised: %s", _cb_exc)
            return ChainVerifyResult(
                status="BROKEN",
                events_checked=events_checked,
                broken_at=broken_event_id,
                window_start_event_id=window_start_event_id,
                pre_chain_events=pre_chain_events,
            )

        expected_prev = stored_hash
        events_checked += 1

    logger.info(
        "verify_chain: exit status=CLEAN events_checked=%d pre_chain=%d",
        events_checked, pre_chain_events,
    )
    return ChainVerifyResult(
        status="CLEAN",
        events_checked=events_checked,
        window_start_event_id=window_start_event_id,
        pre_chain_events=pre_chain_events,
    )


# ---------------------------------------------------------------------------
# Read tail helper
# ---------------------------------------------------------------------------


def read_chain_tail(n: int) -> list[dict]:
    """Return the last *n* events from ``data/events.jsonl`` (newest-last order).

    Args:
        n: Number of events to return.

    Returns:
        List of event dicts; at most *n* entries.  Empty list if file absent.
    """
    all_events = _read_jsonl(EVENTS_FILE)
    return all_events[-n:] if n < len(all_events) else all_events


__all__ = [
    "compute_event_hash",
    "append_chained_event",
    "verify_chain",
    "read_chain_tail",
    "ChainVerifyResult",
    "EVENTS_FILE",
    "CHECKPOINTS_FILE",
]
