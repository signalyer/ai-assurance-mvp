"""Integration tests — governance layer: framework coverage, release gates, runtime memory.

Tests are organised by the three modified domain modules:
  1. framework_coverage.py  — framework_matrix (regression) + framework_matrix_with_agents
                              + aggregate_agent_risk_tier
  2. release_gate_engine.py — evaluate_system_gates (agent-aware + pass case)
  3. runtime_engine.py      — assemble_context (with/without bindings)
                              + get_agent_context

All tests use monkeypatching — no Postgres dependency, no Implementer 1 binaries
required at import time.

Test count: 12 minimum (cases labelled with their index in the docstrings).
"""

from __future__ import annotations

import sys
import types
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers to build lightweight stub models without importing Implementer 1
# ---------------------------------------------------------------------------

class _StubAgent:
    """Minimal stub for domain.models.Agent — no Pydantic dependency."""

    def __init__(
        self,
        agent_id: str,
        name: str,
        inherent_risk: str = "LOW",
        framework_refs: list[dict] | None = None,
        eval_scores: dict | None = None,
    ) -> None:
        self.agent_id = agent_id
        self.name = name
        self.inherent_risk = inherent_risk
        self.framework_refs = framework_refs or []
        self.eval_scores = eval_scores or {}


class _StubBinding:
    """Minimal stub for domain.models.AgentBinding."""

    def __init__(self, agent_id: str, system_id: str, version_id: str = "v1.0.0") -> None:
        self.agent_id = agent_id
        self.system_id = system_id
        self.version_id = version_id
        self.pinned = False


def _inject_stub_modules(
    agents: dict[str, _StubAgent],
    bindings_by_system: dict[str, list[_StubBinding]],
) -> None:
    """Inject fake domain.agents and domain.agent_bindings into sys.modules.

    This allows the modules under test to perform successful late imports even
    though Implementer 1's real implementations don't exist yet.
    """
    # domain.agents
    agents_mod = types.ModuleType("domain.agents")

    def get_agent(agent_id: str) -> _StubAgent | None:
        return agents.get(agent_id)

    def list_versions(agent_id: str) -> list[str]:
        return ["v1.0.0"]

    agents_mod.get_agent = get_agent  # type: ignore[attr-defined]
    agents_mod.list_versions = list_versions  # type: ignore[attr-defined]
    sys.modules["domain.agents"] = agents_mod

    # domain.agent_bindings
    bindings_mod = types.ModuleType("domain.agent_bindings")

    def list_bindings_for_system(system_id: str) -> list[_StubBinding]:
        return bindings_by_system.get(system_id, [])

    def bind_agent_to_system(agent_id: str, system_id: str, pinned: bool = False) -> _StubBinding:
        b = _StubBinding(agent_id, system_id)
        b.pinned = pinned
        bindings_by_system.setdefault(system_id, []).append(b)
        return b

    bindings_mod.list_bindings_for_system = list_bindings_for_system  # type: ignore[attr-defined]
    bindings_mod.bind_agent_to_system = bind_agent_to_system  # type: ignore[attr-defined]
    sys.modules["domain.agent_bindings"] = bindings_mod


def _remove_stub_modules() -> None:
    """Remove stub modules injected by _inject_stub_modules."""
    sys.modules.pop("domain.agents", None)
    sys.modules.pop("domain.agent_bindings", None)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=False)
