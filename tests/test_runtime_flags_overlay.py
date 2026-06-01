"""S82f-2 — runtime-flag overlay + dispatcher-injection regression.

Closes the SOP Phase 8 failure-mode drill (ADR-004 §5):

    (a) attest via PATCH       → policy_gate ALLOW
    (b) let TTL expire         → policy_gate DENY  (workload_required_flag_not_set)
    (c) re-attest              → policy_gate ALLOW

These tests exercise the OVERLAY STORE + REPOSITORY FOLD layers in
isolation, then drive the SAME inputs the dispatcher would build through
`domain.policy_engine.evaluate` to prove the end-to-end story.

This is intentionally a separate file from `test_policy_vendor_risk.py`,
which tests the rego loader + policy_engine in isolation. That file
already covers "missing flag → DENY" at the policy layer; this file
covers "no overlay row → dispatcher injects False → DENY" at the
storage+dispatcher layer, which is the layer ADR-004 Option B actually
delivers.

Per [[rego-files-were-decorative]]: the first test for any new
control-plane surface MUST be a negative-test DENY. The overlay-empty
case here is that test.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# Pin OPA off so policy_engine exercises the local Python evaluator path
# (matches test_policy_vendor_risk.py:39).
os.environ.pop("OPA_URL", None)

from domain import rego_loader
from domain.models import RuntimeFlags
from domain.policy_engine import Decision, evaluate
from domain.repository import get_ai_system

INT_ID = "sys-vendor-risk-int-001"


@pytest.fixture
def isolated_overlay(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect the runtime-flags overlay to a tmp file for the test.

    storage.SYSTEM_RUNTIME_FLAGS_FILE is resolved at import time from
    STORAGE_DIR. We monkeypatch the module-level constant so writes go
    to tmp_path and reads see only this test's rows. The audit-chain
    write in patch_system_runtime_flags is also redirected via DATA_ROOT
    so the test never touches the real events.jsonl.
    """
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    # Re-import after env change so STORAGE_DIR + SYSTEM_RUNTIME_FLAGS_FILE
    # pick up the new path. The audit_chain module reads DATA_ROOT at
    # import-time too, so its _DATA_DIR also needs refresh; the cache
    # invariant in audit_chain handles seeded-from-different-path.
    import importlib

    import storage as storage_mod
    import domain.audit_chain as audit_chain_mod

    importlib.reload(storage_mod)
    importlib.reload(audit_chain_mod)
    rego_loader.clear_cache()
    yield storage_mod
    rego_loader.clear_cache()


def _build_int_policy_input(flags: RuntimeFlags | None) -> dict:
    """Mirror the dispatcher's input-shaping logic (agent_runner.py:200-225)."""
    return {
        "prompt": "Assess vendor X for INT use.",
        "operator_role": "ciso",
        "dlp_completed": bool(flags.dlp_completed) if flags else False,
        "network_egress_lock_engaged": (
            bool(flags.network_egress_lock_engaged) if flags else False
        ),
    }


# ---------------------------------------------------------------------------
# Storage overlay — direct unit tests
# ---------------------------------------------------------------------------

def test_overlay_empty_returns_none(isolated_overlay) -> None:
    """Negative baseline: an empty overlay yields no attestation."""
    assert isolated_overlay.read_system_runtime_flags(INT_ID) is None


def test_overlay_patch_then_read_roundtrips(isolated_overlay) -> None:
    """PATCH writes the row + reads back as the latest non-expired."""
    now = datetime.now(timezone.utc)
    flags = RuntimeFlags(
        dlp_completed=True,
        network_egress_lock_engaged=True,
        attested_by="demo-ciso",
        attested_at=now,
        justification="test_overlay_patch_then_read_roundtrips",
        expires_at=now + timedelta(hours=1),
    )
    isolated_overlay.patch_system_runtime_flags(INT_ID, flags)
    read = isolated_overlay.read_system_runtime_flags(INT_ID)
    assert read is not None
    assert read.dlp_completed is True
    assert read.network_egress_lock_engaged is True
    assert read.attested_by == "demo-ciso"


def test_overlay_expired_latest_returns_none(isolated_overlay) -> None:
    """ADR-004 §5 deny-on-expiry: the latest row's expires_at gates everything."""
    now = datetime.now(timezone.utc)
    expired = RuntimeFlags(
        dlp_completed=True,
        network_egress_lock_engaged=True,
        attested_by="demo-ciso",
        attested_at=now,
        justification="expired",
        expires_at=now - timedelta(seconds=1),
    )
    isolated_overlay.patch_system_runtime_flags(INT_ID, expired)
    assert isolated_overlay.read_system_runtime_flags(INT_ID) is None


def test_overlay_latest_wins_even_when_newer_is_expired(isolated_overlay) -> None:
    """Older valid row must NOT shadow a newer expired row.

    Semantics: the operator's most recent attestation is authoritative.
    If they last attested an expired-in-the-past row (or did not refresh
    in time), the system DENIES — there is no "fall back to the
    still-valid previous attestation" path, because that would defeat
    the failure-mode drill.
    """
    now = datetime.now(timezone.utc)
    isolated_overlay.patch_system_runtime_flags(
        INT_ID,
        RuntimeFlags(
            dlp_completed=True,
            network_egress_lock_engaged=True,
            attested_by="demo-ciso",
            attested_at=now - timedelta(minutes=30),
            justification="older valid",
            expires_at=now + timedelta(hours=24),
        ),
    )
    isolated_overlay.patch_system_runtime_flags(
        INT_ID,
        RuntimeFlags(
            dlp_completed=True,
            network_egress_lock_engaged=True,
            attested_by="demo-ciso",
            attested_at=now - timedelta(minutes=1),
            justification="newer expired",
            expires_at=now - timedelta(seconds=1),
        ),
    )
    assert isolated_overlay.read_system_runtime_flags(INT_ID) is None


