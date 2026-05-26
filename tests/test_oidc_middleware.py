"""Tests for middleware/oidc.py — group/UPN/overage resolution + denial paths.

Coverage:
    - resolve_role_from_groups: CISO / engineer / both / neither / unknown OIDs.
    - extract_upn_from_claims: preferred_username / upn / email precedence,
      missing-all error path.
    - is_group_overage: _claim_names referencing groups vs other claims vs absent.
    - _group_role_map: fail-loudly when env vars missing.
    - is_oidc_enabled: presence check on the three required env vars.

Does NOT cover: the live authlib token exchange (no Entra tenant in CI).
Callback-handler integration tests are in tests/test_oidc_callback.py
(deferred — requires mocking authlib's request.session usage end-to-end).
"""

from __future__ import annotations

import pytest

from middleware import oidc as oidc_mod


CISO_OID = "ciso-group-oid-aaaa-1111"
TEAM_OID = "team-group-oid-bbbb-2222"
UNKNOWN_OID = "unknown-oid-cccc-3333"


@pytest.fixture(autouse=True)
def _set_group_oids(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure both group-OID env vars are set for every test by default.

    Tests that want to exercise the missing-env path override these inside
    the test body via monkeypatch.delenv.
    """
    monkeypatch.setenv("OIDC_CISO_CONSOLE_GROUP_OID", CISO_OID)
    monkeypatch.setenv("OIDC_TEAM_PORTAL_GROUP_OID", TEAM_OID)
    # Reset the authlib registry cache between tests since OIDC_* env vars
    # are monkeypatched per test and a stale registry would shadow them.
    oidc_mod._reset_cache_for_tests()


# ---------------------------------------------------------------------------
# resolve_role_from_groups
# ---------------------------------------------------------------------------


def test_resolve_role_ciso_group_only() -> None:
    assert oidc_mod.resolve_role_from_groups([CISO_OID]) == "ciso"


def test_resolve_role_team_group_only() -> None:
    assert oidc_mod.resolve_role_from_groups([TEAM_OID]) == "engineer"


def test_resolve_role_both_groups_ciso_wins() -> None:
    """User in both portal groups gets CISO Console (higher-privilege landing)."""
    assert oidc_mod.resolve_role_from_groups([CISO_OID, TEAM_OID]) == "ciso"
    assert oidc_mod.resolve_role_from_groups([TEAM_OID, CISO_OID]) == "ciso"


def test_resolve_role_no_matching_groups() -> None:
    """No portal group → None (caller must treat as denial)."""
    assert oidc_mod.resolve_role_from_groups([UNKNOWN_OID]) is None
    assert oidc_mod.resolve_role_from_groups([]) is None


def test_resolve_role_unknown_oids_mixed_with_known() -> None:
    """Unknown OIDs alongside a known one don't interfere."""
    assert oidc_mod.resolve_role_from_groups([UNKNOWN_OID, TEAM_OID]) == "engineer"
    assert oidc_mod.resolve_role_from_groups([UNKNOWN_OID, CISO_OID]) == "ciso"


def test_resolve_role_raises_when_env_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing CISO group OID env → RuntimeError, not silent default."""
    monkeypatch.delenv("OIDC_CISO_CONSOLE_GROUP_OID", raising=False)
    with pytest.raises(RuntimeError, match="OIDC_CISO_CONSOLE_GROUP_OID"):
        oidc_mod.resolve_role_from_groups([TEAM_OID])


# ---------------------------------------------------------------------------
# extract_upn_from_claims
# ---------------------------------------------------------------------------


def test_extract_upn_prefers_preferred_username() -> None:
    claims = {
        "preferred_username": "Praveen@SignalLayer.AI",
        "upn": "should-not-win@signallayer.ai",
        "email": "also-should-not-win@signallayer.ai",
    }
    assert oidc_mod.extract_upn_from_claims(claims) == "praveen@signallayer.ai"


def test_extract_upn_falls_back_to_upn() -> None:
    claims = {"upn": "Pravdev@signallayer.ai"}
    assert oidc_mod.extract_upn_from_claims(claims) == "pravdev@signallayer.ai"


def test_extract_upn_falls_back_to_email() -> None:
    claims = {"email": "Rajesh@signallayer.ai"}
    assert oidc_mod.extract_upn_from_claims(claims) == "rajesh@signallayer.ai"


def test_extract_upn_skips_empty_strings() -> None:
    """Empty/whitespace preferred_username should not win over a real upn."""
    claims = {"preferred_username": "  ", "upn": "real@signallayer.ai"}
    assert oidc_mod.extract_upn_from_claims(claims) == "real@signallayer.ai"


def test_extract_upn_raises_when_all_missing() -> None:
    with pytest.raises(ValueError, match="preferred_username/upn/email"):
        oidc_mod.extract_upn_from_claims({})


def test_extract_upn_raises_when_non_string_values() -> None:
    """Non-string values (e.g. None or list) should not be accepted."""
    claims = {"preferred_username": None, "upn": [], "email": 42}
    with pytest.raises(ValueError):
        oidc_mod.extract_upn_from_claims(claims)


# ---------------------------------------------------------------------------
# is_group_overage
# ---------------------------------------------------------------------------


def test_overage_detected_when_claim_names_references_groups() -> None:
    claims = {"_claim_names": {"groups": "src1"}, "_claim_sources": {"src1": {"endpoint": "..."}}}
    assert oidc_mod.is_group_overage(claims) is True


def test_overage_false_when_claim_names_references_other_claims() -> None:
    """_claim_names exists but doesn't reference groups → not an overage we handle."""
    claims = {"_claim_names": {"roles": "src1"}}
    assert oidc_mod.is_group_overage(claims) is False


def test_overage_false_when_claim_names_absent() -> None:
    assert oidc_mod.is_group_overage({}) is False


def test_overage_false_when_claim_names_not_a_dict() -> None:
    """Defensive: _claim_names should be a dict; anything else is treated as absent."""
    assert oidc_mod.is_group_overage({"_claim_names": "not-a-dict"}) is False
    assert oidc_mod.is_group_overage({"_claim_names": None}) is False


# ---------------------------------------------------------------------------
# is_oidc_enabled
# ---------------------------------------------------------------------------


def test_oidc_enabled_when_all_three_vars_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OIDC_TENANT_ID", "tenant-guid")
    monkeypatch.setenv("OIDC_CLIENT_ID", "client-guid")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "secret")
    assert oidc_mod.is_oidc_enabled() is True


def test_oidc_disabled_when_any_var_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OIDC_TENANT_ID", "tenant-guid")
    monkeypatch.setenv("OIDC_CLIENT_ID", "client-guid")
    monkeypatch.delenv("OIDC_CLIENT_SECRET", raising=False)
    assert oidc_mod.is_oidc_enabled() is False


def test_oidc_disabled_when_var_is_empty_string(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty string env var (not just missing) also disables OIDC."""
    monkeypatch.setenv("OIDC_TENANT_ID", "tenant-guid")
    monkeypatch.setenv("OIDC_CLIENT_ID", "client-guid")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "   ")
    assert oidc_mod.is_oidc_enabled() is False


# ---------------------------------------------------------------------------
# Mask helper (operational logging sanity)
# ---------------------------------------------------------------------------


def test_mask_oid_returns_last_six_chars() -> None:
    assert oidc_mod._mask_oid("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee") == "…eeeeee"


def test_mask_oid_short_value() -> None:
    """Short value (shouldn't happen for real OIDs) doesn't leak."""
    assert oidc_mod._mask_oid("abc") == "…"
