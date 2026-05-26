"""Data-mode middleware for V1 (seeded demo portfolio) vs V2 (real customer systems).

Session 52 — V1/V2 data-mode toggle.

The SPA Topbars carry a localStorage-backed toggle (`aigovern_data_mode`)
and inject `X-Data-Mode: v1|v2` into every API request via the shared
`apiRequest` helpers. The engine reads the header here and filters list
endpoints server-side so the SPA is never the source of truth for what
is visible.

Tolerance rules (locked in S52 plan):
- Missing or malformed header => treat as "v1" (backward compat).
- Rows lacking a `source` key => treated as "seed" (legacy mock_data).
- V1 mode = no filter (every row visible).
- V2 mode = only rows whose source == "real".

The filter helper accepts both dict rows (legacy mock_data style) and
Pydantic model instances (intake-persisted style) so it can sit in front
of every list endpoint regardless of layer.
"""

from __future__ import annotations

from typing import Any, Iterable, Literal

from fastapi import Request


DataMode = Literal["v1", "v2"]

_VALID_MODES: frozenset[str] = frozenset({"v1", "v2"})


def get_data_mode(request: Request) -> DataMode:
    """Read X-Data-Mode header. Defaults to 'v1' on missing/malformed.

    Never raises — the toggle is a kill switch; the engine must keep
    serving even if the SPA sends a malformed header.
    """
    raw = request.headers.get("X-Data-Mode") or request.headers.get("x-data-mode")
    if not raw:
        return "v1"
    value = raw.strip().lower()
    if value not in _VALID_MODES:
        return "v1"
    return value  # type: ignore[return-value]


def _row_data_source(row: Any) -> str:
    """Extract `data_source` from a row (dict or Pydantic model).

    Missing => 'seed' (legacy mock_data and any row that pre-dates S52).
    Named `data_source` rather than `source` because `Evidence.source`
    already means 'tool that produced the evidence' — different concept.
    """
    if isinstance(row, dict):
        return row.get("data_source") or "seed"
    return getattr(row, "data_source", None) or "seed"


def filter_by_mode(rows: Iterable[Any], mode: DataMode) -> list[Any]:
    """Filter a row stream by data mode.

    V1 => return rows unchanged (every row visible).
    V2 => return only rows whose `data_source` is "real".

    Tolerant: rows missing the field are treated as "seed" and thus
    invisible in V2.
    """
    materialized = list(rows)
    if mode == "v1":
        return materialized
    return [r for r in materialized if _row_data_source(r) == "real"]


__all__ = ["DataMode", "get_data_mode", "filter_by_mode"]
