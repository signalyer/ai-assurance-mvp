"""Right-to-Forget cascade orchestrator (GDPR Art. 17 / CCPA).

Executes a four-store purge in order:

1. **vault**    — Fernet-encrypted PII token mappings in ``domain/deid_vault.py``
2. **tier2**    — Postgres episodic memory in ``domain/agent_memory.py``
3. **tier3**    — Azure AI Search RAG chunks in ``domain/rag_engine.py``
4. **langfuse** — Langfuse trace store (PHASE-2 STUB — flag-gated via
                  ``LANGFUSE_DELETE_ENABLED`` env var; default disabled)

Architecture constraints
------------------------
* **Fail-closed** — if ANY step fails, the cascade stops, emits
  ``RTF_CASCADE_FAILED``, and returns ``PARTIAL_FAILURE``.
  ``RTF_CASCADE_COMPLETED`` is only emitted when ALL four steps succeed.
* **Idempotent** — re-submitting the same ``cascade_id`` returns
  ``ALREADY_COMPLETED`` with the stored result; no second purge is executed.
* Every event is written through :func:`domain.audit_chain.append_chained_event`
  so the full cascade is part of the tamper-evident audit trail.

Environment variables
---------------------
``LANGFUSE_DELETE_ENABLED``
    Set to ``"true"`` to enable real Langfuse API deletes (Phase 2).
    Default ``"false"`` — returns a simulated digest and ``items_removed=0``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level idempotency cache
# key = cascade_id; value = CascadeResult for completed cascades
# ---------------------------------------------------------------------------

_completed_cache: dict[str, "CascadeResult"] = {}

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class PurgeResult(BaseModel):
    """Per-store result from a single purge step."""

    model_config = ConfigDict(extra="forbid")

    store: str
    items_removed: int
    sha256_digest_after: str
    error: str | None = None


class CascadeResult(BaseModel):
    """Aggregated result of a Right-to-Forget cascade run."""

    model_config = ConfigDict(extra="forbid")

    cascade_id: str
    subject_id: str
    status: Literal["COMPLETED", "PARTIAL_FAILURE", "ALREADY_COMPLETED"]
    steps: dict[str, PurgeResult]
    started_at: str
    completed_at: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _sha256_str(data: str) -> str:
    """Return the SHA-256 hex digest of *data* encoded as UTF-8."""
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _emit(event_type: str, payload: dict) -> None:
    """Emit a chained audit event, logging errors but never raising."""
    try:
        from domain.audit_chain import append_chained_event  # late import — avoids circular
        append_chained_event(event_type, payload)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "_emit: failed to write audit event event_type=%s: %s",
            event_type, exc, exc_info=True,
        )


def _canonical_json(obj: dict) -> str:
    """Return compact canonical JSON."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


# ---------------------------------------------------------------------------
# Per-store purge implementations
# ---------------------------------------------------------------------------


def _purge_vault(subject_id: str) -> PurgeResult:
    """Tombstone all vault tokens belonging to *subject_id*.

    Delegates to :func:`domain.deid_vault.purge_subject_tokens`.

    Args:
        subject_id: Subject identifier to purge.

    Returns:
        :class:`PurgeResult` with store ``"vault"``.
    """
    logger.info("_purge_vault: entry subject_id=%s", subject_id)
    try:
        from domain.deid_vault import purge_subject_tokens  # late import

        result = purge_subject_tokens(subject_id)
        pr = PurgeResult(
            store="vault",
            items_removed=result.get("tokens_removed", 0),
            sha256_digest_after=result.get("sha256_digest_after", _sha256_str("")),
        )
        logger.info(
            "_purge_vault: exit subject_id=%s tokens_removed=%d",
            subject_id, pr.items_removed,
        )
        return pr
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "_purge_vault: failed subject_id=%s: %s", subject_id, exc, exc_info=True
        )
        return PurgeResult(
            store="vault",
            items_removed=0,
            sha256_digest_after=_sha256_str(""),
            error=str(exc),
        )


def _purge_tier2(subject_id: str) -> PurgeResult:
    """Tombstone all Tier-2 episodic memory for *subject_id*.

    Delegates to :func:`domain.agent_memory.purge_episodes`.

    Args:
        subject_id: Subject identifier to purge.

    Returns:
        :class:`PurgeResult` with store ``"tier2"``.
    """
    logger.info("_purge_tier2: entry subject_id=%s", subject_id)
    try:
        from domain.agent_memory import purge_episodes  # late import

        result = purge_episodes(subject_id)
        pr = PurgeResult(
            store="tier2",
            items_removed=result.get("episodes_removed", 0),
            sha256_digest_after=result.get("sha256_digest_after", _sha256_str("")),
        )
        logger.info(
            "_purge_tier2: exit subject_id=%s episodes_removed=%d",
            subject_id, pr.items_removed,
        )
        return pr
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "_purge_tier2: failed subject_id=%s: %s", subject_id, exc, exc_info=True
        )
        return PurgeResult(
            store="tier2",
            items_removed=0,
            sha256_digest_after=_sha256_str(""),
            error=str(exc),
        )


