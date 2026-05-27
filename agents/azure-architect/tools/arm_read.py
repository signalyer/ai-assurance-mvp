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
# Tool 3 — get_resource_metadata
# ---------------------------------------------------------------------------


async def get_resource_metadata(
    credential: _Cred, resource_id: str
) -> ResourceMetadata:
    """Fetch detailed metadata for one Azure resource.

    Wraps `azure.mgmt.resource.ResourceManagementClient.resources.get_by_id`.

    Args:
        credential: Azure credential.
        resource_id: Full ARM resource ID
            (e.g. `/subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Web/sites/<name>`).

    Returns:
        Strict ResourceMetadata. The `properties` field is intentionally
        a polymorphic dict — schema varies per ARM resource type.

    Raises:
        ValueError: If `resource_id` is malformed.
    """
    raise NotImplementedError("P4 Day-1 — wrap ResourceManagementClient.resources.get_by_id")


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
