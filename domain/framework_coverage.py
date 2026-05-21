"""Framework coverage engine.

Computes, for each user-facing framework item (NIST AI RMF function,
NIST AI 600-1 risk area, OWASP LLM Top 10 category, OWASP Agentic AI
Top 10 category), the actual coverage derived from controls / findings /
evidence / release gates — not hardcoded percentages.

Public API:
    framework_catalog(framework) -> list[FrameworkItem]
    item_coverage(framework, clause, scope='ALL'|<ai_system_id>) -> ItemCoverage
    framework_overview(framework) -> list[ItemCoverage]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from domain.models import (
    FrameworkName, Priority, Severity, FindingStatus, EvalStatus,
)
from domain.controls import CONTROLS, CONTROLS_BY_ID, is_applicable
from domain.release_gate_engine import GATE_DEFS, _GATE_TO_CONTROLS
from domain.assessment_engine import evaluate_control, ControlStatus
from domain import repository


# ---------------------------------------------------------------------------
# Framework catalog — the user-facing items, anchored to clauses in controls
# ---------------------------------------------------------------------------

@dataclass
class FrameworkItem:
    id: str                          # stable slug e.g. "rmf-govern", "600-data-privacy", "llm01", "aai-04"
    framework: str                   # FrameworkName.value
    display_name: str                # what the UI shows
    description: str
    # Clause matching rules. A control is considered mapped to this item
    # when any of its framework_mappings (where framework matches) has a clause
    # that either equals one of `exact_clauses` or starts with one of `prefix_clauses`.
    exact_clauses: list[str] = field(default_factory=list)
    prefix_clauses: list[str] = field(default_factory=list)
    recommended_owner: str = "AI Governance"


NIST_RMF_ITEMS: list[FrameworkItem] = [
    FrameworkItem(
        id="rmf-govern", framework=FrameworkName.NIST_AI_RMF.value,
        display_name="Govern", description="Policies, accountability, roles, governance structures for the AI program.",
        prefix_clauses=["GOVERN"], recommended_owner="AI Governance",
    ),
    FrameworkItem(
        id="rmf-map", framework=FrameworkName.NIST_AI_RMF.value,
        display_name="Map", description="Contextualize the system: purpose, users, data classes, regulatory exposure, dependencies.",
        prefix_clauses=["MAP"], recommended_owner="Model Risk",
    ),
    FrameworkItem(
        id="rmf-measure", framework=FrameworkName.NIST_AI_RMF.value,
        display_name="Measure", description="Evaluate AI risks: evals, red-team, bias, hallucination, prompt injection.",
        prefix_clauses=["MEASURE"], recommended_owner="AppSec / Model Risk",
    ),
    FrameworkItem(
        id="rmf-manage", framework=FrameworkName.NIST_AI_RMF.value,
        display_name="Manage", description="Allocate response, run incidents, manage exceptions, kill switches.",
        prefix_clauses=["MANAGE"], recommended_owner="CISO",
    ),
]

NIST_600_1_ITEMS: list[FrameworkItem] = [
    FrameworkItem(id="600-data-privacy",     framework=FrameworkName.NIST_AI_600_1.value,
                  display_name="Data Privacy", description="PII / NPI / PCI handling in prompts, RAG, outputs, logs.",
                  exact_clauses=["Data Privacy"], recommended_owner="CISO"),
    FrameworkItem(id="600-prompt-injection", framework=FrameworkName.NIST_AI_600_1.value,
                  display_name="Prompt Injection", description="Direct + indirect prompt injection attack resistance.",
                  exact_clauses=["Prompt Injection"], recommended_owner="AppSec"),
    FrameworkItem(id="600-rag-risks",        framework=FrameworkName.NIST_AI_600_1.value,
                  display_name="RAG Risks", description="Corpus poisoning, retrieval drift, embedding leakage.",
                  exact_clauses=["RAG Risks"], recommended_owner="Model Risk"),
    FrameworkItem(id="600-hallucination",    framework=FrameworkName.NIST_AI_600_1.value,
                  display_name="Hallucination", description="Factual error rate, unsupported citations, fabricated precedent.",
                  exact_clauses=["Hallucination"], recommended_owner="Model Risk"),
    FrameworkItem(id="600-human-ai",         framework=FrameworkName.NIST_AI_600_1.value,
                  display_name="Human-AI Interaction", description="HITL gates, override paths, escalation triggers.",
                  exact_clauses=["Human-AI Interaction"], recommended_owner="CRO"),
    FrameworkItem(id="600-transparency",     framework=FrameworkName.NIST_AI_600_1.value,
                  display_name="Transparency", description="Model cards, decision logs, what the system can/cannot do.",
                  exact_clauses=["Transparency"], recommended_owner="AI Governance"),
    FrameworkItem(id="600-accountability",   framework=FrameworkName.NIST_AI_600_1.value,
                  display_name="Accountability", description="Named owners, approval lineage, immutable audit trail.",
                  exact_clauses=["Accountability"], recommended_owner="Internal Audit"),
    FrameworkItem(id="600-misuse",           framework=FrameworkName.NIST_AI_600_1.value,
                  display_name="Misuse", description="Abuse paths, off-purpose use, vendor-level misuse controls.",
                  exact_clauses=["Misuse"], recommended_owner="CRO"),
    FrameworkItem(id="600-content-provenance", framework=FrameworkName.NIST_AI_600_1.value,
                  display_name="Content Provenance", description="Source-of-truth lineage for RAG content + AI-produced documents.",
                  exact_clauses=["Content Provenance"], recommended_owner="AI Governance"),
]

OWASP_LLM_ITEMS: list[FrameworkItem] = [
    FrameworkItem(id="llm01", framework=FrameworkName.OWASP_LLM_TOP10.value,
                  display_name="LLM01 Prompt Injection",
                  description="Direct + indirect prompt injection attacks.",
                  exact_clauses=["LLM01"], recommended_owner="AppSec"),
    FrameworkItem(id="llm02", framework=FrameworkName.OWASP_LLM_TOP10.value,
                  display_name="LLM02 Sensitive Information Disclosure",
                  description="Leakage of PII / NPI / PCI / model secrets via outputs or logs.",
                  exact_clauses=["LLM02"], recommended_owner="CISO"),
    FrameworkItem(id="llm03", framework=FrameworkName.OWASP_LLM_TOP10.value,
                  display_name="LLM03 Supply Chain",
                  description="Risks from model providers, fine-tunes, embeddings, base images.",
                  exact_clauses=["LLM03"], recommended_owner="AppSec"),
    FrameworkItem(id="llm04", framework=FrameworkName.OWASP_LLM_TOP10.value,
                  display_name="LLM04 Data and Model Poisoning",
                  description="Adversarial inputs in training/RAG corpora; model weight tampering.",
                  exact_clauses=["LLM04"], recommended_owner="Model Risk"),
    FrameworkItem(id="llm05", framework=FrameworkName.OWASP_LLM_TOP10.value,
                  display_name="LLM05 Improper Output Handling",
                  description="Downstream consumers trust model output without sanitization.",
                  exact_clauses=["LLM05"], recommended_owner="AppSec"),
    FrameworkItem(id="llm06", framework=FrameworkName.OWASP_LLM_TOP10.value,
                  display_name="LLM06 Excessive Agency",
                  description="Agents granted more capability or autonomy than necessary.",
                  exact_clauses=["LLM06"], recommended_owner="AppSec"),
    FrameworkItem(id="llm07", framework=FrameworkName.OWASP_LLM_TOP10.value,
                  display_name="LLM07 System Prompt Leakage",
                  description="Disclosure of system prompts containing secrets or business logic.",
                  exact_clauses=["LLM07"], recommended_owner="AppSec"),
    FrameworkItem(id="llm08", framework=FrameworkName.OWASP_LLM_TOP10.value,
                  display_name="LLM08 Vector and Embedding Weaknesses",
                  description="Retrieval-level access control, cross-tenant collisions, embedding inversion.",
                  exact_clauses=["LLM08"], recommended_owner="CISO"),
    FrameworkItem(id="llm09", framework=FrameworkName.OWASP_LLM_TOP10.value,
                  display_name="LLM09 Misinformation",
                  description="Confidently wrong outputs (hallucination, fabricated citations).",
                  exact_clauses=["LLM09"], recommended_owner="Model Risk"),
    FrameworkItem(id="llm10", framework=FrameworkName.OWASP_LLM_TOP10.value,
                  display_name="LLM10 Unbounded Consumption",
                  description="Resource exhaustion via runaway tool loops or token spend.",
                  exact_clauses=["LLM10"], recommended_owner="AppSec"),
]

OWASP_AGENTIC_ITEMS: list[FrameworkItem] = [
    FrameworkItem(id="aai-01", framework=FrameworkName.OWASP_AGENTIC_TOP10.value,
                  display_name="Goal manipulation",
                  description="Adversarial control of the agent's stated goal or sub-goal decomposition.",
                  exact_clauses=["AAI-01"], recommended_owner="AppSec"),
    FrameworkItem(id="aai-03", framework=FrameworkName.OWASP_AGENTIC_TOP10.value,
                  display_name="Memory poisoning",
                  description="Adversarial writes to persistent memory that influence future sessions.",
                  exact_clauses=["AAI-03"], recommended_owner="AppSec"),
    FrameworkItem(id="aai-04", framework=FrameworkName.OWASP_AGENTIC_TOP10.value,
                  display_name="Unsafe tool use",
                  description="Side-effectful tool calls without authorization, allowlist, or sandbox.",
                  exact_clauses=["AAI-04"], recommended_owner="AppSec"),
    FrameworkItem(id="aai-05", framework=FrameworkName.OWASP_AGENTIC_TOP10.value,
                  display_name="Excessive agency",
                  description="Agent capability or autonomy exceeds the business purpose.",
                  exact_clauses=["AAI-05"], recommended_owner="AI Governance"),
    FrameworkItem(id="aai-06", framework=FrameworkName.OWASP_AGENTIC_TOP10.value,
                  display_name="Delegation abuse",
                  description="Sub-agent invoked with elevated privilege; confused-deputy.",
                  exact_clauses=["AAI-06"], recommended_owner="AppSec"),
    FrameworkItem(id="aai-07", framework=FrameworkName.OWASP_AGENTIC_TOP10.value,
                  display_name="Agent identity spoofing",
                  description="One agent impersonates another to bypass trust boundaries.",
                  exact_clauses=["AAI-07"], recommended_owner="AppSec"),
    FrameworkItem(id="aai-toolchain", framework=FrameworkName.OWASP_AGENTIC_TOP10.value,
                  display_name="Toolchain poisoning",
                  description="Tool registry / signed-package supply chain compromise.",
                  exact_clauses=["AAI-04"], recommended_owner="AppSec"),
    FrameworkItem(id="aai-08", framework=FrameworkName.OWASP_AGENTIC_TOP10.value,
                  display_name="Autonomous persistence",
                  description="Agent escapes its session lifecycle to persist beyond intended bounds.",
                  exact_clauses=["AAI-08"], recommended_owner="CISO"),
    FrameworkItem(id="aai-09", framework=FrameworkName.OWASP_AGENTIC_TOP10.value,
                  display_name="Runtime control failure",
                  description="Loss of policy monitor, kill switch, or rate-limit at runtime.",
                  exact_clauses=["AAI-09"], recommended_owner="CISO"),
    FrameworkItem(id="aai-10", framework=FrameworkName.OWASP_AGENTIC_TOP10.value,
                  display_name="Human oversight failure",
                  description="HITL gate bypassed or absent on high-risk action.",
                  exact_clauses=["AAI-10"], recommended_owner="CRO"),
]

ALL_ITEMS: dict[str, FrameworkItem] = {
    item.id: item for items in (NIST_RMF_ITEMS, NIST_600_1_ITEMS, OWASP_LLM_ITEMS, OWASP_AGENTIC_ITEMS)
    for item in items
}


def framework_catalog(framework: str) -> list[FrameworkItem]:
    f = framework.upper()
    if f in ("NIST_AI_RMF", "NIST-RMF", "RMF"):                 return NIST_RMF_ITEMS
    if f in ("NIST_AI_600_1", "NIST-600", "600", "GENAI"):      return NIST_600_1_ITEMS
    if f in ("OWASP_LLM_TOP10", "OWASP_LLM", "LLM"):            return OWASP_LLM_ITEMS
    if f in ("OWASP_AGENTIC_TOP10", "OWASP_AGENTIC", "AGENTIC"): return OWASP_AGENTIC_ITEMS
    raise ValueError(f"Unknown framework: {framework}")


# ---------------------------------------------------------------------------
# Control resolution: which controls map to a given framework item?
# ---------------------------------------------------------------------------

def controls_for_item(item: FrameworkItem) -> list:
    """Return the controls whose framework_mappings include this item's clauses."""
    out = []
    for c in CONTROLS:
        for fm in c.framework_mappings:
            if fm.framework.value != item.framework:
                continue
            clause = fm.clause
            if clause in item.exact_clauses:
                out.append(c); break
            if any(clause.startswith(p) for p in item.prefix_clauses):
                out.append(c); break
    return out


