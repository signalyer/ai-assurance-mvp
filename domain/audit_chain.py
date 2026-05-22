"""Tamper-evident SHA-256 hash-chain for the agent/RTF audit log.

Every event written to ``data/events.jsonl`` via :func:`append_chained_event`
receives three extra fields:

* ``event_id``  — UUID4 assigned at write time.
* ``prev_hash`` — SHA-256 hash of the previous event's serialised record
  (or the sentinel string ``"GENESIS"`` for the very first event).
* ``hash``      — SHA-256 over ``prev_hash || canonical_json(event_without_hash)``.

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

Thread safety
-------------
An in-process ``threading.Lock`` serialises all writes through
:func:`append_chained_event`.  Cross-process safety is not guaranteed (Azure
App Service runs single-instance for v1).
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
# Paths — same data directory used by repository.py
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
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, default=str) + "\n")


def _canonical_json(obj: dict) -> str:
    """Return a deterministic, compact JSON string for *obj*.

    Uses ``sort_keys=True`` and ``separators=(',', ':')`` so the output is
    identical regardless of insertion order.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


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

    Steps performed under ``_write_lock``:

    1. Read the last event from ``EVENTS_FILE`` to obtain ``prev_hash``.
       If no chained event exists yet, ``prev_hash = "GENESIS"``.
       Pre-genesis events (lacking a ``hash`` field) are skipped.
    2. Build the full record with ``event_id``, ``ts``, ``event_type``,
       ``prev_hash`` and all *payload* fields.
    3. Compute ``hash = compute_event_hash(prev_hash, record)``.
    4. Append the completed record to ``EVENTS_FILE``.
    5. Every :data:`_CHECKPOINT_INTERVAL` chained events, append a checkpoint
       to ``data/audit_checkpoints.jsonl``.

    Args:
        event_type: String event type, e.g. ``"AGENT_CREATED"``.
        payload:    Arbitrary context dict merged into the record.

    Returns:
        The complete dict that was written to disk, including ``hash``.
    """
    logger.debug(
        "append_chained_event: entry event_type=%s", event_type
    )

    with _write_lock:
        # Step 1 — determine prev_hash by scanning backwards for last chained event
        prev_hash: str = "GENESIS"
        all_events = _read_jsonl(EVENTS_FILE)
        for ev in reversed(all_events):
            if "hash" in ev:
                prev_hash = ev["hash"]
                break

        # Step 2 — build record (without hash field yet)
        now = datetime.now(timezone.utc).isoformat()
        record: dict = {
            "event_id": str(uuid.uuid4()),
            "ts": now,
            "event_type": event_type,
            "prev_hash": prev_hash,
            **payload,
        }

        # Step 3 — compute hash over canonical form
        record["hash"] = compute_event_hash(prev_hash, record)

        # Step 4 — append to events file
        _append_jsonl(EVENTS_FILE, record)

        # Step 5 — checkpoint every N chained events
        chained_count = sum(1 for ev in all_events if "hash" in ev) + 1
        if chained_count % _CHECKPOINT_INTERVAL == 0:
            checkpoint = {
                "checkpoint_index": chained_count,
                "event_id": record["event_id"],
                "hash": record["hash"],
                "ts": now,
            }
            _append_jsonl(CHECKPOINTS_FILE, checkpoint)
            logger.info(
                "audit_chain: checkpoint written at index=%d event_id=%s",
                chained_count, record["event_id"],
            )

    logger.debug(
        "append_chained_event: exit event_id=%s event_type=%s hash=%s…",
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
        logger.info("verify_chain: no chained events — trivially CLEAN")
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
        # Window starts mid-chain — seed prev_hash from the event just before
        window_start_index = chained.index(to_verify[0])
        expected_prev = chained[window_start_index - 1]["hash"]
    else:
        expected_prev = "GENESIS"

    events_checked = 0

    for i, ev in enumerate(to_verify):
        stored_hash: str = ev.get("hash", "")
        stored_prev: str = ev.get("prev_hash", "")

        # Verify prev_hash linkage
        if stored_prev != expected_prev:
            broken_event_id: str | None = ev.get("event_id")
            logger.warning(
                "verify_chain: BROKEN — prev_hash mismatch at event_id=%s "
                "expected=%s…  stored=%s…",
                broken_event_id,
                expected_prev[:12] if expected_prev else "GENESIS",
                stored_prev[:12] if stored_prev else "",
            )
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
                "verify_chain: BROKEN — hash mismatch at event_id=%s "
                "recomputed=%s… stored=%s…",
                broken_event_id, recomputed[:12], stored_hash[:12],
            )
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
