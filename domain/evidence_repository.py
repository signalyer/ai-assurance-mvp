"""Evidence Repository — audit-ready completeness, sectioning, and rollups.

Sections (eight, per spec):
  1. Assessment evidence
  2. Eval evidence
  3. Runtime trace evidence
  4. Approval evidence
  5. Architecture snapshots
  6. Model/version evidence
  7. Prompt/tool/policy version evidence
  8. Exception/waiver evidence

Specific subtypes (e.g. BEDROCK_CONFIG) "roll up" to satisfy general control
evidence requirements (e.g. POLICY_ATTESTATION). The rollup keeps existing
controls compatible while letting the UI organize by the realistic artifacts
that engineers and auditors actually deal with.
"""

from __future__ import annotations

from dataclasses import dataclass

from domain.models import EvidenceType, FrameworkName
from domain.controls import (
    CONTROLS, CONTROLS_BY_ID, is_applicable, get_required_controls,
    get_controls_for_ai_system,
)
from domain import repository


# ---------------------------------------------------------------------------
# Section catalog
# ---------------------------------------------------------------------------

SECTIONS: list[dict] = [
    {"id": "assessment",  "name": "Assessment Evidence",            "types": [EvidenceType.POLICY_ATTESTATION]},
    {"id": "eval",        "name": "Eval Evidence",                  "types": [EvidenceType.EVAL_RUN, EvidenceType.GARAK_REPORT, EvidenceType.PYRIT_REPORT, EvidenceType.RED_TEAM_REPORT, EvidenceType.PEN_TEST]},
    {"id": "runtime",     "name": "Runtime Trace Evidence",         "types": [EvidenceType.RUNTIME_TELEMETRY, EvidenceType.LANGFUSE_TRACE, EvidenceType.CLOUDTRAIL_EVENT, EvidenceType.MACIE_FINDING, EvidenceType.SECURITY_HUB_FINDING, EvidenceType.AUDIT_LOG]},
    {"id": "approval",    "name": "Approval Evidence",              "types": [EvidenceType.APPROVAL_RECORD]},
    {"id": "arch",        "name": "Architecture Snapshots",         "types": [EvidenceType.ARCHITECTURE_DIAGRAM, EvidenceType.TERRAFORM_SNAPSHOT, EvidenceType.IAM_POLICY_SNAPSHOT, EvidenceType.BEDROCK_CONFIG, EvidenceType.RAG_CONFIG]},
    {"id": "model",       "name": "Model / Version Evidence",       "types": [EvidenceType.MODEL_CARD, EvidenceType.THIRD_PARTY_REPORT, EvidenceType.DATA_LINEAGE]},
    {"id": "versions",    "name": "Prompt / Tool / Policy Version", "types": [EvidenceType.PROMPT_VERSION_RECORD, EvidenceType.TOOL_VERSION_RECORD, EvidenceType.POLICY_VERSION_RECORD]},
    {"id": "waiver",      "name": "Exception / Waiver Evidence",    "types": [EvidenceType.EXCEPTION_WAIVER, EvidenceType.REMEDIATION_VERIFICATION]},
]

_TYPE_TO_SECTION: dict[EvidenceType, str] = {t: s["id"] for s in SECTIONS for t in s["types"]}


# Rollup: a specific subtype satisfies a general type for completeness purposes.
_ROLLUP_TO_GENERAL: dict[EvidenceType, EvidenceType] = {
    EvidenceType.ARCHITECTURE_DIAGRAM:    EvidenceType.POLICY_ATTESTATION,
    EvidenceType.TERRAFORM_SNAPSHOT:      EvidenceType.POLICY_ATTESTATION,
    EvidenceType.IAM_POLICY_SNAPSHOT:     EvidenceType.POLICY_ATTESTATION,
    EvidenceType.BEDROCK_CONFIG:          EvidenceType.POLICY_ATTESTATION,
    EvidenceType.RAG_CONFIG:              EvidenceType.DATA_LINEAGE,
    EvidenceType.LANGFUSE_TRACE:          EvidenceType.RUNTIME_TELEMETRY,
    EvidenceType.GARAK_REPORT:            EvidenceType.RED_TEAM_REPORT,
    EvidenceType.PYRIT_REPORT:            EvidenceType.RED_TEAM_REPORT,
    EvidenceType.MACIE_FINDING:           EvidenceType.RUNTIME_TELEMETRY,
    EvidenceType.SECURITY_HUB_FINDING:    EvidenceType.RUNTIME_TELEMETRY,
    EvidenceType.CLOUDTRAIL_EVENT:        EvidenceType.AUDIT_LOG,
    EvidenceType.EXCEPTION_WAIVER:        EvidenceType.APPROVAL_RECORD,
    EvidenceType.REMEDIATION_VERIFICATION: EvidenceType.AUDIT_LOG,
    EvidenceType.PROMPT_VERSION_RECORD:   EvidenceType.POLICY_ATTESTATION,
    EvidenceType.TOOL_VERSION_RECORD:     EvidenceType.POLICY_ATTESTATION,
    EvidenceType.POLICY_VERSION_RECORD:   EvidenceType.POLICY_ATTESTATION,
}


