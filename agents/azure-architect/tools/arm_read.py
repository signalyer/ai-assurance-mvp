"""ARM read tools — async functions wrapping azure.mgmt.* packages.

P4 Day-1 deliverable. Skeleton-only in S55 prep: signatures, docstrings,
JSON-schema-pinned return types, NotImplementedError bodies. S60 STEP 1
fills in the first body: `list_resource_groups`.

Auth contract: every function expects an azure.identity credential injected
via the agent's startup path (`agent.py::_init_azure_credential`). No env-var
sniffing inside individual tool functions — keeps the trust boundary at
one explicit init site, per CLAUDE.md universal rule "SDK Client
Initialisation: always at module/global scope".

Governance contract (S60): every tool is wrapped with
`@signallayer.policy_gate(action="tool_invoke")` and accepts a `tool_name`
kwarg whose value matches the function name. `middleware.policy._evaluate_policy`
auto-extracts `tool_name` into the rego input, which fires Rule 1 (allowlist)
and Rule 2 (mutation-verb) in `policies/azure-architect.rego`. Adding a
function here that is NOT in the rego `readonly_azure_tools` set will deny
at runtime — single source of truth.
"""

from __future__ import annotations

import asyncio
import os
from typing import Protocol

import signallayer

from .schemas import (
    NetworkTopologyOut,
    ResourceGroupSummary,
    ResourceGroupsListOut,
    ResourceMetadata,
    ResourceSummary,
    ResourcesInGroupOut,
    RoleAssignmentsListOut,
    SubscriptionsListOut,
)


# ---------------------------------------------------------------------------
# Credential protocol — duck-types azure.identity.TokenCredential without
# importing the real package, so this module is unit-testable in isolation.
# ---------------------------------------------------------------------------


class _Cred(Protocol):
    def get_token(self, *scopes: str) -> object: ...  # pragma: no cover


# ---------------------------------------------------------------------------
# Tool 1 — list_subscriptions
# ---------------------------------------------------------------------------


async def list_subscriptions(credential: _Cred) -> SubscriptionsListOut:
    """Enumerate every subscription the caller has Reader on.

    Wraps `azure.mgmt.subscription.SubscriptionClient.subscriptions.list`.
    The SDK call is synchronous; wrap with asyncio.to_thread in P4.

    Args:
        credential: An azure.identity credential. ManagedIdentityCredential
            in production; DefaultAzureCredential in dev.

    Returns:
        Strict SubscriptionsListOut. Empty list is a valid result (caller
        has zero subscriptions).
    """
    raise NotImplementedError("P4 Day-1 — wrap azure.mgmt.subscription.SubscriptionClient")


# ---------------------------------------------------------------------------
# Tool 2 — list_resource_groups
# ---------------------------------------------------------------------------


@signallayer.policy_gate(action="tool_invoke")
async def list_resource_groups(
    credential: _Cred,
    subscription_id: str,
    *,
    tool_name: str = "list_resource_groups",
    workload_id: str = "azure-architect",
) -> ResourceGroupsListOut:
    """List every resource group in one subscription.

    Wraps `azure.mgmt.resource.ResourceManagementClient.resource_groups.list`.
    The SDK call is synchronous; we wrap it in `asyncio.to_thread` so the
    orchestration loop can fan-out tool calls without blocking the event loop.

    Args:
        credential: Azure credential (DefaultAzureCredential in dev,
            ManagedIdentityCredential in prod). Injected by the agent
            startup path; never sourced here from env.
        subscription_id: Target subscription GUID.
        tool_name: Identity for the policy engine. DO NOT override at call
            site — it is the contract key used by rego Rule 1 (allowlist)
            and Rule 2 (mutation-verb prefix). Default matches function name.
        workload_id: Workload identity for policy + audit attribution.

    Returns:
        Strict ResourceGroupsListOut (pydantic v2, frozen, extra="forbid").

    Raises:
        signallayer.PolicyDeniedError: If rego denies the call.
        RuntimeError: If azure-mgmt-resource is not installed in the env.
    """
    try:
        from azure.mgmt.resource import ResourceManagementClient
    except ImportError as exc:
        raise RuntimeError(
            "azure-mgmt-resource not installed. Run "
            "`uv pip install -e agents/azure-architect` (or install the "
            "package directly) before invoking ARM read tools."
        ) from exc

    def _call_sync() -> list[ResourceGroupSummary]:
        client = ResourceManagementClient(credential, subscription_id)
        groups: list[ResourceGroupSummary] = []
        for rg in client.resource_groups.list():
            groups.append(
                ResourceGroupSummary(
                    name=rg.name or "",
                    location=rg.location or "",
                    tags=dict(rg.tags or {}),
                    provisioning_state=(
                        getattr(rg, "properties", None)
                        and getattr(rg.properties, "provisioning_state", "")
                    ) or "",
                )
            )
        return groups

    resource_groups = await asyncio.to_thread(_call_sync)
    return ResourceGroupsListOut(
        subscription_id=subscription_id,
        resource_groups=resource_groups,
    )