# ---------------------------------------------------------------------------
# Coverage computation
# ---------------------------------------------------------------------------

@dataclass
class ControlRollup:
    control_id: str
    title: str
    priority: str
    domain: str
    status: str                      # PASS / FAIL / NO_EVIDENCE / PARTIAL / NOT_APPLICABLE / NOT_EVALUATED
    open_findings: int


@dataclass
class FindingSummary:
    id: str
    system_id: str
    title: str
    severity: str
    status: str
    control_id: str | None


@dataclass
class ItemCoverage:
    item_id: str
    framework: str
    display_name: str
    description: str
    recommended_owner: str
    scope: str                                  # 'ALL' or specific ai_system_id

    mapped_controls: list[ControlRollup]
    related_findings: list[FindingSummary]
    release_gates_affected: list[str]           # gate_ids
    coverage_pct: float                         # passing / applicable
    evidence_completeness: float                # 0..1 across the item's controls
    recommended_remediation: list[str]


def _systems_in_scope(scope: str):
    if scope == "ALL":
        return repository.list_ai_systems()
    s = repository.get_ai_system(scope)
    return [s] if s else []


def _evaluate(controls, system) -> dict[str, ControlStatus]:
    evidence = repository.evidence_for(system.id)
    evals = repository.eval_results_for(system.id)
    runtime = repository.runtime_events_for(system.id)
    out: dict[str, ControlStatus] = {}
    for c in controls:
        ev = evaluate_control(c, system, evidence, evals, runtime)
        out[c.control_id] = ev.status
    return out


