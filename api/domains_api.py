"""Custom domain CRUD API — create, read, update, delete domains.

Session 30 — Track A OpenAPI sweep, per-router #6.

Strict-vs-list[dict] decision matrix (per compound rule 27a):
  GET /            → list[dict] envelope. Domain JSON files carry
                     arbitrary keys (eval_weights/risk_rules/test_cases
                     vary per file); consumers (compare.html picker,
                     memory.html picker) read 2-3 fields. Decouples the
                     OpenAPI surface from per-domain schema drift.
  GET /{domain_id} → strict mirror of DomainConfig + id, with
                     ConfigDict(extra="allow") to tolerate bounded
                     drift in stored JSON. domains.html edit modal
                     reads many fields.
  POST /{domain_id} → same strict mirror (response echoes stored data).
  PUT /{domain_id}  → same strict mirror.
  DELETE /{domain_id} → strict 2-field envelope; trivial, audit value.

operation_id convention: domains_<verb> per S30 plan.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from domains import list_domains
from audit import global_audit

router = APIRouter(prefix="/api/domains", tags=["domains"])

DOMAINS_DIR = Path(__file__).parent.parent / "domains"


# ===========================================================================
# Request / response models (Session 30 — Track A OpenAPI sweep, router #6)
# ===========================================================================


class DomainConfig(BaseModel):
    """Schema for creating/updating a domain (request body)."""

    name: str
    description: str
    prompt: str | None = None
    context: list[str] | None = None
    industry: str | None = None
    compliance: list[str] | None = None
    eval_weights: dict[str, Any] | None = None
    risk_rules: dict[str, Any] | None = None
    regulatory_context: list[str] | None = None
    test_cases: list[dict[str, Any]] | None = None


class DomainOut(BaseModel):
    """Single-domain response: DomainConfig fields + id.

    `extra="allow"` tolerates legacy keys in stored JSON files without
    forcing a schema migration. Single-record consumers (domains.html
    edit modal) read many fields, so a strict mirror is worthwhile.
    """

    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    description: str
    prompt: str | None = None
    context: list[str] | None = None
    industry: str | None = None
    compliance: list[str] | None = None
    eval_weights: dict[str, Any] | None = None
    risk_rules: dict[str, Any] | None = None
    regulatory_context: list[str] | None = None
    test_cases: list[dict[str, Any]] | None = None


class DomainListResponse(BaseModel):
    """Envelope for GET / (list).

    `domains` is list[dict] per compound 27a — domain JSON files carry
    arbitrary keys and picker consumers read few fields; decoupling
    OpenAPI from per-domain schema drift is the goal here.
    """

    domains: list[dict[str, Any]]
    count: int


class DomainDeleteResponse(BaseModel):
    """Envelope for DELETE /{domain_id}."""

    id: str
    deleted: bool


# ===========================================================================
# Routes
# ===========================================================================


@router.get(
    "/",
    response_model=DomainListResponse,
    operation_id="domains_list",
)
async def list_all_domains() -> DomainListResponse:
    """List all available domains with full configs."""
    domain_names = list_domains()
    domains: list[dict[str, Any]] = []

    for name in domain_names:
        try:
            with open(DOMAINS_DIR / f"{name}.json") as f:
                config = json.load(f)
            config["id"] = name
            domains.append(config)
        except Exception:
            continue

    return DomainListResponse(domains=domains, count=len(domains))


@router.get(
    "/{domain_id}",
    response_model=DomainOut,
    operation_id="domains_get",
)
async def get_domain(domain_id: str) -> DomainOut:
    """Get a specific domain configuration."""
    file_path = DOMAINS_DIR / f"{domain_id}.json"

    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"Domain '{domain_id}' not found")

    with open(file_path) as f:
        config = json.load(f)

    config["id"] = domain_id

    global_audit.log_action(
        action="read",
        resource_type="domain",
        resource_id=domain_id,
    )

    return DomainOut(**config)


@router.post(
    "/{domain_id}",
    response_model=DomainOut,
    operation_id="domains_create",
)
async def create_domain(domain_id: str, config: DomainConfig) -> DomainOut:
    """Create a new domain."""
    file_path = DOMAINS_DIR / f"{domain_id}.json"

    if file_path.exists():
        raise HTTPException(status_code=409, detail=f"Domain '{domain_id}' already exists")

    # Validate domain_id (alphanumeric + underscore only)
    if not domain_id.replace("_", "").isalnum():
        raise HTTPException(
            status_code=400,
            detail="Domain ID must be alphanumeric (underscores allowed)",
        )

    # Write file
    data = config.model_dump(exclude_none=True)
    with open(file_path, "w") as f:
        json.dump(data, f, indent=2)

    global_audit.log_action(
        action="create",
        resource_type="domain",
        resource_id=domain_id,
        after_state=data,
    )

    return DomainOut(id=domain_id, **data)


@router.put(
    "/{domain_id}",
    response_model=DomainOut,
    operation_id="domains_update",
)
async def update_domain(domain_id: str, config: DomainConfig) -> DomainOut:
    """Update an existing domain."""
    file_path = DOMAINS_DIR / f"{domain_id}.json"

    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"Domain '{domain_id}' not found")

    # Read before-state for audit
    with open(file_path) as f:
        before_state = json.load(f)

    # Write new config
    data = config.model_dump(exclude_none=True)
    with open(file_path, "w") as f:
        json.dump(data, f, indent=2)

    global_audit.log_action(
        action="update",
        resource_type="domain",
        resource_id=domain_id,
        before_state=before_state,
        after_state=data,
    )

    return DomainOut(id=domain_id, **data)


@router.delete(
    "/{domain_id}",
    response_model=DomainDeleteResponse,
    operation_id="domains_delete",
)
async def delete_domain(domain_id: str) -> DomainDeleteResponse:
    """Delete a domain."""
    file_path = DOMAINS_DIR / f"{domain_id}.json"

    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"Domain '{domain_id}' not found")

    # Read for audit before deletion
    with open(file_path) as f:
        before_state = json.load(f)

    file_path.unlink()

    global_audit.log_action(
        action="delete",
        resource_type="domain",
        resource_id=domain_id,
        before_state=before_state,
    )

    return DomainDeleteResponse(id=domain_id, deleted=True)
