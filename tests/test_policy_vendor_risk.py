"""S82b Phase 3 — vendor_risk policy tests.

Per [[rego-files-were-decorative]] (S60 F-024), the first test for any new
policy file MUST be a negative-test DENY against a live call. "The file
loaded" is not proof of enforcement.

These tests exercise BOTH the data-loading path (rego_loader parsing the
.rego files) AND the enforcement path (policy_engine.evaluate making
DENY/ALLOW decisions on representative inputs).

Coverage per rego file:
  ext (sys-vendor-risk-ext-001):
    - tool allowlist DENY + ALLOW
    - mutation verb DENY
    - denied_token_types DENY (INTERNAL_SYSTEMS / MNPI / CREDIT_DATA)
    - required_operator_roles DENY + ALLOW
    - max_prompt_tokens cap DENY
    - max_injection_score_pct DENY
    - max_llm_calls_per_run DENY
    - clean-path ALLOW (the positive baseline)

  int (sys-vendor-risk-int-001):
    - tool allowlist DENY + ALLOW
    - mutation verb DENY
    - stricter operator role allowlist (admin denied)
    - required_true_flags DENY (network_egress_lock_engaged missing)
    - denied_url_substrings DENY (URL in tool args)
    - clean-path ALLOW
"""

from __future__ import annotations

import os

import pytest

# F-024 enforcement runs in the local Python evaluator path. Pin OPA_URL
# off so the tests exercise _check_workload_specific directly, not OPA.
os.environ.pop("OPA_URL", None)

from domain import rego_loader
from domain.policy_engine import Decision, evaluate

EXT_ID = "sys-vendor-risk-ext-001"
INT_ID = "sys-vendor-risk-int-001"


@pytest.fixture(autouse=True)
def _clear_rego_cache() -> None:
    """Force re-parse of rego files between tests so authored edits don't
    silently leak via @lru_cache."""
    rego_loader.clear_cache()
    yield
    rego_loader.clear_cache()


# ---------------------------------------------------------------------------
# Loader smoke — both files parse to the expected data shapes
# ---------------------------------------------------------------------------

def test_loader_parses_ext_rego() -> None:
    _, data = rego_loader.resolve_workload_policy(EXT_ID)
    assert isinstance(data.get("vendor_risk_ext_tools"), set)
    assert "search_tprm_corpus" in data["vendor_risk_ext_tools"]
    assert isinstance(data.get("mutation_verbs"), list)
    assert "create_" in data["mutation_verbs"]
    assert data.get("denied_token_types") == {"INTERNAL_SYSTEMS", "MNPI", "CREDIT_DATA"}
    assert data.get("required_operator_roles") == {"tprm-analyst", "ciso", "admin"}
    assert data.get("max_prompt_tokens") == 32000
    assert data.get("max_injection_score_pct") == 70
    assert data.get("max_llm_calls_per_run") == 25


def test_loader_parses_int_rego() -> None:
    _, data = rego_loader.resolve_workload_policy(INT_ID)
    assert isinstance(data.get("vendor_risk_int_tools"), set)
    assert "search_tprm_corpus" in data["vendor_risk_int_tools"]
    # Stricter: admin NOT in the internal allowlist
    assert data.get("required_operator_roles") == {"tprm-analyst", "ciso"}
    assert data.get("required_true_flags") == {
        "network_egress_lock_engaged",
        "dlp_completed",
    }
    assert isinstance(data.get("denied_url_substrings"), list)
    assert "https://" in data["denied_url_substrings"]
    # denied_token_types intentionally absent on internal path
    assert data.get("denied_token_types") is None


def test_unknown_system_id_falls_through() -> None:
    name, data = rego_loader.resolve_workload_policy("sys-something-else-001")
    assert name is None
    assert data == {}


# ---------------------------------------------------------------------------
# External system — DENY cases
# ---------------------------------------------------------------------------

def test_ext_tool_not_in_allowlist_denies() -> None:
    r = evaluate(EXT_ID, "tool_invoke", {
        "operator_role": "tprm-analyst",
        "tool_name": "fetch_random_internet_thing",
    })
    assert r.decision == Decision.DENY
    assert r.policy_name == "workload_tool_not_allowlisted"


def test_ext_mutation_verb_denies() -> None:
    r = evaluate(EXT_ID, "tool_invoke", {
        "operator_role": "tprm-analyst",
        "tool_name": "delete_vendor_record",
    })
    assert r.decision == Decision.DENY
    assert r.policy_name == "workload_mutation_verb_blocked"
    assert r.metadata.get("matched_verb") == "delete_"


@pytest.mark.parametrize("denied_type", ["INTERNAL_SYSTEMS", "MNPI", "CREDIT_DATA"])
def test_ext_denied_token_type_denies(denied_type: str) -> None:
    r = evaluate(EXT_ID, "agent_run", {
        "operator_role": "tprm-analyst",
        "redacted_token_types": ["EMAIL", denied_type, "PHONE"],
    })
    assert r.decision == Decision.DENY
    assert r.policy_name == "workload_denied_token_type"
    assert denied_type in r.metadata.get("denied_token_types", [])


def test_ext_operator_role_not_allowed_denies() -> None:
    r = evaluate(EXT_ID, "agent_run", {
        "operator_role": "marketing-intern",
        "redacted_token_types": [],
    })
    assert r.decision == Decision.DENY
    assert r.policy_name == "workload_operator_role_not_allowed"


def test_ext_admin_role_allowed_on_external_path() -> None:
    """Admin is in the external allowlist (it is NOT in the internal one)."""
    r = evaluate(EXT_ID, "agent_run", {
        "operator_role": "admin",
        "redacted_token_types": [],
    })
    assert r.decision == Decision.ALLOW


