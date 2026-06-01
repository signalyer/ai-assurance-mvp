"""Unit tests for vendor_risk tools + output-coercion contract (S82d).

These tests run deterministically without touching the Anthropic API.
The full eval suite (`agents.vendor_risk.eval.run_eval`) does hit Anthropic
and writes baseline.json — those live runs are the S82d exit criteria,
but they are NOT part of the unit test suite (cost + flakiness).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.vendor_risk import tools
from agents.vendor_risk.agent import _coerce_output
from agents.vendor_risk.prompts import SYSTEM_ID_EXT, SYSTEM_ID_INT, TOOL_SPECS


# --- prompts.py --------------------------------------------------------------


def test_tool_specs_cover_six_tools():
    names = {spec["name"] for spec in TOOL_SPECS}
    assert names == {
        "search_tprm_corpus",
        "lookup_subprocessor_risk",
        "parse_vendor_document",
        "check_regulatory_requirements",
        "compare_to_baseline",
        "escalate_to_human",
    }


def test_system_ids_match_seed():
    assert SYSTEM_ID_EXT == "sys-vendor-risk-ext-001"
    assert SYSTEM_ID_INT == "sys-vendor-risk-int-001"


# --- tools.search_tprm_corpus -----------------------------------------------


def test_search_returns_at_least_one_hit_on_carve_out_query():
    result = tools.search_tprm_corpus({"query": "carve-out DPA subprocessor SCC", "top_k": 5})
    assert "results" in result
    doc_ids = [r["doc_id"] for r in result["results"]]
    # The carve-out playbook should rank in the top-K.
    assert "carve-out-playbook" in doc_ids


def test_search_handles_empty_query():
    result = tools.search_tprm_corpus({"query": ""})
    assert "error" in result


def test_search_top_k_clamped():
    result = tools.search_tprm_corpus({"query": "SOC2 Type II", "top_k": 100})
    assert len(result["results"]) <= 10


# --- tools.lookup_subprocessor_risk -----------------------------------------


def test_lookup_known_subprocessor():
    result = tools.lookup_subprocessor_risk({"vendor_name": "AWS Inc."})
    assert result["vendor_name"] == "AWS Inc."
    assert "risk_score" in result
    assert 0 <= result["risk_score"] <= 100


def test_lookup_high_risk_subprocessor_has_known_issues():
    result = tools.lookup_subprocessor_risk({"vendor_name": "RogueStore Ltd"})
    assert result["risk_score"] >= 80
    assert len(result["known_issues"]) > 0


def test_lookup_unknown_subprocessor_returns_error():
    result = tools.lookup_subprocessor_risk({"vendor_name": "DoesNotExist Inc."})
    assert "error" in result


# --- tools.parse_vendor_document --------------------------------------------


def test_parse_vendor_document_without_fixture_returns_error():
    result = tools.parse_vendor_document({"doc_type": "dpa"}, fixture_meta=None)
    assert "error" in result


def test_parse_vendor_document_present_doc():
    meta = tools.load_fixture_meta("fixtures/05-edge-carveout-eu/")
    result = tools.parse_vendor_document({"doc_type": "dpa"}, fixture_meta=meta)
    assert result["metadata"]["present"] is True
    # The carve-out fixture's DPA must mention EuroDataPro per the generator.
    assert "EuroDataPro" in result["body"]


def test_parse_vendor_document_missing_doc():
    meta = tools.load_fixture_meta("fixtures/04-clean-cdn/")
    result = tools.parse_vendor_document({"doc_type": "msa"}, fixture_meta=meta)
    assert result["metadata"]["present"] is False
    assert "available_doc_types" in result["metadata"]


# --- tools.check_regulatory_requirements ------------------------------------


def test_check_regulatory_known_framework():
    result = tools.check_regulatory_requirements({"framework": "gdpr-art28"})
    assert "clauses" in result
    assert "Article 28" in result["clauses"]


def test_check_regulatory_unknown_framework():
    result = tools.check_regulatory_requirements({"framework": "fictional-act-2099"})
    assert "error" in result


# --- tools.compare_to_baseline ----------------------------------------------


def test_compare_to_baseline_hits_known_vendor():
    result = tools.compare_to_baseline({"vendor_name": "QuantumLog"})
    assert result.get("prior_risk_tier") == "MEDIUM"


def test_compare_to_baseline_no_prior():
    result = tools.compare_to_baseline({"vendor_name": "NeverBefore Inc."})
    assert result.get("error") == "no prior"


# --- tools.escalate_to_human ------------------------------------------------


def test_escalate_flips_state():
    state: dict = {"escalation_triggered": False}
    result = tools.escalate_to_human(
        {"reason": "carve-out detected", "residual_risk": "HIGH"}, state=state
    )
    assert result["escalated"] is True
    assert state["escalation_triggered"] is True
    assert state["escalation_residual_risk"] == "HIGH"


def test_escalate_rejects_bad_residual_risk():
    result = tools.escalate_to_human(
        {"reason": "x", "residual_risk": "SEVERE"}, state={}
    )
    assert "error" in result


# --- agent._coerce_output ---------------------------------------------------


def test_coerce_output_valid_json():
    final = json.dumps({
        "risk_tier": "HIGH",
        "concerns": ["DPA carves out EuroDataPro from SCCs"],
        "conflicts": [],
        "citations": ["carve-out-playbook", "gdpr-art28"],
        "mitigations": ["Remove carve-out before contract execution"],
        "contract_clauses": ["Strike DPA Exhibit B carve-out language"],
        "summary": "Carve-out detected; escalate.",
    })
    out = _coerce_output(
        final,
        system_id=SYSTEM_ID_EXT,
        retrieved_doc_ids=["carve-out-playbook", "gdpr-art28", "tprm-policy"],
        state={"escalation_triggered": True},
    )
    assert out["system_id"] == SYSTEM_ID_EXT
    assert out["risk_tier"] == "HIGH"
    assert out["escalation_triggered"] is True
    assert out["retrieved_doc_ids"] == ["carve-out-playbook", "gdpr-art28", "tprm-policy"]
    assert out["citations"] == ["carve-out-playbook", "gdpr-art28"]


def test_coerce_output_handles_code_fence():
    final = "```json\n" + json.dumps({"risk_tier": "LOW", "summary": "ok"}) + "\n```"
    out = _coerce_output(final, system_id=SYSTEM_ID_EXT, retrieved_doc_ids=[], state={})
    assert out["risk_tier"] == "LOW"


def test_coerce_output_invalid_json_degrades_to_medium():
    out = _coerce_output("not json at all", system_id=SYSTEM_ID_EXT, retrieved_doc_ids=[], state={})
    assert out["risk_tier"] == "MEDIUM"
    assert any("parse failed" in c for c in out["concerns"])


# --- fixture coverage --------------------------------------------------------


@pytest.mark.parametrize("fixture_name", [
    "01-clean-saas", "02-clean-paas", "03-clean-data-processor", "04-clean-cdn",
    "05-edge-carveout-eu", "06-edge-iso-expired", "07-edge-conflicting-dpa",
    "08-adv-pdf-injection", "09-adv-soc2-type-confusion", "10-adv-encryption-ambiguity",
    "11-mnpi-deal-context", "12-mnpi-active-deal", "13-mnpi-board-package",
    "14-intref-core-banking", "15-intref-trading-platform",
    "16-intref-customer-pii-export", "17-hitl-critical-resid", "18-hitl-high-resid-mnpi",
])
def test_every_fixture_resolves(fixture_name: str):
    meta = tools.load_fixture_meta(f"fixtures/{fixture_name}/")
    assert meta["case_id"]
    assert meta["vendor_name"]
    assert "documents" in meta
    # Every fixture should at least carry a package summary.
    assert "package_summary" in meta["documents"]


# --- registry ----------------------------------------------------------------


def test_registry_lists_vendor_risk_with_demo_only_true():
    from agents._registry import get_agent
    spec = get_agent("vendor_risk")
    assert spec.demo_only is True
    assert spec.default_system_id == SYSTEM_ID_EXT
    assert spec.module_path == "agents.vendor_risk.agent"
    assert spec.entrypoint == "run_vendor_risk"
    assert spec.inner_entrypoint == "_run_review_inner"
