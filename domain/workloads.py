"""AI Workload definition layer (Step 1 of the AI Assurance flow).

The workload is the ROOT object. Selecting it drives downstream intake fields,
required controls, eval packs, release gates, evidence, provider routing, and
runtime policies. This module hosts the schema, registry, and selection store.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)
SELECTIONS_FILE = DATA_DIR / "workload_selections.jsonl"


@dataclass
class AIWorkload:
    id: str
    name: str
    display_name: str
    category: str
    description: str
    workload_type: str
    primary_outputs: list[str]
    allowed_actions: list[str]
    blocked_actions: list[str]
    default_autonomy: str
    default_release_target: str
    default_risk_level: str
    risk_reason: str
    allowed_input_sources: list[str]
    blocked_input_sources: list[str]
    allowed_data_classes: list[str]
    blocked_data_classes: list[str]
    raw_data_processing_boundary: str
    external_llm_policy: str
    required_human_review: bool
    created_at: str = ""
    updated_at: str = ""


@dataclass
class SelectedAIWorkload:
    workload_id: str
    workload_type: str
    display_name: str
    selected_at: str
    selected_by: str


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


_NOW = _iso_now()


_WORKLOADS: dict[str, AIWorkload] = {
    "aws-logical-architecture-security-posture-analyzer": AIWorkload(
        id="aws-logical-architecture-security-posture-analyzer",
        name="aws-logical-architecture-security-posture-analyzer",
        display_name="AWS Deployment Logical Architecture & Security Posture Analyzer",
        category="Cloud Security / Enterprise Architecture",
        workload_type="aws_deployment_analyzer",
        description=(
            "Reads AWS deployment metadata and generates a logical architecture "
            "diagram, component inventory, trust-boundary map, data-flow map, "
            "security posture assessment, remediation guidance, and evidence-backed "
            "architecture analysis document."
        ),
        primary_outputs=[
            "Architecture Analysis Document",
            "Logical Architecture Diagram",
            "Component Inventory",
            "Data Flow Map",
            "Trust Boundary Map",
            "Security Posture Assessment",
            "Security Findings Placeholder",
            "Remediation Plan Placeholder",
            "Evidence Appendix Placeholder",
        ],
        allowed_actions=[
            "Read deployment metadata", "Read Terraform", "Read CloudFormation",
            "Read AWS Config snapshots", "Read IAM policy metadata", "Read VPC topology",
            "Read security group rules", "Read route table metadata",
            "Read Security Hub findings", "Read GuardDuty findings", "Read Macie findings",
            "Read CloudTrail configuration", "Read CloudWatch configuration",
            "Generate logical architecture diagram", "Generate component inventory",
            "Generate trust-boundary map", "Generate data-flow map",
            "Generate security posture assessment", "Generate architecture analysis document",
        ],
        blocked_actions=[
            "Modify AWS resources", "Change IAM policies", "Update security groups",
            "Deploy infrastructure", "Delete resources", "Rotate secrets",
            "Access raw secrets", "Query application databases", "Access raw customer data",
            "Access raw application logs containing sensitive payloads",
            "Execute remediation autonomously",
            "Send raw customer deployment data to external LLMs",
        ],
        default_autonomy="Read-only analysis / Recommend only",
        default_release_target="Internal Pilot",
        default_risk_level="High",
        risk_reason=(
            "Reads AWS security-sensitive metadata including IAM policies, VPC "
            "topology, deployment configuration, account boundaries, and security "
            "findings. This creates security-sensitive exposure even when PII is "
            "not present."
        ),
        allowed_input_sources=[
            "Terraform", "CloudFormation", "AWS Config snapshots", "IAM policies",
            "IAM trust policies", "VPC topology", "Subnet metadata",
            "Security group rules", "Route tables", "API Gateway configuration",
            "ALB/NLB configuration", "Lambda metadata", "ECS metadata", "EKS metadata",
            "EC2 metadata", "Step Functions metadata", "SQS/SNS/EventBridge metadata",
            "S3 bucket policies", "Aurora/RDS metadata", "DynamoDB metadata",
            "OpenSearch metadata", "Bedrock configuration", "KMS key metadata",
            "Secrets Manager metadata only", "CloudTrail configuration",
            "CloudWatch configuration", "Security Hub findings", "GuardDuty findings",
            "Macie findings",
        ],
        blocked_input_sources=[
            "Raw secrets", "Secret values", "KMS plaintext material",
            "Raw customer data", "Customer PII", "NPI", "PCI", "Payment data",
            "AML/KYC records", "Credit records", "Raw database records",
            "Raw application logs with sensitive payloads",
        ],
        allowed_data_classes=[
            "Internal", "Confidential", "Security-sensitive metadata",
            "AWS architecture metadata", "IAM policy metadata",
            "Network topology metadata", "Security findings metadata",
            "Sanitized summaries", "Synthetic data", "Redacted evidence",
        ],
        blocked_data_classes=[
            "Raw secrets", "Raw customer data", "PII", "NPI", "PCI",
            "Payment data", "AML/KYC data", "Credit data", "Raw application logs",
            "Customer-identifying infrastructure metadata exposed externally",
        ],
        raw_data_processing_boundary=(
            "Raw AWS deployment metadata must be processed only inside an approved "
            "AWS, customer VPC, local model, deterministic parser, or in-boundary "
            "analysis worker."
        ),
        external_llm_policy=(
            "External LLMs are prohibited from processing raw customer deployment "
            "data. OpenAI and Anthropic may only be used later for sanitized "
            "summaries, redacted findings, synthetic test cases, aggregate scores, "
            "or generic narrative generation after sanitization and policy "
            "validation."
        ),
        required_human_review=True,
        created_at=_NOW,
        updated_at=_NOW,
    ),
}


def list_workloads() -> list[dict]:
    return [asdict(w) for w in _WORKLOADS.values()]


def get_workload(workload_id: str) -> Optional[dict]:
    w = _WORKLOADS.get(workload_id)
    return asdict(w) if w else None


def select_workload(workload_id: str, selected_by: str) -> Optional[SelectedAIWorkload]:
    w = _WORKLOADS.get(workload_id)
    if w is None:
        return None
    sel = SelectedAIWorkload(
        workload_id=w.id,
        workload_type=w.workload_type,
        display_name=w.display_name,
        selected_at=_iso_now(),
        selected_by=selected_by or "system",
    )
    with SELECTIONS_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(asdict(sel), ensure_ascii=False) + "\n")
    return sel


def current_selection() -> Optional[dict]:
    if not SELECTIONS_FILE.exists():
        return None
    last: Optional[dict] = None
    with SELECTIONS_FILE.open("r", encoding="utf-8") as fh:
        for line in fh:
            try:
                last = json.loads(line)
            except json.JSONDecodeError:
                continue
    return last


def selection_history(limit: int = 20) -> list[dict]:
    if not SELECTIONS_FILE.exists():
        return []
    out: list[dict] = []
    with SELECTIONS_FILE.open("r", encoding="utf-8") as fh:
        for line in fh:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out[-limit:][::-1]


def _seed_select_if_needed() -> None:
    """Auto-select the AWS analyzer on first boot — gives the walkthrough
    something to render. Idempotent: only writes if no selection exists."""
    if current_selection() is None:
        select_workload("aws-logical-architecture-security-posture-analyzer", "system")


_seed_select_if_needed()