# ---------------------------------------------------------------------------
# Tool 2b — list_resources_in_group  (S62)
# ---------------------------------------------------------------------------


@signallayer.policy_gate(action="tool_invoke")
async def list_resources_in_group(
    credential: _Cred,
    subscription_id: str,
    resource_group: str,
    *,
    tool_name: str = "list_resources_in_group",
    workload_id: str = "azure-architect",
) -> ResourcesInGroupOut:
    """List every resource inside one resource group.

    Wraps `ResourceManagementClient.resources.list_by_resource_group`. Uses
    the same client + credential as `list_resource_groups` so no extra Azure
    SDK install is needed. The SDK call is synchronous; we wrap in
    `asyncio.to_thread` so the orchestration loop can fan-out future calls.

    Returns a thin `ResourceSummary` per item (id/name/type/location/sku/kind/
    tags). The polymorphic ARM `properties` blob is omitted by ARM at this
    endpoint; use `get_resource_metadata(resource_id)` to drill into one
    resource's full property set.

    Multi-turn chaining contract: the model gets RG names from
    `list_resource_groups`, then calls THIS tool with one of those names to
    enumerate contents. That's the canonical two-turn pattern for a
    subscription audit.

    Args:
        credential: Azure credential injected at agent startup.
        subscription_id: Target subscription GUID.
        resource_group: Name of the RG to enumerate. Must match a name
            returned by a prior `list_resource_groups` call.
        tool_name: Identity for the policy engine. DO NOT override.
        workload_id: Workload identity for policy + audit attribution.

    Returns:
        Strict ResourcesInGroupOut (pydantic v2, frozen, extra="forbid").

    Raises:
        signallayer.PolicyDeniedError: If rego denies the call.
        RuntimeError: If azure-mgmt-resource is not installed.
        azure.core.exceptions.ResourceNotFoundError: If `resource_group`
            does not exist in `subscription_id`. The orchestration loop
            converts this to an `is_error` tool_result so the model can
            self-correct (e.g. retry with a typo'd name fixed).
    """
    try:
        from azure.mgmt.resource import ResourceManagementClient
    except ImportError as exc:
        raise RuntimeError(
            "azure-mgmt-resource not installed. Run "
            "`pip install azure-mgmt-resource azure-identity` before "
            "invoking ARM read tools."
        ) from exc

    def _call_sync() -> list[ResourceSummary]:
        client = ResourceManagementClient(credential, subscription_id)
        out: list[ResourceSummary] = []
        # list_by_resource_group returns GenericResource iterable. `.sku` is
        # a SkuDescription object (or None) — we flatten to its name; full
        # SKU detail is available via get_resource_metadata if needed.
        for r in client.resources.list_by_resource_group(resource_group):
            sku_val: str | None = None
            if getattr(r, "sku", None) is not None:
                sku_val = getattr(r.sku, "name", None) or None
            out.append(
                ResourceSummary(
                    id=r.id or "",
                    name=r.name or "",
                    type=r.type or "",
                    location=r.location or "",
                    sku=sku_val,
                    kind=getattr(r, "kind", None) or None,
                    tags=dict(r.tags or {}),
                )
            )
        return out

    resources = await asyncio.to_thread(_call_sync)
    return ResourcesInGroupOut(
        subscription_id=subscription_id,
        resource_group=resource_group,
        resources=resources,
    )