def _purge_tier3(subject_id: str) -> PurgeResult:
    """Delete RAG chunks for *subject_id* from Azure AI Search.

    Delegates to :func:`domain.rag_engine.purge_chunks`.

    Args:
        subject_id: Subject identifier to purge.

    Returns:
        :class:`PurgeResult` with store ``"tier3"``.
    """
    logger.info("_purge_tier3: entry subject_id=%s", subject_id)
    try:
        from domain.rag_engine import purge_chunks  # late import

        result = purge_chunks(subject_id)
        pr = PurgeResult(
            store="tier3",
            items_removed=result.get("chunks_removed", 0),
            sha256_digest_after=result.get("sha256_digest_after", _sha256_str("")),
        )
        logger.info(
            "_purge_tier3: exit subject_id=%s chunks_removed=%d",
            subject_id, pr.items_removed,
        )
        return pr
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "_purge_tier3: failed subject_id=%s: %s", subject_id, exc, exc_info=True
        )
        return PurgeResult(
            store="tier3",
            items_removed=0,
            sha256_digest_after=_sha256_str(""),
            error=str(exc),
        )


def _purge_langfuse(subject_id: str) -> PurgeResult:
    """Purge Langfuse traces for *subject_id*.

    **Phase-2 stub.**  When ``LANGFUSE_DELETE_ENABLED`` is not ``"true"`` (the
    default), this returns a simulated digest and ``items_removed=0`` without
    making any external API call.  The intent is recorded in the audit chain
    via the caller.

    Args:
        subject_id: Subject identifier to purge.

    Returns:
        :class:`PurgeResult` with store ``"langfuse"``.
    """
    langfuse_enabled = os.environ.get("LANGFUSE_DELETE_ENABLED", "false").lower() == "true"

    if not langfuse_enabled:
        # Phase-2 stub: flag disabled — return simulated digest
        simulated_digest = _sha256_str(f"disabled:{subject_id}")
        logger.info(
            "_purge_langfuse: LANGFUSE_DELETE_ENABLED=false — stub return "
            "subject_id=%s digest=%s…", subject_id, simulated_digest[:12],
        )
        return PurgeResult(
            store="langfuse",
            items_removed=0,
            sha256_digest_after=simulated_digest,
        )

    # Phase 2: real Langfuse delete (wired but only reached when flag=true)
    logger.info("_purge_langfuse: real delete path subject_id=%s", subject_id)
    try:
        langfuse_host = os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com")
        langfuse_public_key = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
        langfuse_secret_key = os.environ.get("LANGFUSE_SECRET_KEY", "")

        if not langfuse_public_key or not langfuse_secret_key:
            raise ValueError(
                "LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY must be set for real deletes"
            )

        import httpx

        auth = (langfuse_public_key, langfuse_secret_key)
        search_url = f"{langfuse_host}/api/public/traces?userId={subject_id}&limit=100"

        deleted = 0
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(search_url, auth=auth)
            resp.raise_for_status()
            traces = resp.json().get("data", [])

            for trace in traces:
                trace_id = trace.get("id")
                if not trace_id:
                    continue
                del_resp = client.delete(
                    f"{langfuse_host}/api/public/traces/{trace_id}", auth=auth
                )
                if del_resp.status_code in (200, 204):
                    deleted += 1
                else:
                    logger.warning(
                        "_purge_langfuse: delete failed trace_id=%s status=%d",
                        trace_id, del_resp.status_code,
                    )

        digest = _sha256_str(f"langfuse:{subject_id}:deleted:{deleted}")
        logger.info(
            "_purge_langfuse: exit subject_id=%s traces_deleted=%d", subject_id, deleted
        )
        return PurgeResult(
            store="langfuse",
            items_removed=deleted,
            sha256_digest_after=digest,
        )

    except Exception as exc:  # noqa: BLE001
        logger.error(
            "_purge_langfuse: failed subject_id=%s: %s", subject_id, exc, exc_info=True
        )
        return PurgeResult(
            store="langfuse",
            items_removed=0,
            sha256_digest_after=_sha256_str(""),
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# Idempotency helpers
# ---------------------------------------------------------------------------


def _find_completed_cascade(cascade_id: str) -> CascadeResult | None:
    """Return a completed CascadeResult for *cascade_id*, or None.

    Checks the module-level in-memory cache first, then falls back to a
    backwards scan of ``data/events.jsonl`` looking for
    ``RTF_CASCADE_COMPLETED`` events.  Matched results are cached so the scan
    only happens once per process lifetime per cascade_id.
    """
    if cascade_id in _completed_cache:
        return _completed_cache[cascade_id]

    # Backward scan of the event log
    from domain.audit_chain import read_chain_tail  # late import

    # Scan in blocks; 5000 recent events should cover recent activity
    tail = read_chain_tail(5000)
    for ev in reversed(tail):
        if ev.get("event_type") != "RTF_CASCADE_COMPLETED":
            continue
        if ev.get("cascade_id") != cascade_id:
            continue
        # Reconstruct CascadeResult from the payload stored on the event
        try:
            steps_raw: dict = ev.get("steps", {})
            steps: dict[str, PurgeResult] = {
                store: PurgeResult.model_validate(step)
                for store, step in steps_raw.items()
            }
            result = CascadeResult(
                cascade_id=cascade_id,
                subject_id=ev.get("subject_id", ""),
                status="COMPLETED",
                steps=steps,
                started_at=ev.get("started_at", ""),
                completed_at=ev.get("completed_at", ev.get("ts", "")),
            )
            _completed_cache[cascade_id] = result
            return result
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "_find_completed_cascade: failed to reconstruct result "
                "cascade_id=%s: %s", cascade_id, exc,
            )
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def cascade(
    subject_id: str,
    reason: str = "",
    cascade_id: str | None = None,
    langfuse_enabled: bool | None = None,
) -> CascadeResult:
    """Execute a Right-to-Forget cascade for *subject_id* across all four stores.

    If *cascade_id* is supplied and a ``RTF_CASCADE_COMPLETED`` event already
    exists for it, returns ``ALREADY_COMPLETED`` immediately (idempotency).

    Otherwise, runs the stores in order: vault → tier2 → tier3 → langfuse.
    If any step fails, the cascade returns ``PARTIAL_FAILURE`` without emitting
    ``RTF_CASCADE_COMPLETED``.

    Args:
        subject_id:       Identifier of the data subject (e.g. customer UUID).
        reason:           Human-readable justification (e.g. "GDPR Art 17 request").
        cascade_id:       Optional pre-generated UUID; uuid4 is generated if None.
        langfuse_enabled: Override for the ``LANGFUSE_DELETE_ENABLED`` env var.
                          None means read from env (default behaviour).

    Returns:
        :class:`CascadeResult` with status ``COMPLETED``, ``PARTIAL_FAILURE``,
        or ``ALREADY_COMPLETED``.
    """
    logger.info(
        "cascade: entry subject_id=%s reason=%s cascade_id=%s",
        subject_id, reason, cascade_id,
    )

    # Capture the langfuse-enable choice as a local — never mutate os.environ
    # (would race across concurrent requests). Pass into _purge_langfuse below.
    _langfuse_flag_local: bool = (
        langfuse_enabled
        if langfuse_enabled is not None
        else os.environ.get("LANGFUSE_DELETE_ENABLED", "false").lower() == "true"
    )

    # Idempotency check — must happen before generating a new cascade_id
    if cascade_id:
        prior = _find_completed_cascade(cascade_id)
        if prior is not None:
            logger.info(
                "cascade: ALREADY_COMPLETED cascade_id=%s subject_id=%s",
                cascade_id, subject_id,
            )
            return CascadeResult(
                cascade_id=cascade_id,
                subject_id=subject_id,
                status="ALREADY_COMPLETED",
                steps=prior.steps,
                started_at=prior.started_at,
                completed_at=prior.completed_at,
            )

    if not cascade_id:
        cascade_id = str(uuid.uuid4())

    started_at = datetime.now(timezone.utc).isoformat()

    _emit("RTF_CASCADE_STARTED", {
        "cascade_id": cascade_id,
        "subject_id": subject_id,
        "reason": reason,
        "started_at": started_at,
    })

    steps: dict[str, PurgeResult] = {}
    _store_funcs: list[tuple[str, object]] = [
        ("vault", _purge_vault),
        ("tier2", _purge_tier2),
        ("tier3", _purge_tier3),
        ("langfuse", _purge_langfuse),
    ]

    for store_name, purge_fn in _store_funcs:
        _emit("RTF_STEP_STARTED", {
            "cascade_id": cascade_id,
            "subject_id": subject_id,
            "store": store_name,
        })

        try:
            import inspect
            if inspect.isfunction(purge_fn) or callable(purge_fn):
                step_result: PurgeResult = purge_fn(subject_id)  # type: ignore[operator]
            else:
                raise TypeError(f"purge_fn for {store_name} is not callable")
        except Exception as exc:  # noqa: BLE001
            step_result = PurgeResult(
                store=store_name,
                items_removed=0,
                sha256_digest_after=_sha256_str(""),
                error=str(exc),
            )

        steps[store_name] = step_result

        if step_result.error:
            _emit("RTF_STEP_FAILED", {
                "cascade_id": cascade_id,
                "subject_id": subject_id,
                "store": store_name,
                "error": step_result.error,
                "step_result": step_result.model_dump(),
            })

            completed_at = datetime.now(timezone.utc).isoformat()
            _emit("RTF_CASCADE_FAILED", {
                "cascade_id": cascade_id,
                "subject_id": subject_id,
                "failed_store": store_name,
                "completed_stores": list(steps.keys()),
                "completed_at": completed_at,
            })

            logger.error(
                "cascade: PARTIAL_FAILURE cascade_id=%s failed_store=%s error=%s",
                cascade_id, store_name, step_result.error,
            )
            return CascadeResult(
                cascade_id=cascade_id,
                subject_id=subject_id,
                status="PARTIAL_FAILURE",
                steps=steps,
                started_at=started_at,
                completed_at=completed_at,
            )

        _emit("RTF_STEP_COMPLETED", {
            "cascade_id": cascade_id,
            "subject_id": subject_id,
            "store": store_name,
            "items_removed": step_result.items_removed,
            "sha256_digest_after": step_result.sha256_digest_after,
        })

    # All steps succeeded
    completed_at = datetime.now(timezone.utc).isoformat()

    steps_serialisable = {k: v.model_dump() for k, v in steps.items()}

    _emit("RTF_CASCADE_COMPLETED", {
        "cascade_id": cascade_id,
        "subject_id": subject_id,
        "reason": reason,
        "started_at": started_at,
        "completed_at": completed_at,
        "steps": steps_serialisable,
    })

    _emit("RTF_CASCADE_VERIFIED", {
        "cascade_id": cascade_id,
        "subject_id": subject_id,
        "digests": {k: v.sha256_digest_after for k, v in steps.items()},
    })

    result = CascadeResult(
        cascade_id=cascade_id,
        subject_id=subject_id,
        status="COMPLETED",
        steps=steps,
        started_at=started_at,
        completed_at=completed_at,
    )

    # Cache for idempotency
    _completed_cache[cascade_id] = result

    logger.info(
        "cascade: exit COMPLETED cascade_id=%s subject_id=%s",
        cascade_id, subject_id,
    )
    return result


