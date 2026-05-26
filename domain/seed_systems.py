"""Seed data — 6 test AI systems each bound to 1-3 agents.

Creates systems in the repository (idempotent) and wires up agent bindings
once Implementer 1's domain/agent_bindings module is available.

Public API:
    seed_test_systems() -> list[AISystem]
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from domain.models import (
    AISystem,
    AgentTool,
    AutonomyLevel,
    CloudProvider,
    CustomerImpact,
    DataClass,
    Environment,
    RAGSource,
    RegulatoryExposure,
    ReleaseDecision,
    RiskLevel,
    RuntimeStatus,
)

_NOW = datetime(2026, 5, 21, 12, 0, 0)


# ---------------------------------------------------------------------------
# System definitions (no bindings yet — bindings wired in seed_test_systems)
# ---------------------------------------------------------------------------

_SYSTEM_DEFS: list[dict] = [
    {
        "id": "sys-payments-001",
        "name": "Payments Fraud Detection Platform",
        "description": (
            "Real-time fraud detection system for payment transactions.  Combines "
            "rule-based fraud screening with LLM-assisted case review.  Uses a "
            "PII-redacting agent before any model inference and a fraud-signal agent "
            "for anomaly classification.  All actions over $10K require HITL approval."
        ),
        "business_owner": "Elena Vasquez, SVP Payments Risk",
        "technical_owner": "Kai Chen, ML Platform Lead",
        "domain": "Payments Risk",
        "cloud_provider": CloudProvider.AWS,
        "environment": Environment.STAGING,
        "model_provider": "Anthropic via AWS Bedrock",
        "models_used": ["claude-sonnet-4-6", "internal-fraud-classifier-v4"],
        "data_classes": [
            DataClass.PII, DataClass.NPI, DataClass.ACCOUNT_NUMBERS,
            DataClass.TRANSACTION_DATA, DataClass.CUSTOMER_NAMES,
        ],
        "autonomy_level": AutonomyLevel.TOOL_USING_HITL,
        "user_population": "Internal — 180 Payments Risk analysts",
        "customer_impact": CustomerImpact.DIRECT_FINANCIAL,
        "regulatory_exposure": [
            RegulatoryExposure.GLBA, RegulatoryExposure.OFAC,
            RegulatoryExposure.FFIEC, RegulatoryExposure.SOX,
        ],
        "rag_enabled": True,
        "rag_sources": [
            RAGSource(
                name="Fraud Signal Corpus",
                type="vector_store",
                uri="s3://bank-rag-fraud-prod/signals-v8/",
                classification=[DataClass.TRANSACTION_DATA],
                version_controlled=True,
                last_refreshed=_NOW - timedelta(days=3),
            )
        ],
        "tools": [
            AgentTool(name="lookup_transaction", description="Read transaction details by id",
                      side_effect=False, authorization_required=True),
            AgentTool(name="flag_suspicious", description="Flag transaction for manual review",
                      side_effect=True, authorization_required=True, rate_limit_per_min=100),
            AgentTool(name="block_transaction", description="Block pending transaction",
                      side_effect=True, authorization_required=True, rate_limit_per_min=20),
        ],
        "aws_services": ["Bedrock", "S3", "Lambda", "Aurora PostgreSQL", "CloudTrail",
                         "CloudWatch", "KMS", "Macie"],
        "runtime_status": RuntimeStatus.STAGED,
        "release_decision": ReleaseDecision.HOLD,
        "inherent_risk": RiskLevel.HIGH,
        "residual_risk": RiskLevel.HIGH,
        "use_case": "Block 85% of fraudulent transactions before settlement with < 0.1% false-positive rate.",
        "human_oversight": "Required for transactions > $10K and cross-border flags.",
        "data_residency": "us-east-1",
        "bound_agent_ids": ["ai-agent-pay-fraud", "ai-agent-pii-redactor"],
    },
    {
        "id": "sys-cx-001",
        "name": "Customer Experience Routing Hub",
        "description": (
            "Multi-channel customer service routing hub.  Uses an LLM routing agent "
            "to classify incoming customer requests by intent and urgency, and a "
            "sentiment agent to prioritise distressed customers.  Routes to the "
            "appropriate queue or self-service workflow."
        ),
        "business_owner": "Priya Nair, SVP Customer Experience",
        "technical_owner": "Jake Osei, CX Engineering Lead",
        "domain": "Customer Experience",
        "cloud_provider": CloudProvider.AWS,
        "environment": Environment.PILOT,
        "model_provider": "Anthropic via AWS Bedrock",
        "models_used": ["claude-sonnet-4-6"],
        "data_classes": [
            DataClass.PII, DataClass.CUSTOMER_NAMES, DataClass.TRANSACTION_DATA,
        ],
        "autonomy_level": AutonomyLevel.TRIAGE,
        "user_population": "External — customer self-service portal (~1.2M customers)",
        "customer_impact": CustomerImpact.DIRECT,
        "regulatory_exposure": [RegulatoryExposure.CFPB, RegulatoryExposure.GLBA],
        "rag_enabled": False,
        "rag_sources": [],
        "tools": [
            AgentTool(name="classify_intent", description="Classify incoming request by intent type",
                      side_effect=False, authorization_required=False),
            AgentTool(name="route_to_queue", description="Route to named support queue",
                      side_effect=False, authorization_required=True),
        ],
        "aws_services": ["Bedrock", "Lambda", "API Gateway", "CloudTrail", "CloudWatch"],
        "runtime_status": RuntimeStatus.PILOT,
        "release_decision": ReleaseDecision.CONDITIONAL_PILOT,
        "inherent_risk": RiskLevel.MEDIUM,
        "residual_risk": RiskLevel.MEDIUM,
        "use_case": "Route 70% of incoming requests to the correct queue on first contact.",
        "human_oversight": "Escalation to human agent on CRITICAL sentiment or complaint keywords.",
        "data_residency": "us-east-1",
        "bound_agent_ids": ["ai-agent-cx-router", "ai-agent-sentiment"],
    },
    {
        "id": "sys-risk-001",
        "name": "Enterprise Risk Classification Engine",
        "description": (
            "End-to-end risk classification pipeline for commercial loan applications.  "
            "Uses a risk-classifier agent for structured risk scoring, a PII-redaction "
            "agent for document sanitisation before model inference, and a document "
            "summariser agent for financial statement abstraction.  Integrates with the "
            "core banking system."
        ),
        "business_owner": "Marcus Chen, Chief Risk Officer",
        "technical_owner": "Aisha Hassan, Risk Tech Lead",
        "domain": "Commercial Risk",
        "cloud_provider": CloudProvider.AWS,
        "environment": Environment.STAGING,
        "model_provider": "Anthropic via AWS Bedrock",
        "models_used": ["claude-opus-4-7", "internal-risk-model-v7"],
        "data_classes": [
            DataClass.PII, DataClass.NPI, DataClass.FINANCIAL_STATEMENTS,
            DataClass.INTERNAL_CREDIT, DataClass.CUSTOMER_NAMES,
        ],
        "autonomy_level": AutonomyLevel.DOCUMENT_GENERATION,
        "user_population": "Internal — 95 Commercial Risk officers",
        "customer_impact": CustomerImpact.DIRECT_FINANCIAL,
        "regulatory_exposure": [
            RegulatoryExposure.FFIEC, RegulatoryExposure.SOX,
            RegulatoryExposure.GLBA, RegulatoryExposure.CFPB,
        ],
        "rag_enabled": True,
        "rag_sources": [
            RAGSource(
                name="Regulatory Guidance Corpus",
                type="vector_store",
                uri="s3://bank-rag-risk-prod/regulatory-guidance/",
                classification=[DataClass.PUBLIC],
                version_controlled=True,
                last_refreshed=_NOW - timedelta(days=14),
            )
        ],
        "tools": [
            AgentTool(name="fetch_financials", description="Retrieve financial statement data",
                      side_effect=False, authorization_required=True),
            AgentTool(name="score_risk", description="Compute composite risk score",
                      side_effect=False, authorization_required=True),
        ],
        "aws_services": ["Bedrock", "S3", "Lambda", "Aurora PostgreSQL",
                         "CloudTrail", "CloudWatch", "KMS", "Security Hub"],
        "runtime_status": RuntimeStatus.STAGED,
        "release_decision": ReleaseDecision.HOLD,
        "inherent_risk": RiskLevel.CRITICAL,
        "residual_risk": RiskLevel.HIGH,
        "use_case": "Automate Tier-1 commercial risk classification; reduce analyst time by 50%.",
        "human_oversight": "Credit officer sign-off required before any risk rating is committed.",
        "data_residency": "us-east-1",
        "bound_agent_ids": ["ai-agent-risk-classifier", "ai-agent-pii-redactor",
                            "ai-agent-doc-summarizer"],
    },
    {
        "id": "sys-platform-001",
        "name": "Internal Platform Sentiment Monitor",
        "description": (
            "Lightweight sentiment analysis service used by internal teams to gauge "
            "employee and stakeholder sentiment from survey responses and internal "
            "communication summaries.  Read-only, no side effects, no customer data."
        ),
        "business_owner": "Linda Park, VP People Analytics",
        "technical_owner": "Tom Fraser, Platform Engineering",
        "domain": "Internal Operations",
        "cloud_provider": CloudProvider.AWS,
        "environment": Environment.PRODUCTION,
        "model_provider": "Anthropic via AWS Bedrock",
        "models_used": ["claude-sonnet-4-6"],
        "data_classes": [DataClass.PUBLIC],
        "autonomy_level": AutonomyLevel.ADVISORY,
        "user_population": "Internal — HR and management ~500 users",
        "customer_impact": CustomerImpact.NONE,
        "regulatory_exposure": [],
        "rag_enabled": False,
        "rag_sources": [],
        "tools": [],
        "aws_services": ["Bedrock", "Lambda", "CloudWatch"],
        "runtime_status": RuntimeStatus.PRODUCTION,
        "release_decision": ReleaseDecision.APPROVED,
        "inherent_risk": RiskLevel.LOW,
        "residual_risk": RiskLevel.LOW,
        "use_case": "Surface sentiment trends from internal survey data for People Analytics.",
        "human_oversight": "Outputs are advisory only; no automated actions taken.",
        "data_residency": "us-east-1",
        "bound_agent_ids": ["ai-agent-sentiment"],
    },
    {
        "id": "sys-finserv-001",
        "name": "FinServ Document Intelligence Pipeline",
        "description": (
            "Document processing pipeline for regulatory filings and customer documents.  "
            "Uses a PII-redaction agent before model inference and a document-summariser "
            "agent for structured extraction.  Outputs feed downstream compliance workflows."
        ),
        "business_owner": "Sandra Lee, Chief Compliance Officer",
        "technical_owner": "Ben Okafor, Compliance Tech Lead",
        "domain": "Regulatory Compliance",
        "cloud_provider": CloudProvider.AWS,
        "environment": Environment.PILOT,
        "model_provider": "Anthropic via AWS Bedrock",
        "models_used": ["claude-opus-4-7"],
        "data_classes": [
            DataClass.PII, DataClass.NPI, DataClass.KYC_DOCUMENTS,
            DataClass.CUSTOMER_NAMES, DataClass.FINANCIAL_STATEMENTS,
        ],
        "autonomy_level": AutonomyLevel.DOCUMENT_GENERATION,
        "user_population": "Internal — 60 Compliance staff",
        "customer_impact": CustomerImpact.INDIRECT,
        "regulatory_exposure": [
            RegulatoryExposure.FFIEC, RegulatoryExposure.GLBA,
            RegulatoryExposure.OFAC, RegulatoryExposure.SOX,
        ],
        "rag_enabled": True,
        "rag_sources": [
            RAGSource(
                name="Regulatory Filings Corpus",
                type="vector_store",
                uri="s3://bank-rag-compliance-prod/regulatory-filings/",
                classification=[DataClass.PUBLIC],
                version_controlled=True,
                last_refreshed=_NOW - timedelta(days=7),
            )
        ],
        "tools": [
            AgentTool(name="extract_document", description="Extract structured fields from document",
                      side_effect=False, authorization_required=True),
            AgentTool(name="submit_to_workflow", description="Submit extracted data to downstream workflow",
                      side_effect=True, authorization_required=True, rate_limit_per_min=50),
        ],
        "aws_services": ["Bedrock", "Textract", "S3", "Lambda", "CloudTrail",
                         "CloudWatch", "KMS", "Macie"],
        "runtime_status": RuntimeStatus.PILOT,
        "release_decision": ReleaseDecision.CONDITIONAL_PILOT,
        "inherent_risk": RiskLevel.HIGH,
        "residual_risk": RiskLevel.MEDIUM,
        "use_case": "Automate extraction of structured data from regulatory filings; reduce processing time by 70%.",
        "human_oversight": "Compliance officer review required before workflow submission.",
        "data_residency": "us-east-1",
        "bound_agent_ids": ["ai-agent-pii-redactor", "ai-agent-doc-summarizer"],
    },
    {
        "id": "sys-internal-001",
        "name": "Internal Knowledge Base Summariser",
        "description": (
            "Internal tool that summarises long-form documents (policies, SOPs, meeting notes) "
            "for knowledge management.  Read-only; no customer data; no external API calls.  "
            "Uses a single document-summariser agent."
        ),
        "business_owner": "Rachel Kim, Chief Knowledge Officer",
        "technical_owner": "Dan Rivera, Platform Engineering",
        "domain": "Internal Knowledge Management",
        "cloud_provider": CloudProvider.AZURE,
        "environment": Environment.PRODUCTION,
        "model_provider": "Anthropic direct API",
        "models_used": ["claude-sonnet-4-6"],
        "data_classes": [DataClass.PUBLIC],
        "autonomy_level": AutonomyLevel.DOCUMENT_GENERATION,
        "user_population": "Internal — all staff (~3 000 users)",
        "customer_impact": CustomerImpact.NONE,
        "regulatory_exposure": [],
        "rag_enabled": False,
        "rag_sources": [],
        "tools": [],
        "aws_services": [],
        "runtime_status": RuntimeStatus.PRODUCTION,
        "release_decision": ReleaseDecision.APPROVED,
        "inherent_risk": RiskLevel.MEDIUM,
        "residual_risk": RiskLevel.LOW,
        "use_case": "Provide instant structured summaries of internal policy documents.",
        "human_oversight": "Outputs are advisory; no automated publishing without human review.",
        "data_residency": "westus2",
        "bound_agent_ids": ["ai-agent-doc-summarizer"],
    },
]


def _build_system(defn: dict) -> AISystem:
    """Construct an :class:`AISystem` from a definition dict."""
    return AISystem(
        id=defn["id"],
        name=defn["name"],
        description=defn["description"],
        business_owner=defn["business_owner"],
        technical_owner=defn["technical_owner"],
        domain=defn["domain"],
        cloud_provider=defn["cloud_provider"],
        environment=defn["environment"],
        model_provider=defn["model_provider"],
        models_used=defn["models_used"],
        data_classes=defn["data_classes"],
        autonomy_level=defn["autonomy_level"],
        user_population=defn["user_population"],
        customer_impact=defn["customer_impact"],
        regulatory_exposure=defn["regulatory_exposure"],
        rag_enabled=defn.get("rag_enabled", False),
        rag_sources=defn.get("rag_sources", []),
        tools=defn.get("tools", []),
        aws_services=defn.get("aws_services", []),
        runtime_status=defn["runtime_status"],
        release_decision=defn["release_decision"],
        inherent_risk=defn["inherent_risk"],
        residual_risk=defn["residual_risk"],
        use_case=defn.get("use_case"),
        human_oversight=defn.get("human_oversight"),
        data_residency=defn.get("data_residency"),
        created_at=_NOW - timedelta(days=60),
        updated_at=_NOW,
    )


def seed_test_systems() -> list[AISystem]:
    """Idempotently create 6 test AI systems with agent bindings.

    Each system is only created (written to the repository) if it does not
    already exist (checked by ``id``).  Agent bindings are created via
    ``domain.agent_bindings.bind_agent_to_system`` with ``pinned=False``
    (auto-accept latest version) if the binding does not already exist.

    Agent binding creation is attempted silently — if Implementer 1's
    ``domain.agent_bindings`` module is not yet available, systems are still
    created and an informational log is emitted.

    Returns:
        List of all 6 :class:`AISystem` objects (newly created or pre-existing).
    """
    import json
    import logging
    from pathlib import Path

    from domain import repository

    _log = logging.getLogger(__name__)
    _DATA_DIR = Path(__import__("os").environ.get("DATA_ROOT") or (Path(__file__).resolve().parents[1] / "data"))
    _DATA_DIR.mkdir(exist_ok=True)
    _SYSTEMS_FILE = _DATA_DIR / "ai_systems.jsonl"

    # Build existing id set from repository (seed + JSONL)
    existing_ids: set[str] = {s.id for s in repository.list_ai_systems()}

    created: list[AISystem] = []
    for defn in _SYSTEM_DEFS:
        sid = defn["id"]
        if sid in existing_ids:
            _log.info(f"seed_test_systems: {sid} already exists — skipping")
            system = repository.get_ai_system(sid)
            if system is not None:
                created.append(system)
            continue

        system = _build_system(defn)
        # Append to repository JSONL
        with _SYSTEMS_FILE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(system.model_dump(mode="json"), default=str) + "\n")

        _log.info(f"seed_test_systems: created {sid}")
        created.append(system)
        existing_ids.add(sid)

    # Wire agent bindings — attempted after all systems are registered
    _wire_bindings(created)

    return created


def _wire_bindings(systems: list[AISystem]) -> None:
    """Create agent bindings for each seeded system.

    Silently skips if ``domain.agent_bindings`` is unavailable.  Bindings are
    created with ``pinned=False`` so the system auto-accepts the latest agent
    version.
    """
    import logging
    _log = logging.getLogger(__name__)

    try:
        from domain.agent_bindings import (  # type: ignore[import]
            bind_agent_to_system,
            list_bindings_for_system,
        )
    except ImportError:
        _log.info(
            "seed_test_systems: domain.agent_bindings not yet available — "
            "skipping binding wiring (run again once Implementer 1 is complete)"
        )
        return

    # Build lookup: system_id -> bound_agent_ids from our definitions
    defn_by_id: dict[str, list[str]] = {
        d["id"]: d.get("bound_agent_ids", []) for d in _SYSTEM_DEFS
    }

    for system in systems:
        agent_ids = defn_by_id.get(system.id, [])
        if not agent_ids:
            continue

        # Collect already-bound agent ids to make wiring idempotent
        try:
            existing_bindings = list_bindings_for_system(system.id)
            already_bound: set[str] = {b.agent_id for b in existing_bindings}
        except Exception as exc:  # noqa: BLE001
            _log.warning(f"seed_test_systems: could not list bindings for {system.id}: {exc}")
            already_bound = set()

        for agent_id in agent_ids:
            if agent_id in already_bound:
                _log.info(f"seed_test_systems: binding {agent_id} -> {system.id} already exists")
                continue
            try:
                bind_agent_to_system(agent_id=agent_id, system_id=system.id, pinned=False)
                _log.info(f"seed_test_systems: bound {agent_id} -> {system.id}")
            except Exception as exc:  # noqa: BLE001
                _log.warning(
                    f"seed_test_systems: failed to bind {agent_id} -> {system.id}: {exc}"
                )


# Convenience constant — used by tests to reference expected system IDs
SEEDED_SYSTEM_IDS: list[str] = [d["id"] for d in _SYSTEM_DEFS]

# Map system_id -> expected bound agent_ids (used by tests for assertion)
SEEDED_BINDINGS: dict[str, list[str]] = {
    d["id"]: d.get("bound_agent_ids", []) for d in _SYSTEM_DEFS
}


__all__ = [
    "seed_test_systems",
    "SEEDED_SYSTEM_IDS",
    "SEEDED_BINDINGS",
]
