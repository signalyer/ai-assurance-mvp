"""Package version. Single source of truth for FastAPI(version=...) and OpenAPI info.version.

Bump rule (per docs/plans/SESSION-13-api-typing-audit.md §6.4):
    - new optional field on a response model: patch (2.0.0-phase1 -> 2.0.1-phase1)
    - new required field, new endpoint, new operationId: minor (2.0.0-phase1 -> 2.1.0-phase1)
    - removed/renamed field, removed endpoint, breaking shape change: major (2.0.0 -> 3.0.0)

Phase suffix tracks V2-PORTAL-SPLIT.md phase. Dropped at Phase 5 DNS cutover.
"""
from __future__ import annotations

__version__ = "2.0.0-phase1"