def section_for(et: EvidenceType) -> str:
    return _TYPE_TO_SECTION.get(et, "other")


def general_types_satisfied_by(et: EvidenceType) -> set[EvidenceType]:
    """An evidence record of type `et` satisfies the requirement for `et` itself
    and (if it's a specific subtype) the general type it rolls up to."""
    out = {et}
    g = _ROLLUP_TO_GENERAL.get(et)
    if g:
        out.add(g)
    return out


# ---------------------------------------------------------------------------
# Completeness — 4 axes
# ---------------------------------------------------------------------------

@dataclass
class CompletenessRow:
    label: str
    present: int
    required: int
    pct: float
    missing: list[str]                       # human-readable, e.g. "AI-006: RED_TEAM_REPORT"


def _present_general_types(evidence_list) -> set[EvidenceType]:
    out: set[EvidenceType] = set()
    for e in evidence_list:
        out |= general_types_satisfied_by(e.evidence_type)
    return out


def _completeness_against_controls(controls, evidence_list) -> tuple[int, int, list[str]]:
    """For the given controls, count (present_pairs, required_pairs, missing_descriptions).

    A (control, required_evidence_type) pair is satisfied when ANY evidence
    record's type either matches that required type directly or rolls up to it.
    """
    present_types = _present_general_types(evidence_list)
    required = 0
    present = 0
    missing: list[str] = []
    for c in controls:
        for et in c.evidence_required:
            required += 1
            if et in present_types:
                present += 1
            else:
                missing.append(f"{c.control_id}: {et.value}")
    return present, required, missing


def completeness_by_ai_system() -> list[CompletenessRow]:
    """Evidence completeness for every AI system across its required controls."""
    out: list[CompletenessRow] = []
    for s in repository.list_ai_systems():
        ctrls = get_required_controls(s)
        ev = repository.evidence_for(s.id)
        present, required, missing = _completeness_against_controls(ctrls, ev)
        pct = (present / required * 100.0) if required else 100.0
        out.append(CompletenessRow(
            label=f"{s.id} — {s.name}", present=present, required=required,
            pct=round(pct, 1), missing=missing[:15],
        ))
    return out


def completeness_by_framework(framework: FrameworkName, scope: str = "ALL") -> CompletenessRow:
    """Aggregate completeness over controls that map to a given framework."""
    if scope == "ALL":
        systems = repository.list_ai_systems()
    else:
        s = repository.get_ai_system(scope)
        systems = [s] if s else []

    fw_controls = [c for c in CONTROLS if any(fm.framework == framework for fm in c.framework_mappings)]

    total_present = 0
    total_required = 0
    missing: list[str] = []
    for sys in systems:
        applicable = [c for c in fw_controls if is_applicable(c, sys)]
        ev = repository.evidence_for(sys.id)
        p, r, m = _completeness_against_controls(applicable, ev)
        total_present += p
        total_required += r
        missing.extend(f"{sys.id}: {x}" for x in m)
    pct = (total_present / total_required * 100.0) if total_required else 100.0
    return CompletenessRow(
        label=framework.value, present=total_present, required=total_required,
        pct=round(pct, 1), missing=missing[:15],
    )