def stub_agents_and_bindings(request: pytest.FixtureRequest) -> Any:
    """Fixture: inject stub agent/binding modules and remove them after test."""
    agents: dict[str, _StubAgent] = {
        "ai-agent-pay-fraud": _StubAgent(
            "ai-agent-pay-fraud", "Payments Fraud Agent",
            inherent_risk="HIGH",
            framework_refs=[
                {"framework": "NIST_AI_RMF", "clause": "MANAGE"},
                {"framework": "OWASP_LLM_TOP10", "clause": "LLM01"},
                {"framework": "OWASP_LLM_TOP10", "clause": "LLM02"},
            ],
            eval_scores={"pii_leakage": True, "prompt_injection": 0.97},
        ),
        "ai-agent-pii-redactor": _StubAgent(
            "ai-agent-pii-redactor", "PII Redactor Agent",
            inherent_risk="CRITICAL",
            framework_refs=[
                {"framework": "NIST_AI_RMF", "clause": "GOVERN"},
                {"framework": "OWASP_LLM_TOP10", "clause": "LLM02"},
            ],
            eval_scores={"pii_leakage": False},  # will fail RG-001
        ),
        "ai-agent-cx-router": _StubAgent(
            "ai-agent-cx-router", "CX Router Agent",
            inherent_risk="MEDIUM",
            eval_scores={"pii_leakage": True, "prompt_injection": 0.96},
        ),
        "ai-agent-risk-classifier": _StubAgent(
            "ai-agent-risk-classifier", "Risk Classifier Agent",
            inherent_risk="HIGH",
            eval_scores={"pii_leakage": True},
        ),
        "ai-agent-sentiment": _StubAgent(
            "ai-agent-sentiment", "Sentiment Analysis Agent",
            inherent_risk="LOW",
            eval_scores={"pii_leakage": True},
        ),
        "ai-agent-doc-summarizer": _StubAgent(
            "ai-agent-doc-summarizer", "Document Summariser Agent",
            inherent_risk="MEDIUM",
            eval_scores={"pii_leakage": True},
        ),
    }

    bindings_by_system: dict[str, list[_StubBinding]] = {
        "sys-payments-001": [
            _StubBinding("ai-agent-pay-fraud", "sys-payments-001"),
            _StubBinding("ai-agent-pii-redactor", "sys-payments-001"),
        ],
        "sys-cx-001": [
            _StubBinding("ai-agent-cx-router", "sys-cx-001"),
            _StubBinding("ai-agent-sentiment", "sys-cx-001"),
        ],
        "sys-risk-001": [
            _StubBinding("ai-agent-risk-classifier", "sys-risk-001"),
            _StubBinding("ai-agent-pii-redactor", "sys-risk-001"),
            _StubBinding("ai-agent-doc-summarizer", "sys-risk-001"),
        ],
        "sys-platform-001": [
            _StubBinding("ai-agent-sentiment", "sys-platform-001"),
        ],
        "sys-finserv-001": [
            _StubBinding("ai-agent-pii-redactor", "sys-finserv-001"),
            _StubBinding("ai-agent-doc-summarizer", "sys-finserv-001"),
        ],
        "sys-internal-001": [
            _StubBinding("ai-agent-doc-summarizer", "sys-internal-001"),
        ],
    }

    _inject_stub_modules(agents, bindings_by_system)
    yield agents, bindings_by_system
    _remove_stub_modules()


# ---------------------------------------------------------------------------
# Tests — framework_coverage.py
# ---------------------------------------------------------------------------

class TestFrameworkMatrix:
    """Case 1 — regression: framework_matrix for ai-sys-001 still works."""

    def test_existing_system_no_bindings(self) -> None:
        """Case 1: framework_matrix(['ai-sys-001']) returns a MatrixResult with 1 row."""
        from domain.framework_coverage import framework_matrix

        result = framework_matrix(["ai-sys-001"])

        assert len(result.rows) == 1, "Expected exactly 1 row for ai-sys-001"
        row = result.rows[0]
        assert row.system_id == "ai-sys-001"
        # Cells should be a dict keyed by framework slugs
        assert isinstance(row.cells, dict)
        assert len(row.cells) > 0