# ---------------------------------------------------------------------------
# Tool 3 — get_resource_metadata  (S63)
# ---------------------------------------------------------------------------


def _parse_resource_id(resource_id: str) -> tuple[str, str, str, str]:
    """Parse an ARM resource_id into (subscription_id, resource_group, namespace, type_path).

    ARM resource IDs follow the shape
        /subscriptions/<sub>/resourceGroups/<rg>/providers/<ns>/<type>/<name>[/<subtype>/<subname>...]
    Nested child types use alternating type/name pairs after the provider
    namespace; we collapse those back into a slash-joined type path
    (e.g. `sites/slots`) which is the shape Azure expects when looking up
    `api_versions` on the provider.

    Raises ValueError on any shape mismatch — the orchestration loop catches
    it and surfaces it back to the model as a typed tool_result error so the
    model can self-correct (e.g. fix a malformed id from a prior turn).
    """
    parts = resource_id.strip("/").split("/")
    if (
        len(parts) < 8
        or parts[0].lower() != "subscriptions"
        or parts[2].lower() != "resourcegroups"
        or parts[4].lower() != "providers"
    ):
        raise ValueError(
            f"Malformed resource_id: {resource_id!r}. Expected "
            "/subscriptions/<sub>/resourceGroups/<rg>/providers/<ns>/<type>/<name>"
        )
    subscription_id = parts[1]
    resource_group = parts[3]
    namespace = parts[5]
    # parts[6:] alternates type, name, type, name, ... — take every other.
    type_parts = parts[6:]
    if len(type_parts) % 2 != 0:
        raise ValueError(
            f"Malformed resource_id: {resource_id!r}. Type/name segments are unpaired."
        )
    type_path = "/".join(type_parts[::2])
    return subscription_id, resource_group, namespace, type_path


