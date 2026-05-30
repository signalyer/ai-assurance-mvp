"""Pydantic v2 return-schema models for the ARM read tools.

Every tool returns a model that includes a `schema_version` field. The agent
contract treats schema_version as part of the wire — adding a field is a
minor bump, removing or retyping is a major bump. The eval harness pins
against schema_version so prompt drift doesn't silently change the wire.

Per CLAUDE.md universal rules: strictest typing the language offers,
explicit field types, no `Any` escape hatches except where the underlying
Azure ARM payload is genuinely polymorphic (resource `properties` dict).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION: Literal["1.0"] = "1.0"


def _strict() -> ConfigDict:
    """Strict config used on every tool-return model."""
    return ConfigDict(extra="forbid", frozen=True)


# ---------------------------------------------------------------------------
# list_subscriptions
# ---------------------------------------------------------------------------


class SubscriptionSummary(BaseModel):
    """One subscription the caller has Reader on."""

    model_config = _strict()

    subscription_id: str
    display_name: str
    tenant_id: str
    state: Literal["Enabled", "Disabled", "Warned", "PastDue", "Deleted"]


class SubscriptionsListOut(BaseModel):
    model_config = _strict()
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    subscriptions: list[SubscriptionSummary]


# ---------------------------------------------------------------------------
# list_resource_groups
# ---------------------------------------------------------------------------


class ResourceGroupSummary(BaseModel):
    """One resource group in a subscription."""

    model_config = _strict()

    name: str
    location: str
    tags: dict[str, str] = Field(default_factory=dict)
    provisioning_state: str


class ResourceGroupsListOut(BaseModel):
    model_config = _strict()
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    subscription_id: str
    resource_groups: list[ResourceGroupSummary]


# ---------------------------------------------------------------------------
# list_resources_in_group
# ---------------------------------------------------------------------------


class ResourceSummary(BaseModel):
    """One Azure resource as returned by a list endpoint.

    Deliberately thin: list endpoints in ARM omit the polymorphic per-type
    `properties` blob, and including it would blow the per-turn token budget
    when the model fans out across multiple RGs. For drill-down detail use
    `get_resource_metadata(resource_id)` — that tool returns the full
    `ResourceMetadata` with properties populated.

    `sku` and `kind` are upstream-optional; we surface them as `None` rather
    than empty string so the WAF synthesis can distinguish "no SKU concept
    for this resource type" from "SKU=Free".
    """

    model_config = _strict()

    id: str = Field(..., description="Full ARM resource ID")
    name: str
    type: str = Field(..., description="ARM type, e.g. Microsoft.Web/sites")
    location: str
    sku: str | None = None
    kind: str | None = None
    tags: dict[str, str] = Field(default_factory=dict)


class ResourcesInGroupOut(BaseModel):
    model_config = _strict()
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    subscription_id: str
    resource_group: str
    resources: list[ResourceSummary]


# ---------------------------------------------------------------------------
# get_resource_metadata
# ---------------------------------------------------------------------------


class ResourceMetadata(BaseModel):
    """Detail row for a single Azure resource.

    `properties` is intentionally `dict` (polymorphic per resource_type); the
    Haiku per-resource summarization prompt is responsible for normalizing
    interesting fields into prose. The eval harness pins on the OUTER shape,
    not on `properties` contents.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    id: str = Field(..., description="Full ARM resource ID")
    name: str
    type: str = Field(..., description="ARM type, e.g. Microsoft.Web/sites")
    location: str
    resource_group: str
    sku: str | None = None
    tags: dict[str, str] = Field(default_factory=dict)
    properties: dict[str, object] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# list_role_assignments
# ---------------------------------------------------------------------------


class RoleAssignment(BaseModel):
    """One RBAC role assignment scoped at sub/rg/resource."""

    model_config = _strict()

    principal_id: str
    principal_type: Literal["User", "Group", "ServicePrincipal", "ForeignGroup", "Device"]
    role_definition_name: str
    scope: str
    condition: str | None = None


class RoleAssignmentsListOut(BaseModel):
    model_config = _strict()
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    scope: str
    role_assignments: list[RoleAssignment]


# ---------------------------------------------------------------------------
# get_network_topology
# ---------------------------------------------------------------------------


class VNetPeering(BaseModel):
    model_config = _strict()
    local_vnet: str
    remote_vnet: str
    peering_state: Literal["Initiated", "Connected", "Disconnected"]
    allow_forwarded_traffic: bool
    allow_gateway_transit: bool


class PrivateEndpoint(BaseModel):
    model_config = _strict()
    name: str
    subnet_id: str
    target_resource_id: str
    target_resource_type: str
    is_manual_approval: bool


class NetworkTopologyOut(BaseModel):
    model_config = _strict()
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    subscription_id: str
    vnets: list[str]
    peerings: list[VNetPeering]
    private_endpoints: list[PrivateEndpoint]


# ---------------------------------------------------------------------------
# render_mermaid_diagram
# ---------------------------------------------------------------------------


class MermaidRenderOut(BaseModel):
    """Result of rendering a Mermaid source string to SVG.

    `svg` is None when `parse_ok=False` — the diagram source did not compile.
    The agent's terminal-state contract is `(parse_ok=True, svg=<bytes>)`.
    """

    model_config = _strict()

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    parse_ok: bool
    svg: str | None = None
    error: str | None = None


__all__ = [
    "SCHEMA_VERSION",
    "SubscriptionSummary",
    "SubscriptionsListOut",
    "ResourceGroupSummary",
    "ResourceGroupsListOut",
    "ResourceSummary",
    "ResourcesInGroupOut",
    "ResourceMetadata",
    "RoleAssignment",
    "RoleAssignmentsListOut",
    "VNetPeering",
    "PrivateEndpoint",
    "NetworkTopologyOut",
    "MermaidRenderOut",
]