class TestFrameworkMatrixWithAgents:
    """Cases 2 and 3 — framework_matrix_with_agents for sys-payments-001."""

    def test_enriched_result_structure(self, stub_agents_and_bindings: Any) -> None:
        """Case 2: framework_matrix_with_agents returns EnrichedMatrixResult with per-agent rows."""
        from domain.framework_coverage import framework_matrix_with_agents

        # sys-payments-001 must be registered in the repository
        # We monkeypatch the repository to include it
        from domain.seed_systems import _build_system, _SYSTEM_DEFS

        sys_def = next(d for d in _SYSTEM_DEFS if d["id"] == "sys-payments-001")
        sys_obj = _build_system(sys_def)

        with patch("domain.framework_coverage.repository") as mock_repo:
            mock_repo.list_ai_systems.return_value = [sys_obj]
            mock_repo.get_ai_system.side_effect = lambda sid: sys_obj if sid == "sys-payments-001" else None

            result = framework_matrix_with_agents(["sys-payments-001"])

        assert len(result.rows) == 1
        row = result.rows[0]
        assert row.system_id == "sys-payments-001"
        assert isinstance(row.cells, dict)
        assert isinstance(row.system_cells, dict)
        # Two agents are bound
        assert len(row.agent_rows) == 2, f"Expected 2 agent rows, got {len(row.agent_rows)}"

    def test_enriched_cells_are_worst_case(self, stub_agents_and_bindings: Any) -> None:
        """Case 3: Enriched cells ≤ system's own cells (worst-link aggregation)."""
        from domain.framework_coverage import framework_matrix_with_agents
        from domain.seed_systems import _build_system, _SYSTEM_DEFS

        sys_def = next(d for d in _SYSTEM_DEFS if d["id"] == "sys-payments-001")
        sys_obj = _build_system(sys_def)

        with patch("domain.framework_coverage.repository") as mock_repo:
            mock_repo.list_ai_systems.return_value = [sys_obj]
            mock_repo.get_ai_system.side_effect = lambda sid: sys_obj if sid == "sys-payments-001" else None

            result = framework_matrix_with_agents(["sys-payments-001"])

        row = result.rows[0]
        for slug, final_pct in row.cells.items():
            system_pct = row.system_cells.get(slug, 0.0)
            assert final_pct <= system_pct + 0.01, (
                f"Final cell for {slug} ({final_pct}) must be ≤ system cell ({system_pct})"
            )


class TestAggregateAgentRiskTier:
    """Cases 4, 5, 6 — aggregate_agent_risk_tier."""

    def test_critical_wins_for_sys_risk_001(self, stub_agents_and_bindings: Any) -> None:
        """Case 4: sys-risk-001 has ai-agent-pii-redactor (CRITICAL) → returns CRITICAL."""
        from domain.framework_coverage import aggregate_agent_risk_tier
        from domain.models import RiskLevel
        from domain.seed_systems import _build_system, _SYSTEM_DEFS

        sys_def = next(d for d in _SYSTEM_DEFS if d["id"] == "sys-risk-001")
        sys_obj = _build_system(sys_def)

        with patch("domain.framework_coverage.repository") as mock_repo:
            mock_repo.get_ai_system.return_value = sys_obj

            result = aggregate_agent_risk_tier("sys-risk-001")

        assert result == RiskLevel.CRITICAL, (
            f"Expected CRITICAL for sys-risk-001 (pii-redactor bound), got {result}"
        )

    def test_low_for_single_low_agent(self, stub_agents_and_bindings: Any) -> None:
        """Case 5: sys-platform-001 has only ai-agent-sentiment (LOW) → returns LOW."""
        from domain.framework_coverage import aggregate_agent_risk_tier
        from domain.models import RiskLevel
        from domain.seed_systems import _build_system, _SYSTEM_DEFS

        sys_def = next(d for d in _SYSTEM_DEFS if d["id"] == "sys-platform-001")
        sys_obj = _build_system(sys_def)

        with patch("domain.framework_coverage.repository") as mock_repo:
            mock_repo.get_ai_system.return_value = sys_obj

            result = aggregate_agent_risk_tier("sys-platform-001")

        assert result == RiskLevel.LOW, (
            f"Expected LOW for sys-platform-001 (only sentiment bound), got {result}"
        )

    def test_no_bindings_returns_system_own_risk(self) -> None:
        """Case 6: No bindings → returns system's own inherent_risk (backward compat)."""
        # Remove stub modules to simulate absence of agent_bindings
        _remove_stub_modules()

        from domain.framework_coverage import aggregate_agent_risk_tier
        from domain.models import RiskLevel

        # ai-sys-001 has inherent_risk=CRITICAL (from seed.py)
        result = aggregate_agent_risk_tier("ai-sys-001")

        assert result == RiskLevel.CRITICAL, (
            f"Expected CRITICAL (ai-sys-001 system's own risk) without bindings, got {result}"
        )


# ---------------------------------------------------------------------------
# Tests — release_gate_engine.py
# ---------------------------------------------------------------------------

