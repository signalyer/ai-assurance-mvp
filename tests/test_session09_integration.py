"""Session 09 end-to-end integration tests.

Asserts:
- SDK is importable as `signallayer` after editable install
- CLI module `sl` is importable
- Dashboard mounts the new projection + HMAC layers
- Projection code never writes JSONL (architectural invariant)
- Decorator chain order constant in production code is UNCHANGED
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent


def test_sdk_importable() -> None:
    """`signallayer` SDK package imports and exposes the public surface."""
    import sys

    sys.path.insert(0, str(REPO_ROOT / "sdk"))
    try:
        sl = importlib.import_module("signallayer")
        assert hasattr(sl, "init")
        assert hasattr(sl, "guard")
        assert hasattr(sl, "policy_gate")
        assert hasattr(sl, "scrub_pii")
        assert hasattr(sl, "guardrails")
        assert hasattr(sl, "__version__")
        assert sl.__version__ == "0.1.0"
    finally:
        sys.path.remove(str(REPO_ROOT / "sdk"))


def test_cli_importable() -> None:
    """`sl` CLI package imports."""
    import sys

    sys.path.insert(0, str(REPO_ROOT / "cli"))
    try:
        sl_cli = importlib.import_module("sl")
        assert hasattr(sl_cli, "__version__")
    finally:
        sys.path.remove(str(REPO_ROOT / "cli"))


def test_dashboard_mounts_session09_routers() -> None:
    """dashboard.app has projection router + HMAC middleware mounted."""
    import dashboard

    paths = {getattr(r, "path", None) for r in dashboard.app.routes}
    assert "/api/projection/status" in paths
    assert "/api/projection/replay" in paths

    middleware_class_names = [
        m.cls.__name__ for m in dashboard.app.user_middleware
    ]
    assert "HMACAuthMiddleware" in middleware_class_names
    assert "SessionAuthMiddleware" in middleware_class_names


def test_projection_never_writes_jsonl() -> None:
    """Architectural invariant: projection code is read-only against events.jsonl."""
    forbidden_patterns = [
        r"_append_jsonl\s*\(",
        r"open\([^)]*events\.jsonl[^)]*['\"]w",
        r"open\([^)]*events\.jsonl[^)]*['\"]a",
    ]
    targets = [
        REPO_ROOT / "domain" / "projection.py",
        REPO_ROOT / "domain" / "projection_worker.py",
    ]
    for path in targets:
        assert path.exists(), f"missing projection file: {path}"
        # Strip docstrings (naive triple-quote strip) before scanning code.
        text = path.read_text(encoding="utf-8")
        code = re.sub(r'"""[\s\S]*?"""', "", text)
        code = re.sub(r"'''[\s\S]*?'''", "", code)
        for pat in forbidden_patterns:
            assert not re.search(pat, code), (
                f"{path.name}: forbidden write-pattern {pat!r} found in code"
            )


def test_projection_never_joins_vault() -> None:
    """Architectural invariant: projection MUST NOT read vault.jsonl or raw prompts."""
    targets = [
        REPO_ROOT / "domain" / "projection.py",
        REPO_ROOT / "domain" / "projection_worker.py",
    ]
    for path in targets:
        text = path.read_text(encoding="utf-8")
        code = re.sub(r'"""[\s\S]*?"""', "", text)
        code = re.sub(r"'''[\s\S]*?'''", "", code)
        assert "vault.jsonl" not in code
        assert "raw_prompt" not in code


def test_decorator_chain_order_unchanged() -> None:
    """The five-stage chain order is still documented in ARCHITECTURE.md exactly."""
    arch = (REPO_ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")
    chain = "@policy_gate` → `@scrub_pii` → `@guardrails` → `@trace_llm_call` → `@evaluate_response"
    assert chain in arch, "Session 09 must not alter the decorator chain in ARCHITECTURE.md"


def test_hmac_middleware_module_exists() -> None:
    """`middleware.hmac_auth` exposes HMACAuthMiddleware class."""
    mod = importlib.import_module("middleware.hmac_auth")
    assert hasattr(mod, "HMACAuthMiddleware")


def test_projection_migration_present() -> None:
    """Migration SQL exists with all five domain tables + projection_state."""
    path = REPO_ROOT / "migrations" / "009_projection_views.sql"
    assert path.exists()
    sql = path.read_text(encoding="utf-8").lower()
    for table in ("ai_systems", "eval_runs", "findings", "release_decisions", "policy_evaluations", "projection_state"):
        assert table in sql, f"migration missing table: {table}"
    # Hybrid schema: JSONB column present
    assert "jsonb" in sql
    # GIN index requirement
    assert "using gin" in sql or "using  gin" in sql