def test_ext_prompt_token_cap_denies() -> None:
    r = evaluate(EXT_ID, "llm_call", {
        "operator_role": "tprm-analyst",
        "redacted_token_types": [],
        "prompt_token_count": 32001,
    })
    assert r.decision == Decision.DENY
    assert r.policy_name == "workload_prompt_token_cap_exceeded"


def test_ext_injection_score_over_threshold_denies() -> None:
    r = evaluate(EXT_ID, "llm_call", {
        "operator_role": "tprm-analyst",
        "redacted_token_types": [],
        "prompt_injection_score_pct": 85,
    })
    assert r.decision == Decision.DENY
    assert r.policy_name == "workload_injection_score_exceeded"


def test_ext_llm_call_budget_exceeded_denies() -> None:
    r = evaluate(EXT_ID, "llm_call", {
        "operator_role": "tprm-analyst",
        "redacted_token_types": [],
        "run_call_count": 26,
    })
    assert r.decision == Decision.DENY
    assert r.policy_name == "workload_llm_call_budget_exceeded"


# ---------------------------------------------------------------------------
# External system — ALLOW (positive baseline; catches over-restriction)
# ---------------------------------------------------------------------------

def test_ext_clean_path_allows() -> None:
    r = evaluate(EXT_ID, "agent_run", {
        "operator_role": "tprm-analyst",
        "redacted_token_types": ["EMAIL", "PERSON"],  # benign types
        "prompt_token_count": 4000,
        "prompt_injection_score_pct": 5,
        "run_call_count": 3,
    })
    assert r.decision == Decision.ALLOW


def test_ext_allowed_tool_invoke_allows() -> None:
    r = evaluate(EXT_ID, "tool_invoke", {
        "operator_role": "tprm-analyst",
        "tool_name": "search_tprm_corpus",
    })
    assert r.decision == Decision.ALLOW


# ---------------------------------------------------------------------------
# Internal system — DENY cases
# ---------------------------------------------------------------------------

def test_int_tool_not_in_allowlist_denies() -> None:
    r = evaluate(INT_ID, "tool_invoke", {
        "operator_role": "tprm-analyst",
        "tool_name": "exfiltrate_to_pastebin",
    })
    assert r.decision == Decision.DENY
    assert r.policy_name == "workload_tool_not_allowlisted"


def test_int_admin_role_denied() -> None:
    """Internal path is stricter than external — admin not allowed."""
    r = evaluate(INT_ID, "agent_run", {
        "operator_role": "admin",
        "network_egress_lock_engaged": True,
        "dlp_completed": True,
    })
    assert r.decision == Decision.DENY
    assert r.policy_name == "workload_operator_role_not_allowed"


def test_int_required_egress_flag_missing_denies() -> None:
    r = evaluate(INT_ID, "agent_run", {
        "operator_role": "tprm-analyst",
        # network_egress_lock_engaged intentionally omitted
        "dlp_completed": True,
    })
    assert r.decision == Decision.DENY
    assert r.policy_name == "workload_required_flag_not_set"
    assert "network_egress_lock_engaged" in r.metadata.get("missing_flags", [])


def test_int_required_dlp_flag_missing_denies() -> None:
    r = evaluate(INT_ID, "agent_run", {
        "operator_role": "tprm-analyst",
        "network_egress_lock_engaged": True,
        "dlp_completed": False,
    })
    assert r.decision == Decision.DENY
    assert r.policy_name == "workload_required_flag_not_set"
    assert "dlp_completed" in r.metadata.get("missing_flags", [])


def test_int_denied_url_substring_in_tool_args_denies() -> None:
    r = evaluate(INT_ID, "tool_invoke", {
        "operator_role": "tprm-analyst",
        "tool_name": "search_tprm_corpus",
        "tool_args_text": '{"query": "fetch from https://api.anthropic.com/v1"}',
    })
    assert r.decision == Decision.DENY
    assert r.policy_name == "workload_denied_url_in_tool_args"


def test_int_internal_tokens_DO_NOT_deny() -> None:
    """The whole point of the internal path is to handle INTERNAL_SYSTEMS /
    MNPI tokens. The rego must NOT carry a denied_token_types rule for them.
    Regression guard: if someone copies the ext rego pattern over, this
    test catches it."""
    r = evaluate(INT_ID, "agent_run", {
        "operator_role": "tprm-analyst",
        "network_egress_lock_engaged": True,
        "dlp_completed": True,
        "redacted_token_types": ["INTERNAL_SYSTEMS", "MNPI"],
    })
    assert r.decision == Decision.ALLOW


# ---------------------------------------------------------------------------
# Internal system — ALLOW
# ---------------------------------------------------------------------------

def test_int_clean_path_allows() -> None:
    r = evaluate(INT_ID, "agent_run", {
        "operator_role": "ciso",
        "network_egress_lock_engaged": True,
        "dlp_completed": True,
        "redacted_token_types": ["INTERNAL_SYSTEMS", "EMAIL"],
        "prompt_token_count": 8000,
        "run_call_count": 2,
    })
    assert r.decision == Decision.ALLOW


def test_int_allowed_tool_invoke_with_clean_args_allows() -> None:
    r = evaluate(INT_ID, "tool_invoke", {
        "operator_role": "tprm-analyst",
        "tool_name": "lookup_subprocessor_risk",
        "tool_args_text": '{"vendor": "ACME Corp", "domain": "saas-billing"}',
    })
    assert r.decision == Decision.ALLOW