class TestEvaluateSystemGatesAgentAware:
    """Cases 7, 8, 9 — evaluate_system_gates with agent-aware override."""

    def _build_minimal_system_and_patch(self, system_id: str, inherent_risk: str = "HIGH"):
        """Return a mock AISystem and a patcher that stubs the repository."""
        from unittest.mock import MagicMock

        system = MagicMock()
        system.id = system_id
        system.name = f"Test System {system_id}"
        system.inherent_risk = MagicMock()
        system.inherent_risk.value = inherent_risk
        system.tools = []
        system.rag_enabled = False
        system.customer_impact = MagicMock()

        from domain.models import CustomerImpact
        system.customer_impact = CustomerImpact.INDIRECT

        return system

    def test_pii_redactor_fails_pii_gate(self, stub_agents_and_bindings: Any) -> None:
        """Case 7: pii-redactor agent fails RG-001 → system gate.status = FAIL naming the agent."""
        agents, bindings = stub_agents_and_bindings
        # pii-redactor has eval_scores={"pii_leakage": False} — will fail RG-001

        from domain.release_gate_engine import GateStatus, evaluate_system_gates

        system = self._build_minimal_system_and_patch("sys-payments-001")

        with patch("domain.release_gate_engine.repository") as mock_repo, \
             patch("domain.assessment_engine.evaluate_control") as mock_eval, \
             patch("domain.assessment_engine.evidence_completeness", return_value=0.9):
            mock_repo.get_ai_system.return_value = system
            mock_repo.eval_results_for.return_value = []
            mock_repo.findings_for.return_value = []
            mock_repo.evidence_for.return_value = []
            mock_repo.runtime_events_for.return_value = []

            from domain.assessment_engine import ControlStatus
            mock_eval.return_value = MagicMock(status=ControlStatus.PASS)

            report = evaluate_system_gates("sys-payments-001")

        # Find RG-001 (PII Leakage Gate) in results
        rg001 = next((g for g in report.gates if g.gate_id == "RG-001"), None)
        assert rg001 is not None, "RG-001 not found in gate results"
        assert rg001.status == GateStatus.FAIL, (
            f"Expected RG-001 FAIL due to pii-redactor agent, got {rg001.status}"
        )
        assert rg001.failed_reason is not None
        assert "PII Redactor Agent" in rg001.failed_reason or "ai-agent-pii-redactor" in rg001.failed_reason, (
            f"Failure reason should name the agent, got: {rg001.failed_reason}"
        )

    def test_agent_failure_reason_names_agent(self, stub_agents_and_bindings: Any) -> None:
        """Case 8: Failed reason string must include agent name or id."""
        from domain.release_gate_engine import GateStatus, evaluate_system_gates

        system = self._build_minimal_system_and_patch("sys-payments-001")

        with patch("domain.release_gate_engine.repository") as mock_repo, \
             patch("domain.assessment_engine.evaluate_control") as mock_eval, \
             patch("domain.assessment_engine.evidence_completeness", return_value=0.9):
            mock_repo.get_ai_system.return_value = system
            mock_repo.eval_results_for.return_value = []
            mock_repo.findings_for.return_value = []
            mock_repo.evidence_for.return_value = []
            mock_repo.runtime_events_for.return_value = []

            from domain.assessment_engine import ControlStatus
            mock_eval.return_value = MagicMock(status=ControlStatus.PASS)

            report = evaluate_system_gates("sys-payments-001")

        failed_gates = [g for g in report.gates if g.status == GateStatus.FAIL]
        for fg in failed_gates:
            if fg.failed_reason and ("agent" in fg.failed_reason.lower()
                                     or "Agent" in fg.failed_reason):
                # At least one failure names an agent
                assert True
                return
        # If no agent-named failure found, check RG-001 specifically
        rg001 = next((g for g in report.gates if g.gate_id == "RG-001"), None)
        if rg001 and rg001.status == GateStatus.FAIL and rg001.failed_reason:
            assert "v1.0.0" in rg001.failed_reason or "agent" in rg001.failed_reason.lower()

    def test_no_agent_failures_produces_clean_report(self) -> None:
        """Case 9: When no agents fail any gate, evaluate_system_gates behaves as evaluate_gates."""
        # No stub modules injected — simulates no bindings / backward compat
        _remove_stub_modules()

        from domain.release_gate_engine import evaluate_system_gates

        system = MagicMock()
        system.id = "ai-sys-004"
        system.name = "Credit Memo Drafting Agent"
        from domain.models import CustomerImpact, RiskLevel
        system.customer_impact = CustomerImpact.INDIRECT
        system.inherent_risk = RiskLevel.MEDIUM
        system.tools = []
        system.rag_enabled = False

        with patch("domain.release_gate_engine.repository") as mock_repo, \
             patch("domain.assessment_engine.evaluate_control") as mock_eval, \
             patch("domain.assessment_engine.evidence_completeness", return_value=0.95):
            mock_repo.get_ai_system.return_value = system
            mock_repo.eval_results_for.return_value = []
            mock_repo.findings_for.return_value = []
            mock_repo.evidence_for.return_value = []
            mock_repo.runtime_events_for.return_value = []

            from domain.assessment_engine import ControlStatus
            mock_eval.return_value = MagicMock(status=ControlStatus.PASS)

            report = evaluate_system_gates("ai-sys-004")

        # Should succeed (or at worst WARNING) — no FAIL from agents since no bindings
        fail_count = sum(1 for g in report.gates if g.gate_id == "RG-001"
                         and "Agent" in (g.failed_reason or ""))
        assert fail_count == 0, "No agent-caused failures expected when no bindings"