@signallayer.policy_gate(action="tool_invoke")
async def get_resource_metadata(
    credential: _Cred,
    resource_id: str,
    *,
    tool_name: str = "get_resource_metadata",
    workload_id: str = "azure-architect",
) -> ResourceMetadata:
    """Fetch detailed metadata for one Azure resource by full ARM id.

    Wraps `ResourceManagementClient.resources.get_by_id`. ARM requires an
    explicit `api_version` per resource type (the polymorphic `properties`
    blob is api-version-pinned), so this tool does a two-step:

      1. Parse the resource_id to extract namespace + type_path.
      2. Call `providers.get(namespace)` to discover available api_versions
         for that type and pick the newest.
      3. Call `resources.get_by_id(resource_id, api_version=<latest>)`.

    The extra round-trip is acceptable for an audit tool. The `properties`
    dict is returned verbatim — the per-resource WAF synthesis (or a
    downstream Haiku summarizer) is responsible for normalising it.

    Multi-turn chaining contract: the model gets resource ids from
    `list_resources_in_group`, then calls THIS tool with one id to drill
    into a specific resource (storage tier, app service SKU, vault
    soft-delete, etc.). Canonical three-step audit pattern:
        list_resource_groups → list_resources_in_group → get_resource_metadata.

    Args:
        credential: Azure credential injected at agent startup.
        resource_id: Full ARM resource ID. Must begin with `/subscriptions/`.
        tool_name: Identity for the policy engine. DO NOT override at call
            site — it is the contract key used by rego Rule 1 (allowlist)
            and Rule 2 (mutation-verb prefix). Default matches function name.
        workload_id: Workload identity for policy + audit attribution.

    Returns:
        Strict ResourceMetadata (pydantic v2, frozen, extra="forbid").

    Raises:
        signallayer.PolicyDeniedError: If rego denies the call.
        ValueError: If `resource_id` is malformed or its provider type has
            no published api_versions.
        RuntimeError: If azure-mgmt-resource is not installed.
        azure.core.exceptions.ResourceNotFoundError: If the resource_id
            does not resolve. Surfaced to the model as a typed tool_result
            error by the orchestration loop.
    """
    try:
        from azure.mgmt.resource import ResourceManagementClient
    except ImportError as exc:
        raise RuntimeError(
            "azure-mgmt-resource not installed. Run "
            "`pip install azure-mgmt-resource azure-identity` before "
            "invoking ARM read tools."
        ) from exc

    subscription_id, resource_group, namespace, type_path = _parse_resource_id(
        resource_id
    )

    def _call_sync() -> ResourceMetadata:
        client = ResourceManagementClient(credential, subscription_id)

        # Discover the latest api_version for this resource type. ARM lists
        # newest-first in `api_versions`, but we also filter out preview
        # tags when a stable one exists — preview api_versions can mutate
        # `properties` shape without warning and aren't safe for audit.
        provider = client.providers.get(namespace)
        api_version: str | None = None
        for rt in (provider.resource_types or []):
            if (rt.resource_type or "").lower() == type_path.lower():
                versions = list(rt.api_versions or [])
                stable = [v for v in versions if "preview" not in v.lower()]
                api_version = (stable or versions or [None])[0]
                break
        if not api_version:
            raise ValueError(
                f"No api_version found for {namespace}/{type_path}. "
                "Resource type may be retired or not registered in this subscription."
            )

        resource = client.resources.get_by_id(resource_id, api_version=api_version)

        # `resource.properties` is the polymorphic blob; coerce to dict so
        # pydantic's ConfigDict(extra='forbid') doesn't choke on an SDK
        # model object. ARM returns plain dicts in modern SDK versions, but
        # some sub-resources still hand back typed objects.
        props_raw = getattr(resource, "properties", None) or {}
        if isinstance(props_raw, dict):
            properties = dict(props_raw)
        else:
            # Best-effort serialise SDK objects; falls back to empty rather
            # than raising, because a missing properties blob is a finding,
            # not a tool failure.
            try:
                properties = dict(props_raw.__dict__)
            except (AttributeError, TypeError):
                properties = {}

        sku_val: str | None = None
        sku_obj = getattr(resource, "sku", None)
        if sku_obj is not None:
            sku_val = getattr(sku_obj, "name", None) or None

        return ResourceMetadata(
            id=resource.id or resource_id,
            name=resource.name or "",
            type=resource.type or f"{namespace}/{type_path}",
            location=resource.location or "",
            resource_group=resource_group,
            sku=sku_val,
            tags=dict(resource.tags or {}),
            properties=properties,
        )

    return await asyncio.to_thread(_call_sync)


# ---------------------------------------------------------------------------
# Tool 4 — list_role_assignments
# ---------------------------------------------------------------------------


async def list_role_assignments(
    credential: _Cred, scope: str
) -> RoleAssignmentsListOut:
    """List RBAC role assignments at the given scope.

    Wraps `azure.mgmt.authorization.AuthorizationManagementClient.role_assignments.list_for_scope`.

    Args:
        credential: Azure credential.
        scope: ARM scope string — subscription, RG, or individual resource ID.

    Returns:
        Strict RoleAssignmentsListOut. Includes inherited assignments by
        default — exclude inheriting parent scopes when summarizing the
        access matrix to avoid double-counting.
    """
    raise NotImplementedError("P4 Day-1 — wrap AuthorizationManagementClient.role_assignments")


# ---------------------------------------------------------------------------
# Tool 5 — get_network_topology
# ---------------------------------------------------------------------------


async def get_network_topology(
    credential: _Cred, subscription_id: str
) -> NetworkTopologyOut:
    """Walk VNets, peerings, and private endpoints in a subscription.

    Wraps:
        - `azure.mgmt.network.NetworkManagementClient.virtual_networks.list_all`
        - `...virtual_network_peerings.list` (per VNet, batched via asyncio.gather)
        - `...private_endpoints.list_by_subscription`

    Args:
        credential: Azure credential.
        subscription_id: Target subscription GUID.

    Returns:
        Strict NetworkTopologyOut.
    """
    raise NotImplementedError("P4 Day-1 — wrap NetworkManagementClient (3 sub-calls, parallelize)")