def test_repository_fold_surfaces_flags(isolated_overlay) -> None:
    """domain.repository.get_ai_system folds the overlay onto AISystem."""
    now = datetime.now(timezone.utc)
    flags = RuntimeFlags(
        dlp_completed=True,
        network_egress_lock_engaged=True,
        attested_by="demo-tprm-analyst",
        attested_at=now,
        justification="fold check",
        expires_at=now + timedelta(hours=1),
    )
    isolated_overlay.patch_system_runtime_flags(INT_ID, flags)
    sys = get_ai_system(INT_ID)
    assert sys is not None
    assert sys.runtime_flags is not None
    assert sys.runtime_flags.attested_by == "demo-tprm-analyst"


# ---------------------------------------------------------------------------
# End-to-end drill (ADR-004 §5): attest → ALLOW · expire → DENY · re-attest → ALLOW
# ---------------------------------------------------------------------------

def test_drill_attest_then_allow(isolated_overlay) -> None:
    """(a) attest via PATCH → dispatcher-shaped input ALLOWs."""
    now = datetime.now(timezone.utc)
    isolated_overlay.patch_system_runtime_flags(
        INT_ID,
        RuntimeFlags(
            dlp_completed=True,
            network_egress_lock_engaged=True,
            attested_by="demo-ciso",
            attested_at=now,
            justification="drill (a)",
            expires_at=now + timedelta(hours=24),
        ),
    )
    flags = isolated_overlay.read_system_runtime_flags(INT_ID)
    r = evaluate(INT_ID, "agent_run", _build_int_policy_input(flags))
    assert r.decision == Decision.ALLOW, (
        f"expected ALLOW with valid attestation, got {r.decision} "
        f"policy_name={r.policy_name} reason={r.reason}"
    )


def test_drill_expired_then_deny(isolated_overlay) -> None:
    """(b) latest attestation is expired → dispatcher injects False → DENY."""
    now = datetime.now(timezone.utc)
    isolated_overlay.patch_system_runtime_flags(
        INT_ID,
        RuntimeFlags(
            dlp_completed=True,
            network_egress_lock_engaged=True,
            attested_by="demo-ciso",
            attested_at=now,
            justification="drill (b)",
            expires_at=now - timedelta(seconds=1),
        ),
    )
    flags = isolated_overlay.read_system_runtime_flags(INT_ID)
    assert flags is None, "overlay read must report None on expiry"
    r = evaluate(INT_ID, "agent_run", _build_int_policy_input(flags))
    assert r.decision == Decision.DENY
    assert r.policy_name == "workload_required_flag_not_set"


def test_drill_reattest_then_allow(isolated_overlay) -> None:
    """(c) PATCH again after expiry → ALLOW restored on next chain call."""
    now = datetime.now(timezone.utc)
    # Step b state: expired latest
    isolated_overlay.patch_system_runtime_flags(
        INT_ID,
        RuntimeFlags(
            dlp_completed=True,
            network_egress_lock_engaged=True,
            attested_by="demo-ciso",
            attested_at=now - timedelta(minutes=5),
            justification="drill (c) prior expired",
            expires_at=now - timedelta(seconds=1),
        ),
    )
    # Step c: re-attest
    isolated_overlay.patch_system_runtime_flags(
        INT_ID,
        RuntimeFlags(
            dlp_completed=True,
            network_egress_lock_engaged=True,
            attested_by="demo-ciso",
            attested_at=now,
            justification="drill (c) re-attest",
            expires_at=now + timedelta(hours=24),
        ),
    )
    flags = isolated_overlay.read_system_runtime_flags(INT_ID)
    assert flags is not None
    r = evaluate(INT_ID, "agent_run", _build_int_policy_input(flags))
    assert r.decision == Decision.ALLOW


# ---------------------------------------------------------------------------
# Dispatcher-shape regression — the cheap-and-canonical negative test
# ---------------------------------------------------------------------------

def test_dispatcher_shape_with_no_overlay_denies(isolated_overlay) -> None:
    """The exact policy_input the dispatcher would build with an empty overlay.

    This is the test ADR-004 §5 directly asks for: prove that a vendor_risk
    INT call with no PATCH'd attestation is DENIED at policy_gate with the
    expected rule name. Storage layer + dispatcher layer + rego must all
    agree.
    """
    flags = isolated_overlay.read_system_runtime_flags(INT_ID)
    assert flags is None
    r = evaluate(INT_ID, "agent_run", _build_int_policy_input(flags))
    assert r.decision == Decision.DENY
    assert r.policy_name == "workload_required_flag_not_set"
    missing = set(r.metadata.get("missing_flags", []))
    assert {"dlp_completed", "network_egress_lock_engaged"} <= missing