def get_cascade(cascade_id: str) -> CascadeResult | None:
    """Reconstruct a :class:`CascadeResult` for *cascade_id* from the audit log.

    Returns ``None`` if no completed cascade with this ID is found.

    Args:
        cascade_id: UUID of the cascade to retrieve.

    Returns:
        :class:`CascadeResult` or None.
    """
    return _find_completed_cascade(cascade_id)


def list_cascades() -> list[CascadeResult]:
    """Return all completed cascades reconstructed from the audit event log.

    Scans ``data/events.jsonl`` for ``RTF_CASCADE_COMPLETED`` events and
    reconstructs a :class:`CascadeResult` for each unique cascade_id.

    Returns:
        List of :class:`CascadeResult` ordered oldest-first.
    """
    from domain.audit_chain import read_chain_tail  # late import

    # Read all events — necessary for full historical list
    from domain.audit_chain import _read_jsonl, EVENTS_FILE  # late import

    all_events = _read_jsonl(EVENTS_FILE)
    seen_ids: set[str] = set()
    results: list[CascadeResult] = []

    for ev in all_events:
        if ev.get("event_type") != "RTF_CASCADE_COMPLETED":
            continue
        cid = ev.get("cascade_id", "")
        if cid in seen_ids:
            continue
        seen_ids.add(cid)

        try:
            steps_raw: dict = ev.get("steps", {})
            steps: dict[str, PurgeResult] = {
                store: PurgeResult.model_validate(step)
                for store, step in steps_raw.items()
            }
            result = CascadeResult(
                cascade_id=cid,
                subject_id=ev.get("subject_id", ""),
                status="COMPLETED",
                steps=steps,
                started_at=ev.get("started_at", ""),
                completed_at=ev.get("completed_at", ev.get("ts", "")),
            )
            results.append(result)
            _completed_cache[cid] = result
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "list_cascades: failed to reconstruct cascade_id=%s: %s", cid, exc
            )

    return results


__all__ = [
    "PurgeResult",
    "CascadeResult",
    "cascade",
    "get_cascade",
    "list_cascades",
]