def item_coverage(framework: str, clause_or_id: str, scope: str = "ALL") -> ItemCoverage:
    """Compute coverage for a single framework item.

    `clause_or_id` may be either the item's `id` slug ('llm01') or its clause
    ('LLM01') or its display key.
    """
    items = framework_catalog(framework)
    key = clause_or_id.strip()
    item = next(
        (i for i in items if i.id == key or key in i.exact_clauses
                          or any(key.startswith(p) for p in i.prefix_clauses)
                          or key == i.display_name),
        None,
    )
    if item is None:
        raise ValueError(f"Unknown framework item: {clause_or_id} in {framework}")

    mapped = controls_for_item(item)
    systems = _systems_in_scope(scope)

    # Roll up control status across systems in scope.
    rollups: dict[str, ControlRollup] = {}
    applicable_total = 0
    passing_total = 0
    failing_total = 0
    required_evidence_types: set[str] = set()
    seen_evidence_types: set[str] = set()
    findings_acc: list[FindingSummary] = []

    for c in mapped:
        required_evidence_types.update(et.value for et in c.evidence_required)

    for system in systems:
        statuses = _evaluate(mapped, system)
        # Track evidence types present for any system in scope
        for e in repository.evidence_for(system.id):
            seen_evidence_types.add(e.evidence_type.value)

        for c in mapped:
            if not is_applicable(c, system):
                continue
            applicable_total += 1
            st = statuses.get(c.control_id, ControlStatus.NOT_APPLICABLE)
            if st == ControlStatus.PASS:
                passing_total += 1
            elif st in (ControlStatus.FAIL, ControlStatus.NO_EVIDENCE):
                failing_total += 1

            open_findings = [
                f for f in repository.findings_for(system.id)
                if f.control_id == c.control_id and f.status in (FindingStatus.OPEN, FindingStatus.IN_PROGRESS)
            ]
            rk = (c.control_id, system.id)
            rollups[rk] = ControlRollup(
                control_id=c.control_id, title=c.title,
                priority=c.priority.value, domain=c.domain.value,
                status=st.value, open_findings=len(open_findings),
            )
            for f in open_findings:
                findings_acc.append(FindingSummary(
                    id=f.id, system_id=system.id, title=f.title,
                    severity=f.severity.value, status=f.status.value, control_id=f.control_id,
                ))

    # Aggregate the same control across systems: prefer the worst status.
    severity_order = {"PASS": 0, "PARTIAL": 1, "NO_EVIDENCE": 2, "FAIL": 3, "NOT_APPLICABLE": -1, "NOT_EVALUATED": -1}
    by_control: dict[str, ControlRollup] = {}
    for r in rollups.values():
        cur = by_control.get(r.control_id)
        if cur is None or severity_order.get(r.status, 0) > severity_order.get(cur.status, 0):
            by_control[r.control_id] = ControlRollup(
                control_id=r.control_id, title=r.title, priority=r.priority,
                domain=r.domain, status=r.status, open_findings=r.open_findings,
            )
    final_controls = sorted(by_control.values(), key=lambda x: (x.priority, x.control_id))

    # Release gates affected — any gate whose mapped controls intersect this item's controls
    item_control_ids = {c.control_id for c in mapped}
    gates_affected = sorted({
        gate_id for gate_id, ctrls in _GATE_TO_CONTROLS.items()
        if set(ctrls) & item_control_ids
    })

    coverage_pct = (passing_total / applicable_total * 100.0) if applicable_total else 0.0
    ev_complete = (
        len(required_evidence_types & seen_evidence_types) / len(required_evidence_types)
        if required_evidence_types else 1.0
    )

    # Recommended remediation: pass_criteria for non-passing controls
    remediation: list[str] = []
    for r in final_controls:
        if r.status in ("FAIL", "NO_EVIDENCE"):
            c = CONTROLS_BY_ID.get(r.control_id)
            if c:
                remediation.append(f"{c.control_id} — {c.title}: {c.pass_criteria}")

    return ItemCoverage(
        item_id=item.id, framework=item.framework,
        display_name=item.display_name, description=item.description,
        recommended_owner=item.recommended_owner, scope=scope,
        mapped_controls=final_controls,
        related_findings=findings_acc[:50],  # cap drill-down list
        release_gates_affected=gates_affected,
        coverage_pct=round(coverage_pct, 1),
        evidence_completeness=round(ev_complete, 3),
        recommended_remediation=remediation[:20],
    )


def framework_overview(framework: str, scope: str = "ALL") -> list[ItemCoverage]:
    """Compute coverage for every item in a framework, in display order."""
    return [item_coverage(framework, item.id, scope=scope)
            for item in framework_catalog(framework)]


__all__ = [
    "FrameworkItem", "ControlRollup", "FindingSummary", "ItemCoverage",
    "framework_catalog", "controls_for_item",
    "item_coverage", "framework_overview",
    "NIST_RMF_ITEMS", "NIST_600_1_ITEMS", "OWASP_LLM_ITEMS", "OWASP_AGENTIC_ITEMS",
]