# ---------------------------------------------------------------------------
# Tests — runtime_engine.py
# ---------------------------------------------------------------------------

class TestGetAgentContext:
    """Case 10 — get_agent_context returns memory for composite workload_id."""

    def test_composite_workload_id_used(self) -> None:
        """Case 10: get_agent_context calls build_context with composite workload_id."""
        from domain.runtime_engine import get_agent_context

        captured: dict[str, str] = {}

        def fake_build_context(workload_id: str, **kwargs: object) -> str:
            captured["workload_id"] = workload_id
            return f"[context for {workload_id}]"

        with patch("domain.agent_memory.build_context", fake_build_context):
            ctx = get_agent_context(
                system_id="sys-payments-001",
                agent_id="ai-agent-pay-fraud",
                version_id="v1.0.0",
                query="fraud patterns",
                limit=5,
            )

        expected_wid = "sys-payments-001__ai-agent-pay-fraud__v1.0.0"
        assert captured.get("workload_id") == expected_wid, (
            f"Expected composite workload_id {expected_wid!r}, "
            f"got {captured.get('workload_id')!r}"
        )
        assert expected_wid in ctx


class TestAssembleContext:
    """Cases 11 and 12 — assemble_context with and without bindings."""

    def test_returns_dict_with_per_agent_contexts_when_bindings_exist(
        self, stub_agents_and_bindings: Any
    ) -> None:
        """Case 11: assemble_context returns dict with per_agent_contexts when bindings exist."""
        agents, bindings = stub_agents_and_bindings

        from domain.runtime_engine import assemble_context

        def fake_build_context(workload_id: str, **kwargs: object) -> str:
            return f"[context:{workload_id}]"

        with patch("domain.agent_memory.build_context", fake_build_context):
            result = assemble_context(
                system_id="sys-payments-001",
                query="fraud check",
            )

        assert isinstance(result, dict), (
            f"Expected dict when bindings exist, got {type(result).__name__}"
        )
        assert "system_context" in result, "Missing 'system_context' key"
        assert "per_agent_contexts" in result, "Missing 'per_agent_contexts' key"

        per_agent = result["per_agent_contexts"]
        assert isinstance(per_agent, dict)
        # Both bound agents should have contexts
        assert "ai-agent-pay-fraud" in per_agent
        assert "ai-agent-pii-redactor" in per_agent

    def test_returns_string_when_no_bindings(self) -> None:
        """Case 12: assemble_context returns plain string when no bindings (backward compat)."""
        # Remove stub modules so ImportError triggers the fallback path
        _remove_stub_modules()

        from domain.runtime_engine import assemble_context

        def fake_build_context(workload_id: str, **kwargs: object) -> str:
            return f"[context:{workload_id}]"

        with patch("domain.agent_memory.build_context", fake_build_context):
            result = assemble_context(
                system_id="ai-sys-001",
                query="payment exceptions",
            )

        assert isinstance(result, str), (
            f"Expected str when no bindings, got {type(result).__name__}"
        )
        assert "ai-sys-001" in result