def completeness_by_control_domain(scope: str = "ALL") -> list[CompletenessRow]:
    """One row per ControlDomain."""
    from domain.models import ControlDomain
    if scope == "ALL":
        systems = repository.list_ai_systems()
    else:
        s = repository.get_ai_system(scope)
        systems = [s] if s else []

    out: list[CompletenessRow] = []
    for domain in ControlDomain:
        dom_controls = [c for c in CONTROLS if c.domain == domain]
        total_present = 0
        total_required = 0
        missing: list[str] = []
        for sys in systems:
            applicable = [c for c in dom_controls if is_applicable(c, sys)]
            ev = repository.evidence_for(sys.id)
            p, r, m = _completeness_against_controls(applicable, ev)
            total_present += p
            total_required += r
            missing.extend(f"{sys.id}: {x}" for x in m)
        if total_required == 0:
            continue
        pct = total_present / total_required * 100.0
        out.append(CompletenessRow(
            label=domain.value, present=total_present, required=total_required,
            pct=round(pct, 1), missing=missing[:10],
        ))
    return out


def completeness_by_release_gate(scope: str = "ALL") -> list[CompletenessRow]:
    """One row per release gate, computed against its mapped controls."""
    from domain.release_gate_engine import GATE_DEFS, _GATE_TO_CONTROLS
    if scope == "ALL":
        systems = repository.list_ai_systems()
    else:
        s = repository.get_ai_system(scope)
        systems = [s] if s else []

    out: list[CompletenessRow] = []
    for gid, definition in GATE_DEFS.items():
        gate_controls = [CONTROLS_BY_ID[cid] for cid in _GATE_TO_CONTROLS[gid] if cid in CONTROLS_BY_ID]
        if not gate_controls:
            continue
        total_present = 0
        total_required = 0
        missing: list[str] = []
        for sys in systems:
            applicable = [c for c in gate_controls if is_applicable(c, sys)]
            ev = repository.evidence_for(sys.id)
            p, r, m = _completeness_against_controls(applicable, ev)
            total_present += p
            total_required += r
            missing.extend(f"{sys.id}: {x}" for x in m)
        if total_required == 0:
            continue
        pct = total_present / total_required * 100.0
        out.append(CompletenessRow(
            label=f"{gid} — {definition.name}", present=total_present, required=total_required,
            pct=round(pct, 1), missing=missing[:10],
        ))
    return out


# ---------------------------------------------------------------------------
# Sectioned listing
# ---------------------------------------------------------------------------

@dataclass
class EvidenceRow:
    id: str
    ai_system_id: str
    ai_system_name: str
    assessment_id: str | None
    evidence_type: str
    evidence_type_pretty: str
    section_id: str
    section_name: str
    source: str
    collected_at: str
    hash: str | None
    immutable: bool
    summary: str
    uri: str | None
    linked_control_ids: list[str]
    linked_finding_ids: list[str]
    linked_frameworks: list[str]


def _pretty(et: EvidenceType) -> str:
    return et.value.replace("_", " ").title()


def list_evidence_sectioned(scope: str = "ALL") -> dict[str, list[EvidenceRow]]:
    """Return {section_id: [EvidenceRow...]} for the given scope."""
    if scope == "ALL":
        systems = repository.list_ai_systems()
    else:
        s = repository.get_ai_system(scope)
        systems = [s] if s else []
    sys_name = {s.id: s.name for s in systems}

    sections: dict[str, list[EvidenceRow]] = {s["id"]: [] for s in SECTIONS}
    sections["other"] = []

    for sys in systems:
        for e in repository.evidence_for(sys.id):
            sec_id = section_for(e.evidence_type)
            sec_name = next((s["name"] for s in SECTIONS if s["id"] == sec_id), "Other")
            row = EvidenceRow(
                id=e.id, ai_system_id=sys.id, ai_system_name=sys_name.get(sys.id, sys.id),
                assessment_id=e.assessment_id,
                evidence_type=e.evidence_type.value,
                evidence_type_pretty=_pretty(e.evidence_type),
                section_id=sec_id, section_name=sec_name,
                source=e.source, collected_at=e.collected_at.isoformat(),
                hash=e.hash, immutable=e.immutable, summary=e.summary, uri=e.uri,
                linked_control_ids=list(e.linked_control_ids),
                linked_finding_ids=list(e.linked_finding_ids),
                linked_frameworks=list(e.linked_frameworks),
            )
            sections.setdefault(sec_id, []).append(row)

    # Sort each section by collected_at desc
    for v in sections.values():
        v.sort(key=lambda r: r.collected_at, reverse=True)
    return sections


__all__ = [
    "SECTIONS", "section_for", "general_types_satisfied_by",
    "completeness_by_ai_system", "completeness_by_framework",
    "completeness_by_control_domain", "completeness_by_release_gate",
    "list_evidence_sectioned", "EvidenceRow", "CompletenessRow",
]
