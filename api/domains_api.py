"""Custom domain CRUD API — create, read, update, delete domains."""

import json
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from domains import list_domains, load_domain
from audit import global_audit

router = APIRouter(prefix="/api/domains", tags=["domains"])

DOMAINS_DIR = Path(__file__).parent.parent / "domains"


class DomainConfig(BaseModel):
    """Schema for creating/updating a domain."""
    name: str
    description: str
    prompt: str | None = None
    context: list[str] | None = None
    industry: str | None = None
    compliance: list[str] | None = None
    eval_weights: dict | None = None
    risk_rules: dict | None = None
    regulatory_context: list[str] | None = None
    test_cases: list[dict] | None = None


@router.get("/")
async def list_all_domains() -> dict:
    """List all available domains with full configs."""
    domain_names = list_domains()
    domains = []

    for name in domain_names:
        try:
            with open(DOMAINS_DIR / f"{name}.json") as f:
                config = json.load(f)
            config["id"] = name
            domains.append(config)
        except Exception as e:
            continue

    return {"domains": domains, "count": len(domains)}


@router.get("/{domain_id}")
async def get_domain(domain_id: str) -> dict:
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

    return config


@router.post("/{domain_id}")
async def create_domain(domain_id: str, config: DomainConfig) -> dict:
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
    data = config.dict(exclude_none=True)
    with open(file_path, "w") as f:
        json.dump(data, f, indent=2)

    global_audit.log_action(
        action="create",
        resource_type="domain",
        resource_id=domain_id,
        after_state=data,
    )

    return {"id": domain_id, **data}


@router.put("/{domain_id}")
async def update_domain(domain_id: str, config: DomainConfig) -> dict:
    """Update an existing domain."""
    file_path = DOMAINS_DIR / f"{domain_id}.json"

    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"Domain '{domain_id}' not found")

    # Read before-state for audit
    with open(file_path) as f:
        before_state = json.load(f)

    # Write new config
    data = config.dict(exclude_none=True)
    with open(file_path, "w") as f:
        json.dump(data, f, indent=2)

    global_audit.log_action(
        action="update",
        resource_type="domain",
        resource_id=domain_id,
        before_state=before_state,
        after_state=data,
    )

    return {"id": domain_id, **data}


@router.delete("/{domain_id}")
async def delete_domain(domain_id: str) -> dict:
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

    return {"id": domain_id, "deleted": True}
