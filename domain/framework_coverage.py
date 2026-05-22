"""Framework coverage engine.

Computes, for each user-facing framework item (NIST AI RMF function,
NIST AI 600-1 risk area, OWASP LLM Top 10 category, OWASP Agentic AI
Top 10 category), the actual coverage derived from controls / findings /
evidence / release gates — not hardcoded percentages.

Public API:
    framework_catalog(framework) -> list[FrameworkItem]
    item_coverage(framework, clause, scope='ALL'|<ai_system_id>) -> ItemCoverage
    framework_overview(framework) -> list[ItemCoverage]
    framework_display_name(slug) -> str
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
    # Finding #11: aai-toolchain now has its own distinct clause (AAI-04-toolchain)
    # so it no longer shadows aai-04's "AAI-04" exact_clause.
    FrameworkItem(id="aai-toolchain", framework=FrameworkName.OWASP_AGENTIC_TOP10.value,
                  display_name="Toolchain poisoning",
                  description="Tool registry / signed-package supply chain compromise.",
                  exact_clauses=["AAI-04-toolchain"], recommended_owner="AppSec"),
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

# ---------------------------------------------------------------------------
# YAML-sourced catalogs — loaded once at module import.
# load_all_frameworks() propagates YAML parse errors (fail-loud per spec).
# ---------------------------------------------------------------------------

_YAML_CATALOGS: dict[str, list[FrameworkItem]] = {}


def _ensure_yaml_catalogs() -> None:
    """Populate _YAML_CATALOGS from the YAML loader on first call.

    The import of ``frameworks.loader`` is deferred to this function to avoid
    a circular import at module load time (``frameworks.loader`` imports
    ``FrameworkItem`` from this module).  Any YAML parse error propagates
    immediately (fail-loud per spec).
    """
    global _YAML_CATALOGS  # noqa: PLW0603
    if _YAML_CATALOGS:
        return
    from frameworks.loader import load_all_frameworks  # deferred to break circular import
    raw = load_all_frameworks()
    # Group by FrameworkName value (the 'framework' field on each FrameworkItem)
    by_fw: dict[str, list[FrameworkItem]] = {}
    for items in raw.values():
        for item in items:
            fw_val = item.framework if isinstance(item.framework, str) else item.framework.value
            by_fw.setdefault(fw_val, []).append(item)
    _YAML_CATALOGS = by_fw


def _yaml_items(framework_value: str) -> list[FrameworkItem]:
    """Return YAML-sourced items for the given FrameworkName value."""
    _ensure_yaml_catalogs()
    return _YAML_CATALOGS.get(framework_value, [])


def framework_catalog(framework: str) -> list[FrameworkItem]:
    """Return the ordered list of :class:`FrameworkItem` objects for a framework.

    Python-defined catalogs (NIST AI RMF, NIST AI 600-1, OWASP LLM, OWASP
    Agentic) are returned directly.  YAML-sourced catalogs (EU AI Act, ISO 42001,
    SR 11-7, FFIEC) are loaded from ``frameworks.loader.load_all_frameworks()``
    on first access and cached.  Any YAML parse error propagates immediately.
    """
    f = framework.upper()
    if f in ("NIST_AI_RMF", "NIST-RMF", "RMF"):                  return NIST_RMF_ITEMS
    if f in ("NIST_AI_600_1", "NIST-600", "600", "GENAI"):       return NIST_600_1_ITEMS
    if f in ("OWASP_LLM_TOP10", "OWASP_LLM", "LLM"):             return OWASP_LLM_ITEMS
    if f in ("OWASP_AGENTIC_TOP10", "OWASP_AGENTIC", "AGENTIC"):  return OWASP_AGENTIC_ITEMS
    if f in ("EU_AI_ACT", "EU-AI-ACT", "EUAIACT"):                return _yaml_items("EU_AI_ACT")
    if f in ("ISO_42001", "ISO-42001", "ISO42001"):                return _yaml_items("ISO_42001")
    if f in ("SR_11_7", "SR-11-7", "SR117"):                      return _yaml_items("SR_11_7")
    if f in ("FFIEC",):                                            return _yaml_items("FFIEC")
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


# ---------------------------------------------------------------------------
# Matrix computation — portfolio view across all frameworks and systems
# ---------------------------------------------------------------------------

# The frameworks surfaced in the coverage matrix UI (Day 6 spec: NIST + OWASP + EU AI Act + ISO 42001 + SR 11-7 + FFIEC).
MATRIX_FRAMEWORKS: list[tuple[str, str]] = [
    ("nist-ai-rmf",     FrameworkName.NIST_AI_RMF.value),
    ("nist-ai-600-1",   FrameworkName.NIST_AI_600_1.value),
    ("owasp-llm",       FrameworkName.OWASP_LLM_TOP10.value),
    ("owasp-agentic",   FrameworkName.OWASP_AGENTIC_TOP10.value),
    ("eu-ai-act",       "EU_AI_ACT"),
    ("iso-42001",       "ISO_42001"),
    ("sr-11-7",         "SR_11_7"),
    ("ffiec",           "FFIEC"),
]

# For frameworks that don't have a catalog in this engine yet, we return 0.0.
_FRAMEWORK_SLUG_TO_CATALOG_KEY: dict[str, str] = {
    "nist-ai-rmf":   "NIST_AI_RMF",
    "nist-ai-600-1": "NIST_AI_600_1",
    "owasp-llm":     "OWASP_LLM",
    "owasp-agentic": "OWASP_AGENTIC",
    "eu-ai-act":     "EU_AI_ACT",
    "iso-42001":     "ISO_42001",
    "sr-11-7":       "SR_11_7",
    "ffiec":         "FFIEC",
}


def _mean_coverage(coverages: list[ItemCoverage]) -> float:
    if not coverages:
        return 0.0
    return round(sum(c.coverage_pct for c in coverages) / len(coverages), 1)


def _system_framework_coverage(system_id: str, catalog_key: str) -> float:
    """Return mean coverage % for one system × one framework. Returns 0.0 on error."""
    try:
        items = framework_overview(catalog_key, scope=system_id)
        return _mean_coverage(items)
    except Exception:                                          # noqa: BLE001
        return 0.0


@dataclass
class MatrixRow:
    system_id: str
    system_name: str
    cells: dict[str, float]   # framework_slug -> coverage_pct


@dataclass
class MatrixResult:
    """Coverage matrix result.

    Supports both attribute access (``result.rows``) and dict-style subscript
    access (``result['rows']``) so that validation checks written as plain
    dict lookups work without a separate serialisation step.
    """

    frameworks: list[dict]    # [{slug, display_name}]
    rows: list[MatrixRow]

    def __getitem__(self, key: str) -> list[dict] | list[MatrixRow]:
        """Allow dict-style access: result['frameworks'] / result['rows']."""
        if key == "frameworks":
            return self.frameworks
        if key == "rows":
            return self.rows
        raise KeyError(key)


def framework_matrix(system_ids: list[str] | None = None) -> MatrixResult:
    """Compute the full N-systems × 6-frameworks coverage matrix.

    If ``system_ids`` is None, uses all governed AI systems from the repository.
    If ``system_ids`` is provided, a row is returned for every requested ID — systems
    not found in the repository receive 0.0% coverage across all frameworks rather
    than being silently dropped.  This guarantees ``len(result.rows) == len(system_ids)``
    when a non-None list is supplied.

    Returns a :class:`MatrixResult` whose `rows` list is ordered by the original
    ``system_ids`` order (or by system_id when None).  Supports both attribute
    access and dict-style subscript access.
    """
    repo_systems = repository.list_ai_systems()
    repo_by_id = {s.id: s for s in repo_systems}

    framework_meta = [
        {"slug": slug, "display_name": framework_display_name(slug)}
        for slug, _fn in MATRIX_FRAMEWORKS
    ]

    if system_ids is not None:
        # Preserve the caller's requested order; include unknown IDs as 0% rows.
        target_ids: list[str] = system_ids
    else:
        target_ids = [s.id for s in repo_systems]

    rows: list[MatrixRow] = []
    for sid in target_ids:
        system = repo_by_id.get(sid)
        cells: dict[str, float] = {}
        for slug, _fn in MATRIX_FRAMEWORKS:
            if system is None:
                cells[slug] = 0.0
            else:
                catalog_key = _FRAMEWORK_SLUG_TO_CATALOG_KEY.get(slug)
                if catalog_key:
                    cells[slug] = _system_framework_coverage(system.id, catalog_key)
                else:
                    cells[slug] = 0.0
        rows.append(MatrixRow(
            system_id=sid,
            system_name=system.name if system else sid,
            cells=cells,
        ))

    return MatrixResult(frameworks=framework_meta, rows=rows)


def framework_display_name(slug: str) -> str:
    """Return a human-readable display name for a framework slug.

    Args:
        slug: URL-style framework slug, e.g. ``"nist-ai-rmf"``.

    Returns:
        Human-readable name, e.g. ``"NIST AI RMF"``.
        Falls back to the slug itself if not found.
    """
    _NAMES: dict[str, str] = {
        "nist-ai-rmf":   "NIST AI RMF",
        "nist-ai-600-1": "NIST AI 600-1",
        "owasp-llm":     "OWASP LLM Top 10",
        "owasp-agentic": "OWASP Agentic Top 10",
        "eu-ai-act":     "EU AI Act",
        "iso-42001":     "ISO/IEC 42001",
        "sr-11-7":       "SR 11-7",
        "ffiec":         "FFIEC",
    }
    return _NAMES.get(slug, slug)


# Keep private alias for internal callers that pre-date the rename.
_framework_display = framework_display_name


# ---------------------------------------------------------------------------
# Agent-aware matrix computation — Session 07 additions
# ---------------------------------------------------------------------------

@dataclass
class AgentCoverageBreakdown:
    """Per-agent framework coverage row within an enriched matrix result."""

    agent_id: str
    agent_name: str
    semver: str
    cells: dict[str, float]  # framework_slug -> coverage_pct


@dataclass
class EnrichedMatrixRow:
    """Matrix row with per-agent coverage breakdown (worst-case cells)."""

    system_id: str
    system_name: str
    cells: dict[str, float]          # worst-of(system, all agents) per slug
    system_cells: dict[str, float]   # system's own coverage, pre-aggregation
    agent_rows: list[AgentCoverageBreakdown]


@dataclass
class EnrichedMatrixResult:
    """Enriched coverage matrix result that includes per-agent breakdowns.

    Supports both attribute access and dict-style subscript access
    (``result['frameworks']`` / ``result['rows']``) for consistency with
    :class:`MatrixResult`.
    """

    frameworks: list[dict]          # [{slug, display_name}]
    rows: list[EnrichedMatrixRow]

    def __getitem__(self, key: str) -> object:
        """Allow dict-style access: result['frameworks'] / result['rows']."""
        if key == "frameworks":
            return self.frameworks
        if key == "rows":
            return self.rows
        raise KeyError(key)


def _agent_framework_coverage(agent_id: str, semver: str, catalog_key: str) -> float:
    """Return mean framework coverage for a single agent version.

    Agents don't have their own findings/evidence — we approximate coverage
    from their ``framework_refs`` field (list of ``{framework, clause}`` dicts).
    A ref matching a framework item's exact_clause or prefix_clause counts as
    COVERED for that item.  Coverage = covered_items / total_items.

    Falls back to 0.0 on any error so the aggregation remains robust.
    """
    try:
        # Late import — Implementer 1's module may not exist during test monkeypatching
        from domain.agent_bindings import list_bindings_for_system  # noqa: F401  (unused here)
        from domain.agents import get_agent  # type: ignore[import]

        agent = get_agent(agent_id)
        if agent is None:
            return 0.0

        framework_refs: list = getattr(agent, "framework_refs", []) or []
        if not framework_refs:
            return 0.0

        items = framework_catalog(catalog_key)
        if not items:
            return 0.0

        # Parse refs into (framework, clause) tuples. Supports two shapes:
        #   list[str]  — "FRAMEWORK:CLAUSE" (Implementer 1 seed format)
        #   list[dict] — {"framework": "...", "clause": "..."}
        parsed_clauses: list[str] = []
        for ref in framework_refs:
            if isinstance(ref, str):
                if ":" in ref:
                    _fw, _, clause = ref.partition(":")
                    if clause:
                        parsed_clauses.append(clause)
            elif isinstance(ref, dict):
                clause = ref.get("clause", "")
                if clause:
                    parsed_clauses.append(clause)

        if not parsed_clauses:
            return 0.0

        covered = 0
        for item in items:
            for clause in parsed_clauses:
                if clause in item.exact_clauses:
                    covered += 1
                    break
                if any(clause.startswith(p) for p in item.prefix_clauses):
                    covered += 1
                    break

        return round(covered / len(items) * 100.0, 1) if items else 0.0
    except Exception:  # noqa: BLE001
        return 0.0


def framework_matrix_with_agents(system_ids: list[str] | None = None) -> EnrichedMatrixResult:
    """Compute enriched coverage matrix with per-agent breakdown.

    For each system:
    1. Computes the system's own per-framework coverage.
    2. For each bound agent, computes that agent's per-framework coverage
       derived from its ``framework_refs``.
    3. Returns the WORST (minimum) coverage across system + all bound agents
       for each framework cell.

    When a system has no bound agents the enriched row still includes
    ``agent_rows=[]`` and the cells equal the system's own coverage — backward
    compatible with the plain :func:`framework_matrix` shape.

    Args:
        system_ids: Optional list of system IDs to include. ``None`` = all
                    governed systems in the repository.

    Returns:
        :class:`EnrichedMatrixResult` with per-agent breakdown per system.
    """
    repo_systems = repository.list_ai_systems()
    repo_by_id = {s.id: s for s in repo_systems}

    framework_meta = [
        {"slug": slug, "display_name": framework_display_name(slug)}
        for slug, _fn in MATRIX_FRAMEWORKS
    ]

    if system_ids is not None:
        target_ids: list[str] = system_ids
    else:
        target_ids = [s.id for s in repo_systems]

    rows: list[EnrichedMatrixRow] = []
    for sid in target_ids:
        system = repo_by_id.get(sid)

        # System's own per-slug coverage
        system_cells: dict[str, float] = {}
        for slug, _fn in MATRIX_FRAMEWORKS:
            if system is None:
                system_cells[slug] = 0.0
            else:
                catalog_key = _FRAMEWORK_SLUG_TO_CATALOG_KEY.get(slug)
                system_cells[slug] = (
                    _system_framework_coverage(system.id, catalog_key) if catalog_key else 0.0
                )

        # Per-agent coverage
        agent_rows: list[AgentCoverageBreakdown] = []
        try:
            from domain.agent_bindings import list_bindings_for_system  # type: ignore[import]
            from domain.agents import get_agent  # type: ignore[import]

            bindings = list_bindings_for_system(sid)
            for binding in bindings:
                agent = get_agent(binding.agent_id)
                if agent is None:
                    continue
                agent_cells: dict[str, float] = {}
                for slug, _fn in MATRIX_FRAMEWORKS:
                    catalog_key = _FRAMEWORK_SLUG_TO_CATALOG_KEY.get(slug)
                    agent_cells[slug] = (
                        _agent_framework_coverage(binding.agent_id, binding.version_id, catalog_key)
                        if catalog_key else 0.0
                    )
                agent_rows.append(AgentCoverageBreakdown(
                    agent_id=binding.agent_id,
                    agent_name=getattr(agent, "name", binding.agent_id),
                    semver=binding.version_id,
                    cells=agent_cells,
                ))
        except (ImportError, Exception):  # noqa: BLE001
            # Implementer 1's modules not yet present, or no bindings
            pass

        # Worst-link aggregation: worst-of(system, each agent) per slug
        final_cells: dict[str, float] = {}
        for slug, _fn in MATRIX_FRAMEWORKS:
            worst = system_cells[slug]
            for ar in agent_rows:
                if ar.cells.get(slug, 100.0) < worst:
                    worst = ar.cells[slug]
            final_cells[slug] = worst

        rows.append(EnrichedMatrixRow(
            system_id=sid,
            system_name=system.name if system else sid,
            cells=final_cells,
            system_cells=system_cells,
            agent_rows=agent_rows,
        ))

    return EnrichedMatrixResult(frameworks=framework_meta, rows=rows)


def aggregate_agent_risk_tier(system_id: str) -> "RiskLevel":
    """Return the MAX(agent.inherent_risk) across all bound agents.

    Implements the weakest-link rule: one CRITICAL agent makes the system
    CRITICAL regardless of the system's own declared inherent_risk.

    When no agents are bound (or the agent modules are unavailable), returns
    the system's own inherent_risk — backward compatible.

    Args:
        system_id: The AI system identifier.

    Returns:
        The effective :class:`~domain.models.RiskLevel` for governance purposes.
    """
    from domain.models import RiskLevel

    _RISK_ORDER: dict[str, int] = {
        RiskLevel.LOW.value: 0,
        RiskLevel.MEDIUM.value: 1,
        RiskLevel.HIGH.value: 2,
        RiskLevel.CRITICAL.value: 3,
    }

    system = repository.get_ai_system(system_id)
    base_risk: str = system.inherent_risk.value if system else RiskLevel.LOW.value

    try:
        from domain.agent_bindings import list_bindings_for_system  # type: ignore[import]
        from domain.agents import get_agent  # type: ignore[import]

        bindings = list_bindings_for_system(system_id)
        if not bindings:
            risk_value = base_risk
        else:
            max_risk = base_risk
            for binding in bindings:
                agent = get_agent(binding.agent_id)
                if agent is None:
                    continue
                agent_risk: str = getattr(agent, "inherent_risk", RiskLevel.LOW.value)
                # Normalise to .value if it's an enum instance
                if hasattr(agent_risk, "value"):
                    agent_risk = agent_risk.value
                if _RISK_ORDER.get(agent_risk, 0) > _RISK_ORDER.get(max_risk, 0):
                    max_risk = agent_risk
            risk_value = max_risk
    except (ImportError, Exception):  # noqa: BLE001
        risk_value = base_risk

    # Return the RiskLevel enum member for the computed value
    return RiskLevel(risk_value)


__all__ = [
    "FrameworkItem", "ControlRollup", "FindingSummary", "ItemCoverage",
    "MatrixRow", "MatrixResult",
    "AgentCoverageBreakdown", "EnrichedMatrixRow", "EnrichedMatrixResult",
    "framework_catalog", "controls_for_item",
    "item_coverage", "framework_overview", "framework_matrix",
    "framework_matrix_with_agents", "aggregate_agent_risk_tier",
    "framework_display_name",
    "NIST_RMF_ITEMS", "NIST_600_1_ITEMS", "OWASP_LLM_ITEMS", "OWASP_AGENTIC_ITEMS",
    "MATRIX_FRAMEWORKS",
]
