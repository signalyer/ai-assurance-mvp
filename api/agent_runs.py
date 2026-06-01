"""Agent Runs read API — S82f-1c minimal viewer.

GET /api/agent-runs/{run_id}
    Return the persisted per-run summary record for a previously streamed
    agent run. The record is appended to data/agent_runs.jsonl by the SSE
    wrapper in api.agent_runner._gen on chain.done.

GET /api/agent-runs
    Return the most recent N records (default 50, max 500), newest-first.
    Intended for an operator drill-down list adjacent to the Agent Runner
    UI; the calibration log's per-row run_id values resolve here.

Auth: read-only, role-gated to the same broad operator set as
api.agent_runner._RUNNER_ROLES. No mutation surface — listing audit-shape
data, not an admin verb.

Storage shape (one JSONL row per run, written on chain.done):
    {
        "run_id": "run-...",
        "agent_id": "vendor_risk",
        "system_id": "sys-vendor-risk-ext-001",
        "user": "praveen",
        "started_at": "...",
        "ended_at": "...",
        "outcome": "success" | "failure" | "review" | "denied" | "error",
        "audit_id": "aud-...",
        "operation_id": "...",
        "appinsights_url": "...",
        "langfuse_url": "...",
        "total_elapsed_ms": 1234.5,
        "events": [ {event dicts, in emission order} ]
    }

The full event list is preserved so the calibration row's structured fields
(risk_tier, concerns, citations) remain inspectable without re-running.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from middleware.auth import require_role

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent-runs", tags=["agent-runs"])

_DATA_DIR: Path = Path(os.environ.get("DATA_ROOT") or (Path(__file__).resolve().parents[1] / "data"))
_RUNS_FILE: Path = _DATA_DIR / "agent_runs.jsonl"

# Mirror api.agent_runner._RUNNER_ROLES — read viewer is operator-facing,
# same auth scope as the runner itself.
_VIEWER_ROLES: tuple[str, ...] = (
    "operator",
    "architect",
    "ciso",
    "auditor",
    "admin",
)


def _read_all_runs() -> list[dict[str, Any]]:
    """Read every persisted run record. Returns [] if the file is absent.

    Per project rule: JSONL reads go through storage.py helpers. This is a
    narrow read-side path; we use the helper to stay consistent with
    [[storage-only-jsonl-pattern]].
    """
    try:
        from storage import _read_jsonl
    except ImportError as exc:
        logger.error("agent_runs: storage helper unavailable: %s", exc)
        raise HTTPException(
            status_code=503,
            detail={"error": "Run store unavailable", "code": "STORAGE_UNAVAILABLE"},
        )
    if not _RUNS_FILE.exists():
        return []
    return _read_jsonl(_RUNS_FILE)


@router.get("")
async def list_runs(
    limit: int = Query(50, ge=1, le=500, description="Most-recent N runs to return"),
    agent_id: str | None = Query(None, description="Optional filter by agent_id"),
    system_id: str | None = Query(None, description="Optional filter by system_id"),
    _role: None = Depends(require_role(*_VIEWER_ROLES)),
) -> dict[str, Any]:
    """Return the most recent runs (newest-first), optionally filtered."""
    rows = _read_all_runs()
    if agent_id:
        rows = [r for r in rows if r.get("agent_id") == agent_id]
    if system_id:
        rows = [r for r in rows if r.get("system_id") == system_id]
    rows = list(reversed(rows))[:limit]
    return {"count": len(rows), "runs": rows}


@router.get("/{run_id}")
async def get_run(
    run_id: str,
    _role: None = Depends(require_role(*_VIEWER_ROLES)),
) -> dict[str, Any]:
    """Return the full persisted record for a single run, or 404."""
    for record in _read_all_runs():
        if record.get("run_id") == run_id:
            return record
    raise HTTPException(
        status_code=404,
        detail={"error": f"Run '{run_id}' not found", "code": "NOT_FOUND"},
    )
